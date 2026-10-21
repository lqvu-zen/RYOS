"""Build every RYOS download into dist/, and check each one.

    uv run --extra mcp --with cx_Freeze python build_release.py

Writes:

* ``RYOS-windows.zip``    -- RYOS.exe and ryos-cli.exe, no MCP server;
* ``RYOS-windows-ai.zip`` -- RYOS.exe and ryos-cli.exe with the MCP server;
* ``RYOS-agent.zip``      -- ryos-cli.exe alone with MCP, no window and no Qt;
* ``RYOS-portable.zip``   -- the source as HEAD holds it, run with uv (``run.bat``);
* ``SHA256SUMS.txt``      -- a checksum line per zip.

Each zip is checked for what it must hold and must not; a missing exe, Qt
in the agent build, a frozen build without the release key or with the
test-build mark (``TEST_UPDATES``), or a ``__pycache__`` in the source stops
the script with exit 1 before anything is published. It does not smoke-test the builds --
``tests/launch_smoke.py`` does that (``--exe`` and ``--cli-only``).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
sys.path.insert(0, str(ROOT))
from ryos import buildinfo  # noqa: E402

#: Every frozen variant, in its own folder (buildinfo.BUILD_FOLDERS).
BUILDS = {v: ROOT / folder for v, folder in buildinfo.BUILD_FOLDERS.items()}
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


def _git(*args: str) -> bytes:
    done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True)
    if done.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed: {done.stderr.decode('utf-8', 'replace')}")
    return done.stdout


def commit_files() -> list[str]:
    names = _git("ls-tree", "-r", "-z", "--name-only", "HEAD", "--", "ryos").decode("utf-8")
    ryos = sorted(n for n in names.split("\0")
                  if n and "__pycache__" not in n.split("/") and not n.endswith("_build_info.py"))
    return ryos + list(PORTABLE_FILES)


def commit_blob(name: str) -> bytes:
    return _git("cat-file", "blob", f"HEAD:{name}")


def commit_time() -> tuple[int, int, int, int, int, int]:
    seconds = int(_git("show", "-s", "--format=%ct", "HEAD").decode("ascii").strip())
    stamp = time.gmtime(seconds)
    if stamp.tm_year < 1980:
        return (1980, 1, 1, 0, 0, 0)
    return (stamp.tm_year, stamp.tm_mon, stamp.tm_mday,
            stamp.tm_hour, stamp.tm_min, stamp.tm_sec)


def zip_portable(target: Path) -> list[str]:
    when = commit_time()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for name in commit_files():
            info = zipfile.ZipInfo(name, when)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, commit_blob(name))
        return z.namelist()


STAMP = "release_check.passed"
FROZEN_ZIPS = ("RYOS-windows.zip", "RYOS-windows-ai.zip", "RYOS-agent.zip")


def sums_digest(dist: Path) -> str:
    try:
        return hashlib.sha256((dist / "SHA256SUMS.txt").read_bytes()).hexdigest()
    except FileNotFoundError:
        return ""


def stamp_for(results: list[tuple[str, str, str]], head: str, sums: str,
              head_after: str, sums_after: str, python: str) -> str | None:
    if not head or not sums or head != head_after or sums != sums_after:
        return None
    if any(outcome not in ("PASS", "SKIP") for _name, outcome, _why in results):
        return None
    return json.dumps({
        "head": head, "sha256sums": sums,
        "passed": sum(1 for _n, o, _w in results if o == "PASS"),
        "skipped": sum(1 for _n, o, _w in results if o == "SKIP"),
        "python": python,
    }, indent=2) + "\n"


def clear_stamp(dist: Path) -> None:
    try:
        (dist / STAMP).unlink()
    except FileNotFoundError:
        pass


def python_refusal(dist: Path, magic: bytes = importlib.util.MAGIC_NUMBER,
                   running: str = platform.python_version()) -> str | None:
    for name in FROZEN_ZIPS:
        try:
            with zipfile.ZipFile(dist / name) as z:
                pyc = z.read(BUILD_INFO_ENTRY)
                entries = z.namelist()
        except (FileNotFoundError, KeyError, zipfile.BadZipFile):
            continue
        if pyc[:4] == magic:
            continue
        found = [re.fullmatch(r"python3(\d+)\.dll", e, re.IGNORECASE) for e in entries]
        minors = [m.group(1) for m in found if m]
        if not minors:
            return (f"{name} was built with another Python than this one ({running}): "
                    "run release_check with the Python the builds used.")
        built = f"3.{minors[0]}"
        return (f"{name} was built with Python {built}, and this is {running}: run "
                f"uv run --python {built} python tests/release_check.py")
    return None


def problems_in(name: str, entries: list[str]) -> list[str]:
    """What is missing from, or wrongly in, one download."""
    files = {e.rsplit("/", 1)[-1] for e in entries}
    has_mcp = any(e.startswith("lib/mcp/") for e in entries)
    found = []
    if name == "RYOS-windows.zip":
        found += [f"no {exe}" for exe in ("RYOS.exe", "ryos-cli.exe") if exe not in files]
        if has_mcp:
            found.append("the MCP SDK is in the build without AI agents")
        if any(e.startswith("lib/cryptography/") for e in entries):
            found.append("cryptography is in the build without AI agents")
    elif name == "RYOS-windows-ai.zip":
        found += [f"no {exe}" for exe in ("RYOS.exe", "ryos-cli.exe") if exe not in files]
        if not has_mcp:
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


BUILD_INFO_ENTRY = "lib/ryos/_build_info.pyc"


def release_key_problems(name: str, read: Callable[[str], bytes]) -> list[str]:
    """Whether a frozen download trusts the release key, and is not one of
    release_check's test builds; ``read`` gives a zip entry's bytes."""
    if name == "RYOS-portable.zip":
        return []
    try:
        data = read(BUILD_INFO_ENTRY)
    except KeyError:
        return [f"no {BUILD_INFO_ENTRY}, so its release key cannot be checked"]
    found = []
    if buildinfo.RELEASE_PUBLIC_KEY.encode("ascii") not in data:
        found.append("it does not carry the release key")
    if buildinfo.TEST_UPDATES_NAME.encode("ascii") in data:
        found.append("it is a test build (TEST_UPDATES)")
    return found


def main() -> int:
    clear_stamp(DIST)
    try:
        import mcp  # noqa: F401
    except ImportError:
        sys.exit("The builds carry the MCP server: run this as\n"
                 "  uv run --extra mcp --with cx_Freeze python build_release.py")
    DIST.mkdir(exist_ok=True)
    for variant in BUILDS:
        build(variant)
    zips = {buildinfo.download_name(v): zip_folder(folder, DIST / buildinfo.download_name(v))
            for v, folder in BUILDS.items()}
    zips["RYOS-portable.zip"] = zip_portable(DIST / "RYOS-portable.zip")
    failed = False
    sums = []
    for name, entries in zips.items():
        found = problems_in(name, entries)
        path = DIST / name
        with zipfile.ZipFile(path) as z:
            found += release_key_problems(name, z.read)
        size = path.stat().st_size / 2**20
        print(f"  {name:<18} {size:5.1f} MB  {len(entries)} files"
              + (f"  PROBLEM: {'; '.join(found)}" if found else ""))
        failed |= bool(found)
        sums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {name}")
    # LF on every OS: `sha256sum -c` reads a CRLF line's file name with a
    # stray \r and fails (2.3.0's file had to be rewritten before publishing).
    (DIST / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8",
                                         newline="\n")
    if failed:
        print("\nbuild_release FAILED")
        return 1
    print("  SHA256SUMS.txt written\n\nbuild_release done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
