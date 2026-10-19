#!/usr/bin/env python3
"""The release gate: every download in dist/, checked the way a user would
meet it, on throwaway data, with nothing opening on the first screen.

    uv run --extra mcp --with cx_Freeze python build_release.py
    uv run python tests/release_check.py [--dist DIR] [--fixtures DIR]

One line per case, `[PASS] case`, `[FAIL] case: why` or `[SKIP] case: why`,
then a total and RELEASE CHECK PASSED / FAILED (exit 1). Cases:

* zips, build_commit -- the four zips and SHA256SUMS.txt; each frozen zip
  trusts the release key and is no test build; each exe names the commit at
  HEAD (a clean tree) and the source's version;
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
* self_update_<variant> -- a copy of each frozen download, marked as a test
  build that trusts the RFC 8032 test key (never the release key), updates
  itself from a release served on 127.0.0.1 and rolls back: an unsigned or
  wrongly signed release is refused, a helper killed mid-swap and a file
  held open leave the old build whole, and after the swap ryos-cli, MCP and
  the window answer from the same path with the data as it was;
* self_update_newer_database -- update and roll back leave data a newer RYOS
  reshaped byte for byte, and the roll back warns;
* self_update_portable -- the source refuses to update itself and keeps
  today's notice, and ignores the test source;
* shipped_builds_ignore_the_test_source -- the builds in dist/ never read
  RYOS_TEST_RELEASES_API;
* real_folder_untouched -- the user's own %APPDATA%/RYOS and
  %LOCALAPPDATA%/RYOS/updates did not change.

Every process gets its own APPDATA under one temp folder, no run-at-login
writes, no toasts, no single-instance handoff and Qt's offscreen platform.
The temp folder is deleted when everything passed, and kept (its path
printed) when something failed.
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import importlib.util
import json
import os
import py_compile
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import zipfile
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

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
REAL_UPDATES = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache") / "RYOS" / "updates"

UPDATE_TAG = "v99.0.0"
MARKER = "release-check-update.txt"
LOCKED = "icon.ico"
DEAD_PROXY = "http://127.0.0.1:9"
FROZEN = ("windows", "windows-ai", "agent")
SIBLINGS = (".previous", ".incoming", ".incoming.part", ".outgoing")

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


class _ReleaseHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, data) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        srv = self.server
        srv.seen.append(self.path)
        if self.path == "/releases/latest":
            if srv.release is None:
                self.send_error(404)
            else:
                self._json(srv.release)
            return
        if self.path == "/releases":
            self._json([] if srv.release is None else [srv.release])
            return
        name = self.path[len("/download/"):] if self.path.startswith("/download/") else None
        path = srv.files.get(name) if name else None
        if path is None:
            self.send_error(404)
            return
        size = path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        with open(path, "rb") as f:
            shutil.copyfileobj(f, self.wfile, 1 << 20)


class ReleaseServer(ThreadingHTTPServer):
    """A GitHub-shaped release source on 127.0.0.1, for the test builds."""
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _ReleaseHandler)
        self.release: dict | None = None
        self.files: dict[str, Path] = {}
        self.seen: list[str] = []

    def shutdown_request(self, request):
        try:
            request.settimeout(120)
            while request.recv(4096):
                pass
        except OSError:
            pass
        self.close_request(request)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class Check:
    def __init__(self, dist: Path, fixtures: Path, root: Path):
        self.dist, self.fixtures, self.root = dist, fixtures, root
        self.dirs: dict[str, Path] = {}
        self.results: list[tuple[str, str, str]] = []
        self._n = 0
        self.server: ReleaseServer | None = None
        self._test_builds: dict[str, Path] = {}
        self._served: dict[str, Path] = {}

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
    def env(appdata: Path, **extra) -> dict:
        return dict(REAL_ENV, APPDATA=str(appdata),
                    LOCALAPPDATA=str(appdata / "local"), RYOS_NO_REGISTRY="1",
                    RYOS_NO_TOASTS="1", RYOS_ALLOW_MULTIPLE="1",
                    QT_QPA_PLATFORM="offscreen", **extra)

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

    def run(self, cmd: list, appdata: Path, *args, timeout: float = 180,
            extra_env: dict | None = None):
        return launch_smoke.run_bounded([*cmd, *args], cwd=str(appdata),
                                        env=self.env(appdata, **(extra_env or {})),
                                        stdin=subprocess.DEVNULL, timeout=timeout)

    def cli(self, variant: str, appdata: Path, *args, timeout: float = 180,
            exe: Path | None = None, extra_env: dict | None = None):
        if exe is not None:
            cmd = [str(exe)]
        elif variant == "portable":
            cmd = ["uv", "run", "--project", str(self.dirs["portable"]), "ryos"]
        else:
            cmd = [str(self.exe(variant))]
        return self.run(cmd, appdata, *args, timeout=timeout, extra_env=extra_env)

    def cli_json(self, variant: str, appdata: Path, *args, exe: Path | None = None,
                 extra_env: dict | None = None):
        got = self.cli(variant, appdata, *args, "--json", exe=exe, extra_env=extra_env)
        try:
            return json.loads(got.stdout)
        except ValueError:
            raise Failed(f"{variant} ryos-cli {' '.join(args)} --json gave exit "
                         f"{got.returncode}: {got.stdout[-300:]!r} {got.stderr[-300:]!r}")

    def window(self, variant: str, appdata: Path, exe: Path | None = None,
               extra_env: dict | None = None) -> None:
        """Start the window on this data, wait for it, check its log, end it."""
        self.settle_settings(appdata)
        if exe is not None:
            cmd = [str(exe)]
        elif variant == "portable":
            cmd = ["cmd", "/c", str(self.dirs["portable"] / "run.bat")]
        else:
            cmd = [str(self.exe(variant, "RYOS.exe"))]
        problems, _log, output = launch_smoke.launch_window(
            cmd, appdata / "RYOS", self.env(appdata, **(extra_env or {})),
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
                problems += [f"{name}: {p}"
                             for p in build_release.release_key_problems(name, z.read)]
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

    def state(self, variant: str, a: Path, exe: Path | None = None,
              extra_env: dict | None = None) -> tuple:
        listing = self.cli_json(variant, a, "list", exe=exe, extra_env=extra_env)
        history = self.cli_json(variant, a, "history", "--limit", "200", exe=exe,
                                extra_env=extra_env)
        raw = counts(a / "RYOS" / "scripts.db")
        raw.pop("user_version")
        return (listing, [(h["id"], h["by"], h["status"]) for h in history], raw)

    def _use(self, variant: str, a: Path, exe: Path | None = None, group: str = "Mix",
             extra_env: dict | None = None) -> None:
        f = self.scripts(a)
        for args in (("add", str(f["hello"]), "--group", group, "--yes"),
                     ("add", str(f["fail"]), "--group", group, "--yes"),
                     ("expose", f"{group}/hello", "on", "--yes"),
                     ("preset", "add", f"{group}/hello", "fast", "--params=--fast"),
                     ("run", f"{group}/hello", "--preset", "fast")):
            got = self.cli(variant, a, *args, exe=exe, extra_env=extra_env)
            need(got.returncode == 0, f"{variant} ryos-cli {args[0]}: {got.stderr[-300:]!r}")
        db = ScriptDB(a / "RYOS" / "scripts.db")
        hello = next(r[0] for r in db.list_all() if r[1] == "hello" and r[8] == group)
        both = db.create_pipeline("Both", group)
        db.add_pipeline_step(both, hello)
        db.add_pipeline_step(both, hello)
        got = self.cli(variant, a, "expose", f"{group}/Both", "on", "--pipeline", "--yes",
                       exe=exe, extra_env=extra_env)
        need(got.returncode == 0, f"{variant} expose the pipeline: {got.stderr[-300:]!r}")

    def mixed_agent_first(self) -> None:
        a = self.appdata("mixed-agent")
        self._use("agent", a)
        want = self.state("agent", a)
        need(want[2].get("exposed") == 2, f"not both exposed: {want[2]}")
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

    def test_build(self, variant: str) -> Path:
        """A copy of the shipped build whose _build_info.pyc marks it as a
        test build trusting the RFC 8032 test key."""
        if variant in self._test_builds:
            return self._test_builds[variant]
        target = self.root / "test-builds" / variant
        shutil.copytree(self.dirs[variant], target)
        pyc = target / build_release.BUILD_INFO_ENTRY
        need(pyc.is_file(), f"the {variant} build has no {build_release.BUILD_INFO_ENTRY}")
        need(pyc.read_bytes()[:4] == importlib.util.MAGIC_NUMBER,
             f"the {variant} build's Python differs from this one ({sys.version.split()[0]}), "
             "so its _build_info.pyc cannot be replaced: run release_check with the "
             "Python the build used")
        source = self.root / "test-builds" / f"_build_info-{variant}.py"
        source.write_text(buildinfo.build_info_source(
            variant, buildinfo.git_commit(ROOT), ed25519_signer.TEST_PUBLIC.hex(),
            test_updates=True), encoding="utf-8")
        pyc.unlink()
        py_compile.compile(str(source), cfile=str(pyc), doraise=True)
        self._test_builds[variant] = target
        return target

    def served_zip(self, variant: str) -> Path:
        if variant in self._served:
            return self._served[variant]
        folder = self.root / "served"
        folder.mkdir(exist_ok=True)
        target = folder / buildinfo.download_name(variant)
        build_release.zip_folder(self.test_build(variant), target)
        with zipfile.ZipFile(target, "a", zipfile.ZIP_DEFLATED) as z:
            z.writestr(MARKER, f"release_check's {UPDATE_TAG} of {variant}\n")
        self._served[variant] = target
        return target

    def publish(self, mode: str) -> None:
        """Serve UPDATE_TAG: 'signed' with the test key, 'unsigned' (no
        .sig) or signed with 'other-key'."""
        assert self.server is not None
        zips = {variant: self.served_zip(variant) for variant in FROZEN}
        sums = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
                       for p in zips.values()).encode("utf-8")
        folder = self.root / "served"
        (folder / "SHA256SUMS.txt").write_bytes(sums)
        files = {p.name: p for p in zips.values()}
        files["SHA256SUMS.txt"] = folder / "SHA256SUMS.txt"
        if mode != "unsigned":
            seed = ed25519_signer.TEST_SEED if mode == "signed" else ed25519_signer.OTHER_SEED
            sig = folder / "SHA256SUMS.txt.sig"
            sig.write_bytes(ed25519_signer.sig_file(seed, UPDATE_TAG.lstrip("v"), sums))
            files[sig.name] = sig
        base = self.server.base
        self.server.files = files
        self.server.release = {
            "tag_name": UPDATE_TAG, "html_url": f"{base}/release/{UPDATE_TAG}",
            "prerelease": False, "draft": False,
            "assets": [{"name": name, "size": path.stat().st_size,
                        "browser_download_url": f"{base}/download/{name}"}
                       for name, path in files.items()]}

    def install(self, variant: str, label: str) -> Path:
        self._n += 1
        target = self.root / "installs" / f"{self._n:02d}-{label}" / "RYOS"
        shutil.copytree(self.test_build(variant), target)
        return target

    def updating_env(self) -> dict:
        assert self.server is not None
        return {buildinfo.TEST_RELEASES_ENV: f"{self.server.base}/releases",
                "NO_PROXY": "127.0.0.1"}

    @staticmethod
    def updates_root(a: Path) -> Path:
        return a / "local" / "RYOS" / "updates"

    def journal(self, a: Path, install: Path) -> dict | None:
        """The install's journal, without its file list."""
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(a / "local")}):
            found = swap.read_journal(swap.journal_dir_for(install))
        return None if found is None else {k: v for k, v in found.items() if k != "files"}

    def helpers(self, a: Path) -> list:
        root = self.updates_root(a)
        return selfupdate.running_from(root) if root.is_dir() else []

    def await_helper(self, a: Path, install: Path, budget: float = 300) -> dict:
        deadline = time.time() + budget
        journal = None
        while time.time() < deadline:
            journal = self.journal(a, install)
            if (not self.helpers(a) and journal is not None
                    and journal["state"] in (swap.DONE, swap.UNDONE)):
                return journal
            time.sleep(0.5)
        raise Failed(f"the helper did not finish within {budget:g}s: {self.helpers(a)} "
                     f"still running, journal {journal}")

    def kill_helper(self, a: Path, install: Path, budget: float = 180) -> dict:
        deadline = time.time() + budget
        journal = None
        while time.time() < deadline:
            journal = self.journal(a, install)
            if journal is not None and journal["state"] == "swap":
                break
            time.sleep(0.25)
        else:
            raise Failed(f"the helper never reached the swap within {budget:g}s: {journal}")
        time.sleep(2)
        journal = self.journal(a, install)
        need(journal is not None and journal["state"] == "swap",
             f"the swap ended before the helper could be killed: {journal}")
        pid = journal["helper_pid"]
        need(pid in [p.pid for p in self.helpers(a)],
             f"the journal's helper (process {pid}) is not running from "
             f"{self.updates_root(a)}: {self.helpers(a)}")
        os.kill(pid, signal.SIGTERM)
        deadline = time.time() + 30
        while pid in [p.pid for p in self.helpers(a)]:
            need(time.time() < deadline, f"the helper (process {pid}) did not die")
            time.sleep(0.25)
        return journal

    @staticmethod
    def siblings(install: Path) -> list[str]:
        return [s for s in SIBLINGS if install.with_name(install.name + s).exists()]

    def self_update(self, variant: str) -> None:
        a = self.appdata(f"update-{variant}")
        install = self.install(variant, variant)
        icli = install / "ryos-cli.exe"
        extra = self.updating_env()
        name = buildinfo.download_name(variant)
        staged = self.updates_root(a) / UPDATE_TAG.lstrip("v") / name
        log = a / "RYOS" / "logs" / "ryos-cli.log"
        mcp = buildinfo.bundles_mcp(variant)

        def ryos(*args, code=0, has=()):
            got = self.cli(variant, a, *args, exe=icli, extra_env=extra, timeout=600)
            said = got.stdout + got.stderr
            need(got.returncode == code,
                 f"step {step}: `ryos-cli {' '.join(args)}` gave exit {got.returncode}, not "
                 f"{code}: {got.stdout[-400:]!r} {got.stderr[-400:]!r}")
            for words in ((has,) if isinstance(has, str) else has):
                need(words in said, f"step {step}: `ryos-cli {' '.join(args)}` did not say "
                                    f"{words!r}: {said[-400:]!r}")
            return got

        def state():
            return self.state(variant, a, exe=icli, extra_env=extra)

        def untouched(old_files):
            need(swap.tree_listing(install) == old_files,
                 f"step {step}: {install} changed")
            need(not self.siblings(install),
                 f"step {step}: {self.siblings(install)} beside {install}")

        def answers():
            ryos("--version", has=launch_smoke._source_version())

        def mcp_lists(want_refs, run_one=False):
            client = launch_smoke.McpClient([str(icli), "mcp"], self.env(a, **extra))
            try:
                info = client.initialize().get("result", {}).get("serverInfo", {})
                need(info.get("name") == "RYOS", f"step {step}: serverInfo {info}")
                need(client.tools() == MCP_TOOLS, f"step {step}: tools {client.tools()}")
                scripts, err = client.call("list_scripts")
                refs = sorted(s["ref"] for s in scripts) if not err else scripts
                need(refs == want_refs, f"step {step}: list_scripts {refs}")
                if run_one:
                    started, err = client.call("run_script", {"script": "Upd/hello"})
                    need(not err, f"step {step}: run_script Upd/hello: {started}")
                    done, _lines = self._until_done(client, started["run_id"])
                    need(done["status"] == "ok", f"step {step}: Upd/hello ended "
                                                 f"{done['status']}")
            finally:
                exited = client.close(timeout=15)
            need(exited, f"step {step}: the MCP server did not exit after stdin closed")

        step = 0
        self._use(variant, a, exe=icli, group="Upd", extra_env=extra)
        want = state()
        need(want[2].get("exposed") == 2, f"step 0: not both exposed: {want[2]}")
        old_files = swap.tree_listing(install)

        step = 1
        self.publish("unsigned")
        ryos("update", "--yes", code=1, has="SHA256SUMS.txt.sig")
        need(not staged.exists(), f"step 1: {staged} was downloaded")
        untouched(old_files)

        step = 2
        self.publish("other-key")
        ryos("update", "--yes", code=1, has="different key")
        need(not staged.exists(), f"step 2: {staged} was downloaded")
        untouched(old_files)

        step = 3
        self.publish("signed")
        ryos("version", "--check", has=(f"RYOS {UPDATE_TAG.lstrip('v')} is out",
                                        "Not downloaded yet."))

        step = 4
        with open(install / LOCKED, "rb"):
            ryos("update", "--yes", has=f"becomes {UPDATE_TAG.lstrip('v')} once this command ends")
            self.kill_helper(a, install)
            journal = self.journal(a, install)
            need(journal is not None and journal["state"] == "swap",
                 f"step 4: the journal after the kill: {journal}")
            need(install.with_name(install.name + ".incoming").is_dir(),
                 f"step 4: no {install.name}.incoming after the kill")
            need(not (install / MARKER).exists(), f"step 4: {MARKER} is in {install}")
            answers()
            need(state() == want, f"step 4: {state()} is not {want}")

            step = 5
            ryos("update", "--yes", has="becomes")
            journal = self.await_helper(a, install)
            message = str(journal.get("message"))
            need(journal["kind"] == swap.UPDATE and journal["state"] == swap.UNDONE,
                 f"step 5: the journal: {journal}")
            need(os.path.normcase(str(install)) in os.path.normcase(message)
                 and "antivirus" in message, f"step 5: the message: {message!r}")
            need("apply-update undone" in log.read_text(encoding="utf-8", errors="replace"),
                 f"step 5: {log} does not say `apply-update undone`")
            untouched(old_files)
            need(not (install / MARKER).exists(), f"step 5: {MARKER} is in {install}")
            answers()
            need(state() == want, f"step 5: {state()} is not {want}")

        step = 6
        ryos("version", "--check", has="is downloaded and checked")

        step = 7
        ryos("update", "--yes", has="becomes")
        journal = self.await_helper(a, install)
        need(journal["kind"] == swap.UPDATE and journal["state"] == swap.DONE
             and journal.get("version") == UPDATE_TAG, f"step 7: the journal: {journal}")
        previous = install.with_name(install.name + ".previous")
        need((install / MARKER).is_file(), f"step 7: no {MARKER} in {install}")
        need(previous.is_dir() and not (previous / MARKER).exists(),
             f"step 7: {previous} is not the old build")
        need(self.siblings(install) == [".previous"],
             f"step 7: {self.siblings(install)} beside {install}")
        need("apply-update done" in log.read_text(encoding="utf-8", errors="replace"),
             f"step 7: {log} does not say `apply-update done`")
        need(state() == want, f"step 7: {state()} is not {want}")
        ryos("run", "Upd/hello")
        if mcp:
            mcp_lists(["Upd/hello"], run_one=True)
        else:
            ryos("mcp", code=125)
        if variant != "agent":
            shutil.rmtree(a / "RYOS" / "logs", ignore_errors=True)
            self.window(variant, a, exe=install / "RYOS.exe", extra_env=extra)
        after = state()
        need(len(after[1]) > len(want[1]), f"step 7: the runs were not recorded: {after[1]}")

        step = 8
        ryos("update", "--rollback", "--yes", has="goes back to")
        journal = self.await_helper(a, install)
        need(journal["kind"] == swap.ROLLBACK and journal["state"] == swap.DONE,
             f"step 8: the journal: {journal}")
        need(not (install / MARKER).exists(), f"step 8: {MARKER} is still in {install}")
        need((previous / MARKER).is_file(), f"step 8: {previous} is not the updated build")
        need(self.siblings(install) == [".previous"],
             f"step 8: {self.siblings(install)} beside {install}")
        answers()
        need(state() == after, f"step 8: {state()} is not {after}")
        if mcp:
            mcp_lists(["Upd/hello"])

    def self_update_newer_database(self) -> None:
        a = self.appdata("update-newer")
        install = self.install("agent", "newer")
        icli = install / "ryos-cli.exe"
        extra = self.updating_env()
        self.publish("signed")
        self._use("agent", a, exe=icli, group="Upd", extra_env=extra)
        db_path = a / "RYOS" / "scripts.db"
        with closing(sqlite3.connect(db_path)) as conn:
            conn.execute("UPDATE meta SET value='99' WHERE key='compatible_from'")
            conn.commit()
        before = db_path.read_bytes()

        def ryos(*args):
            return self.cli("agent", a, *args, exe=icli, extra_env=extra, timeout=600)

        got = ryos("update", "--yes")
        need(got.returncode == 0, f"update gave exit {got.returncode}: {got.stderr[-400:]!r}")
        journal = self.await_helper(a, install)
        need(journal["state"] == swap.DONE, f"the update: {journal}")
        need(db_path.read_bytes() == before, "the update changed the database")
        got = ryos("update", "--rollback", "--yes")
        need(got.returncode == 0, f"update --rollback gave exit {got.returncode}: "
                                  f"{got.stderr[-400:]!r}")
        need("warning:" in got.stderr and "layout 99" in got.stderr,
             f"the roll back did not warn: {got.stderr[-400:]!r}")
        journal = self.await_helper(a, install)
        need(journal["kind"] == swap.ROLLBACK and journal["state"] == swap.DONE,
             f"the roll back: {journal}")
        need(db_path.read_bytes() == before, "the roll back changed the database")
        got = ryos("list")
        need(got.returncode == 125 and "newer RYOS" in got.stderr,
             f"list after the roll back gave exit {got.returncode}: {got.stderr[-300:]!r}")

    def self_update_portable(self) -> None:
        a = self.appdata("update-portable")
        for args in (("update", "--yes"), ("update", "--rollback", "--yes")):
            got = self.cli("portable", a, *args, timeout=600)
            need(got.returncode == 125 and "does not update itself" in got.stderr,
                 f"`ryos {' '.join(args)}` gave exit {got.returncode}: {got.stderr[-300:]!r}")
        python = ["uv", "run", "--project", str(self.dirs["portable"]), "python", "-c"]
        got = self.run([*python, "import sys; from ryos import cli; sys.exit(cli.main("
                        "['version', '--check'], fetch_release=lambda: "
                        f"({UPDATE_TAG!r}, 'http://127.0.0.1/page')))"], a, timeout=600)
        said = got.stdout
        need(got.returncode == 0 and f"RYOS {UPDATE_TAG.lstrip('v')} is out" in said
             and "RYOS-portable.zip" in said, f"version --check said {said[-400:]!r} "
                                              f"{got.stderr[-300:]!r}")
        need("Not downloaded yet" not in said and "downloaded and checked" not in said,
             f"version --check offered to update: {said[-400:]!r}")
        got = self.run([*python, "from ryos import buildinfo; "
                        "print(repr(buildinfo.test_releases_api()))"], a, timeout=600,
                       extra_env={buildinfo.TEST_RELEASES_ENV: "http://127.0.0.1:8123/releases"})
        need(got.stdout.strip() == "None",
             f"from source the test source is {got.stdout.strip()!r} {got.stderr[-300:]!r}")
        need(not self.updates_root(a).exists() or not any(self.updates_root(a).rglob("*")),
             f"something was put in {self.updates_root(a)}")

    def shipped_builds_ignore_the_test_source(self) -> None:
        assert self.server is not None
        self.publish("signed")
        self.server.seen.clear()
        extra = dict(self.updating_env(), HTTPS_PROXY=DEAD_PROXY, HTTP_PROXY=DEAD_PROXY)
        problems = []
        for variant in FROZEN:
            a = self.appdata(f"shipped-{variant}")
            for args, has in ((("version", "--check"), ""),
                              (("update", "--yes"), "Could not reach GitHub")):
                got = self.cli(variant, a, *args, extra_env=extra, timeout=300)
                if got.returncode != 1 or has not in got.stdout + got.stderr:
                    problems.append(f"{variant} `{' '.join(args)}` gave exit {got.returncode}: "
                                    f"{(got.stdout + got.stderr)[-300:]!r}")
            root = self.updates_root(a)
            if root.exists() and any(root.rglob("*")):
                problems.append(f"{variant} put something in {root}")
        if self.server.seen:
            problems.append(f"the test source was asked for {self.server.seen[:5]}")
        need(not problems, "; ".join(problems))

    def real_folder_untouched(self, before: dict, updates_before: dict) -> None:
        after = launch_smoke._snapshot(REAL_FOLDER)
        changed = sorted(set(after.items()) ^ set(before.items()))
        need(not changed, f"changed: {changed[:5]}")
        after = launch_smoke._snapshot(REAL_UPDATES)
        changed = sorted(set(after.items()) ^ set(updates_before.items()))
        need(not changed, f"{REAL_UPDATES} changed: {changed[:5]}")


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
    updates_before = launch_smoke._snapshot(REAL_UPDATES)
    root = Path(tempfile.mkdtemp(prefix="ryos-release-check-"))
    check = Check(Path(args.dist).resolve(), Path(args.fixtures).resolve(), root)
    print(f"RYOS release check: {check.dist}\n  (throwaway data in {root})", flush=True)
    check.unzip()
    check.server = ReleaseServer()
    threading.Thread(target=check.server.serve_forever, args=(0.1,), daemon=True).start()

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
    check.case("self_update_windows", check.self_update, "windows")
    check.case("self_update_windows_ai", check.self_update, "windows-ai")
    check.case("self_update_agent", check.self_update, "agent")
    check.case("self_update_newer_database", check.self_update_newer_database)
    check.case("self_update_portable", check.self_update_portable)
    check.case("shipped_builds_ignore_the_test_source",
               check.shipped_builds_ignore_the_test_source)
    check.case("real_folder_untouched", check.real_folder_untouched, real_before,
               updates_before)
    check.server.shutdown()
    check.server.server_close()

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
from ryos import buildinfo, selfupdate, swap  # noqa: E402
from ryos.db import SCHEMA_VERSION, ScriptDB  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
