"""The Quick Run file index: cache, single-flight, and background rebuild.

``quickrun.py`` holds the pure decisions (what to index, how to rank, how to
resolve a query). This module holds the *state* around them — the in-memory
cache, the on-disk cache, and the rule that only one scan per base directory
runs at a time.

It is UI-free. The one thing it cannot do for itself is hop back onto the main
thread, so the caller injects a ``schedule`` function (Tk's ``after(0, ...)``,
Qt's ``QTimer.singleShot(0, ...)``) and a ``on_ready`` callback to refresh
whatever is showing. That is the same shape as ``JobController``, and it is
what lets this survive the Qt migration (docs/plans/qt-migration.md).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Callable

from .logger import get_logger
from .quickrun import (_SKIP_DIRS, build_entry, deserialize_index,
                       rank_suggestions, serialize_index, should_index)
from .settings import QR_INDEX_DIR

_log = get_logger("quickrun_index")

# Bump when the on-disk payload shape changes; older files are then ignored
# and rebuilt rather than misread.
INDEX_VERSION = 2

# Pruned in place during os.walk, which is why os.walk is used over rglob --
# rglob would enumerate everything under node_modules/.git before anything
# could discard it. Shared with quickrun.resolve() so the two cannot disagree
# about what is indexable.
SKIP_DIRS = _SKIP_DIRS


def index_path(base_dir: str) -> Path:
    """Where this base directory's on-disk cache lives."""
    key = os.path.normcase(os.path.normpath(base_dir))
    h = hashlib.md5(key.encode()).hexdigest()[:12]
    return QR_INDEX_DIR / f"qr_index_{h}.json"


def load_disk_index(base_dir: str, ttl: float) -> "tuple[float, list] | None":
    """The cached index for ``base_dir``, or None if absent, stale or unusable."""
    try:
        t0 = time.monotonic()
        data = json.loads(index_path(base_dir).read_text(encoding="utf-8"))
        # Written by an older format -- rebuild rather than misread.
        if data.get("v") != INDEX_VERSION:
            return None
        # Hash-collision guard: the stored base_dir must match exactly.
        if data["base_dir"] != base_dir:
            return None
        if time.time() - data["ts"] >= ttl:
            return None
        paths = deserialize_index(data["paths"])
        _log.info("Quick Run index: loaded %d entries from disk in %.0f ms (%s)",
                  len(paths), (time.monotonic() - t0) * 1000, base_dir)
        return (data["ts"], paths)
    except (OSError, ValueError, KeyError, TypeError) as e:
        _log.debug("Quick Run index cache unreadable for %s: %s", base_dir, e)
        return None


def save_disk_index(base_dir: str, wall_ts: float, paths: list) -> None:
    """Write the index for ``base_dir``, atomically."""
    try:
        dest = index_path(base_dir)
        tmp = Path(str(dest) + ".tmp")
        payload = {"v": INDEX_VERSION, "base_dir": base_dir, "ts": wall_ts,
                   "paths": serialize_index(paths)}
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        # Atomic swap, so a concurrent read never sees a partial file.
        os.replace(tmp, dest)
    except OSError as e:
        _log.debug("Could not write Quick Run index cache for %s: %s", base_dir, e)


def scan(base_dir: str, allowed_exts: set, max_files: int) -> tuple[list, bool]:
    """Walk ``base_dir`` and build index entries. Returns ``(entries, capped)``.

    Pure apart from the filesystem read, and the slow part of the whole
    subsystem -- which is why it runs on a worker thread.
    """
    paths: list = []
    capped = False
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if not should_index(fn, allowed_exts):
                continue
            full = os.path.join(root, fn)
            try:
                rel_str = os.path.relpath(full, base_dir)
            except ValueError:
                rel_str = fn
            paths.append(build_entry(rel_str, fn))
            if max_files and len(paths) >= max_files:
                capped = True
                break
        if capped:
            break
    return paths, capped


class QuickRunIndex:
    """Per-base-directory file indexes, built off-thread and cached.

    ``schedule(fn)`` must run ``fn`` on the UI thread; every mutation of this
    object's state goes through it, so the dicts and sets below are only ever
    touched from one thread despite the scanning happening on another.
    """

    def __init__(self, *, schedule: Callable[[Callable[[], None]], None],
                 on_ready: Callable[[str], None] | None = None,
                 spawn: Callable[[Callable[[], None]], None] | None = None):
        self._schedule = schedule
        self._on_ready = on_ready
        self._spawn = spawn or self._default_spawn
        self._cache: dict[str, tuple[float, list]] = {}
        self._disk_loaded: set[str] = set()
        self._indexing: set[str] = set()

    @staticmethod
    def _default_spawn(fn: Callable[[], None]) -> None:
        threading.Thread(target=fn, daemon=True).start()

    # -- state, for callers and tests ------------------------------------
    def cached(self, base_dir: str) -> list | None:
        """Whatever is in memory for ``base_dir``, without triggering a build."""
        entry = self._cache.get(base_dir)
        return entry[1] if entry else None

    def is_indexing(self, base_dir: str) -> bool:
        return base_dir in self._indexing

    def clear(self) -> None:
        """Drop the in-memory index, forcing a full rescan on next use.

        Deliberately leaves the disk-loaded gate set: clearing the cache must
        not send the next lookup back to the on-disk copy, which is the cache
        the user just asked to be rid of. The next build therefore rescans.
        """
        self._cache.clear()

    # -- the main entry point ---------------------------------------------
    def get(self, base_dir: str, *, ttl: float, allowed_exts: set,
            max_files: int) -> list | None:
        """Entries for ``base_dir`` now, or None while the first build runs.

        Stale entries are returned immediately and refreshed in the background:
        showing slightly old suggestions beats showing none while a large tree
        is rescanned.
        """
        cached = self._cache.get(base_dir)
        if cached is not None:
            if time.monotonic() - cached[0] > ttl:
                self.build_async(base_dir, ttl=ttl, allowed_exts=allowed_exts,
                                 max_files=max_files, try_disk=False)
            return cached[1]
        # Nothing in memory. Build off-thread so reading a large on-disk cache
        # -- or a full rescan -- never blocks the UI. The disk-loaded gate is
        # flipped here, on the UI thread, so two rapid keystrokes cannot both
        # decide to read disk.
        try_disk = base_dir not in self._disk_loaded
        if try_disk:
            self._disk_loaded.add(base_dir)
        self.build_async(base_dir, ttl=ttl, allowed_exts=allowed_exts,
                         max_files=max_files, try_disk=try_disk)
        return None

    def suggestions(self, base_dir: str, query: str, *, max_n: int, ttl: float,
                    allowed_exts: set, max_files: int) -> list:
        """Ranked suggestions, or [] while the index is still being built."""
        index = self.get(base_dir, ttl=ttl, allowed_exts=allowed_exts,
                         max_files=max_files)
        if index is None:
            return []
        return rank_suggestions(index, query, max_n)

    def build_async(self, base_dir: str, *, ttl: float, allowed_exts: set,
                    max_files: int, try_disk: bool = False) -> None:
        """Start a background build, unless one is already running for this dir.

        Single-flight matters: without it every keystroke during a slow scan
        would spawn its own full-tree walk, each slowing the others down.
        """
        if base_dir in self._indexing:
            return
        self._indexing.add(base_dir)

        def _worker() -> None:
            try:
                # Prefer a fresh on-disk cache over walking the tree. A stale
                # one is still posted first, so the UI has something to show
                # before the rescan replaces it.
                if try_disk:
                    disk = load_disk_index(base_dir, ttl)
                    if disk is not None:
                        wall_ts, paths = disk
                        age = time.time() - wall_ts
                        mono_ts = time.monotonic() - age
                        self._schedule(
                            lambda: self._on_index_ready(base_dir, mono_ts, paths))
                        if age <= ttl:
                            return          # still fresh; no rescan needed
                t0 = time.monotonic()
                paths, capped = scan(base_dir, allowed_exts, max_files)
                ts = time.monotonic()
                _log.info("Quick Run index: scanned %s -> %d entries in %.0f ms%s",
                          base_dir, len(paths), (ts - t0) * 1000,
                          " (capped)" if capped else "")
                save_disk_index(base_dir, time.time(), paths)
                self._schedule(lambda: self._on_index_ready(base_dir, ts, paths))
            finally:
                # Cleared on the UI thread once fully done, covering both the
                # fresh-disk early return and the rescan path.
                self._schedule(lambda: self._indexing.discard(base_dir))

        self._spawn(_worker)

    def _on_index_ready(self, base_dir: str, ts: float, paths: list) -> None:
        self._cache[base_dir] = (ts, paths)
        if self._on_ready is not None:
            self._on_ready(base_dir)
