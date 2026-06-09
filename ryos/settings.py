"""Paths, settings defaults, and load/save helpers."""
import json
import os
import shutil
import sys
from pathlib import Path

# Store user data in %APPDATA%\RYOS (Windows) or ~/.local/share/RYOS (other).
_APPDATA = Path(os.environ.get("APPDATA") or Path.home() / ".local" / "share") / "RYOS"
_APPDATA.mkdir(parents=True, exist_ok=True)
DB_PATH        = _APPDATA / "scripts.db"
_SETTINGS_PATH = _APPDATA / "settings.json"
LOG_DIR = _APPDATA / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "ryos.log"

# Directory of the exe / script (used for icon and migration).
_NUITKA   = "__compiled__" in dir()          # True only in Nuitka-compiled builds
_PACKAGED = getattr(sys, "frozen", False) or _NUITKA  # True for Nuitka, PyInstaller, cx_Freeze
_BASE = Path(sys.executable).parent if _PACKAGED else Path(__file__).resolve().parents[1]

# Migrate files from old location (next to exe / script) if not yet moved.
for _fname in ("scripts.db", "settings.json"):
    _old = _BASE / _fname
    _new = _APPDATA / _fname
    if _old.exists() and not _new.exists():
        shutil.move(str(_old), _new)


_CORNER_CHOICES = [
    ("↘  Bottom right", "bottom_right"),
    ("↙  Bottom left",  "bottom_left"),
    ("↗  Top right",    "top_right"),
    ("↖  Top left",     "top_left"),
    ("Off",             "none"),
]
_CORNER_VAL_TO_LABEL = {v: l for l, v in _CORNER_CHOICES}
_CORNER_LABEL_TO_VAL = {l: v for l, v in _CORNER_CHOICES}

_SETTINGS_DEFAULTS: dict = {
    "remember_last_group":    True,
    "last_group":             None,
    "start_minimized":        False,
    "remember_window_geometry": True,
    "window_geometry":        None,
    "always_on_top":          False,
    "snap_corner":            "bottom_right",
    "window_width":           540,
    "window_height":          640,
    "max_output_lines":       2000,
    "auto_clear_output":      False,
    "auto_scroll_output":     True,
    "auto_check_update":      True,
    "notify_on_complete":     True,
    "quick_run_enabled":      True,
    "quick_run_autocomplete":    True,
    "quick_run_max_suggestions": 10,
    "logging_enabled":        True,
    "log_level":              "INFO",
    "log_runs_output":        False,
    "max_parallel_jobs":      10,
    "theme":                  "light",
    "accent_color":           None,
    "compact_mode":           False,
    "card_size":              "medium",
}


def _load_settings() -> dict:
    try:
        stored = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        stored = {}
    return {**_SETTINGS_DEFAULTS, **stored}


def _save_settings(settings: dict) -> None:
    try:
        _SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except Exception:
        pass
