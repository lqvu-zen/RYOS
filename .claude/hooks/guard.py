from __future__ import annotations

import json
import os
import posixpath
import re
import subprocess
import sys
from typing import Callable, Mapping, NamedTuple


class Verdict(NamedTuple):
    kind: str
    reason: str = ""


ALLOW = Verdict("allow")


class Places(NamedTuple):
    real_data: tuple[str, ...]
    keys: tuple[str, ...]
    refs: dict[str, str]
    project: str = ""


class Location:
    def __init__(self, project: str = "") -> None:
        self.project = project
        self.absolute: str | None = None
        self.relative: str | None = ""

    def change(self, target: str | None) -> None:
        if not target or target == "-" or target[0] in "$%":
            self.absolute = None
            self.relative = None
            return
        if _is_absolute(target):
            self.absolute = posixpath.normpath(target)
            self.relative = "" if self.project and self.absolute == self.project else None
            return
        if self.absolute is not None:
            self.absolute = posixpath.normpath(self.absolute + "/" + target)
        if self.relative is not None:
            joined = posixpath.normpath(posixpath.join(self.relative or ".", target))
            self.relative = None if joined.startswith("..") else ("" if joined == "." else joined)

    def resolve(self, word: str) -> str:
        if self.absolute is None or not _looks_relative(word):
            return word
        return posixpath.normpath(self.absolute + "/" + word.replace("\\", "/"))


class Segment(NamedTuple):
    text: str
    words: list[str]
    redirects: list[str]
    body: str
    shell: str
    piped: bool
    substitution: bool


READ_ONLY = frozenset(
    "ls dir cat head tail less more grep rg find stat wc file du sha256sum md5sum echo "
    "printf diff cmp sort get-content gc type get-childitem gci get-item gi test-path "
    "select-string sls get-filehash measure-object select-object where-object format-list "
    "format-table out-string sort-object write-output write-host".split()
)
START_SWITCHES = frozenset({
    "/b", "/wait", "/min", "/max", "/low", "/high", "/normal", "/realtime", "/abovenormal",
    "/belownormal", "/separate", "/shared", "/i", "/d",
})
COPIES = frozenset({"cp", "copy-item", "copy", "cpi", "xcopy", "robocopy"})
FIND_ACTIONS = frozenset({"-delete", "-exec", "-execdir", "-ok", "-okdir"})
INTERPRETERS = frozenset({"python", "python3", "py", "uv", "bash", "sh", "pwsh", "powershell", "node"})
PYTHONS = frozenset({"python", "python3", "py", "pythonw"})
CD_COMMANDS = frozenset({"cd", "set-location", "sl", "chdir", "pushd", "push-location"})
PATTERN_FIRST = frozenset({"grep", "egrep", "fgrep", "rg", "select-string", "sls", "findstr"})
FILE_COMMANDS = (READ_ONLY | COPIES | frozenset({
    "mv", "move", "move-item", "mi", "rm", "del", "erase", "remove-item", "ri", "set-content",
    "sc", "add-content", "ac", "out-file", "tee", "chmod", "icacls", "openssl", "ssh-keygen",
    "scp", "base64", "xxd", "od", "notepad", "code", "gpg", "certutil", "attrib", "ren",
    "rename-item", "new-item", "ni", "touch", "vim", "vi", "nano", "dd", "zip", "7z", "tar",
    "compress-archive", "get-acl", "set-acl", "findstr",
})) - frozenset({"echo", "printf", "write-output", "write-host"})
SELF_GUARDING = (
    "tests/real_data_smoke.py",
    "tests/release_check.py",
    "tests/launch_smoke.py",
    "tests/session_smoke.py",
)
UV_VALUE_OPTIONS = frozenset({
    "--from",
    "--with", "--with-editable", "--with-requirements", "--extra", "--project",
    "--directory", "--python", "-p", "--group", "--env-file", "--index", "--package",
    "--only-group", "--no-group",
})
RYOS_HARMLESS = (["--version"], ["-v"], ["--help"], ["-h"])
WHOLE_TREE = frozenset({".", "./", ":/", ":/.", "*", "docs", "docs/", "./docs", "./docs/"})
SECRETARY_PATHS = ("docs/status.md", "docs/plans")

SET_MESSAGE = (
    "guard.py refused: `set APPDATA=...` outside `cmd /c` sets no environment variable. "
    "In PowerShell this sets no environment variable; use `$env:APPDATA = '...'`. In Bash "
    "write `APPDATA=... LOCALAPPDATA=... command` in the same command. On 2026-10-09 test "
    "scripts ran against the real %APPDATA%\\RYOS this way."
)
RYOS_MESSAGE = (
    "guard.py refused: this starts RYOS against the real %APPDATA%\\RYOS. Point APPDATA and "
    "LOCALAPPDATA at a scratch folder in the same command (Bash: `APPDATA=\"$S/a\" "
    "LOCALAPPDATA=\"$S/l\" uv run ryos ...`; PowerShell: `$env:APPDATA = '...'; "
    "$env:LOCALAPPDATA = '...'; ...`), or ask Vũ to run it himself."
)

_DRIVE = re.compile(r"(?<![\w.:/~$-])/([a-z])(?=/|$|[\s\"'`;|&)])")
_REF = re.compile(r"%(\w+)%|\$\{env:(\w+)\}|\$env:(\w+)|\$\{(\w+)\}|\$(\w+)", re.IGNORECASE)
_TILDE = re.compile(r"(?<![\w/.~-])~(?=[/\\]|$|[\s\"'])")
_KEY_WORD = re.compile(r"^.*[\w-]\.(pem|key|p8)$", re.IGNORECASE)
_KEY_PATH = re.compile(r"[/\\~][\w.-]*[\w-]\.(pem|key|p8)(?![\w(])", re.IGNORECASE)
_BASH_ASSIGN = re.compile(r"^([A-Za-z_]\w*)=(.*)$", re.DOTALL)
_PS_ASSIGN = re.compile(r"^\s*\$(?:env:)?(\w+)\s*=(?!=)\s*(.*)$", re.DOTALL | re.IGNORECASE)


def normalise(text: str) -> str:
    lowered = text.lower().replace("\\", "/")
    lowered = re.sub(r"/{2,}", "/", lowered)
    return _DRIVE.sub(r"\1:", lowered)


def flat(text: str) -> str:
    return normalise(re.sub(r"[\"'`]", "", text))


def places_from_env(env: Mapping[str, str]) -> Places:
    profile = env.get("USERPROFILE") or ""
    appdata = env.get("APPDATA") or ""
    local = env.get("LOCALAPPDATA") or ""
    roots = [
        appdata and appdata + "/RYOS",
        local and local + "/RYOS",
        profile and profile + "/AppData/Roaming/RYOS",
        profile and profile + "/AppData/Local/RYOS",
    ]
    real = tuple(dict.fromkeys(normalise(r) for r in roots if r))
    keys = (normalise(profile + "/ryos-keys"),) if profile else ()
    refs = {k: v for k, v in (("APPDATA", appdata), ("LOCALAPPDATA", local),
                              ("USERPROFILE", profile), ("HOME", profile)) if v}
    project = normalise(env.get("CLAUDE_PROJECT_DIR") or "")
    return Places(real, keys, refs, posixpath.normpath(project) if project else "")


def expand_refs(text: str, refs: Mapping[str, str], assigned: Mapping[str, str]) -> str:
    def replace(match: re.Match) -> str:
        name = next(g for g in match.groups() if g).upper()
        if name in assigned:
            return assigned[name]
        if refs.get(name):
            return refs[name]
        return match.group(0)

    expanded = _REF.sub(replace, text)
    profile = refs.get("USERPROFILE")
    if profile:
        expanded = _TILDE.sub(lambda _m: profile, expanded)
    return expanded


def names_place(text: str, roots: tuple[str, ...] | list[str]) -> bool:
    for root in roots:
        if not root:
            continue
        for match in re.finditer(re.escape(root), text):
            end = match.end()
            if end == len(text) or not re.match(r"[\w.-]", text[end]):
                return True
    return False


def names_key_path(text: str) -> bool:
    return bool(_KEY_PATH.search(text))


def _file_operands(words: list[str]) -> list[str]:
    name = command_name(words[0])
    args = words[1:]
    if name not in PATTERN_FIRST:
        return [w for w in args if not w.startswith("-")]
    operands: list[str] = []
    pattern_given = False
    index = 0
    while index < len(args):
        word = args[index]
        lowered = word.lower()
        if lowered in ("-e", "--regexp", "-pattern"):
            pattern_given = True
            index += 2
            continue
        if lowered in ("-f", "--file", "-path", "-literalpath"):
            if index + 1 < len(args):
                operands.append(args[index + 1])
            pattern_given = pattern_given or lowered in ("-f", "--file")
            index += 2
            continue
        if not word.startswith("-"):
            if pattern_given:
                operands.append(word)
            pattern_given = True
        index += 1
    return operands


def names_key_file(words: list[str], redirects: list[str]) -> bool:
    if any(_KEY_WORD.match(r) or names_key_path(r) for r in redirects):
        return True
    if not words or command_name(words[0]) in ("git", "gh"):
        return False
    if any(names_key_path(w) for w in words):
        return True
    if command_name(words[0]) not in FILE_COMMANDS:
        return False
    return any(_KEY_WORD.match(w) for w in _file_operands(words))


def _is_absolute(path: str) -> bool:
    return bool(re.match(r"^([a-z]:/|/|~)", path))


def _looks_relative(word: str) -> bool:
    return bool(word) and not re.match(r"^([a-zA-Z]:[/\\]|[/\\~$%-]|\w+://)", word)


def command_name(word: str) -> str:
    base = word.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return base[:-4] if base.endswith(".exe") else base


def _escape_char(shell: str) -> str:
    return {"bash": "\\", "powershell": "`", "cmd": "^"}[shell]


def parse_words(text: str, shell: str) -> tuple[list[str], list[str]]:
    words: list[str] = []
    redirects: list[str] = []
    cur: list[str] = []
    started = False
    quote = ""
    target_next = False
    esc = _escape_char(shell)
    quotes = "\"" if shell == "cmd" else "\"'"
    i, n = 0, len(text)

    def finish() -> None:
        nonlocal cur, started, target_next
        if started:
            word = "".join(cur)
            if target_next:
                redirects.append(word)
                target_next = False
            else:
                words.append(word)
        cur = []
        started = False

    while i < n:
        c = text[i]
        if quote:
            if c == quote:
                if shell == "powershell" and quote == "'" and i + 1 < n and text[i + 1] == "'":
                    cur.append("'")
                    i += 2
                    continue
                quote = ""
            elif quote == "\"" and shell == "bash" and c == "\\" and i + 1 < n and text[i + 1] in "\"\\$`":
                cur.append(text[i + 1])
                i += 2
                continue
            elif quote == "\"" and shell == "powershell" and c == "`" and i + 1 < n:
                cur.append(text[i + 1])
                i += 2
                continue
            else:
                cur.append(c)
            i += 1
            continue
        if c == esc and i + 1 < n:
            if text[i + 1] == "\n":
                i += 2
                continue
            cur.append(c)
            cur.append(text[i + 1])
            started = True
            i += 2
            continue
        if c in quotes:
            quote = c
            started = True
            i += 1
            continue
        if c.isspace():
            finish()
            i += 1
            continue
        if c == ">":
            prefix = "".join(cur)
            if started and prefix not in ("1", "2", "3", "&", "*"):
                finish()
            else:
                cur = []
                started = False
            while i < n and text[i] == ">":
                i += 1
            if i + 1 < n and text[i] == "&" and text[i + 1].isdigit():
                i += 2
                continue
            target_next = True
            continue
        if c == "<":
            finish()
            i += 1
            continue
        cur.append(c)
        started = True
        i += 1
    finish()
    return words, redirects


def _heredoc_delimiter(text: str, i: int) -> tuple[str, int] | None:
    j = i + 2
    if j < len(text) and text[j] == "<":
        return None
    if j < len(text) and text[j] == "-":
        j += 1
    while j < len(text) and text[j] in " \t":
        j += 1
    quote = text[j] if j < len(text) and text[j] in "'\"" else ""
    if quote:
        j += 1
    start = j
    while j < len(text) and (text[j].isalnum() or text[j] == "_"):
        j += 1
    if j == start:
        return None
    word = text[start:j]
    if quote and j < len(text) and text[j] == quote:
        j += 1
    return word, j


def _split(command: str, shell: str) -> list[tuple[str, str, bool]]:
    pieces: list[tuple[str, str, bool]] = []
    buf: list[str] = []
    bodies: list[str] = []
    pending: list[str] = []
    quote = ""
    piped = False
    esc = _escape_char(shell)
    quotes = "\"" if shell == "cmd" else "\"'"
    i, n = 0, len(command)

    def flush(next_piped: bool) -> None:
        nonlocal buf, bodies, piped
        text = "".join(buf).strip()
        if text:
            pieces.append((text, "\n".join(bodies), piped))
        buf = []
        bodies = []
        piped = next_piped

    def read_bodies(at: int) -> int:
        lines = command[at:].split("\n")
        consumed = 0
        index = 0
        while pending and index < len(lines):
            delimiter = pending[0]
            body: list[str] = []
            while index < len(lines):
                line = lines[index]
                consumed += len(line) + 1
                index += 1
                if line.strip() == delimiter:
                    break
                body.append(line)
            bodies.append("\n".join(body))
            pending.pop(0)
        return min(at + consumed, n)

    while i < n:
        c = command[i]
        if c == "\n" and pending:
            buf.append("\n")
            i = read_bodies(i + 1)
            if not quote:
                flush(False)
            continue
        if quote:
            if c == quote:
                quote = ""
            elif quote == "\"" and c == esc and shell != "cmd" and i + 1 < n:
                buf.append(command[i:i + 2])
                i += 2
                continue
            elif shell == "bash" and quote == "\"" and command.startswith("<<", i):
                found = _heredoc_delimiter(command, i)
                if found:
                    pending.append(found[0])
                    buf.append(command[i:found[1]])
                    i = found[1]
                    continue
            buf.append(c)
            i += 1
            continue
        if c == esc and i + 1 < n:
            if command[i + 1] == "\n":
                i += 2
                continue
            buf.append(command[i:i + 2])
            i += 2
            continue
        if c in quotes:
            quote = c
            buf.append(c)
            i += 1
            continue
        if shell == "bash" and command.startswith("<<", i):
            found = _heredoc_delimiter(command, i)
            if found:
                pending.append(found[0])
                buf.append(command[i:found[1]])
                i = found[1]
                continue
        if c in "\n;":
            flush(False)
            i += 1
            continue
        if command.startswith("&&", i) or command.startswith("||", i):
            flush(False)
            i += 2
            continue
        if c == "|":
            flush(True)
            i += 1
            continue
        if c == "&":
            before = command[i - 1] if i else ""
            after = command[i + 1] if i + 1 < n else ""
            if before in "<>" and before or after == ">" or shell == "powershell":
                buf.append(c)
                i += 1
                continue
            flush(False)
            i += 1
            continue
        buf.append(c)
        i += 1
    flush(False)
    return pieces


def _strip_wrappers(words: list[str]) -> list[str]:
    while words:
        name = command_name(words[0])
        if words[0] == "&":
            words = words[1:]
        elif name == "nohup":
            words = words[1:]
        elif name == "env":
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[2:] if words[0] in ("-u", "--unset") else words[1:]
        elif name == "timeout" and len(words) > 1:
            rest = words[1:]
            while rest and rest[0].startswith("-"):
                rest = rest[2:] if rest[0] in ("-k", "-s", "--signal", "--kill-after") else rest[1:]
            words = rest[1:] if rest else []
        elif name == "start-process":
            rest = []
            skip = False
            for word in words[1:]:
                lowered = word.lower()
                if skip:
                    skip = False
                    continue
                if lowered in ("-filepath", "-argumentlist", "-wait", "-nonewwindow", "-passthru"):
                    continue
                if lowered in ("-windowstyle", "-workingdirectory", "-redirectstandardoutput",
                               "-redirectstandarderror", "-redirectstandardinput", "-verb"):
                    skip = True
                    continue
                rest.append(word)
            words = rest
        elif name == "start":
            rest = words[1:]
            while rest and (rest[0] == "" or rest[0].lower() in START_SWITCHES):
                rest = rest[2:] if rest[0].lower() == "/d" else rest[1:]
            words = rest
        elif name in ("invoke-item", "ii"):
            words = [w for w in words[1:] if w.lower() not in ("-path", "-literalpath")]
            if not words:
                return words
        else:
            return words
    return words


def _inner_command(words: list[str]) -> tuple[str, str] | None:
    if not words:
        return None
    name = command_name(words[0])
    lowered = [w.lower() for w in words]
    if name == "cmd":
        for index, word in enumerate(lowered[1:], start=1):
            if word in ("/c", "/k", "//c", "//k"):
                return " ".join(words[index + 1:]), "cmd"
        return None
    if name in ("powershell", "pwsh"):
        for index, word in enumerate(lowered[1:], start=1):
            if word in ("-command", "-c", "/c", "-com", "-comm"):
                return " ".join(words[index + 1:]), "powershell"
        return None
    if name in ("bash", "sh"):
        for index, word in enumerate(lowered[1:], start=1):
            if word.startswith("-") and not word.startswith("--") and word.endswith("c"):
                if index + 1 < len(words):
                    return words[index + 1], "bash"
        return None
    return None


def segments(command: str, shell: str, depth: int = 0) -> list[Segment]:
    result: list[Segment] = []
    for text, body, piped in _split(command, shell):
        words, redirects = parse_words(text, shell)
        words = _strip_wrappers(words)
        substitution = "$(" in text or (shell == "bash" and "`" in text)
        inner = _inner_command(words) if depth < 2 else None
        if inner is not None:
            inner_segments = segments(inner[0], inner[1], depth + 1)
            if inner_segments:
                first = inner_segments[0]
                inner_segments[0] = first._replace(piped=piped,
                                                   redirects=first.redirects + redirects)
                result.extend(inner_segments)
                continue
        result.append(Segment(text, words, redirects, body, shell, piped, substitution))
    return result


def _assignment_value(raw: str, refs: Mapping[str, str], assigned: Mapping[str, str]) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return expand_refs(value, refs, assigned)


def assignments(segment: Segment, refs: Mapping[str, str],
                assigned: dict[str, str]) -> tuple[list[str], bool]:
    words = list(segment.words)
    if segment.shell == "powershell" and words:
        match = _PS_ASSIGN.match(segment.text)
        if match and words[0].startswith("$"):
            name, rhs = match.group(1).upper(), match.group(2)
            rhs_words, _ = parse_words(rhs, "powershell")
            pure = len(rhs_words) <= 1 and (not rhs.strip() or rhs.strip()[0] in "\"'$0123456789@")
            assigned[name] = _assignment_value(rhs, refs, assigned)
            return ([] if pure else rhs_words), True
        return words, False
    if segment.shell == "cmd" and words and words[0].lower() == "set" and len(words) > 1:
        rest = " ".join(words[1:]).strip()
        if rest.startswith("/"):
            return words, False
        name, _, value = rest.partition("=")
        if name:
            assigned[name.strip().upper()] = _assignment_value(value, refs, assigned)
            return [], True
        return words, False
    if segment.shell == "bash" and words and words[0] in ("export", "declare", "local", "readonly"):
        words = words[1:]
        while words and words[0].startswith("-"):
            words = words[1:]
    found = False
    while words:
        match = _BASH_ASSIGN.match(words[0])
        if not match:
            break
        assigned[match.group(1).upper()] = _assignment_value(match.group(2), refs, assigned)
        words = words[1:]
        found = True
    return words, found


def is_set_outside_cmd(segment: Segment) -> bool:
    words = segment.words
    return (segment.shell != "cmd" and len(words) > 1 and words[0].lower() == "set"
            and words[1].upper().startswith(("APPDATA=", "LOCALAPPDATA=")))


def _after_xargs(words: list[str]) -> list[str]:
    rest = words[1:]
    while rest and rest[0].startswith("-"):
        option = rest[0]
        if option in ("-n", "-I", "-d", "-P", "-L", "-s", "-E", "-a"):
            rest = rest[2:]
        else:
            rest = rest[1:]
    return rest


def _copy_destination(name: str, args: list[str]) -> str | None:
    positional: list[str] = []
    index = 0
    while index < len(args):
        word = args[index]
        lowered = word.lower()
        if lowered in ("-t", "--target-directory"):
            return args[index + 1] if index + 1 < len(args) else None
        if lowered.startswith("--target-directory="):
            return word.split("=", 1)[1]
        if lowered.startswith("-dest"):
            return args[index + 1] if index + 1 < len(args) else None
        if lowered in ("-path", "-literalpath", "-filter", "-include", "-exclude"):
            index += 2
            continue
        if word.startswith("-") or (name in ("xcopy", "robocopy", "copy") and word.startswith("/")
                                    and len(word) <= 5 and ":" not in word):
            index += 1
            continue
        positional.append(word)
        index += 1
    if name == "robocopy":
        return positional[1] if len(positional) > 1 else None
    if not positional:
        return None
    if name in ("copy-item", "cpi") and any(a.lower() in ("-path", "-literalpath") for a in args):
        return positional[-1]
    return positional[-1] if len(positional) > 1 else None


def is_read_only(words: list[str], redirects: list[str], places: Places) -> bool:
    if any(names_place(flat(r), places.real_data) for r in redirects):
        return False
    if not words:
        return True
    script = script_of(words)
    if script is not None and flat(script).endswith(SELF_GUARDING):
        return True
    name = command_name(words[0])
    if name == "xargs":
        inner = _after_xargs(words)
        return bool(inner) and is_read_only(inner, [], places)
    if name in COPIES:
        destination = _copy_destination(name, words[1:])
        return destination is not None and not names_place(flat(destination), places.real_data)
    if name not in READ_ONLY:
        return False
    if name == "find" and any(w.lower() in FIND_ACTIONS for w in words):
        return False
    if name == "sort":
        for index, word in enumerate(words):
            if word in ("-o", "--output") and index + 1 < len(words):
                if names_place(flat(words[index + 1]), places.real_data):
                    return False
            if word.startswith("--output=") and names_place(flat(word), places.real_data):
                return False
    return True


def _python_script(args: list[str]) -> str | None:
    index = 0
    while index < len(args) and args[index].startswith("-"):
        if args[index].startswith(("-m", "-c")):
            return None
        index += 2 if args[index] in ("-X", "-W") else 1
    return args[index] if index < len(args) else None


def script_of(words: list[str]) -> str | None:
    if not words:
        return None
    name = command_name(words[0])
    if name in PYTHONS:
        return _python_script(words[1:])
    if name == "uv" and len(words) > 1 and words[1] == "run":
        index = 2
        while index < len(words) and words[index].startswith("-"):
            index += 2 if words[index] in UV_VALUE_OPTIONS else 1
        if index >= len(words):
            return None
        if command_name(words[index]) in PYTHONS:
            return _python_script(words[index + 1:])
        return words[index]
    return None


def ryos_arguments(words: list[str]) -> list[str] | None:
    if not words:
        return None
    name = command_name(words[0])
    if name in ("ryos", "ryos-cli", "run.bat") or name.endswith("ryos-cli"):
        return words[1:]
    tool_run = name == "uv" and words[1:3] == ["tool", "run"]
    if name == "uvx" or tool_run:
        index = 3 if tool_run else 1
        while index < len(words) and words[index].startswith("-"):
            index += 2 if words[index] in UV_VALUE_OPTIONS else 1
        if index < len(words) and command_name(words[index]) in ("ryos", "ryos-cli"):
            return words[index + 1:]
        return None
    if name == "uv" and len(words) > 1 and words[1] == "run":
        index = 2
        while index < len(words) and words[index].startswith("-"):
            option = words[index]
            index += 2 if option in UV_VALUE_OPTIONS else 1
        if index >= len(words):
            return None
        program = command_name(words[index])
        if program in ("ryos", "ryos-cli"):
            return words[index + 1:]
        if program in PYTHONS:
            return _python_module_ryos(words[index + 1:])
        return None
    if name in PYTHONS:
        return _python_module_ryos(words[1:])
    return None


def _python_module_ryos(args: list[str]) -> list[str] | None:
    index = 0
    while index < len(args) and args[index].startswith("-"):
        option = args[index]
        if option == "-m":
            if index + 1 < len(args) and (args[index + 1] == "ryos" or args[index + 1].startswith("ryos.")):
                return args[index + 2:]
            return None
        if option.startswith("-m"):
            module = option[2:]
            return args[index + 1:] if module == "ryos" or module.startswith("ryos.") else None
        if option in ("-c",):
            return None
        index += 2 if option in ("-X", "-W") else 1
    return None


def starts_ryos(words: list[str]) -> bool:
    args = ryos_arguments(words)
    if args is None:
        return False
    if [a.lower() for a in args] in RYOS_HARMLESS:
        return False
    if len(args) == 2 and args[0] == "verify":
        return False
    return True


def _git(words: list[str]) -> tuple[str, list[str], str] | None:
    if not words or command_name(words[0]) != "git":
        return None
    index = 1
    directory = ""
    while index < len(words) and words[index].startswith("-"):
        if words[index] == "-C" and index + 1 < len(words):
            directory = posixpath.join(directory, words[index + 1].replace("\\", "/"))
        index += 2 if words[index] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") else 1
    if index >= len(words):
        return None
    return words[index].lower(), words[index + 1:], directory


def _path_form(word: str, prefix: str = "") -> str:
    form = word.lower().replace("\\", "/")
    if form.startswith(":/"):
        return posixpath.normpath(form[2:] or ".")
    if prefix and not _is_absolute(form):
        form = posixpath.join(prefix.lower(), form)
    while form.startswith("./"):
        form = form[2:]
    return posixpath.normpath(form) if form else form


def _pathspec(args: list[str]) -> tuple[list[str], list[str]]:
    paths: list[str] = []
    after: list[str] = []
    after_dashes = False
    skip = False
    takes_value = ("-s", "--source", "-b", "-B", "--orphan", "--conflict", "--pathspec-from-file")
    for word in args:
        if skip:
            skip = False
            continue
        if after_dashes:
            paths.append(word)
            after.append(word)
        elif word == "--":
            after_dashes = True
        elif word in takes_value:
            skip = True
        elif not word.startswith("-"):
            paths.append(word)
    return paths, after


def _dirty_reason(what: str, dirty: Callable[[], list[str]]) -> str | None:
    files = dirty()
    if not files:
        return None
    return (f"guard.py refused: {what} would discard uncommitted secretary edits "
            f"({', '.join(files)}). Commit them with your next change; never revert them.")


def _broad(path: str, form: str) -> bool:
    return form in WHOLE_TREE or any(c in path for c in "*?[")


def _bare_file(form: str) -> bool:
    return "/" not in form and bool(re.search(r"\.\w+$", form))


def reverts_secretary_files(words: list[str], dirty: Callable[[], list[str]],
                            prefix: str | None = "") -> str | None:
    if words and command_name(words[0]) == "xargs":
        inner = _git(_after_xargs(words))
        if inner and inner[0] in ("checkout", "restore"):
            return ("guard.py refused: `git checkout` / `git restore` fed by xargs can revert "
                    "docs/STATUS.md or docs/plans/ (secretary edits); name the paths yourself.")
        return None
    found = _git(words)
    if found is None:
        return None
    sub, args, directory = found
    if sub == "reset" and "--hard" in args:
        return "guard.py refused: `git reset --hard` discards uncommitted secretary edits; never run it."
    if sub in ("checkout", "restore"):
        base = posixpath.join(prefix or "", directory) if prefix is not None else directory
        paths, after = _pathspec(args)
        for path in paths:
            form = _path_form(path, base)
            if any(form.startswith(p) or "/" + p in form for p in SECRETARY_PATHS):
                return (f"guard.py refused: `git {sub}` on {path} reverts a secretary edit "
                        "(docs/STATUS.md and docs/plans/ are the secretary's; commit them, never revert).")
            if "$(" in path or "`" in path:
                return (f"guard.py refused: `git {sub}` fed by a command substitution can revert "
                        "docs/STATUS.md or docs/plans/; name the paths yourself.")
        if sub == "restore" and any(a in ("--staged", "-S") for a in args) and not any(
                a in ("--worktree", "-W") for a in args):
            return None
        files = paths if sub == "restore" else after
        unknown_place = prefix is None or bool(directory)
        risky = any(_broad(p, _path_form(p)) for p in paths) or any(
            _bare_file(_path_form(p)) or (unknown_place and "/" not in _path_form(p))
            for p in files)
        forced = sub == "checkout" and any(a in ("-f", "--force") for a in args)
        if risky or forced:
            return _dirty_reason(f"`git {sub} {' '.join(args)}`", dirty)
        return None
    if sub == "switch":
        if any(a in ("-f", "--force", "--discard-changes") for a in args):
            return _dirty_reason(f"`git switch {' '.join(args)}`", dirty)
        return None
    if sub == "stash":
        if not args or args[0] in ("push", "save") or args[0].startswith("-"):
            return _dirty_reason("`git stash`", dirty)
        return None
    if sub == "clean":
        if any(a == "--force" or (a.startswith("-") and not a.startswith("--") and "f" in a) for a in args):
            return _dirty_reason("`git clean -f`", dirty)
    return None


def release_ask(words: list[str]) -> str | None:
    if not words:
        return None
    name = command_name(words[0])
    if name == "gh":
        index = 1
        while index < len(words) and words[index].startswith("-"):
            index += 2 if words[index] in ("-R", "--repo") else 1
        rest = words[index:]
        if len(rest) > 1 and rest[0] == "release" and rest[1] in (
                "create", "edit", "delete", "delete-asset", "upload"):
            return f"`gh release {rest[1]}` changes a published release; Vũ approves it."
        if rest and rest[0] == "api" and any("releases" in w for w in rest):
            method = "GET"
            fields = False
            for i, word in enumerate(rest):
                if word in ("-X", "--method") and i + 1 < len(rest):
                    method = rest[i + 1].upper()
                elif word.startswith("-X") and len(word) > 2:
                    method = word[2:].upper()
                elif word.startswith("--method="):
                    method = word.split("=", 1)[1].upper()
                elif word in ("-f", "-F", "--field", "--raw-field", "--input"):
                    fields = True
            explicit = any(w in ("-X", "--method") or w.startswith(("-X", "--method=")) for w in rest)
            if method != "GET" or (fields and not explicit):
                return "`gh api` writing to releases changes a published release; Vũ approves it."
        return None
    found = _git(words)
    if found and found[0] == "push":
        for word in found[1]:
            if (word.startswith("--force") or word == "--mirror" or word.startswith("+")
                    or (word.startswith("-") and not word.startswith("--") and "f" in word)):
                return "A forced or mirroring `git push` rewrites history on GitHub; Vũ approves it."
    return None


def _sign_release(words: list[str]) -> bool:
    for index, word in enumerate(words):
        if flat(word).endswith("tools/sign_release.py"):
            return index + 1 < len(words) and words[index + 1] in ("sign", "new")
    return False


def _cd_target(words: list[str]) -> str | None:
    args = [w for w in words[1:] if w.lower() not in ("-path", "-literalpath", "/d", "-l", "-p")]
    return args[0] if args else None


def _segment_verdict(segment: Segment, places: Places, assigned: dict[str, str],
                     dirty: Callable[[], list[str]], tainted_in: bool,
                     location: Location) -> tuple[Verdict, bool]:
    if is_set_outside_cmd(segment):
        return Verdict("deny", SET_MESSAGE), False
    before = dict(assigned)
    words, _assigned_here = assignments(segment, places.refs, assigned)
    expanded = [expand_refs(w, places.refs, before) for w in words]
    redirects = [expand_refs(r, places.refs, before) for r in segment.redirects]
    values = [assigned[k] for k in assigned if before.get(k) != assigned[k]]
    text = flat(" ".join(expanded + redirects))
    name = command_name(expanded[0]) if expanded else ""
    body = flat(expand_refs(segment.body, places.refs, before)) if name in INTERPRETERS else ""
    if names_place(text, places.keys) or names_place(body, places.keys) \
            or names_key_file(expanded, redirects) or names_key_path(body):
        return Verdict("deny", "guard.py refused: this names the release signing key (~/ryos-keys, "
                               "*.pem, *.key, *.p8). Vũ keeps the key; Claude never reads, copies "
                               "or uses it."), False
    if name in CD_COMMANDS:
        target = _cd_target(expanded)
        location.change(flat(target) if target is not None else None)
        if location.absolute is not None and names_place(location.absolute, places.keys):
            return Verdict("deny", "guard.py refused: this enters the release signing key folder. "
                                   "Vũ keeps the key; Claude never reads, copies or uses it."), False
        return ALLOW, False
    if _sign_release(expanded):
        return Verdict("deny", "guard.py refused: tools/sign_release.py sign/new is Vũ's; he signs "
                               "releases himself (release-ryos A3b)."), False
    if not expanded and segment.substitution and any(
            names_place(flat(v), places.real_data) for v in values):
        return Verdict("deny", "guard.py refused: a command substitution touching the real "
                               "%APPDATA%\\RYOS; read it with a read-only command instead."), False
    located = expanded[:1] + [location.resolve(flat(w)) for w in expanded[1:]]
    located_redirects = [location.resolve(flat(r)) for r in redirects]
    names_real = (names_place(text, places.real_data) or names_place(body, places.real_data)
                  or names_place(flat(" ".join(located + located_redirects)), places.real_data)
                  or (location.absolute is not None
                      and names_place(location.absolute, places.real_data)))
    tainted_out = False
    if expanded and (names_real or tainted_in):
        if name in ("git", "gh"):
            pass
        elif not body and not (segment.substitution and names_real) and is_read_only(
                located, located_redirects, places):
            tainted_out = True
        else:
            return Verdict("deny", "guard.py refused: this writes to, or runs something on, the "
                                   "real RYOS data (%APPDATA%\\RYOS or %LOCALAPPDATA%\\RYOS). Only "
                                   "reads and copies out of it are allowed; work on a copy in a "
                                   "scratch folder."), False
    if starts_ryos(expanded):
        appdata = assigned.get("APPDATA")
        if not appdata or names_place(flat(appdata + "/RYOS"), places.real_data):
            return Verdict("deny", RYOS_MESSAGE), False
    reason = reverts_secretary_files(expanded, dirty, location.relative)
    if reason:
        return Verdict("deny", reason), False
    ask = release_ask(expanded)
    if ask:
        return Verdict("ask", ask), tainted_out
    return ALLOW, tainted_out


def command_verdict(command: str, shell: str, places: Places,
                    secretary_dirty: Callable[[], list[str]]) -> Verdict:
    assigned: dict[str, str] = {}
    location = Location(places.project)
    tainted = False
    asked: Verdict | None = None
    for segment in segments(command, shell):
        verdict, tainted_out = _segment_verdict(segment, places, assigned, secretary_dirty,
                                                tainted and segment.piped, location)
        if verdict.kind == "deny":
            return verdict
        if verdict.kind == "ask" and asked is None:
            asked = verdict
        tainted = tainted_out
    return asked or ALLOW


def file_verdict(path: str, places: Places) -> Verdict:
    form = flat(expand_refs(path, places.refs, {}))
    if names_place(form, places.keys) or re.search(r"\.(pem|key|p8)$", form):
        return Verdict("deny", "guard.py refused: this file is (or is beside) the release signing "
                               "key. Vũ keeps the key; Claude never reads or writes it.")
    if names_place(form, places.real_data):
        return Verdict("deny", "guard.py refused: this file is in the real RYOS data folder "
                               "(%APPDATA%\\RYOS or %LOCALAPPDATA%\\RYOS). Work on a copy in a "
                               "scratch folder.")
    return ALLOW


def decide(tool_name: str, tool_input: Mapping, env: Mapping[str, str],
           secretary_dirty: Callable[[], list[str]]) -> Verdict:
    places = places_from_env(env)
    if tool_name in ("Bash", "PowerShell"):
        command = tool_input.get("command") or ""
        shell = "bash" if tool_name == "Bash" else "powershell"
        return command_verdict(command, shell, places, secretary_dirty)
    if tool_name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        return file_verdict(path, places)
    return ALLOW


def secretary_changes(project_dir: str) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", "docs/STATUS.md", "docs/plans"],
            cwd=project_dir or None, capture_output=True, text=True, encoding="utf-8", timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    return [line[3:].strip() for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
        project = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or ""
        verdict = decide(data.get("tool_name", ""), data.get("tool_input") or {}, os.environ,
                         lambda: secretary_changes(project))
    except Exception as error:
        print(f"guard.py failed: {type(error).__name__}: {error} -- not checked", file=sys.stderr)
        return 1
    if verdict.kind == "deny":
        print(verdict.reason, file=sys.stderr)
        return 2
    if verdict.kind == "ask":
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": verdict.reason,
        }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
