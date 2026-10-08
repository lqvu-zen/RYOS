"""Build every RYOS download into dist/, and check each one.

    uv run --extra mcp --with cx_Freeze python build_release.py

Writes:

* ``RYOS-windows.zip`` -- RYOS.exe and ryos-cli.exe (MCP inside), for most users;
* ``RYOS-agent.zip``   -- ryos-cli.exe alone, no window and no Qt (RYOS Agent);
* ``RYOS-portable.zip``-- the source, run with uv (``run.bat``);
* ``SHA256SUMS.txt``   -- a checksum line per zip.

Each zip is checked for what it must hold and must not; a missing exe, Qt
in the agent build or a ``__pycache__`` in the source stops the script with
exit 1 before anything is published. It does not smoke-test the builds --
``tests/launch_smoke.py`` does that (``--exe`` and ``--cli-only``).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
BUILDS = {"windows": DIST / "cxfreeze", "agent": DIST / "cxfreeze-agent"}
PORTABLE_FILES = ("pyproject.toml", "run.bat", "install_uv.bat", "icon.ico")


def build(variant: str) -> None:
    shutil.rmtree(BUILDS[variant], ignore_errors=True)
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    print(f"building {variant}...", flush=True)
    done = subprocess.run([sys.executable, "setup_cxfreeze.py", "build_exe"], cwd=ROOT,
                          env=dict(os.environ, RYOS_VARIANT=variant),
                          capture_output=True, text=True)
    if done.returncode != 0:
        sys.exit(f"the {variant} build failed:\n{done.stdout[-2000:]}\n{done.stderr[-2000:]}")


def zip_folder(folder: Path, target: Path) -> list[str]:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(folder).as_posix())
        return z.namelist()


def zip_portable(target: Path) -> list[str]:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted((ROOT / "ryos").rglob("*")):
            if (p.is_file() and "__pycache__" not in p.parts
                    and p.name != "_build_info.py"):
                z.write(p, p.relative_to(ROOT).as_posix())
        for name in PORTABLE_FILES:
            z.write(ROOT / name, name)
        return z.namelist()


def problems_in(name: str, entries: list[str]) -> list[str]:
    """What is missing from, or wrongly in, one download."""
    files = {e.rsplit("/", 1)[-1] for e in entries}
    found = []
    if name == "RYOS-windows.zip":
        found += [f"no {exe}" for exe in ("RYOS.exe", "ryos-cli.exe") if exe not in files]
        if not any(e.startswith("lib/mcp/") for e in entries):
            found.append("no MCP SDK in ryos-cli.exe")
    elif name == "RYOS-agent.zip":
        if "ryos-cli.exe" not in files:
            found.append("no ryos-cli.exe")
        if "RYOS.exe" in files or any("/qtui/" in e for e in entries):
            found.append("the window is in the agent build")
        if any(f.lower().startswith(("qt6", "pyside6", "shiboken6")) for f in files):
            found.append("Qt is in the agent build")
        if not any(e.startswith("lib/mcp/") for e in entries):
            found.append("no MCP SDK")
    else:
        found += [f"no {f}" for f in (*PORTABLE_FILES, "ryos/__init__.py")
                  if f not in entries]
        if any("__pycache__" in e or e.endswith("_build_info.py") for e in entries):
            found.append("build leftovers (__pycache__ or _build_info.py)")
    return found


def main() -> int:
    try:
        import mcp  # noqa: F401
    except ImportError:
        sys.exit("The builds carry the MCP server: run this as\n"
                 "  uv run --extra mcp --with cx_Freeze python build_release.py")
    DIST.mkdir(exist_ok=True)
    for variant in BUILDS:
        build(variant)
    zips = {
        "RYOS-windows.zip": zip_folder(BUILDS["windows"], DIST / "RYOS-windows.zip"),
        "RYOS-agent.zip": zip_folder(BUILDS["agent"], DIST / "RYOS-agent.zip"),
        "RYOS-portable.zip": zip_portable(DIST / "RYOS-portable.zip"),
    }
    failed = False
    sums = []
    for name, entries in zips.items():
        found = problems_in(name, entries)
        path = DIST / name
        size = path.stat().st_size / 2**20
        print(f"  {name:<18} {size:5.1f} MB  {len(entries)} files"
              + (f"  PROBLEM: {'; '.join(found)}" if found else ""))
        failed |= bool(found)
        sums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {name}")
    (DIST / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
    if failed:
        print("\nbuild_release FAILED")
        return 1
    print("  SHA256SUMS.txt written\n\nbuild_release done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
