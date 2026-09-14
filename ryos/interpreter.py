"""Map script file extensions to interpreters and build subprocess command lists."""
import json
import os
import shlex
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .logger import get_logger

_log = get_logger("interpreter")


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
        ".sln": shutil.which("devenv") or "cmd /c",
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
    """Directory a command should run in: the folder holding the script.

    Argument 0 is always the executable — build_command puts the interpreter
    first — so the search for the script starts at argument 1. Skipping it
    matters because a detected interpreter is an absolute path to a real file
    (sys.executable for .py), and searching from 0 would match *that* and run
    every Python script in the Python install directory instead of its own
    folder.

    Falls back to argument 0's parent when no argument names an existing file,
    and to a bare command list (no interpreter) naming the script at 0.
    """
    target = next((c for c in cmd[1:] if Path(c).is_file()), None)
    if target is None:
        target = next((c for c in cmd if Path(c).is_file()), cmd[0])
    return str(Path(target).parent)


@dataclass(frozen=True)
class RunSpec:
    """Everything needed to spawn one run: the command, where, and with what.

    ``env is None`` means "inherit the parent environment unchanged" — which is
    what ``Popen(env=None)`` already does, so a script with no overrides
    produces exactly the call this app made before per-script environments
    existed.
    """
    cmd: list[str]
    cwd: str
    env: dict | None = None


def parse_env_vars(raw) -> dict[str, str]:
    """Decode a stored env_vars blob into {name: value}.

    Anything unusable — bad JSON, a list, a nested object — yields {} rather
    than raising. This sits on the run path, where a malformed blob must not be
    able to stop a script from launching.
    """
    if not raw:
        return {}
    if isinstance(raw, dict):
        pairs = raw
    else:
        try:
            pairs = json.loads(raw)
        except (TypeError, ValueError):
            _log.warning("Ignoring unparseable env_vars: %.80r", raw)
            return {}
        if not isinstance(pairs, dict):
            _log.warning("Ignoring env_vars that is not an object: %.80r", raw)
            return {}
    out = {}
    for k, v in pairs.items():
        key = str(k).strip()
        if key:
            # Values are stored and passed literally — no %VAR% / $VAR
            # expansion. Expansion is easy to add later and impossible to
            # remove once scripts depend on it.
            out[key] = "" if v is None else str(v)
    return out


def build_run_spec(cmd: list[str], work_dir: str = "", env_vars=None,
                   base_env=None) -> RunSpec:
    """Compose a RunSpec from a command and a script's stored overrides.

    The environment is the parent's with the script's pairs laid over the top,
    never a replacement: a bare environment has no PATH, which on Windows
    breaks the interpreter lookup the command usually depends on.
    """
    cwd = work_dir.strip() if isinstance(work_dir, str) else ""
    overlay = parse_env_vars(env_vars)
    env = {**(os.environ if base_env is None else base_env), **overlay} if overlay else None
    return RunSpec(cmd=cmd, cwd=cwd or working_dir_for(cmd), env=env)


def parse_env_text(text: str) -> dict[str, str]:
    """Parse a KEY=value block (one pair per line) into a dict.

    Uses .env conventions rather than a bespoke widget format, so a block can be
    pasted straight in from a shell or an existing .env file: blank lines and
    lines starting with '#' are ignored, the split is on the first '=' only
    (values may contain '='), and a line with no '=' is skipped rather than
    becoming a variable with an empty name.
    """
    out: dict[str, str] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            out[key] = value.strip()
    return out


def format_env_text(raw) -> str:
    """Render a stored env_vars blob back into an editable KEY=value block."""
    return "\n".join(f"{k}={v}" for k, v in parse_env_vars(raw).items())
