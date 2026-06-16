"""Map script file extensions to interpreters and build subprocess command lists."""
import os
import shlex
import shutil
import sys
from pathlib import Path


def _find_python() -> str:
    """Return a usable Python executable path.

    When frozen (cx_Freeze), sys.executable is RYOS.exe — using it to run
    .py scripts would relaunch the app.  Fall back to PATH lookup instead.
    """
    if getattr(sys, "frozen", False):
        for candidate in ("python", "python3", "py"):
            found = shutil.which(candidate)
            if found:
                return found
        return "python"
    return sys.executable


def detect_interpreter(path: str) -> str:
    ext = Path(path).suffix.lower()
    mapping = {
        ".py":  _find_python(),
        ".js":  "node",
        ".ts":  "ts-node",
        ".rb":  "ruby",
        ".pl":  "perl",
        ".php": "php",
        ".sh":  "bash",
        ".ps1": "powershell",
        ".bat": "",
        ".cmd": "",
        ".exe": "",
        ".sln": "cmd",
        ".code-workspace": "code",
    }
    return mapping.get(ext, "cmd")


def _script_tag(path: str) -> tuple[str, str]:
    """Return (label, bg_color) for the script type badge."""
    ext = Path(path).suffix.lower()
    tags = {
        ".py":  ("Python",     "#2B5B84"),
        ".js":  ("JavaScript", "#B8860B"),
        ".ts":  ("TypeScript", "#2B6CB0"),
        ".rb":  ("Ruby",       "#A02020"),
        ".pl":  ("Perl",       "#0067A3"),
        ".php": ("PHP",        "#3D4A7A"),
        ".sh":  ("Shell",      "#2E7D32"),
        ".ps1": ("PowerShell", "#1A3A6C"),
        ".bat": ("Batch",      "#4A4A4A"),
        ".cmd": ("CMD",        "#4A4A4A"),
        ".exe": ("EXE",        "#3A3A3A"),
        ".sln": ("VS",         "#68217A"),
        ".code-workspace": ("VS Code", "#0078D4"),
    }
    label = ext.lstrip(".").upper() if ext else "Script"
    return tags.get(ext, (label, "#555555"))


def resolve_interpreter(path: str, stored: str) -> str:
    """Return the effective interpreter for a script.

    Uses *stored* when non-empty, falls back to auto-detection otherwise.
    Also falls back to auto-detection when *stored* resolves to RYOS.exe
    itself (a database entry left over from running under a compiled build
    where sys.executable was RYOS.exe).
    """
    interp = stored.strip() if stored.strip() else detect_interpreter(path)
    if interp and Path(interp).stem.lower() == "ryos":
        interp = detect_interpreter(path)
    return interp


def build_command(path: str, params: str, interpreter: str):
    cmd = []
    if interpreter.strip():
        cmd.extend(shlex.split(interpreter, posix=(os.name != "nt")))
    if path.strip():
        cmd.append(path)
    if params.strip():
        cmd.extend(shlex.split(params, posix=(os.name != "nt")))
    return cmd


def working_dir_for(cmd: list[str]) -> str:
    """Directory a command should run in.

    Picks the parent of the first argument that is an existing file — i.e. the
    script itself, even when the command is interpreter-prefixed like
    ["python", "/path/script.py", ...] — falling back to the parent of the
    executable when no argument names an existing file.
    """
    target = next((c for c in cmd if Path(c).is_file()), cmd[0])
    return str(Path(target).parent)
