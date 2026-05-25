# -*- coding: utf-8 -*-
# /// script
# requires-python = ">=3.10"
# dependencies = ["tkinterdnd2"]
# ///
"""
RYOS (Run Your Own Scripts) - Tkinter app for saving and running scripts
"""

import os
import sys
import json
import shlex
import sqlite3
import subprocess
import threading
import queue
import ctypes
import urllib.request
import webbrowser
if sys.platform == "win32":
    import winreg
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _DND_AVAILABLE = True
except ImportError:
    _DND_AVAILABLE = False
    DND_FILES = None
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog


# ---------------------------------------------------------------------------
# Database layer
# ---------------------------------------------------------------------------
__version__ = "1.4.0"
_RELEASES_API = "https://api.github.com/repos/lqvu-zen/RYOS/releases/latest"
_RELEASES_PAGE = "https://github.com/lqvu-zen/RYOS/releases/latest"

# When frozen by PyInstaller, store DB next to the .exe; otherwise next to this file.
_BASE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
DB_PATH       = _BASE / "scripts.db"
_SETTINGS_PATH = _BASE / "settings.json"

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


def _apply_snap_corner(window, corner: str, margin: int = 10) -> None:
    window.update_idletasks()
    w = window.winfo_width()
    h = window.winfo_height()
    # Use work area (excludes taskbar) on Windows; fall back to full screen elsewhere
    if sys.platform == "win32":
        try:
            import ctypes.wintypes
            wa = ctypes.wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(wa), 0)
            ax, ay = wa.left, wa.top
            aw, ah = wa.right - wa.left, wa.bottom - wa.top
        except Exception:
            ax, ay = 0, 0
            aw, ah = window.winfo_screenwidth(), window.winfo_screenheight()
    else:
        ax, ay = 0, 0
        aw, ah = window.winfo_screenwidth(), window.winfo_screenheight()
    x = ax + margin if "left" in corner else ax + aw - w - margin
    y = ay + margin if "top"  in corner else ay + ah - h - margin
    window.geometry(f"+{x}+{y}")


# ---------------------------------------------------------------------------
# Windows startup registry helpers
# ---------------------------------------------------------------------------
_RUN_KEY  = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_NAME = "RYOS"


def _startup_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = Path(sys.executable)
    return f'"{pythonw}" "{Path(__file__).resolve()}"'


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


def _show_notification(title: str, body: str) -> None:
    """Fire a Windows toast notification (fire-and-forget, Windows 10/11 only)."""
    if sys.platform != "win32":
        return
    import base64
    # Use PowerShell's own registered AppId so no app registration is needed.
    _APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
    t = title.replace('"', '`"')
    b = body.replace('"', '`"')
    script = f"""
[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$t1 = $xml.GetElementsByTagName("text").Item(0)
$t2 = $xml.GetElementsByTagName("text").Item(1)
$t1.AppendChild($xml.CreateTextNode("{t}")) | Out-Null
$t2.AppendChild($xml.CreateTextNode("{b}")) | Out-Null
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("{_APP_ID}").Show([Windows.UI.Notifications.ToastNotification]::new($xml))
"""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        subprocess.Popen(
            ["powershell", "-WindowStyle", "Hidden", "-NoProfile",
             "-EncodedCommand", encoded],
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _parse_version(tag: str) -> tuple:
    try:
        return tuple(int(x.split("-")[0]) for x in tag.lstrip("v").split("."))
    except Exception:
        return (0,)


def _fetch_latest_release() -> tuple[str, str] | None:
    try:
        req = urllib.request.Request(
            _RELEASES_API, headers={"User-Agent": "RYOS-update-check"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        return data["tag_name"], data["html_url"]
    except Exception:
        return None


class ScriptDB:
    """SQLite wrapper - manages saved scripts."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scripts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT NOT NULL,
                    path        TEXT NOT NULL,
                    params      TEXT DEFAULT '',
                    interpreter TEXT DEFAULT '',
                    created_at  TEXT NOT NULL,
                    last_run_at     TEXT,
                    last_run_status TEXT,
                    order_index     INTEGER DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS groups (
                    id   INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE
                )
                """
            )
            # migrate existing databases that lack newer columns
            cols = [r[1] for r in conn.execute("PRAGMA table_info(scripts)")]
            if "order_index" not in cols:
                conn.execute("ALTER TABLE scripts ADD COLUMN order_index INTEGER DEFAULT 0")
                conn.execute("UPDATE scripts SET order_index = id")
            if "last_run_status" not in cols:
                conn.execute("ALTER TABLE scripts ADD COLUMN last_run_status TEXT")
            if "group_name" not in cols:
                conn.execute("ALTER TABLE scripts ADD COLUMN group_name TEXT DEFAULT ''")
            # populate groups table from existing script group_name values
            existing_groups = {r[0] for r in conn.execute("SELECT name FROM groups")}
            named = conn.execute(
                "SELECT DISTINCT group_name FROM scripts "
                "WHERE group_name != '' AND group_name IS NOT NULL"
            ).fetchall()
            for (g,) in named:
                if g not in existing_groups:
                    conn.execute("INSERT OR IGNORE INTO groups (name) VALUES (?)", (g,))
            gcols = [r[1] for r in conn.execute("PRAGMA table_info(groups)")]
            if "sort_order" not in gcols:
                conn.execute("ALTER TABLE groups ADD COLUMN sort_order INTEGER DEFAULT 0")
                conn.execute("UPDATE groups SET sort_order = id")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pipelines (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    name       TEXT NOT NULL,
                    group_name TEXT NOT NULL DEFAULT '',
                    sort_order INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pipeline_steps (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    pipeline_id INTEGER NOT NULL,
                    script_id   INTEGER NOT NULL,
                    step_order  INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS script_param_presets (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    script_id  INTEGER NOT NULL,
                    label      TEXT NOT NULL,
                    params     TEXT DEFAULT '',
                    sort_order INTEGER DEFAULT 0
                )
            """)
            pscols = [r[1] for r in conn.execute("PRAGMA table_info(pipeline_steps)")]
            if "params_override" not in pscols:
                conn.execute("ALTER TABLE pipeline_steps ADD COLUMN params_override TEXT DEFAULT NULL")
            conn.commit()

    def add(self, name: str, path: str, params: str, interpreter: str, group_name: str = "") -> int:
        with self._connect() as conn:
            max_order = conn.execute("SELECT COALESCE(MAX(order_index), 0) FROM scripts").fetchone()[0]
            cur = conn.execute(
                "INSERT INTO scripts (name, path, params, interpreter, created_at, order_index, group_name) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, path, params, interpreter, datetime.now().isoformat(timespec="seconds"),
                 max_order + 1, group_name),
            )
            conn.commit()
            return cur.lastrowid

    def update(self, script_id: int, name: str, path: str, params: str, interpreter: str, group_name: str = ""):
        with self._connect() as conn:
            conn.execute(
                "UPDATE scripts SET name=?, path=?, params=?, interpreter=?, group_name=? WHERE id=?",
                (name, path, params, interpreter, group_name, script_id),
            )
            conn.commit()

    def delete(self, script_id: int):
        with self._connect() as conn:
            conn.execute("DELETE FROM scripts WHERE id=?", (script_id,))
            conn.commit()

    def delete_many(self, ids: list[int]):
        with self._connect() as conn:
            conn.executemany("DELETE FROM scripts WHERE id=?", [(i,) for i in ids])
            conn.commit()

    def delete_all(self):
        with self._connect() as conn:
            conn.execute("DELETE FROM scripts")
            conn.commit()

    def export_to_file(self, path: str, group_name: str | None = None):
        with self._connect() as conn:
            if group_name is not None:
                scripts = conn.execute(
                    "SELECT name, path, params, interpreter, order_index, group_name "
                    "FROM scripts WHERE COALESCE(group_name,'')=? "
                    "ORDER BY order_index ASC, id ASC",
                    (group_name,),
                ).fetchall()
                pipelines = conn.execute(
                    "SELECT id, name, group_name, sort_order FROM pipelines "
                    "WHERE group_name=? ORDER BY sort_order ASC, id ASC",
                    (group_name,),
                ).fetchall()
                groups = conn.execute(
                    "SELECT name, sort_order FROM groups WHERE name=?",
                    (group_name,),
                ).fetchall()
            else:
                scripts = conn.execute(
                    "SELECT name, path, params, interpreter, order_index, group_name "
                    "FROM scripts ORDER BY "
                    "CASE WHEN COALESCE(group_name,'')='' THEN 1 ELSE 0 END, "
                    "group_name ASC, order_index ASC, id ASC"
                ).fetchall()
                pipelines = conn.execute(
                    "SELECT id, name, group_name, sort_order FROM pipelines "
                    "ORDER BY sort_order ASC, id ASC"
                ).fetchall()
                groups = conn.execute(
                    "SELECT name, sort_order FROM groups ORDER BY sort_order ASC, id ASC"
                ).fetchall()

            pipeline_data = []
            for p_id, p_name, p_group, p_order in pipelines:
                steps = conn.execute(
                    "SELECT s.path FROM pipeline_steps ps "
                    "JOIN scripts s ON s.id=ps.script_id "
                    "WHERE ps.pipeline_id=? ORDER BY ps.step_order ASC, ps.id ASC",
                    (p_id,),
                ).fetchall()
                pipeline_data.append({
                    "name": p_name,
                    "group_name": p_group,
                    "sort_order": p_order,
                    "steps": [{"script_path": row[0]} for row in steps],
                })

        data = {
            "version": 2,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "groups": [{"name": g[0], "sort_order": g[1]} for g in groups],
            "scripts": [
                {
                    "name": s[0], "path": s[1], "params": s[2],
                    "interpreter": s[3], "order_index": s[4],
                    "group_name": s[5] or "",
                }
                for s in scripts
            ],
            "pipelines": pipeline_data,
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        return len(scripts), len(pipeline_data)

    def import_from_file(self, path: str, replace: bool = False) -> tuple[int, int]:
        """Returns (scripts_added, scripts_skipped)."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        groups    = data.get("groups", [])
        scripts   = data.get("scripts", [])
        pipelines = data.get("pipelines", [])
        now = datetime.now().isoformat(timespec="seconds")
        added = skipped = 0
        # Groups covered by this import file (used to scope a replace)
        imported_group_names: set[str] = {g["name"] for g in groups}
        for s in scripts:
            imported_group_names.add(s.get("group_name") or "")
        for p in pipelines:
            imported_group_names.add(p.get("group_name") or "")

        with self._connect() as conn:
            if replace:
                # Only clear data belonging to the imported groups, leave others untouched
                for gname in imported_group_names:
                    pipe_ids = [r[0] for r in conn.execute(
                        "SELECT id FROM pipelines WHERE COALESCE(group_name,'')=?", (gname,)
                    )]
                    for pid in pipe_ids:
                        conn.execute("DELETE FROM pipeline_steps WHERE pipeline_id=?", (pid,))
                    conn.execute("DELETE FROM pipelines WHERE COALESCE(group_name,'')=?", (gname,))
                    conn.execute("DELETE FROM scripts   WHERE COALESCE(group_name,'')=?", (gname,))
                    if gname:
                        conn.execute("DELETE FROM groups WHERE name=?", (gname,))

            # Ensure every referenced group exists
            existing_groups: set[str] = {r[0] for r in conn.execute("SELECT name FROM groups")}

            def _ensure_group(gname: str):
                if gname and gname not in existing_groups:
                    max_ord = conn.execute(
                        "SELECT COALESCE(MAX(sort_order), -1) FROM groups"
                    ).fetchone()[0]
                    conn.execute(
                        "INSERT OR IGNORE INTO groups (name, sort_order) VALUES (?, ?)",
                        (gname, max_ord + 1),
                    )
                    existing_groups.add(gname)

            for g in groups:
                gname = g["name"]
                if gname not in existing_groups:
                    conn.execute(
                        "INSERT OR IGNORE INTO groups (name, sort_order) VALUES (?, ?)",
                        (gname, g.get("sort_order", 0)),
                    )
                    existing_groups.add(gname)

            # Import scripts; build path→id map for pipeline wiring
            path_to_id: dict[str, int] = {
                r[0]: r[1] for r in conn.execute("SELECT path, id FROM scripts")
            }
            existing_paths = set(path_to_id)
            for s in scripts:
                spath = s["path"]
                if not replace and spath in existing_paths:
                    skipped += 1
                    continue
                _ensure_group(s.get("group_name", ""))
                cur = conn.execute(
                    "INSERT INTO scripts "
                    "(name, path, params, interpreter, created_at, order_index, group_name) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (s["name"], spath, s.get("params", ""),
                     s.get("interpreter", ""), now,
                     s.get("order_index", 0), s.get("group_name", "")),
                )
                path_to_id[spath] = cur.lastrowid
                added += 1

            # Import pipelines
            for p in pipelines:
                p_name  = p["name"]
                p_group = p.get("group_name", "")
                _ensure_group(p_group)
                if not replace and conn.execute(
                    "SELECT id FROM pipelines WHERE name=? AND group_name=?",
                    (p_name, p_group),
                ).fetchone():
                    continue
                max_ord = conn.execute(
                    "SELECT COALESCE(MAX(sort_order), -1) FROM pipelines WHERE group_name=?",
                    (p_group,),
                ).fetchone()[0]
                cur = conn.execute(
                    "INSERT INTO pipelines (name, group_name, sort_order) VALUES (?, ?, ?)",
                    (p_name, p_group, p.get("sort_order", max_ord + 1)),
                )
                p_id = cur.lastrowid
                for i, step in enumerate(p.get("steps", [])):
                    sid = path_to_id.get(step.get("script_path"))
                    if sid:
                        conn.execute(
                            "INSERT INTO pipeline_steps (pipeline_id, script_id, step_order) "
                            "VALUES (?, ?, ?)",
                            (p_id, sid, i * 10),
                        )

            conn.commit()
        return added, skipped

    def mark_run(self, script_id: int):
        with self._connect() as conn:
            conn.execute(
                "UPDATE scripts SET last_run_at=?, last_run_status=NULL WHERE id=?",
                (datetime.now().isoformat(timespec="seconds"), script_id),
            )
            conn.commit()

    def mark_run_status(self, script_id: int, status: str):
        with self._connect() as conn:
            conn.execute(
                "UPDATE scripts SET last_run_status=? WHERE id=?",
                (status, script_id),
            )
            conn.commit()

    def list_all(self):
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT id, name, path, params, interpreter, created_at, last_run_at, last_run_status, group_name "
                "FROM scripts "
                "ORDER BY CASE WHEN COALESCE(group_name,'')='' THEN 1 ELSE 0 END, "
                "group_name ASC, order_index ASC, id ASC"
            )
            return cur.fetchall()

    def list_groups(self) -> list[str]:
        with self._connect() as conn:
            cur = conn.execute("SELECT name FROM groups ORDER BY sort_order ASC, id ASC")
            return [r[0] for r in cur.fetchall()]

    def create_group(self, name: str):
        with self._connect() as conn:
            max_order = conn.execute("SELECT COALESCE(MAX(sort_order), -1) FROM groups").fetchone()[0]
            conn.execute("INSERT OR IGNORE INTO groups (name, sort_order) VALUES (?, ?)",
                         (name, max_order + 1))
            conn.commit()

    def reorder_groups(self, names: list[str]):
        with self._connect() as conn:
            for i, name in enumerate(names):
                conn.execute("UPDATE groups SET sort_order=? WHERE name=?", (i, name))
            conn.commit()

    def rename_group(self, old: str, new: str):
        with self._connect() as conn:
            conn.execute("UPDATE groups SET name=? WHERE name=?", (new, old))
            conn.execute("UPDATE scripts SET group_name=? WHERE group_name=?", (new, old))
            conn.execute("UPDATE pipelines SET group_name=? WHERE group_name=?", (new, old))
            conn.commit()

    def delete_group(self, name: str):
        with self._connect() as conn:
            conn.execute("DELETE FROM groups WHERE name=?", (name,))
            conn.execute("UPDATE scripts SET group_name='' WHERE group_name=?", (name,))
            conn.execute("UPDATE pipelines SET group_name='' WHERE group_name=?", (name,))
            conn.commit()

    def list_param_presets(self, script_id: int) -> list:
        with self._connect() as conn:
            return conn.execute(
                "SELECT id, label, params FROM script_param_presets "
                "WHERE script_id=? ORDER BY sort_order ASC, id ASC",
                (script_id,),
            ).fetchall()

    def replace_param_presets(self, script_id: int, presets: list):
        """Replace all presets for script_id. presets = [(label, params), ...]"""
        with self._connect() as conn:
            conn.execute("DELETE FROM script_param_presets WHERE script_id=?", (script_id,))
            for i, (label, params) in enumerate(presets):
                conn.execute(
                    "INSERT INTO script_param_presets (script_id, label, params, sort_order) "
                    "VALUES (?, ?, ?, ?)",
                    (script_id, label, params, i),
                )
            conn.commit()

    def create_pipeline(self, name: str, group_name: str) -> int:
        with self._connect() as conn:
            max_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) FROM pipelines WHERE group_name=?", (group_name,)
            ).fetchone()[0]
            cur = conn.execute(
                "INSERT INTO pipelines (name, group_name, sort_order) VALUES (?, ?, ?)",
                (name, group_name, max_order + 1),
            )
            conn.commit()
            return cur.lastrowid

    def clone_pipeline(self, pipeline_id: int) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT name, group_name FROM pipelines WHERE id=?", (pipeline_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"Pipeline {pipeline_id} not found")
            name, group_name = row
            max_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) FROM pipelines WHERE group_name=?",
                (group_name,),
            ).fetchone()[0]
            cur = conn.execute(
                "INSERT INTO pipelines (name, group_name, sort_order) VALUES (?, ?, ?)",
                (f"{name} (copy)", group_name, max_order + 1),
            )
            new_id = cur.lastrowid
            steps = conn.execute(
                "SELECT script_id, step_order FROM pipeline_steps "
                "WHERE pipeline_id=? ORDER BY step_order ASC, id ASC",
                (pipeline_id,),
            ).fetchall()
            for script_id, step_order in steps:
                conn.execute(
                    "INSERT INTO pipeline_steps (pipeline_id, script_id, step_order) "
                    "VALUES (?, ?, ?)",
                    (new_id, script_id, step_order),
                )
            conn.commit()
            return new_id

    def delete_pipeline(self, pipeline_id: int):
        with self._connect() as conn:
            conn.execute("DELETE FROM pipeline_steps WHERE pipeline_id=?", (pipeline_id,))
            conn.execute("DELETE FROM pipelines WHERE id=?", (pipeline_id,))
            conn.commit()

    def rename_pipeline(self, pipeline_id: int, name: str):
        with self._connect() as conn:
            conn.execute("UPDATE pipelines SET name=? WHERE id=?", (name, pipeline_id))
            conn.commit()

    def list_pipelines(self, group_name: str) -> list:
        with self._connect() as conn:
            return conn.execute(
                "SELECT id, name FROM pipelines WHERE group_name=? ORDER BY sort_order ASC, id ASC",
                (group_name,),
            ).fetchall()

    def list_pipeline_steps(self, pipeline_id: int) -> list:
        """Returns list of (step_id, script_id, name, path, params, interpreter, params_override)."""
        with self._connect() as conn:
            return conn.execute(
                "SELECT ps.id, s.id, s.name, s.path, s.params, s.interpreter, ps.params_override "
                "FROM pipeline_steps ps JOIN scripts s ON s.id = ps.script_id "
                "WHERE ps.pipeline_id=? ORDER BY ps.step_order ASC, ps.id ASC",
                (pipeline_id,),
            ).fetchall()

    def update_pipeline_step_params(self, step_id: int, params_override):
        with self._connect() as conn:
            conn.execute("UPDATE pipeline_steps SET params_override=? WHERE id=?",
                         (params_override, step_id))
            conn.commit()

    def add_pipeline_step(self, pipeline_id: int, script_id: int) -> int:
        with self._connect() as conn:
            max_order = conn.execute(
                "SELECT COALESCE(MAX(step_order), -1) FROM pipeline_steps WHERE pipeline_id=?",
                (pipeline_id,),
            ).fetchone()[0]
            cur = conn.execute(
                "INSERT INTO pipeline_steps (pipeline_id, script_id, step_order) VALUES (?, ?, ?)",
                (pipeline_id, script_id, max_order + 1),
            )
            conn.commit()
            return cur.lastrowid

    def remove_pipeline_step(self, step_id: int):
        with self._connect() as conn:
            conn.execute("DELETE FROM pipeline_steps WHERE id=?", (step_id,))
            conn.commit()

    def reorder_pipeline_steps(self, pipeline_id: int, ordered_step_ids: list[int]):
        with self._connect() as conn:
            for i, sid in enumerate(ordered_step_ids):
                conn.execute("UPDATE pipeline_steps SET step_order=? WHERE id=?", (i * 10, sid))
            conn.commit()

    def swap_order(self, id_a: int, id_b: int):
        with self._connect() as conn:
            oa = conn.execute("SELECT order_index FROM scripts WHERE id=?", (id_a,)).fetchone()[0]
            ob = conn.execute("SELECT order_index FROM scripts WHERE id=?", (id_b,)).fetchone()[0]
            conn.execute("UPDATE scripts SET order_index=? WHERE id=?", (ob, id_a))
            conn.execute("UPDATE scripts SET order_index=? WHERE id=?", (oa, id_b))
            conn.commit()

    def move_to_top(self, script_id: int):
        with self._connect() as conn:
            row = conn.execute("SELECT group_name FROM scripts WHERE id=?", (script_id,)).fetchone()
            grp = (row[0] or "") if row else ""
            min_order = conn.execute(
                "SELECT COALESCE(MIN(order_index), 0) FROM scripts WHERE COALESCE(group_name,'')=?", (grp,)
            ).fetchone()[0]
            conn.execute("UPDATE scripts SET order_index=? WHERE id=?", (min_order - 1, script_id))
            conn.commit()

    def reorder_script(self, script_id: int, group_name: str, before_id: int | None):
        """Place script_id before before_id within group_name (None = append at end)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM scripts WHERE COALESCE(group_name,'')=? AND id!=? "
                "ORDER BY order_index ASC, id ASC",
                (group_name, script_id),
            ).fetchall()
            ids = [r[0] for r in rows]
            if before_id is not None and before_id in ids:
                ids.insert(ids.index(before_id), script_id)
            else:
                ids.append(script_id)
            for i, sid in enumerate(ids):
                conn.execute("UPDATE scripts SET order_index=? WHERE id=?", (i * 10, sid))
            conn.commit()

    def move_to_group(self, script_id: int, new_group: str):
        """Move script to a different group, appended at the end."""
        with self._connect() as conn:
            max_order = conn.execute(
                "SELECT COALESCE(MAX(order_index), -1) FROM scripts WHERE COALESCE(group_name,'')=?",
                (new_group,),
            ).fetchone()[0]
            conn.execute(
                "UPDATE scripts SET group_name=?, order_index=? WHERE id=?",
                (new_group, max_order + 10, script_id),
            )
            conn.commit()

    def reorder_pipeline(self, pipeline_id: int, group_name: str, before_id: int | None):
        """Place pipeline_id before before_id within group_name (None = append at end)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM pipelines WHERE group_name=? AND id!=? "
                "ORDER BY sort_order ASC, id ASC",
                (group_name, pipeline_id),
            ).fetchall()
            ids = [r[0] for r in rows]
            if before_id is not None and before_id in ids:
                ids.insert(ids.index(before_id), pipeline_id)
            else:
                ids.append(pipeline_id)
            for i, pid in enumerate(ids):
                conn.execute("UPDATE pipelines SET sort_order=? WHERE id=?", (i * 10, pid))
            conn.commit()

    def move_pipeline_to_group(self, pipeline_id: int, new_group: str):
        """Move pipeline to a different group, appended at the end."""
        with self._connect() as conn:
            max_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) FROM pipelines WHERE group_name=?",
                (new_group,),
            ).fetchone()[0]
            conn.execute(
                "UPDATE pipelines SET group_name=?, sort_order=? WHERE id=?",
                (new_group, max_order + 10, pipeline_id),
            )
            conn.commit()

    def get(self, script_id: int):
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT id, name, path, params, interpreter, group_name FROM scripts WHERE id=?",
                (script_id,),
            )
            return cur.fetchone()


# ---------------------------------------------------------------------------
# Execution helpers
# ---------------------------------------------------------------------------
def detect_interpreter(path: str) -> str:
    ext = Path(path).suffix.lower()
    mapping = {
        ".py":  sys.executable,
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
    }
    return mapping.get(ext, "")


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
    }
    label = ext.lstrip(".").upper() if ext else "Script"
    return tags.get(ext, (label, "#555555"))


def build_command(path: str, params: str, interpreter: str):
    cmd = []
    if interpreter.strip():
        cmd.extend(shlex.split(interpreter, posix=(os.name != "nt")))
    if path.strip():
        cmd.append(path)
    if params.strip():
        cmd.extend(shlex.split(params, posix=(os.name != "nt")))
    return cmd


# ---------------------------------------------------------------------------
# Edit / Add dialog
# ---------------------------------------------------------------------------
class ScriptDialog(tk.Toplevel):
    """Modal dialog for adding or editing a script entry."""

    def __init__(self, parent, db: ScriptDB, script_id: int | None = None,
                 on_save=None, existing_groups: list[str] | None = None,
                 default_group: str = ""):
        super().__init__(parent)
        self.db = db
        self.script_id = script_id
        self.on_save = on_save
        self.result = None
        self.existing_groups = existing_groups or []
        self.default_group = default_group

        self.title("Edit Script" if script_id else "Add Script")
        self.resizable(False, False)
        self.grab_set()
        self.configure(bg=C["card_bg"])

        self._presets = []  # list of [label, params]

        self._build()

        if script_id:
            rec = db.get(script_id)
            if rec:
                _, name, path, params, interp, grp = rec
                self.e_name.insert(0, name)
                self.e_path.insert(0, path)
                self.e_params.insert(0, params)
                self.e_interp.set(interp)
                self.e_group.set(grp or "")
            for _, label, pparams in db.list_param_presets(script_id):
                self._presets.append([label, pparams])
                self._preset_listbox.insert(tk.END, label)
        else:
            self.e_group.set(self.default_group)

        self.transient(parent)
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()
        self.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")
        self.wait_visibility()
        self.focus_set()

    def _build(self):
        pad = {"padx": 8, "pady": 4}

        # In-body title strip with border below — matches the design dialog__title
        title_strip = tk.Frame(self, bg=C["card_bg"])
        title_strip.pack(fill="x")
        tk.Label(title_strip,
                 text="Edit Script" if self.script_id else "Add Script",
                 bg=C["card_bg"], fg=C["name_fg"],
                 font=("Segoe UI", 11, "bold"),
                 anchor="w", padx=16, pady=12).pack(fill="x")
        tk.Frame(title_strip, bg=C["border"], height=1).pack(fill="x")

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Name:").grid(row=0, column=0, sticky="w", **pad)
        self.e_name = ttk.Entry(frame, width=40)
        self.e_name.grid(row=0, column=1, columnspan=2, sticky="ew", **pad)

        ttk.Label(frame, text="Path:").grid(row=1, column=0, sticky="w", **pad)
        self.e_path = ttk.Entry(frame, width=40)
        self.e_path.grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(frame, text="Browse…", command=self._browse).grid(row=1, column=2, **pad)

        ttk.Label(frame, text="Parameters:").grid(row=2, column=0, sticky="w", **pad)
        self.e_params = ttk.Entry(frame, width=40)
        self.e_params.grid(row=2, column=1, sticky="ew", **pad)
        self.e_params.bind("<FocusOut>", self._auto_name_from_params)
        self.e_params.bind("<Return>", lambda _: self._preset_add_from_params())
        ttk.Button(frame, text="+ Preset", width=8,
                   command=self._preset_add_from_params).grid(row=2, column=2, **pad)

        # Presets section
        ttk.Label(frame, text="Presets:").grid(row=3, column=0, sticky="nw", **pad)
        preset_frame = ttk.Frame(frame)
        preset_frame.grid(row=3, column=1, columnspan=2, sticky="ew", **pad)
        preset_frame.columnconfigure(0, weight=1)

        preset_frame.columnconfigure(0, weight=1)
        self._preset_listbox = tk.Listbox(
            preset_frame, height=4, selectmode=tk.SINGLE,
            bg="#1e1e1e", fg="#cccccc", selectbackground=C["accent"],
            selectforeground="#ffffff", relief="flat", highlightthickness=1,
            highlightbackground=C["border"], font=("Segoe UI", 9),
        )
        _preset_scroll = ttk.Scrollbar(preset_frame, orient="vertical",
                                       command=self._preset_listbox.yview)
        self._preset_listbox.configure(yscrollcommand=_preset_scroll.set)
        self._preset_listbox.grid(row=0, column=0, sticky="nsew")
        _preset_scroll.grid(row=0, column=1, sticky="ns")
        self._preset_listbox.bind("<Double-Button-1>", lambda _: self._preset_use())
        self._preset_listbox.bind("<Button-3>", self._preset_context_menu)

        ttk.Label(frame, text="Interpreter:").grid(row=4, column=0, sticky="w", **pad)
        self.e_interp = ttk.Combobox(frame, width=38, values=[
            "cmd /c", "powershell -File", "pwsh -File", "python", "node", "bash",
        ])
        self.e_interp.grid(row=4, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Label(frame, text="Leave blank for auto-detection, or pick a preset", foreground="#888").grid(
            row=5, column=1, columnspan=2, sticky="w", padx=8
        )

        ttk.Label(frame, text="Group:").grid(row=6, column=0, sticky="w", **pad)
        self.e_group = ttk.Combobox(frame, values=self.existing_groups, width=38)
        self.e_group.grid(row=6, column=1, columnspan=2, sticky="ew", **pad)

        sep = ttk.Separator(frame, orient="horizontal")
        sep.grid(row=7, column=0, columnspan=3, sticky="ew", pady=8)

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=8, column=0, columnspan=3, sticky="ew")
        ttk.Button(btn_row, text="Save", command=self._save).pack(side="right", padx=4)
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side="right", padx=4)

        if self.script_id:
            ttk.Button(btn_row, text="Delete", command=self._delete).pack(side="left", padx=4)

    def _preset_add_from_params(self):
        params = self.e_params.get().strip()
        if params and not any(p[1] == params for p in self._presets):
            self._presets.append([params, params])
            self._preset_listbox.insert(tk.END, params)
            self._autosave_presets(new_params=params)

    def _autosave_presets(self, new_params=None):
        if self.script_id:
            self.db.replace_param_presets(self.script_id, [(l, p) for l, p in self._presets])
            if new_params is not None:
                rec = self.db.get(self.script_id)
                if rec:
                    _, name, path, _, interp, grp = rec
                    self.db.update(self.script_id, name, path, new_params, interp, grp)
            if self.on_save:
                self.on_save()

    def _preset_context_menu(self, event):
        self._preset_listbox.selection_clear(0, tk.END)
        idx = self._preset_listbox.nearest(event.y)
        if idx < 0 or idx >= len(self._presets):
            return
        self._preset_listbox.selection_set(idx)
        menu = tk.Menu(self.winfo_toplevel(), tearoff=0,
                       bg="#2d2d2d", fg="#ffffff",
                       activebackground=C["accent"], activeforeground="#ffffff",
                       font=("Segoe UI", 10))
        menu.add_command(label="← Use",  command=self._preset_use)
        menu.add_command(label="Edit",   command=self._preset_edit)
        menu.add_separator()
        menu.add_command(label="Remove", command=self._preset_remove,
                         foreground="#ff8080", activeforeground="#ff8080")
        menu.tk_popup(event.x_root, event.y_root)

    def _preset_edit(self):
        sel = self._preset_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        _, params = self._presets[idx]
        dlg = _PresetEntryDialog(self, params)
        self.wait_window(dlg)
        if dlg.result:
            new_params = dlg.result
            self._presets[idx] = [new_params, new_params]
            self._preset_listbox.delete(idx)
            self._preset_listbox.insert(idx, new_params)
            self._preset_listbox.selection_set(idx)

    def _preset_use(self):
        sel = self._preset_listbox.curselection()
        if not sel:
            return
        _, params = self._presets[sel[0]]
        self.e_params.delete(0, tk.END)
        self.e_params.insert(0, params)

    def _preset_remove(self):
        sel = self._preset_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self._presets.pop(idx)
        self._preset_listbox.delete(idx)

    def _auto_name_from_params(self, _event=None):
        if not self.e_name.get().strip():
            params = self.e_params.get().strip()
            if params:
                self.e_name.delete(0, tk.END)
                self.e_name.insert(0, params)

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Select Script",
            filetypes=[("All Files", "*.*"), ("Python", "*.py"), ("Shell", "*.sh"),
                       ("Batch", "*.bat;*.cmd"), ("Executable", "*.exe")],
        )
        if path:
            self.e_path.delete(0, tk.END)
            self.e_path.insert(0, path)
            if not self.e_name.get().strip():
                self.e_name.insert(0, Path(path).stem)

    def _save(self):
        name = self.e_name.get().strip()
        path = self.e_path.get().strip()
        params = self.e_params.get().strip()
        interp = self.e_interp.get().strip()
        group_name = self.e_group.get().strip()

        if not name or (not path and not interp):
            messagebox.showwarning("Missing Info", "Name is required. Path is required when no interpreter is set.", parent=self)
            return
        if not interp and not Path(path).exists():
            if not messagebox.askyesno("Warning", f"File not found:\n{path}\n\nSave anyway?", parent=self):
                return

        if self.script_id:
            self.db.update(self.script_id, name, path, params, interp, group_name)
        else:
            self.script_id = self.db.add(name, path, params, interp, group_name)

        self.db.replace_param_presets(self.script_id, [(l, p) for l, p in self._presets])

        if self.on_save:
            self.on_save()
        self.destroy()

    def _delete(self):
        if messagebox.askyesno("Delete", "Delete this script?", parent=self):
            self.db.delete(self.script_id)
            if self.on_save:
                self.on_save()
            self.destroy()


# ---------------------------------------------------------------------------
# Pipeline editor dialog
# ---------------------------------------------------------------------------
class PipelineEditorDialog(tk.Toplevel):
    def __init__(self, parent, db: ScriptDB, pipeline_id: int,
                 pipeline_name: str, group_name: str, on_save):
        super().__init__(parent)
        self.db = db
        self.pipeline_id = pipeline_id
        self.group_name = group_name
        self.on_save = on_save
        self._steps: list = []

        self.title("Edit Pipeline")
        self.resizable(True, True)
        self.configure(bg=C["card_bg"])
        self.grab_set()
        self.geometry("440x520")
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - 440) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - 520) // 2
        self.geometry(f"440x520+{x}+{y}")

        # Name field
        nf = tk.Frame(self, bg=C["card_bg"], padx=16, pady=12)
        nf.pack(fill="x")
        tk.Label(nf, text="Pipeline Name", bg=C["card_bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self._name_var = tk.StringVar(value=pipeline_name)
        tk.Entry(nf, textvariable=self._name_var,
                 font=("Segoe UI", 10)).pack(fill="x", pady=(4, 0))

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        # Steps section header
        sh = tk.Frame(self, bg=C["bg"], padx=16, pady=8)
        sh.pack(fill="x")
        tk.Label(sh, text="Steps", bg=C["bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9, "bold")).pack(side="left")

        # Scrollable steps list
        list_frame = tk.Frame(self, bg=C["bg"])
        list_frame.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        sb = ttk.Scrollbar(list_frame)
        sb.pack(side="right", fill="y")
        self._listbox = tk.Listbox(
            list_frame, yscrollcommand=sb.set,
            selectmode="single", font=("Segoe UI", 10),
            exportselection=False,
            bg="#f8f9fc", fg=C["name_fg"],
            selectbackground=C["accent"], selectforeground="#ffffff",
            relief="flat", highlightthickness=1,
            highlightbackground=C["border"], activestyle="none",
        )
        sb.config(command=self._listbox.yview)
        self._listbox.pack(side="left", fill="both", expand=True)

        # Step control buttons
        ctrl = tk.Frame(self, bg=C["card_bg"], padx=12, pady=4)
        ctrl.pack(fill="x")
        for label, cmd in (("▲ Up", self._move_up), ("▼ Down", self._move_down),
                           ("✕ Remove", self._remove_selected)):
            tk.Button(ctrl, text=label, command=cmd,
                      bg="#e8eaf0", fg=C["name_fg"],
                      activebackground=C["card_hover"], relief="flat",
                      bd=0, padx=10, pady=4, cursor="hand2",
                      font=("Segoe UI", 9)).pack(side="left", padx=2)

        # Per-step preset picker
        pf = tk.Frame(self, bg=C["card_bg"], padx=12, pady=6)
        pf.pack(fill="x")
        tk.Label(pf, text="Step preset:", bg=C["card_bg"], fg=C["path_fg"],
                 font=("Segoe UI", 8)).pack(side="left")
        self._step_preset_var = tk.StringVar()
        self._step_preset_combo = ttk.Combobox(
            pf, textvariable=self._step_preset_var,
            state="disabled", font=("Segoe UI", 9), width=30,
        )
        self._step_preset_combo.pack(side="left", padx=(6, 0), fill="x", expand=True)
        self._step_preset_combo.bind("<<ComboboxSelected>>", self._on_step_preset_change)
        self._listbox.bind("<ButtonRelease-1>", self._on_step_select)
        self._listbox.bind("<KeyRelease>", self._on_step_select)

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        # Add step section
        af = tk.Frame(self, bg=C["card_bg"], padx=16, pady=10)
        af.pack(fill="x")
        tk.Label(af, text="Add Step", bg=C["card_bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 4))
        combo_row = tk.Frame(af, bg=C["card_bg"])
        combo_row.pack(fill="x")
        scripts = [s for s in db.list_all() if (s[8] or "") == group_name]
        # Build label → id map, disambiguating duplicate names with filename
        name_count: dict[str, int] = {}
        for s in scripts:
            name_count[s[1]] = name_count.get(s[1], 0) + 1
        self._script_map: dict[str, int] = {}
        for s in scripts:
            lbl = s[1] if name_count[s[1]] == 1 else f"{s[1]}  ({Path(s[2]).name})"
            self._script_map[lbl] = s[0]
        keys = list(self._script_map.keys())
        self._combo_var = tk.StringVar(value=keys[0] if keys else "")
        self._add_combo = ttk.Combobox(
            combo_row, textvariable=self._combo_var,
            values=keys, state="readonly", font=("Segoe UI", 9),
        )
        self._add_combo.pack(side="left", fill="x", expand=True)
        tk.Button(combo_row, text="Add", command=self._add_step,
                  bg=C["accent"], fg="#ffffff", activebackground=C["accent2"],
                  relief="flat", padx=10, pady=4, cursor="hand2",
                  font=("Segoe UI", 9, "bold")).pack(side="left", padx=(6, 0))

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        # Save / Cancel
        br = tk.Frame(self, bg=C["card_bg"], padx=16, pady=12)
        br.pack(fill="x")
        tk.Button(br, text="Save", command=self._save,
                  bg=C["accent"], fg="#ffffff", activebackground=C["accent2"],
                  relief="flat", padx=16, pady=6, cursor="hand2",
                  font=("Segoe UI", 9, "bold")).pack(side="right")
        tk.Button(br, text="Cancel", command=self.destroy,
                  bg="#e0e0e0", fg="#333333",
                  activebackground="#d0d0d0", relief="flat",
                  padx=16, pady=6, cursor="hand2",
                  font=("Segoe UI", 9)).pack(side="right", padx=(0, 8))

        self._reloading = False
        self._preset_changing = False
        self._reload_steps()

    def _on_step_select(self, _event=None):
        if self._reloading or self._preset_changing:
            return
        idx = self._selected_index()
        if idx is None:
            self._step_preset_combo.configure(state="disabled", values=[])
            self._step_preset_var.set("")
            return
        step_id, sid, name, path, params, interp, params_override = self._steps[idx]
        presets = self.db.list_param_presets(sid)
        values = ["(Script default)"] + [p[2] for p in presets]
        self._step_preset_combo.configure(
            state="readonly" if presets else "disabled", values=values)
        self._step_preset_var.set(
            params_override if params_override in values else "(Script default)")

    def _on_step_preset_change(self, _event=None):
        self._preset_changing = True
        try:
            idx = self._selected_index()
            if idx is None:
                return
            step_id, sid, name = self._steps[idx][0], self._steps[idx][1], self._steps[idx][2]
            chosen = self._step_preset_var.get()
            override = None if chosen == "(Script default)" else chosen
            self.db.update_pipeline_step_params(step_id, override)
            # Update in-memory state before touching listbox
            step = list(self._steps[idx])
            step[6] = override
            self._steps[idx] = tuple(step)
            # Update listbox label in-place
            label = f"  {idx + 1}.  {name}"
            if override is not None:
                label += f"  [{override}]"
            self._listbox.delete(idx)
            self._listbox.insert(idx, label)
            self._listbox.selection_set(idx)
        finally:
            self._preset_changing = False

    def _reload_steps(self):
        self._reloading = True
        self._steps = list(self.db.list_pipeline_steps(self.pipeline_id))
        self._listbox.delete(0, tk.END)
        for i, (step_id, sid, name, path, params, interp, params_override) in enumerate(self._steps):
            label = f"  {i + 1}.  {name}"
            if params_override is not None:
                label += f"  [{params_override}]"
            self._listbox.insert(tk.END, label)
        self._reloading = False

    def _selected_index(self) -> int | None:
        sel = self._listbox.curselection()
        return sel[0] if sel else None

    def _add_step(self):
        sel = self._combo_var.get()
        script_id = self._script_map.get(sel)
        if script_id is None:
            return
        self.db.add_pipeline_step(self.pipeline_id, script_id)
        self._reload_steps()
        self._listbox.selection_set(tk.END)

    def _remove_selected(self):
        idx = self._selected_index()
        if idx is None:
            return
        step_id = self._steps[idx][0]
        self.db.remove_pipeline_step(step_id)
        self._reload_steps()

    def _move_up(self):
        idx = self._selected_index()
        if idx is None or idx == 0:
            return
        ids = [s[0] for s in self._steps]
        ids[idx], ids[idx - 1] = ids[idx - 1], ids[idx]
        self.db.reorder_pipeline_steps(self.pipeline_id, ids)
        self._reload_steps()
        self._listbox.selection_set(idx - 1)

    def _move_down(self):
        idx = self._selected_index()
        if idx is None or idx >= len(self._steps) - 1:
            return
        ids = [s[0] for s in self._steps]
        ids[idx], ids[idx + 1] = ids[idx + 1], ids[idx]
        self.db.reorder_pipeline_steps(self.pipeline_id, ids)
        self._reload_steps()
        self._listbox.selection_set(idx + 1)

    def _save(self):
        name = self._name_var.get().strip()
        if not name:
            messagebox.showwarning("Name Required", "Enter a pipeline name.", parent=self)
            return
        self.db.rename_pipeline(self.pipeline_id, name)
        self.on_save()
        self.destroy()


# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------
C = {
    "bg":         "#f0f2f5",
    "card_bg":    "#ffffff",
    "card_hover": "#f5f7ff",
    "accent":     "#4a6fa5",
    "accent2":    "#3d5d8a",
    "header_bg":  "#1e2a3a",
    "name_fg":    "#1a1a2e",
    "path_fg":    "#8892a0",
    "btn_run_bg": "#2ecc71",
    "btn_run_hover": "#27ae60",
    "btn_mod_bg": "#4a6fa5",
    "btn_mod_hover": "#3d5d8a",
    "btn_fg":     "#ffffff",
    "border":     "#dde2ea",
    "status_bg":  "#e8ebf0",
}


def _flat_button(parent, text, bg, hover_bg, command, width=9):
    """Borderless button with hover color swap."""
    btn = tk.Button(
        parent, text=text, command=command,
        bg=bg, fg=C["btn_fg"],
        activebackground=hover_bg, activeforeground=C["btn_fg"],
        relief="flat", bd=0, padx=12, pady=5,
        font=("Segoe UI", 9, "bold"), cursor="hand2", width=width,
    )
    btn.bind("<Enter>", lambda e: btn.config(bg=hover_bg))
    btn.bind("<Leave>", lambda e: btn.config(bg=bg))
    return btn


# ---------------------------------------------------------------------------
# Scrolling name label
# ---------------------------------------------------------------------------
class ScrollingLabel(tk.Canvas):
    """Clips and horizontally scrolls text that is wider than the widget."""
    _IDLE_MS = 1500
    _SPEED   = 1
    _TICK_MS = 25
    _GAP     = 80

    def __init__(self, parent, text, fg, bg, height=22):
        super().__init__(parent, bg=bg, highlightthickness=0, height=height)
        self._text   = text
        self._fg     = fg
        self._offset = 0
        self._job    = None
        self._tw     = 0
        self._font   = tkfont.Font(family="Segoe UI", size=11, weight="bold")

        self.bind("<Configure>", self._on_configure)
        self.bind("<Destroy>",   lambda e: self._cancel())
        self.bind("<Enter>",     lambda e: self._pause())
        self.bind("<Leave>",     lambda e: self._schedule())

    def _on_configure(self, e):
        self._tw = self._font.measure(self._text)
        self._offset = 0
        self._draw()
        self._schedule()

    def _draw(self):
        h = max(self.winfo_height(), 1)
        self.delete("all")
        self.create_text(-self._offset, h // 2,
                         text=self._text, font=self._font,
                         fill=self._fg, anchor="w")

    def _schedule(self):
        self._cancel()
        if self._tw > self.winfo_width():
            self._job = self.after(self._IDLE_MS, self._tick)

    def _tick(self):
        self._offset += self._SPEED
        self._draw()
        if self._offset >= self._tw + self._GAP:
            self._offset = 0
            self._draw()
            self._job = self.after(self._IDLE_MS, self._tick)
        else:
            self._job = self.after(self._TICK_MS, self._tick)

    def _pause(self):
        self._cancel()
        self._offset = 0
        self._draw()

    def _cancel(self):
        if self._job:
            self.after_cancel(self._job)
            self._job = None


# ---------------------------------------------------------------------------
# Pipeline card
# ---------------------------------------------------------------------------
class PipelineCard(tk.Frame):
    """Card displaying a pipeline and its steps summary."""
    _PIPE_ACCENT  = "#5c4bbd"
    _PIPE_ACCENT2 = "#7060d0"

    def __init__(self, parent, pipeline_id: int, name: str, db: ScriptDB,
                 group_name: str, on_run, on_edit, on_refresh, on_stop=None, *, is_running: bool = False):
        super().__init__(parent, bg=C["card_bg"],
                         highlightbackground=C["border"], highlightthickness=1)
        self.pipeline_id = pipeline_id
        self._name = name
        self._group_name = group_name
        self.db = db
        self.on_run = on_run
        self.on_edit = on_edit
        self.on_refresh = on_refresh

        steps = db.list_pipeline_steps(pipeline_id)

        # Left accent strip (indigo, distinct from script cards)
        tk.Frame(self, bg=self._PIPE_ACCENT, width=5).pack(side="left", fill="y")

        # Buttons (right, packed first so they always claim space)
        btn_area = tk.Frame(self, bg=C["border"])
        btn_area.pack(side="right", fill="y")

        def _sep():
            tk.Frame(btn_area, bg=C["border"], width=1).pack(side="left", fill="y")

        def _rbtn(text, bg, hover_bg, cmd, **kw):
            b = tk.Button(btn_area, text=text, bg=bg,
                          fg=kw.get("fg", C["name_fg"]),
                          activebackground=hover_bg,
                          activeforeground=kw.get("active_fg", kw.get("fg", C["name_fg"])),
                          disabledforeground=kw.get("disabled_fg", "#444444"),
                          relief="flat", bd=0, font=("Segoe UI", 10),
                          width=3, state=kw.get("state", "normal"),
                          cursor="hand2" if kw.get("state", "normal") == "normal" else "arrow",
                          command=cmd)
            b.pack(side="left", fill="y")
            if kw.get("state", "normal") == "normal":
                _bg, _hbg = bg, hover_bg
                b.bind("<Enter>", lambda e, _b=b: _b.config(bg=_hbg))
                b.bind("<Leave>", lambda e, _b=b: _b.config(bg=_bg))
            return b

        _sep()
        _rbtn("⚙", C["btn_mod_bg"], C["btn_mod_hover"],
              lambda: on_edit(pipeline_id, name))
        _sep()
        _rbtn("▶", C["btn_run_bg"], C["btn_run_hover"],
              lambda: on_run(pipeline_id, name))
        _sep()
        self._stop_btn = _rbtn("⏹", "#8b0000" if is_running else "#3a3a3a",
              "#5a1a1a" if is_running else "#4a4a4a",
              on_stop or (lambda: None),
              fg="#ffffff" if is_running else "#666666",
              active_fg="#ffffff" if is_running else "#888888")

        # Content
        content = tk.Frame(self, bg=C["card_bg"], padx=12, pady=10)
        content.pack(side="left", fill="both", expand=True)
        self._content = content

        # Badge row
        badge_row = tk.Frame(content, bg=C["card_bg"])
        badge_row.pack(fill="x")
        self._badge_row = badge_row
        tk.Label(badge_row, text="⚡ PIPELINE", bg=self._PIPE_ACCENT, fg="#ffffff",
                 font=("Segoe UI", 7, "bold"), padx=5, pady=1).pack(side="left")
        self._running_lbl = None
        if is_running:
            self._running_lbl = tk.Label(badge_row, text="▶ RUNNING", bg="#27ae60", fg="#ffffff",
                     font=("Segoe UI", 7, "bold"), padx=5, pady=1)
            self._running_lbl.pack(side="left", padx=(4, 0))

        # Name (scrolling if long)
        ScrollingLabel(content, name, C["name_fg"], C["card_bg"]).pack(fill="x", pady=(2, 0))

        # Steps summary row (click to open step review popup)
        n = len(steps)
        if n == 0:
            summary_text = "No steps — click ⚙ to add scripts"
        else:
            parts = [s[2] for s in steps[:4]]
            summary_text = "  →  ".join(parts)
            if n > 4:
                summary_text += f"  →  +{n - 4} more"

        summary_row = tk.Frame(content, bg=C["card_bg"],
                               cursor="hand2" if n > 0 else "")
        summary_row.pack(fill="x")
        self._summary_row = summary_row
        if n > 0:
            tk.Label(summary_row, text="▸ ", bg=C["card_bg"], fg=C["path_fg"],
                     font=("Segoe UI", 8), cursor="hand2").pack(side="left")
        tk.Label(summary_row, text=f"{n} step{'s' if n != 1 else ''}  ·  {summary_text}",
                 bg=C["card_bg"], fg=C["path_fg"], font=("Segoe UI", 8), anchor="w",
                 cursor="hand2" if n > 0 else "").pack(side="left", fill="x", expand=True)

        if n > 0:
            for w in (summary_row, *summary_row.winfo_children()):
                w.bind("<Button-1>", self._show_steps_popup)

        for widget in (self, content):
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)

        self._bind_right_click_all(self)

    def set_running(self, is_running: bool, on_stop=None):
        if is_running:
            self._stop_btn.config(
                bg="#8b0000", activebackground="#5a1a1a",
                fg="#ffffff", activeforeground="#ffffff",
                command=on_stop or (lambda: None),
            )
            self._stop_btn.bind("<Enter>", lambda e: self._stop_btn.config(bg="#5a1a1a"))
            self._stop_btn.bind("<Leave>", lambda e: self._stop_btn.config(bg="#8b0000"))
            if not self._running_lbl:
                self._running_lbl = tk.Label(
                    self._badge_row, text="▶ RUNNING", bg="#27ae60", fg="#ffffff",
                    font=("Segoe UI", 7, "bold"), padx=5, pady=1)
                self._running_lbl.pack(side="left", padx=(4, 0))
        else:
            self._stop_btn.config(
                bg="#3a3a3a", activebackground="#4a4a4a",
                fg="#666666", activeforeground="#888888",
                command=lambda: None,
            )
            self._stop_btn.bind("<Enter>", lambda e: self._stop_btn.config(bg="#4a4a4a"))
            self._stop_btn.bind("<Leave>", lambda e: self._stop_btn.config(bg="#3a3a3a"))
            if self._running_lbl:
                self._running_lbl.destroy()
                self._running_lbl = None

    def _show_steps_popup(self, event=None):
        # Close any existing popup first
        existing = getattr(self, "_steps_popup", None)
        if existing:
            try:
                existing.destroy()
            except tk.TclError:
                pass
            self._steps_popup = None
            return

        steps = self.db.list_pipeline_steps(self.pipeline_id)

        popup = tk.Toplevel(self)
        popup.overrideredirect(True)
        popup.configure(bg=C["border"])
        self._steps_popup = popup

        inner = tk.Frame(popup, bg=C["card_bg"], padx=14, pady=10)
        inner.pack(padx=1, pady=1)

        # Title
        tk.Label(inner, text=self._name, bg=C["card_bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x", pady=(0, 6))
        tk.Frame(inner, bg=C["border"], height=1).pack(fill="x", pady=(0, 6))

        if not steps:
            tk.Label(inner, text="No steps yet.", bg=C["card_bg"], fg=C["path_fg"],
                     font=("Segoe UI", 8)).pack(anchor="w")
        else:
            for i, step in enumerate(steps, 1):
                row = tk.Frame(inner, bg=C["card_bg"])
                row.pack(fill="x", pady=2)
                tk.Label(row, text=f"{i}.", bg=C["card_bg"], fg=C["path_fg"],
                         font=("Segoe UI", 8), width=3, anchor="e").pack(side="left")
                tk.Label(row, text=step[2], bg=C["card_bg"], fg=C["name_fg"],
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left", padx=(6, 0))
                tk.Label(row, text=step[3], bg=C["card_bg"], fg=C["path_fg"],
                         font=("Segoe UI", 7), anchor="w").pack(side="left", padx=(6, 0))
                if len(step) > 6 and step[6] is not None:
                    tk.Label(row, text=f"[{step[6]}]", bg=C["card_bg"], fg=C["accent"],
                             font=("Segoe UI", 7), anchor="w").pack(side="left", padx=(4, 0))

        # Position near click, nudge inside screen bounds
        popup.update_idletasks()
        pw, ph = popup.winfo_reqwidth(), popup.winfo_reqheight()
        sw, sh = popup.winfo_screenwidth(), popup.winfo_screenheight()
        x = min((event.x_root + 12) if event else self.winfo_rootx(), sw - pw - 8)
        y = min((event.y_root + 12) if event else self.winfo_rooty(), sh - ph - 8)
        popup.geometry(f"+{x}+{y}")

        popup.bind("<Escape>", lambda e: popup.destroy())
        popup.bind("<FocusOut>", lambda e: popup.destroy())
        popup.focus_set()

    def _bind_right_click_all(self, widget):
        widget.bind("<Button-3>", self._context_menu)
        for ch in widget.winfo_children():
            self._bind_right_click_all(ch)

    def _on_enter(self, _e=None):
        self._set_bg(self, C["card_hover"])

    def _on_leave(self, _e=None):
        self._set_bg(self, C["card_bg"])

    def _set_bg(self, widget, color):
        try:
            if widget.cget("bg") in (C["card_bg"], C["card_hover"]):
                widget.configure(bg=color)
        except tk.TclError:
            pass
        for ch in widget.winfo_children():
            self._set_bg(ch, color)

    def _context_menu(self, event):
        menu = tk.Menu(self.winfo_toplevel(), tearoff=0,
                       bg="#2d2d2d", fg="#ffffff",
                       activebackground=C["accent"], activeforeground="#ffffff",
                       font=("Segoe UI", 10))
        menu.add_command(label="⚙  Edit",
                         command=lambda: self.on_edit(self.pipeline_id, self._name))
        menu.add_command(label="⧉  Clone", command=self._clone)
        menu.add_separator()
        menu.add_command(label="🗑  Delete", command=self._delete,
                         foreground="#ff8080", activeforeground="#ff8080")
        menu.tk_popup(event.x_root, event.y_root)

    def _clone(self):
        self.db.clone_pipeline(self.pipeline_id)
        self.on_refresh()

    def _delete(self):
        if messagebox.askyesno("Delete Pipeline",
                                f"Delete pipeline '{self._name}'?", parent=self):
            self.db.delete_pipeline(self.pipeline_id)
            self.on_refresh()


# ---------------------------------------------------------------------------
# Preset entry dialog (used inside ScriptDialog)
# ---------------------------------------------------------------------------
class _PresetEntryDialog(tk.Toplevel):
    """Small dialog for entering/editing a param preset value."""

    def __init__(self, parent, params: str, title: str = "Preset"):
        super().__init__(parent)
        self.result = None
        self.title(title)
        self.resizable(False, False)
        self.grab_set()
        self.configure(bg=C["card_bg"])

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        pad = {"padx": 6, "pady": 4}
        ttk.Label(frame, text="Parameters:").grid(row=0, column=0, sticky="w", **pad)
        self._e_params = ttk.Entry(frame, width=36)
        self._e_params.grid(row=0, column=1, sticky="ew", **pad)
        self._e_params.insert(0, params)

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=1, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(btn_row, text="OK",     command=self._ok).pack(side="right", padx=(4, 0))
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side="right")

        self.bind("<Return>", lambda _: self._ok())
        self.bind("<Escape>", lambda _: self.destroy())
        self.transient(parent)
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        self.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")
        self._e_params.focus_set()

    def _ok(self):
        params = self._e_params.get().strip()
        if not params:
            messagebox.showwarning("Required", "Please enter parameters.", parent=self)
            return
        self.result = params
        self.destroy()


# ---------------------------------------------------------------------------
# Param picker dialog (shown before running when presets exist)
# ---------------------------------------------------------------------------
class ParamPickerDialog(tk.Toplevel):
    """Let the user pick which param preset to use before running a script."""

    def __init__(self, parent, script_name: str, default_params: str, presets: list):
        """presets: list of (id, label, params)"""
        super().__init__(parent)
        self.result = None  # set to chosen params string; None means cancelled
        self.title(f"Run — {script_name}")
        self.resizable(False, False)
        self.grab_set()
        self.configure(bg=C["card_bg"])

        title_strip = tk.Frame(self, bg=C["card_bg"])
        title_strip.pack(fill="x")
        tk.Label(title_strip, text="Select parameters",
                 bg=C["card_bg"], fg=C["name_fg"],
                 font=("Segoe UI", 11, "bold"),
                 anchor="w", padx=16, pady=12).pack(fill="x")
        tk.Frame(title_strip, bg=C["border"], height=1).pack(fill="x")

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)

        self._choice = tk.StringVar(value="__default__")

        options = [("__default__", "Default", default_params)] + \
                  [(str(pid), lbl, prm) for pid, lbl, prm in presets]

        for val, lbl, prm in options:
            row = tk.Frame(body, bg=C["card_bg"], pady=3)
            row.pack(fill="x")
            tk.Radiobutton(
                row, variable=self._choice, value=val,
                text=lbl if lbl != prm else prm,
                bg=C["card_bg"], fg=C["name_fg"],
                selectcolor=C["card_bg"],
                activebackground=C["card_bg"],
                font=("Segoe UI", 10),
                anchor="w", cursor="hand2",
            ).pack(side="left")

        self._params_map = {val: prm for val, _, prm in options}

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")
        btn_row = ttk.Frame(self, padding=(16, 8))
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="▶ Run",   command=self._run).pack(side="right", padx=(4, 0))
        ttk.Button(btn_row, text="Cancel",  command=self.destroy).pack(side="right")

        self.bind("<Return>", lambda _: self._run())
        self.bind("<Escape>", lambda _: self.destroy())
        self.transient(parent)
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        self.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    def _run(self):
        self.result = self._params_map[self._choice.get()]
        self.destroy()


# ---------------------------------------------------------------------------
# Script card
# ---------------------------------------------------------------------------
class ScriptCard(tk.Frame):
    """A single styled card: accent strip + name/path + Modify + Run."""

    def __init__(self, parent, record, db: ScriptDB, runner, on_refresh,
                 on_move_up, on_move_down, on_move_top, on_stop=None, *, is_running: bool = False):
        super().__init__(parent, bg=C["card_bg"],
                         highlightbackground=C["border"], highlightthickness=1)
        sid, name, path, params, interp, _created, last_run, last_run_status, _group = record
        self.script_id = sid
        self._name = name
        self._group_name = _group or ""
        self.db = db
        self.runner = runner
        self.on_refresh = on_refresh
        self.selected = tk.BooleanVar(value=False)

        # Left accent strip
        tk.Frame(self, bg=C["accent"], width=5).pack(side="left", fill="y")

        # Checkbox (hidden until select mode is on)
        self._chk = tk.Checkbutton(self, variable=self.selected,
                                   bg=C["card_bg"], activebackground=C["card_bg"],
                                   relief="flat", bd=0, cursor="hand2")

        self._on_move_top = on_move_top
        self._on_move_up  = on_move_up
        self._on_move_down = on_move_down

        # Buttons — packed before text_area so they always claim space on the right
        btn_area = tk.Frame(self, bg=C["border"])
        btn_area.pack(side="right", fill="y")

        def _sep():
            tk.Frame(btn_area, bg=C["border"], width=1).pack(side="left", fill="y")

        def _rbtn(text, bg, hover_bg, cmd, **kw):
            b = tk.Button(btn_area, text=text, bg=bg,
                          fg=kw.get("fg", C["name_fg"]),
                          activebackground=hover_bg,
                          activeforeground=kw.get("active_fg", kw.get("fg", C["name_fg"])),
                          disabledforeground=kw.get("disabled_fg", "#444444"),
                          relief="flat", bd=0, font=("Segoe UI", 10),
                          width=3, state=kw.get("state", "normal"),
                          cursor="hand2" if kw.get("state", "normal") == "normal" else "arrow",
                          command=cmd)
            b.pack(side="left", fill="y")
            if kw.get("state", "normal") == "normal":
                _bg, _hbg = bg, hover_bg
                b.bind("<Enter>", lambda e, _b=b: _b.config(bg=_hbg))
                b.bind("<Leave>", lambda e, _b=b: _b.config(bg=_bg))
            return b

        # Text area
        self._text_area = text_area = tk.Frame(self, bg=C["card_bg"], padx=12, pady=10)
        text_area.pack(side="left", fill="both", expand=True)

        tag_text, tag_bg = _script_tag(path)
        badge_row = tk.Frame(text_area, bg=C["card_bg"])
        badge_row.pack(anchor="w", fill="x", pady=(0, 2))
        self._badge_row = badge_row
        tk.Label(badge_row, text=tag_text, bg=tag_bg, fg="#ffffff",
                 font=("Segoe UI", 7, "bold"), padx=5, pady=1).pack(side="left")
        self._running_lbl = None
        if is_running:
            self._running_lbl = tk.Label(badge_row, text="▶ RUNNING", bg="#27ae60", fg="#ffffff",
                     font=("Segoe UI", 7, "bold"), padx=5, pady=1)
            self._running_lbl.pack(side="left", padx=(4, 0))
        ScrollingLabel(text_area, name, C["name_fg"], C["card_bg"]).pack(fill="x")
        tk.Label(text_area, text=path, bg=C["card_bg"], fg=C["path_fg"],
                 font=("Segoe UI", 8), anchor="w").pack(fill="x")

        if last_run and last_run != "-":
            meta_row = tk.Frame(text_area, bg=C["card_bg"])
            meta_row.pack(fill="x")
            tk.Label(meta_row, text=f"Last run: {last_run}", bg=C["card_bg"],
                     fg=C["path_fg"], font=("Segoe UI", 7, "italic"), anchor="w").pack(side="left")
            if last_run_status == "error":
                tk.Label(meta_row, text="✕ Failed", bg="#c0392b", fg="#ffffff",
                         font=("Segoe UI", 7, "bold"), padx=5, pady=1).pack(side="left", padx=(6, 0))
            elif last_run_status == "ok":
                tk.Label(meta_row, text="✓ OK", bg="#2ecc71", fg="#ffffff",
                         font=("Segoe UI", 7, "bold"), padx=5, pady=1).pack(side="left", padx=(6, 0))

        self._params_combo = None
        presets = db.list_param_presets(sid)
        if presets:
            preset_values = [p[2] for p in presets]
            self._params_combo = ttk.Combobox(
                text_area, values=preset_values,
                state="readonly", font=("Segoe UI", 8),
            )
            self._params_combo.pack(fill="x", pady=(4, 0))
            if params in preset_values:
                self._params_combo.set(params)
            else:
                self._params_combo.current(0)

        _sep()
        _rbtn("⚙", C["btn_mod_bg"], C["btn_mod_hover"], self._modify)
        _sep()
        _rbtn("▶+", "#1a6b9a", "#1a5a80", self._run_with_param)
        _sep()
        _rbtn("▶", C["btn_run_bg"], C["btn_run_hover"], self._run)
        _sep()
        self._stop_btn = _rbtn("⏹", "#8b0000" if is_running else "#3a3a3a",
              "#5a1a1a" if is_running else "#4a4a4a",
              on_stop or (lambda: None),
              fg="#ffffff" if is_running else "#666666",
              active_fg="#ffffff" if is_running else "#888888")

        # Hover highlight on whole card
        for widget in (self, text_area):
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)

        self._bind_right_click(self)

    def set_running(self, is_running: bool, on_stop=None):
        if is_running:
            self._stop_btn.config(
                bg="#8b0000", activebackground="#5a1a1a",
                fg="#ffffff", activeforeground="#ffffff",
                command=on_stop or (lambda: None),
            )
            self._stop_btn.bind("<Enter>", lambda e: self._stop_btn.config(bg="#5a1a1a"))
            self._stop_btn.bind("<Leave>", lambda e: self._stop_btn.config(bg="#8b0000"))
            if not self._running_lbl:
                self._running_lbl = tk.Label(
                    self._badge_row, text="▶ RUNNING", bg="#27ae60", fg="#ffffff",
                    font=("Segoe UI", 7, "bold"), padx=5, pady=1)
                self._running_lbl.pack(side="left", padx=(4, 0))
        else:
            self._stop_btn.config(
                bg="#3a3a3a", activebackground="#4a4a4a",
                fg="#666666", activeforeground="#888888",
                command=lambda: None,
            )
            self._stop_btn.bind("<Enter>", lambda e: self._stop_btn.config(bg="#4a4a4a"))
            self._stop_btn.bind("<Leave>", lambda e: self._stop_btn.config(bg="#3a3a3a"))
            if self._running_lbl:
                self._running_lbl.destroy()
                self._running_lbl = None

    def show_checkbox(self, command=None):
        self._chk.config(command=command)
        self._chk.pack(side="left", padx=(6, 0), before=self._text_area)

    def hide_checkbox(self):
        self._chk.pack_forget()
        self.selected.set(False)

    def _on_enter(self, _e=None):
        self._set_card_bg(self, C["card_hover"])

    def _on_leave(self, _e=None):
        self._set_card_bg(self, C["card_bg"])

    def _set_card_bg(self, widget, color):
        try:
            if widget.cget("bg") in (C["card_bg"], C["card_hover"]):
                widget.config(bg=color)
        except Exception:
            pass
        for child in widget.winfo_children():
            self._set_card_bg(child, color)

    def _bind_right_click(self, widget):
        widget.bind("<Button-3>", self._card_context_menu)
        for child in widget.winfo_children():
            self._bind_right_click(child)

    def _card_context_menu(self, event):
        menu = tk.Menu(self.winfo_toplevel(), tearoff=0,
                       bg="#2d2d2d", fg="#ffffff",
                       activebackground=C["accent"], activeforeground="#ffffff",
                       font=("Segoe UI", 10))
        menu.add_command(label="⤒  Move to Top", command=self._on_move_top)
        menu.add_command(label="▲  Move Up",     command=self._on_move_up)
        menu.add_command(label="▼  Move Down",   command=self._on_move_down)
        menu.add_separator()
        menu.add_command(label="⧉  Clone",       command=self._clone)
        menu.add_separator()
        menu.add_command(label="🗑  Delete",      command=self._delete_card,
                         foreground="#ff8080", activeforeground="#ff8080")
        menu.tk_popup(event.x_root, event.y_root)

    def _modify(self):
        ScriptDialog(self.winfo_toplevel(), self.db,
                     script_id=self.script_id, on_save=self.on_refresh,
                     existing_groups=self.db.list_groups())

    def _clone(self):
        rec = self.db.get(self.script_id)
        if rec:
            _, name, path, params, interp, grp = rec
            self.db.add(f"{name} (copy)", path, params, interp, grp)
            self.on_refresh()

    def _delete_card(self):
        if messagebox.askyesno("Delete", f"Delete '{self._name}'?", parent=self):
            self.db.delete(self.script_id)
            self.on_refresh()

    def _run(self):
        rec = self.db.get(self.script_id)
        if rec:
            _, name, path, params, interp, _grp = rec
            if self._params_combo:
                params = self._params_combo.get()
            self.runner(self.script_id, name, path, params, interp)

    def _run_with_param(self):
        rec = self.db.get(self.script_id)
        if not rec:
            return
        _, name, path, default_params, interp, _grp = rec
        script_id = self.script_id
        runner = self.runner
        on_refresh = self.on_refresh
        db = self.db
        current = self._params_combo.get() if self._params_combo else default_params

        dlg = _PresetEntryDialog(self.winfo_toplevel(), current, title="Run with Parameters")
        self.wait_window(dlg)
        if dlg.result is None:
            return

        chosen = dlg.result
        existing = db.list_param_presets(script_id)
        if not any(p[2] == chosen for p in existing):
            db.replace_param_presets(script_id, [(p[1], p[2]) for p in existing] + [(chosen, chosen)])
        db.update(script_id, name, path, chosen, interp, _grp)
        on_refresh()

        runner(script_id, name, path, chosen, interp)


# ---------------------------------------------------------------------------
# Advanced Options dialog
# ---------------------------------------------------------------------------
class AdvancedOptionsDialog(tk.Toplevel):
    def __init__(self, parent, settings: dict, on_save):
        super().__init__(parent)
        self._settings = dict(settings)
        self._on_save  = on_save
        self.title("Advanced Options")
        self.configure(bg=C["bg"])
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        # ── variables ──────────────────────────────────────────────
        self._start_with_windows = tk.BooleanVar(value=_startup_enabled())
        self._always_on_top     = tk.BooleanVar(value=self._settings["always_on_top"])
        self._snap_corner       = tk.StringVar(
            value=_CORNER_VAL_TO_LABEL.get(self._settings.get("snap_corner") or "none", "Off"))
        self._snap_corner.trace_add("write", self._on_corner_change)
        self._remember_group    = tk.BooleanVar(value=self._settings["remember_last_group"])
        self._start_minimized   = tk.BooleanVar(value=self._settings["start_minimized"])
        self._remember_geometry = tk.BooleanVar(value=self._settings["remember_window_geometry"])
        self._win_width         = tk.StringVar(value=str(self._settings.get("window_width",  540)))
        self._win_height        = tk.StringVar(value=str(self._settings.get("window_height", 640)))
        self._max_lines         = tk.StringVar(value=str(self._settings["max_output_lines"]))
        self._auto_clear        = tk.BooleanVar(value=self._settings["auto_clear_output"])
        self._auto_scroll       = tk.BooleanVar(value=self._settings["auto_scroll_output"])
        self._auto_check_update = tk.BooleanVar(value=self._settings.get("auto_check_update", True))
        self._notify_on_complete = tk.BooleanVar(value=self._settings.get("notify_on_complete", True))

        self._build()
        self.update_idletasks()
        pw, ph = parent.winfo_rootx(), parent.winfo_rooty()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{pw + 60}+{ph + 60}")

    def _on_corner_change(self, *_):
        val = _CORNER_LABEL_TO_VAL.get(self._snap_corner.get(), "none")
        if val and val != "none":
            _apply_snap_corner(self.master, val)

    # ── helpers ────────────────────────────────────────────────────
    def _section(self, text: str) -> tk.Frame:
        tk.Label(self._body, text=text, bg=C["bg"], fg=C["accent"],
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(
            fill="x", padx=16, pady=(14, 2))
        sep = tk.Frame(self._body, bg=C["accent"], height=1)
        sep.pack(fill="x", padx=16, pady=(0, 6))
        frame = tk.Frame(self._body, bg=C["bg"])
        frame.pack(fill="x", padx=24, pady=2)
        return frame

    def _chk(self, parent, text: str, var: tk.BooleanVar) -> tk.Checkbutton:
        cb = tk.Checkbutton(parent, text=text, variable=var,
                            bg=C["bg"], fg=C["name_fg"],
                            selectcolor=C["card_bg"],
                            activebackground=C["bg"], activeforeground=C["name_fg"],
                            font=("Segoe UI", 9), anchor="w")
        cb.pack(fill="x", pady=2)
        return cb

    def _build(self):
        self._body = tk.Frame(self, bg=C["bg"])
        self._body.pack(fill="both", expand=True)

        # ── Startup ────────────────────────────────────────────────
        f = self._section("STARTUP")
        if sys.platform == "win32":
            self._chk(f, "Start with Windows",               self._start_with_windows)
        self._chk(f, "Always on top",                     self._always_on_top)
        self._chk(f, "Remember last active group",        self._remember_group)
        self._chk(f, "Start minimized",                  self._start_minimized)
        self._chk(f, "Remember window size and position", self._remember_geometry)

        # Window size
        size_row = tk.Frame(f, bg=C["bg"])
        size_row.pack(fill="x", pady=(8, 2))
        vcmd_int = (self.register(lambda s: s.isdigit() or s == ""), "%P")
        tk.Label(size_row, text="Window size:", bg=C["bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9)).pack(side="left")
        tk.Spinbox(size_row, from_=400, to=3840, increment=10,
                   textvariable=self._win_width, width=6,
                   validate="key", validatecommand=vcmd_int,
                   bg=C["card_bg"], fg=C["name_fg"],
                   buttonbackground=C["card_bg"],
                   font=("Segoe UI", 9)).pack(side="left", padx=(8, 0))
        tk.Label(size_row, text="×", bg=C["bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9)).pack(side="left", padx=4)
        tk.Spinbox(size_row, from_=300, to=2160, increment=10,
                   textvariable=self._win_height, width=6,
                   validate="key", validatecommand=vcmd_int,
                   bg=C["card_bg"], fg=C["name_fg"],
                   buttonbackground=C["card_bg"],
                   font=("Segoe UI", 9)).pack(side="left")

        # Corner picker
        row = tk.Frame(f, bg=C["bg"])
        row.pack(fill="x", pady=(8, 2))
        tk.Label(row, text="Snap to screen corner:", bg=C["bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9)).pack(side="left")
        ttk.Combobox(row, textvariable=self._snap_corner,
                     values=[l for l, _ in _CORNER_CHOICES],
                     state="readonly", width=18,
                     font=("Segoe UI", 9)).pack(side="left", padx=(8, 0))

        # ── Output ─────────────────────────────────────────────────
        f = self._section("OUTPUT")
        self._chk(f, "Auto-clear output before each run",        self._auto_clear)
        self._chk(f, "Auto-scroll to bottom",                     self._auto_scroll)
        self._chk(f, "Notify when script / pipeline completes",   self._notify_on_complete)
        self._chk(f, "Check for updates on startup",              self._auto_check_update)

        row = tk.Frame(f, bg=C["bg"])
        row.pack(fill="x", pady=4)
        tk.Label(row, text="Max output lines:", bg=C["bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9)).pack(side="left")
        vcmd = (self.register(lambda s: s.isdigit() or s == ""), "%P")
        tk.Spinbox(row, from_=100, to=50000, increment=100,
                   textvariable=self._max_lines, width=7,
                   validate="key", validatecommand=vcmd,
                   bg=C["card_bg"], fg=C["name_fg"],
                   buttonbackground=C["card_bg"],
                   font=("Segoe UI", 9)).pack(side="left", padx=(8, 0))

        # ── Buttons ────────────────────────────────────────────────
        btn_row = tk.Frame(self, bg=C["bg"])
        btn_row.pack(fill="x", padx=16, pady=12)
        _flat_button(btn_row, "Cancel", "#3a3a3a", "#555",
                     self.destroy, width=10).pack(side="right", padx=(6, 0))
        _flat_button(btn_row, "Save", C["accent"], C["accent2"],
                     self._save, width=10).pack(side="right")

    def _save(self):
        try:
            max_lines = max(100, int(self._max_lines.get() or 100))
        except ValueError:
            max_lines = _SETTINGS_DEFAULTS["max_output_lines"]
        try:
            win_w = max(400, int(self._win_width.get()  or 540))
            win_h = max(300, int(self._win_height.get() or 640))
        except ValueError:
            win_w, win_h = 540, 640
        self._settings.update({
            "always_on_top":            self._always_on_top.get(),
            "snap_corner":              _CORNER_LABEL_TO_VAL.get(self._snap_corner.get(), "none"),
            "window_width":             win_w,
            "window_height":            win_h,
            "remember_last_group":      self._remember_group.get(),
            "start_minimized":          self._start_minimized.get(),
            "remember_window_geometry": self._remember_geometry.get(),
            "max_output_lines":         max_lines,
            "auto_clear_output":        self._auto_clear.get(),
            "auto_scroll_output":       self._auto_scroll.get(),
            "notify_on_complete":       self._notify_on_complete.get(),
            "auto_check_update":        self._auto_check_update.get(),
        })
        try:
            _set_startup(self._start_with_windows.get())
        except Exception as e:
            messagebox.showerror("Startup Error",
                                 f"Could not update Windows startup entry:\n{e}",
                                 parent=self)
            return
        self._on_save(self._settings)
        self.destroy()


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------
_BaseWindow = TkinterDnD.Tk if _DND_AVAILABLE else tk.Tk


class RYOSApp(_BaseWindow):
    def __init__(self):
        super().__init__()
        if sys.platform == "win32":
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("RYOS.RunYourOwnScripts")

        self.title("RYOS — Run Your Own Scripts")
        self.minsize(480, 320)
        self.configure(bg=C["bg"])
        _icon = Path(getattr(sys, "_MEIPASS", str(_BASE))) / "icon.ico"
        if _icon.exists():
            self.iconbitmap(str(_icon))
        self.db = ScriptDB()
        self._settings: dict = _load_settings()

        self.update_idletasks()
        w = self._settings.get("window_width",  540)
        h = self._settings.get("window_height", 640)
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        self.current_process = None
        self.output_queue: queue.Queue = queue.Queue()
        self._cards: list[ScriptCard] = []
        self._pipeline_cards: list[PipelineCard] = []
        self._select_mode = False
        self._pipeline_queue: list = []
        self._pipeline_step_idx = 0
        self._pipeline_total = 0
        self._running_script_id: int | None = None
        self._running_pipeline_id: int | None = None
        self._run_start_time: datetime | None = None
        # drag-and-drop card state
        self._drag_card: ScriptCard | None = None
        self._drag_start_x = self._drag_start_y = 0
        self._drag_ghost: tk.Toplevel | None = None
        self._drag_indicator: tk.Frame | None = None
        self._drag_insert_before: int | None = None
        self._drag_target_group: str | None = None
        self._drag_tab_highlight: tuple | None = None
        self._section_collapsed: dict[str, dict[str, bool]] = {}
        self._output_tabs: dict = {}
        self._active_tab_key: str | None = None

        groups = self.db.list_groups()
        if self._settings["remember_last_group"] and self._settings.get("last_group") in groups:
            self._active_group: str | None = self._settings["last_group"]
        else:
            self._active_group = groups[0] if groups else None

        corner = self._settings.get("snap_corner") or ""
        if not corner or corner == "none":
            # Only restore saved geometry when snap is disabled
            if self._settings["remember_window_geometry"] and self._settings.get("window_geometry"):
                self.geometry(self._settings["window_geometry"])

        self._build_ui()
        self._refresh()
        self.after(80, self._drain_output_queue)
        self.after(0,  self._setup_file_drop)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        if self._settings.get("auto_check_update", True):
            threading.Thread(target=self._check_for_update, daemon=True).start()
        self.attributes("-topmost", self._settings["always_on_top"])
        if corner and corner != "none":
            self.after(0, lambda c=corner: _apply_snap_corner(self, c))
        if self._settings["start_minimized"]:
            self.after(0, self.iconify)

    # ---------- file drag-and-drop ----------
    def _setup_file_drop(self):
        if not _DND_AVAILABLE:
            return
        self.drop_target_register(DND_FILES)
        self.dnd_bind("<<Drop>>", self._on_drop_event)

    def _on_drop_event(self, event):
        paths = self.tk.splitlist(event.data)
        self._on_files_dropped(list(paths))

    def _on_files_dropped(self, paths: list[str]):
        groups = self.db.list_groups()
        if not groups:
            name = simpledialog.askstring(
                "Create a Group First",
                "You have no groups yet.\nEnter a group name to continue:",
                parent=self,
            )
            if not (name and name.strip()):
                return
            self.db.create_group(name.strip())
            self._active_group = name.strip()
            self._refresh_tabs()
            groups = self.db.list_groups()

        group = self._active_group or ""
        added = 0
        for path in paths:
            p = Path(path)
            if p.is_file():
                self.db.add(p.stem, str(p), "", detect_interpreter(str(p)), group)
                added += 1
        if added:
            self._refresh_cards()

    # ---------- UI ----------
    def _build_ui(self):
        # Header
        header = tk.Frame(self, bg=C["header_bg"], pady=14, padx=18)
        header.pack(fill="x")
        wm = tk.Frame(header, bg=C["header_bg"])
        wm.pack(side="left")
        header_btn_size = 6
        tk.Label(wm, text="⚡", bg=C["header_bg"], fg="#FFD23F",
                 font=("Segoe UI", 14, "bold")).pack(side="left")
        tk.Label(wm, text=" RYOS", bg=C["header_bg"], fg="#ffffff",
                 font=("Segoe UI", 14, "bold")).pack(side="left")
        add_btn = _flat_button(header, "+ Script", C["accent"], C["accent2"],
                               self._add_script, width=header_btn_size)
        add_btn.config(bg=C["accent"])
        add_btn.pack(side="right")
        add_group_btn = _flat_button(header, "+ Group", "#2e7d32", "#388e3c",
                                     self._create_group, width=header_btn_size)
        add_group_btn.pack(side="right", padx=(0, 6))
        self._pipeline_btn = _flat_button(header, "+ Pipeline", "#5c4bbd", "#7060d0",
                                           self._add_pipeline, width=header_btn_size)
        self._pipeline_btn.pack(side="right", padx=(0, 6))

        # Options dropdown
        self._options_menu = tk.Menu(self, tearoff=0, bg="#2d2d2d", fg="#ffffff",
                                     activebackground=C["accent"], activeforeground="#ffffff",
                                     borderwidth=0, relief="flat")
        self._options_menu.add_command(label="☑  Select scripts",     command=self._toggle_select_mode)
        self._options_menu.add_separator()
        self._options_menu.add_command(label="📤  Export all groups",  command=self._export_config)
        self._options_menu.add_command(label="📥  Import config",      command=self._import_config)
        self._options_menu.add_separator()
        self._options_menu.add_command(label="⚙  Advanced options…",  command=self._open_advanced_options)
        self._options_menu.add_separator()
        self._options_menu.add_command(label="🔔  Check for updates",  command=self._manual_update_check)
        self._options_menu.add_separator()
        self._options_menu.add_command(label="🗑  Delete All",         command=self._delete_all)

        options_btn = _flat_button(header, "⚙", "#3a3a3a", "#555",
                                   self._show_options_menu, width=4)
        options_btn.pack(side="right", padx=8)
        self._options_btn = options_btn

        self._select_btn = None  # managed via menu label update

        # Amber select-mode bar — shown between header and list when select mode is on
        self._select_bar = tk.Frame(self, bg="#fff7e6",
                                    highlightbackground="#f3d99a", highlightthickness=1)
        self._select_bar_var = tk.StringVar(value="Tick the checkboxes next to scripts you want to delete.")
        tk.Label(self._select_bar, textvariable=self._select_bar_var,
                 bg="#fff7e6", fg="#7a4a00", font=("Segoe UI", 9),
                 padx=14, pady=5, anchor="w").pack(side="left", fill="x", expand=True)
        self._del_selected_btn = _flat_button(self._select_bar, "🗑 Delete Selected",
                                              "#5a2d2d", "#7a3d3d", self._delete_selected, width=15)
        self._del_selected_btn.pack(side="right", padx=10, pady=4)
        self._sel_all_btn = tk.Button(
            self._select_bar, text="Select All",
            bg="#fff7e6", fg="#7a4a00",
            activebackground="#f3d99a", activeforeground="#7a4a00",
            relief="flat", bd=0, padx=10, pady=5,
            font=("Segoe UI", 9, "bold"), cursor="hand2",
            command=self._toggle_select_all,
        )
        self._sel_all_btn.bind("<Enter>", lambda e: self._sel_all_btn.config(bg="#f3d99a"))
        self._sel_all_btn.bind("<Leave>", lambda e: self._sel_all_btn.config(bg="#fff7e6"))
        self._sel_all_btn.pack(side="right", padx=4, pady=4)

        # Status bar first — must be packed before paned so it sits at bottom
        self.status_var = tk.StringVar(value="Ready.")
        self._status_bar = tk.Label(self, textvariable=self.status_var, anchor="w",
                                    bg=C["status_bg"], fg="#555", font=("Segoe UI", 8),
                                    padx=10, pady=4)
        self._status_bar.pack(fill="x", side="bottom")

        # PanedWindow — resizable split between cards and output
        self._paned = ttk.PanedWindow(self, orient="vertical")
        self._paned.pack(fill="both", expand=True)

        # Scrollable card list (top pane)
        cards_pane = tk.Frame(self._paned, bg=C["bg"])
        self._paned.add(cards_pane, weight=3)

        # Tab bar
        self._tab_bar = tk.Frame(cards_pane, bg=C["bg"])
        self._tab_bar.pack(fill="x", padx=12, pady=(8, 0))
        tk.Frame(cards_pane, bg=C["border"], height=1).pack(fill="x", padx=12)

        container = tk.Frame(cards_pane, bg=C["bg"])
        container.pack(fill="both", expand=True, padx=12, pady=(8, 12))

        canvas = tk.Canvas(container, highlightthickness=0, bg=C["bg"])
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self.cards_frame = tk.Frame(canvas, bg=C["bg"])
        self._canvas_window = canvas.create_window((0, 0), window=self.cards_frame, anchor="nw")

        self.cards_frame.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(
            self._canvas_window, width=e.width))
        def _on_wheel(e):
            # only scroll when content is taller than the viewport
            content_h = self.cards_frame.winfo_reqheight()
            viewport_h = canvas.winfo_height()
            if content_h > viewport_h:
                canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        self._canvas = canvas

        # Output panel (bottom pane, collapsible)
        self._out_expanded = False
        self.out_panel = tk.Frame(self._paned, bg="#1e1e1e")

        out_header = tk.Frame(self.out_panel, bg="#2d2d2d", pady=4, padx=10)
        out_header.pack(fill="x")
        tk.Label(out_header, text="Output", bg="#2d2d2d", fg="#aaa",
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(side="left")
        self._toggle_btn = tk.Button(out_header, text="▲  Show Output", bg="#2d2d2d", fg="#aaa",
                                     activebackground="#3d3d3d", activeforeground="#fff",
                                     relief="flat", bd=0, cursor="hand2", font=("Segoe UI", 9),
                                     command=self._toggle_output)
        self._toggle_btn.pack(side="right")
        tk.Button(out_header, text="🗑 Clear", bg="#2d2d2d", fg="#aaa",
                  activebackground="#3d3d3d", activeforeground="#fff",
                  relief="flat", bd=0, cursor="hand2", font=("Segoe UI", 9),
                  command=self._clear_log).pack(side="right", padx=4)

        # tab bar and body — not packed on init (starts collapsed)
        self._out_tab_bar = tk.Frame(self.out_panel, bg="#252525")
        self._out_tab_body = tk.Frame(self.out_panel, bg="#1e1e1e")
        self._init_all_tab()

        self._paned.add(self.out_panel, weight=0)


    # ---------- group header ----------
    def _make_group_header(self, name: str):
        hdr = tk.Frame(self.cards_frame, bg=C["bg"])
        hdr.pack(fill="x", pady=(16, 2))
        tk.Label(hdr, text=name.upper(), bg=C["bg"], fg=C["path_fg"],
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        tk.Frame(hdr, bg=C["border"], height=1).pack(
            side="left", fill="x", expand=True, padx=(8, 0), pady=4)

    def _make_section_header(self, parent, group: str, section: str, label: str) -> tk.Frame:
        """Collapsible section row; returns the content frame."""
        collapsed = self._section_collapsed.get(group, {}).get(section, False)

        section_frame = tk.Frame(parent, bg=C["bg"])
        section_frame.pack(fill="x")

        hdr = tk.Frame(section_frame, bg=C["bg"], cursor="hand2")
        hdr.pack(fill="x", padx=2, pady=(6, 0))

        arrow_var = tk.StringVar(value="▶" if collapsed else "▼")
        arrow_lbl = tk.Label(hdr, textvariable=arrow_var, bg=C["bg"], fg=C["path_fg"],
                             font=("Segoe UI", 8), cursor="hand2", width=2)
        arrow_lbl.pack(side="left")
        tk.Label(hdr, text=label.upper(), bg=C["bg"], fg=C["path_fg"],
                 font=("Segoe UI", 8, "bold"), cursor="hand2").pack(side="left")
        tk.Frame(hdr, bg=C["border"], height=1).pack(
            side="left", fill="x", expand=True, padx=(6, 0), pady=4)

        content = tk.Frame(section_frame, bg=C["bg"])
        if not collapsed:
            content.pack(fill="x")

        def _toggle(_e=None):
            is_col = self._section_collapsed.get(group, {}).get(section, False)
            if group not in self._section_collapsed:
                self._section_collapsed[group] = {}
            self._section_collapsed[group][section] = not is_col
            if is_col:
                arrow_var.set("▼")
                content.pack(fill="x")
            else:
                arrow_var.set("▶")
                content.pack_forget()

        for w in (hdr, arrow_lbl) + tuple(hdr.winfo_children()):
            w.bind("<Button-1>", _toggle)

        return content

    # ---------- tab bar ----------
    def _refresh_tabs(self):
        for w in self._tab_bar.winfo_children():
            w.destroy()
        self._group_tab_btns: list[tuple[str, tk.Button]] = []
        self._drag_state: dict | None = None

        for g in self.db.list_groups():
            btn, wrapper, inner, indicator = self._add_tab_btn(g, g, self._active_group == g)
            idx = len(self._group_tab_btns)
            self._group_tab_btns.append((g, btn, wrapper, inner, indicator))
            btn.bind("<ButtonPress-1>",   lambda e, i=idx: self._drag_start(e, i))
            btn.bind("<B1-Motion>",       self._drag_motion)
            btn.bind("<ButtonRelease-1>", self._drag_end)

        plus = tk.Button(
            self._tab_bar, text="+",
            bg=C["bg"], fg="#2d3748",
            activebackground=C["card_hover"], activeforeground=C["accent"],
            relief="flat", bd=0, padx=10, pady=7,
            font=("Segoe UI", 10), cursor="hand2",
            command=self._create_group,
        )
        plus.bind("<Enter>", lambda e: plus.config(bg=C["card_hover"]))
        plus.bind("<Leave>", lambda e: plus.config(bg=C["bg"]))
        plus.pack(side="left", padx=(8, 2))

        self._all_tab_refs = self._add_tab_btn(None, "All", self._active_group is None, side="right")

    def _add_tab_btn(self, group, label, is_active, side="left"):
        if is_active:
            btn_bg, fg, fw = C["card_bg"], C["accent"], "bold"
            bar_bg   = C["accent"]
            hover_bg = "#eef2ff"
            border   = C["card_bg"]
        else:
            btn_bg, fg, fw = "#e4e9f0", "#2d3748", "normal"
            bar_bg   = "#e4e9f0"    # no underline on inactive
            hover_bg = "#d8dfe8"
            border   = "#b8c4d0"

        wrapper = tk.Frame(self._tab_bar, bg=border,
                           highlightthickness=0, padx=1, pady=1)
        inner = tk.Frame(wrapper, bg=btn_bg)
        inner.pack(fill="both", expand=True)

        btn = tk.Button(
            inner, text=label,
            bg=btn_bg, fg=fg,
            activebackground=hover_bg, activeforeground=fg,
            relief="flat", bd=0, padx=14, pady=6,
            font=("Segoe UI", 10, fw), cursor="hand2",
            command=lambda g=group: self._switch_group(g),
        )
        btn.pack(fill="x")
        indicator = tk.Frame(inner, bg=bar_bg, height=3)
        indicator.pack(fill="x")

        btn.bind("<Enter>", lambda e, b=btn, h=hover_bg: b.config(bg=h))
        btn.bind("<Leave>", lambda e, b=btn, ob=btn_bg: b.config(bg=ob))
        if group is not None:
            btn.bind("<Button-3>", lambda e, g=group: self._tab_context_menu(e, g))
        wrapper.pack(side=side, padx=3, pady=(3, 0))
        return btn, wrapper, inner, indicator

    def _apply_tab_style(self, is_active, btn, wrapper, inner, indicator):
        if is_active:
            btn_bg, fg, fw = C["card_bg"], C["accent"], "bold"
            bar_bg, hover_bg, border = C["accent"], "#eef2ff", C["card_bg"]
        else:
            btn_bg, fg, fw = "#e4e9f0", "#2d3748", "normal"
            bar_bg, hover_bg, border = "#e4e9f0", "#d8dfe8", "#b8c4d0"
        wrapper.config(bg=border)
        inner.config(bg=btn_bg)
        btn.config(bg=btn_bg, fg=fg, font=("Segoe UI", 10, fw),
                   activebackground=hover_bg, activeforeground=fg)
        indicator.config(bg=bar_bg)
        btn.bind("<Enter>", lambda e, b=btn, h=hover_bg: b.config(bg=h))
        btn.bind("<Leave>", lambda e, b=btn, ob=btn_bg: b.config(bg=ob))

    def _update_tab_styles(self):
        for name, btn, wrapper, inner, indicator in self._group_tab_btns:
            self._apply_tab_style(self._active_group == name, btn, wrapper, inner, indicator)
        if hasattr(self, "_all_tab_refs"):
            self._apply_tab_style(self._active_group is None, *self._all_tab_refs)

    def _switch_group(self, group):
        self._active_group = group
        self._update_tab_styles()
        self._refresh_cards()
        self._canvas.yview_moveto(0)

    def _create_group(self):
        name = simpledialog.askstring("New Group", "Group name:", parent=self)
        if name and name.strip():
            name = name.strip()
            self.db.create_group(name)
            self._active_group = name
            self._refresh()

    def _drag_start(self, event, idx: int):
        self._drag_state = {
            "src_idx": idx,
            "start_x": event.x_root,
            "active": False,
            "hover_idx": None,
        }

    def _drag_motion(self, event):
        if self._drag_state is None:
            return
        if abs(event.x_root - self._drag_state["start_x"]) > 5:
            self._drag_state["active"] = True
        if not self._drag_state["active"]:
            return

        hover_idx = None
        for i, (_, btn, *_rest) in enumerate(self._group_tab_btns):
            bx = btn.winfo_rootx()
            if bx <= event.x_root <= bx + btn.winfo_width():
                hover_idx = i
                break

        prev = self._drag_state["hover_idx"]
        if prev != hover_idx:
            if prev is not None:
                pname, pbtn = self._group_tab_btns[prev][0], self._group_tab_btns[prev][1]
                pbtn.config(bg=C["card_bg"] if self._active_group == pname else "#e4e9f0")
            if hover_idx is not None and hover_idx != self._drag_state["src_idx"]:
                self._group_tab_btns[hover_idx][1].config(bg="#4a4a6a")
            self._drag_state["hover_idx"] = hover_idx

    def _drag_end(self, event):
        if self._drag_state is None:
            return
        state = self._drag_state
        self._drag_state = None

        if not state["active"]:
            return

        hover_idx = state["hover_idx"]
        src_idx = state["src_idx"]
        if hover_idx is not None and hover_idx != src_idx:
            groups = [entry[0] for entry in self._group_tab_btns]
            groups.insert(hover_idx, groups.pop(src_idx))
            self.db.reorder_groups(groups)
            self._refresh_tabs()

        return "break"

    def _rename_group(self, old: str):
        new = simpledialog.askstring("Rename Group", f"New name for '{old}':",
                                     initialvalue=old, parent=self)
        if new and new.strip() and new.strip() != old:
            self.db.rename_group(old, new.strip())
            if self._active_group == old:
                self._active_group = new.strip()
            self._refresh()

    def _delete_group(self, name: str):
        if messagebox.askyesno(
            "Delete Group",
            f"Delete group '{name}'?\n\nScripts in this group will be moved to ungrouped.",
            parent=self,
        ):
            self.db.delete_group(name)
            if self._active_group == name:
                remaining = self.db.list_groups()
                self._active_group = remaining[0] if remaining else None
            self._refresh()

    def _tab_context_menu(self, event, group: str):
        menu = tk.Menu(self, tearoff=0, bg="#2d2d2d", fg="#ffffff",
                       activebackground=C["accent"], activeforeground="#ffffff",
                       font=("Segoe UI", 10))
        menu.add_command(label="✏  Rename", command=lambda: self._rename_group(group))
        menu.add_command(label="📤  Export group", command=lambda: self._export_config(group_name=group))
        menu.add_separator()
        menu.add_command(label="🗑  Delete Group", command=lambda: self._delete_group(group),
                         foreground="#ff8080", activeforeground="#ff8080")
        menu.tk_popup(event.x_root, event.y_root)

    # ---------- refresh ----------
    def _refresh(self):
        self._cards = []
        if self._select_mode:
            self._select_mode = False
            self._select_bar.pack_forget()
            self._options_menu.entryconfig(0, label="☑  Select scripts")
        self._refresh_tabs()
        self._refresh_cards()

    def _refresh_cards(self):
        for w in self.cards_frame.winfo_children():
            w.destroy()
        self._cards = []
        self._pipeline_cards = []

        def make_move(a, b):
            def _move():
                self.db.swap_order(a, b)
                self._refresh()
            return _move

        def make_top(s):
            def _top():
                self.db.move_to_top(s)
                self._refresh()
            return _top

        def render_group_sections(gname: str, scripts: list):
            # ── Pipelines ──────────────────────────────────────
            pipe_content = self._make_section_header(
                self.cards_frame, gname, "pipelines", "Pipelines"
            )
            pipelines = self.db.list_pipelines(gname)
            if pipelines:
                for p_id, p_name in pipelines:
                    pc = PipelineCard(
                        pipe_content, p_id, p_name, self.db,
                        group_name=gname,
                        on_run=self._run_pipeline,
                        on_edit=self._edit_pipeline,
                        on_refresh=self._refresh_cards,
                        on_stop=self._stop_running,
                        is_running=(p_id == self._running_pipeline_id),
                    )
                    pc.pack(fill="x", pady=5, ipady=2)
                    self._bind_pipeline_drag(pc)
                    self._pipeline_cards.append(pc)
            else:
                tk.Label(pipe_content, text="No pipelines yet.",
                         bg=C["bg"], fg=C["path_fg"],
                         font=("Segoe UI", 9), padx=6).pack(anchor="w", pady=(2, 4))

            # ── Scripts ────────────────────────────────────────
            scr_content = self._make_section_header(
                self.cards_frame, gname, "scripts", "Scripts"
            )
            if scripts:
                gids = [r[0] for r in scripts]
                for gi, rec in enumerate(scripts):
                    sid = rec[0]
                    up_id   = gids[gi - 1] if gi > 0 else None
                    down_id = gids[gi + 1] if gi < len(gids) - 1 else None
                    card = ScriptCard(
                        scr_content, rec, self.db, self._run_script, self._refresh,
                        on_move_up   = make_move(sid, up_id)   if up_id   else lambda: None,
                        on_move_down = make_move(sid, down_id) if down_id else lambda: None,
                        on_move_top  = make_top(sid)           if up_id   else lambda: None,
                        on_stop      = self._stop_running,
                        is_running   = (sid == self._running_script_id),
                    )
                    card.pack(fill="x", pady=5, ipady=2)
                    self._bind_card_drag(card)
                    self._cards.append(card)
            else:
                tk.Label(scr_content, text="No scripts yet.",
                         bg=C["bg"], fg=C["path_fg"],
                         font=("Segoe UI", 9), padx=6).pack(anchor="w", pady=(2, 4))

        if self._active_group is None:
            # All mode — group headers with two sections each
            all_scripts = self.db.list_all()
            groups = self.db.list_groups()
            if not groups and not all_scripts:
                tk.Label(self.cards_frame,
                         text="No scripts yet.\nClick '+ Script' to get started.",
                         bg=C["bg"], fg=C["path_fg"],
                         font=("Segoe UI", 10), justify="center").pack(pady=60)
                return
            group_scripts: dict[str, list] = {g: [] for g in groups}
            group_scripts.setdefault("", [])
            for rec in all_scripts:
                g = rec[8] or ""
                group_scripts.setdefault(g, [])
                group_scripts[g].append(rec)
            any_named = bool(groups)
            for gname in groups:
                self._make_group_header(gname)
                render_group_sections(gname, group_scripts.get(gname, []))
            ungrouped = group_scripts.get("", [])
            if ungrouped:
                if any_named:
                    self._make_group_header("Other")
                render_group_sections("", ungrouped)
        else:
            # Single-group mode
            scripts = [s for s in self.db.list_all()
                       if (s[8] or "") == self._active_group]
            render_group_sections(self._active_group, scripts)

    def _add_script(self):
        groups = self.db.list_groups()
        if not groups:
            name = simpledialog.askstring(
                "Create a Group First",
                "You have no groups yet.\nEnter a group name to continue:",
                parent=self,
            )
            if not (name and name.strip()):
                return
            self.db.create_group(name.strip())
            self._active_group = name.strip()
            self._refresh_tabs()
            groups = self.db.list_groups()
        ScriptDialog(self, self.db, on_save=self._refresh,
                     existing_groups=groups,
                     default_group=self._active_group or "")

    # ---------- card drag-and-drop ----------
    _DRAG_THRESHOLD = 6

    def _bind_card_drag(self, card: "ScriptCard"):
        def recurse(w):
            w.bind("<ButtonPress-1>",   lambda e, c=card: self._card_drag_press(e, c))
            w.bind("<B1-Motion>",       lambda e, c=card: self._card_drag_motion(e, c))
            w.bind("<ButtonRelease-1>", lambda e:         self._card_drag_release(e))
            for ch in w.winfo_children():
                recurse(ch)
        recurse(card._text_area)

    def _bind_pipeline_drag(self, card: "PipelineCard"):
        def recurse(w):
            if w is card._summary_row:
                return
            w.bind("<ButtonPress-1>",   lambda e, c=card: self._card_drag_press(e, c))
            w.bind("<B1-Motion>",       lambda e, c=card: self._card_drag_motion(e, c))
            w.bind("<ButtonRelease-1>", lambda e:         self._card_drag_release(e))
            for ch in w.winfo_children():
                recurse(ch)
        recurse(card._content)

    def _card_drag_press(self, event, card: "ScriptCard"):
        self._drag_card = card
        self._drag_start_x = event.x_root
        self._drag_start_y = event.y_root

    def _card_drag_motion(self, event, card: "ScriptCard"):
        if self._drag_card is None:
            return
        if (abs(event.x_root - self._drag_start_x) < self._DRAG_THRESHOLD and
                abs(event.y_root - self._drag_start_y) < self._DRAG_THRESHOLD):
            return
        if self._drag_ghost is None:
            self._create_drag_ghost(card)
        self._drag_ghost.geometry(f"+{event.x_root + 14}+{event.y_root + 8}")
        self._update_drag_target(event)

    def _create_drag_ghost(self, card: "ScriptCard"):
        self._drag_ghost = tk.Toplevel(self)
        self._drag_ghost.overrideredirect(True)
        self._drag_ghost.attributes("-alpha", 0.85)
        self._drag_ghost.configure(bg=C["accent"])
        tk.Label(self._drag_ghost, text=f"  {card._name}  ",
                 bg=C["accent"], fg="#ffffff",
                 font=("Segoe UI", 10, "bold"), padx=6, pady=4).pack()

    def _update_drag_target(self, event):
        over_tab = self._find_tab_at(event.x_root, event.y_root)

        # Restore previous tab highlight when cursor moves away from it
        if self._drag_tab_highlight:
            prev_btn, prev_bg = self._drag_tab_highlight
            if over_tab is None or over_tab[1] is not prev_btn:
                try:
                    prev_btn.config(bg=prev_bg)
                except tk.TclError:
                    pass
                self._drag_tab_highlight = None

        if over_tab is not None:
            btn = over_tab[1]
            if self._drag_tab_highlight is None:
                self._drag_tab_highlight = (btn, btn.cget("bg"))
                btn.config(bg="#6b7bbd")
            self._drag_target_group = over_tab[0]
            self._drag_insert_before = None
            if self._drag_indicator:
                self._drag_indicator.place_forget()
        else:
            self._drag_target_group = None
            self._update_insertion_indicator(event)

    def _find_tab_at(self, x_root, y_root):
        for entry in self._group_tab_btns:
            _, btn, *_ = entry
            try:
                if (btn.winfo_rootx() <= x_root <= btn.winfo_rootx() + btn.winfo_width() and
                        btn.winfo_rooty() <= y_root <= btn.winfo_rooty() + btn.winfo_height()):
                    return entry
            except tk.TclError:
                pass
        return None

    def _update_insertion_indicator(self, event):
        is_pipeline_drag = isinstance(self._drag_card, PipelineCard)
        active_list = self._pipeline_cards if is_pipeline_drag else self._cards
        if self._active_group is None or not active_list:
            if self._drag_indicator:
                self._drag_indicator.place_forget()
            return

        insert_y_screen = None
        before_id = None
        visible = [c for c in active_list if c is not self._drag_card]

        id_attr = "pipeline_id" if is_pipeline_drag else "script_id"
        for card in visible:
            try:
                mid = card.winfo_rooty() + card.winfo_height() // 2
            except tk.TclError:
                continue
            if event.y_root <= mid:
                before_id = getattr(card, id_attr)
                insert_y_screen = card.winfo_rooty()
                break

        if insert_y_screen is None and visible:
            last = visible[-1]
            try:
                insert_y_screen = last.winfo_rooty() + last.winfo_height()
            except tk.TclError:
                pass

        self._drag_insert_before = before_id

        if insert_y_screen is not None:
            if self._drag_indicator is None:
                self._drag_indicator = tk.Frame(self, bg=C["accent"], height=3)
            rel_y = insert_y_screen - self.winfo_rooty()
            cx    = self._canvas.winfo_rootx() - self.winfo_rootx()
            self._drag_indicator.place(x=cx, y=rel_y,
                                       width=self._canvas.winfo_width(), height=3)
            self._drag_indicator.lift()
        else:
            if self._drag_indicator:
                self._drag_indicator.place_forget()

    def _card_drag_release(self, _event):
        card = self._drag_card
        if card is None:
            return
        if self._drag_ghost is not None:
            is_pipeline = isinstance(card, PipelineCard)
            if self._drag_target_group is not None:
                if self._drag_target_group != card._group_name:
                    if is_pipeline:
                        self.db.move_pipeline_to_group(card.pipeline_id, self._drag_target_group)
                    else:
                        self.db.move_to_group(card.script_id, self._drag_target_group)
                    self._refresh()
            elif self._active_group is not None:
                if is_pipeline:
                    self.db.reorder_pipeline(card.pipeline_id, self._active_group,
                                             self._drag_insert_before)
                else:
                    self.db.reorder_script(card.script_id, self._active_group,
                                           self._drag_insert_before)
                self._refresh_cards()
        self._clear_drag_state()

    def _clear_drag_state(self):
        if self._drag_ghost:
            try:
                self._drag_ghost.destroy()
            except tk.TclError:
                pass
            self._drag_ghost = None
        if self._drag_indicator:
            try:
                self._drag_indicator.place_forget()
                self._drag_indicator.destroy()
            except tk.TclError:
                pass
            self._drag_indicator = None
        if self._drag_tab_highlight:
            btn, orig_bg = self._drag_tab_highlight
            try:
                btn.config(bg=orig_bg)
            except tk.TclError:
                pass
            self._drag_tab_highlight = None
        self._drag_card = None
        self._drag_insert_before = None
        self._drag_target_group = None

    def _show_options_menu(self):
        btn = self._options_btn
        self._options_menu.tk_popup(
            btn.winfo_rootx(),
            btn.winfo_rooty() + btn.winfo_height(),
        )

    def _add_pipeline(self):
        if not self._active_group:
            messagebox.showinfo("Select a Group",
                                "Please select a group first to create a pipeline.",
                                parent=self)
            return
        name = simpledialog.askstring("New Pipeline", "Pipeline name:", parent=self)
        if not (name and name.strip()):
            return
        pid = self.db.create_pipeline(name.strip(), self._active_group)
        self._refresh_cards()
        self._edit_pipeline(pid, name.strip())

    def _edit_pipeline(self, pipeline_id: int, name: str):
        PipelineEditorDialog(self, self.db, pipeline_id, name,
                             self._active_group or "", self._refresh_cards)

    def _run_pipeline(self, pipeline_id: int, pipeline_name: str):
        if self.current_process and self.current_process.poll() is None:
            messagebox.showinfo("Already Running",
                                "A script is already running. Stop it first.",
                                parent=self)
            return
        steps = self.db.list_pipeline_steps(pipeline_id)
        if not steps:
            messagebox.showinfo("Empty Pipeline",
                                "This pipeline has no steps.\nClick ⚙ to add scripts.",
                                parent=self)
            return
        self._pipeline_queue = list(steps)
        self._pipeline_step_idx = 0
        self._pipeline_total = len(steps)
        self._running_pipeline_id = pipeline_id
        self._running_pipeline_name = pipeline_name
        self._running_script_id = None
        self._run_start_time = datetime.now()
        for _pc in self._pipeline_cards:
            _pc.set_running(_pc.pipeline_id == pipeline_id,
                            self._stop_running if _pc.pipeline_id == pipeline_id else None)
        for _c in self._cards:
            _c.set_running(False)
        self._get_or_create_tab(f"pipeline:{pipeline_id}", f"⚡ {pipeline_name}")
        self._append_output(
            f"\n{'━' * 60}\n"
            f"⚡  {pipeline_name}  ·  {self._pipeline_total} step"
            f"{'s' if self._pipeline_total != 1 else ''}\n"
            f"{'━' * 60}\n\n",
            tag="info",
        )
        self._run_next_pipeline_step()

    def _run_next_pipeline_step(self):
        if not self._pipeline_queue:
            return
        step_id, sid, name, path, params, interp, params_override = self._pipeline_queue.pop(0)
        if params_override is not None:
            params = params_override
        self._pipeline_step_idx += 1
        n, total = self._pipeline_step_idx, self._pipeline_total
        self._append_output(
            f"{'─' * 40}\nStep {n}/{total}:  {name}\n{'─' * 40}\n",
            tag="info",
        )
        self.status_var.set(f"Pipeline step {n}/{total}: {name}")
        if not Path(path).exists():
            self.output_queue.put(("stderr", f"[ERROR] File not found: {path}\n"))
            self.output_queue.put(("done", sid, "error", ""))
            return
        final_interp = interp if interp.strip() else detect_interpreter(path)
        try:
            cmd = build_command(path, params, final_interp)
        except ValueError as e:
            self.output_queue.put(("stderr", f"[ERROR] Parameter error: {e}\n"))
            self.output_queue.put(("done", sid, "error", ""))
            return
        self.db.mark_run(sid)
        self._running_script_id = sid
        for _c in self._cards:
            _c.set_running(_c.script_id == sid,
                           self._stop_running if _c.script_id == sid else None)
        threading.Thread(
            target=self._run_subprocess, args=(cmd, name, sid), daemon=True,
        ).start()

    def _toggle_select_mode(self):
        self._select_mode = not self._select_mode
        if self._select_mode:
            self._options_menu.entryconfig(0, label="✕  Cancel select")
            self._select_bar_var.set("Tick the checkboxes next to scripts you want to delete.")
            self._select_bar.pack(fill="x", before=self._paned)
            for card in self._cards:
                card.show_checkbox(self._update_select_count)
        else:
            self._options_menu.entryconfig(0, label="☑  Select scripts")
            self._select_bar.pack_forget()
            for card in self._cards:
                card.hide_checkbox()

    def _update_select_count(self):
        n = sum(1 for c in self._cards if c.selected.get())
        total = len(self._cards)
        if n:
            self._select_bar_var.set(f"{n} of {total} selected")
        else:
            self._select_bar_var.set("Tick the checkboxes next to scripts you want to delete.")
        all_selected = n == total and total > 0
        self._sel_all_btn.config(text="Deselect All" if all_selected else "Select All")

    def _toggle_select_all(self):
        all_selected = all(c.selected.get() for c in self._cards) and self._cards
        for card in self._cards:
            card.selected.set(not all_selected)
        self._update_select_count()

    def _delete_selected(self):
        ids = [c.script_id for c in self._cards if c.selected.get()]
        if not ids:
            messagebox.showinfo("Nothing Selected", "Tick the checkboxes next to the scripts you want to delete.")
            return
        if messagebox.askyesno("Delete Selected", f"Delete {len(ids)} selected script(s)?"):
            self.db.delete_many(ids)
            self._refresh()

    def _delete_all(self):
        if not self._cards:
            return
        if messagebox.askyesno("Delete All", f"Delete all {len(self._cards)} scripts? This cannot be undone."):
            self.db.delete_all()
            self._refresh()

    def _export_config(self, group_name: str | None = None):
        if group_name:
            initial = f"ryos_{group_name}.json"
            title   = f"Export Group: {group_name}"
        else:
            initial = "ryos_all.json"
            title   = "Export All Groups"
        path = filedialog.asksaveasfilename(
            title=title,
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All Files", "*.*")],
            initialfile=initial,
        )
        if not path:
            return
        try:
            n_scripts, n_pipelines = self.db.export_to_file(path, group_name=group_name)
            self.status_var.set(
                f"Exported {n_scripts} script(s), {n_pipelines} pipeline(s) → {Path(path).name}"
            )
        except Exception as e:
            messagebox.showerror("Export Failed", str(e))

    def _import_config(self):
        path = filedialog.askopenfilename(
            title="Import Config",
            filetypes=[("JSON", "*.json"), ("All Files", "*.*")],
        )
        if not path:
            return
        try:
            replace = messagebox.askyesno(
                "Import Mode",
                "How should existing data in the imported groups be handled?\n\n"
                "Yes = Replace (overwrite scripts/pipelines in the imported groups)\n"
                "No  = Merge (skip duplicates by path / name)",
            )
            added, skipped = self.db.import_from_file(path, replace=replace)
            self._refresh()
            self.status_var.set(f"Import done — {added} script(s) added, {skipped} skipped.")
        except Exception as e:
            messagebox.showerror("Import Failed", str(e))

    # ---------- execution ----------
    def _run_script(self, script_id, name, path, params, interpreter):
        if self.current_process and self.current_process.poll() is None:
            messagebox.showinfo("Already Running",
                                "A script is already running. Wait for it to finish or close its output window.")
            return

        if not Path(path).exists():
            messagebox.showerror("File Not Found", f"File does not exist:\n{path}")
            return

        final_interp = interpreter if interpreter.strip() else detect_interpreter(path)
        try:
            cmd = build_command(path, params, final_interp)
        except ValueError as e:
            messagebox.showerror("Parameter Error", f"Could not parse parameters:\n{e}")
            return

        self._get_or_create_tab(f"script:{script_id}", name)
        self._append_output(
            f"\n{'━'*60}\n"
            f"  ▶  {name}\n"
            f"  {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}    {' '.join(cmd)}\n"
            f"{'━'*60}\n\n",
            tag="info",
        )
        self.status_var.set(f"Running: {name}")
        self.db.mark_run(script_id)
        self._running_script_id = script_id
        self._running_script_name = name
        self._running_pipeline_id = None
        self._run_start_time = datetime.now()
        for _c in self._cards:
            _c.set_running(_c.script_id == script_id,
                           self._stop_running if _c.script_id == script_id else None)
        for _pc in self._pipeline_cards:
            _pc.set_running(False)

        thread = threading.Thread(
            target=self._run_subprocess, args=(cmd, name, script_id), daemon=True
        )
        thread.start()

    def _run_subprocess(self, cmd, name, script_id):
        try:
            self.current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                text=True,
                cwd=str(Path(next((c for c in cmd if Path(c).is_file()), cmd[0])).parent),
            )
        except FileNotFoundError as e:
            self.output_queue.put(("stderr", f"[ERROR] {e}\n"))
            self.output_queue.put(("done", script_id, "error", f"❌ Interpreter/file not found: {name}\n"))
            return
        except Exception as e:
            self.output_queue.put(("stderr", f"[ERROR] {e}\n"))
            self.output_queue.put(("done", script_id, "error", f"❌ Error: {name}\n"))
            return

        assert self.current_process.stdout is not None
        for line in self.current_process.stdout:
            self.output_queue.put(("stdout", line))

        self.current_process.wait()
        rc = self.current_process.returncode
        tag = "ok" if rc == 0 else "stderr"
        status = "ok" if rc == 0 else "error"
        self.output_queue.put((
            "done_tag", script_id, status, tag,
            f"\n  exit code {rc}  ·  {datetime.now().strftime('%H:%M:%S')}\n",
        ))

    def _init_all_tab(self):
        text = scrolledtext.ScrolledText(
            self._out_tab_body, wrap="word", height=10, font=("Consolas", 10),
            bg="#1e1e1e", fg="#dcdcdc", insertbackground="#dcdcdc",
        )
        text.tag_config("stderr", foreground="#ff8080")
        text.tag_config("info",   foreground="#7ec0ee")
        text.tag_config("ok",     foreground="#90ee90")
        btn = tk.Frame(self._out_tab_bar, bg="#2d2d2d", cursor="hand2")
        btn.pack(side="left", padx=(1, 0), pady=(2, 0))
        name_lbl = tk.Label(btn, text="All", bg="#2d2d2d", fg="#aaa",
                            font=("Segoe UI", 9, "bold"), cursor="hand2", padx=8, pady=3)
        name_lbl.pack(side="left")
        self._output_tabs["all"] = {"text": text, "btn": btn,
                                    "name_lbl": name_lbl, "close_lbl": None}
        name_lbl.bind("<Button-1>", lambda e: self._activate_tab("all"))
        btn.bind("<Button-1>",      lambda e: self._activate_tab("all"))
        self._bind_tab_context_menu(btn, name_lbl, None, "all")
        self._active_tab_key = "all"
        text.pack(fill="both", expand=True)

    def _get_or_create_tab(self, key: str, name: str):
        all_btn = self._output_tabs["all"]["btn"]
        if key in self._output_tabs:
            tab = self._output_tabs[key]
            tab["text"].configure(state="normal")
            tab["text"].delete("1.0", tk.END)
            tab["name_lbl"].config(text=name)
            self._activate_tab(key)
        else:
            text = scrolledtext.ScrolledText(
                self._out_tab_body, wrap="word", height=10, font=("Consolas", 10),
                bg="#1e1e1e", fg="#dcdcdc", insertbackground="#dcdcdc",
            )
            text.tag_config("stderr", foreground="#ff8080")
            text.tag_config("info",   foreground="#7ec0ee")
            text.tag_config("ok",     foreground="#90ee90")

            btn = tk.Frame(self._out_tab_bar, bg="#2d2d2d", cursor="hand2")
            btn.pack(side="left", padx=(1, 0), pady=(2, 0), before=all_btn)
            name_lbl = tk.Label(btn, text=name, bg="#2d2d2d", fg="#aaa",
                                font=("Segoe UI", 9), cursor="hand2", padx=8, pady=3)
            name_lbl.pack(side="left")
            close_lbl = tk.Label(btn, text="×", bg="#2d2d2d", fg="#555",
                                 font=("Segoe UI", 9), cursor="hand2", padx=4, pady=3)
            close_lbl.pack(side="left")

            self._output_tabs[key] = {"text": text, "btn": btn,
                                      "name_lbl": name_lbl, "close_lbl": close_lbl}
            name_lbl.bind("<Button-1>", lambda e, k=key: self._activate_tab(k))
            btn.bind("<Button-1>",      lambda e, k=key: self._activate_tab(k))
            close_lbl.bind("<Button-1>", lambda e, k=key: self._close_tab(k))
            self._bind_tab_context_menu(btn, name_lbl, close_lbl, key)
            self._activate_tab(key)

        if not self._out_expanded:
            self._toggle_output()

    def _bind_tab_context_menu(self, btn, name_lbl, close_lbl, key: str):
        def show(e):
            self._show_tab_context_menu(e, key)
        for w in [btn, name_lbl] + ([close_lbl] if close_lbl else []):
            w.bind("<Button-3>", show)

    def _show_tab_context_menu(self, event, key: str):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="⎘  Copy", command=lambda: self._copy_log(key))
        menu.add_command(label="💾  Save", command=lambda: self._save_log(key))
        if key != "all":
            menu.add_separator()
            menu.add_command(label="✕  Close", command=lambda: self._close_tab(key))
        menu.tk_popup(event.x_root, event.y_root)

    def _activate_tab(self, key: str):
        if self._active_tab_key and self._active_tab_key in self._output_tabs:
            old = self._output_tabs[self._active_tab_key]
            for w in [old["btn"], old["name_lbl"]] + ([old["close_lbl"]] if old["close_lbl"] else []):
                w.config(bg="#2d2d2d")
            old["name_lbl"].config(fg="#aaa")
            if old["close_lbl"]:
                old["close_lbl"].config(fg="#555")
            old["text"].pack_forget()
        self._active_tab_key = key
        tab = self._output_tabs[key]
        for w in [tab["btn"], tab["name_lbl"]] + ([tab["close_lbl"]] if tab["close_lbl"] else []):
            w.config(bg="#1e1e1e")
        tab["name_lbl"].config(fg="#ffffff")
        if tab["close_lbl"]:
            tab["close_lbl"].config(fg="#888")
        tab["text"].pack(fill="both", expand=True)

    def _close_tab(self, key: str):
        if key == "all" or key not in self._output_tabs:
            return
        tab = self._output_tabs.pop(key)
        tab["text"].pack_forget()
        tab["text"].destroy()
        tab["btn"].destroy()
        if key == self._active_tab_key:
            self._active_tab_key = None
            self._activate_tab("all")

    def _toggle_output(self):
        if self._out_expanded:
            self._saved_sash_pos = self._paned.sashpos(0)
            self._out_tab_bar.pack_forget()
            self._out_tab_body.pack_forget()
            self._toggle_btn.config(text="▲  Show Output")
            self._out_expanded = False
            self.update_idletasks()
            h = self._paned.winfo_height()
            self._paned.sashpos(0, h - self.out_panel.winfo_reqheight())
        else:
            self._out_tab_bar.pack(fill="x")
            self._out_tab_body.pack(fill="both", expand=True)
            self._toggle_btn.config(text="▼  Hide Output")
            self._out_expanded = True
            self.update_idletasks()
            h = self._paned.winfo_height()
            sash = getattr(self, "_saved_sash_pos", max(50, h - 200))
            self._paned.sashpos(0, min(sash, h - 50))

    def _append_output(self, text: str, tag: str | None = None):
        if not self._active_tab_key or self._active_tab_key not in self._output_tabs:
            return
        keys = [self._active_tab_key]
        if self._active_tab_key != "all" and "all" in self._output_tabs:
            keys.append("all")
        max_lines = self._settings.get("max_output_lines", 2000)
        scroll = self._settings.get("auto_scroll_output", True)
        for k in keys:
            out_text = self._output_tabs[k]["text"]
            out_text.configure(state="normal")
            if tag:
                out_text.insert(tk.END, text, tag)
            else:
                out_text.insert(tk.END, text)
            line_count = int(out_text.index(tk.END).split(".")[0]) - 1
            if line_count > max_lines:
                out_text.delete("1.0", f"{line_count - max_lines + 1}.0")
            if scroll:
                out_text.see(tk.END)

    def _clear_log(self):
        if not self._active_tab_key or self._active_tab_key not in self._output_tabs:
            return
        out_text = self._output_tabs[self._active_tab_key]["text"]
        out_text.configure(state="normal")
        out_text.delete("1.0", tk.END)

    def _save_log(self, key: str | None = None):
        k = key or self._active_tab_key
        if not k or k not in self._output_tabs:
            self.status_var.set("Nothing to save.")
            return
        text = self._output_tabs[k]["text"].get("1.0", tk.END).strip()
        if not text:
            self.status_var.set("Nothing to save.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Save output",
        )
        if path:
            Path(path).write_text(text, encoding="utf-8")
            self.status_var.set(f"Saved to {path}")

    def _copy_log(self, key: str | None = None):
        k = key or self._active_tab_key
        if not k or k not in self._output_tabs:
            return
        text = self._output_tabs[k]["text"].get("1.0", tk.END).strip()
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.status_var.set("Log copied to clipboard.")

    def _stop_running(self):
        self._pipeline_queue.clear()
        self._pipeline_total = 0
        self._running_pipeline_id = None
        self._running_script_id = None
        if self.current_process and self.current_process.poll() is None:
            self.current_process.terminate()
            self._append_output("\n[STOPPED by user]\n", tag="stderr")
            self.status_var.set("Stopped.")
        else:
            self.status_var.set("No script is currently running.")
        self._clear_running_state()

    def _drain_output_queue(self):
        try:
            while True:
                item = self.output_queue.get_nowait()
                if item[0] == "done":
                    _, sid, status, text = item
                    self._append_output(text, tag="info")
                    self.db.mark_run_status(sid, status)
                    self._handle_step_done(status)
                elif item[0] == "done_tag":
                    _, sid, status, tag, text = item
                    self._append_output(text, tag=tag)
                    self.db.mark_run_status(sid, status)
                    self._handle_step_done(status)
                elif item[0] == "stderr":
                    self._append_output(item[1], tag="stderr")
                else:
                    self._append_output(item[1])
        except queue.Empty:
            pass
        self.after(80, self._drain_output_queue)

    def _clear_running_state(self):
        for _c in self._cards:
            _c.set_running(False)
        for _pc in self._pipeline_cards:
            _pc.set_running(False)

    def _handle_step_done(self, status: str):
        notify = self._settings.get("notify_on_complete", True)
        elapsed = ""
        if self._run_start_time:
            secs = (datetime.now() - self._run_start_time).total_seconds()
            elapsed = f"{int(secs // 60)} m {secs % 60:.0f} s" if secs >= 60 else f"{secs:.1f} s"

        if self._pipeline_total > 0:
            if status == "ok" and self._pipeline_queue:
                self._run_next_pipeline_step()
            elif status == "ok":
                self._append_output(
                    f"\n{'━' * 60}\n"
                    f"✓  Pipeline complete  ·  {datetime.now().strftime('%H:%M:%S')}\n"
                    f"{'━' * 60}\n",
                    tag="ok",
                )
                self.status_var.set("Pipeline complete.")
                name = getattr(self, "_running_pipeline_name", "Pipeline")
                total = self._pipeline_total
                self._pipeline_total = 0
                self._running_pipeline_id = None
                self._running_script_id = None
                self._clear_running_state()
                if notify:
                    _show_notification(
                        "RYOS — Pipeline passed",
                        f"✓  {name}  ·  {total} step{'s' if total != 1 else ''}  ·  {elapsed}",
                    )
            else:
                self._pipeline_queue.clear()
                self._append_output("\n[Pipeline stopped — step failed]\n", tag="stderr")
                self.status_var.set("Pipeline stopped (step failed).")
                name = getattr(self, "_running_pipeline_name", "Pipeline")
                failed_at = getattr(self, "_pipeline_step_idx", 1)
                total = self._pipeline_total
                self._pipeline_total = 0
                self._running_pipeline_id = None
                self._running_script_id = None
                self._clear_running_state()
                if notify:
                    _show_notification(
                        "RYOS — Pipeline failed",
                        f"✗  {name}  ·  failed at step {failed_at}/{total}  ·  {elapsed}",
                    )
        else:
            name = getattr(self, "_running_script_name", "Script")
            self._running_script_id = None
            if status == "ok":
                self.status_var.set("Done.")
                if notify:
                    _show_notification(
                        "RYOS — Script passed",
                        f"✓  {name}  ·  {elapsed}",
                    )
            else:
                self.status_var.set("Failed.")
                if notify:
                    _show_notification(
                        "RYOS — Script failed",
                        f"✗  {name}  ·  {elapsed}",
                    )
            self._clear_running_state()

    def _check_for_update(self):
        result = _fetch_latest_release()
        if result is None:
            return
        tag, url = result
        if _parse_version(tag) > _parse_version(__version__):
            self.after(0, lambda: self._show_update_banner(tag, url))

    def _show_update_banner(self, tag: str, url: str):
        if getattr(self, "_update_banner", None):
            return
        banner = tk.Frame(self, bg="#1a3a5c", pady=6, padx=12)
        banner.pack(fill="x", before=self._paned)
        self._update_banner = banner

        tk.Label(banner, text=f"🔔  Update available: {tag}  (you have v{__version__})",
                 bg="#1a3a5c", fg="#90cdf4",
                 font=("Segoe UI", 9)).pack(side="left")
        tk.Button(banner, text="Download", bg="#2b6cb0", fg="#ffffff",
                  activebackground="#2c5282", activeforeground="#ffffff",
                  relief="flat", bd=0, font=("Segoe UI", 9, "bold"),
                  padx=8, pady=1, cursor="hand2",
                  command=lambda: webbrowser.open(url)).pack(side="left", padx=(10, 0))
        tk.Button(banner, text="✕", bg="#1a3a5c", fg="#90cdf4",
                  activebackground="#2a4a6c", activeforeground="#ffffff",
                  relief="flat", bd=0, font=("Segoe UI", 9),
                  cursor="hand2",
                  command=banner.destroy).pack(side="right")

    def _manual_update_check(self):
        def _check():
            result = _fetch_latest_release()
            if result is None:
                self.after(0, lambda: messagebox.showinfo(
                    "Update Check",
                    "Could not reach GitHub. Check your internet connection.",
                    parent=self))
                return
            tag, url = result
            if _parse_version(tag) > _parse_version(__version__):
                self.after(0, lambda: self._show_update_banner(tag, url))
            else:
                self.after(0, lambda: messagebox.showinfo(
                    "Up to date",
                    f"You are running the latest version ({__version__}).",
                    parent=self))
        threading.Thread(target=_check, daemon=True).start()

    def _open_advanced_options(self):
        def _apply(new_settings: dict):
            self._settings = new_settings
            _save_settings(self._settings)
            self.attributes("-topmost", self._settings["always_on_top"])
            self.geometry(f"{self._settings['window_width']}x{self._settings['window_height']}")
            corner = self._settings.get("snap_corner") or ""
            if corner and corner != "none":
                _apply_snap_corner(self, corner)
        AdvancedOptionsDialog(self, self._settings, _apply)

    def _on_close(self):
        if self.current_process and self.current_process.poll() is None:
            if not messagebox.askyesno("Still Running", "A script is still running. Exit anyway?"):
                return
            try:
                self.current_process.terminate()
            except Exception:
                pass
        if self._settings["remember_window_geometry"]:
            self._settings["window_geometry"] = self.geometry()
        if self._settings["remember_last_group"]:
            self._settings["last_group"] = self._active_group
        _save_settings(self._settings)
        self.destroy()


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app = RYOSApp()
    app.mainloop()
