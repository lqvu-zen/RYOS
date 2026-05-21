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
        """Returns list of (step_id, script_id, name, path, params, interpreter)."""
        with self._connect() as conn:
            return conn.execute(
                "SELECT ps.id, s.id, s.name, s.path, s.params, s.interpreter "
                "FROM pipeline_steps ps JOIN scripts s ON s.id = ps.script_id "
                "WHERE ps.pipeline_id=? ORDER BY ps.step_order ASC, ps.id ASC",
                (pipeline_id,),
            ).fetchall()

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

        self._build()

        if script_id:
            rec = db.get(script_id)
            if rec:
                _, name, path, params, interp, grp = rec
                self.e_name.insert(0, name)
                self.e_path.insert(0, path)
                self.e_params.insert(0, params)
                self.e_interp.insert(0, interp)
                self.e_group.set(grp or "")
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
        self.e_params.grid(row=2, column=1, columnspan=2, sticky="ew", **pad)

        ttk.Label(frame, text="Interpreter:").grid(row=3, column=0, sticky="w", **pad)
        self.e_interp = ttk.Entry(frame, width=40)
        self.e_interp.grid(row=3, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Label(frame, text="Leave blank for auto-detection", foreground="#888").grid(
            row=4, column=1, columnspan=2, sticky="w", padx=8
        )

        ttk.Label(frame, text="Group:").grid(row=5, column=0, sticky="w", **pad)
        self.e_group = ttk.Combobox(frame, values=self.existing_groups, width=38)
        self.e_group.grid(row=5, column=1, columnspan=2, sticky="ew", **pad)

        sep = ttk.Separator(frame, orient="horizontal")
        sep.grid(row=6, column=0, columnspan=3, sticky="ew", pady=8)

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=7, column=0, columnspan=3, sticky="ew")
        ttk.Button(btn_row, text="Save", command=self._save).pack(side="right", padx=4)
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side="right", padx=4)

        if self.script_id:
            ttk.Button(btn_row, text="Delete", command=self._delete).pack(side="left", padx=4)

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

        if not name or not path:
            messagebox.showwarning("Missing Info", "Name and path are required.", parent=self)
            return
        if not Path(path).exists():
            if not messagebox.askyesno("Warning", f"File not found:\n{path}\n\nSave anyway?", parent=self):
                return

        if self.script_id:
            self.db.update(self.script_id, name, path, params, interp, group_name)
        else:
            self.script_id = self.db.add(name, path, params, interp, group_name)

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

        self._reload_steps()

    def _reload_steps(self):
        self._steps = list(self.db.list_pipeline_steps(self.pipeline_id))
        self._listbox.delete(0, tk.END)
        for i, (step_id, sid, name, path, params, interp) in enumerate(self._steps):
            self._listbox.insert(tk.END, f"  {i + 1}.  {name}")

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
                 group_name: str, on_run, on_edit, on_refresh, *, is_running: bool = False):
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
        btn_area = tk.Frame(self, bg=C["card_bg"], padx=10, pady=10)
        btn_area.pack(side="right", fill="y")
        _flat_button(btn_area, "⚙", C["btn_mod_bg"], C["btn_mod_hover"],
                     lambda: on_edit(pipeline_id, name)).pack(side="left", padx=3)
        _flat_button(btn_area, "▶", self._PIPE_ACCENT, self._PIPE_ACCENT2,
                     lambda: on_run(pipeline_id, name)).pack(side="left", padx=3)

        # Content
        content = tk.Frame(self, bg=C["card_bg"], padx=12, pady=10)
        content.pack(side="left", fill="both", expand=True)
        self._content = content

        # Badge row
        badge_row = tk.Frame(content, bg=C["card_bg"])
        badge_row.pack(fill="x")
        tk.Label(badge_row, text="⚡ PIPELINE", bg=self._PIPE_ACCENT, fg="#ffffff",
                 font=("Segoe UI", 7, "bold"), padx=5, pady=1).pack(side="left")
        if is_running:
            tk.Label(badge_row, text="▶ RUNNING", bg="#27ae60", fg="#ffffff",
                     font=("Segoe UI", 7, "bold"), padx=5, pady=1).pack(side="left", padx=(4, 0))

        # Name (scrolling if long)
        ScrollingLabel(content, name, C["name_fg"], C["card_bg"]).pack(fill="x", pady=(2, 0))

        # Steps summary
        n = len(steps)
        if n == 0:
            summary = "No steps — click ⚙ to add scripts"
        else:
            parts = [s[2] for s in steps[:4]]
            summary = "  →  ".join(parts)
            if n > 4:
                summary += f"  →  +{n - 4} more"
        tk.Label(content, text=f"{n} step{'s' if n != 1 else ''}  ·  {summary}",
                 bg=C["card_bg"], fg=C["path_fg"],
                 font=("Segoe UI", 8), anchor="w").pack(fill="x")

        for widget in (self, content):
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)

        self._bind_right_click_all(self)

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
# Script card
# ---------------------------------------------------------------------------
class ScriptCard(tk.Frame):
    """A single styled card: accent strip + name/path + Modify + Run."""

    def __init__(self, parent, record, db: ScriptDB, runner, on_refresh,
                 on_move_up, on_move_down, on_move_top, *, is_running: bool = False):
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
        btn_area = tk.Frame(self, bg=C["card_bg"], padx=10, pady=10)
        btn_area.pack(side="right", fill="y")

        # Text area
        self._text_area = text_area = tk.Frame(self, bg=C["card_bg"], padx=12, pady=10)
        text_area.pack(side="left", fill="both", expand=True)

        tag_text, tag_bg = _script_tag(path)
        badge_row = tk.Frame(text_area, bg=C["card_bg"])
        badge_row.pack(anchor="w", fill="x", pady=(0, 2))
        tk.Label(badge_row, text=tag_text, bg=tag_bg, fg="#ffffff",
                 font=("Segoe UI", 7, "bold"), padx=5, pady=1).pack(side="left")
        if is_running:
            tk.Label(badge_row, text="▶ RUNNING", bg="#27ae60", fg="#ffffff",
                     font=("Segoe UI", 7, "bold"), padx=5, pady=1).pack(side="left", padx=(4, 0))
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

        _flat_button(btn_area, "⚙", C["btn_mod_bg"], C["btn_mod_hover"],
                     self._modify).pack(side="left", padx=3)
        _flat_button(btn_area, "▶", C["btn_run_bg"], C["btn_run_hover"],
                     self._run).pack(side="left", padx=3)

        # Hover highlight on whole card
        for widget in (self, text_area):
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)

        self._bind_right_click(self)

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
            self.runner(self.script_id, name, path, params, interp)


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
        self._chk(f, "Auto-clear output before each run", self._auto_clear)
        self._chk(f, "Auto-scroll to bottom",             self._auto_scroll)

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
        # drag-and-drop card state
        self._drag_card: ScriptCard | None = None
        self._drag_start_x = self._drag_start_y = 0
        self._drag_ghost: tk.Toplevel | None = None
        self._drag_indicator: tk.Frame | None = None
        self._drag_insert_before: int | None = None
        self._drag_target_group: str | None = None
        self._drag_tab_highlight: tuple | None = None
        self._section_collapsed: dict[str, dict[str, bool]] = {}

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
        tk.Label(wm, text="⚡", bg=C["header_bg"], fg="#FFD23F",
                 font=("Segoe UI", 14, "bold")).pack(side="left")
        tk.Label(wm, text=" RYOS", bg=C["header_bg"], fg="#ffffff",
                 font=("Segoe UI", 14, "bold")).pack(side="left")
        add_btn = _flat_button(header, "+ Script", C["accent"], C["accent2"],
                               self._add_script, width=10)
        add_btn.config(bg=C["accent"])
        add_btn.pack(side="right")
        add_group_btn = _flat_button(header, "+ Group", "#2e7d32", "#388e3c",
                                     self._create_group, width=10)
        add_group_btn.pack(side="right", padx=(0, 6))
        self._pipeline_btn = _flat_button(header, "+ Pipeline", "#5c4bbd", "#7060d0",
                                           self._add_pipeline, width=10)
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
        self.out_title = tk.Label(out_header, text="Output", bg="#2d2d2d", fg="#aaa",
                                  font=("Segoe UI", 9, "bold"), anchor="w")
        self.out_title.pack(side="left")
        self._toggle_btn = tk.Button(out_header, text="▲  Show Output", bg="#2d2d2d", fg="#aaa",
                                     activebackground="#3d3d3d", activeforeground="#fff",
                                     relief="flat", bd=0, cursor="hand2", font=("Segoe UI", 9),
                                     command=self._toggle_output)
        self._toggle_btn.pack(side="right")
        tk.Button(out_header, text="⏹ Stop", bg="#2d2d2d", fg="#ff8080",
                  activebackground="#3d3d3d", activeforeground="#ff8080",
                  relief="flat", bd=0, cursor="hand2", font=("Segoe UI", 9),
                  command=self._stop_running).pack(side="right", padx=8)
        tk.Button(out_header, text="💾 Save", bg="#2d2d2d", fg="#aaa",
                  activebackground="#3d3d3d", activeforeground="#fff",
                  relief="flat", bd=0, cursor="hand2", font=("Segoe UI", 9),
                  command=self._save_log).pack(side="right", padx=4)
        tk.Button(out_header, text="⎘ Copy", bg="#2d2d2d", fg="#aaa",
                  activebackground="#3d3d3d", activeforeground="#fff",
                  relief="flat", bd=0, cursor="hand2", font=("Segoe UI", 9),
                  command=self._copy_log).pack(side="right", padx=4)
        tk.Button(out_header, text="🗑 Clear", bg="#2d2d2d", fg="#aaa",
                  activebackground="#3d3d3d", activeforeground="#fff",
                  relief="flat", bd=0, cursor="hand2", font=("Segoe UI", 9),
                  command=self._clear_log).pack(side="right", padx=4)

        self.out_text = scrolledtext.ScrolledText(
            self.out_panel, wrap="word", height=10, font=("Consolas", 10),
            bg="#1e1e1e", fg="#dcdcdc", insertbackground="#dcdcdc",
        )
        # not packed on init — starts collapsed; out_panel itself always in paned
        self.out_text.tag_config("stderr", foreground="#ff8080")
        self.out_text.tag_config("info",   foreground="#7ec0ee")
        self.out_text.tag_config("ok",     foreground="#90ee90")

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
        self._running_script_id = None
        self._refresh_cards()
        self._show_output(f"Pipeline: {pipeline_name}")
        if not self._out_expanded:
            self._toggle_output()
        if self._settings["auto_clear_output"]:
            self._clear_log()
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
        step_id, sid, name, path, params, interp = self._pipeline_queue.pop(0)
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
        self._refresh_cards()
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

        self._show_output(name)
        if self._settings["auto_clear_output"]:
            self._clear_log()
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
        self._running_pipeline_id = None
        self._refresh()

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
                cwd=str(Path(cmd[-1] if len(cmd) == 1 else cmd[1]).parent)
                    if Path(cmd[-1] if len(cmd) == 1 else cmd[1]).exists() else None,
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

    def _show_output(self, name: str):
        self.out_title.config(text=f"Output — {name}")

    def _toggle_output(self):
        if self._out_expanded:
            self._saved_sash_pos = self._paned.sashpos(0)
            self.out_text.pack_forget()
            self._toggle_btn.config(text="▲  Show Output")
            self._out_expanded = False
            self.update_idletasks()
            h = self._paned.winfo_height()
            self._paned.sashpos(0, h - self.out_panel.winfo_reqheight())
        else:
            self.out_text.pack(fill="both", expand=True)
            self._toggle_btn.config(text="▼  Hide Output")
            self._out_expanded = True
            self.update_idletasks()
            h = self._paned.winfo_height()
            sash = getattr(self, "_saved_sash_pos", max(50, h - 200))
            self._paned.sashpos(0, min(sash, h - 50))

    def _append_output(self, text: str, tag: str | None = None):
        self.out_text.configure(state="normal")
        if tag:
            self.out_text.insert(tk.END, text, tag)
        else:
            self.out_text.insert(tk.END, text)
        # Trim oldest lines when buffer exceeds the max
        max_lines = self._settings.get("max_output_lines", 2000)
        line_count = int(self.out_text.index(tk.END).split(".")[0]) - 1
        if line_count > max_lines:
            self.out_text.delete("1.0", f"{line_count - max_lines + 1}.0")
        if self._settings.get("auto_scroll_output", True):
            self.out_text.see(tk.END)

    def _clear_log(self):
        self.out_text.configure(state="normal")
        self.out_text.delete("1.0", tk.END)
        self.out_title.config(text="Output")

    def _save_log(self):
        text = self.out_text.get("1.0", tk.END).strip()
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

    def _copy_log(self):
        text = self.out_text.get("1.0", tk.END).strip()
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
        self._refresh_cards()

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

    def _handle_step_done(self, status: str):
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
                self._pipeline_total = 0
                self._running_pipeline_id = None
                self._running_script_id = None
                self._refresh()
            else:
                self._pipeline_queue.clear()
                self._append_output("\n[Pipeline stopped — step failed]\n", tag="stderr")
                self.status_var.set("Pipeline stopped (step failed).")
                self._pipeline_total = 0
                self._running_pipeline_id = None
                self._running_script_id = None
                self._refresh()
        else:
            self._running_script_id = None
            self.status_var.set("Done.")
            self._refresh()

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
