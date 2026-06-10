# -*- coding: utf-8 -*-
"""
Unit tests for RYOS non-UI layers: ScriptDB, detect_interpreter, build_command.
Run with:  uv run python -m pytest tests/test_ryos.py -v
       or: uv run python -m unittest discover -s tests -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

# Allow importing script_runner without launching the Tkinter window
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Patch tkinter before importing so tests run headless (CI / no display)
import unittest.mock as mock
sys.modules.setdefault("tkinter", mock.MagicMock())
sys.modules.setdefault("tkinter.ttk", mock.MagicMock())
sys.modules.setdefault("tkinter.filedialog", mock.MagicMock())
sys.modules.setdefault("tkinter.font", mock.MagicMock())
sys.modules.setdefault("tkinter.messagebox", mock.MagicMock())
sys.modules.setdefault("tkinter.scrolledtext", mock.MagicMock())
sys.modules.setdefault("tkinter.simpledialog", mock.MagicMock())

from ryos.db import ScriptDB  # noqa: E402
from ryos.interpreter import detect_interpreter, build_command  # noqa: E402

# sqlite3 context managers commit/rollback but don't close — suppress the noise in Python 3.13+
warnings.filterwarnings("ignore", category=ResourceWarning)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db() -> ScriptDB:
    """Return a fresh in-memory ScriptDB backed by a temp file."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return ScriptDB(Path(tmp.name))


# ---------------------------------------------------------------------------
# detect_interpreter
# ---------------------------------------------------------------------------

class TestDetectInterpreter(unittest.TestCase):

    def test_python(self):
        self.assertEqual(detect_interpreter("hello.py"), sys.executable)

    def test_node(self):
        self.assertEqual(detect_interpreter("app.js"), "node")

    def test_typescript(self):
        self.assertEqual(detect_interpreter("app.ts"), "ts-node")

    def test_bash(self):
        self.assertEqual(detect_interpreter("run.sh"), "bash")

    def test_powershell(self):
        self.assertEqual(detect_interpreter("setup.ps1"), "powershell")

    def test_batch_no_interpreter(self):
        self.assertEqual(detect_interpreter("install.bat"), "")

    def test_cmd_no_interpreter(self):
        self.assertEqual(detect_interpreter("launch.cmd"), "")

    def test_exe_no_interpreter(self):
        self.assertEqual(detect_interpreter("app.exe"), "")

    def test_unknown_extension(self):
        # Unknown extensions default to cmd (see commit 4fdf2e0)
        self.assertEqual(detect_interpreter("file.xyz"), "cmd")

    def test_case_insensitive(self):
        self.assertEqual(detect_interpreter("SCRIPT.PY"), sys.executable)

    def test_no_extension(self):
        # No extension also falls through to the cmd default
        self.assertEqual(detect_interpreter("Makefile"), "cmd")


# ---------------------------------------------------------------------------
# build_command
# ---------------------------------------------------------------------------

class TestBuildCommand(unittest.TestCase):

    def test_no_interpreter_no_params(self):
        self.assertEqual(build_command("script.bat", "", ""), ["script.bat"])

    def test_with_interpreter(self):
        self.assertEqual(
            build_command("script.py", "", sys.executable),
            [sys.executable, "script.py"],
        )

    def test_with_params(self):
        cmd = build_command("script.py", "hello world", sys.executable)
        self.assertEqual(cmd, [sys.executable, "script.py", "hello", "world"])

    def test_quoted_param(self):
        # On Windows shlex uses posix=False, so quotes are kept as-is by the shell.
        # On POSIX, quotes are stripped by shlex.
        cmd = build_command("script.py", '"hello world"', sys.executable)
        if os.name == "nt":
            self.assertEqual(cmd, [sys.executable, "script.py", '"hello world"'])
        else:
            self.assertEqual(cmd, [sys.executable, "script.py", "hello world"])

    def test_multi_word_interpreter(self):
        cmd = build_command("script.py", "", "python -u")
        self.assertEqual(cmd, ["python", "-u", "script.py"])

    def test_blank_interpreter_whitespace(self):
        cmd = build_command("script.bat", "", "   ")
        self.assertEqual(cmd, ["script.bat"])


# ---------------------------------------------------------------------------
# ScriptDB — basic CRUD
# ---------------------------------------------------------------------------

class TestScriptDBCRUD(unittest.TestCase):

    def setUp(self):
        self.db = _make_db()

    def test_add_and_list(self):
        self.db.add("Hello", "/path/hello.py", "", "")
        scripts = self.db.list_all()
        self.assertEqual(len(scripts), 1)
        self.assertEqual(scripts[0][1], "Hello")
        self.assertEqual(scripts[0][2], "/path/hello.py")

    def test_add_returns_id(self):
        sid = self.db.add("A", "/a.py", "", "")
        self.assertIsInstance(sid, int)
        self.assertGreater(sid, 0)

    def test_get(self):
        sid = self.db.add("GetMe", "/get.py", "arg", "python")
        rec = self.db.get(sid)
        self.assertIsNotNone(rec)
        self.assertEqual(rec[1], "GetMe")
        self.assertEqual(rec[3], "arg")
        self.assertEqual(rec[4], "python")

    def test_get_nonexistent(self):
        self.assertIsNone(self.db.get(9999))

    def test_update(self):
        sid = self.db.add("Old", "/old.py", "", "")
        self.db.update(sid, "New", "/new.py", "p", "node")
        rec = self.db.get(sid)
        self.assertEqual(rec[1], "New")
        self.assertEqual(rec[2], "/new.py")
        self.assertEqual(rec[3], "p")
        self.assertEqual(rec[4], "node")

    def test_delete(self):
        sid = self.db.add("ToDelete", "/del.py", "", "")
        self.db.delete(sid)
        self.assertIsNone(self.db.get(sid))
        self.assertEqual(self.db.list_all(), [])

    def test_delete_many(self):
        ids = [self.db.add(f"S{i}", f"/s{i}.py", "", "") for i in range(4)]
        self.db.delete_many(ids[:2])
        remaining = self.db.list_all()
        self.assertEqual(len(remaining), 2)
        remaining_ids = [r[0] for r in remaining]
        self.assertNotIn(ids[0], remaining_ids)
        self.assertNotIn(ids[1], remaining_ids)

    def test_delete_all(self):
        for i in range(3):
            self.db.add(f"S{i}", f"/s{i}.py", "", "")
        self.db.delete_all()
        self.assertEqual(self.db.list_all(), [])

    def test_mark_run_updates_timestamp(self):
        sid = self.db.add("Runner", "/run.py", "", "")
        before = self.db.list_all()[0][6]  # last_run_at
        self.assertIsNone(before)
        self.db.mark_run(sid)
        after = self.db.list_all()[0][6]
        self.assertIsNotNone(after)

    def test_list_empty(self):
        self.assertEqual(self.db.list_all(), [])


# ---------------------------------------------------------------------------
# ScriptDB — ordering
# ---------------------------------------------------------------------------

class TestScriptDBOrdering(unittest.TestCase):

    def setUp(self):
        self.db = _make_db()
        self.ids = [self.db.add(f"S{i}", f"/s{i}.py", "", "") for i in range(4)]

    def _names(self):
        return [r[1] for r in self.db.list_all()]

    def test_initial_order(self):
        self.assertEqual(self._names(), ["S0", "S1", "S2", "S3"])

    def test_swap_order(self):
        self.db.swap_order(self.ids[0], self.ids[1])
        names = self._names()
        self.assertEqual(names[0], "S1")
        self.assertEqual(names[1], "S0")

    def test_move_to_top(self):
        self.db.move_to_top(self.ids[3])
        names = self._names()
        self.assertEqual(names[0], "S3")

    def test_swap_is_reversible(self):
        self.db.swap_order(self.ids[1], self.ids[2])
        self.db.swap_order(self.ids[1], self.ids[2])  # swap back
        self.assertEqual(self._names(), ["S0", "S1", "S2", "S3"])


# ---------------------------------------------------------------------------
# ScriptDB — export / import
# ---------------------------------------------------------------------------

class TestScriptDBExportImport(unittest.TestCase):

    def setUp(self):
        self.db = _make_db()
        self.db.add("Alpha", "/alpha.py", "", "")
        self.db.add("Beta",  "/beta.js",  "x", "node")

    def test_export_creates_valid_json(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        self.db.export_to_file(path)
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 2)
        self.assertIn("exported_at", data)
        self.assertEqual(len(data["scripts"]), 2)
        names = [s["name"] for s in data["scripts"]]
        self.assertIn("Alpha", names)
        self.assertIn("Beta", names)

    def test_export_preserves_fields(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        self.db.export_to_file(path)
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        beta = next(s for s in data["scripts"] if s["name"] == "Beta")
        self.assertEqual(beta["path"], "/beta.js")
        self.assertEqual(beta["params"], "x")
        self.assertEqual(beta["interpreter"], "node")

    def _write_config(self, scripts: list) -> str:
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w",
                                         delete=False, encoding="utf-8") as f:
            json.dump({"version": 1, "scripts": scripts}, f)
            return f.name

    def test_import_merge_skips_duplicates(self):
        path = self._write_config([
            {"name": "Alpha",  "path": "/alpha.py", "params": "", "interpreter": ""},
            {"name": "Gamma",  "path": "/gamma.py", "params": "", "interpreter": ""},
        ])
        added, skipped = self.db.import_from_file(path, replace=False)
        self.assertEqual(added, 1)
        self.assertEqual(skipped, 1)
        names = [r[1] for r in self.db.list_all()]
        self.assertIn("Gamma", names)
        self.assertEqual(names.count("Alpha"), 1)  # no duplicate

    def test_import_replace_clears_existing(self):
        path = self._write_config([
            {"name": "NewOnly", "path": "/new.py", "params": "", "interpreter": ""},
        ])
        added, skipped = self.db.import_from_file(path, replace=True)
        self.assertEqual(added, 1)
        self.assertEqual(skipped, 0)
        scripts = self.db.list_all()
        self.assertEqual(len(scripts), 1)
        self.assertEqual(scripts[0][1], "NewOnly")

    def test_import_empty_scripts(self):
        path = self._write_config([])
        added, skipped = self.db.import_from_file(path, replace=False)
        self.assertEqual(added, 0)
        self.assertEqual(skipped, 0)
        self.assertEqual(len(self.db.list_all()), 2)  # unchanged

    def test_roundtrip(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        self.db.export_to_file(path)

        db2 = _make_db()
        added, skipped = db2.import_from_file(path, replace=False)
        self.assertEqual(added, 2)
        self.assertEqual(skipped, 0)
        names2 = {r[1] for r in db2.list_all()}
        self.assertEqual(names2, {"Alpha", "Beta"})


# ---------------------------------------------------------------------------
# ScriptDB — migration (DB created without order_index)
# ---------------------------------------------------------------------------

class TestScriptDBMigration(unittest.TestCase):

    def test_migrates_old_schema(self):
        import sqlite3
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        # Create old-style table without order_index
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                CREATE TABLE scripts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT NOT NULL,
                    path        TEXT NOT NULL,
                    params      TEXT DEFAULT '',
                    interpreter TEXT DEFAULT '',
                    created_at  TEXT NOT NULL,
                    last_run_at TEXT
                )
            """)
            conn.execute(
                "INSERT INTO scripts (name, path, params, interpreter, created_at) "
                "VALUES ('Old', '/old.py', '', '', '2024-01-01')"
            )
            conn.commit()

        # Opening via ScriptDB should migrate
        db = ScriptDB(db_path)
        scripts = db.list_all()
        self.assertEqual(len(scripts), 1)
        self.assertEqual(scripts[0][1], "Old")
        # Should be able to add and reorder without error
        db.add("New", "/new.py", "", "")
        self.assertEqual(len(db.list_all()), 2)


# ---------------------------------------------------------------------------
# Integration — batch script calls uv run
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ScriptDB — param presets
# ---------------------------------------------------------------------------

class TestParamPresets(unittest.TestCase):

    def setUp(self):
        self.db = _make_db()
        self.sid = self.db.add("MyScript", "/my.bat", "--default", "")

    def test_replace_and_list(self):
        self.db.replace_param_presets(self.sid, [("dev", "--env dev"), ("prod", "--env prod")])
        presets = self.db.list_param_presets(self.sid)
        self.assertEqual(len(presets), 2)
        labels = [p[1] for p in presets]
        self.assertEqual(labels, ["dev", "prod"])

    def test_params_values_stored(self):
        self.db.replace_param_presets(self.sid, [("dev", "--env dev --port 3000")])
        presets = self.db.list_param_presets(self.sid)
        self.assertEqual(presets[0][2], "--env dev --port 3000")

    def test_order_preserved(self):
        self.db.replace_param_presets(self.sid, [("a", "1"), ("b", "2"), ("c", "3")])
        labels = [p[1] for p in self.db.list_param_presets(self.sid)]
        self.assertEqual(labels, ["a", "b", "c"])

    def test_replace_clears_previous(self):
        self.db.replace_param_presets(self.sid, [("old", "--old")])
        self.db.replace_param_presets(self.sid, [("new", "--new")])
        presets = self.db.list_param_presets(self.sid)
        self.assertEqual(len(presets), 1)
        self.assertEqual(presets[0][1], "new")

    def test_replace_with_empty_clears_all(self):
        self.db.replace_param_presets(self.sid, [("x", "1")])
        self.db.replace_param_presets(self.sid, [])
        self.assertEqual(self.db.list_param_presets(self.sid), [])

    def test_presets_isolated_per_script(self):
        sid2 = self.db.add("Other", "/other.bat", "", "")
        self.db.replace_param_presets(self.sid, [("dev", "--env dev")])
        self.assertEqual(self.db.list_param_presets(sid2), [])

    def test_no_presets_by_default(self):
        self.assertEqual(self.db.list_param_presets(self.sid), [])

    # Integration: run echo_args.bat with each preset's params
    BAT = Path(__file__).parent / "echo_args.bat"

    @unittest.skipUnless(os.name == "nt", "batch scripts only run on Windows")
    def test_batch_runs_with_each_preset(self):
        self.db.replace_param_presets(self.sid, [
            ("dev",  "--env dev --port 3000"),
            ("prod", "--env prod"),
        ])
        for _, label, preset_params in self.db.list_param_presets(self.sid):
            with self.subTest(preset=label):
                cmd = build_command(str(self.BAT), preset_params, "")
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=10,
                    cwd=str(self.BAT.parent),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(preset_params, result.stdout)


# ---------------------------------------------------------------------------
# Batch + uv execution
# ---------------------------------------------------------------------------

class TestBatchUvExecution(unittest.TestCase):
    BAT = Path(__file__).parent / "uv_runner.bat"

    @unittest.skipUnless(os.name == "nt", "batch scripts only run on Windows")
    def test_batch_runs_python_via_uv(self):
        result = subprocess.run(
            [str(self.BAT)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(self.BAT.parent),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Hello from uv!", result.stdout)

    @unittest.skipUnless(os.name == "nt", "batch scripts only run on Windows")
    def test_batch_exits_zero_with_args(self):
        result = subprocess.run(
            [str(self.BAT), "foo", "bar"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(self.BAT.parent),
        )
        self.assertEqual(result.returncode, 0, result.stderr)


# ---------------------------------------------------------------------------
# Quick Run index TTL logic
# ---------------------------------------------------------------------------

class TestQuickRunIndexTTL(unittest.TestCase):
    """Verify the stale-while-revalidate TTL comparison without needing Tkinter."""

    _TTL = 30.0

    def test_stale_entry_triggers_rebuild(self):
        import time
        cache = {"fake_dir": (time.monotonic() - 35, [])}
        ts, _ = cache["fake_dir"]
        self.assertTrue(time.monotonic() - ts > self._TTL)

    def test_fresh_entry_does_not_trigger_rebuild(self):
        import time
        cache = {"fake_dir": (time.monotonic(), [])}
        ts, _ = cache["fake_dir"]
        self.assertFalse(time.monotonic() - ts > self._TTL)

# ---------------------------------------------------------------------------
# Update-check version parsing (ryos.notifications._parse_version)
# ---------------------------------------------------------------------------

from ryos.notifications import _parse_version  # noqa: E402


class TestParseVersion(unittest.TestCase):
    """The tuple returned is what the update check compares to decide whether
    to show the 'update available' banner, so ordering must be correct."""

    def test_basic_semver(self):
        self.assertEqual(_parse_version("1.7.2"), (1, 7, 2))

    def test_strips_v_prefix(self):
        self.assertEqual(_parse_version("v1.7.2"), (1, 7, 2))

    def test_strips_prerelease_suffix(self):
        self.assertEqual(_parse_version("1.7.2-dev"), (1, 7, 2))
        self.assertEqual(_parse_version("v2.0.0-rc1"), (2, 0, 0))

    def test_two_component_version(self):
        self.assertEqual(_parse_version("v2.0"), (2, 0))

    def test_malformed_returns_zero_tuple(self):
        self.assertEqual(_parse_version("not-a-version"), (0,))
        self.assertEqual(_parse_version(""), (0,))

    def test_newer_compares_greater(self):
        self.assertGreater(_parse_version("v1.7.3"), _parse_version("v1.7.2"))
        self.assertGreater(_parse_version("v1.8.0"), _parse_version("v1.7.9"))
        self.assertGreater(_parse_version("v2.0.0"), _parse_version("v1.9.9"))

    def test_prerelease_equals_release_numerically(self):
        self.assertEqual(_parse_version("1.7.2-dev"), _parse_version("1.7.2"))

    def test_malformed_sorts_lowest(self):
        self.assertGreater(_parse_version("v1.0.0"), _parse_version("garbage"))

# ---------------------------------------------------------------------------
# Quick Run suggestion ranking (ryos.quickrun)
# ---------------------------------------------------------------------------

from ryos.quickrun import build_entry, rank_suggestions  # noqa: E402


class TestQuickRunRanking(unittest.TestCase):
    """Ranking drives the autocomplete dropdown order, so tiers and
    tie-breaks must stay stable."""

    def test_build_entry_shape(self):
        self.assertEqual(
            build_entry("sub/Foo.py", "Foo.py"),
            ("sub/Foo.py", "foo.py", "foo", "sub/foo.py"),
        )

    def test_build_entry_multi_suffix_stem(self):
        # Path.stem drops only the final suffix.
        self.assertEqual(build_entry("a/x.tar.gz", "x.tar.gz")[2], "x.tar")

    def _index(self):
        return [
            build_entry("foo.py", "foo.py"),            # tier 0: stem == query
            build_entry("foobar.py", "foobar.py"),      # tier 1: stem startswith
            build_entry("src/afoo.py", "afoo.py"),      # tier 3: name contains
            build_entry("foo/zzz.py", "zzz.py"),        # tier 4: only path contains
            build_entry("unrelated.py", "unrelated.py"),  # no match
        ]

    def test_tier_ordering(self):
        self.assertEqual(
            rank_suggestions(self._index(), "foo", 10),
            ["foo.py", "foobar.py", "src/afoo.py", "foo/zzz.py"],
        )

    def test_non_matches_excluded(self):
        self.assertNotIn("unrelated.py", rank_suggestions(self._index(), "foo", 10))

    def test_no_match_returns_empty(self):
        self.assertEqual(rank_suggestions(self._index(), "qqq", 10), [])

    def test_max_n_limit(self):
        self.assertEqual(rank_suggestions(self._index(), "foo", 2), ["foo.py", "foobar.py"])

    def test_tiebreak_shorter_stem_first(self):
        idx = [build_entry("abcd.py", "abcd.py"), build_entry("ab.py", "ab.py")]
        # both stem-prefix matches (tier 1); shorter stem "ab" wins.
        self.assertEqual(rank_suggestions(idx, "ab", 10), ["ab.py", "abcd.py"])

    def test_tiebreak_alphabetical_relpath(self):
        idx = [build_entry("dir2/abc.py", "abc.py"), build_entry("dir1/abd.py", "abd.py")]
        # same tier, same stem length -> sorted by relative path.
        self.assertEqual(rank_suggestions(idx, "ab", 10), ["dir1/abd.py", "dir2/abc.py"])

    def test_case_insensitive(self):
        idx = [build_entry("Deploy.PY", "Deploy.PY")]
        self.assertEqual(rank_suggestions(idx, "DEPLOY", 10), ["Deploy.PY"])

# ---------------------------------------------------------------------------
# Schema versioning (ryos.db PRAGMA user_version migration scheme)
# ---------------------------------------------------------------------------

import sqlite3  # noqa: E402

from ryos.db import SCHEMA_VERSION, _BASELINE_VERSION, _run_migrations  # noqa: E402


def _user_version(path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


class TestSchemaVersioning(unittest.TestCase):
    """A fresh or legacy database must end up stamped at the current schema."""

    def test_fresh_db_is_stamped_current(self):
        db = _make_db()
        self.assertEqual(_user_version(db.db_path), SCHEMA_VERSION)
        self.assertGreaterEqual(SCHEMA_VERSION, _BASELINE_VERSION)

    def test_reopen_is_idempotent(self):
        db = _make_db()
        first = _user_version(db.db_path)
        ScriptDB(db.db_path)  # re-init the same file
        self.assertEqual(_user_version(db.db_path), first)

    def test_legacy_unversioned_db_gets_stamped(self):
        db = _make_db()
        conn = sqlite3.connect(db.db_path)
        conn.execute("PRAGMA user_version = 0")  # mimic a pre-versioning database
        conn.commit()
        conn.close()
        ScriptDB(db.db_path)  # re-init should bring it up and stamp it
        self.assertEqual(_user_version(db.db_path), SCHEMA_VERSION)


class TestRunMigrations(unittest.TestCase):
    """The migration runner advances user_version, runs each step once, in order."""

    def _mem(self):
        return sqlite3.connect(":memory:")

    def test_runs_in_order_and_stamps(self):
        conn = self._mem()
        calls = []
        migs = {1: lambda c: calls.append(1),
                2: lambda c: calls.append(2),
                3: lambda c: calls.append(3)}
        final = _run_migrations(conn, migs, 3)
        self.assertEqual(calls, [1, 2, 3])
        self.assertEqual(final, 3)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 3)
        conn.close()

    def test_runs_only_pending(self):
        conn = self._mem()
        conn.execute("PRAGMA user_version = 2")
        calls = []
        migs = {2: lambda c: calls.append(2), 3: lambda c: calls.append(3)}
        _run_migrations(conn, migs, 3)
        self.assertEqual(calls, [3])  # version 2 already applied
        conn.close()

    def test_tolerates_version_gaps(self):
        conn = self._mem()
        calls = []
        migs = {3: lambda c: calls.append(3)}  # no 1 or 2 registered
        final = _run_migrations(conn, migs, 3)
        self.assertEqual(calls, [3])
        self.assertEqual(final, 3)
        conn.close()

    def test_noop_when_up_to_date(self):
        conn = self._mem()
        conn.execute("PRAGMA user_version = 5")
        calls = []
        _run_migrations(conn, {}, 5)
        self.assertEqual(calls, [])
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 5)
        conn.close()

# ---------------------------------------------------------------------------
# Quick Run path containment and name resolution (ryos.quickrun)
# ---------------------------------------------------------------------------

import tempfile as _tempfile  # noqa: E402

from ryos.quickrun import _is_inside, resolve  # noqa: E402


class TestIsInside(unittest.TestCase):
    """Directory-traversal guard for user-typed quick-run paths."""

    def test_direct_child_is_inside(self):
        self.assertTrue(_is_inside("/base/sub/x.py", "/base"))

    def test_base_itself_is_inside(self):
        self.assertTrue(_is_inside("/base", "/base"))

    def test_sibling_is_outside(self):
        self.assertFalse(_is_inside("/other/x.py", "/base"))

    def test_prefix_lookalike_is_outside(self):
        # "/baseball" must not count as inside "/base".
        self.assertFalse(_is_inside("/baseball/x.py", "/base"))

    def test_empty_args_are_outside(self):
        self.assertFalse(_is_inside("", "/base"))
        self.assertFalse(_is_inside("/base/x", ""))


class TestResolve(unittest.TestCase):
    """Resolving a typed name/path to a script under a base directory."""

    def _touch(self, base, *parts):
        p = Path(base, *parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# x", encoding="utf-8")
        return p

    def test_empty_query(self):
        with _tempfile.TemporaryDirectory() as base:
            self.assertEqual(resolve(base, "   "), (None, [], "Please enter a script name."))

    def test_single_match(self):
        with _tempfile.TemporaryDirectory() as base:
            self._touch(base, "foo.py")
            abs_path, candidates, err = resolve(base, "foo")
            self.assertEqual((candidates, err), ([], ""))
            self.assertEqual(os.path.basename(abs_path), "foo.py")

    def test_no_match(self):
        with _tempfile.TemporaryDirectory() as base:
            self._touch(base, "foo.py")
            abs_path, candidates, err = resolve(base, "nope")
            self.assertIsNone(abs_path)
            self.assertEqual(candidates, [])
            self.assertIn("No script found", err)

    def test_multiple_matches(self):
        with _tempfile.TemporaryDirectory() as base:
            self._touch(base, "a", "foo.py")
            self._touch(base, "b", "foo.py")
            abs_path, candidates, err = resolve(base, "foo")
            self.assertIsNone(abs_path)
            self.assertEqual(err, "")
            self.assertEqual(len(candidates), 2)

    def test_path_style_query_inside(self):
        with _tempfile.TemporaryDirectory() as base:
            self._touch(base, "sub", "bar.py")
            abs_path, candidates, err = resolve(base, "sub/bar.py")
            self.assertEqual((candidates, err), ([], ""))
            self.assertEqual(os.path.basename(abs_path), "bar.py")

    def test_traversal_attempt_rejected(self):
        with _tempfile.TemporaryDirectory() as base:
            abs_path, candidates, err = resolve(base, "../escape.txt")
            self.assertIsNone(abs_path)
            self.assertEqual(candidates, [])
            self.assertIn("outside the base directory", err)

    def test_skip_dirs_ignored(self):
        with _tempfile.TemporaryDirectory() as base:
            self._touch(base, "__pycache__", "hidden.py")  # only match is in a skipped dir
            abs_path, candidates, err = resolve(base, "hidden")
            self.assertIsNone(abs_path)
            self.assertIn("No script found", err)
