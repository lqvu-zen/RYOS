"""SQLite wrapper - manages saved scripts, groups, pipelines, and param presets."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .logger import get_logger
from .settings import DB_PATH

_log = get_logger("db")


# --- Schema versioning -------------------------------------------------------
# _ensure_baseline() brings any database up to the v1 schema; numbered
# migrations beyond that run once each, gated by SQLite's PRAGMA user_version.
_BASELINE_VERSION = 1
_MIGRATIONS: dict = {}  # {2: lambda conn: conn.execute("ALTER ..."), ...}
SCHEMA_VERSION = max((_BASELINE_VERSION, *_MIGRATIONS))


def _run_migrations(conn, migrations: dict, target_version: int) -> int:
    """Apply pending migrations in ascending order, advancing user_version.

    Each migrations[v] is a callable(conn) that upgrades the schema to version
    v. Only versions greater than the database's current user_version (up to
    target_version) run, each stamped on success. Returns the new version.
    """
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for v in range(current + 1, target_version + 1):
        migrate = migrations.get(v)
        if migrate is not None:
            migrate(conn)
        conn.execute(f"PRAGMA user_version = {v}")
    return conn.execute("PRAGMA user_version").fetchone()[0]


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
            _log.exception("DB error")
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._connect() as conn:
            self._ensure_baseline(conn)
            # Stamp pre-versioning databases (and brand-new ones) at the
            # baseline schema, then apply any later migrations exactly once.
            if conn.execute("PRAGMA user_version").fetchone()[0] < _BASELINE_VERSION:
                conn.execute(f"PRAGMA user_version = {_BASELINE_VERSION}")
            _run_migrations(conn, _MIGRATIONS, SCHEMA_VERSION)
            conn.commit()

    def _ensure_baseline(self, conn):
        """Bring a database of any prior vintage up to the baseline (v1)
        schema by creating tables and adding missing columns. Idempotent.
        Frozen: future schema changes belong in _MIGRATIONS, not here."""
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
        if "temp_param" not in cols:
            conn.execute("ALTER TABLE scripts ADD COLUMN temp_param INTEGER DEFAULT 0")
        if "is_favorite" not in cols:
            conn.execute("ALTER TABLE scripts ADD COLUMN is_favorite INTEGER DEFAULT 0")
        if "detached" not in cols:
            conn.execute("ALTER TABLE scripts ADD COLUMN detached INTEGER DEFAULT 0")
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
        if "base_dir" not in gcols:
            conn.execute("ALTER TABLE groups ADD COLUMN base_dir TEXT DEFAULT ''")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pipelines (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                group_name TEXT NOT NULL DEFAULT '',
                sort_order INTEGER DEFAULT 0
            )
        """)
        pcols = [r[1] for r in conn.execute("PRAGMA table_info(pipelines)")]
        if "is_favorite" not in pcols:
            conn.execute("ALTER TABLE pipelines ADD COLUMN is_favorite INTEGER DEFAULT 0")
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
    def add(self, name: str, path: str, params: str, interpreter: str, group_name: str = "",
            temp_param: int = 0, detached: int = 0) -> int:
        with self._connect() as conn:
            max_order = conn.execute("SELECT COALESCE(MAX(order_index), 0) FROM scripts").fetchone()[0]
            cur = conn.execute(
                "INSERT INTO scripts (name, path, params, interpreter, created_at, order_index, group_name, temp_param, detached) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (name, path, params, interpreter, datetime.now().isoformat(timespec="seconds"),
                 max_order + 1, group_name, int(temp_param), int(detached)),
            )
            conn.commit()
            return cur.lastrowid

    def update(self, script_id: int, name: str, path: str, params: str, interpreter: str,
               group_name: str = "", temp_param: int | None = None,
               detached: int | None = None):
        """Update a script. temp_param/detached=None leaves that flag untouched."""
        with self._connect() as conn:
            if temp_param is None:
                conn.execute(
                    "UPDATE scripts SET name=?, path=?, params=?, interpreter=?, group_name=? WHERE id=?",
                    (name, path, params, interpreter, group_name, script_id),
                )
            else:
                conn.execute(
                    "UPDATE scripts SET name=?, path=?, params=?, interpreter=?, group_name=?, temp_param=? WHERE id=?",
                    (name, path, params, interpreter, group_name, int(temp_param), script_id),
                )
            if detached is not None:
                conn.execute("UPDATE scripts SET detached=? WHERE id=?",
                             (int(detached), script_id))
            conn.commit()

    def is_detached(self, script_id: int) -> bool:
        """True if the script is a launcher (fire-and-forget; not kept in Running)."""
        with self._connect() as conn:
            row = conn.execute("SELECT COALESCE(detached, 0) FROM scripts WHERE id=?",
                               (script_id,)).fetchone()
            return bool(row[0]) if row else False

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
                    "SELECT id, name, path, params, interpreter, order_index, group_name "
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
                    "SELECT name, sort_order, COALESCE(base_dir, '') FROM groups WHERE name=?",
                    (group_name,),
                ).fetchall()
            else:
                scripts = conn.execute(
                    "SELECT id, name, path, params, interpreter, order_index, group_name "
                    "FROM scripts ORDER BY "
                    "CASE WHEN COALESCE(group_name,'')='' THEN 1 ELSE 0 END, "
                    "group_name ASC, order_index ASC, id ASC"
                ).fetchall()
                pipelines = conn.execute(
                    "SELECT id, name, group_name, sort_order FROM pipelines "
                    "ORDER BY sort_order ASC, id ASC"
                ).fetchall()
                groups = conn.execute(
                    "SELECT name, sort_order, COALESCE(base_dir, '') FROM groups "
                    "ORDER BY sort_order ASC, id ASC"
                ).fetchall()

            script_data = []
            for s in scripts:
                presets = conn.execute(
                    "SELECT label, params FROM script_param_presets "
                    "WHERE script_id=? ORDER BY sort_order ASC, id ASC",
                    (s[0],),
                ).fetchall()
                script_data.append({
                    "name": s[1], "path": s[2], "params": s[3],
                    "interpreter": s[4], "order_index": s[5],
                    "group_name": s[6] or "",
                    "presets": [{"label": lbl, "params": prm} for lbl, prm in presets],
                })

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
            "version": 3,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "groups": [{"name": g[0], "sort_order": g[1], "base_dir": g[2]} for g in groups],
            "scripts": script_data,
            "pipelines": pipeline_data,
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        return len(script_data), len(pipeline_data)

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
                        "INSERT OR IGNORE INTO groups (name, sort_order, base_dir) VALUES (?, ?, ?)",
                        (gname, g.get("sort_order", 0), g.get("base_dir", "")),
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
                new_sid = cur.lastrowid
                path_to_id[spath] = new_sid
                for i, pr in enumerate(s.get("presets", [])):
                    conn.execute(
                        "INSERT INTO script_param_presets (script_id, label, params, sort_order) "
                        "VALUES (?, ?, ?, ?)",
                        (new_sid, pr.get("label", ""), pr.get("params", ""), i),
                    )
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

    def set_favorite_script(self, script_id: int, fav: bool) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE scripts SET is_favorite=? WHERE id=?", (1 if fav else 0, script_id))

    def set_favorite_pipeline(self, pipeline_id: int, fav: bool) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE pipelines SET is_favorite=? WHERE id=?", (1 if fav else 0, pipeline_id))

    def list_all(self):
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT id, name, path, params, interpreter, created_at, last_run_at, last_run_status, group_name, "
                "COALESCE(temp_param, 0), COALESCE(is_favorite, 0) "
                "FROM scripts "
                "ORDER BY CASE WHEN COALESCE(group_name,'')='' THEN 1 ELSE 0 END, "
                "group_name ASC, order_index ASC, id ASC"
            )
            return cur.fetchall()

    def list_groups(self) -> list[str]:
        with self._connect() as conn:
            cur = conn.execute("SELECT name FROM groups ORDER BY sort_order ASC, id ASC")
            return [r[0] for r in cur.fetchall()]

    def list_groups_with_meta(self) -> list[tuple[str, str]]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT name, COALESCE(base_dir, '') FROM groups ORDER BY sort_order ASC, id ASC"
            )
            return [(r[0], r[1]) for r in cur.fetchall()]

    def get_group_base_dir(self, name: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(base_dir, '') FROM groups WHERE name=?", (name,)
            ).fetchone()
            return row[0] if row else ""

    def set_group_base_dir(self, name: str, new_dir: str) -> tuple[int, list[str]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(base_dir, '') FROM groups WHERE name=?", (name,)
            ).fetchone()
            old_dir = row[0] if row else ""

            remapped = 0
            untouched = []

            if old_dir:
                norm_old = os.path.normcase(os.path.normpath(old_dir))
                scripts = conn.execute(
                    "SELECT id, path FROM scripts WHERE COALESCE(group_name,'')=?", (name,)
                ).fetchall()
                norm_new = os.path.normcase(os.path.normpath(new_dir)) if new_dir else ""
                for sid, spath in scripts:
                    norm_path = os.path.normcase(os.path.normpath(spath))
                    if norm_path == norm_old or norm_path.startswith(norm_old + os.sep):
                        if new_dir:
                            if norm_path == norm_new or norm_path.startswith(norm_new + os.sep):
                                continue  # already inside new_dir, no remap needed
                            rel = os.path.relpath(spath, old_dir)
                            new_path = os.path.join(new_dir, rel)
                        else:
                            new_path = spath
                        conn.execute("UPDATE scripts SET path=? WHERE id=?", (new_path, sid))
                        remapped += 1
                    else:
                        untouched.append(spath)

            conn.execute("UPDATE groups SET base_dir=? WHERE name=?", (new_dir, name))
            conn.commit()
            return remapped, untouched

    def create_group(self, name: str, base_dir: str = ""):
        with self._connect() as conn:
            max_order = conn.execute("SELECT COALESCE(MAX(sort_order), -1) FROM groups").fetchone()[0]
            conn.execute("INSERT OR IGNORE INTO groups (name, sort_order, base_dir) VALUES (?, ?, ?)",
                         (name, max_order + 1, base_dir))
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

    def clone_group(self, source: str, new_name: str) -> tuple[int, int]:
        with self._connect() as conn:
            max_order = conn.execute("SELECT COALESCE(MAX(sort_order), -1) FROM groups").fetchone()[0]
            src_base = conn.execute(
                "SELECT COALESCE(base_dir, '') FROM groups WHERE name=?", (source,)
            ).fetchone()
            src_base_dir = src_base[0] if src_base else ""
            conn.execute(
                "INSERT OR IGNORE INTO groups (name, sort_order, base_dir) VALUES (?, ?, ?)",
                (new_name, max_order + 1, src_base_dir),
            )
            now = datetime.now().isoformat(timespec="seconds")
            source_scripts = conn.execute(
                "SELECT id, name, path, params, interpreter, order_index, COALESCE(temp_param, 0) "
                "FROM scripts WHERE group_name=?",
                (source,),
            ).fetchall()
            id_map: dict[int, int] = {}
            for old_id, s_name, path, params, interpreter, order_index, temp_param in source_scripts:
                cur = conn.execute(
                    "INSERT INTO scripts (name, path, params, interpreter, created_at, "
                    "last_run_at, last_run_status, order_index, group_name, temp_param) "
                    "VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?)",
                    (s_name, path, params, interpreter, now, order_index, new_name, temp_param),
                )
                new_id = cur.lastrowid
                id_map[old_id] = new_id
                presets = conn.execute(
                    "SELECT label, params, sort_order FROM script_param_presets "
                    "WHERE script_id=? ORDER BY sort_order ASC, id ASC",
                    (old_id,),
                ).fetchall()
                for label, preset_params, sort_order in presets:
                    conn.execute(
                        "INSERT INTO script_param_presets (script_id, label, params, sort_order) "
                        "VALUES (?, ?, ?, ?)",
                        (new_id, label, preset_params, sort_order),
                    )
            source_pipelines = conn.execute(
                "SELECT id, name, sort_order FROM pipelines WHERE group_name=?",
                (source,),
            ).fetchall()
            for old_pipe_id, p_name, sort_order in source_pipelines:
                cur = conn.execute(
                    "INSERT INTO pipelines (name, group_name, sort_order) VALUES (?, ?, ?)",
                    (p_name, new_name, sort_order),
                )
                new_pipe_id = cur.lastrowid
                steps = conn.execute(
                    "SELECT script_id, step_order, params_override FROM pipeline_steps "
                    "WHERE pipeline_id=? ORDER BY step_order ASC, id ASC",
                    (old_pipe_id,),
                ).fetchall()
                for script_id, step_order, params_override in steps:
                    new_script_id = id_map.get(script_id, script_id)
                    conn.execute(
                        "INSERT INTO pipeline_steps (pipeline_id, script_id, step_order, params_override) "
                        "VALUES (?, ?, ?, ?)",
                        (new_pipe_id, new_script_id, step_order, params_override),
                    )
            conn.commit()
            return len(source_scripts), len(source_pipelines)

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
                "SELECT id, name, COALESCE(is_favorite, 0) FROM pipelines WHERE group_name=? ORDER BY sort_order ASC, id ASC",
                (group_name,),
            ).fetchall()

    def group_match_counts(self, query: str) -> list[tuple[str, int]]:
        """(group_name, count) for each group containing a script or pipeline
        whose name matches `query` (case-insensitive substring); count is the
        total matching scripts + pipelines in that group. Group sort order with
        the ungrouped bucket ('') last. Blank query returns []. The LIKE pattern
        is escaped so '%'/'_' behave as literals, matching the plain-substring
        search used by the UI filter."""
        q = (query or "").strip().lower()
        if not q:
            return []
        esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{esc}%"
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT g, SUM(c) FROM ("
                "  SELECT COALESCE(group_name, '') AS g, COUNT(*) AS c FROM scripts "
                "  WHERE LOWER(name) LIKE ? ESCAPE '\\' GROUP BY g "
                "  UNION ALL "
                "  SELECT COALESCE(group_name, '') AS g, COUNT(*) AS c FROM pipelines "
                "  WHERE LOWER(name) LIKE ? ESCAPE '\\' GROUP BY g"
                ") GROUP BY g",
                (like, like),
            ).fetchall()
        counts = {r[0]: r[1] for r in rows}
        ordered = [(g, counts[g]) for g in self.list_groups() if g in counts]
        if "" in counts:
            ordered.append(("", counts[""]))
        return ordered

    def groups_with_match(self, query: str) -> list[str]:
        """Group names containing a script or pipeline matching `query`, in the
        same order as group_match_counts (ungrouped last). Blank query → []."""
        return [g for g, _ in self.group_match_counts(query)]

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
                "SELECT id, name, path, params, interpreter, group_name, "
                "COALESCE(temp_param, 0) FROM scripts WHERE id=?",
                (script_id,),
            )
            return cur.fetchone()
