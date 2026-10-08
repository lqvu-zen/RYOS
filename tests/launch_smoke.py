#!/usr/bin/env python3
"""Launch RYOS for real -- from source, or a built RYOS.exe -- and check it
starts, without touching the user's own RYOS.

    uv run python tests/launch_smoke.py                 # from source
    uv run python tests/launch_smoke.py --exe dist/cxfreeze/RYOS.exe
    ... --visible                                       # show the window

Everything that is not inside the process is kept away from the real thing:

* APPDATA points at a throwaway folder, so the database, settings, logs,
  themes and instance lock are all new and all thrown away;
* RYOS_NO_REGISTRY=1, so the run-at-login entry is never rewritten -- a build
  launched from dist/ would otherwise point it at itself;
* RYOS_NO_TOASTS=1, so nothing pops up on the screen in use;
* RYOS_ALLOW_MULTIPLE=1, so a running RYOS is neither signalled nor blocked;
* the Qt "offscreen" platform, so no window appears on any screen, unless
  --visible, which puts it on a second screen when there is one.

It waits for the app's "Window shown" log line, closes it, and fails if any
file in the user's real %APPDATA%/RYOS changed, or if the app does not log the
version in ryos/__init__.py -- a stale RYOS.exe left in dist/ would otherwise
pass.

Then the command line, in the same throwaway folder: `--version`, `list
--json` and a real `run --json` of a one-line script -- through ryos-cli.exe
beside a built RYOS.exe (a build without one fails), or `python -m ryos`.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WAIT_S = 90


def _source_version() -> str:
    text = (ROOT / "ryos" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def _snapshot(folder: Path) -> dict:
    if not folder.is_dir():
        return {}
    return {str(p): (p.stat().st_mtime_ns, p.stat().st_size)
            for p in folder.rglob("*") if p.is_file()}


def _second_screen_geometry():
    sys.path.insert(0, str(ROOT / "tests"))
    from smoke_screen import smoke_screen    # the same screen choice as the smokes
    area = smoke_screen()
    return f"540x640+{area[0] + 40}+{area[1] + 40}" if area else None


def _check_cli(cli: list, env: dict, data: Path, problems: list) -> str:
    """The command line against the throwaway folder; a line for the report."""
    def ryos(*args):
        return subprocess.run([*cli, *args], cwd=str(ROOT), env=env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=120)

    version = _source_version()
    got = ryos("--version")
    if f"RYOS {version}" not in got.stdout:
        problems.append(f"the CLI's --version said {got.stdout.strip()!r} "
                        f"(exit {got.returncode}), not RYOS {version}")
        return ""
    sys.path.insert(0, str(ROOT))
    from ryos.db import ScriptDB
    hello = data / "hello.py"
    hello.write_text("print('hello from the CLI')\n", encoding="utf-8")
    db = ScriptDB(data / "scripts.db")
    db.create_group("Smoke")
    db.add("hello", str(hello), "", sys.executable, "Smoke")
    listed = ryos("list", "--json")
    try:
        refs = [s["ref"] for s in json.loads(listed.stdout)["scripts"]]
    except (ValueError, KeyError):
        refs = None
    if refs != ["Smoke/hello"]:
        problems.append(f"the CLI's list said {listed.stdout[:200]!r} {listed.stderr[-300:]!r}")
    ran = ryos("run", "Smoke/hello", "--json", "--timeout", "60")
    try:
        result = json.loads(ran.stdout)
    except ValueError:
        result = {}
    if (ran.returncode != 0 or result.get("status") != "ok"
            or "hello from the CLI" not in result.get("output", [])):
        problems.append(f"the CLI's run gave exit {ran.returncode}: "
                        f"{ran.stdout[:300]!r} {ran.stderr[-300:]!r}")
    shown = Path(cli[0]).name if len(cli) == 1 else "python -m ryos"
    return f"  [ok] the command line ({shown}): --version, list, run"


def _check_mcp(exe: Path, env: dict, data: Path, problems: list) -> str:
    """`ryos-cli.exe mcp` from a build: initialize, the tool list and
    list_scripts, spoken as the protocol's newline-delimited JSON-RPC -- no
    SDK needed here, and none on the machine but the one inside the exe."""
    sys.path.insert(0, str(ROOT))
    from ryos.db import ScriptDB
    db = ScriptDB(data / "scripts.db")
    hello = next((r[0] for r in db.list_all() if r[1] == "hello"), None)
    if hello is not None:
        db.set_agent_exposed("script", hello, True)
    proc = subprocess.Popen([str(exe), "mcp"], cwd=str(ROOT), env=env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace")
    answers = {}

    def send(message):
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()

    def answer(want_id):
        deadline = time.time() + 60
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            got = json.loads(line)
            if got.get("id") == want_id:
                return got
        return {}
    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "launch-smoke", "version": "1"}}})
        answers["init"] = answer(1)
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        answers["tools"] = answer(2)
        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": "list_scripts", "arguments": {}}})
        answers["list"] = answer(3)
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
    info = answers["init"].get("result", {}).get("serverInfo", {})
    tools = sorted(t["name"] for t in answers["tools"].get("result", {}).get("tools", []))
    listed = json.dumps(answers["list"].get("result", {}))
    if info.get("name") != "RYOS" or info.get("version") != _source_version():
        problems.append(f"ryos-cli mcp did not start as RYOS {_source_version()}: "
                        f"{answers['init']!r} {proc.stderr.read()[-500:]!r}")
    elif "run_script" not in tools or "Smoke/hello" not in listed:
        problems.append(f"ryos-cli mcp tools {tools}, list_scripts {listed[:200]}")
    return f"  [ok] MCP from {exe.name} mcp: initialize, {len(tools)} tools, list_scripts"


def _check_mcp_or_its_absence(exe: Path, env: dict, data: Path, problems: list) -> str:
    """The Windows build with AI agents talks MCP; the one without says it
    has no MCP server and exits 125 (RYOS refused)."""
    version = subprocess.run([str(exe), "--version"], env=env, capture_output=True,
                             text=True, timeout=60).stdout
    if "with AI agents" in version:
        return _check_mcp(exe, env, data, problems)
    got = subprocess.run([str(exe), "mcp"], env=env, capture_output=True, text=True,
                         timeout=60, stdin=subprocess.DEVNULL)
    if got.returncode != 125 or "isn't included in this download" not in got.stderr:
        problems.append(f"ryos-cli mcp in the build without AI agents gave exit "
                        f"{got.returncode}: {got.stderr[-300:]!r}")
    return f"  [ok] {exe.name} mcp: not in this download, exit 125 (no MCP server here)"


def _agent_smoke(exe: Path) -> int:
    """RYOS Agent: ryos-cli.exe on its own -- it says so, carries no Qt and no
    window, and its command line and MCP server work against a throwaway
    folder."""
    real = Path(os.environ.get("APPDATA") or Path.home() / ".local" / "share") / "RYOS"
    before = _snapshot(real)
    tmp = Path(tempfile.mkdtemp(prefix="ryos-agent-"))
    data = tmp / "RYOS"
    data.mkdir()
    env = dict(os.environ, APPDATA=str(tmp), RYOS_NO_REGISTRY="1", RYOS_NO_TOASTS="1")
    print(f"RYOS agent smoke: {exe}\n  (data in {data}; registry writes off)")
    problems: list = []
    version = subprocess.run([str(exe), "--version"], env=env, capture_output=True,
                             text=True, timeout=60).stdout.strip()
    if version != f"RYOS {_source_version()} (RYOS Agent)":
        problems.append(f"--version said {version!r}, not RYOS {_source_version()} (RYOS Agent)")
    qt = [p.name for p in exe.parent.rglob("*")
          if p.name.lower().startswith(("qt6", "pyside6", "shiboken6"))]
    if qt:
        problems.append(f"the agent build carries Qt: {sorted(set(qt))[:5]}")
    if (exe.parent / "RYOS.exe").exists() or (exe.parent / "lib" / "ryos" / "qtui").exists():
        problems.append("the agent build carries the window")
    report = _check_cli([str(exe)], env, data, problems)
    if not problems:
        report += "\n" + _check_mcp(exe, env, data, problems)
    if _snapshot(real) != before:
        problems.append("the real RYOS folder changed")
    if problems:
        print("\n".join(f"  PROBLEM: {p}" for p in problems))
        print("\nRYOS agent smoke FAILED")
        return 1
    print(f"  [ok] {version}: no Qt, no window; the real RYOS folder is unchanged")
    print(report)
    print("\nRYOS agent smoke PASSED")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--exe", help="a built RYOS.exe to launch instead of source")
    parser.add_argument("--visible", action="store_true",
                        help="show the window (on a second screen when there is one)")
    parser.add_argument("--cli-only", metavar="RYOS-CLI-EXE",
                        help="RYOS Agent: check a ryos-cli.exe built without the window")
    args = parser.parse_args()
    if args.cli_only:
        return _agent_smoke(Path(args.cli_only).resolve())

    real = Path(os.environ.get("APPDATA") or Path.home() / ".local" / "share") / "RYOS"
    before = _snapshot(real)

    tmp = Path(tempfile.mkdtemp(prefix="ryos-launch-"))
    data = tmp / "RYOS"
    data.mkdir()
    settings = {"auto_check_update": False, "open_on_cursor_monitor": False,
                "remember_window_geometry": True, "start_minimized": False,
                "snap_corner": "none"}
    if args.visible:
        geometry = _second_screen_geometry()
        if geometry:
            settings["window_geometry"] = geometry
    (data / "settings.json").write_text(json.dumps(settings), encoding="utf-8")

    env = dict(os.environ, APPDATA=str(tmp), RYOS_NO_REGISTRY="1", RYOS_NO_TOASTS="1",
               RYOS_ALLOW_MULTIPLE="1")
    if not args.visible:
        env["QT_QPA_PLATFORM"] = "offscreen"
    cmd = [str(Path(args.exe).resolve())] if args.exe else [sys.executable, "-m", "ryos"]
    print(f"RYOS launch smoke: {' '.join(cmd)}")
    print(f"  (data in {data}; registry writes off; "
          f"{'window visible' if args.visible else 'no window'})")

    problems = []
    proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        log_text = ""
        deadline = time.time() + WAIT_S
        while time.time() < deadline:
            logs = sorted(data.rglob("*.log"))
            log_text = "".join(p.read_text(encoding="utf-8", errors="replace")
                               for p in logs)
            if "Window shown" in log_text or proc.poll() is not None:
                break
            time.sleep(0.5)
        version = _source_version()
        if f"RYOS {version} starting" not in log_text:
            problems.append(f"the log does not say RYOS {version} started "
                            "(a stale build?)")
        if "ui=qt" not in log_text:
            problems.append("the log does not say the Qt interface started")
        if "Window shown" not in log_text:
            problems.append(f"no 'Window shown' within {WAIT_S}s "
                            f"(exit code {proc.poll()})")
        for bad in ("Traceback", "Fatal error", "ERROR", "no SVG"):
            if bad in log_text:
                problems.append(f"the log contains {bad!r}")
        if not (data / "scripts.db").exists():
            problems.append("no database was created in the throwaway folder")
        time.sleep(1.0)                          # let it settle into the loop
        if proc.poll() is not None:
            problems.append(f"the app exited on its own (code {proc.returncode})")
    finally:
        if proc.poll() is None:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True)
            else:
                proc.terminate()
            proc.wait(timeout=15)
        output = proc.stdout.read().decode("utf-8", errors="replace") if proc.stdout else ""

    cli_report = ""
    if args.exe:
        cli_exe = Path(args.exe).resolve().parent / "ryos-cli.exe"
        if cli_exe.exists():
            cli_report = _check_cli([str(cli_exe)], env, data, problems)
            if not problems:
                cli_report += "\n" + _check_mcp_or_its_absence(cli_exe, env, data, problems)
        else:
            problems.append(f"the build has no {cli_exe.name} beside RYOS.exe")
    else:
        cli_report = _check_cli([sys.executable, "-m", "ryos"], env, data, problems)

    after = _snapshot(real)
    if after != before:
        changed = sorted(set(after.items()) ^ set(before.items()))
        problems.append(f"the real RYOS folder changed: {changed[:5]}")

    if problems:
        print("\n".join(f"  PROBLEM: {p}" for p in problems))
        if output.strip():
            print("  --- app output ---\n" + output[-2000:])
        print("\nRYOS launch smoke FAILED")
        return 1
    print(f"  [ok] RYOS {_source_version()} started on Qt, showed its window, "
          "stayed up; the real RYOS folder is unchanged")
    if cli_report:
        print(cli_report)
    print("\nRYOS launch smoke PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
