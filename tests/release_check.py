#!/usr/bin/env python3
"""The release gate: every download in dist/, checked the way a user would
meet it, on throwaway data, with nothing opening on the first screen.

    uv run --extra mcp --with cx_Freeze python build_release.py
    uv run python tests/release_check.py [--dist DIR] [--fixtures DIR]

One line per case, `[PASS] case`, `[FAIL] case: why` or `[SKIP] case: why`,
then a total and RELEASE CHECK PASSED / FAILED (exit 1). Cases:

* zips, build_commit -- the four zips and SHA256SUMS.txt; each exe names the
  commit at HEAD (a clean tree) and the source's version;
* signature -- SHA256SUMS.txt.sig, made by Vu with tools/sign_release.py, is
  accepted by each frozen build's own `ryos-cli verify` for its own zip, and
  refused when made with the test key or when SHA256SUMS.txt was changed;
* launch_* -- tests/launch_smoke.py on each built download (launch_visible
  on a second screen, when there is one);
* portable -- the source zip is exactly the tracked ryos/ at HEAD, and runs
  with uv: the command line and the window (run.bat);
* cli_management -- add, edit, presets, expose, run, timeouts, ambiguous
  names, a pipeline, history and remove, on RYOS Agent's ryos-cli.exe;
* mcp_* -- the MCP server over plain JSON-RPC: list, run, poll, stop, the
  refusals; and the build without agents refusing with 125;
* session_* -- tests/session_smoke.py in both layouts. It runs the window
  from source, which `portable` and `build_commit` prove is what the
  downloads hold: the frozen window is only started, never driven;
* fixture_upgrade_<name> -- a database from each past release (tests/fixtures/db)
  opened by the window and by RYOS Agent, with nothing lost;
* mixed_agent_first, mixed_app_first -- the same data used by RYOS Agent and
  the Windows builds, in both orders;
* newer_database_refused -- data a newer RYOS reshaped is refused by every
  download, and left byte for byte as it was;
* real_folder_untouched -- the user's own %APPDATA%/RYOS did not change.

Every process gets its own APPDATA under one temp folder, no run-at-login
writes, no toasts, no single-instance handoff and Qt's offscreen platform.
The temp folder is deleted when everything passed, and kept (its path
printed) when something failed.
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
ZIPS = {"RYOS-windows.zip": "windows", "RYOS-windows-ai.zip": "windows-ai",
        "RYOS-agent.zip": "agent", "RYOS-portable.zip": "portable"}
MCP_TOOLS = ["get_run", "list_pipelines", "list_scripts", "run_pipeline", "run_script",
             "stop_run"]
TABLES = ("groups", "scripts", "pipelines", "pipeline_steps", "script_param_presets",
          "runs", "schedules")
# The real environment, for the smokes this runs as subprocesses: each makes
# its own throwaway folder and checks the real one itself.
REAL_ENV = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
REAL_FOLDER = Path(os.environ.get("APPDATA") or Path.home() / ".local" / "share") / "RYOS"

HELLO = "import sys\nprint('hello', *sys.argv[1:], flush=True)\n"
FAIL = "import sys\nprint('about to fail', flush=True)\nsys.exit(3)\n"
SLOW = ("import time\nfor i in range(120):\n"
        "    print('tick', i, flush=True)\n    time.sleep(0.5)\n")


class Failed(Exception):
    pass


class Skipped(Exception):
    pass


def need(ok, why: str) -> None:
    if not ok:
        raise Failed(why)


class Check:
    def __init__(self, dist: Path, fixtures: Path, root: Path):
        self.dist, self.fixtures, self.root = dist, fixtures, root
        self.dirs: dict[str, Path] = {}
        self.results: list[tuple[str, str, str]] = []
        self._n = 0

    # -- set-up ------------------------------------------------------------
    def unzip(self) -> None:
        for name, variant in ZIPS.items():
            target = self.root / variant
            if (self.dist / name).exists():
                with zipfile.ZipFile(self.dist / name) as z:
                    z.extractall(target)
            self.dirs[variant] = target

    def exe(self, variant: str, name: str = "ryos-cli.exe") -> Path:
        return self.dirs[variant] / name

    def appdata(self, label: str) -> Path:
        """A fresh APPDATA; its RYOS folder already exists."""
        self._n += 1
        folder = self.root / "data" / f"{self._n:02d}-{label}"
        (folder / "RYOS").mkdir(parents=True)
        return folder

    @staticmethod
    def env(appdata: Path) -> dict:
        return dict(REAL_ENV, APPDATA=str(appdata),
                    LOCALAPPDATA=str(appdata / "local"), RYOS_NO_REGISTRY="1",
                    RYOS_NO_TOASTS="1", RYOS_ALLOW_MULTIPLE="1",
                    QT_QPA_PLATFORM="offscreen")

    @staticmethod
    def settle_settings(appdata: Path) -> None:
        """Before a window starts: no update check, and history kept for
        good (pruning at start-up would change the counts compared)."""
        path = appdata / "RYOS" / "settings.json"
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = {}
        stored.update(auto_check_update=False, history_retention_days=0,
                      open_on_cursor_monitor=False, start_minimized=False,
                      snap_corner="none")
        path.write_text(json.dumps(stored), encoding="utf-8")

    def run(self, cmd: list, appdata: Path, *args, timeout: float = 180):
        return launch_smoke.run_bounded([*cmd, *args], cwd=str(appdata),
                                        env=self.env(appdata), stdin=subprocess.DEVNULL,
                                        timeout=timeout)

    def cli(self, variant: str, appdata: Path, *args, timeout: float = 180):
        if variant == "portable":
            cmd = ["uv", "run", "--project", str(self.dirs["portable"]), "ryos"]
        else:
            cmd = [str(self.exe(variant))]
        return self.run(cmd, appdata, *args, timeout=timeout)

    def cli_json(self, variant: str, appdata: Path, *args):
        got = self.cli(variant, appdata, *args, "--json")
        try:
            return json.loads(got.stdout)
        except ValueError:
            raise Failed(f"{variant} ryos-cli {' '.join(args)} --json gave exit "
                         f"{got.returncode}: {got.stdout[-300:]!r} {got.stderr[-300:]!r}")

    def window(self, variant: str, appdata: Path) -> None:
        """Start the window on this data, wait for it, check its log, end it."""
        self.settle_settings(appdata)
        cmd = (["cmd", "/c", str(self.dirs["portable"] / "run.bat")] if variant == "portable"
               else [str(self.exe(variant, "RYOS.exe"))])
        problems, _log, output = launch_smoke.launch_window(
            cmd, appdata / "RYOS", self.env(appdata),
            wait_s=300 if variant == "portable" else launch_smoke.WAIT_S)
        need(not problems, f"the {variant} window: {'; '.join(problems)} {output[-300:]!r}")

    def scripts(self, appdata: Path) -> dict:
        folder = appdata / "scripts"
        folder.mkdir(exist_ok=True)
        files = {}
        for name, text in (("hello", HELLO), ("fail", FAIL), ("slow", SLOW),
                           ("secret", HELLO)):
            files[name] = folder / f"{name}.py"
            files[name].write_text(text, encoding="utf-8")
        return files

    # -- the cases ---------------------------------------------------------
    def case(self, name: str, fn, *args) -> None:
        start = time.monotonic()
        try:
            fn(*args)
            outcome, why = "PASS", ""
        except Skipped as e:
            outcome, why = "SKIP", str(e)
        except Failed as e:
            outcome, why = "FAIL", str(e)
        except Exception as e:                       # a crash in a case fails it
            outcome, why = "FAIL", f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        line = f"[{outcome}] {name}" + (f": {why}" if why else "")
        print(f"{line}  ({time.monotonic() - start:.0f}s)", flush=True)
        self.results.append((name, outcome, why))

    def zips(self) -> None:
        missing = [n for n in ZIPS if not (self.dist / n).exists()]
        need(not missing, f"missing {missing} in {self.dist}")
        sums_file = self.dist / "SHA256SUMS.txt"
        need(sums_file.exists(), "no SHA256SUMS.txt")
        sums = {}
        for line in sums_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                digest, name = line.split(None, 1)
                sums[name.strip().lstrip("*")] = digest
        need(sorted(sums) == sorted(ZIPS), f"SHA256SUMS.txt lists {sorted(sums)}")
        problems = []
        for name in ZIPS:
            data = (self.dist / name).read_bytes()
            if hashlib.sha256(data).hexdigest() != sums[name]:
                problems.append(f"{name}: its SHA-256 does not match SHA256SUMS.txt")
            with zipfile.ZipFile(self.dist / name) as z:
                entries = z.namelist()
            problems += [f"{name}: {p}" for p in build_release.problems_in(name, entries)]
            data = [e for e in entries
                    if e.rsplit("/", 1)[-1].lower() in ("scripts.db", "settings.json")]
            if data:
                problems.append(f"{name}: holds user data {data[:3]}")
        need(not problems, "; ".join(problems))

    def build_commit(self) -> None:
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
                               text=True).stdout.strip()
        head = subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True).stdout.strip()
        version = launch_smoke._source_version()
        problems = []
        if dirty:
            problems.append(f"the tree has uncommitted changes ({len(dirty.splitlines())} "
                            "paths): commit before building")
        for variant in ("windows", "windows-ai", "agent"):
            said = self.run([str(self.exe(variant)), "--version"],
                            self.appdata("version")).stdout.strip()
            if f"RYOS {version} (" not in said or not said.endswith(f", {head})"):
                problems.append(f"{variant} says {said!r}, not RYOS {version} at {head}")
        need(not problems, "; ".join(problems))

    def signature(self) -> None:
        sums = self.dist / "SHA256SUMS.txt"
        sig = self.dist / "SHA256SUMS.txt.sig"
        need(sig.exists(), "no SHA256SUMS.txt.sig in dist/: sign SHA256SUMS.txt with "
             "tools/sign_release.py after the build, before this check")
        by_variant = {variant: name for name, variant in ZIPS.items()}
        problems = []
        for variant in ("windows", "windows-ai", "agent"):
            zip_path = self.dist / by_variant[variant]
            got = self.cli(variant, self.appdata("verify"), "verify", str(zip_path))
            if got.returncode != 0:
                problems.append(f"{variant} refused {zip_path.name} (exit {got.returncode}): "
                                f"{(got.stdout + got.stderr)[-200:]!r}")
        need(not problems, "; ".join(problems))
        zip_path = self.dist / by_variant["agent"]
        version = launch_smoke._source_version()
        planted = {
            "signed with the test key": (
                sums.read_bytes(),
                ed25519_signer.sig_file(ed25519_signer.TEST_SEED, version, sums.read_bytes())),
            "changed": (sums.read_bytes().replace(b"0", b"1", 1), sig.read_bytes()),
        }
        for number, (what, (planted_sums, planted_sig)) in enumerate(planted.items()):
            folder = self.root / f"planted-{number}"
            folder.mkdir()
            try:
                os.link(zip_path, folder / zip_path.name)
            except OSError:
                shutil.copy2(zip_path, folder / zip_path.name)
            (folder / "SHA256SUMS.txt").write_bytes(planted_sums)
            (folder / "SHA256SUMS.txt.sig").write_bytes(planted_sig)
            got = self.cli("agent", self.appdata("planted"), "verify",
                           str(folder / zip_path.name))
            need(got.returncode == 125,
                 f"the agent build did not refuse a zip with SHA256SUMS.txt {what} "
                 f"(exit {got.returncode}): {(got.stdout + got.stderr)[-200:]!r}")

    def smoke(self, *args) -> None:
        got = launch_smoke.run_bounded([sys.executable, str(TESTS / "launch_smoke.py"), *args],
                                       cwd=str(ROOT), env=REAL_ENV, timeout=900)
        need(got.returncode == 0, f"launch_smoke {' '.join(args)}: "
                                  f"{(got.stdout + got.stderr)[-800:]}")

    def launch_visible(self) -> None:
        sys.path.insert(0, str(TESTS))
        from smoke_screen import _monitor_work_areas
        if len(_monitor_work_areas()) < 2:
            raise Skipped("one monitor")
        self.smoke("--exe", str(self.exe("windows-ai", "RYOS.exe")), "--visible")

    def portable(self) -> None:
        tracked = subprocess.run(["git", "ls-files", "ryos"], cwd=ROOT, capture_output=True,
                                 text=True).stdout.split()
        tracked = sorted(p for p in tracked if not p.endswith("_build_info.py"))
        with zipfile.ZipFile(self.dist / "RYOS-portable.zip") as z:
            entries = sorted(n for n in z.namelist() if n.startswith("ryos/"))
            need(entries == tracked,
                 f"the zip's ryos/ differs from git ls-files: extra "
                 f"{sorted(set(entries) - set(tracked))[:5]}, missing "
                 f"{sorted(set(tracked) - set(entries))[:5]}")
            changed = [n for n in entries if z.read(n) != (ROOT / n).read_bytes()]
        need(not changed, f"zipped files differ from the working tree: {changed[:5]}")
        if not shutil.which("uv"):
            raise Failed("uv is not on PATH")
        appdata = self.appdata("portable")
        problems: list = []
        launch_smoke._check_cli(["uv", "run", "--project", str(self.dirs["portable"]), "ryos"],
                                self.env(appdata), appdata / "RYOS", problems)
        need(not problems, "; ".join(problems))
        self.window("portable", appdata)

    def cli_management(self) -> None:
        a = self.appdata("cli")
        f = self.scripts(a)

        def ryos(*args, code=0, has=""):
            got = self.cli("agent", a, *args)
            need(got.returncode == code,
                 f"`ryos-cli {' '.join(args)}` gave exit {got.returncode}, not {code}: "
                 f"{got.stdout[-300:]!r} {got.stderr[-300:]!r}")
            need(has in got.stdout + got.stderr,
                 f"`ryos-cli {' '.join(args)}` did not say {has!r}: "
                 f"{got.stdout[-300:]!r} {got.stderr[-300:]!r}")
            return got

        def agents():
            return {s["ref"]: s["agents"] for s in self.cli_json("agent", a, "list")["scripts"]}

        def output(*args):
            got = self.cli_json("agent", a, "run", *args)
            need(got.get("status") == "ok", f"run {args}: {got}")
            return " ".join(got.get("output", []))

        ryos("add", str(f["hello"]), "--group", "Check", "--params=a b", "--yes")
        need(agents() == {"Check/hello": False}, f"after add: {agents()}")
        ryos("add", str(f["slow"]), "--group", "Check", "--expose", "--yes")
        need(agents() == {"Check/hello": False, "Check/slow": True}, f"after add --expose: {agents()}")
        ryos("add", str(f["fail"]), "--group", "Check", "--yes")
        need("hello a b" in output("Check/hello"), "the added parameters were not passed")
        ryos("edit", "Check/hello", "--params=--x 1")
        need("--x 1" in output("Check/hello"), "edit --params did not reach the run")
        ryos("preset", "add", "Check/hello", "fast", "--params=--fast")
        need("--fast" in output("Check/hello", "--preset", "fast"), "the preset's parameters")
        ryos("preset", "remove", "Check/hello", "fast")
        ryos("run", "Check/hello", "--preset", "fast", code=125)
        ryos("expose", "Check/hello", "on", code=125, has="--yes")
        need(agents()["Check/hello"] is False, "expose without --yes changed it")
        ryos("expose", "Check/hello", "on", "--yes")
        need(agents()["Check/hello"] is True, "expose on --yes did not")
        ryos("expose", "--group", "Check", "off", "--yes")
        need(not any(agents().values()), f"expose --group off left {agents()}")
        ryos("run", "Check/fail", code=3)
        ryos("run", "Check/slow", "--timeout", "2", code=124)
        ryos("add", str(f["secret"]), "--name", "hello", "--group", "Other", "--yes")
        got = ryos("run", "hello", code=125)
        need("Check/hello" in got.stderr and "Other/hello" in got.stderr,
             f"the ambiguous name did not name both: {got.stderr[-300:]!r}")
        db = ScriptDB(a / "RYOS" / "scripts.db")
        hello = next(r[0] for r in db.list_all() if r[1] == "hello" and r[8] == "Check")
        both = db.create_pipeline("Both", "Check")
        db.add_pipeline_step(both, hello)
        db.add_pipeline_step(both, hello)
        got = self.cli_json("agent", a, "pipeline", "Check/Both")
        need(got.get("status") == "ok", f"pipeline Check/Both: {got}")
        rows = [r for r in self.cli_json("agent", a, "history", "Check/hello")
                if r["by"] == "cli"]
        need(len(rows) >= 3, f"history Check/hello has {len(rows)} rows by cli")
        ryos("remove", "Check/hello", code=125, has="--yes")
        need("Check/hello" in agents(), "remove without --yes removed it")
        ryos("remove", "Check/hello", "--yes")
        need("Check/hello" not in agents(), "remove --yes left it")

    def _seed_mcp(self, variant: str, a: Path) -> None:
        f = self.scripts(a)
        for name, expose in (("hello", True), ("slow", True), ("secret", False)):
            got = self.cli(variant, a, "add", str(f[name]), "--group", "MCP", "--yes",
                           *(["--expose"] if expose else []))
            need(got.returncode == 0, f"add {name}: {got.stderr[-300:]!r}")
        got = self.cli(variant, a, "preset", "add", "MCP/hello", "fast", "--params=--fast")
        need(got.returncode == 0, f"preset add: {got.stderr[-300:]!r}")
        db = ScriptDB(a / "RYOS" / "scripts.db")
        hello = next(r[0] for r in db.list_all() if r[1] == "hello")
        both = db.create_pipeline("Both", "MCP")
        db.add_pipeline_step(both, hello)
        db.add_pipeline_step(both, hello)
        got = self.cli(variant, a, "expose", "MCP/Both", "on", "--pipeline", "--yes")
        need(got.returncode == 0, f"expose the pipeline: {got.stderr[-300:]!r}")

    @staticmethod
    def _until_done(client, run_id: int, budget: float = 120):
        offset, lines = 0, []
        deadline = time.time() + budget
        while time.time() < deadline:
            got, err = client.call("get_run", {"run_id": run_id, "offset": offset,
                                               "wait_seconds": 30}, timeout=90)
            need(not err and isinstance(got, dict), f"get_run {run_id}: {got!r}")
            lines += got["lines"]
            offset = got["next_offset"]
            if got["done"]:
                return got, lines
        raise Failed(f"run {run_id} was not done within {budget:g}s")

    def mcp(self, variant: str) -> None:
        a = self.appdata(f"mcp-{variant}")
        self._seed_mcp(variant, a)
        version = launch_smoke._source_version()
        client = launch_smoke.McpClient([str(self.exe(variant)), "mcp"], self.env(a))
        exited = None
        try:
            info = client.initialize().get("result", {}).get("serverInfo", {})
            need(info.get("name") == "RYOS" and info.get("version") == version,
                 f"serverInfo {info}, not RYOS {version}")
            need(client.tools() == MCP_TOOLS, f"tools {client.tools()}")
            scripts, err = client.call("list_scripts")
            refs = sorted(s["ref"] for s in scripts) if not err else scripts
            need(refs == ["MCP/hello", "MCP/slow"], f"list_scripts {refs}")
            pipes, err = client.call("list_pipelines")
            need(not err and [p["ref"] for p in pipes] == ["MCP/Both"], f"list_pipelines {pipes}")
            started, err = client.call("run_script", {"script": "MCP/hello"})
            need(not err, f"run_script hello: {started}")
            done, lines = self._until_done(client, started["run_id"])
            need(done["status"] == "ok" and any("hello" in x for x in lines),
                 f"hello ended {done['status']} with {lines[-5:]}")
            started, err = client.call("run_script", {"script": "MCP/hello", "preset": "fast"})
            need(not err, f"run_script hello fast: {started}")
            done, lines = self._until_done(client, started["run_id"])
            need(done["status"] == "ok" and any("--fast" in x for x in lines),
                 f"hello with its preset ended {done['status']} with {lines[-5:]}")
            refused, err = client.call("run_script", {"script": "MCP/secret"})
            need(err and isinstance(refused, str) and refused.strip(),
                 f"run_script secret was not refused readably: {refused!r}")
            started, err = client.call("run_pipeline", {"pipeline": "MCP/Both"})
            need(not err, f"run_pipeline Both: {started}")
            done, _lines = self._until_done(client, started["run_id"])
            need(done["status"] == "ok", f"the pipeline ended {done['status']}")
            started, err = client.call("run_script", {"script": "MCP/slow"})
            need(not err, f"run_script slow: {started}")
            got, err = client.call("get_run", {"run_id": started["run_id"],
                                               "wait_seconds": 10}, timeout=60)
            need(not err and any("tick" in x for x in got.get("lines", [])),
                 f"slow showed no ticks: {got!r}")
            _stopped, err = client.call("stop_run", {"run_id": started["run_id"]})
            need(not err, f"stop_run: {_stopped}")
            done, _lines = self._until_done(client, started["run_id"], budget=60)
            need(done["status"] == "stopped", f"slow ended {done['status']}, not stopped")
        finally:
            exited = client.close(timeout=15)
        need(exited, "the server did not exit within 15 s of stdin closing")
        rows = self.cli_json(variant, a, "history", "--limit", "100")
        by_agent = {r["name"] for r in rows if r["by"] == "agent"}
        need({"hello", "Both", "slow"} <= by_agent, f"history by agent names {by_agent}")

    def mcp_windows(self) -> None:
        a = self.appdata("mcp-windows")
        got = self.cli("windows", a, "mcp")
        need(got.returncode == 125, f"windows ryos-cli mcp gave exit {got.returncode}")

    def session(self, layout: str) -> None:
        got = launch_smoke.run_bounded(
            [sys.executable, str(TESTS / "session_smoke.py"), "--layout", layout],
            cwd=str(ROOT), env=REAL_ENV, timeout=1800)
        need(got.returncode == 0, f"session_smoke --layout {layout}: "
                                  f"{(got.stdout + got.stderr)[-800:]}")

    def fixture_upgrade(self, fixture: Path) -> None:
        names = None
        for first in ("window", "agent"):
            a = self.appdata(f"fixture-{fixture.stem}-{first}")
            db_path = a / "RYOS" / "scripts.db"
            shutil.copyfile(fixture, db_path)
            before = counts(db_path)
            with closing(sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)) as c:
                names = sorted(r[0] for r in c.execute("SELECT name FROM scripts"))
            if first == "window":
                self.window("windows-ai", a)
                listing = self.cli_json("windows-ai", a, "list")
            else:
                listing = self.cli_json("agent", a, "list")
            after = counts(db_path)
            need(after.pop("user_version") == SCHEMA_VERSION,
                 f"{first} first: the database is not at schema {SCHEMA_VERSION}")
            before.pop("user_version")
            before.setdefault("exposed", 0)
            need(after == before, f"{first} first: {before} became {after}")
            listed = sorted(s["name"] for s in listing["scripts"])
            need(listed == names, f"{first} first: lists {listed}, not {names}")

    def _same(self, a: Path, variant: str, want: tuple, when: str) -> None:
        got = self.state(variant, a)
        need(got == want, f"{when}: {got} is not {want}")

    def state(self, variant: str, a: Path) -> tuple:
        listing = self.cli_json(variant, a, "list")
        history = self.cli_json(variant, a, "history", "--limit", "200")
        raw = counts(a / "RYOS" / "scripts.db")
        raw.pop("user_version")
        return (listing, [(h["id"], h["by"], h["status"]) for h in history], raw)

    def _use(self, variant: str, a: Path) -> None:
        f = self.scripts(a)
        for args in (("add", str(f["hello"]), "--group", "Mix", "--yes"),
                     ("add", str(f["fail"]), "--group", "Mix", "--yes"),
                     ("expose", "Mix/hello", "on", "--yes"),
                     ("preset", "add", "Mix/hello", "fast", "--params=--fast"),
                     ("run", "Mix/hello", "--preset", "fast")):
            got = self.cli(variant, a, *args)
            need(got.returncode == 0, f"{variant} ryos-cli {args[0]}: {got.stderr[-300:]!r}")

    def mixed_agent_first(self) -> None:
        a = self.appdata("mixed-agent")
        self._use("agent", a)
        want = self.state("agent", a)
        need(want[2].get("exposed") == 1, f"nothing exposed: {want[2]}")
        self.window("windows", a)
        self._same(a, "agent", want, "after the build without agents")
        self.window("windows-ai", a)
        self._same(a, "windows-ai", want, "after the build with agents")

    def mixed_app_first(self) -> None:
        a = self.appdata("mixed-app")
        self.window("windows-ai", a)
        self._use("windows-ai", a)
        want = self.state("windows-ai", a)
        self._same(a, "agent", want, "RYOS Agent after the window")
        client = launch_smoke.McpClient([str(self.exe("agent")), "mcp"], self.env(a))
        try:
            client.initialize()
            scripts, err = client.call("list_scripts")
        finally:
            client.close()
        need(not err and [s["ref"] for s in scripts] == ["Mix/hello"],
             f"RYOS Agent's MCP lists {scripts}")

    def newer_database_refused(self) -> None:
        a = self.appdata("newer")
        got = self.cli("agent", a, "list")
        need(got.returncode == 0, "could not make the database")
        db_path = a / "RYOS" / "scripts.db"
        with closing(sqlite3.connect(db_path)) as conn:
            conn.execute("UPDATE meta SET value='99' WHERE key='compatible_from'")
            conn.commit()
        before = db_path.read_bytes()
        problems = []

        def unchanged(what):
            if db_path.read_bytes() != before:
                problems.append(f"{what} changed the file")

        for variant in ("windows", "windows-ai", "agent", "portable"):
            got = self.cli(variant, a, "list", timeout=600)
            if got.returncode != 125 or "newer RYOS" not in got.stderr:
                problems.append(f"{variant} list gave exit {got.returncode}: {got.stderr[-200:]!r}")
            unchanged(f"{variant} list")
        for variant in ("windows-ai", "agent"):
            got = self.cli(variant, a, "mcp")
            if got.returncode != 125:
                problems.append(f"{variant} mcp gave exit {got.returncode}")
            unchanged(f"{variant} mcp")
        for variant in ("windows", "windows-ai"):
            self.settle_settings(a)
            logs = a / "RYOS" / "logs"
            shutil.rmtree(logs, ignore_errors=True)
            proc = subprocess.Popen([str(self.exe(variant, "RYOS.exe"))], cwd=str(a),
                                    env=self.env(a), stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
            text = ""
            try:
                deadline = time.time() + 30
                while time.time() < deadline:
                    text = "".join(p.read_text(encoding="utf-8", errors="replace")
                                   for p in sorted(logs.rglob("*.log")))
                    if "Refused to open the data" in text or proc.poll() is not None:
                        break
                    time.sleep(0.5)
            finally:
                launch_smoke.kill_tree(proc)
            if "Refused to open the data" not in text or "Window shown" in text:
                problems.append(f"the {variant} window did not log the refusal: {text[-300:]!r}")
            unchanged(f"the {variant} window")
        need(not problems, "; ".join(problems))

    def real_folder_untouched(self, before: dict) -> None:
        after = launch_smoke._snapshot(REAL_FOLDER)
        changed = sorted(set(after.items()) ^ set(before.items()))
        need(not changed, f"changed: {changed[:5]}")


def counts(path: Path) -> dict:
    """Rows per table and items an agent may run, read without upgrading."""
    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        found = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                 for t in TABLES if t in tables}
        if "agent_exposed" in [r[1] for r in conn.execute("PRAGMA table_info(scripts)")]:
            found["exposed"] = sum(conn.execute(
                f"SELECT COUNT(*) FROM {t} WHERE agent_exposed=1").fetchone()[0]
                for t in ("scripts", "pipelines"))
        found["user_version"] = conn.execute("PRAGMA user_version").fetchone()[0]
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dist", default=str(ROOT / "dist"))
    parser.add_argument("--fixtures", default=str(TESTS / "fixtures" / "db"))
    args = parser.parse_args()

    real_before = launch_smoke._snapshot(REAL_FOLDER)
    root = Path(tempfile.mkdtemp(prefix="ryos-release-check-"))
    check = Check(Path(args.dist).resolve(), Path(args.fixtures).resolve(), root)
    print(f"RYOS release check: {check.dist}\n  (throwaway data in {root})", flush=True)
    check.unzip()

    check.case("zips", check.zips)
    check.case("build_commit", check.build_commit)
    check.case("signature", check.signature)
    check.case("launch_windows", check.smoke, "--exe", str(check.exe("windows", "RYOS.exe")))
    check.case("launch_windows_ai", check.smoke, "--exe",
               str(check.exe("windows-ai", "RYOS.exe")))
    check.case("launch_agent", check.smoke, "--cli-only", str(check.exe("agent")))
    check.case("launch_visible", check.launch_visible)
    check.case("portable", check.portable)
    check.case("cli_management", check.cli_management)
    check.case("mcp_windows_ai", check.mcp, "windows-ai")
    check.case("mcp_agent", check.mcp, "agent")
    check.case("mcp_windows", check.mcp_windows)
    check.case("session_normal", check.session, "normal")
    check.case("session_compact", check.session, "compact")
    for fixture in sorted(check.fixtures.glob("*.db")):
        check.case(f"fixture_upgrade_{fixture.stem}", check.fixture_upgrade, fixture)
    check.case("mixed_agent_first", check.mixed_agent_first)
    check.case("mixed_app_first", check.mixed_app_first)
    check.case("newer_database_refused", check.newer_database_refused)
    check.case("real_folder_untouched", check.real_folder_untouched, real_before)

    tally = {k: sum(1 for _n, o, _w in check.results if o == k) for k in ("PASS", "FAIL", "SKIP")}
    print("\nThe session cases ran the window from source; build_commit and portable "
          "show that source is what these zips hold.")
    print(f"release_check: {tally['PASS']} passed, {tally['FAIL']} failed, "
          f"{tally['SKIP']} skipped")
    if tally["FAIL"]:
        print(f"(throwaway data kept in {root})\n\nRELEASE CHECK FAILED")
        return 1
    shutil.rmtree(root, ignore_errors=True)
    print("\nRELEASE CHECK PASSED")
    return 0


# Before anything imports ryos: its settings module makes the data folder
# under APPDATA, and this process's own must be a throwaway one too.
SELF_APPDATA = tempfile.mkdtemp(prefix="ryos-release-check-self-")
os.environ["APPDATA"] = SELF_APPDATA
os.environ["LOCALAPPDATA"] = os.path.join(SELF_APPDATA, "local")
atexit.register(shutil.rmtree, SELF_APPDATA, ignore_errors=True)
sys.path[:0] = [str(ROOT), str(TESTS)]
import build_release  # noqa: E402
import ed25519_signer  # noqa: E402
import launch_smoke  # noqa: E402
from ryos.db import SCHEMA_VERSION, ScriptDB  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
