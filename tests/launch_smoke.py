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
* RYOS_ALLOW_MULTIPLE=1, so a running RYOS is neither signalled nor blocked;
* the Qt "offscreen" platform, so no window appears on any screen, unless
  --visible, which puts it on a second screen when there is one.

It waits for the app's "Window shown" log line, closes it, and fails if any
file in the user's real %APPDATA%/RYOS changed.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WAIT_S = 90


def _snapshot(folder: Path) -> dict:
    if not folder.is_dir():
        return {}
    return {str(p): (p.stat().st_mtime_ns, p.stat().st_size)
            for p in folder.rglob("*") if p.is_file()}


def _second_screen_geometry():
    sys.path.insert(0, str(ROOT / "tests"))
    from gui_smoke import smoke_screen    # the same screen choice as the smokes
    area = smoke_screen()
    return f"540x640+{area[0] + 40}+{area[1] + 40}" if area else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--exe", help="a built RYOS.exe to launch instead of source")
    parser.add_argument("--visible", action="store_true",
                        help="show the window (on a second screen when there is one)")
    args = parser.parse_args()

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

    env = dict(os.environ, APPDATA=str(tmp), RYOS_NO_REGISTRY="1",
               RYOS_ALLOW_MULTIPLE="1")
    env.pop("RYOS_UI", None)
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
        if "ui=qt" not in log_text:
            problems.append("the log does not say the Qt interface started")
        if "Window shown" not in log_text:
            problems.append(f"no 'Window shown' within {WAIT_S}s "
                            f"(exit code {proc.poll()})")
        for bad in ("Traceback", "Fatal error", "ERROR"):
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
    print("  [ok] started on Qt, showed its window, stayed up; "
          "the real RYOS folder is unchanged")
    print("\nRYOS launch smoke PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
