"""Single-instance guard: a named mutex plus a localhost socket handshake so a
second launch can ask the first (already-running) instance to restore itself.
No ryos.ui.* imports.
"""
import ctypes
import json
import os
import queue
import secrets
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from .logger import get_logger
from .settings import DATA_DIR

_log = get_logger("single_instance")

_LOCK_PATH = DATA_DIR / "instance.lock"
_MUTEX_NAME = "Local\\RYOS-SingleInstance"
_ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    """Holds the resources that make this process the primary instance.

    Constructed either "live" (mutex + listening socket + lock file) or as a
    no-op (non-Windows, RYOS_ALLOW_MULTIPLE=1, or a fail-open fallback) --
    both expose the same interface so callers never need to branch.
    """

    def __init__(self, mutex_handle=None, sock: Optional[socket.socket] = None,
                 token: Optional[str] = None):
        self._mutex_handle = mutex_handle
        self._sock = sock
        self._token = token
        self.signals: "queue.Queue[str]" = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._released = False
        if self._sock is not None:
            self._thread = threading.Thread(target=self._serve, daemon=True)
            self._thread.start()

    def _serve(self) -> None:
        self._sock.settimeout(1.0)
        while not self._stop_event.is_set():
            try:
                conn, _addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                # Socket closed out from under accept() during release().
                return
            try:
                conn.settimeout(1.0)
                data = conn.recv(256)
                text = data.decode("utf-8", errors="replace").strip()
                parts = text.split(None, 1)
                token = parts[0] if parts else ""
                verb = parts[1] if len(parts) > 1 else "RESTORE"
                if token and token == self._token:
                    conn.sendall(b"OK\n")
                    self.signals.put(verb)
            except Exception:
                _log.debug("Error handling instance-signal connection", exc_info=True)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        try:
            if self._token is not None and _LOCK_PATH.exists():
                stored = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
                if stored.get("token") == self._token:
                    _LOCK_PATH.unlink()
        except (OSError, ValueError, KeyError):
            pass
        self._stop_event.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._mutex_handle:
            try:
                _get_kernel32().CloseHandle(self._mutex_handle)
            except Exception:
                _log.debug("Error closing instance mutex handle", exc_info=True)
            self._mutex_handle = None


def _signal_existing(verb: str) -> bool:
    # The lock-file read is inside the retry loop, not just the connect: a
    # racing launch can see the mutex before the primary has finished
    # writing the file, and failing open here (instead of retrying) would
    # make the second process become a second primary and clobber the
    # first's lock file, orphaning it.
    for attempt in range(3):
        try:
            stored = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
            port = stored["port"]
            token = stored["token"]
            with socket.create_connection(("127.0.0.1", port), timeout=1.0) as sock:
                sock.sendall(f"{token} {verb}\n".encode("utf-8"))
                reply = sock.recv(16)
                if reply == b"OK\n":
                    return True
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if attempt < 2:
            time.sleep(0.15)
    return False


def _get_kernel32():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.restype = ctypes.c_void_p
    k.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    k.CloseHandle.restype = ctypes.c_bool
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    return k


def _start_as_primary(mutex_handle) -> SingleInstance:
    # Must fail open like every other path in this module: a launch that
    # can't bind a loopback socket or write the lock file (locked profile,
    # disk full, hardened host) must still start the app, just without the
    # single-instance guard.
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(4)
        port = sock.getsockname()[1]
        token = secrets.token_hex(16)
        payload = {"port": port, "token": token, "pid": os.getpid()}
        tmp = Path(str(_LOCK_PATH) + ".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, _LOCK_PATH)
    except OSError:
        _log.warning("Could not start instance-signal listener; "
                     "proceeding without a single-instance guard", exc_info=True)
        try:
            _get_kernel32().CloseHandle(mutex_handle)
        except Exception:
            pass
        return SingleInstance()
    return SingleInstance(mutex_handle=mutex_handle, sock=sock, token=token)


def acquire(restore_existing: bool = True, verb: str = "RESTORE") -> Optional[SingleInstance]:
    if os.environ.get("RYOS_ALLOW_MULTIPLE") == "1" or sys.platform != "win32":
        return SingleInstance()

    kernel32 = _get_kernel32()
    handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if not handle:
        _log.warning("Could not create instance mutex (error %s); proceeding without a guard",
                     ctypes.get_last_error())
        return SingleInstance()

    already_exists = ctypes.get_last_error() == _ERROR_ALREADY_EXISTS

    if not already_exists:
        return _start_as_primary(handle)

    if not restore_existing:
        kernel32.CloseHandle(handle)
        return None

    if _signal_existing(verb):
        kernel32.CloseHandle(handle)
        return None

    _log.warning("Instance mutex already held but no responder found; "
                 "becoming primary (stale lock file, if any, will be replaced)")
    return _start_as_primary(handle)
