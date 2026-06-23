"""Windows startup-on-login registry helpers."""
import shutil
import sys
from pathlib import Path

from .settings import _PACKAGED

if sys.platform == "win32":
    import winreg

_RUN_KEY  = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_NAME = "RYOS"


def _startup_command() -> str:
    # The trailing --startup tells the app it was launched at login (so it
    # restores the last-used screen rather than relocating to the cursor's).
    if _PACKAGED:
        return f'"{sys.executable}" --startup'
    repo_root = Path(__file__).resolve().parents[1]
    uv = shutil.which("uv")
    if uv:
        return f'"{uv}" run --project "{repo_root}" ryos --startup'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = Path(sys.executable)
    return f'cmd /c cd /d "{repo_root}" && "{pythonw}" -m ryos --startup'


def _startup_enabled() -> bool:
    if sys.platform != "win32":
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            winreg.QueryValueEx(k, _RUN_NAME)
            return True
    except OSError:
        return False


def _set_startup(enable: bool) -> None:
    if sys.platform != "win32":
        return
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY,
                        access=winreg.KEY_SET_VALUE) as k:
        if enable:
            winreg.SetValueEx(k, _RUN_NAME, 0, winreg.REG_SZ, _startup_command())
        else:
            try:
                winreg.DeleteValue(k, _RUN_NAME)
            except FileNotFoundError:
                pass


def _sync_startup_command() -> None:
    """If startup-on-login is enabled but its stored command is out of date
    (e.g. an older entry lacking the --startup flag), rewrite it. Safe to call
    on every launch; it only writes when the value actually differs."""
    if sys.platform != "win32" or not _startup_enabled():
        return
    desired = _startup_command()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            current, _ = winreg.QueryValueEx(k, _RUN_NAME)
        if current != desired:
            _set_startup(True)
    except OSError:
        pass
