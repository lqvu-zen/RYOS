"""When and how RYOS swaps in a downloaded update, or rolls one back: the
rules and words behind the window's "Restart to update" and Help -> Roll
back, ``ryos-cli update [--rollback]``, and what start-up does about an
update left half-done or asked for "the next time RYOS starts".

Toolkit-free. ``decide`` is pure; everything that reaches outside the
process -- which folder RYOS runs from, the process list, writing probe
files, spawning the helper -- is a field of ``Updater``, inert unless
``real()`` builds it. The swap itself is ``swap.py``; the plan and
decisions are in docs/plans/release-2.4.0.md, step 10.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Callable, NamedTuple

from . import buildinfo, swap, updates
from .notifications import _RELEASES_PAGE, _parse_version

GO = "go"
PORTABLE = "portable"
NOTHING = "nothing"
NOT_WRITABLE = "not-writable"
BLOCKED = "blocked"
BUSY = "busy"
DUE = "due"

WINDOW = "window"
CLI = "cli"

UPDATE = swap.UPDATE
ROLLBACK = swap.ROLLBACK

DUE_SOON = timedelta(minutes=5)
AT_START_NAME = "at-start.json"
LOCK_POLL = 0.25

RESTART_LABEL = "Restart to update"
LATER_LABEL = "Later"
CANCEL_LABEL = "Cancel"

UPDATE_TITLE = "Update RYOS"
ROLLBACK_TITLE = "Roll back RYOS"


class Process(NamedTuple):
    pid: int
    name: str


@dataclass(frozen=True)
class Decision:
    verdict: str
    title: str
    text: str
    warning: str | None = None


class AtStart(NamedTuple):
    applying: bool
    notes: tuple[tuple[str, str, str], ...]


def _bare(tag: str | None) -> str:
    return str(tag or "").lstrip("v")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def is_newer(tag: str | None, current: str) -> bool:
    return bool(tag) and _parse_version(str(tag)) > _parse_version(current)


def ready_text(tag: str, current: str) -> str:
    return f"Update ready — RYOS {_bare(tag)} (you have v{_bare(current)})"


def staging_text(tag: str) -> str:
    return f"Getting RYOS {_bare(tag)} ready to install…"


def waiting_text(n: int, kind: str = UPDATE) -> str:
    then = "rolls back" if kind == ROLLBACK else "restarts to update"
    return f"Waiting for {_plural(n, 'run')} to finish; then RYOS {then}."


def at_start_text(tag: str) -> str:
    return f"RYOS {_bare(tag)} installs the next time RYOS starts."


def rollback_label(version: str | None) -> str:
    if version is None:
        return "Roll back to the previous version"
    return f"Roll back to RYOS {_bare(version)}…"


def rollback_question(version: str) -> str:
    return f"Roll back RYOS to {_bare(version)}? RYOS restarts."


def blocker_words(blockers: list[Process], install: Path | str) -> str:
    first = blockers[0]
    if first.name.casefold() == swap.CLI_EXE.casefold():
        return (f"{swap.CLI_EXE} (process {first.pid}) is running from {install}, most "
                "likely an AI agent's MCP server, which stays open while the agent runs.")
    if first.name.casefold() == swap.WINDOW_EXE.casefold():
        return f"RYOS is open (process {first.pid}) from {install}."
    return f"{first.name} (process {first.pid}) is running from {install}."


def _blocked(kind: str, where: str, blockers: list[Process], install) -> str:
    words = blocker_words(blockers, install)
    first = blockers[0]
    if where == CLI:
        if first.name.casefold() == swap.WINDOW_EXE.casefold():
            return (f"RYOS is open (process {first.pid}): use Restart to update in its "
                    "window, or quit it, then run `ryos-cli update` again.")
        again = "update --rollback" if kind == ROLLBACK else "update"
        return f"{words} Close the agent and run `ryos-cli {again}` again."
    if kind == ROLLBACK:
        return f"{words} RYOS cannot roll back while it runs: close it, then try again."
    return f"{words} RYOS cannot update while it runs. Update the next time RYOS starts?"


def _not_writable(where: str, problem: str) -> str:
    if where == CLI:
        return f"{problem} Download the new version by hand from {_RELEASES_PAGE}."
    return f"{problem} The release page opens so you can download it by hand."


def obstacle(kind: str, *, where: str, install, blockers: list[Process],
             write_problem: str | None) -> Decision | None:
    """NOT_WRITABLE or BLOCKED, or None: what stops any swap, whatever is
    downloaded."""
    title = ROLLBACK_TITLE if kind == ROLLBACK else UPDATE_TITLE
    if write_problem:
        return Decision(NOT_WRITABLE, title, _not_writable(where, write_problem))
    if blockers:
        return Decision(BLOCKED, title, _blocked(kind, where, blockers, install))
    return None


def compat_warning(target: str, db_needs: int | None, previous_accepts: int) -> str:
    if db_needs is None:
        return (f"RYOS could not read your data to check which layout it needs, so "
                f"it cannot tell whether RYOS {_bare(target)} (which reads up to layout "
                f"{previous_accepts}) will open it after rolling back.")
    return (f"Your RYOS data was last opened by a RYOS that changed its layout "
            f"(it needs layout {db_needs}); RYOS {_bare(target)} reads only up to "
            f"layout {previous_accepts}, so after rolling back it will refuse to open "
            "your data until you update again.")


def decide(kind: str, *, where: str, which: str, install, current: str,
           target: str | None, blockers: list[Process], write_problem: str | None,
           active_runs: int, due: int, db_needs: int | None = 1,
           previous_accepts: int = 1) -> Decision:
    title = ROLLBACK_TITLE if kind == ROLLBACK else UPDATE_TITLE
    warning = None
    if kind == ROLLBACK and target is not None and (
            db_needs is None or db_needs > previous_accepts):
        warning = compat_warning(target, db_needs, previous_accepts)
    if which == buildinfo.PORTABLE or install is None:
        return Decision(PORTABLE, title, updates.FROM_SOURCE)
    if kind == ROLLBACK and target is None:
        return Decision(NOTHING, title, "There is no earlier build of RYOS to roll "
                        f"back to beside {install}.")
    if kind == UPDATE and target is None:
        return Decision(NOTHING, title, "No newer RYOS is downloaded and checked yet.")
    if kind == UPDATE and not is_newer(target, current):
        return Decision(NOTHING, title, f"RYOS {_bare(current)} is already installed; "
                        f"{_bare(target)} is not newer.")
    stop = obstacle(kind, where=where, install=install, blockers=blockers,
                    write_problem=write_problem)
    if stop is not None:
        return Decision(stop.verdict, stop.title, stop.text, warning)
    doing = "roll back" if kind == ROLLBACK else "restart to update"
    if active_runs:
        going = "is going" if active_runs == 1 else "are going"
        return Decision(BUSY, title, f"{_plural(active_runs, 'run')} {going}. RYOS "
                        f"never stops a run to update. {doing.capitalize()} when "
                        f"{'it has' if active_runs == 1 else 'they have'} finished?",
                        warning)
    if due:
        verb = "is" if due == 1 else "are"
        return Decision(DUE, title, f"{_plural(due, 'scheduled run')} {verb} due within "
                        f"{int(DUE_SOON.total_seconds() // 60)} minutes and will not run "
                        f"while RYOS restarts. {doing.capitalize()} now anyway?", warning)
    if where == CLI:
        if kind == ROLLBACK:
            text = f"Roll back RYOS in {install} to {_bare(target)}?"
        else:
            text = f"Update RYOS in {install} from {_bare(current)} to {_bare(target)}?"
    elif kind == ROLLBACK:
        text = rollback_question(str(target))
    else:
        text = f"RYOS restarts as {_bare(target)}."
    return Decision(GO, title, text, warning)


def running_from(folder) -> list[Process]:
    """Every process whose program lies inside ``folder``. Windows only;
    elsewhere nothing."""
    if sys.platform != "win32" or folder is None:
        return []
    import ctypes
    from ctypes import wintypes
    root = os.path.normcase(os.path.realpath(folder)).rstrip("\\/") + os.sep
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.K32EnumProcesses.argtypes = (ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
                                          ctypes.POINTER(wintypes.DWORD))
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.QueryFullProcessImageNameW.argtypes = (
        ctypes.c_void_p, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    count = 1024
    while True:
        pids = (wintypes.DWORD * count)()
        needed = wintypes.DWORD()
        if not kernel32.K32EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(needed)):
            return []
        if needed.value < ctypes.sizeof(pids):
            break
        count *= 2
    found = []
    for pid in pids[:needed.value // ctypes.sizeof(wintypes.DWORD)]:
        if not pid:
            continue
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            continue
        try:
            size = wintypes.DWORD(32768)
            buf = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                continue
            image = buf.value
        finally:
            kernel32.CloseHandle(handle)
        if os.path.normcase(image).startswith(root):
            found.append(Process(int(pid), os.path.basename(image)))
    return found


def _why(error: OSError) -> str:
    return error.strerror or str(error) or type(error).__name__


def write_problem(install) -> str | None:
    """Words for why RYOS cannot swap ``install``, or None: a folder made
    and removed beside it (the renames need its parent) and a file made and
    removed inside it."""
    install = Path(install)
    pid = os.getpid()
    probe_dir = install.parent / f"{install.name}.write-probe-{pid}"
    try:
        os.mkdir(probe_dir)
        os.rmdir(probe_dir)
    except OSError as e:
        return (f"RYOS cannot write in {install.parent} ({_why(e)}), which it needs "
                f"to swap the build in {install}.")
    probe_file = install / f".write-probe-{pid}"
    try:
        with open(probe_file, "xb"):
            pass
        os.remove(probe_file)
    except OSError as e:
        return f"RYOS cannot write in {install} ({_why(e)})."
    return None


def due_soon(db, now, within: timedelta = DUE_SOON) -> int:
    return len(db.due_schedules(now + within))


def _no_processes(_folder) -> list[Process]:
    return []


def _no_problem(_install) -> str | None:
    return None


def _nothing_staged(_tag: str) -> Path | None:
    return None


def _no_spawn(_argv: list, _cwd: Path) -> None:
    return None


@dataclass
class Updater:
    install: Path | None = None
    which: str = buildinfo.PORTABLE
    running_from: Callable[[Path], list[Process]] = _no_processes
    write_problem: Callable[[Path], str | None] = _no_problem
    staged: Callable[[str], Path | None] = _nothing_staged
    spawn: Callable[[list, Path], None] = _no_spawn
    effects: swap.Effects = field(default_factory=swap.Effects)
    pid: int = field(default_factory=os.getpid)

    def blockers(self) -> list[Process]:
        if self.install is None:
            return []
        return [p for p in self.running_from(self.install) if p.pid != self.pid]

    def problem(self) -> str | None:
        return None if self.install is None else self.write_problem(self.install)


def real() -> Updater:
    from .settings import _BASE, _PACKAGED
    which = buildinfo.variant()
    if not _PACKAGED or which == buildinfo.PORTABLE:
        return Updater()
    return Updater(install=Path(_BASE), which=which, running_from=running_from,
                   write_problem=write_problem, staged=updates.downloaded,
                   spawn=swap._spawn)


def prepare(updater: Updater, kind: str, *, tag: str | None, current: str,
            compatible_from: int, restart: bool) -> tuple[list[str], Path]:
    """Stage the helper and return its command line and folder. Raises
    swap.SwapError with words."""
    install = updater.install
    if install is None:
        raise swap.SwapError(updates.FROM_SOURCE)
    try:
        if kind == UPDATE:
            zip_path = updater.staged(str(tag)) if tag else None
            if zip_path is None:
                raise swap.SwapError(f"RYOS {_bare(tag)} is no longer downloaded and "
                                     "checked, so it cannot be installed.")
            exe = swap.stage_helper(zip_path, str(tag), updater.effects, which=updater.which)
            argv = swap.helper_argv(exe, install, version=str(tag), from_version=current,
                                    wait_pids=[updater.pid], restart=restart,
                                    from_compatible=compatible_from)
        else:
            if swap.previous_build(install, check_files=True) is None:
                raise swap.SwapError("There is no earlier build of RYOS to roll back to "
                                     f"beside {install}, or it has changed since.")
            exe = swap.stage_rollback_helper(install, updater.effects)
            argv = swap.helper_argv(exe, install, rollback=True, from_version=current,
                                    wait_pids=[updater.pid], restart=restart,
                                    from_compatible=compatible_from)
    except OSError as e:
        raise swap.SwapError(f"RYOS could not get the update ready: {_why(e)}.") from None
    return argv, exe.parent


def _at_start_path(install) -> Path:
    return swap.journal_dir_for(install) / AT_START_NAME


def request_at_start(install, tag: str) -> None:
    path = _at_start_path(install)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"install": str(install), "tag": tag}), encoding="utf-8")


def pending_at_start(install) -> str | None:
    try:
        data = json.loads(_at_start_path(install).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (not isinstance(data, dict) or not isinstance(data.get("tag"), str)
            or not isinstance(data.get("install"), str)
            or not swap._same_path(data["install"], install)):
        return None
    return data["tag"]


def clear_at_start(install) -> None:
    try:
        os.remove(_at_start_path(install))
    except FileNotFoundError:
        pass


IN_PROGRESS_NOTE = ("warning", "Update in progress",
                    "Another update or roll back of RYOS is still going; RYOS opened "
                    "as it is. Look in ryos-cli.log for what happened.")


def _wait_for_lock(updater: Updater, jdir: Path, wait_seconds: float) -> bool:
    if not jdir.is_dir():
        return True
    waited = 0.0
    while True:
        release = updater.effects.hold_lock(jdir / swap.LOCK_NAME)
        if release is not None:
            release()
            return True
        if waited >= wait_seconds:
            return False
        updater.effects.sleep(LOCK_POLL)
        waited += LOCK_POLL


def _journal_note(updater: Updater, jdir: Path) -> tuple[str, str, str] | None:
    journal = swap.read_journal(jdir)
    if (journal is None or journal["state"] not in (swap.DONE, swap.UNDONE)
            or not journal.get("restart") or journal.get("shown")
            or not journal.get("message")):
        return None
    release = updater.effects.hold_lock(jdir / swap.LOCK_NAME)
    if release is None:
        return None
    try:
        journal["shown"] = True
        try:
            updater.effects.save_journal(jdir / swap.JOURNAL_NAME, journal)
        except OSError:
            return None
    finally:
        release()
    title = ROLLBACK_TITLE if journal["kind"] == ROLLBACK else UPDATE_TITLE
    level = "info" if journal["state"] == swap.DONE else "warning"
    return level, title, str(journal["message"])


def at_start(current: str, updater: Updater, *, compatible_from: int,
             wait_seconds: float = 10) -> AtStart:
    """Start-up, before the window: wait for a helper still at work, accept
    whichever whole build is in place, say once what the last update or
    roll back did, and carry out an update asked for "the next time RYOS
    starts" (``applying``: then RYOS exits for the helper)."""
    install = updater.install
    if install is None:
        return AtStart(False, ())
    jdir = swap.journal_dir_for(install)
    notes: list[tuple[str, str, str]] = []
    if not _wait_for_lock(updater, jdir, wait_seconds):
        return AtStart(False, (IN_PROGRESS_NOTE,))
    settled = swap.settle_at_start(install, jdir, updater.effects)
    if settled is not None and settled.code == swap.STUCK:
        notes.append(("warning", UPDATE_TITLE, settled.message))
    else:
        note = _journal_note(updater, jdir)
        if note is not None:
            notes.append(note)
    tag = pending_at_start(install)
    if tag is None:
        return AtStart(False, tuple(notes))
    if not is_newer(tag, current) or updater.staged(tag) is None:
        clear_at_start(install)
        return AtStart(False, tuple(notes))
    blockers = updater.blockers()
    problem = updater.problem()
    stop = obstacle(UPDATE, where=WINDOW, install=install, blockers=blockers,
                    write_problem=problem)
    if stop is not None:
        why = (blocker_words(blockers, install) if stop.verdict == BLOCKED
               else _not_writable(CLI, str(problem)))
        notes.append(("info", UPDATE_TITLE, f"RYOS {_bare(tag)} is still waiting to be "
                      f"installed: {why} RYOS tries again the next time it starts."))
        return AtStart(False, tuple(notes))
    clear_at_start(install)
    try:
        argv, cwd = prepare(updater, UPDATE, tag=tag, current=current,
                            compatible_from=compatible_from, restart=True)
        updater.spawn(argv, cwd)
    except (swap.SwapError, OSError) as e:
        notes.append(("warning", UPDATE_TITLE, str(e)))
        return AtStart(False, tuple(notes))
    return AtStart(True, tuple(notes))
