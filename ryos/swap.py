"""Apply a downloaded update, or roll one back, by swapping folders beside the
install: the new build is extracted to ``<install>.incoming``, checked, and
put in place with two renames, the old one kept as ``<install>.previous``.

Toolkit-free; every file-system and process effect is a field of ``Effects``
(the real one unless a caller passes another), so tests inject failures and
crashes at each step. A journal (``swap.json`` in the updates folder) names
each step before it is taken, so ``recover`` can finish or undo a swap a
crash left behind. Each install keeps its own journal, lock and
``previous.json`` in ``journal_dir_for(install)``. ``ryos-cli apply-update``
runs it (``cli.py``); ``selfupdate.py`` decides when; the plan and decisions
are in docs/plans/release-2.4.0.md, steps 9 and 10.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, NamedTuple

FORMAT = 1
JOURNAL_NAME = "swap.json"
LOCK_NAME = "swap.lock"
PREVIOUS_NAME = "previous.json"

DONE = "done"
UNDONE = "undone"
REFUSED = "refused"
STUCK = "stuck"

UPDATE = "update"
ROLLBACK = "rollback"

RENAME_DELAYS = (0.25, 0.5, 1, 2, 4, 8, 15, 15, 15)
WAIT_SECONDS = 120.0

WINDOW_EXE = "RYOS.exe"
CLI_EXE = "ryos-cli.exe"
_NEEDS = {"windows": (WINDOW_EXE, CLI_EXE), "windows-ai": (WINDOW_EXE, CLI_EXE),
          "agent": (CLI_EXE,)}

_PRE_SWAP = {UPDATE: ("prepare", "extract", "check"), ROLLBACK: ("prepare",)}
_STATES = {UPDATE: {"prepare", "extract", "check", "swap", "verify", "restart",
                    "unswap", DONE, UNDONE},
           ROLLBACK: {"prepare", "swap", "verify", "restart", "settle",
                      "unswap", DONE, UNDONE}}

BLAMES = ("RYOS or ryos-cli (an agent's MCP server) may still be running, "
          "or antivirus may be scanning it")
IN_PROGRESS = "Another update or roll back of RYOS is in progress."
NOT_EXITED = "not-exited"

_NEW, _OLD, _MID = "new", "old", "mid"


class SwapError(Exception):
    pass


class UnsafeZip(SwapError):
    pass


class _Failed(Exception):
    pass


class _Stuck(Exception):
    pass


@dataclass(frozen=True)
class Folders:
    install: Path
    previous: Path
    incoming: Path
    incoming_part: Path
    outgoing: Path


class PreviousBuild(NamedTuple):
    version: str
    compatible_from: int


@dataclass(frozen=True)
class SwapResult:
    code: str
    state: str | None
    message: str
    restarted: bool = False


def folders_for(install: str | os.PathLike) -> Folders:
    path = Path(os.path.abspath(install))
    if path.parent == path or not path.name:
        raise ValueError(f"RYOS cannot be updated in {path}: it is a drive's root.")

    def beside(suffix: str) -> Path:
        return path.with_name(path.name + suffix)
    return Folders(path, beside(".previous"), beside(".incoming"),
                   beside(".incoming.part"), beside(".outgoing"))


def _same_path(a: str | os.PathLike, b: str | os.PathLike) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def zip_manifest(zip_path: str | os.PathLike, which: str) -> dict[str, int]:
    """Every file in the zip and its size; raises UnsafeZip for a name that
    could land outside the folder, a link, or a zip without this download's
    programs."""
    needs = _NEEDS.get(which)
    if needs is None:
        raise UnsafeZip(f"There is no update for this download ({which}).")
    name_of = Path(zip_path).name
    try:
        with zipfile.ZipFile(zip_path) as archive:
            infos = archive.infolist()
    except (OSError, zipfile.BadZipFile) as e:
        raise UnsafeZip(f"{name_of} cannot be read as a zip: {e}") from None
    manifest: dict[str, int] = {}
    seen: set[str] = set()
    for info in infos:
        name = info.filename
        if "\\" in name or ":" in name or name.startswith("/"):
            raise UnsafeZip(f"{name_of} holds {name!r}, a path outside its folder.")
        parts = name.rstrip("/").split("/") if info.is_dir() else name.split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise UnsafeZip(f"{name_of} holds {name!r}, a path outside its folder.")
        if stat.S_ISLNK(info.external_attr >> 16):
            raise UnsafeZip(f"{name_of} holds {name!r}, a link.")
        if info.is_dir():
            continue
        folded = name.casefold()
        if folded in seen:
            raise UnsafeZip(f"{name_of} holds {name!r} twice (ignoring case).")
        seen.add(folded)
        manifest[name] = info.file_size
    missing = [exe for exe in needs if exe not in manifest]
    if missing:
        raise UnsafeZip(f"{name_of} has no {', '.join(missing)}: it is not this "
                        "download's update.")
    return manifest


def extract_zip(zip_path: str | os.PathLike, dest: str | os.PathLike,
                manifest: dict[str, int]) -> None:
    root = os.path.realpath(dest)
    os.makedirs(root, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.is_dir() or info.filename not in manifest:
                continue
            target = os.path.realpath(os.path.join(root, *info.filename.split("/")))
            if os.path.commonpath([root, target]) != root:
                raise UnsafeZip(f"{info.filename!r} would land outside {dest}.")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with archive.open(info) as source, open(target, "xb") as out:
                shutil.copyfileobj(source, out, 1024 * 1024)


def tree_listing(folder: str | os.PathLike) -> dict[str, int]:
    """Every file under ``folder`` (relative, with /) and its size."""
    found: dict[str, int] = {}
    folder = os.fspath(folder)
    for here, _dirs, files in os.walk(folder):
        for name in files:
            full = os.path.join(here, name)
            rel = os.path.relpath(full, folder).replace(os.sep, "/")
            found[rel] = os.path.getsize(full)
    return found


def tree_problems(expected: dict[str, int], actual: dict[str, int]) -> list[str]:
    problems = [f"{name} is missing" for name in sorted(set(expected) - set(actual))]
    problems += [f"{name} should not be there" for name in sorted(set(actual) - set(expected))]
    problems += [f"{name} is {actual[name]} bytes, not {expected[name]}"
                 for name in sorted(set(expected) & set(actual))
                 if actual[name] != expected[name]]
    return problems


def _rename(src: Path, dst: Path) -> None:
    if os.path.lexists(dst):
        raise FileExistsError(errno.EEXIST, "already there", str(dst))
    os.rename(src, dst)


def _remove_tree(path: Path) -> None:
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    elif os.path.lexists(path):
        os.remove(path)


def _remove_file(path: Path) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _copy_tree(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst)


def _wait_for_exit(pid: int, timeout: float) -> bool:
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        handle = kernel32.OpenProcess(0x00100000, False, int(pid))
        if not handle:
            return True
        try:
            return kernel32.WaitForSingleObject(handle, int(timeout * 1000)) == 0
        finally:
            kernel32.CloseHandle(handle)
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.kill(int(pid), 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def _spawn(argv: list[str], cwd: Path) -> None:
    if sys.platform == "win32":
        subprocess.Popen(argv, cwd=str(cwd), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         close_fds=True,
                         creationflags=subprocess.DETACHED_PROCESS
                         | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        subprocess.Popen(argv, cwd=str(cwd), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         close_fds=True, start_new_session=True)


def _save_json(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _hold_lock(path: Path) -> Callable[[], None] | None:
    fh = open(path, "a+b")
    try:
        if sys.platform == "win32":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None

    def release() -> None:
        try:
            if sys.platform == "win32":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        fh.close()
    return release


@dataclass
class Effects:
    rename: Callable[[Path, Path], None] = _rename
    remove_tree: Callable[[Path], None] = _remove_tree
    remove_file: Callable[[Path], None] = _remove_file
    copy_tree: Callable[[Path, Path], None] = _copy_tree
    extract: Callable[[Path, Path, dict], None] = extract_zip
    listing: Callable[[Path], dict] = tree_listing
    wait_for_exit: Callable[[int, float], bool] = _wait_for_exit
    spawn: Callable[[list, Path], None] = _spawn
    sleep: Callable[[float], None] = time.sleep
    save_journal: Callable[[Path, dict], None] = _save_json
    hold_lock: Callable[[Path], Callable[[], None] | None] = _hold_lock


def _retrying(effects: Effects, action: Callable[[], None]) -> None:
    for delay in (*RENAME_DELAYS, None):
        try:
            action()
            return
        except (FileExistsError, FileNotFoundError):
            raise
        except OSError:
            if delay is None:
                raise
            effects.sleep(delay)


def retry_rename(effects: Effects, src: Path, dst: Path) -> None:
    _retrying(effects, lambda: effects.rename(src, dst))


def _updates_root() -> Path:
    from .settings import updates_root
    return updates_root()


def journal_dir_for(install: str | os.PathLike) -> Path:
    key = os.path.normcase(os.path.realpath(install))
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return _updates_root() / "installs" / digest


def _journal_dir(journal_dir: str | os.PathLike | None,
                 install: str | os.PathLike) -> Path:
    return Path(journal_dir) if journal_dir is not None else journal_dir_for(install)


def read_journal(journal_dir: str | os.PathLike) -> dict | None:
    return _read_journal(Path(journal_dir))


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _read_journal(jdir: Path) -> dict | None:
    data = _read_json(jdir / JOURNAL_NAME)
    if (data is None or data.get("format") != FORMAT
            or data.get("kind") not in _STATES
            or data.get("state") not in _STATES[data["kind"]]
            or not isinstance(data.get("install"), str)
            or not isinstance(data.get("files"), dict)):
        return None
    return data


def _read_previous(jdir: Path, install: Path) -> dict | None:
    data = _read_json(jdir / PREVIOUS_NAME)
    if (data is None or data.get("format") != FORMAT
            or not isinstance(data.get("install"), str)
            or not _same_path(data["install"], install)
            or not isinstance(data.get("files"), dict)):
        return None
    return data


def _detail(error: BaseException) -> str:
    return str(error) or type(error).__name__


class _Swap:
    def __init__(self, folders: Folders, effects: Effects, jdir: Path, journal: dict):
        self.f = folders
        self.effects = effects
        self.jdir = jdir
        self.journal = journal
        if journal["kind"] == UPDATE:
            self.other, self.park = folders.incoming, folders.previous
        else:
            self.other, self.park = folders.previous, folders.outgoing

    @property
    def kind(self) -> str:
        return self.journal["kind"]

    @property
    def state(self) -> str:
        return self.journal["state"]

    def enter(self, state: str, message: str | None = None) -> None:
        self.journal["state"] = state
        if message is not None:
            self.journal["message"] = message
        self.effects.save_journal(self.jdir / JOURNAL_NAME, self.journal)

    def end(self, code: str, message: str, restarted: bool = False) -> SwapResult:
        self.enter(code, message)
        return SwapResult(code, code, message, restarted)

    def layout(self) -> str | None:
        i, o, p = (os.path.lexists(x) for x in (self.f.install, self.other, self.park))
        if i and p and not o:
            return _NEW
        if i and not p and (o or self.kind == UPDATE):
            return _OLD
        if not i and o and p:
            return _MID
        return None

    def forward(self) -> None:
        found = self.layout()
        if found == _OLD:
            retry_rename(self.effects, self.f.install, self.park)
            retry_rename(self.effects, self.other, self.f.install)
        elif found == _MID:
            retry_rename(self.effects, self.other, self.f.install)
        elif found != _NEW:
            raise _Stuck()

    def back(self) -> None:
        found = self.layout()
        if found == _NEW:
            retry_rename(self.effects, self.f.install, self.other)
            retry_rename(self.effects, self.park, self.f.install)
        elif found == _MID:
            retry_rename(self.effects, self.park, self.f.install)
        elif found != _OLD:
            raise _Stuck()

    def clean(self, *paths: Path) -> list[str]:
        left = []
        for path in paths:
            try:
                _retrying(self.effects, lambda: self.effects.remove_tree(path))
            except OSError:
                left.append(str(path))
        return left

    def discard(self) -> list[str]:
        if self.kind == UPDATE:
            self.effects.remove_file(self.jdir / PREVIOUS_NAME)
            return self.clean(self.f.incoming_part, self.f.incoming, self.f.previous)
        return self.clean(self.f.outgoing)

    def after_back(self) -> list[str]:
        if self.kind == UPDATE:
            self.effects.remove_file(self.jdir / PREVIOUS_NAME)
            return self.clean(self.f.incoming, self.f.incoming_part)
        return []

    def write_previous(self, folder: Path, version: str | None) -> None:
        record = {"format": FORMAT, "install": str(self.f.install), "version": version,
                  "files": self.effects.listing(folder)}
        if self.journal.get("from_compatible") is not None:
            record["compatible_from"] = self.journal["from_compatible"]
        self.effects.save_journal(self.jdir / PREVIOUS_NAME, record)

    def verify(self) -> None:
        if self.kind == UPDATE:
            self.write_previous(self.f.previous, self.journal.get("from_version"))
        problems = tree_problems(self.journal["files"], self.effects.listing(self.f.install))
        if problems:
            raise _Failed(f"after the swap {self.f.install} is not what was checked: "
                          + "; ".join(problems[:5]))

    def settle(self) -> None:
        outgoing, previous = self.f.outgoing, self.f.previous
        version = self.journal.get("from_version")
        if os.path.lexists(outgoing) and not os.path.lexists(previous):
            self.write_previous(outgoing, version)
            retry_rename(self.effects, outgoing, previous)
        elif os.path.lexists(previous) and not os.path.lexists(outgoing):
            self.write_previous(previous, version)
        else:
            raise _Stuck()

    def finish_forward(self) -> None:
        if self.kind == UPDATE:
            self.write_previous(self.f.previous, self.journal.get("from_version"))
        else:
            self.enter("settle")
            self.settle()

    def start(self) -> None:
        self.effects.spawn([str(self.f.install / WINDOW_EXE)], self.f.install)

    def words(self, error: BaseException) -> str:
        doing = "updated" if self.kind == UPDATE else "rolled back"
        return (f"RYOS in {self.f.install} could not be {doing}: {_detail(error)}. "
                f"{BLAMES}. The build that was there is back, as it was.")

    def stuck_words(self, error: BaseException | None = None) -> str:
        why = f" ({_detail(error)})" if error is not None and _detail(error) != "_Stuck" else ""
        return (f"RYOS could not put {self.f.install} back together{why}: one build may "
                f"be in {self.other} and the other in {self.park}. {BLAMES}. Close "
                "them, then run `ryos-cli apply-update --install "
                f"\"{self.f.install}\" --recover`.")

    def stuck(self, error: BaseException | None = None) -> SwapResult:
        message = self.stuck_words(error)
        self.journal["message"] = message
        try:
            self.effects.save_journal(self.jdir / JOURNAL_NAME, self.journal)
        except OSError:
            pass
        return SwapResult(STUCK, self.state, message)

    def undo(self, error: BaseException) -> SwapResult:
        message = self.words(error)
        try:
            if self.state in _PRE_SWAP[self.kind]:
                left = self.discard()
            else:
                self.enter("unswap", message)
                self.back()
                left = self.after_back()
        except Exception as e:
            return self.stuck(e)
        if left:
            message += f" Left to delete: {', '.join(left)}."
        restarted = False
        if self.journal.get("restart"):
            try:
                self.start()
                restarted = True
            except Exception:
                pass
        return self.end(UNDONE, message, restarted)

    def run(self, steps: Callable[[], None]) -> SwapResult:
        try:
            steps()
            restarted = False
            if self.journal.get("restart"):
                self.enter("restart", self.done_words())
                self.start()
                restarted = True
        except _Stuck as e:
            return self.stuck(e)
        except Exception as e:
            return self.undo(e)
        message = self.done_words()
        if self.kind == ROLLBACK:
            try:
                self.enter("settle")
                self.settle()
            except (OSError, _Stuck) as e:
                return SwapResult(DONE, self.state, message + f" ({self.f.outgoing} is "
                                  f"left to tidy up: {_detail(e)}.)", restarted)
        try:
            return self.end(DONE, message, restarted)
        except OSError:
            return SwapResult(DONE, self.state, message, restarted)

    def done_words(self) -> str:
        version = self.journal.get("version") or "the other build"
        if self.kind == UPDATE:
            return f"RYOS in {self.f.install} is now {version}; the old build is in {self.f.previous}."
        return f"RYOS in {self.f.install} is back to {version}; the build it replaced is in {self.f.previous}."


def _new_journal(kind: str, folders: Folders, *, version, from_version, zip_path,
                 restart: bool, files: dict, from_compatible: int | None = None) -> dict:
    return {"format": FORMAT, "kind": kind, "install": str(folders.install),
            "version": version, "from_version": from_version,
            "from_compatible": from_compatible,
            "zip": None if zip_path is None else str(zip_path),
            "restart": restart, "helper_pid": os.getpid(), "state": "prepare",
            "message": "", "files": files}


def _waited(effects: Effects, wait_pids: Iterable[int], seconds: float) -> SwapResult | None:
    for pid in wait_pids:
        if not effects.wait_for_exit(pid, seconds):
            return SwapResult(REFUSED, NOT_EXITED, f"RYOS (process {pid}) did not exit within "
                              f"{seconds:g} seconds, so nothing was changed.")
    return None


def _locked(effects: Effects, jdir: Path, body: Callable[[], SwapResult]) -> SwapResult:
    jdir.mkdir(parents=True, exist_ok=True)
    release = effects.hold_lock(jdir / LOCK_NAME)
    if release is None:
        return SwapResult(REFUSED, None, IN_PROGRESS)
    try:
        return body()
    finally:
        release()


def _settle_pending(effects: Effects, jdir: Path) -> SwapResult | None:
    journal = _read_journal(jdir)
    if journal is None or journal["state"] in (DONE, UNDONE):
        return None
    settled = _recover_locked(jdir, effects, journal, True)
    return settled if settled.code == STUCK else None


def apply_update(install: str | os.PathLike, zip_path: str | os.PathLike, *,
                 version: str, from_version: str | None = None,
                 which: str | None = None, wait_pids: Iterable[int] = (),
                 restart: bool = False, effects: Effects | None = None,
                 journal_dir: str | os.PathLike | None = None,
                 wait_seconds: float = WAIT_SECONDS,
                 from_compatible: int | None = None) -> SwapResult:
    effects = effects or Effects()
    if which is None:
        from . import buildinfo
        which = buildinfo.variant()
    try:
        folders = folders_for(install)
        manifest = zip_manifest(zip_path, which)
    except (ValueError, UnsafeZip) as e:
        return SwapResult(REFUSED, None, str(e))
    refused = _waited(effects, wait_pids, wait_seconds)
    if refused is not None:
        return refused
    jdir = _journal_dir(journal_dir, folders.install)

    def body() -> SwapResult:
        stuck = _settle_pending(effects, jdir)
        if stuck is not None:
            return stuck
        if not folders.install.is_dir():
            return SwapResult(REFUSED, None, f"There is no RYOS folder at {folders.install}.")
        journal = _new_journal(UPDATE, folders, version=version, from_version=from_version,
                               zip_path=zip_path, files=manifest,
                               restart=bool(restart) and WINDOW_EXE in manifest,
                               from_compatible=from_compatible)
        run = _Swap(folders, effects, jdir, journal)

        def steps() -> None:
            run.enter("prepare")
            effects.remove_file(jdir / PREVIOUS_NAME)
            for path in (folders.previous, folders.incoming, folders.incoming_part):
                _retrying(effects, lambda: effects.remove_tree(path))
            run.enter("extract")
            effects.extract(Path(zip_path), folders.incoming_part, manifest)
            run.enter("check")
            problems = tree_problems(manifest, effects.listing(folders.incoming_part))
            if problems:
                raise _Failed("the extracted files are not the zip's: "
                              + "; ".join(problems[:5]))
            retry_rename(effects, folders.incoming_part, folders.incoming)
            run.enter("swap")
            run.forward()
            run.enter("verify")
            run.verify()
        return run.run(steps)
    return _locked(effects, jdir, body)


def roll_back(install: str | os.PathLike, *, wait_pids: Iterable[int] = (),
              restart: bool = False, from_version: str | None = None,
              effects: Effects | None = None,
              journal_dir: str | os.PathLike | None = None,
              wait_seconds: float = WAIT_SECONDS,
              from_compatible: int | None = None) -> SwapResult:
    effects = effects or Effects()
    try:
        folders = folders_for(install)
    except ValueError as e:
        return SwapResult(REFUSED, None, str(e))
    refused = _waited(effects, wait_pids, wait_seconds)
    if refused is not None:
        return refused
    jdir = _journal_dir(journal_dir, folders.install)

    def body() -> SwapResult:
        stuck = _settle_pending(effects, jdir)
        if stuck is not None:
            return stuck
        previous = _read_previous(jdir, folders.install)
        if previous is None or not folders.previous.is_dir() or not folders.install.is_dir():
            return SwapResult(REFUSED, None, "There is no earlier build of RYOS to roll "
                              f"back to beside {folders.install}.")
        if effects.listing(folders.previous) != previous["files"]:
            return SwapResult(REFUSED, None, f"{folders.previous} is no longer the build "
                              "that was moved out, so RYOS will not roll back to it.")
        files = previous["files"]
        journal = _new_journal(ROLLBACK, folders, version=previous.get("version"),
                               from_version=from_version, zip_path=None, files=files,
                               restart=bool(restart) and WINDOW_EXE in files,
                               from_compatible=from_compatible)
        run = _Swap(folders, effects, jdir, journal)

        def steps() -> None:
            run.enter("prepare")
            _retrying(effects, lambda: effects.remove_tree(folders.outgoing))
            run.enter("swap")
            run.forward()
            run.enter("verify")
            run.verify()
        return run.run(steps)
    return _locked(effects, jdir, body)


def _recover_locked(jdir: Path, effects: Effects, journal: dict,
                    may_move_install: bool) -> SwapResult:
    run = _Swap(folders_for(journal["install"]), effects, jdir, journal)
    state = run.state
    try:
        if state in _PRE_SWAP[run.kind]:
            left = run.discard()
            note = f" Left to delete: {', '.join(left)}." if left else ""
            return run.end(UNDONE, "An unfinished change to RYOS was undone before "
                           "anything was swapped." + note)
        if state == "settle":
            run.settle()
            return run.end(DONE, run.done_words())
        found = run.layout()
        if not may_move_install:
            if found == _NEW and state in ("swap", "verify", "unswap") and tree_problems(
                    journal["files"], effects.listing(run.f.install)):
                return run.stuck()
            if found == _NEW:
                run.finish_forward()
                kept = " (it was already in place, so it was kept)" if state == "unswap" else ""
                return run.end(DONE, run.done_words() + kept)
            if found == _OLD:
                run.after_back()
                return run.end(UNDONE, "An unfinished change to RYOS was undone.")
            return run.stuck()
        if state == "restart" and run.kind == UPDATE and found == _NEW:
            return run.end(DONE, run.done_words())
        if state == "unswap" or found != _NEW:
            run.enter("unswap")
            run.back()
            run.after_back()
            return run.end(UNDONE, "An unfinished change to RYOS was undone.")
        run.enter("verify")
        try:
            run.verify()
        except _Failed as e:
            message = run.words(e)
            run.enter("unswap", message)
            run.back()
            run.after_back()
            return run.end(UNDONE, message)
        if run.kind == ROLLBACK:
            run.enter("settle")
            run.settle()
        return run.end(DONE, run.done_words())
    except _Stuck as e:
        return run.stuck(e)
    except OSError as e:
        return run.stuck(e)


def recover(journal_dir: str | os.PathLike, effects: Effects | None = None, *,
            may_move_install: bool = True) -> SwapResult | None:
    """Finish or undo a swap a crash left behind; None when there is none,
    another helper holds the lock, or the journal is not one RYOS knows."""
    effects = effects or Effects()
    jdir = Path(journal_dir)
    journal = _read_journal(jdir)
    if journal is None or journal["state"] in (DONE, UNDONE):
        return None
    release = effects.hold_lock(jdir / LOCK_NAME)
    if release is None:
        return None
    try:
        journal = _read_journal(jdir)
        if journal is None or journal["state"] in (DONE, UNDONE):
            return None
        return _recover_locked(jdir, effects, journal, may_move_install)
    finally:
        release()


def settle_at_start(install: str | os.PathLike,
                    journal_dir: str | os.PathLike | None = None,
                    effects: Effects | None = None) -> SwapResult | None:
    """The window's start-up: accept whichever whole build is in place and
    tidy the rest, never moving the folder it runs from."""
    jdir = _journal_dir(journal_dir, install)
    journal = _read_journal(jdir)
    if journal is None or not _same_path(journal["install"], install):
        return None
    return recover(jdir, effects, may_move_install=False)


def _compatible(value) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1


def previous_build(install: str | os.PathLike,
                   journal_dir: str | os.PathLike | None = None, *,
                   check_files: bool = True) -> PreviousBuild | None:
    """What ``<install>.previous`` holds -- its version and the oldest
    database layout it accepts -- when it is still what was moved out
    (``check_files`` lists it again); None otherwise."""
    try:
        folders = folders_for(install)
    except ValueError:
        return None
    jdir = _journal_dir(journal_dir, folders.install)
    previous = _read_previous(jdir, folders.install)
    if previous is None or not folders.previous.is_dir():
        return None
    if check_files:
        try:
            if tree_listing(folders.previous) != previous["files"]:
                return None
        except OSError:
            return None
    return PreviousBuild(str(previous.get("version") or "unknown"),
                         _compatible(previous.get("compatible_from", 1)))


def rollback_available(install: str | os.PathLike,
                       journal_dir: str | os.PathLike | None = None) -> str | None:
    """The version ``<install>.previous`` holds, when it is still what was
    moved out; None otherwise."""
    found = previous_build(install, journal_dir)
    return None if found is None else found.version


def stage_helper(zip_path: str | os.PathLike, version: str,
                 effects: Effects | None = None, which: str | None = None) -> Path:
    """Extract the checked zip into ``updates/<version>/helper/`` and return
    its ryos-cli.exe, which runs the swap from outside both folders."""
    effects = effects or Effects()
    if which is None:
        from . import buildinfo
        which = buildinfo.variant()
    from .settings import updates_dir
    dest = updates_dir(version) / "helper"
    manifest = zip_manifest(zip_path, which)
    effects.remove_tree(dest)
    effects.extract(Path(zip_path), dest, manifest)
    problems = tree_problems(manifest, effects.listing(dest))
    if problems:
        raise SwapError(f"The helper in {dest} is not the zip's: " + "; ".join(problems[:5]))
    return dest / CLI_EXE


def stage_rollback_helper(install: str | os.PathLike,
                          effects: Effects | None = None) -> Path:
    """Copy the installed build to ``rollback-helper/`` in its journal folder
    and return its ryos-cli.exe."""
    effects = effects or Effects()
    source = Path(os.path.abspath(install))
    dest = journal_dir_for(source) / "rollback-helper"
    effects.remove_tree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    effects.copy_tree(source, dest)
    if effects.listing(dest) != effects.listing(source):
        raise SwapError(f"The copy of RYOS in {dest} does not match {source}.")
    if not (dest / CLI_EXE).is_file():
        raise SwapError(f"There is no {CLI_EXE} in {source}.")
    return dest / CLI_EXE


def helper_argv(helper_exe: str | os.PathLike, install: str | os.PathLike, *,
                version: str | None = None, rollback: bool = False,
                from_version: str | None = None, wait_pids: Iterable[int] = (),
                restart: bool = False, from_compatible: int | None = None) -> list[str]:
    if rollback == (version is not None):
        raise ValueError("give a version to update to, or rollback, not both")
    argv = [str(helper_exe), "apply-update", "--install", str(install)]
    argv += ["--rollback"] if rollback else ["--version", str(version)]
    if from_version:
        argv += ["--from-version", from_version]
    if from_compatible is not None:
        argv += ["--from-compatible", str(int(from_compatible))]
    for pid in wait_pids:
        argv += ["--wait-pid", str(int(pid))]
    if restart:
        argv.append("--restart")
    return argv
