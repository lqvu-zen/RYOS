# -*- coding: utf-8 -*-
# /// script
# requires-python = ">=3.10"
# dependencies = []
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
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog


# ---------------------------------------------------------------------------
# Database layer
# ---------------------------------------------------------------------------
# When frozen by PyInstaller, store DB next to the .exe; otherwise next to this file.
_BASE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
DB_PATH = _BASE / "scripts.db"


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

    def export_to_file(self, path: str):
        scripts = self.list_all()
        data = {
            "version": 1,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "scripts": [
                {
                    "name": s[1], "path": s[2], "params": s[3],
                    "interpreter": s[4], "order_index": i,
                    "group_name": s[8] or "",
                }
                for i, s in enumerate(scripts)
            ],
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    def import_from_file(self, path: str, replace: bool = False) -> tuple[int, int]:
        """Returns (added, skipped) counts."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        scripts = data.get("scripts", [])
        now = datetime.now().isoformat(timespec="seconds")
        added = skipped = 0
        with self._connect() as conn:
            if replace:
                conn.execute("DELETE FROM scripts")
            existing = {r[0] for r in conn.execute("SELECT path FROM scripts")}
            for s in scripts:
                if not replace and s["path"] in existing:
                    skipped += 1
                    continue
                conn.execute(
                    "INSERT INTO scripts (name, path, params, interpreter, created_at, order_index, group_name) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (s["name"], s["path"], s.get("params", ""),
                     s.get("interpreter", ""), now, s.get("order_index", 0),
                     s.get("group_name", "")),
                )
                added += 1
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
            cur = conn.execute("SELECT name FROM groups ORDER BY name")
            return [r[0] for r in cur.fetchall()]

    def create_group(self, name: str):
        with self._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO groups (name) VALUES (?)", (name,))
            conn.commit()

    def rename_group(self, old: str, new: str):
        with self._connect() as conn:
            conn.execute("UPDATE groups SET name=? WHERE name=?", (new, old))
            conn.execute("UPDATE scripts SET group_name=? WHERE group_name=?", (new, old))
            conn.commit()

    def delete_group(self, name: str):
        with self._connect() as conn:
            conn.execute("DELETE FROM groups WHERE name=?", (name,))
            conn.execute("UPDATE scripts SET group_name='' WHERE group_name=?", (name,))
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
# Script card
# ---------------------------------------------------------------------------
class ScriptCard(tk.Frame):
    """A single styled card: accent strip + name/path + Modify + Run."""

    def __init__(self, parent, record, db: ScriptDB, runner, on_refresh, on_move_up, on_move_down, on_move_top):
        super().__init__(parent, bg=C["card_bg"],
                         highlightbackground=C["border"], highlightthickness=1)
        sid, name, path, params, interp, _created, last_run, last_run_status, _group = record
        self.script_id = sid
        self._name = name
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

        # Up/down reorder buttons (vertically centered)
        self._order_area = order_area = tk.Frame(self, bg=C["card_bg"], padx=4)
        order_area.pack(side="left", fill="y")
        btn_wrapper = tk.Frame(order_area, bg=C["card_bg"])
        btn_wrapper.pack(expand=True)
        for text, cmd in (("⤒", on_move_top), ("▲", on_move_up), ("▼", on_move_down)):
            tk.Button(btn_wrapper, text=text, command=cmd,
                      bg=C["card_bg"], fg=C["path_fg"],
                      activebackground=C["card_hover"], activeforeground=C["accent"],
                      relief="flat", bd=0, cursor="hand2",
                      font=("Segoe UI", 8)).pack()

        # Text area
        text_area = tk.Frame(self, bg=C["card_bg"], padx=12, pady=10)
        text_area.pack(side="left", fill="both", expand=True)

        name_row = tk.Frame(text_area, bg=C["card_bg"])
        name_row.pack(fill="x")
        tk.Label(name_row, text=name, bg=C["card_bg"], fg=C["name_fg"],
                 font=("Segoe UI", 11, "bold"), anchor="w").pack(side="left")
        tag_text, tag_bg = _script_tag(path)
        tk.Label(name_row, text=tag_text, bg=tag_bg, fg="#ffffff",
                 font=("Segoe UI", 7, "bold"), padx=5, pady=2).pack(side="left", padx=(8, 0))
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

        # Buttons
        btn_area = tk.Frame(self, bg=C["card_bg"], padx=10, pady=10)
        btn_area.pack(side="right", fill="y")

        self._actions_btn = _flat_button(btn_area, "⋯", C["btn_mod_bg"], C["btn_mod_hover"],
                                         self._show_actions_menu, width=3)
        self._actions_btn.pack(side="left", padx=4)
        _flat_button(btn_area, "▶  Run", C["btn_run_bg"], C["btn_run_hover"],
                     self._run).pack(side="left", padx=4)

        # Hover highlight on whole card
        for widget in (self, text_area):
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)

    def show_checkbox(self, command=None):
        self._chk.config(command=command)
        self._chk.pack(side="left", padx=(6, 0), before=self._order_area)

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

    def _show_actions_menu(self):
        menu = tk.Menu(self.winfo_toplevel(), tearoff=0,
                       bg="#2d2d2d", fg="#ffffff",
                       activebackground=C["accent"], activeforeground="#ffffff",
                       font=("Segoe UI", 10))
        menu.add_command(label="✏  Modify", command=self._modify)
        menu.add_command(label="⧉  Clone",  command=self._clone)
        menu.add_separator()
        menu.add_command(label="🗑  Delete", command=self._delete_card,
                         foreground="#ff8080", activeforeground="#ff8080")
        menu.tk_popup(
            self._actions_btn.winfo_rootx(),
            self._actions_btn.winfo_rooty() + self._actions_btn.winfo_height(),
        )

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
# Main app
# ---------------------------------------------------------------------------
class RYOSApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RYOS — Run Your Own Scripts")
        self.minsize(480, 320)
        self.configure(bg=C["bg"])
        self.update_idletasks()
        w, h = 540, 640
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

        self.db = ScriptDB()
        self.current_process = None
        self.output_queue: queue.Queue = queue.Queue()
        self._cards: list[ScriptCard] = []
        self._select_mode = False
        self._active_group: str | None = None

        self._build_ui()
        self._refresh()
        self.after(80, self._drain_output_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

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
        add_btn = _flat_button(header, "+ Add Script", C["accent"], C["accent2"],
                               self._add_script, width=12)
        add_btn.config(bg=C["accent"])
        add_btn.pack(side="right")

        # Options dropdown
        self._options_menu = tk.Menu(self, tearoff=0, bg="#2d2d2d", fg="#ffffff",
                                     activebackground=C["accent"], activeforeground="#ffffff",
                                     borderwidth=0, relief="flat")
        self._options_menu.add_command(label="☑  Select scripts",  command=self._toggle_select_mode)
        self._options_menu.add_separator()
        self._options_menu.add_command(label="📤  Export config",   command=self._export_config)
        self._options_menu.add_command(label="📥  Import config",   command=self._import_config)
        self._options_menu.add_separator()
        self._options_menu.add_command(label="🗑  Delete All",      command=self._delete_all)

        options_btn = _flat_button(header, "⋮ Options", "#3a3a3a", "#555",
                                   self._show_options_menu, width=10)
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

    # ---------- tab bar ----------
    def _refresh_tabs(self):
        for w in self._tab_bar.winfo_children():
            w.destroy()
        self._add_tab_btn(None, "All", self._active_group is None)
        for g in self.db.list_groups():
            self._add_tab_btn(g, g, self._active_group == g)
        plus = tk.Button(
            self._tab_bar, text="+ Group",
            bg=C["bg"], fg=C["path_fg"],
            activebackground=C["card_hover"], activeforeground=C["accent"],
            relief="flat", bd=0, padx=10, pady=5,
            font=("Segoe UI", 9), cursor="hand2",
            command=self._create_group,
        )
        plus.bind("<Enter>", lambda e: plus.config(bg=C["card_hover"]))
        plus.bind("<Leave>", lambda e: plus.config(bg=C["bg"]))
        plus.pack(side="left", padx=(8, 2))

    def _add_tab_btn(self, group, label, is_active):
        if is_active:
            bg, fg, fw = C["accent"], "#ffffff", "bold"
            hover_bg = C["accent2"]
        else:
            bg, fg, fw = C["bg"], C["path_fg"], "normal"
            hover_bg = C["card_hover"]
        btn = tk.Button(
            self._tab_bar, text=label,
            bg=bg, fg=fg,
            activebackground=hover_bg, activeforeground=fg,
            relief="flat", bd=0, padx=12, pady=5,
            font=("Segoe UI", 9, fw), cursor="hand2",
            command=lambda g=group: self._switch_group(g),
        )
        btn.bind("<Enter>", lambda e, b=btn, h=hover_bg: b.config(bg=h))
        btn.bind("<Leave>", lambda e, b=btn, ob=bg: b.config(bg=ob))
        if group is not None:
            btn.bind("<Button-3>", lambda e, g=group: self._tab_context_menu(e, g))
        btn.pack(side="left", padx=2)

    def _switch_group(self, group):
        self._active_group = group
        self._refresh()

    def _create_group(self):
        name = simpledialog.askstring("New Group", "Group name:", parent=self)
        if name and name.strip():
            name = name.strip()
            self.db.create_group(name)
            self._active_group = name
            self._refresh()

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
                self._active_group = None
            self._refresh()

    def _tab_context_menu(self, event, group: str):
        menu = tk.Menu(self, tearoff=0, bg="#2d2d2d", fg="#ffffff",
                       activebackground=C["accent"], activeforeground="#ffffff",
                       font=("Segoe UI", 10))
        menu.add_command(label="✏  Rename", command=lambda: self._rename_group(group))
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

        if self._active_group is None:
            scripts = self.db.list_all()
        else:
            scripts = [s for s in self.db.list_all() if (s[8] or "") == self._active_group]

        if not scripts:
            msg = (
                f"No scripts in '{self._active_group}' yet.\nClick '+ Add Script' to add one."
                if self._active_group else
                "No scripts yet.\nClick '+ Add Script' to get started."
            )
            tk.Label(self.cards_frame, text=msg, bg=C["bg"], fg=C["path_fg"],
                     font=("Segoe UI", 10), justify="center").pack(pady=60)
            return

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

        if self._active_group is None:
            # All mode: show group section headers
            groups_order: list[str] = []
            group_scripts: dict[str, list] = {}
            for rec in scripts:
                g = rec[8] or ""
                if g not in group_scripts:
                    groups_order.append(g)
                    group_scripts[g] = []
                group_scripts[g].append(rec)
            any_named = any(g for g in groups_order)
            for gname in groups_order:
                if gname:
                    self._make_group_header(gname)
                elif any_named:
                    self._make_group_header("Other")
                recs = group_scripts[gname]
                gids = [r[0] for r in recs]
                for gi, rec in enumerate(recs):
                    sid = rec[0]
                    up_id   = gids[gi - 1] if gi > 0 else None
                    down_id = gids[gi + 1] if gi < len(gids) - 1 else None
                    card = ScriptCard(
                        self.cards_frame, rec, self.db, self._run_script, self._refresh,
                        on_move_up   = make_move(sid, up_id)   if up_id   else lambda: None,
                        on_move_down = make_move(sid, down_id) if down_id else lambda: None,
                        on_move_top  = make_top(sid)           if up_id   else lambda: None,
                    )
                    card.pack(fill="x", pady=5, ipady=2)
                    self._cards.append(card)
        else:
            # Single-group mode: no section headers
            gids = [r[0] for r in scripts]
            for gi, rec in enumerate(scripts):
                sid = rec[0]
                up_id   = gids[gi - 1] if gi > 0 else None
                down_id = gids[gi + 1] if gi < len(gids) - 1 else None
                card = ScriptCard(
                    self.cards_frame, rec, self.db, self._run_script, self._refresh,
                    on_move_up   = make_move(sid, up_id)   if up_id   else lambda: None,
                    on_move_down = make_move(sid, down_id) if down_id else lambda: None,
                    on_move_top  = make_top(sid)           if up_id   else lambda: None,
                )
                card.pack(fill="x", pady=5, ipady=2)
                self._cards.append(card)

    def _add_script(self):
        ScriptDialog(self, self.db, on_save=self._refresh,
                     existing_groups=self.db.list_groups(),
                     default_group=self._active_group or "")

    def _show_options_menu(self):
        btn = self._options_btn
        self._options_menu.tk_popup(
            btn.winfo_rootx(),
            btn.winfo_rooty() + btn.winfo_height(),
        )

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

    def _export_config(self):
        path = filedialog.asksaveasfilename(
            title="Export Scripts",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All Files", "*.*")],
            initialfile="ryos_scripts.json",
        )
        if not path:
            return
        try:
            self.db.export_to_file(path)
            self.status_var.set(f"Exported {len(self._cards)} script(s) to {Path(path).name}")
        except Exception as e:
            messagebox.showerror("Export Failed", str(e))

    def _import_config(self):
        path = filedialog.askopenfilename(
            title="Import Scripts",
            filetypes=[("JSON", "*.json"), ("All Files", "*.*")],
        )
        if not path:
            return
        try:
            replace = messagebox.askyesno(
                "Import Mode",
                "Replace all existing scripts with the imported ones?\n\n"
                "Yes = Replace all\nNo = Merge (skip duplicates by path)",
            )
            added, skipped = self.db.import_from_file(path, replace=replace)
            self._refresh()
            self.status_var.set(f"Import done — {added} added, {skipped} skipped.")
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
        self._append_output(
            f"\n{'━'*60}\n"
            f"  ▶  {name}\n"
            f"  {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}    {' '.join(cmd)}\n"
            f"{'━'*60}\n\n",
            tag="info",
        )
        self.status_var.set(f"Running: {name}")
        self.db.mark_run(script_id)
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
        if self.current_process and self.current_process.poll() is None:
            self.current_process.terminate()
            self._append_output("\n[STOPPED by user]\n", tag="stderr")
            self.status_var.set("Stopped.")
        else:
            self.status_var.set("No script is currently running.")

    def _drain_output_queue(self):
        try:
            while True:
                item = self.output_queue.get_nowait()
                if item[0] == "done":
                    _, sid, status, text = item
                    self._append_output(text, tag="info")
                    self.db.mark_run_status(sid, status)
                    self.status_var.set("Done.")
                    self._refresh()
                elif item[0] == "done_tag":
                    _, sid, status, tag, text = item
                    self._append_output(text, tag=tag)
                    self.db.mark_run_status(sid, status)
                    self.status_var.set("Done.")
                    self._refresh()
                elif item[0] == "stderr":
                    self._append_output(item[1], tag="stderr")
                else:
                    self._append_output(item[1])
        except queue.Empty:
            pass
        self.after(80, self._drain_output_queue)

    def _on_close(self):
        if self.current_process and self.current_process.poll() is None:
            if not messagebox.askyesno("Still Running", "A script is still running. Exit anyway?"):
                return
            try:
                self.current_process.terminate()
            except Exception:
                pass
        self.destroy()


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app = RYOSApp()
    app.mainloop()
