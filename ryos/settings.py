"""Paths, settings defaults, and load/save helpers."""
import json
import logging
import os
import shutil
import sys
from pathlib import Path

# Child of the "ryos" logger namespace; inherits handlers from setup_logging().
# Using stdlib logging directly avoids a circular import with ryos.logger.
_log = logging.getLogger("ryos.settings")

# Store user data in %APPDATA%\RYOS (Windows) or ~/.local/share/RYOS (other).
_APPDATA = Path(os.environ.get("APPDATA") or Path.home() / ".local" / "share") / "RYOS"
_APPDATA.mkdir(parents=True, exist_ok=True)
DB_PATH        = _APPDATA / "scripts.db"
_SETTINGS_PATH = _APPDATA / "settings.json"
LOG_DIR = _APPDATA / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "ryos.log"

DATA_DIR = _APPDATA  # public alias for ui/* to import without touching private name
QR_INDEX_DIR = _APPDATA / "qr_index"
QR_INDEX_DIR.mkdir(parents=True, exist_ok=True)

# Directory of the exe / script (used for icon and migration).
_PACKAGED = getattr(sys, "frozen", False)  # True for cx_Freeze builds
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
    # Folder scanned for user theme JSON files (empty = default: <appdata>/themes).
    "themes_dir":             "",
    # On a manual launch, open on the monitor under the mouse cursor (relocating
    # the remembered position onto it). Login launches always restore the last
    # screen regardless of this setting.
    "open_on_cursor_monitor": True,
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
    "quick_run_index_ttl":    300,
    # Extensions the Quick Run file index includes. Empty list = index every
    # file (slower on huge trees); the default keeps the index to runnable
    # script types so it stays small on large project/data directories.
    "quick_run_index_extensions": [
        ".py", ".js", ".ts", ".rb", ".pl", ".php", ".sh", ".ps1",
        ".bat", ".cmd", ".exe", ".sln", ".code-workspace",
    ],
    # Hard cap on indexed files so a misconfigured base dir can't build a
    # multi-hundred-MB cache that freezes the UI on load.
    "quick_run_index_max_files": 5000,
    "logging_enabled":        True,
    "log_level":              "INFO",
    "log_runs_output":        False,
    "max_parallel_jobs":      10,
    # Seconds a "launcher" script (marked don't-keep-in-Running) stays visible
    # in the Running list before being auto-released; 0 releases immediately.
    "launcher_release_seconds": 3,
    "theme":                  "light",
    "accent_color":           None,
    "compact_mode":           False,
    "card_size":              "medium",
}


def _load_settings() -> dict:
    try:
        stored = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        stored = {}  # First run — no settings file yet; defaults apply.
    except (OSError, ValueError) as e:
        # Unreadable or corrupt settings.json (ValueError covers JSONDecodeError).
        # Fall back to defaults but leave a trace so the loss isn't silent.
        _log.warning("Could not read settings from %s: %s; using defaults", _SETTINGS_PATH, e)
        stored = {}
    return {**_SETTINGS_DEFAULTS, **stored}


def _save_settings(settings: dict) -> None:
    try:
        _SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except OSError as e:
        _log.warning("Could not save settings to %s: %s", _SETTINGS_PATH, e)
