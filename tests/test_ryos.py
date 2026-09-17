# -*- coding: utf-8 -*-
"""
Unit tests for RYOS non-UI layers: ScriptDB, detect_interpreter, build_command.
Run with:  uv run python -m pytest tests/test_ryos.py -v
       or: uv run python -m unittest discover -s tests -v
"""
import ast
import json
import os
import re
import socket
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

from ryos.db import TRIGGER_AFTER, TRIGGER_WITH, ScriptDB  # noqa: E402
from ryos.interpreter import detect_interpreter, build_command  # noqa: E402
from ryos.screens import relocate_geometry  # noqa: E402
from ryos.themes import (  # noqa: E402
    ADVANCED_KEYS, BUILTIN_THEMES, PRESETS_DIR, REFERENCE, SEEDS, THEME_LABELS,
    THEME_MODES, THEME_ORDER, _REFERENCE_FALLBACK, _shade, build_palette,
    contrast_ratio, contrast_warnings, delete_user_theme,
    disambiguate_custom_labels, export_theme, import_theme, is_hex_color,
    load_base_themes, load_custom_themes, load_presets, load_user_themes,
    resolve_user_themes_dir, save_custom_themes, save_user_theme, validate_seed,
)

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
        self.assertEqual(data["version"], 6)
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
                    shell=True, cwd=str(self.BAT.parent),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(preset_params, result.stdout)


# ---------------------------------------------------------------------------
# groups_with_match (cross-group search hint)
# ---------------------------------------------------------------------------

class TestScriptDBGroupsWithMatch(unittest.TestCase):

    def setUp(self):
        self.db = _make_db()
        self.db.create_group("Alpha")
        self.db.create_group("Beta")
        self.db.add("deploy", "/a/deploy.py", "", "", "Alpha")
        self.db.add("backup", "/b/backup.py", "", "", "Beta")
        self.db.add("loose", "/loose.py", "", "")  # ungrouped

    def test_blank_query_returns_empty(self):
        self.assertEqual(self.db.groups_with_match(""), [])
        self.assertEqual(self.db.groups_with_match("   "), [])

    def test_finds_group_by_script_name(self):
        self.assertEqual(self.db.groups_with_match("backup"), ["Beta"])

    def test_case_insensitive(self):
        self.assertEqual(self.db.groups_with_match("BACKUP"), ["Beta"])

    def test_substring_match(self):
        self.assertEqual(self.db.groups_with_match("ploy"), ["Alpha"])

    def test_no_match_returns_empty(self):
        self.assertEqual(self.db.groups_with_match("nonexistent"), [])

    def test_ungrouped_reported_last(self):
        self.db.add("zdeploy", "/z.py", "", "")  # ungrouped, also matches "deploy"
        self.assertEqual(self.db.groups_with_match("deploy"), ["Alpha", ""])

    def test_matches_pipeline_name(self):
        self.db.create_pipeline("nightly", "Beta")
        self.assertEqual(self.db.groups_with_match("nightly"), ["Beta"])

    def test_underscore_is_literal_not_wildcard(self):
        self.db.add("a_b", "/ab.py", "", "", "Alpha")
        # 'axb' must not match 'a_b' — underscore is escaped to a literal.
        self.assertEqual(self.db.groups_with_match("axb"), [])
        self.assertEqual(self.db.groups_with_match("a_b"), ["Alpha"])

    def test_counts_blank_query(self):
        self.assertEqual(self.db.group_match_counts(""), [])

    def test_counts_single_match(self):
        self.assertEqual(self.db.group_match_counts("backup"), [("Beta", 1)])

    def test_counts_sum_scripts_and_pipelines(self):
        self.db.add("deploy2", "/a/deploy2.py", "", "", "Alpha")
        self.db.create_pipeline("deploy-nightly", "Alpha")
        # 'deploy', 'deploy2' (scripts) + 'deploy-nightly' (pipeline) = 3 in Alpha.
        self.assertEqual(self.db.group_match_counts("deploy"), [("Alpha", 3)])

    def test_counts_ordering_and_ungrouped_last(self):
        self.db.add("backup-x", "/x.py", "", "", "Alpha")
        self.db.add("backup-z", "/z.py", "", "")  # ungrouped
        # Alpha first (group order), Beta next, ungrouped last.
        self.assertEqual(
            self.db.group_match_counts("backup"),
            [("Alpha", 1), ("Beta", 1), ("", 1)],
        )


# ---------------------------------------------------------------------------
# relocate_geometry (multi-monitor window placement)
# ---------------------------------------------------------------------------

class TestRelocateGeometry(unittest.TestCase):
    PRIMARY = (0, 0, 1920, 1040)        # work area (taskbar trimmed)
    RIGHT   = (1920, 0, 1920, 1040)     # monitor to the right
    LEFT    = (-1920, 0, 1920, 1040)    # monitor to the left

    def test_preserves_relative_offset(self):
        # 100,200 from primary origin -> same offset from right monitor origin.
        self.assertEqual(
            relocate_geometry("540x640+100+200", self.PRIMARY, self.RIGHT),
            "540x640+2020+200",
        )

    def test_relocate_to_left_monitor_negative_coords(self):
        self.assertEqual(
            relocate_geometry("540x640+100+200", self.PRIMARY, self.LEFT),
            "540x640+-1820+200",
        )

    def test_parses_negative_source_origin(self):
        # Window was on the left monitor; move it to primary keeps the offset.
        self.assertEqual(
            relocate_geometry("540x640+-1820+200", self.LEFT, self.PRIMARY),
            "540x640+100+200",
        )

    def test_clamps_to_destination_right_edge(self):
        # Near the right edge of a wide monitor -> clamped onto a narrow one.
        narrow = (1920, 0, 800, 600)
        out = relocate_geometry("540x640+1700+50", self.PRIMARY, narrow)
        # width 540 > 600? no; height 640 > 600 -> y pinned to top (1920..), x clamped.
        self.assertEqual(out, "540x640+2180+0")

    def test_size_only_geometry_unchanged(self):
        self.assertEqual(
            relocate_geometry("540x640", self.PRIMARY, self.RIGHT),
            "540x640",
        )

    def test_unparseable_returns_input(self):
        self.assertEqual(relocate_geometry("garbage", self.PRIMARY, self.RIGHT), "garbage")


# ---------------------------------------------------------------------------
# Theme engine (seed -> palette derivation)
# ---------------------------------------------------------------------------

class TestThemeEngine(unittest.TestCase):
    HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
    REF_KEYS = set(REFERENCE["light"])

    def test_reference_themes_share_key_set(self):
        self.assertEqual(set(REFERENCE["dark"]), self.REF_KEYS)

    def test_builtins_identical_to_reference(self):
        # Phase 1 must not change the look of light/dark.
        self.assertEqual(BUILTIN_THEMES["light"], REFERENCE["light"])
        self.assertEqual(BUILTIN_THEMES["dark"], REFERENCE["dark"])

    def test_build_palette_key_parity(self):
        for name in ("light", "dark"):
            with self.subTest(seed=name):
                self.assertEqual(set(build_palette(SEEDS[name])), self.REF_KEYS)

    def test_build_palette_all_valid_hex(self):
        for name in ("light", "dark"):
            p = build_palette(SEEDS[name])
            bad = [k for k, v in p.items() if not self.HEX.match(v)]
            self.assertEqual(bad, [], f"non-hex values: {bad}")

    def test_synthetic_seed_derives_complete_palette(self):
        nord = {"mode": "dark", "bg": "#2e3440", "surface": "#3b4252",
                "border": "#434c5e", "accent": "#88c0d0", "text": "#eceff4",
                "text_muted": "#9aa3b5", "header_bg": "#272c36"}
        p = build_palette(nord)
        self.assertEqual(set(p), self.REF_KEYS)
        self.assertTrue(all(self.HEX.match(v) for v in p.values()))
        self.assertEqual(p["accent"], "#88c0d0")
        self.assertEqual(p["bg"], "#2e3440")

    def test_overrides_pin_exact_values(self):
        p = build_palette(SEEDS["light"], overrides={"accent": "#ff0000"})
        self.assertEqual(p["accent"], "#ff0000")

    def test_builtin_seeds_meet_contrast(self):
        for name in ("light", "dark"):
            s = SEEDS[name]
            self.assertGreaterEqual(contrast_ratio(s["text"], s["bg"]), 4.5)
            self.assertGreaterEqual(contrast_ratio(s["text"], s["surface"]), 4.5)
            self.assertGreaterEqual(contrast_ratio(s["text_muted"], s["bg"]), 3.0)

    def test_contrast_ratio_known_values(self):
        self.assertAlmostEqual(contrast_ratio("#000000", "#ffffff"), 21.0, places=1)
        self.assertEqual(contrast_ratio("#ffffff", "#ffffff"), 1.0)

    def test_theme_registry_consistent(self):
        self.assertEqual(set(BUILTIN_THEMES), set(THEME_ORDER))
        for name in THEME_ORDER:
            self.assertIn(name, THEME_LABELS, f"{name} missing label")
            self.assertIn(name, THEME_MODES, f"{name} missing mode")
            self.assertIn(name, SEEDS, f"{name} missing seed")

    def test_every_builtin_palette_complete_and_valid(self):
        for name in THEME_ORDER:
            p = BUILTIN_THEMES[name]
            self.assertEqual(set(p), self.REF_KEYS, f"{name} key parity")
            bad = [k for k, v in p.items() if not self.HEX.match(v)]
            self.assertEqual(bad, [], f"{name} non-hex: {bad}")

    def test_every_theme_meets_contrast(self):
        for name in THEME_ORDER:
            s = SEEDS[name]
            self.assertGreaterEqual(contrast_ratio(s["text"], s["bg"]), 4.5, name)
            self.assertGreaterEqual(contrast_ratio(s["text"], s["surface"]), 4.5, name)
            self.assertGreaterEqual(contrast_ratio(s["text_muted"], s["bg"]), 3.0, name)

    def test_advanced_override_with_companion(self):
        seed = {**SEEDS["light"], "btn_run_bg": "#ff0000"}
        p = build_palette(seed)
        self.assertEqual(p["btn_run_bg"], "#ff0000")
        self.assertEqual(p["btn_run_hover"], _shade("#ff0000", -0.12))

    def test_advanced_accent2_drives_button_hovers(self):
        p = build_palette({**SEEDS["light"], "accent2": "#123456"})
        self.assertEqual(p["accent2"], "#123456")
        self.assertEqual(p["btn_mod_hover"], "#123456")
        self.assertEqual(p["btn_create_hover"], "#123456")

    def test_advanced_absent_keeps_derived(self):
        p = build_palette(SEEDS["light"])
        self.assertEqual(p["btn_run_bg"], REFERENCE["light"]["btn_run_bg"])

    def test_advanced_invalid_hex_ignored_in_build(self):
        p = build_palette({**SEEDS["light"], "error": "not-a-color"})
        self.assertEqual(p["error"], REFERENCE["light"]["error"])

    def test_advanced_preserves_key_parity(self):
        seed = {**SEEDS["dark"], "out_bg": "#101010", "pipe_accent": "#aa00aa"}
        self.assertEqual(set(build_palette(seed)), self.REF_KEYS)

    def test_advanced_keys_are_real_palette_keys(self):
        for key, _label in ADVANCED_KEYS:
            self.assertIn(key, self.REF_KEYS, f"{key} not a palette key")

    def test_validate_optional_advanced(self):
        good = SEEDS["dark"]
        self.assertEqual(validate_seed({**good, "out_bg": "#101010"}), [])
        self.assertTrue(any("out_bg" in p for p in validate_seed({**good, "out_bg": "x"})))


# ---------------------------------------------------------------------------
# Bundled preset themes (loaded from JSON)
# ---------------------------------------------------------------------------

class TestBundledThemes(unittest.TestCase):
    """Only Light and Dark ship with the app; extra themes live in the gallery
    and are imported by the user."""

    def test_only_light_dark_bundled(self):
        self.assertEqual(THEME_ORDER, ["light", "dark"])
        self.assertEqual(set(BUILTIN_THEMES), {"light", "dark"})

    def test_no_bundled_presets(self):
        self.assertEqual(load_presets(), [])

    def test_load_presets_missing_dir_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(load_presets(Path(d)), [])


class TestThemeGallery(unittest.TestCase):
    GALLERY = Path(__file__).resolve().parents[1] / "theme-gallery"
    # Core themes that must always be in the gallery; more may be added freely.
    EXPECTED = {"light", "dark", "nord", "solarized-light", "solarized-dark",
                "high-contrast", "sepia"}

    def test_core_gallery_files_present(self):
        names = {p.stem for p in self.GALLERY.glob("*.json")}
        missing = self.EXPECTED - names
        self.assertEqual(missing, set(), f"missing gallery themes: {missing}")

    def test_gallery_themes_importable(self):
        for fp in self.GALLERY.glob("*.json"):
            name, seed = import_theme(fp)  # raises if invalid
            self.assertTrue(name, f"{fp.name} has no name")
            self.assertEqual(validate_seed(seed), [], f"{fp.name} invalid seed")


# ---------------------------------------------------------------------------
# Pipeline editor theming (regression: hardcoded hex vs the live palette)
# ---------------------------------------------------------------------------

class TestPipelineEditorTheming(unittest.TestCase):
    """The pipeline editor once paired hardcoded near-white backgrounds with a
    theme-aware fg, so its list and buttons were invisible in dark themes. These
    read the widget colours straight out of the module source, so they fail if
    anyone reintroduces a literal colour or picks an unreadable palette key."""

    SRC_PATH = Path(__file__).resolve().parents[1] / "ryos" / "ui" / "pipeline.py"
    GALLERY = Path(__file__).resolve().parents[1] / "theme-gallery"
    HEX_RE = re.compile(r"#[0-9a-fA-F]{6}")
    # White-on-accent is an app-wide brand convention owned by the theme engine,
    # not by this dialog, so those pairs are out of scope here.
    SKIP_FG_KEYS = {"fg_on_dark", "btn_fg"}

    @classmethod
    def setUpClass(cls):
        cls.source = cls.SRC_PATH.read_text(encoding="utf-8")
        cls.pairs = cls._extract_pairs(cls.source)
        cls.gallery = {}
        for fp in sorted(cls.GALLERY.glob("*.json")):
            name, seed = import_theme(fp)
            cls.gallery[fp.stem] = build_palette(seed)

    @staticmethod
    def _color_expr(node):
        """('key', name) for C["name"], ('hex', value) for a literal, else None."""
        if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                and node.value.id == "C" and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)):
            return ("key", node.slice.value)
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and re.fullmatch(r"#[0-9a-fA-F]{6}", node.value)):
            return ("hex", node.value)
        return None

    @classmethod
    def _extract_pairs(cls, source):
        """(line, widget, fg, bg, role) for every tk.* widget setting both a
        statically resolvable foreground and background."""
        out = []
        for node in ast.walk(ast.parse(source)):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "tk"):
                continue
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            fg = cls._color_expr(kw["fg"]) if "fg" in kw else None
            if fg is None:
                continue
            for arg, role in (("bg", "idle"), ("activebackground", "hover")):
                bg = cls._color_expr(kw[arg]) if arg in kw else None
                if bg is not None:
                    out.append((node.lineno, node.func.attr, fg, bg, role))
        return out

    @staticmethod
    def _resolve(expr, palette):
        kind, value = expr
        return palette[value] if kind == "key" else value

    def test_no_hardcoded_hex_colors(self):
        # Catches the Cancel button, whose own fg/bg pair is legible but frozen
        # to the light palette — a defect contrast alone cannot express.
        hits = [(i, line.strip())
                for i, line in enumerate(self.source.splitlines(), 1)
                if self.HEX_RE.search(line)]
        self.assertEqual(hits, [], f"colours must come from C[...]: {hits}")

    def test_scan_finds_widget_pairs(self):
        # Guard: an AST scan that matches nothing would make the rest vacuous.
        self.assertGreaterEqual(len(self.pairs), 10, "AST scan found too few widgets")

    def test_builtin_themes_meet_contrast(self):
        for name in THEME_ORDER:
            palette = BUILTIN_THEMES[name]
            for line, widget, fg, bg, role in self.pairs:
                if fg[0] == "key" and fg[1] in self.SKIP_FG_KEYS:
                    continue
                f, b = self._resolve(fg, palette), self._resolve(bg, palette)
                with self.subTest(theme=name, line=line, widget=widget, role=role):
                    self.assertGreaterEqual(
                        contrast_ratio(f, b), 4.5,
                        f"{name}: tk.{widget} line {line} ({role}) {f} on {b}")

    def test_gallery_themes_stay_legible(self):
        # Gallery themes are user content: hold idle states to a 3.0 floor.
        # Hover pairs are excluded (btn_neutral_hover bottoms out at 2.7 there).
        for name, palette in self.gallery.items():
            for line, widget, fg, bg, role in self.pairs:
                if role != "idle" or (fg[0] == "key" and fg[1] in self.SKIP_FG_KEYS):
                    continue
                f, b = self._resolve(fg, palette), self._resolve(bg, palette)
                with self.subTest(theme=name, line=line, widget=widget):
                    self.assertGreaterEqual(
                        contrast_ratio(f, b), 3.0,
                        f"{name}: tk.{widget} line {line} {f} on {b}")


class TestDisambiguateLabels(unittest.TestCase):
    IDS = ["light", "dark"]
    LABELS = ["Light", "Dark"]

    def test_no_collision_keeps_name(self):
        out = disambiguate_custom_labels(["Ocean"], self.IDS, self.LABELS)
        self.assertEqual(out, [("Ocean", "Ocean")])

    def test_collision_with_builtin_label_suffixed(self):
        out = dict(disambiguate_custom_labels(["Light", "Dark"], self.IDS, self.LABELS))
        self.assertEqual(out["Light"], "Light (custom)")
        self.assertEqual(out["Dark"], "Dark (custom)")

    def test_collision_with_builtin_id_suffixed(self):
        # 'dark' (id form) collides too.
        out = dict(disambiguate_custom_labels(["dark"], self.IDS, self.LABELS))
        self.assertEqual(out["dark"], "dark (custom)")

    def test_name_unchanged_only_label_suffixed(self):
        out = disambiguate_custom_labels(["Light"], self.IDS, self.LABELS)
        self.assertEqual(out[0][0], "Light")  # id/name preserved


class TestBaseThemes(unittest.TestCase):
    """light/dark are full-palette JSON files loaded into REFERENCE, with a
    hardcoded fallback so the look never changes."""

    def test_base_theme_files_present(self):
        self.assertTrue((PRESETS_DIR / "light.json").exists())
        self.assertTrue((PRESETS_DIR / "dark.json").exists())

    def test_load_base_themes_full_palettes(self):
        bases = {bid: (label, pal, seed)
                 for bid, label, pal, seed in load_base_themes()}
        self.assertEqual(set(bases), {"light", "dark"})
        for bid, (_label, pal, seed) in bases.items():
            self.assertEqual(set(pal), set(_REFERENCE_FALLBACK[bid]))
            self.assertEqual(validate_seed(seed), [], f"{bid} seed invalid")

    def test_json_matches_hardcoded_fallback(self):
        # Guard against the JSON drifting from the in-code fallback.
        self.assertEqual(REFERENCE["light"], _REFERENCE_FALLBACK["light"])
        self.assertEqual(REFERENCE["dark"], _REFERENCE_FALLBACK["dark"])

    def test_builtins_used_verbatim(self):
        self.assertEqual(BUILTIN_THEMES["light"], REFERENCE["light"])
        self.assertEqual(BUILTIN_THEMES["dark"], REFERENCE["dark"])

    def test_missing_dir_falls_back(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(load_base_themes(Path(d)), [])


# ---------------------------------------------------------------------------
# User theme folder (per-file, auto-scanned, configurable)
# ---------------------------------------------------------------------------

class TestUserThemeFolder(unittest.TestCase):
    GOOD = {"mode": "dark", "bg": "#2e3440", "surface": "#3b4252", "border": "#434c5e",
            "accent": "#88c0d0", "text": "#eceff4", "text_muted": "#aab1c0",
            "header_bg": "#272c36"}

    def test_resolve_default_when_unset(self):
        self.assertEqual(resolve_user_themes_dir("").name, "themes")
        self.assertEqual(resolve_user_themes_dir(None).name, "themes")

    def test_resolve_uses_configured_path(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(resolve_user_themes_dir(d), Path(d))

    def test_save_load_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(load_user_themes(d), {})
            p = save_user_theme(d, "My Theme", self.GOOD)
            self.assertEqual(p.name, "my-theme.json")
            self.assertEqual(load_user_themes(d), {"My Theme": self.GOOD})

    def test_dropped_bare_seed_uses_filename(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "dropped.json").write_text(json.dumps(self.GOOD), encoding="utf-8")
            self.assertEqual(load_user_themes(d), {"dropped": self.GOOD})

    def test_invalid_file_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "bad.json").write_text(json.dumps({"seed": {"mode": "dark"}}),
                                              encoding="utf-8")
            self.assertEqual(load_user_themes(d), {})

    def test_delete_by_name(self):
        with tempfile.TemporaryDirectory() as d:
            save_user_theme(d, "My Theme", self.GOOD)
            delete_user_theme(d, "My Theme")
            self.assertFalse((Path(d) / "my-theme.json").exists())
            self.assertEqual(load_user_themes(d), {})


# ---------------------------------------------------------------------------
# Custom themes (validation + persistence)
# ---------------------------------------------------------------------------

class TestCustomThemes(unittest.TestCase):
    GOOD = {"mode": "dark", "bg": "#2e3440", "surface": "#3b4252", "border": "#434c5e",
            "accent": "#88c0d0", "text": "#eceff4", "text_muted": "#aab1c0",
            "header_bg": "#272c36"}

    def test_is_hex_color(self):
        self.assertTrue(is_hex_color("#aabbcc"))
        self.assertFalse(is_hex_color("#abc"))
        self.assertFalse(is_hex_color("red"))
        self.assertFalse(is_hex_color(123))

    def test_valid_seed_has_no_problems(self):
        self.assertEqual(validate_seed(self.GOOD), [])

    def test_validate_flags_bad_mode_and_hex(self):
        self.assertIn("mode must be 'light' or 'dark'",
                      validate_seed({**self.GOOD, "mode": "x"}))
        self.assertTrue(any("bg" in p for p in validate_seed({**self.GOOD, "bg": "red"})))

    def test_validate_non_dict(self):
        self.assertEqual(validate_seed("nope"), ["theme must be an object"])

    def test_contrast_warnings(self):
        self.assertEqual(contrast_warnings(self.GOOD), [])
        low = {**self.GOOD, "text": "#3b4252"}
        self.assertTrue(contrast_warnings(low))

    def test_persistence_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "themes.json"
            self.assertEqual(load_custom_themes(p), {})
            save_custom_themes({"My Theme": self.GOOD}, p)
            self.assertEqual(load_custom_themes(p), {"My Theme": self.GOOD})

    def test_corrupt_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "themes.json"
            p.write_text("{ not json", encoding="utf-8")
            self.assertEqual(load_custom_themes(p), {})

    def test_invalid_entry_dropped_on_load(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "themes.json"
            save_custom_themes({"ok": self.GOOD, "bad": {"mode": "dark"}}, p)
            loaded = load_custom_themes(p)
            self.assertIn("ok", loaded)
            self.assertNotIn("bad", loaded)

    def test_export_import_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.json"
            export_theme("My Theme", self.GOOD, p)
            name, seed = import_theme(p)
            self.assertEqual(name, "My Theme")
            self.assertEqual(seed, self.GOOD)

    def test_import_bare_seed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bare.json"
            p.write_text(json.dumps(self.GOOD), encoding="utf-8")
            name, seed = import_theme(p)
            self.assertEqual(name, "")
            self.assertEqual(seed, self.GOOD)

    def test_import_single_map(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "map.json"
            p.write_text(json.dumps({"Cool": self.GOOD}), encoding="utf-8")
            name, seed = import_theme(p)
            self.assertEqual(name, "Cool")
            self.assertEqual(seed, self.GOOD)

    def test_import_invalid_seed_raises(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.json"
            p.write_text(json.dumps({"name": "x", "seed": {"mode": "dark"}}),
                         encoding="utf-8")
            with self.assertRaises(ValueError):
                import_theme(p)

    def test_import_non_theme_raises(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "no.json"
            p.write_text(json.dumps({"foo": 1, "bar": 2}), encoding="utf-8")
            with self.assertRaises(ValueError):
                import_theme(p)


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
            shell=True,
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
            shell=True,
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

    def test_non_string_tag_returns_zero_tuple(self):
        # AttributeError path (tag is not a str) still sorts lowest.
        self.assertEqual(_parse_version(None), (0,))

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


from ryos.quickrun import should_index, serialize_index, deserialize_index  # noqa: E402


class TestQuickRunIndexHelpers(unittest.TestCase):
    """Extension filtering and the compact on-disk index format."""

    def test_should_index_filters_by_extension(self):
        exts = {".py", ".sh"}
        self.assertTrue(should_index("deploy.py", exts))
        self.assertTrue(should_index("run.sh", exts))
        self.assertFalse(should_index("notes.txt", exts))
        self.assertFalse(should_index("data.csv", exts))

    def test_should_index_case_insensitive(self):
        self.assertTrue(should_index("Deploy.PY", {".py"}))

    def test_should_index_empty_allowlist_indexes_everything(self):
        # Falsy allowed_exts is the escape hatch: keep every file.
        self.assertTrue(should_index("notes.txt", []))
        self.assertTrue(should_index("noextension", set()))

    def test_should_index_extensionless_excluded_when_filtering(self):
        self.assertFalse(should_index("Makefile", {".py"}))

    def test_serialize_keeps_only_relpath(self):
        entries = [build_entry("sub/Foo.py", "Foo.py"), build_entry("bar.sh", "bar.sh")]
        self.assertEqual(serialize_index(entries), ["sub/Foo.py", "bar.sh"])

    def test_serialize_deserialize_round_trip(self):
        # The lowercased fields are derivable, so a round trip through the
        # compact form must reproduce the original entries exactly.
        entries = [build_entry("sub/Foo.py", "Foo.py"), build_entry("a/x.tar.gz", "x.tar.gz")]
        self.assertEqual(deserialize_index(serialize_index(entries)), entries)

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

    def test_trigger_mode_migration_is_idempotent(self):
        # Opening an already-migrated database a second (or third) time must
        # not re-run the ALTER TABLE (which would error on a duplicate column).
        db = _make_db()
        cols = [r[1] for r in sqlite3.connect(db.db_path).execute(
            "PRAGMA table_info(pipeline_steps)")]
        self.assertIn("trigger_mode", cols)
        ScriptDB(db.db_path)
        ScriptDB(db.db_path)
        cols_again = [r[1] for r in sqlite3.connect(db.db_path).execute(
            "PRAGMA table_info(pipeline_steps)")]
        self.assertEqual(cols_again.count("trigger_mode"), 1)

    def test_label_color_migration_adds_both_tables(self):
        db = _make_db()
        for table in ("scripts", "pipelines"):
            cols = [r[1] for r in sqlite3.connect(db.db_path).execute(
                f"PRAGMA table_info({table})")]
            self.assertIn("label_color", cols, table)

    def test_label_color_migration_is_idempotent(self):
        # Replaying it (a version-0 reset over a current schema) must not raise
        # a duplicate-column error or add the column twice.
        db = _make_db()
        conn = sqlite3.connect(db.db_path)
        conn.execute("PRAGMA user_version = 0")
        conn.commit()
        conn.close()
        ScriptDB(db.db_path)
        for table in ("scripts", "pipelines"):
            cols = [r[1] for r in sqlite3.connect(db.db_path).execute(
                f"PRAGMA table_info({table})")]
            self.assertEqual(cols.count("label_color"), 1, table)


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

# ---------------------------------------------------------------------------
# Job container + elapsed-time formatting (ryos.jobs)
# ---------------------------------------------------------------------------

from datetime import datetime as _dt  # noqa: E402

from ryos.jobs import Job, format_elapsed  # noqa: E402


class TestFormatElapsed(unittest.TestCase):
    """The running-row time label shown next to each job."""

    def test_seconds_only(self):
        start = _dt(2026, 6, 10, 14, 3, 9)
        self.assertEqual(format_elapsed(start, _dt(2026, 6, 10, 14, 3, 14)), "14:03:09  ·  5s")

    def test_zero(self):
        start = _dt(2026, 6, 10, 9, 0, 0)
        self.assertEqual(format_elapsed(start, start), "09:00:00  ·  0s")

    def test_one_minute_pads_seconds(self):
        start = _dt(2026, 6, 10, 0, 0, 0)
        self.assertEqual(format_elapsed(start, _dt(2026, 6, 10, 0, 1, 5)), "00:00:00  ·  1m 05s")

    def test_exact_minute(self):
        start = _dt(2026, 6, 10, 0, 0, 0)
        self.assertEqual(format_elapsed(start, _dt(2026, 6, 10, 0, 10, 0)), "00:00:00  ·  10m 00s")

    def test_minutes_not_capped_at_60(self):
        start = _dt(2026, 6, 10, 0, 0, 0)
        self.assertEqual(format_elapsed(start, _dt(2026, 6, 10, 1, 1, 1)), "00:00:00  ·  61m 01s")


class TestJob(unittest.TestCase):
    """Job state container construction and defaults."""

    def test_defaults(self):
        j = Job(1, "script", 5, None, "Test", "tab1", "grp")
        self.assertEqual((j.job_id, j.kind, j.script_id), (1, "script", 5))
        self.assertEqual(j.pipeline_queue, [])
        self.assertEqual(j.pipeline_total, 0)
        self.assertFalse(j.stopped)
        self.assertIsNone(j.current_process)

    def test_pipeline_queues_are_independent(self):
        # Guards against a shared mutable default argument.
        a = Job(1, "s", 1, None, "a", "t", "g")
        b = Job(2, "s", 2, None, "b", "t", "g")
        a.pipeline_queue.append("step")
        self.assertEqual(b.pipeline_queue, [])

    def test_active_processes_filters_exited_and_none(self):
        class _FakeProc:
            def __init__(self, exit_code):
                self._exit_code = exit_code

            def poll(self):
                return self._exit_code

        running1 = _FakeProc(None)
        running2 = _FakeProc(None)
        exited = _FakeProc(0)
        j = Job(1, "pipeline", None, 9, "P", "t", "g")
        j.processes = {None: None, "a": running1, "b": exited, "c": running2}
        self.assertEqual(set(j.active_processes()), {running1, running2})

# ---------------------------------------------------------------------------
# resolve_interpreter + _script_tag (ryos.interpreter)
# ---------------------------------------------------------------------------

from ryos.interpreter import resolve_interpreter, _script_tag  # noqa: E402


class TestResolveInterpreter(unittest.TestCase):
    """Effective interpreter: stored value wins, else auto-detect; never RYOS.exe."""

    def test_stored_value_used(self):
        self.assertEqual(resolve_interpreter("x.py", "python3"), "python3")

    def test_blank_stored_falls_back_to_detect(self):
        self.assertEqual(resolve_interpreter("x.py", ""), sys.executable)
        self.assertEqual(resolve_interpreter("x.js", "   "), "node")

    def test_stored_is_trimmed(self):
        self.assertEqual(resolve_interpreter("x.py", "  node  "), "node")

    def test_ryos_exe_is_rejected_and_redetected(self):
        # A stored interpreter pointing at RYOS itself (a stale compiled-build
        # entry) must not relaunch the app — it falls back to detection.
        self.assertEqual(resolve_interpreter("x.py", "RYOS.exe"), sys.executable)
        self.assertEqual(resolve_interpreter("x.js", "/usr/local/bin/ryos.exe"), "node")
        self.assertEqual(resolve_interpreter("x.js", "ryos"), "node")


class TestScriptTag(unittest.TestCase):
    """Badge label/colour shown on a script card."""

    def test_known_extension(self):
        self.assertEqual(_script_tag("a.py"), ("Python", "#2B5B84"))
        self.assertEqual(_script_tag("a.ps1"), ("PowerShell", "#1A3A6C"))

    def test_case_insensitive(self):
        self.assertEqual(_script_tag("DEPLOY.PY"), ("Python", "#2B5B84"))

    def test_unknown_extension_uppercased(self):
        self.assertEqual(_script_tag("data.xyz"), ("XYZ", "#555555"))

    def test_no_extension(self):
        self.assertEqual(_script_tag("Makefile"), ("Script", "#555555"))


# ---------------------------------------------------------------------------
# Settings load/save (ryos.settings) — the #2 error-handling fix
# ---------------------------------------------------------------------------

import ryos.settings as _settings_mod  # noqa: E402

from ryos.settings import _SETTINGS_DEFAULTS, _load_settings, _save_settings  # noqa: E402


class TestSettings(unittest.TestCase):
    """Loading tolerates missing/corrupt files; saving round-trips."""

    def setUp(self):
        self._orig_path = _settings_mod._SETTINGS_PATH
        self._dir = tempfile.mkdtemp()
        _settings_mod._SETTINGS_PATH = Path(self._dir) / "settings.json"

    def tearDown(self):
        _settings_mod._SETTINGS_PATH = self._orig_path

    def test_missing_file_returns_defaults(self):
        self.assertEqual(_load_settings(), dict(_SETTINGS_DEFAULTS))

    def test_corrupt_file_falls_back_to_defaults(self):
        _settings_mod._SETTINGS_PATH.write_text("{ not valid json", encoding="utf-8")
        loaded = _load_settings()
        self.assertEqual(loaded["theme"], _SETTINGS_DEFAULTS["theme"])
        self.assertEqual(len(loaded), len(_SETTINGS_DEFAULTS))

    def test_stored_values_override_defaults(self):
        _settings_mod._SETTINGS_PATH.write_text(
            json.dumps({"theme": "dark", "window_width": 999}), encoding="utf-8")
        loaded = _load_settings()
        self.assertEqual(loaded["theme"], "dark")
        self.assertEqual(loaded["window_width"], 999)
        self.assertEqual(loaded["card_size"], _SETTINGS_DEFAULTS["card_size"])  # untouched

    def test_unknown_keys_preserved(self):
        # Forward-compat: a key written by a newer version survives the merge.
        _settings_mod._SETTINGS_PATH.write_text(json.dumps({"future_flag": True}), encoding="utf-8")
        self.assertTrue(_load_settings()["future_flag"])

    def test_save_then_load_roundtrip(self):
        d = dict(_SETTINGS_DEFAULTS)
        d["theme"] = "dark"
        d["window_height"] = 720
        _save_settings(d)
        loaded = _load_settings()
        self.assertEqual(loaded["theme"], "dark")
        self.assertEqual(loaded["window_height"], 720)

    def test_close_to_tray_roundtrips(self):
        d = dict(_SETTINGS_DEFAULTS)
        d["close_to_tray"] = True
        _save_settings(d)
        loaded = _load_settings()
        self.assertTrue(loaded["close_to_tray"])

    def test_close_to_tray_defaults_false_for_old_settings_file(self):
        # An old settings.json written before this feature existed simply
        # lacks the key; the merge with _SETTINGS_DEFAULTS must fill it in.
        _settings_mod._SETTINGS_PATH.write_text(
            json.dumps({"theme": "dark"}), encoding="utf-8")
        loaded = _load_settings()
        self.assertEqual(loaded["close_to_tray"], _SETTINGS_DEFAULTS["close_to_tray"])
        self.assertFalse(loaded["close_to_tray"])

    def test_prompt_close_to_tray_defaults_true_for_old_settings_file(self):
        # An old settings.json written before this feature existed simply
        # lacks the key; the merge with _SETTINGS_DEFAULTS must fill it in.
        _settings_mod._SETTINGS_PATH.write_text(
            json.dumps({"theme": "dark"}), encoding="utf-8")
        loaded = _load_settings()
        self.assertEqual(loaded["prompt_close_to_tray"], _SETTINGS_DEFAULTS["prompt_close_to_tray"])
        self.assertTrue(loaded["prompt_close_to_tray"])

    def test_prompt_close_to_tray_roundtrips(self):
        d = dict(_SETTINGS_DEFAULTS)
        d["prompt_close_to_tray"] = False
        _save_settings(d)
        loaded = _load_settings()
        self.assertFalse(loaded["prompt_close_to_tray"])


# ---------------------------------------------------------------------------
# single_instance — mutex + localhost socket handshake guard
# ---------------------------------------------------------------------------

import ryos.single_instance as _single_instance_mod  # noqa: E402


class TestSignalExisting(unittest.TestCase):
    """_signal_existing() must never raise, only return False, on any bad input."""

    def setUp(self):
        self._orig_lock_path = _single_instance_mod._LOCK_PATH
        self._dir = tempfile.mkdtemp()
        _single_instance_mod._LOCK_PATH = Path(self._dir) / "instance.lock"

    def tearDown(self):
        _single_instance_mod._LOCK_PATH = self._orig_lock_path

    def test_missing_lock_file(self):
        self.assertFalse(_single_instance_mod._signal_existing("RESTORE"))

    def test_truncated_invalid_json(self):
        _single_instance_mod._LOCK_PATH.write_text("{ not valid json", encoding="utf-8")
        self.assertFalse(_single_instance_mod._signal_existing("RESTORE"))

    def test_unreachable_closed_port(self):
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
        probe.close()  # port is now closed; nothing is listening on it
        _single_instance_mod._LOCK_PATH.write_text(
            json.dumps({"port": closed_port, "token": "tok", "pid": 1}), encoding="utf-8")
        self.assertFalse(_single_instance_mod._signal_existing("RESTORE"))


# ---------------------------------------------------------------------------
# JobRegistry — job bookkeeping extracted from RYOSApp (ryos.jobs)
# ---------------------------------------------------------------------------

from ryos.jobs import JobRegistry  # noqa: E402


class TestJobRegistry(unittest.TestCase):
    """Id allocation, add/get/remove, group filtering, and emptiness checks."""

    def _job(self, jid, group="g"):
        return Job(jid, "script", jid, None, f"n{jid}", f"job:{jid}", group)

    def test_new_id_is_monotonic(self):
        r = JobRegistry()
        self.assertEqual([r.new_id(), r.new_id(), r.new_id()], [1, 2, 3])

    def test_add_get_all(self):
        r = JobRegistry()
        j = self._job(1)
        r.add(j)
        self.assertIs(r.get(1), j)
        self.assertEqual(r.all(), [j])

    def test_get_missing_returns_none(self):
        self.assertIsNone(JobRegistry().get(99))

    def test_remove(self):
        r = JobRegistry()
        r.add(self._job(1))
        r.remove(1)
        self.assertIsNone(r.get(1))
        self.assertEqual(r.all(), [])

    def test_remove_missing_is_noop(self):
        r = JobRegistry()
        r.remove(123)
        self.assertEqual(len(r), 0)

    def test_in_group_filters(self):
        r = JobRegistry()
        r.add(self._job(1, "a"))
        r.add(self._job(2, "b"))
        r.add(self._job(3, "a"))
        self.assertEqual({j.job_id for j in r.in_group("a")}, {1, 3})
        self.assertEqual(r.in_group("none"), [])

    def test_len_and_bool(self):
        r = JobRegistry()
        self.assertFalse(r)
        self.assertEqual(len(r), 0)
        r.add(self._job(1))
        self.assertTrue(r)
        self.assertEqual(len(r), 1)

    def test_all_is_a_snapshot(self):
        # all() returns a list copy, so removing during iteration is safe.
        r = JobRegistry()
        r.add(self._job(1))
        r.add(self._job(2))
        for j in r.all():
            r.remove(j.job_id)
        self.assertEqual(len(r), 0)


# ---------------------------------------------------------------------------
# ScriptDB — groups
# ---------------------------------------------------------------------------

class TestScriptDBGroups(unittest.TestCase):

    def setUp(self):
        self.db = _make_db()

    def test_create_and_list_in_sort_order(self):
        self.db.create_group("Beta")
        self.db.create_group("Alpha")
        self.assertEqual(self.db.list_groups(), ["Beta", "Alpha"])

    def test_create_group_is_idempotent(self):
        self.db.create_group("G")
        self.db.create_group("G")
        self.assertEqual(self.db.list_groups().count("G"), 1)

    def test_base_dir_get_set(self):
        self.db.create_group("G")
        self.assertEqual(self.db.get_group_base_dir("G"), "")
        self.db.set_group_base_dir("G", "/some/dir")
        self.assertEqual(self.db.get_group_base_dir("G"), "/some/dir")

    def test_list_groups_with_meta(self):
        self.db.create_group("G", base_dir="/x")
        self.assertEqual(self.db.list_groups_with_meta(), [("G", "/x")])

    def test_reorder_groups(self):
        for n in ("A", "B", "C"):
            self.db.create_group(n)
        self.db.reorder_groups(["C", "A", "B"])
        self.assertEqual(self.db.list_groups(), ["C", "A", "B"])

    def test_rename_group_propagates_to_scripts_and_pipelines(self):
        self.db.create_group("Old")
        sid = self.db.add("S", "/s.py", "", "", "Old")
        self.db.create_pipeline("P", "Old")
        self.db.rename_group("Old", "New")
        self.assertIn("New", self.db.list_groups())
        self.assertNotIn("Old", self.db.list_groups())
        rec = [r for r in self.db.list_all() if r[0] == sid][0]
        self.assertEqual(rec[8], "New")  # group_name column
        self.assertEqual([p[1] for p in self.db.list_pipelines("New")], ["P"])

    def test_delete_group_orphans_scripts_and_pipelines(self):
        self.db.create_group("G")
        sid = self.db.add("S", "/s.py", "", "", "G")
        self.db.create_pipeline("P", "G")
        self.db.delete_group("G")
        self.assertNotIn("G", self.db.list_groups())
        rec = [r for r in self.db.list_all() if r[0] == sid][0]
        self.assertEqual(rec[8], "")            # script survives, ungrouped
        self.assertEqual(self.db.list_pipelines("G"), [])

    def test_clone_group_deep_copies(self):
        self.db.create_group("Src", base_dir="/b")
        self.db.add("S1", "/b/s1.py", "a", "", "Src")
        self.db.create_pipeline("P", "Src")
        n_scripts, n_pipes = self.db.clone_group("Src", "Dst")
        self.assertEqual((n_scripts, n_pipes), (1, 1))
        self.assertEqual(self.db.get_group_base_dir("Dst"), "/b")
        self.assertEqual(len(self.db.list_pipelines("Dst")), 1)
        self.assertEqual(len([r for r in self.db.list_all() if r[8] == "Dst"]), 1)


# ---------------------------------------------------------------------------
# ScriptDB — pipelines
# ---------------------------------------------------------------------------

class TestScriptDBPipelines(unittest.TestCase):

    def setUp(self):
        self.db = _make_db()
        self.db.create_group("G")
        self.s1 = self.db.add("One", "/one.py", "p1", "python", "G")
        self.s2 = self.db.add("Two", "/two.py", "", "node", "G")

    def test_create_and_list(self):
        pid = self.db.create_pipeline("Deploy", "G")
        self.assertEqual(self.db.list_pipelines("G"), [(pid, "Deploy", 0, None)])

    def test_add_and_list_steps_join_script_fields(self):
        pid = self.db.create_pipeline("P", "G")
        self.db.add_pipeline_step(pid, self.s1)
        self.db.add_pipeline_step(pid, self.s2)
        steps = self.db.list_pipeline_steps(pid)
        # (step_id, script_id, name, path, params, interpreter, params_override)
        self.assertEqual([s[1] for s in steps], [self.s1, self.s2])
        self.assertEqual(steps[0][2:6], ("One", "/one.py", "p1", "python"))
        self.assertIsNone(steps[0][6])

    def test_update_step_params_override(self):
        pid = self.db.create_pipeline("P", "G")
        st = self.db.add_pipeline_step(pid, self.s1)
        self.db.update_pipeline_step_params(st, "--flag")
        self.assertEqual(self.db.list_pipeline_steps(pid)[0][6], "--flag")

    def test_remove_step(self):
        pid = self.db.create_pipeline("P", "G")
        st1 = self.db.add_pipeline_step(pid, self.s1)
        self.db.add_pipeline_step(pid, self.s2)
        self.db.remove_pipeline_step(st1)
        self.assertEqual([s[1] for s in self.db.list_pipeline_steps(pid)], [self.s2])

    def test_reorder_steps(self):
        pid = self.db.create_pipeline("P", "G")
        st1 = self.db.add_pipeline_step(pid, self.s1)
        st2 = self.db.add_pipeline_step(pid, self.s2)
        self.db.reorder_pipeline_steps(pid, [st2, st1])
        self.assertEqual([s[0] for s in self.db.list_pipeline_steps(pid)], [st2, st1])

    def test_new_step_defaults_to_after(self):
        pid = self.db.create_pipeline("P", "G")
        self.db.add_pipeline_step(pid, self.s1)
        self.assertEqual(self.db.list_pipeline_steps(pid)[0][7], TRIGGER_AFTER)

    def test_set_step_trigger_mode(self):
        pid = self.db.create_pipeline("P", "G")
        self.db.add_pipeline_step(pid, self.s1)
        st2 = self.db.add_pipeline_step(pid, self.s2)
        self.db.set_step_trigger_mode(st2, TRIGGER_WITH)
        self.assertEqual(self.db.list_pipeline_steps(pid)[1][7], TRIGGER_WITH)

    def test_set_step_trigger_mode_normalizes_first_step(self):
        # A step can never be 'with' once it lands in position 1: reordering,
        # removal, or a direct toggle can all promote a step there.
        pid = self.db.create_pipeline("P", "G")
        st1 = self.db.add_pipeline_step(pid, self.s1)
        st2 = self.db.add_pipeline_step(pid, self.s2)
        self.db.set_step_trigger_mode(st2, TRIGGER_WITH)
        # Directly toggling step 1 itself must always stay 'after'.
        self.db.set_step_trigger_mode(st1, TRIGGER_WITH)
        self.assertEqual(self.db.list_pipeline_steps(pid)[0][7], TRIGGER_AFTER)

    def test_reorder_normalizes_promoted_first_step(self):
        pid = self.db.create_pipeline("P", "G")
        st1 = self.db.add_pipeline_step(pid, self.s1)
        st2 = self.db.add_pipeline_step(pid, self.s2)
        self.db.set_step_trigger_mode(st2, TRIGGER_WITH)
        self.db.reorder_pipeline_steps(pid, [st2, st1])  # promotes st2 to position 1
        steps = self.db.list_pipeline_steps(pid)
        self.assertEqual(steps[0][0], st2)
        self.assertEqual(steps[0][7], TRIGGER_AFTER)

    def test_remove_normalizes_promoted_first_step(self):
        pid = self.db.create_pipeline("P", "G")
        st1 = self.db.add_pipeline_step(pid, self.s1)
        st2 = self.db.add_pipeline_step(pid, self.s2)
        self.db.set_step_trigger_mode(st2, TRIGGER_WITH)
        self.db.remove_pipeline_step(st1)  # promotes st2 to position 1
        steps = self.db.list_pipeline_steps(pid)
        self.assertEqual(steps[0][0], st2)
        self.assertEqual(steps[0][7], TRIGGER_AFTER)

    def test_delete_pipeline_cascades_steps(self):
        pid = self.db.create_pipeline("P", "G")
        self.db.add_pipeline_step(pid, self.s1)
        self.db.delete_pipeline(pid)
        self.assertEqual(self.db.list_pipelines("G"), [])
        self.assertEqual(self.db.list_pipeline_steps(pid), [])

    def test_rename_pipeline(self):
        pid = self.db.create_pipeline("Old", "G")
        self.db.rename_pipeline(pid, "New")
        self.assertEqual(self.db.list_pipelines("G"), [(pid, "New", 0, None)])

    def test_clone_pipeline_copies_steps(self):
        pid = self.db.create_pipeline("P", "G")
        self.db.add_pipeline_step(pid, self.s1)
        self.db.add_pipeline_step(pid, self.s2)
        new_id = self.db.clone_pipeline(pid)
        self.assertNotEqual(new_id, pid)
        self.assertIn("P (copy)", [p[1] for p in self.db.list_pipelines("G")])
        self.assertEqual([s[1] for s in self.db.list_pipeline_steps(new_id)], [self.s1, self.s2])

    def test_clone_missing_pipeline_raises(self):
        with self.assertRaises(ValueError):
            self.db.clone_pipeline(9999)

    def test_mark_run_status(self):
        self.db.mark_run_status(self.s1, "error")
        rec = [r for r in self.db.list_all() if r[0] == self.s1][0]
        self.assertEqual(rec[7], "error")  # last_run_status column


# ---------------------------------------------------------------------------
# ScriptDB — drag-and-drop reordering and moving between groups
# ---------------------------------------------------------------------------

class TestScriptDBReorderMove(unittest.TestCase):

    def setUp(self):
        self.db = _make_db()
        self.db.create_group("G")

    def _script_ids(self, group):
        return [r[0] for r in self.db.list_all() if r[8] == group]

    def test_reorder_script_before(self):
        a = self.db.add("A", "/a.py", "", "", "G")
        b = self.db.add("B", "/b.py", "", "", "G")
        c = self.db.add("C", "/c.py", "", "", "G")
        self.db.reorder_script(c, "G", before_id=a)   # C jumps in front of A
        self.assertEqual(self._script_ids("G"), [c, a, b])

    def test_reorder_script_append_when_before_none(self):
        a = self.db.add("A", "/a.py", "", "", "G")
        b = self.db.add("B", "/b.py", "", "", "G")
        self.db.reorder_script(a, "G", before_id=None)  # A goes to the end
        self.assertEqual(self._script_ids("G"), [b, a])

    def test_move_script_to_group(self):
        self.db.create_group("H")
        a = self.db.add("A", "/a.py", "", "", "G")
        self.db.move_to_group(a, "H")
        self.assertEqual([r[8] for r in self.db.list_all() if r[0] == a], ["H"])
        self.assertEqual(self._script_ids("G"), [])

    def test_reorder_pipeline_before(self):
        p1 = self.db.create_pipeline("P1", "G")
        p2 = self.db.create_pipeline("P2", "G")
        p3 = self.db.create_pipeline("P3", "G")
        self.db.reorder_pipeline(p3, "G", before_id=p1)
        self.assertEqual([p[0] for p in self.db.list_pipelines("G")], [p3, p1, p2])

    def test_move_pipeline_to_group(self):
        self.db.create_group("H")
        p = self.db.create_pipeline("P", "G")
        self.db.move_pipeline_to_group(p, "H")
        self.assertEqual([x[0] for x in self.db.list_pipelines("H")], [p])
        self.assertEqual(self.db.list_pipelines("G"), [])


# ---------------------------------------------------------------------------
# ScriptDB — export/import round-trip with pipelines (and the preset boundary)
# ---------------------------------------------------------------------------

class TestExportImportPipelines(unittest.TestCase):

    def setUp(self):
        self.db = _make_db()

    def test_roundtrip_preserves_pipeline_steps_and_base_dir(self):
        self.db.create_group("Deploy", base_dir="/srv")
        s1 = self.db.add("Build", "/srv/build.py", "", "python", "Deploy")
        s2 = self.db.add("Ship", "/srv/ship.sh", "", "bash", "Deploy")
        pid = self.db.create_pipeline("Release", "Deploy")
        self.db.add_pipeline_step(pid, s1)
        self.db.add_pipeline_step(pid, s2)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        self.db.export_to_file(path)

        db2 = _make_db()
        db2.import_from_file(path, replace=False)
        self.assertEqual(db2.get_group_base_dir("Deploy"), "/srv")
        pipes = db2.list_pipelines("Deploy")
        self.assertEqual([p[1] for p in pipes], ["Release"])
        steps = db2.list_pipeline_steps(pipes[0][0])
        self.assertEqual([s[3] for s in steps], ["/srv/build.py", "/srv/ship.sh"])  # wired by path, in order

    def test_roundtrip_preserves_param_presets(self):
        # Param presets are embedded per-script in the export (format v3) and
        # restored on import, wired to the re-created script.
        sid = self.db.add("S", "/s.py", "", "")
        self.db.replace_param_presets(sid, [("Fast", "--fast"), ("Slow", "--slow")])
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        self.db.export_to_file(path)
        db2 = _make_db()
        db2.import_from_file(path, replace=False)
        imported_id = db2.list_all()[0][0]
        presets = db2.list_param_presets(imported_id)
        self.assertEqual([(p[1], p[2]) for p in presets], [("Fast", "--fast"), ("Slow", "--slow")])


# ---------------------------------------------------------------------------
# Quick Run input parsing + display path (ryos.quickrun)
# ---------------------------------------------------------------------------

from ryos.quickrun import display_relpath, parse_input  # noqa: E402


class TestParseInput(unittest.TestCase):
    """Splitting a quick-run entry into query + params."""

    def test_query_only(self):
        self.assertEqual(parse_input("build"), ("build", "", False))

    def test_query_with_params(self):
        self.assertEqual(parse_input("build --fast"), ("build", "--fast", True))

    def test_multiple_param_tokens_rejoined(self):
        self.assertEqual(parse_input("deploy a b c"), ("deploy", "a b c", True))

    def test_empty_and_whitespace(self):
        self.assertEqual(parse_input(""), ("", "", False))
        self.assertEqual(parse_input("   "), ("", "", False))

    def test_quoting_is_platform_aware(self):
        q, params, given = parse_input('run "hello world"')
        self.assertEqual((q, given), ("run", True))
        if os.name == "nt":
            self.assertEqual(params, '"hello world"')   # posix=False keeps quotes
        else:
            self.assertEqual(params, "hello world")      # posix strips them

    def test_unbalanced_quotes_fall_back_to_split(self):
        # shlex would raise; we fall back to a plain whitespace split.
        self.assertEqual(parse_input('a "b'), ("a", '"b', True))


class TestDisplayRelpath(unittest.TestCase):
    """The label shown for a resolved quick-run script."""

    def test_inside_base_is_relative(self):
        with tempfile.TemporaryDirectory() as base:
            abs_path = os.path.join(base, "sub", "x.py")
            self.assertEqual(display_relpath(abs_path, base), os.path.join("sub", "x.py"))

    def test_outside_base_uses_name(self):
        with tempfile.TemporaryDirectory() as base:
            outside = os.path.join(os.path.dirname(base), "zzz_other.py")
            self.assertEqual(display_relpath(outside, base), "zzz_other.py")


# ---------------------------------------------------------------------------
# working_dir_for — cwd selection for a launched command (ryos.interpreter)
# ---------------------------------------------------------------------------

from ryos.interpreter import working_dir_for  # noqa: E402


class TestWorkingDirFor(unittest.TestCase):
    """The directory a script runs from, derived from its command list."""

    def test_script_only(self):
        with tempfile.TemporaryDirectory() as d:
            script = os.path.join(d, "run.py")
            open(script, "w").close()
            self.assertEqual(working_dir_for([script]), d)

    def test_interpreter_prefixed_uses_script_dir(self):
        with tempfile.TemporaryDirectory() as d:
            script = os.path.join(d, "run.py")
            open(script, "w").close()
            # The interpreter ("python") isn't a file; the script is -> its dir wins.
            self.assertEqual(working_dir_for(["python", script, "--flag"]), d)

    def test_falls_back_to_first_arg_when_no_file(self):
        # Nothing exists on disk -> parent of cmd[0].
        self.assertEqual(working_dir_for(["python", "ghost.py"]), str(Path("python").parent))

    def test_absolute_interpreter_does_not_win_over_the_script(self):
        # Regression: the search used to start at argument 0, so a detected
        # interpreter -- which is an absolute path to a real executable, e.g.
        # sys.executable for .py -- matched first and every Python script ran
        # in the Python install directory instead of its own folder.
        with tempfile.TemporaryDirectory() as d:
            script = os.path.join(d, "run.py")
            open(script, "w").close()
            self.assertEqual(working_dir_for([sys.executable, script]), d)

    def test_multi_token_interpreter_still_finds_the_script(self):
        with tempfile.TemporaryDirectory() as d:
            script = os.path.join(d, "run.ps1")
            open(script, "w").close()
            self.assertEqual(working_dir_for(["powershell", "-File", script]), d)

    def test_real_detected_command_runs_in_the_script_dir(self):
        # Through the real detection path, not a hand-built command list.
        with tempfile.TemporaryDirectory() as d:
            script = os.path.join(d, "run.py")
            open(script, "w").close()
            cmd = build_command(script, "", resolve_interpreter(script, ""))
            self.assertEqual(working_dir_for(cmd), d)


# ---------------------------------------------------------------------------
# run_subprocess — the job execution worker (ryos.runner)
# ---------------------------------------------------------------------------

import queue as _queue  # noqa: E402

from ryos.runner import run_subprocess  # noqa: E402


class TestRunSubprocess(unittest.TestCase):
    """Runs real subprocesses and checks the queue protocol the UI consumes."""

    def _job(self):
        return Job(1, "script", 1, None, "t", "job:1", "g")

    def _drain(self, q):
        items = []
        while not q.empty():
            items.append(q.get_nowait())
        return items

    def test_success_streams_stdout_then_done_ok(self):
        q = _queue.Queue()
        run_subprocess(q, self._job(), [sys.executable, "-c", "print('hello')"], "t", 1)
        items = self._drain(q)
        self.assertIn(("stdout", 1, "hello\n"), items)
        done = items[-1]
        self.assertEqual(done[0], "done_tag")
        self.assertEqual(done[3], "ok")          # status
        self.assertIn("exit code 0", done[5])    # footer

    def test_nonzero_exit_reports_error(self):
        q = _queue.Queue()
        run_subprocess(q, self._job(), [sys.executable, "-c", "import sys; sys.exit(3)"], "t", 1)
        done = self._drain(q)[-1]
        self.assertEqual(done[0], "done_tag")
        self.assertEqual(done[3], "error")
        self.assertIn("exit code 3", done[5])

    def test_sets_current_process(self):
        q = _queue.Queue()
        job = self._job()
        run_subprocess(q, job, [sys.executable, "-c", "pass"], "t", 1)
        self.assertIsNotNone(job.current_process)

    def test_missing_binary_reports_done_error_without_raising(self):
        q = _queue.Queue()
        run_subprocess(q, self._job(), ["__definitely_not_a_real_binary__"], "t", 7)
        items = self._drain(q)
        done = [it for it in items if it[0] == "done"]
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0][2], 7)          # script_id echoed back
        self.assertEqual(done[0][3], "error")


from ryos.runner import decode_output_item  # noqa: E402


class TestDecodeOutputItem(unittest.TestCase):
    """The queue protocol decoded from the consumer side (pairs with run_subprocess)."""

    def test_stdout(self):
        a = decode_output_item(("stdout", 5, "line\n"))
        self.assertEqual((a.text, a.tag, a.status, a.step_done), ("line\n", None, None, False))

    def test_stderr(self):
        a = decode_output_item(("stderr", 5, "boom\n"))
        self.assertEqual((a.text, a.tag, a.status, a.step_done), ("boom\n", "stderr", None, False))

    def test_done(self):
        a = decode_output_item(("done", 5, 9, "error", "msg"))
        self.assertEqual((a.text, a.tag, a.status, a.sid, a.step_done),
                         ("msg", "info", "error", 9, True))

    def test_done_tag(self):
        a = decode_output_item(("done_tag", 5, 9, "ok", "ok", "footer"))
        self.assertEqual((a.text, a.tag, a.status, a.sid, a.step_done),
                         ("footer", "ok", "ok", 9, True))

    def test_no_token_decodes_none(self):
        a = decode_output_item(("stdout", 5, "line\n"))
        self.assertIsNone(a.token)

    def test_stdout_with_token(self):
        a = decode_output_item(("stdout", 5, "line\n", "tok"))
        self.assertEqual((a.text, a.tag, a.token), ("line\n", None, "tok"))

    def test_stderr_with_token(self):
        a = decode_output_item(("stderr", 5, "boom\n", "tok"))
        self.assertEqual((a.text, a.tag, a.token), ("boom\n", "stderr", "tok"))

    def test_done_with_token(self):
        a = decode_output_item(("done", 5, 9, "error", "msg", "tok"))
        self.assertEqual((a.status, a.sid, a.step_done, a.token), ("error", 9, True, "tok"))

    def test_done_tag_with_token(self):
        a = decode_output_item(("done_tag", 5, 9, "ok", "ok", "footer", "tok"))
        self.assertEqual((a.status, a.sid, a.step_done, a.token), ("ok", 9, True, "tok"))

    def test_round_trip_with_runner(self):
        # An item produced by run_subprocess decodes to a completed step.
        q = _queue.Queue()
        run_subprocess(q, Job(1, "script", 1, None, "t", "job:1", "g"),
                       [sys.executable, "-c", "pass"], "t", 1)
        done = [decode_output_item(it) for it in list(q.queue) if it[0] == "done_tag"][0]
        self.assertTrue(done.step_done)
        self.assertEqual(done.status, "ok")


from ryos.job_controller import JobController  # noqa: E402


class _FakeDB:
    """Records mark_run_status calls so pump() can be tested without SQLite."""

    def __init__(self):
        self.marked = []

    def mark_run_status(self, sid, status):
        self.marked.append((sid, status))


class TestJobController(unittest.TestCase):
    """Pipeline sequencing, step completion, and the drain loop (pump).

    The controller is UI-free: it reaches the window only via injected
    callbacks, so it is exercised here without any Tk display.
    """

    def setUp(self):
        self.rec = {
            "output": [], "status": [], "notify": [],
            "finish": [], "rename": [], "launch": [], "started": [],
        }
        self.q = _queue.Queue()
        self.reg = JobRegistry()
        self.db = _FakeDB()
        self.ctl = JobController(
            self.reg, self.q, self.db,
            on_output=lambda tab, text, tag=None: self.rec["output"].append((tab, text, tag)),
            on_status=lambda text: self.rec["status"].append(text),
            on_notify=lambda title, body: self.rec["notify"].append((title, body)),
            on_started=lambda job: self.rec["started"].append(job.job_id),
            on_finish=lambda job: self.rec["finish"].append(job.job_id),
            on_rename=lambda job: self.rec["rename"].append(job.name),
            launch=lambda job, cmd, name, sid, token=None: self.rec["launch"].append((cmd, name, sid, token)),
            now=lambda: _dt(2020, 1, 1, 12, 0, 0),
        )
        self._tmp = tempfile.NamedTemporaryFile(suffix=".py", delete=False)
        self._tmp.write(b"print('hi')\n")
        self._tmp.close()

    def tearDown(self):
        os.unlink(self._tmp.name)

    def _step(self, sid=1, name="s1", params="", override=None, trigger_mode=TRIGGER_AFTER):
        return (sid, sid, name, self._tmp.name, params, "", override, trigger_mode)

    def _job(self, kind="script", queue=None, total=0):
        job = Job(1, kind, 1, None, "n", "job:1", "g",
                  pipeline_name="P", pipeline_queue=queue, pipeline_total=total)
        job.start_time = _dt(2020, 1, 1, 12, 0, 0)
        return job

    def test_script_ok_finishes_and_notifies(self):
        job = self._job("script")
        self.ctl.handle_step_done(job, 1, "ok")
        self.assertEqual(self.rec["status"], ["Done."])
        self.assertEqual(self.rec["finish"], [1])
        self.assertEqual(len(self.rec["notify"]), 1)
        self.assertIn("passed", self.rec["notify"][0][0])

    def test_script_error_finishes_and_notifies_failure(self):
        job = self._job("script")
        self.ctl.handle_step_done(job, 1, "error")
        self.assertEqual(self.rec["status"], ["Failed."])
        self.assertEqual(self.rec["finish"], [1])
        self.assertIn("failed", self.rec["notify"][0][0])

    def test_pipeline_ok_with_remaining_advances_not_finishes(self):
        job = self._job("pipeline", queue=[self._step(2, "s2")], total=2)
        self.ctl.handle_step_done(job, 1, "ok")
        self.assertEqual(len(self.rec["launch"]), 1)
        self.assertEqual(self.rec["launch"][0][2], 2)
        self.assertEqual(self.rec["finish"], [])
        self.assertEqual(self.rec["notify"], [])
        self.assertEqual(job.pipeline_step_idx, 1)

    def test_pipeline_ok_empty_queue_completes(self):
        job = self._job("pipeline", queue=[], total=1)
        self.ctl.handle_step_done(job, 1, "ok")
        self.assertEqual(self.rec["status"], ["Pipeline complete."])
        self.assertEqual(self.rec["finish"], [1])
        self.assertIn("Pipeline passed", self.rec["notify"][0][0])

    def test_pipeline_error_stops_and_clears_queue(self):
        job = self._job("pipeline", queue=[self._step(2, "s2")], total=2)
        job.pipeline_step_idx = 1
        self.ctl.handle_step_done(job, 1, "error")
        self.assertEqual(job.pipeline_queue, [])
        self.assertEqual(self.rec["finish"], [1])
        self.assertIn("Pipeline failed", self.rec["notify"][0][0])
        self.assertIn("step 1/2", self.rec["notify"][0][1])

    def test_run_next_advances_and_launches(self):
        job = self._job("pipeline", queue=[self._step(7, "build")], total=1)
        self.ctl.run_next_pipeline_step(job)
        self.assertEqual(job.pipeline_step_idx, 1)
        self.assertEqual(self.rec["launch"][0][2], 7)
        self.assertEqual(self.rec["rename"], [job.name])
        self.assertIn("Step 1/1", job.name)

    def test_run_next_noop_when_stopped(self):
        job = self._job("pipeline", queue=[self._step()], total=1)
        job.stopped = True
        self.ctl.run_next_pipeline_step(job)
        self.assertEqual(self.rec["launch"], [])

    def test_run_next_missing_file_posts_error_no_launch(self):
        bad = (1, 1, "gone", "/no/such/file.py", "", "", None, TRIGGER_AFTER)
        job = self._job("pipeline", queue=[bad], total=1)
        self.ctl.run_next_pipeline_step(job)
        self.assertEqual(self.rec["launch"], [])
        kinds = [self.q.get_nowait()[0] for _ in range(self.q.qsize())]
        self.assertIn("stderr", kinds)
        self.assertIn("done", kinds)

    def test_run_next_param_override_applied(self):
        job = self._job("pipeline", queue=[self._step(3, "s", params="orig", override="NEW")],
                        total=1)
        self.ctl.run_next_pipeline_step(job)
        cmd = self.rec["launch"][0][0].cmd
        self.assertIn("NEW", cmd)
        self.assertNotIn("orig", cmd)

    def test_pump_appends_stdout_text(self):
        job = self._job("script")
        self.reg.add(job)
        self.q.put(("stdout", job.job_id, "hello\n"))
        self.ctl.pump()
        self.assertEqual(self.rec["output"], [(job.tab_key, "hello\n", None)])
        self.assertEqual(self.db.marked, [])

    def test_pump_done_tag_persists_status_and_dispatches(self):
        job = self._job("script")
        self.reg.add(job)
        self.q.put(("done_tag", job.job_id, 5, "ok", "ok", "footer"))
        self.ctl.pump()
        self.assertEqual(self.db.marked, [(5, "ok")])
        self.assertEqual(self.rec["status"], ["Done."])
        self.assertEqual(self.rec["finish"], [job.job_id])

    def test_pump_empty_queue_is_noop(self):
        self.ctl.pump()
        self.assertEqual(self.rec["output"], [])
        self.assertEqual(self.db.marked, [])

    def test_pump_persists_status_even_without_registered_job(self):
        self.q.put(("done_tag", 999, 7, "error", "error", "f"))
        self.ctl.pump()
        self.assertEqual(self.db.marked, [(7, "error")])
        self.assertEqual(self.rec["finish"], [])

    def test_pump_drains_multiple_items_in_order(self):
        job = self._job("script")
        self.reg.add(job)
        self.q.put(("stdout", job.job_id, "a\n"))
        self.q.put(("stdout", job.job_id, "b\n"))
        self.ctl.pump()
        self.assertEqual([t[1] for t in self.rec["output"]], ["a\n", "b\n"])

    # --- new_job allocation + capacity ---

    def test_new_job_registers_and_fires_started(self):
        job = self.ctl.new_job("script", 1, None, "n", "g")
        self.assertEqual(job.tab_key, "job:1")
        self.assertIs(self.reg.get(job.job_id), job)
        self.assertEqual(self.rec["started"], [job.job_id])

    def test_new_job_sets_pipeline_fields(self):
        steps = [self._step(2, "s2")]
        job = self.ctl.new_job("pipeline", None, 9, "P", "g",
                               pipeline_name="P", pipeline_queue=steps, pipeline_total=1)
        self.assertEqual(job.kind, "pipeline")
        self.assertEqual(job.pipeline_total, 1)
        self.assertEqual(job.pipeline_queue, steps)

    def test_new_job_allocates_monotonic_ids(self):
        a = self.ctl.new_job("script", 1, None, "a", "g")
        b = self.ctl.new_job("script", 2, None, "b", "g")
        self.assertNotEqual(a.job_id, b.job_id)
        self.assertEqual(self.rec["started"], [a.job_id, b.job_id])

    def test_at_capacity(self):
        self.assertFalse(self.ctl.at_capacity(0))   # 0 == unlimited
        self.assertFalse(self.ctl.at_capacity(2))
        self.ctl.new_job("script", 1, None, "a", "g")
        self.ctl.new_job("script", 2, None, "b", "g")
        self.assertTrue(self.ctl.at_capacity(2))
        self.assertFalse(self.ctl.at_capacity(0))   # still unlimited
        self.assertFalse(self.ctl.at_capacity(3))

    # --- concurrent ("with previous") groups ---

    def test_group_detection_absorbs_consecutive_with_steps(self):
        # Leader (a, its own mode irrelevant) + b,c marked "with" form one
        # group; d (mode "after") stays queued for the next call.
        queue = [
            self._step(1, "a"),
            self._step(2, "b", trigger_mode=TRIGGER_WITH),
            self._step(3, "c", trigger_mode=TRIGGER_WITH),
            self._step(4, "d", trigger_mode=TRIGGER_AFTER),
        ]
        job = self._job("pipeline", queue=queue, total=4)
        self.ctl.run_next_pipeline_step(job)
        self.assertEqual(job.group_size, 3)
        self.assertEqual(len(self.rec["launch"]), 3)
        self.assertEqual(len(job.pipeline_queue), 1)
        self.assertEqual(job.pipeline_queue[0][2], "d")

    def test_group_launch_failure_does_not_block_siblings(self):
        # One member's launch failure (missing file) must not stop the other
        # concurrent-group members from still launching -- `continue`, not
        # `return`, in the per-member launch loop.
        bad = (1, 1, "gone", "/no/such/file.py", "", "", None, TRIGGER_AFTER)
        good = self._step(2, "b", trigger_mode=TRIGGER_WITH)
        job = self._job("pipeline", queue=[bad, good], total=2)
        self.ctl.run_next_pipeline_step(job)
        self.assertEqual(job.group_size, 2)
        self.assertEqual(len(self.rec["launch"]), 1)
        self.assertEqual(self.rec["launch"][0][2], 2)  # sid of the good sibling, still launched

    def test_group_advances_only_after_last_member_done(self):
        queue = [self._step(1, "a"), self._step(2, "b", trigger_mode=TRIGGER_WITH),
                 self._step(3, "c")]
        job = self._job("pipeline", queue=queue, total=3)
        self.ctl.run_next_pipeline_step(job)
        self.assertEqual(len(self.rec["launch"]), 2)   # group of 2 launched together

        # First member finishes: the group must NOT advance while b is pending.
        self.ctl.handle_step_done(job, 1, "ok", token=1)
        self.assertEqual(len(self.rec["launch"]), 2)
        self.assertEqual(self.rec["finish"], [])

        # Last member finishes: only now does the pipeline advance to step c.
        self.ctl.handle_step_done(job, 2, "ok", token=2)
        self.assertEqual(len(self.rec["launch"]), 3)
        self.assertEqual(self.rec["launch"][2][2], 3)  # sid of step c
        self.assertEqual(self.rec["finish"], [])

    def test_group_mid_failure_waits_for_sibling_without_terminating_it(self):
        queue = [self._step(1, "a"), self._step(2, "b", trigger_mode=TRIGGER_WITH)]
        job = self._job("pipeline", queue=queue, total=2)
        self.ctl.run_next_pipeline_step(job)

        # a fails while b is still running: pipeline must not advance/finish,
        # and b's token must remain pending (the controller never terminates
        # siblings — that's the app layer's job, but it must not even try by
        # treating the group as settled early).
        self.ctl.handle_step_done(job, 1, "error", token=1)
        self.assertEqual(self.rec["finish"], [])
        self.assertEqual(self.rec["notify"], [])
        self.assertIn(2, job.group_pending)
        self.assertTrue(job.group_failed)
        self.assertEqual(job.group_failed_at, 1)

    def test_group_settles_failed_when_last_sibling_succeeds(self):
        queue = [self._step(1, "a"), self._step(2, "b", trigger_mode=TRIGGER_WITH)]
        job = self._job("pipeline", queue=queue, total=2)
        self.ctl.run_next_pipeline_step(job)
        self.ctl.handle_step_done(job, 1, "error", token=1)  # a fails first
        self.ctl.handle_step_done(job, 2, "ok", token=2)     # b succeeds last

        # The group as a whole is a failure even though the last-reporting
        # member succeeded, and the pipeline stops instead of advancing.
        self.assertEqual(job.pipeline_queue, [])
        self.assertEqual(self.rec["finish"], [job.job_id])
        self.assertIn("Pipeline failed", self.rec["notify"][0][0])

    def test_group_failure_notification_names_actual_failing_step(self):
        # Token 1 (step 1) fails; token 2 (step 2, launched in the same
        # group) is the one whose "done" happens to settle the group. The
        # notification must still name step 1 as the failure, not step 2.
        queue = [self._step(1, "a"), self._step(2, "b", trigger_mode=TRIGGER_WITH)]
        job = self._job("pipeline", queue=queue, total=2)
        self.ctl.run_next_pipeline_step(job)
        self.ctl.handle_step_done(job, 1, "error", token=1)
        self.ctl.handle_step_done(job, 2, "ok", token=2)
        self.assertIn("step 1/2", self.rec["notify"][0][1])

    def test_single_step_group_is_unaffected(self):
        # Group size 1 must behave exactly like the pre-existing sequential
        # path: byte-identical header/status text and no group interception.
        job = self._job("pipeline", queue=[self._step(7, "build")], total=1)
        self.ctl.run_next_pipeline_step(job)
        self.assertEqual(job.group_size, 1)
        self.assertEqual(self.rec["output"][0][1], f"{'─' * 40}\nStep 1/1:  build\n{'─' * 40}\n")
        self.assertEqual(self.rec["status"], ["Pipeline step 1/1: build"])


class TestSourceIntegrity(unittest.TestCase):
    """Guard shipped source against corruption and bad merges.

    Catches the failure modes that actually bite this repo: NUL bytes or
    truncation from a flaky filesystem, non-UTF-8 bytes, and leftover merge
    conflict markers. Pure and fast, so it runs headless in CI.
    """

    _ROOT = Path(__file__).resolve().parents[1]
    _CONFLICT = ("<<<<<<< ", ">>>>>>> ", "||||||| ")

    def _py_files(self):
        files = sorted((self._ROOT / "ryos").rglob("*.py"))
        files += [self._ROOT / "tests" / "test_ryos.py",
                  self._ROOT / "tests" / "gui_smoke.py"]
        return [p for p in files if "__pycache__" not in p.parts and p.exists()]

    def test_files_found(self):
        # Sanity: the walk actually discovers the package (guards against a
        # silently-empty scan making the other checks vacuously pass).
        self.assertGreater(len(self._py_files()), 5)

    def test_no_nul_bytes(self):
        for p in self._py_files():
            self.assertNotIn(b"\x00", p.read_bytes(), f"NUL byte found in {p}")

    def test_valid_utf8(self):
        for p in self._py_files():
            try:
                p.read_bytes().decode("utf-8")
            except UnicodeDecodeError as e:
                self.fail(f"{p} is not valid UTF-8: {e}")

    def test_no_merge_conflict_markers(self):
        for p in self._py_files():
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                for marker in self._CONFLICT:
                    self.assertFalse(
                        line.startswith(marker),
                        f"merge conflict marker at {p}:{n}",
                    )


from ryos.search import HintLink, SearchHint, compute_hint, matches, normalize_query  # noqa: E402


class TestSearchNormalizeAndMatch(unittest.TestCase):
    def test_placeholder_is_no_query(self):
        self.assertEqual(normalize_query("Search…", True), "")

    def test_normalize_lowercases_and_strips(self):
        self.assertEqual(normalize_query("  Deploy ", False), "deploy")

    def test_matches_empty_query_is_true(self):
        self.assertTrue(matches("anything", ""))

    def test_matches_is_case_insensitive_substring(self):
        self.assertTrue(matches("Deploy Prod", "prod"))
        self.assertFalse(matches("Deploy Prod", "stage"))


class TestComputeHint(unittest.TestCase):
    def test_no_query_returns_none(self):
        self.assertIsNone(compute_hint("", "A", [("A", 1)]))

    def test_no_active_group_returns_none(self):
        self.assertIsNone(compute_hint("x", None, [("A", 1)]))

    def test_dismissed_query_returns_none(self):
        self.assertIsNone(compute_hint("x", "A", [("B", 1)], dismissed="x"))

    def test_active_group_has_match_returns_none(self):
        self.assertIsNone(compute_hint("x", "A", [("A", 2), ("B", 1)]))

    def test_no_other_group_matches_returns_none(self):
        self.assertIsNone(compute_hint("x", "A", []))

    def test_other_groups_produce_links(self):
        hint = compute_hint("x", "A", [("B", 3), ("C", 1)])
        self.assertIsInstance(hint, SearchHint)
        self.assertEqual(hint.links,
                         [HintLink("B", "B", 3), HintLink("C", "C", 1)])

    def test_unnamed_group_maps_to_other_label_and_none_target(self):
        hint = compute_hint("x", "A", [("", 2)])
        self.assertEqual(hint.links, [HintLink("Other", None, 2)])


# ---------------------------------------------------------------------------
# Search filter — real-Tk pack-visibility integration test.
#
# The rest of this module runs headless with tkinter mocked (see the top of
# the file), which cannot exercise real pack()/pack_forget()/winfo_manager().
# This test therefore runs the reproduction in a *subprocess* with a fresh,
# unmocked interpreter so real widgets are created. It builds real ScriptCards
# plus an empty-favorites section whose only child is an empty-state placeholder
# label, then drives the real RYOSApp._apply_search_filter /
# _update_section_visibility bound methods and asserts pack visibility.
#
# Regression target: cards/placeholders are selected with hasattr(c, "_name"),
# but EVERY Tk widget has an internal "_name" (its widget path, e.g. "!label"),
# so empty-state placeholder labels are wrongly treated as cards and matched by
# substring against that path name. As a result an empty section's placeholder
# and header flip visibility depending on whether the query text happens to be a
# substring of "!label" (e.g. "la", "e", "l" keep them; "deploy"/"zzqzz" hide
# them). The fix identifies cards by isinstance(ScriptCard/PipelineCard).
# ---------------------------------------------------------------------------

_SEARCH_FILTER_DRIVER = r'''
import sys, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[1])
try:
    import tkinter as tk
    _probe = tk.Tk(); _probe.destroy()
except Exception:
    sys.exit(77)   # no display / Tk unavailable -> caller skips

import ryos.ui.app as appmod
from ryos.db import ScriptDB

tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
seed = ScriptDB(Path(tmp.name))
seed.create_group("Alpha")
seed.create_group("Beta")
seed.add("Deploy Prod", "deploy.py", "", "", "Alpha")  # matches "deploy"
seed.add("Runner",      "run.py",    "", "", "Beta")   # does NOT match "deploy"/"la"

appmod.ScriptDB = lambda *a, **k: ScriptDB(Path(tmp.name))
_real_load = appmod._load_settings
appmod._load_settings = lambda: {**_real_load(), "auto_check_update": False,
                                 "start_minimized": False, "remember_last_group": False}

app = appmod.RYOSApp()
app.withdraw()
app._active_group = None          # "All" view: every group is rendered
app._refresh_cards()
app.update()

def run_query(text):
    app._search_ph[0] = False
    app._search_var.set(text)
    app.update_idletasks()

def wrapper_visible(gname):
    for w in app._group_wrappers:
        if getattr(w, "_grp_name", None) == gname:
            return w.winfo_manager() == "pack"
    return None

def visible_script_names():
    return sorted(c._name for c in app._cards if c.winfo_manager() == "pack")

ok = True

# 1) Real cards + their group blocks filter live: query "deploy" keeps only the
#    Alpha group (and its Deploy Prod card); Beta must hide entirely.
run_query("deploy")
if visible_script_names() != ["Deploy Prod"]:
    ok = False
if wrapper_visible("Alpha") is not True or wrapper_visible("Beta") is not False:
    ok = False

# 2) Regression: "la" matches no real card. Beta must STILL hide. The bug is that
#    "la" is a substring of the internal Tk widget name "!label" of the empty
#    Favorites/Pipelines placeholder labels, which are mis-detected as cards, so
#    Beta's group block wrongly stays visible.
run_query("la")
if visible_script_names() != []:
    ok = False
if wrapper_visible("Alpha") is not False or wrapper_visible("Beta") is not False:
    ok = False

app.destroy()
sys.exit(0 if ok else 1)
'''


class TestSearchFilterRefreshRealTk(unittest.TestCase):
    """Real-Tk pack-visibility of the search filter, run in a subprocess so the
    module-level tkinter mock does not apply. Skips when Tk cannot initialise."""

    def test_non_matching_group_hides_regardless_of_query_text(self):
        repo_root = str(Path(__file__).resolve().parents[1])
        proc = subprocess.run(
            [sys.executable, "-c", _SEARCH_FILTER_DRIVER, repo_root],
            capture_output=True, text=True,
        )
        if proc.returncode == 77:
            self.skipTest("Tk not available for real-widget test")
        self.assertEqual(
            proc.returncode, 0,
            msg=("search filter mis-detects empty-state placeholder labels as "
                 "cards (hasattr(_name)); a group with no real match stays "
                 f"visible for queries like 'la'. stdout={proc.stdout!r} "
                 f"stderr={proc.stderr!r}"),
        )


from ryos.dragdrop import compute_insertion, first_rect_at  # noqa: E402


class TestComputeInsertion(unittest.TestCase):
    # ids 10/20/30 at tops 0/20/40, height 20 -> mids 10/30/50.
    CARDS = [(10, 0, 20), (20, 20, 20), (30, 40, 20)]

    def test_empty_returns_none_none(self):
        self.assertEqual(compute_insertion(5, []), (None, None))

    def test_drop_above_first_mid_lands_before_first(self):
        self.assertEqual(compute_insertion(5, self.CARDS), (10, 0))

    def test_boundary_at_mid_is_inclusive(self):
        self.assertEqual(compute_insertion(10, self.CARDS), (10, 0))

    def test_drop_in_middle_lands_before_that_card(self):
        self.assertEqual(compute_insertion(25, self.CARDS), (20, 20))

    def test_drop_below_all_mids_appends(self):
        self.assertEqual(compute_insertion(100, self.CARDS), (None, 60))


class TestFirstRectAt(unittest.TestCase):
    RECTS = [("a", 0, 0, 10, 10), ("b", 20, 0, 10, 10)]

    def test_point_inside_returns_key(self):
        self.assertEqual(first_rect_at(5, 5, self.RECTS), "a")
        self.assertEqual(first_rect_at(25, 5, self.RECTS), "b")

    def test_point_in_gap_returns_none(self):
        self.assertIsNone(first_rect_at(15, 5, self.RECTS))

    def test_edge_is_inclusive(self):
        self.assertEqual(first_rect_at(0, 0, self.RECTS), "a")
        self.assertEqual(first_rect_at(10, 10, self.RECTS), "a")

    def test_first_match_wins_on_overlap(self):
        rects = [("a", 0, 0, 100, 100), ("b", 0, 0, 10, 10)]
        self.assertEqual(first_rect_at(5, 5, rects), "a")

    def test_empty_returns_none(self):
        self.assertIsNone(first_rect_at(5, 5, []))


from ryos.screens import center_in_work_area, geometry_origin  # noqa: E402


class TestGeometryOrigin(unittest.TestCase):
    def test_positive_origin(self):
        self.assertEqual(geometry_origin("540x640+100+200"), (100, 200))

    def test_negative_origin(self):
        self.assertEqual(geometry_origin("540x640+-1920+0"), (-1920, 0))

    def test_unparseable_returns_zero(self):
        self.assertEqual(geometry_origin(""), (0, 0))
        self.assertEqual(geometry_origin("garbage"), (0, 0))
        self.assertEqual(geometry_origin(None), (0, 0))


class TestCenterInWorkArea(unittest.TestCase):
    def test_centers_on_primary(self):
        self.assertEqual(center_in_work_area(540, 640, (0, 0, 1920, 1080)),
                         "540x640+690+220")

    def test_centers_in_offset_work_area(self):
        self.assertEqual(center_in_work_area(540, 640, (100, 50, 800, 600)),
                         "540x640+230+50")

    def test_window_larger_than_area_clamps_to_origin(self):
        self.assertEqual(center_in_work_area(2000, 2000, (10, 20, 800, 600)),
                         "2000x2000+10+20")


from ryos.grouping import bucket_by_group  # noqa: E402


class TestBucketByGroup(unittest.TestCase):
    @staticmethod
    def _key(r):
        return r[1]

    def test_named_groups_always_present_even_if_empty(self):
        self.assertEqual(bucket_by_group([], ["A", "B"], self._key),
                         {"A": [], "B": [], "": []})

    def test_ungrouped_key_always_present(self):
        self.assertEqual(bucket_by_group([], [], self._key), {"": []})

    def test_records_bucketed_and_order_preserved(self):
        recs = [(1, "A"), (2, ""), (3, "A"), (4, "B")]
        out = bucket_by_group(recs, ["A", "B"], self._key)
        self.assertEqual(out["A"], [(1, "A"), (3, "A")])
        self.assertEqual(out["B"], [(4, "B")])
        self.assertEqual(out[""], [(2, "")])

    def test_unknown_group_bucket_created_on_demand(self):
        out = bucket_by_group([(1, "Z")], ["A"], self._key)
        self.assertEqual(out["Z"], [(1, "Z")])
        self.assertEqual(out["A"], [])


class TestScriptDBDetached(unittest.TestCase):
    """The per-script 'launcher' (detached) flag: add/update/is_detached."""

    def setUp(self):
        self.db = _make_db()

    def test_default_is_not_detached(self):
        sid = self.db.add("s", "/tmp/s.py", "", "")
        self.assertFalse(self.db.is_detached(sid))

    def test_add_detached(self):
        sid = self.db.add("s", "/tmp/s.py", "", "", detached=1)
        self.assertTrue(self.db.is_detached(sid))

    def test_update_sets_and_clears_detached(self):
        sid = self.db.add("s", "/tmp/s.py", "", "")
        self.db.update(sid, "s", "/tmp/s.py", "", "", detached=1)
        self.assertTrue(self.db.is_detached(sid))
        self.db.update(sid, "s", "/tmp/s.py", "", "", detached=0)
        self.assertFalse(self.db.is_detached(sid))

    def test_update_none_leaves_detached_untouched(self):
        sid = self.db.add("s", "/tmp/s.py", "", "", detached=1)
        # A plain edit (no detached arg) must not clear the flag.
        self.db.update(sid, "renamed", "/tmp/s.py", "", "")
        self.assertTrue(self.db.is_detached(sid))

    def test_is_detached_unknown_script_is_false(self):
        self.assertFalse(self.db.is_detached(9999))


# ---------------------------------------------------------------------------
# Per-item highlight colours (card label tint)
# ---------------------------------------------------------------------------
from ryos.ui.theme import (  # noqa: E402
    HIGHLIGHT_LABELS, HIGHLIGHT_MIN_RATIO, HIGHLIGHT_SEEDS, highlight_fg,
)


class TestLabelColorDB(unittest.TestCase):
    """label_color is an optional palette key, defaulting to NULL everywhere."""

    def setUp(self):
        self.db = _make_db()
        self.sid = self.db.add("s", "/tmp/s.py", "", "", "G")
        self.pid = self.db.create_pipeline("P", "G")

    def _script_row(self):
        return [r for r in self.db.list_all() if r[0] == self.sid][0]

    def test_script_default_is_none(self):
        self.assertIsNone(self._script_row()[11])

    def test_pipeline_default_is_none(self):
        self.assertIsNone(self.db.list_pipelines("G")[0][3])

    def test_set_and_read_script_color(self):
        self.db.set_script_color(self.sid, "teal")
        self.assertEqual(self._script_row()[11], "teal")

    def test_set_and_read_pipeline_color(self):
        self.db.set_pipeline_color(self.pid, "purple")
        self.assertEqual(self.db.list_pipelines("G")[0][3], "purple")

    def test_clear_script_color(self):
        self.db.set_script_color(self.sid, "red")
        self.db.set_script_color(self.sid, None)
        self.assertIsNone(self._script_row()[11])

    def test_empty_string_is_stored_as_null(self):
        # "" and NULL must not both mean "no highlight" in the database, or
        # every read site would need to normalise it.
        self.db.set_script_color(self.sid, "")
        self.db.set_pipeline_color(self.pid, "")
        self.assertIsNone(self._script_row()[11])
        self.assertIsNone(self.db.list_pipelines("G")[0][3])

    def test_color_does_not_disturb_earlier_columns(self):
        # The column is appended, so existing index-based readers are unmoved.
        before = self._script_row()[:11]
        self.db.set_script_color(self.sid, "green")
        self.assertEqual(self._script_row()[:11], before)

    def test_setting_unknown_id_is_a_noop(self):
        self.db.set_script_color(99999, "red")
        self.db.set_pipeline_color(99999, "red")
        self.assertIsNone(self._script_row()[11])


class TestHighlightPalette(unittest.TestCase):
    """Every highlight seed must stay readable on every shipped palette.

    The seeds are deliberately *not* final colours: highlight_fg shades them
    until they clear AA, so this is the test that certifies the shading
    actually converges rather than silently returning an unreadable value.
    """

    @classmethod
    def setUpClass(cls):
        cls.palettes = dict(BUILTIN_THEMES)
        gallery = Path(__file__).resolve().parents[1] / "theme-gallery"
        for fp in sorted(gallery.glob("*.json")):
            _name, seed = import_theme(fp)
            cls.palettes[fp.stem] = build_palette(seed)

    def test_gallery_palettes_were_loaded(self):
        # Guards against the loop below passing vacuously if the gallery moves.
        self.assertGreater(len(self.palettes), len(BUILTIN_THEMES))

    def test_seeds_clear_aa_on_card_surfaces(self):
        for theme, P in self.palettes.items():
            for key in HIGHLIGHT_SEEDS:
                with self.subTest(theme=theme, color=key):
                    fg = highlight_fg(key, P["card_bg"], P["card_hover"])
                    for surface in ("card_bg", "card_hover"):
                        self.assertGreaterEqual(
                            contrast_ratio(fg, P[surface]), HIGHLIGHT_MIN_RATIO,
                            f"{key} on {theme}.{surface}")

    def test_seeds_clear_aa_on_menu_surface(self):
        # The context-menu swatches are drawn on menu_bg, not on a card.
        for theme, P in self.palettes.items():
            for key in HIGHLIGHT_SEEDS:
                with self.subTest(theme=theme, color=key):
                    fg = highlight_fg(key, P["menu_bg"])
                    self.assertGreaterEqual(
                        contrast_ratio(fg, P["menu_bg"]), HIGHLIGHT_MIN_RATIO,
                        f"{key} on {theme}.menu_bg")

    def test_unset_returns_none(self):
        self.assertIsNone(highlight_fg(None))
        self.assertIsNone(highlight_fg(""))

    def test_unknown_key_returns_none(self):
        # A key written by a future/other build must fall back to the normal
        # label colour, never render as an invalid Tk colour.
        self.assertIsNone(highlight_fg("chartreuse"))

    def test_labels_cover_every_seed(self):
        self.assertEqual(set(HIGHLIGHT_LABELS), set(HIGHLIGHT_SEEDS))

    def test_seeds_are_valid_hex(self):
        for key, value in HIGHLIGHT_SEEDS.items():
            with self.subTest(color=key):
                self.assertTrue(is_hex_color(value))

    def test_result_tracks_the_surface_not_a_stale_cache(self):
        # The cache is keyed by surface, so switching theme must re-resolve.
        light = highlight_fg("red", BUILTIN_THEMES["light"]["card_bg"])
        dark = highlight_fg("red", BUILTIN_THEMES["dark"]["card_bg"])
        self.assertNotEqual(light, dark)

    def test_seeds_stay_distinguishable_from_each_other(self):
        # A palette that collapsed to seven near-identical pastels would still
        # pass the contrast tests but be useless for telling cards apart.
        for theme, P in self.palettes.items():
            resolved = [highlight_fg(k, P["card_bg"], P["card_hover"])
                        for k in HIGHLIGHT_SEEDS]
            with self.subTest(theme=theme):
                self.assertEqual(len(set(resolved)), len(HIGHLIGHT_SEEDS))


# ---------------------------------------------------------------------------
# Tray status (live tooltip + running-job menu)
# ---------------------------------------------------------------------------
import ryos.tray as tray_mod  # noqa: E402
from ryos.tray import MENU_LABEL_MAX, TIP_MAX, TrayIcon, _ellipsize, tray_title  # noqa: E402


class _StubPystray:
    """Minimal stand-in for the pystray module.

    CI installs no project dependencies, so pystray is genuinely absent there.
    Without this stub _build_menu() raises, TrayIcon's best-effort guard
    swallows it, and every menu assertion below quietly passes on a developer
    machine while failing on a clean runner. Stubbing makes the menu path
    exercise the same code everywhere; TestTrayWithoutPystray covers the
    absent-package behaviour explicitly.
    """

    class Menu:
        SEPARATOR = "---"

        def __init__(self, *items):
            self.items = list(items)

        def __iter__(self):
            return iter(self.items)

    class MenuItem:
        def __init__(self, text, action=None, default=False):
            self.text = text
            self.action = action
            self.default = default


class TestTrayTitle(unittest.TestCase):
    """The tooltip must always fit NOTIFYICONDATAW.szTip (WCHAR[128]).

    ctypes raises on an over-long assignment rather than truncating, so a
    tooltip that overflows would not be a cosmetic bug -- the update would
    fail outright.
    """

    BASE = "RYOS v9.9.9"

    def test_idle_is_just_the_base_title(self):
        self.assertEqual(tray_title([], self.BASE), self.BASE)

    def test_single_job_shows_its_full_label(self):
        title = tray_title(["⚡ Deploy — Step 2/5: build"], self.BASE)
        self.assertIn("Step 2/5: build", title)
        self.assertTrue(title.startswith(self.BASE))

    def test_several_jobs_collapse_to_a_count(self):
        title = tray_title(["a", "b", "c"], self.BASE)
        self.assertIn("3 running", title)
        self.assertIn("a, b, c", title)

    def test_long_label_is_clamped(self):
        title = tray_title(["X" * 500], self.BASE)
        self.assertLessEqual(len(title), TIP_MAX)
        self.assertTrue(title.endswith("…"))

    def test_many_jobs_are_clamped(self):
        title = tray_title([f"job-number-{i}" for i in range(50)], self.BASE)
        self.assertLessEqual(len(title), TIP_MAX)

    def test_absurd_base_is_clamped(self):
        # Even with no jobs at all the base has to survive the cap.
        self.assertLessEqual(len(tray_title([], "R" * 500)), TIP_MAX)

    def test_newlines_do_not_leak_into_the_tooltip(self):
        # A tooltip is single-line; an embedded newline would render as a box.
        title = tray_title(["one" + chr(10) + "two" + chr(9) + "three"], self.BASE)
        self.assertNotIn(chr(10), title)
        self.assertNotIn(chr(9), title)

    def test_ellipsize_leaves_short_text_alone(self):
        self.assertEqual(_ellipsize("short", 20), "short")

    def test_ellipsize_never_exceeds_the_limit(self):
        for n in range(1, 40):
            with self.subTest(n=n):
                self.assertLessEqual(len(_ellipsize("y" * 100, n)), n)


class _FakeIcon:
    """Stands in for pystray.Icon: records what the tray pushes at it."""

    def __init__(self):
        self.title = None
        self.menu = None
        self.menu_writes = 0
        self.title_writes = 0

    def __setattr__(self, name, value):
        if name == "title" and "title" in self.__dict__:
            self.__dict__["title_writes"] += 1
        if name == "menu" and "menu" in self.__dict__:
            self.__dict__["menu_writes"] += 1
        self.__dict__[name] = value


class TestTrayJobSnapshot(unittest.TestCase):
    """set_jobs() is the only thing that crosses the UI/pystray boundary."""

    def setUp(self):
        patcher = mock.patch.object(tray_mod, "pystray", _StubPystray)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tray = TrayIcon(on_show=lambda: None, on_exit=lambda: None,
                             icon_path=Path("icon.ico"), title="RYOS v9.9.9",
                             on_job=lambda jid: self.clicked.append(jid))
        self.clicked = []
        self.icon = _FakeIcon()
        self.tray._icon = self.icon

    def test_menu_lists_jobs_above_the_standing_entries(self):
        # Guards the stub itself: if the menu never gets built, the write
        # assertions elsewhere in this class would pass vacuously.
        self.tray.set_jobs([(1, "build"), (2, "test")])
        labels = [getattr(i, "text", i) for i in self.icon.menu]
        self.assertEqual(labels[:2], ["build", "test"])
        self.assertIn("Show RYOS", labels)
        self.assertIn("Exit", labels)

    def test_first_snapshot_updates_tooltip_and_menu(self):
        self.tray.set_jobs([(1, "build")])
        self.assertIn("build", self.icon.title)
        self.assertEqual(self.icon.menu_writes, 1)

    def test_identical_snapshot_is_skipped(self):
        # Pipelines re-push on every step; an unchanged label must not turn
        # into a stream of Win32 calls.
        self.tray.set_jobs([(1, "build")])
        before = (self.icon.menu_writes, self.icon.title_writes)
        self.tray.set_jobs([(1, "build")])
        self.tray.set_jobs([(1, "build")])
        self.assertEqual((self.icon.menu_writes, self.icon.title_writes), before)

    def test_changed_label_updates_again(self):
        self.tray.set_jobs([(1, "Step 1/3")])
        self.tray.set_jobs([(1, "Step 2/3")])
        self.assertIn("Step 2/3", self.icon.title)

    def test_clearing_jobs_restores_the_idle_title(self):
        self.tray.set_jobs([(1, "build")])
        self.tray.set_jobs([])
        self.assertEqual(self.icon.title, "RYOS v9.9.9")

    def test_snapshot_is_copied_not_aliased(self):
        # The UI thread keeps mutating its own lists; the tray must not see it.
        live = [(1, "build")]
        self.tray.set_jobs(live)
        live.append((2, "test"))
        self.assertEqual(self.tray._jobs, [(1, "build")])

    def test_job_handler_reports_the_right_id(self):
        self.tray.set_jobs([(7, "build"), (9, "test")])
        self.tray._job_handler(9)()
        self.assertEqual(self.clicked, [9])

    def test_menu_refresh_failure_is_swallowed(self):
        # The tray is best-effort: a pystray error must never reach the UI.
        class _Boom(_FakeIcon):
            def __setattr__(self, name, value):
                if name == "menu" and "menu" in self.__dict__:
                    raise RuntimeError("pystray exploded")
                super().__setattr__(name, value)
        self.tray._icon = _Boom()
        self.tray.set_jobs([(1, "build")])   # must not raise

    def test_set_jobs_without_a_started_icon_is_safe(self):
        self.tray._icon = None
        self.tray.set_jobs([(1, "build")])
        self.assertEqual(self.tray._jobs, [(1, "build")])

    def test_stop_resets_the_snapshot(self):
        self.tray.set_jobs([(1, "build")])
        self.tray._icon = None              # mimic an already-stopped icon
        self.tray.stop()
        self.assertEqual(self.tray._jobs, [])
        self.assertEqual(self.tray._title, "RYOS v9.9.9")


class TestTrayMenuLabels(unittest.TestCase):
    """Menu entries are built from the snapshot, not from live Job objects."""

    def test_long_job_labels_are_clamped(self):
        self.assertLessEqual(len(_ellipsize("Z" * 300, MENU_LABEL_MAX)),
                             MENU_LABEL_MAX)


class TestTrayWithoutPystray(unittest.TestCase):
    """pystray is an optional dependency; nothing may break when it is absent.

    This is the environment CI actually runs in -- no project dependencies are
    installed -- so the degraded path deserves to be pinned rather than left to
    a swallowed exception nobody sees.
    """

    def setUp(self):
        for attr, value in (("pystray", None), ("_AVAILABLE", False)):
            patcher = mock.patch.object(tray_mod, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.tray = TrayIcon(on_show=lambda: None, on_exit=lambda: None,
                             icon_path=Path("icon.ico"), title="RYOS v9.9.9")

    def test_not_available(self):
        self.assertFalse(self.tray.available)

    def test_start_is_a_noop(self):
        self.tray.start()
        self.assertIsNone(self.tray._icon)

    def test_set_jobs_does_not_raise(self):
        self.tray.set_jobs([(1, "build")])
        self.assertEqual(self.tray._jobs, [(1, "build")])

    def test_tooltip_is_still_computed(self):
        # The tooltip needs no pystray, so the snapshot stays correct even
        # when the menu cannot be built.
        self.tray.set_jobs([(1, "build")])
        self.assertIn("build", self.tray._title)

    def test_stop_is_a_noop(self):
        self.tray.stop()
        self.assertEqual(self.tray._jobs, [])


# ---------------------------------------------------------------------------
# Multi-monitor popup / dialog placement
# ---------------------------------------------------------------------------
from ryos.screens import (  # noqa: E402
    anchored_position, center_on_rect, clamp_to_work_area,
)


class _MultiMonitor(unittest.TestCase):
    """Work areas for the layouts that actually break naive placement.

    BELOW reproduces the reported setup: a second monitor stacked underneath
    the primary, so every y beyond 1040 lies outside what Tk's
    winfo_screenheight() reports.
    """

    PRIMARY = (0, 0, 1920, 1040)
    RIGHT   = (1920, 0, 1920, 1040)
    LEFT    = (-1920, 0, 1920, 1040)     # negative origin: left of primary
    BELOW   = (0, 1080, 1536, 824)       # smaller monitor underneath


class TestClampToWorkArea(_MultiMonitor):

    def test_inside_is_untouched(self):
        self.assertEqual(clamp_to_work_area(100, 200, 400, 300, self.PRIMARY),
                         (100, 200))

    def test_overflow_right_is_pulled_back(self):
        x, _ = clamp_to_work_area(1800, 0, 400, 300, self.PRIMARY)
        self.assertEqual(x, 1920 - 400)

    def test_clamps_into_the_given_monitor_not_the_primary(self):
        # The whole bug in one assertion: a point on the lower monitor must
        # stay there rather than being dragged up onto the primary.
        _, y = clamp_to_work_area(0, 1900, 400, 300, self.BELOW)
        self.assertGreaterEqual(y, 1080)
        self.assertLessEqual(y + 300, 1080 + 824)

    def test_negative_coordinates_are_left_alone(self):
        # A max(0, ...) style clamp would drag this onto the primary monitor.
        x, _ = clamp_to_work_area(-1900, 100, 400, 300, self.LEFT)
        self.assertEqual(x, -1900)

    def test_overflow_past_a_negative_origin_clamps_to_that_origin(self):
        x, _ = clamp_to_work_area(-2000, 100, 400, 300, self.LEFT)
        self.assertEqual(x, -1920)

    def test_oversized_pins_to_origin(self):
        # Too big to fit: keep the top-left reachable rather than pushing the
        # title bar off the opposite edge.
        self.assertEqual(clamp_to_work_area(500, 500, 4000, 4000, self.BELOW),
                         (0, 1080))


class TestCenterOnRect(_MultiMonitor):

    def test_centers_on_the_parent(self):
        parent = (100, 100, 800, 600)
        self.assertEqual(center_on_rect(parent, 400, 300, self.PRIMARY),
                         (100 + 200, 100 + 150))

    def test_dialog_follows_its_parent_to_the_second_monitor(self):
        # The reported bug: opening a dialog from a window on the lower
        # monitor put the dialog on the primary one.
        parent = (200, 1200, 900, 700)
        _x, y = center_on_rect(parent, 440, 520, self.BELOW)
        self.assertGreaterEqual(y, 1080)

    def test_parent_near_an_edge_does_not_push_the_dialog_off(self):
        parent = (1800, 900, 400, 300)          # hanging off the bottom-right
        x, y = center_on_rect(parent, 600, 500, self.PRIMARY)
        self.assertLessEqual(x + 600, 1920)
        self.assertLessEqual(y + 500, 1040)

    def test_result_is_always_inside_the_work_area(self):
        for area in (self.PRIMARY, self.RIGHT, self.LEFT, self.BELOW):
            left, top, aw, ah = area
            for px in range(left, left + aw, 311):
                for py in range(top, top + ah, 211):
                    with self.subTest(area=area, px=px, py=py):
                        x, y = center_on_rect((px, py, 500, 400), 440, 520, area)
                        self.assertGreaterEqual(x, left)
                        self.assertGreaterEqual(y, top)
                        self.assertLessEqual(x + 440, left + aw)
                        self.assertLessEqual(y + 520, top + ah)


class TestAnchoredPosition(_MultiMonitor):

    def test_default_is_below_right_of_the_anchor(self):
        self.assertEqual(anchored_position(100, 100, 200, 150, self.PRIMARY, 12, 12),
                         (112, 112))

    def test_flips_instead_of_clamping_at_the_right_edge(self):
        # Clamping here would slide the popup back under the pointer, which
        # re-triggers <Leave> on the card and flickers it open/closed.
        x, _ = anchored_position(1900, 100, 200, 150, self.PRIMARY, 12, 12)
        self.assertLess(x + 200, 1900)

    def test_flips_at_the_bottom_edge(self):
        _, y = anchored_position(100, 1030, 200, 150, self.PRIMARY, 12, 12)
        self.assertLess(y + 150, 1030)

    def test_popup_on_the_lower_monitor_stays_there(self):
        # A naive min(y, screenheight - h) would land this on the primary.
        _, y = anchored_position(400, 1500, 200, 150, self.BELOW, 12, 12)
        self.assertGreaterEqual(y, 1080)

    def test_popup_on_a_negative_origin_monitor_stays_there(self):
        x, _ = anchored_position(-1000, 100, 200, 150, self.LEFT, 12, 12)
        self.assertLess(x + 200, 0)

    def test_never_leaves_the_work_area(self):
        for area in (self.PRIMARY, self.RIGHT, self.LEFT, self.BELOW):
            left, top, aw, ah = area
            for ax in range(left, left + aw, 197):
                for ay in range(top, top + ah, 143):
                    with self.subTest(area=area, ax=ax, ay=ay):
                        x, y = anchored_position(ax, ay, 260, 180, area, 16, 20)
                        self.assertGreaterEqual(x, left)
                        self.assertGreaterEqual(y, top)
                        self.assertLessEqual(x + 260, left + aw)
                        self.assertLessEqual(y + 180, top + ah)

    def test_oversized_popup_still_lands_on_the_right_monitor(self):
        x, y = anchored_position(400, 1500, 4000, 4000, self.BELOW, 12, 12)
        self.assertEqual((x, y), (0, 1080))


class TestPlacementCallSites(unittest.TestCase):
    """No placement path may go back to Tk's primary-monitor screen metrics.

    winfo_screenwidth()/winfo_screenheight() are what caused dialogs to open on
    the wrong display, so their few remaining uses are pinned here: an
    unreviewed new one should fail this test rather than ship the bug again.
    """

    ROOT = Path(__file__).resolve().parents[1] / "ryos"
    # file -> why this use is legitimate
    ALLOWED = {
        "ui/app.py": "provisional pre-settings size, refined by _apply_initial_placement",
        "ui/placement.py": "the documented non-Windows fallback",
        "ui/theme.py": "the documented non-Windows fallback in _apply_snap_corner",
    }

    def test_no_unreviewed_screen_metric_uses(self):
        offenders = {}
        for path in sorted(self.ROOT.rglob("*.py")):
            rel = path.relative_to(self.ROOT).as_posix()
            src = path.read_text(encoding="utf-8")
            if "winfo_screenwidth" in src or "winfo_screenheight" in src:
                if rel not in self.ALLOWED:
                    offenders[rel] = src.count("winfo_screen")
        self.assertEqual(offenders, {},
                         "use ryos.ui.placement instead of Tk screen metrics")

    def test_allowlist_has_no_stale_entries(self):
        for rel in self.ALLOWED:
            src = (self.ROOT / rel).read_text(encoding="utf-8")
            with self.subTest(file=rel):
                self.assertIn("winfo_screen", src)


# ---------------------------------------------------------------------------
# Export / import fidelity (payload v4)
# ---------------------------------------------------------------------------

class TestExportImportFidelity(unittest.TestCase):
    """Everything a script or step carries must survive a round trip.

    Before v4 the exporter wrote a pipeline step as {"script_path": ...} and
    nothing else, so params_override and trigger_mode were silently dropped --
    a pipeline with concurrent steps came back fully sequential. The per-script
    flags went the same way. These lock the whole payload down.
    """

    def _tmp_json(self) -> str:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            return f.name

    def _populated_db(self):
        """A group exercising every field the payload is supposed to carry."""
        db = _make_db()
        a = db.add("Alpha", "/alpha.py", "--a", "python", "G", temp_param=1)
        b = db.add("Beta", "/beta.js", "--b", "node", "G", detached=1)
        c = db.add("Gamma", "/gamma.ps1", "", "", "G")
        db.set_favorite_script(a, True)
        db.set_script_color(a, "teal")
        db.set_script_color(b, "purple")
        db.replace_param_presets(a, [("fast", "--fast"), ("slow", "--slow")])
        pid = db.create_pipeline("Deploy", "G")
        db.set_favorite_pipeline(pid, True)
        for sid in (a, b, c):
            db.add_pipeline_step(pid, sid)
        steps = db.list_pipeline_steps(pid)
        db.update_pipeline_step_params(steps[1][0], "--override")
        db.set_step_trigger_mode(steps[1][0], TRIGGER_WITH)
        return db, pid

    def _round_trip(self):
        src, pid = self._populated_db()
        path = self._tmp_json()
        src.export_to_file(path)
        dst = _make_db()
        dst.import_from_file(path)
        return src, dst, path

    # ---- scripts ----------------------------------------------------------

    def test_script_flags_survive(self):
        _src, dst, _ = self._round_trip()
        by_name = {r[1]: r for r in dst.list_all()}
        self.assertEqual(by_name["Alpha"][9], 1, "temp_param lost")
        self.assertEqual(by_name["Alpha"][10], 1, "is_favorite lost")
        self.assertEqual(by_name["Alpha"][11], "teal", "label_color lost")
        self.assertEqual(by_name["Beta"][11], "purple")

    def test_detached_survives(self):
        _src, dst, _ = self._round_trip()
        beta = next(r for r in dst.list_all() if r[1] == "Beta")
        self.assertTrue(dst.is_detached(beta[0]), "detached lost")

    def test_unset_colour_stays_none(self):
        _src, dst, _ = self._round_trip()
        gamma = next(r for r in dst.list_all() if r[1] == "Gamma")
        self.assertIsNone(gamma[11])

    def test_presets_still_survive(self):
        _src, dst, _ = self._round_trip()
        alpha = next(r for r in dst.list_all() if r[1] == "Alpha")
        self.assertEqual([p[2] for p in dst.list_param_presets(alpha[0])],
                         ["--fast", "--slow"])

    # ---- pipeline steps ---------------------------------------------------

    def test_step_trigger_mode_survives(self):
        # The headline regression: a concurrent step came back sequential.
        _src, dst, _ = self._round_trip()
        pid = dst.list_pipelines("G")[0][0]
        modes = [st[7] for st in dst.list_pipeline_steps(pid)]
        self.assertEqual(modes, [TRIGGER_AFTER, TRIGGER_WITH, TRIGGER_AFTER])

    def test_step_params_override_survives(self):
        _src, dst, _ = self._round_trip()
        pid = dst.list_pipelines("G")[0][0]
        overrides = [st[6] for st in dst.list_pipeline_steps(pid)]
        self.assertEqual(overrides, [None, "--override", None])

    def test_step_order_survives(self):
        _src, dst, _ = self._round_trip()
        pid = dst.list_pipelines("G")[0][0]
        self.assertEqual([st[2] for st in dst.list_pipeline_steps(pid)],
                         ["Alpha", "Beta", "Gamma"])

    def test_pipeline_name_and_group_survive(self):
        _src, dst, _ = self._round_trip()
        pipes = dst.list_pipelines("G")
        self.assertEqual(len(pipes), 1)
        self.assertEqual(pipes[0][1], "Deploy")

    # ---- payload shape ----------------------------------------------------

    def test_payload_declares_v4(self):
        src, _pid = self._populated_db()
        path = self._tmp_json()
        src.export_to_file(path)
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 6)

    def test_payload_carries_the_new_step_fields(self):
        src, _pid = self._populated_db()
        path = self._tmp_json()
        src.export_to_file(path)
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        step = data["pipelines"][0]["steps"][1]
        self.assertEqual(step["params_override"], "--override")
        self.assertEqual(step["trigger_mode"], TRIGGER_WITH)

    # ---- backward compatibility ------------------------------------------

    def _write(self, payload) -> str:
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w",
                                         delete=False, encoding="utf-8") as f:
            json.dump(payload, f)
            return f.name

    def _v3_payload(self):
        """A file exactly as the previous exporter wrote it."""
        return {
            "version": 3,
            "groups": [{"name": "G", "sort_order": 0, "base_dir": ""}],
            "scripts": [
                {"name": "Alpha", "path": "/alpha.py", "params": "",
                 "interpreter": "", "order_index": 0, "group_name": "G",
                 "presets": []},
                {"name": "Beta", "path": "/beta.py", "params": "",
                 "interpreter": "", "order_index": 1, "group_name": "G",
                 "presets": []},
            ],
            "pipelines": [{
                "name": "P", "group_name": "G", "sort_order": 0,
                "steps": [{"script_path": "/alpha.py"},
                          {"script_path": "/beta.py"}],
            }],
        }

    def test_v3_file_still_imports(self):
        db = _make_db()
        added, _skipped = db.import_from_file(self._write(self._v3_payload()))
        self.assertEqual(added, 2)
        pid = db.list_pipelines("G")[0][0]
        self.assertEqual(len(db.list_pipeline_steps(pid)), 2)

    def test_v3_file_gets_the_new_defaults(self):
        db = _make_db()
        db.import_from_file(self._write(self._v3_payload()))
        alpha = next(r for r in db.list_all() if r[1] == "Alpha")
        self.assertEqual(alpha[9], 0)       # temp_param
        self.assertEqual(alpha[10], 0)      # is_favorite
        self.assertIsNone(alpha[11])        # label_color
        pid = db.list_pipelines("G")[0][0]
        self.assertEqual([st[7] for st in db.list_pipeline_steps(pid)],
                         [TRIGGER_AFTER, TRIGGER_AFTER])

    # ---- hostile input ----------------------------------------------------

    def test_unknown_trigger_mode_falls_back(self):
        # trigger_mode is NOT NULL; a stray value would leave the step neither
        # sequential nor concurrent at runtime.
        payload = self._v3_payload()
        payload["version"] = 4
        payload["pipelines"][0]["steps"][1]["trigger_mode"] = "whenever"
        db = _make_db()
        db.import_from_file(self._write(payload))
        pid = db.list_pipelines("G")[0][0]
        self.assertEqual(db.list_pipeline_steps(pid)[1][7], TRIGGER_AFTER)

    def test_leading_with_is_normalised(self):
        # A first step has no previous step to run alongside.
        payload = self._v3_payload()
        payload["version"] = 4
        payload["pipelines"][0]["steps"][0]["trigger_mode"] = TRIGGER_WITH
        db = _make_db()
        db.import_from_file(self._write(payload))
        pid = db.list_pipelines("G")[0][0]
        self.assertEqual(db.list_pipeline_steps(pid)[0][7], TRIGGER_AFTER)

    def test_empty_colour_string_becomes_null(self):
        payload = self._v3_payload()
        payload["scripts"][0]["label_color"] = ""
        db = _make_db()
        db.import_from_file(self._write(payload))
        alpha = next(r for r in db.list_all() if r[1] == "Alpha")
        self.assertIsNone(alpha[11])

    def test_unknown_colour_key_is_kept_not_rejected(self):
        # db.py can't import the UI palette to validate; the card layer already
        # falls back for any key it doesn't recognise.
        payload = self._v3_payload()
        payload["scripts"][0]["label_color"] = "chartreuse"
        db = _make_db()
        db.import_from_file(self._write(payload))
        alpha = next(r for r in db.list_all() if r[1] == "Alpha")
        self.assertEqual(alpha[11], "chartreuse")

    def test_step_with_missing_script_is_skipped_not_fatal(self):
        payload = self._v3_payload()
        payload["pipelines"][0]["steps"].append({"script_path": "/nope.py"})
        db = _make_db()
        db.import_from_file(self._write(payload))
        pid = db.list_pipelines("G")[0][0]
        self.assertEqual(len(db.list_pipeline_steps(pid)), 2)


# ---------------------------------------------------------------------------
# Per-script environment and working directory
# ---------------------------------------------------------------------------
from ryos.interpreter import (  # noqa: E402
    RunSpec, build_run_spec, format_env_text, parse_env_text, parse_env_vars,
)


class TestParseEnvVars(unittest.TestCase):
    """The stored blob sits on the run path, so nothing in it may raise."""

    def test_none_and_empty_yield_nothing(self):
        for raw in (None, "", "   ", 0):
            with self.subTest(raw=raw):
                self.assertEqual(parse_env_vars(raw), {})

    def test_json_object_is_decoded(self):
        self.assertEqual(parse_env_vars('{"A": "1", "B": "2"}'), {"A": "1", "B": "2"})

    def test_a_dict_is_accepted_directly(self):
        self.assertEqual(parse_env_vars({"A": "1"}), {"A": "1"})

    def test_malformed_json_degrades_to_empty(self):
        # A bad blob must not be able to stop a script from launching.
        self.assertEqual(parse_env_vars("{not json"), {})

    def test_non_object_json_degrades_to_empty(self):
        self.assertEqual(parse_env_vars("[1, 2]"), {})
        self.assertEqual(parse_env_vars('"a string"'), {})

    def test_values_are_coerced_to_strings(self):
        # Popen requires str values; a number from a hand-edited export would
        # otherwise raise at launch time.
        self.assertEqual(parse_env_vars('{"N": 1, "T": true}'), {"N": "1", "T": "True"})

    def test_null_value_becomes_empty_string(self):
        self.assertEqual(parse_env_vars('{"A": null}'), {"A": ""})

    def test_blank_keys_are_dropped(self):
        self.assertEqual(parse_env_vars('{"  ": "x", "A": "1"}'), {"A": "1"})


class TestParseEnvText(unittest.TestCase):
    """The dialog edits a KEY=value block in .env style."""

    def test_basic_pairs(self):
        self.assertEqual(parse_env_text("A=1\nB=2"), {"A": "1", "B": "2"})

    def test_blank_lines_and_comments_are_ignored(self):
        self.assertEqual(parse_env_text("\n# note\nA=1\n\n"), {"A": "1"})

    def test_value_may_contain_equals(self):
        # Connection strings and query params routinely do.
        self.assertEqual(parse_env_text("DSN=postgres://h/db?x=1"),
                         {"DSN": "postgres://h/db?x=1"})

    def test_surrounding_whitespace_is_trimmed(self):
        self.assertEqual(parse_env_text("  A  =  1  "), {"A": "1"})

    def test_line_without_equals_is_skipped(self):
        self.assertEqual(parse_env_text("novalue\nA=1"), {"A": "1"})

    def test_orphan_equals_is_skipped(self):
        # "=x" would otherwise become a variable with an empty name.
        self.assertEqual(parse_env_text("=x\nA=1"), {"A": "1"})

    def test_empty_value_is_kept(self):
        self.assertEqual(parse_env_text("A="), {"A": ""})

    def test_round_trips_through_format(self):
        text = "A=1\nB=two words"
        self.assertEqual(parse_env_text(format_env_text(json.dumps(parse_env_text(text)))),
                         {"A": "1", "B": "two words"})

    def test_format_of_nothing_is_empty(self):
        self.assertEqual(format_env_text(None), "")


class TestBuildRunSpec(unittest.TestCase):

    BASE = {"PATH": "/usr/bin", "HOME": "/home/u"}
    CMD = ["python", "/proj/run.py"]

    def test_no_overrides_inherits_the_environment(self):
        # env=None is what Popen already defaults to, so a script with no
        # overrides produces the identical call this app made before.
        spec = build_run_spec(self.CMD, base_env=self.BASE)
        self.assertIsNone(spec.env)

    def test_no_work_dir_falls_back_to_the_script_folder(self):
        spec = build_run_spec(self.CMD, base_env=self.BASE)
        self.assertEqual(spec.cwd, working_dir_for(self.CMD))

    def test_work_dir_overrides_the_default(self):
        spec = build_run_spec(self.CMD, work_dir="/elsewhere", base_env=self.BASE)
        self.assertEqual(spec.cwd, "/elsewhere")

    def test_blank_work_dir_is_treated_as_unset(self):
        spec = build_run_spec(self.CMD, work_dir="   ", base_env=self.BASE)
        self.assertEqual(spec.cwd, working_dir_for(self.CMD))

    def test_overlay_preserves_the_parent_environment(self):
        # A bare env has no PATH, which breaks the interpreter lookup on
        # Windows -- the overlay must never replace, only add.
        spec = build_run_spec(self.CMD, env_vars='{"API_KEY": "abc"}', base_env=self.BASE)
        self.assertEqual(spec.env["PATH"], "/usr/bin")
        self.assertEqual(spec.env["HOME"], "/home/u")
        self.assertEqual(spec.env["API_KEY"], "abc")

    def test_overlay_can_shadow_a_parent_variable(self):
        spec = build_run_spec(self.CMD, env_vars='{"PATH": "/custom"}', base_env=self.BASE)
        self.assertEqual(spec.env["PATH"], "/custom")

    def test_malformed_blob_leaves_the_environment_inherited(self):
        spec = build_run_spec(self.CMD, env_vars="{broken", base_env=self.BASE)
        self.assertIsNone(spec.env)

    def test_empty_object_leaves_the_environment_inherited(self):
        spec = build_run_spec(self.CMD, env_vars="{}", base_env=self.BASE)
        self.assertIsNone(spec.env)

    def test_command_is_passed_through_untouched(self):
        spec = build_run_spec(self.CMD, base_env=self.BASE)
        self.assertEqual(spec.cmd, self.CMD)

    def test_default_spec_matches_the_pre_feature_call(self):
        # The safety property for this whole change: an unconfigured script must
        # produce exactly the Popen arguments used before RunSpec existed.
        spec = build_run_spec(self.CMD, base_env=self.BASE)
        self.assertEqual((spec.cmd, spec.cwd, spec.env),
                         (self.CMD, working_dir_for(self.CMD), None))


class TestScriptEnvStorage(unittest.TestCase):

    def setUp(self):
        self.db = _make_db()

    def test_defaults_are_empty(self):
        sid = self.db.add("s", "/s.py", "", "")
        rec = self.db.get(sid)
        self.assertIsNone(rec[7])       # env_vars
        self.assertEqual(rec[8], "")    # work_dir

    def test_add_stores_both(self):
        sid = self.db.add("s", "/s.py", "", "", env_vars='{"A":"1"}', work_dir="/w")
        rec = self.db.get(sid)
        self.assertEqual(parse_env_vars(rec[7]), {"A": "1"})
        self.assertEqual(rec[8], "/w")

    def test_update_sets_both(self):
        sid = self.db.add("s", "/s.py", "", "")
        self.db.update(sid, "s", "/s.py", "", "", env_vars='{"A":"1"}', work_dir="/w")
        rec = self.db.get(sid)
        self.assertEqual(parse_env_vars(rec[7]), {"A": "1"})
        self.assertEqual(rec[8], "/w")

    def test_update_none_leaves_them_untouched(self):
        # A caller that predates these fields must not be able to blank them.
        sid = self.db.add("s", "/s.py", "", "", env_vars='{"A":"1"}', work_dir="/w")
        self.db.update(sid, "renamed", "/s.py", "", "")
        rec = self.db.get(sid)
        self.assertEqual(parse_env_vars(rec[7]), {"A": "1"})
        self.assertEqual(rec[8], "/w")

    def test_update_empty_string_clears_them(self):
        sid = self.db.add("s", "/s.py", "", "", env_vars='{"A":"1"}', work_dir="/w")
        self.db.update(sid, "s", "/s.py", "", "", env_vars="", work_dir="")
        rec = self.db.get(sid)
        self.assertIsNone(rec[7])
        self.assertEqual(rec[8], "")

    def test_pipeline_step_inherits_from_its_script(self):
        sid = self.db.add("s", "/s.py", "", "", "G", env_vars='{"A":"1"}', work_dir="/w")
        pid = self.db.create_pipeline("P", "G")
        self.db.add_pipeline_step(pid, sid)
        step = self.db.list_pipeline_steps(pid)[0]
        self.assertEqual(parse_env_vars(step[8]), {"A": "1"})
        self.assertEqual(step[9], "/w")

    def test_clone_group_carries_them(self):
        self.db.create_group("Src")
        self.db.add("s", "/s.py", "", "", "Src", env_vars='{"A":"1"}', work_dir="/w")
        self.db.clone_group("Src", "Dst")
        rec = [r for r in self.db.list_all() if r[8] == "Dst"][0]
        full = self.db.get(rec[0])
        self.assertEqual(parse_env_vars(full[7]), {"A": "1"})
        self.assertEqual(full[8], "/w")

    def test_export_import_round_trip(self):
        self.db.add("s", "/s.py", "", "", "G", env_vars='{"A":"1"}', work_dir="/w")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        self.db.export_to_file(path)
        other = _make_db()
        other.import_from_file(path)
        sid = other.list_all()[0][0]
        rec = other.get(sid)
        self.assertEqual(parse_env_vars(rec[7]), {"A": "1"})
        self.assertEqual(rec[8], "/w")


class TestRunSpecReachesTheProcess(unittest.TestCase):
    """End-to-end through the real runner and a real subprocess."""

    def _job(self):
        return Job(1, "script", 1, None, "t", "job:1", "g")

    def _drain(self, q):
        out = []
        while not q.empty():
            out.append(q.get_nowait())
        return out

    def test_env_override_is_visible_to_the_child(self):
        q = _queue.Queue()
        spec = build_run_spec(
            [sys.executable, "-c", "import os; print(os.environ['RYOS_TEST_VAR'])"],
            env_vars='{"RYOS_TEST_VAR": "reached"}')
        run_subprocess(q, self._job(), spec, "t", 1)
        text = "".join(i[2] for i in self._drain(q) if i[0] == "stdout")
        self.assertIn("reached", text)

    def test_path_still_reaches_the_child_alongside_an_override(self):
        q = _queue.Queue()
        spec = build_run_spec(
            [sys.executable, "-c", "import os; print('PATH' in os.environ)"],
            env_vars='{"RYOS_TEST_VAR": "x"}')
        run_subprocess(q, self._job(), spec, "t", 1)
        text = "".join(i[2] for i in self._drain(q) if i[0] == "stdout")
        self.assertIn("True", text)

    def test_work_dir_is_where_the_child_runs(self):
        q = _queue.Queue()
        target = os.path.realpath(tempfile.mkdtemp())
        spec = build_run_spec([sys.executable, "-c", "import os; print(os.getcwd())"],
                              work_dir=target)
        run_subprocess(q, self._job(), spec, "t", 1)
        text = "".join(i[2] for i in self._drain(q) if i[0] == "stdout")
        self.assertEqual(os.path.realpath(text.strip()), target)

    def test_a_bare_command_list_still_works(self):
        # The runner accepts a plain list for callers predating RunSpec.
        q = _queue.Queue()
        run_subprocess(q, self._job(), [sys.executable, "-c", "print('plain')"], "t", 1)
        text = "".join(i[2] for i in self._drain(q) if i[0] == "stdout")
        self.assertIn("plain", text)


class TestControllerBuildsRunSpec(unittest.TestCase):
    """Pipeline steps must reach _launch as a RunSpec carrying their script's
    environment -- the controller is the only place that assembles one for a step."""

    def setUp(self):
        self.rec = {"launch": []}
        self.reg = JobRegistry()
        self.q = _queue.Queue()
        self.ctl = JobController(
            self.reg, self.q, _make_db(),
            on_output=lambda *a: None, on_status=lambda *a: None,
            on_notify=lambda *a: None, on_started=lambda *a: None,
            on_finish=lambda *a: None, on_rename=lambda *a: None,
            launch=lambda job, spec, name, sid, tok=None:
                self.rec["launch"].append((spec, name, sid, tok)),
        )

    def _job(self, queue_):
        job = Job(1, "pipeline", None, 1, "p", "job:1", "g",
                  pipeline_name="p", pipeline_queue=queue_, pipeline_total=len(queue_))
        self.reg.add(job)
        return job

    def _step(self, sid, name, path, env_vars=None, work_dir=""):
        return (sid, sid, name, path, "", "", None, TRIGGER_AFTER, env_vars, work_dir)

    def test_step_env_reaches_the_spec(self):
        here = str(Path(__file__).resolve())
        job = self._job([self._step(1, "s", here, env_vars='{"A":"1"}')])
        self.ctl.run_next_pipeline_step(job)
        spec = self.rec["launch"][0][0]
        self.assertIsInstance(spec, RunSpec)
        self.assertEqual(spec.env["A"], "1")

    def test_step_work_dir_reaches_the_spec(self):
        here = str(Path(__file__).resolve())
        target = tempfile.mkdtemp()
        job = self._job([self._step(1, "s", here, work_dir=target)])
        self.ctl.run_next_pipeline_step(job)
        self.assertEqual(self.rec["launch"][0][0].cwd, target)

    def test_step_without_env_inherits(self):
        here = str(Path(__file__).resolve())
        job = self._job([self._step(1, "s", here)])
        self.ctl.run_next_pipeline_step(job)
        self.assertIsNone(self.rec["launch"][0][0].env)

    def test_short_legacy_step_tuple_still_launches(self):
        # 8-tuples predate these columns; they must yield the default spec
        # rather than an IndexError on the run path.
        here = str(Path(__file__).resolve())
        job = self._job([(1, 1, "s", here, "", "", None, TRIGGER_AFTER)])
        self.ctl.run_next_pipeline_step(job)
        spec = self.rec["launch"][0][0]
        self.assertIsNone(spec.env)
        self.assertEqual(spec.cwd, working_dir_for([here]))


# ---------------------------------------------------------------------------
# Run history — storage, retention, formatting, and the controller hooks
# ---------------------------------------------------------------------------
from ryos.db import (  # noqa: E402
    RUN_PIPELINE, RUN_SCRIPT, RUN_STEP, SOURCE_MANUAL, SOURCE_PIPELINE,
)
import datetime  # noqa: E402
from ryos.history import (  # noqa: E402
    describe, format_duration, format_exit_code, format_run_row, format_status,
    format_when, header_row, parse_stamp, summarize,
)


def _run_row(**kw):
    """A list_runs-shaped tuple with sensible defaults."""
    base = dict(id=1, script_id=1, pipeline_id=None, kind=RUN_SCRIPT, name="s",
                started_at="2026-09-14T10:00:00", finished_at="2026-09-14T10:00:04",
                status="ok", exit_code=0, step_index=None,
                trigger_source=SOURCE_MANUAL)
    base.update(kw)
    return (base["id"], base["script_id"], base["pipeline_id"], base["kind"],
            base["name"], base["started_at"], base["finished_at"], base["status"],
            base["exit_code"], base["step_index"], base["trigger_source"])


class TestRunHistoryStorage(unittest.TestCase):

    def setUp(self):
        self.db = _make_db()
        self.sid = self.db.add("s", "/s.py", "", "", "G")
        self.now = datetime.datetime.now()

    def test_records_and_reads_back(self):
        self.db.record_run(RUN_SCRIPT, name="s", script_id=self.sid,
                           started_at=self.now, finished_at=self.now,
                           status="ok", exit_code=0)
        rows = self.db.list_runs(script_id=self.sid)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][3], RUN_SCRIPT)
        self.assertEqual(rows[0][7], "ok")
        self.assertEqual(rows[0][8], 0)

    def test_exit_code_is_preserved_including_zero(self):
        # 0 is falsy; a naive `if exit_code:` would drop the success case.
        self.db.record_run(RUN_SCRIPT, name="s", script_id=self.sid,
                           started_at=self.now, status="ok", exit_code=0)
        self.assertEqual(self.db.list_runs(script_id=self.sid)[0][8], 0)

    def test_missing_exit_code_stays_null(self):
        self.db.record_run(RUN_SCRIPT, name="s", script_id=self.sid,
                           started_at=self.now, status="error")
        self.assertIsNone(self.db.list_runs(script_id=self.sid)[0][8])

    def test_default_trigger_is_manual(self):
        self.db.record_run(RUN_SCRIPT, name="s", script_id=self.sid,
                           started_at=self.now)
        self.assertEqual(self.db.list_runs(script_id=self.sid)[0][10], SOURCE_MANUAL)

    def test_newest_first(self):
        for i, when in enumerate(["2026-01-01T00:00:00", "2026-06-01T00:00:00",
                                  "2026-03-01T00:00:00"]):
            self.db.record_run(RUN_SCRIPT, name=f"r{i}", script_id=self.sid,
                               started_at=when)
        names = [r[4] for r in self.db.list_runs(script_id=self.sid)]
        self.assertEqual(names, ["r1", "r2", "r0"])

    def test_limit_is_respected(self):
        for i in range(10):
            self.db.record_run(RUN_SCRIPT, name=f"r{i}", script_id=self.sid,
                               started_at=self.now)
        self.assertEqual(len(self.db.list_runs(script_id=self.sid, limit=3)), 3)

    def test_filters_by_script(self):
        other = self.db.add("o", "/o.py", "", "", "G")
        self.db.record_run(RUN_SCRIPT, name="mine", script_id=self.sid, started_at=self.now)
        self.db.record_run(RUN_SCRIPT, name="theirs", script_id=other, started_at=self.now)
        self.assertEqual([r[4] for r in self.db.list_runs(script_id=self.sid)], ["mine"])

    def test_filters_by_pipeline(self):
        pid = self.db.create_pipeline("P", "G")
        self.db.record_run(RUN_PIPELINE, name="P", pipeline_id=pid, started_at=self.now)
        self.db.record_run(RUN_SCRIPT, name="s", script_id=self.sid, started_at=self.now)
        self.assertEqual([r[4] for r in self.db.list_runs(pipeline_id=pid)], ["P"])

    def test_accepts_a_datetime_or_a_string(self):
        self.db.record_run(RUN_SCRIPT, name="dt", script_id=self.sid, started_at=self.now)
        self.db.record_run(RUN_SCRIPT, name="str", script_id=self.sid,
                           started_at="2026-09-14T10:00:00")
        for row in self.db.list_runs(script_id=self.sid):
            with self.subTest(name=row[4]):
                self.assertIsNotNone(parse_stamp(row[5]))

    def test_clear_for_one_item_leaves_others(self):
        other = self.db.add("o", "/o.py", "", "", "G")
        self.db.record_run(RUN_SCRIPT, name="mine", script_id=self.sid, started_at=self.now)
        self.db.record_run(RUN_SCRIPT, name="theirs", script_id=other, started_at=self.now)
        self.db.clear_runs(script_id=self.sid)
        self.assertEqual(self.db.list_runs(script_id=self.sid), [])
        self.assertEqual(len(self.db.list_runs(script_id=other)), 1)


class TestRunHistoryRetention(unittest.TestCase):

    def setUp(self):
        self.db = _make_db()
        self.sid = self.db.add("s", "/s.py", "", "")
        now = datetime.datetime.now()
        self.db.record_run(RUN_SCRIPT, name="recent", script_id=self.sid,
                           started_at=now - datetime.timedelta(days=1))
        self.db.record_run(RUN_SCRIPT, name="old", script_id=self.sid,
                           started_at=now - datetime.timedelta(days=200))

    def test_prunes_only_what_is_past_the_window(self):
        removed = self.db.prune_runs(90)
        self.assertEqual(removed, 1)
        self.assertEqual([r[4] for r in self.db.list_runs(script_id=self.sid)], ["recent"])

    def test_zero_disables_pruning(self):
        # An off-by-one that treated 0 as "keep nothing" would silently destroy
        # the user's entire history.
        self.assertEqual(self.db.prune_runs(0), 0)
        self.assertEqual(len(self.db.list_runs(script_id=self.sid)), 2)

    def test_negative_disables_pruning(self):
        self.assertEqual(self.db.prune_runs(-5), 0)
        self.assertEqual(len(self.db.list_runs(script_id=self.sid)), 2)

    def test_pruning_is_idempotent(self):
        self.db.prune_runs(90)
        self.assertEqual(self.db.prune_runs(90), 0)

    def test_sub_second_runs_keep_a_real_duration(self):
        # Stored at seconds resolution, every fast script would read "0.0s".
        db = _make_db()
        sid = db.add("s", "/s.py", "", "")
        start = datetime.datetime.now()
        db.record_run(RUN_SCRIPT, name="quick", script_id=sid, started_at=start,
                      finished_at=start + datetime.timedelta(milliseconds=420),
                      status="ok", exit_code=0)
        row = db.list_runs(script_id=sid)[0]
        self.assertEqual(format_duration(row[5], row[6]), "0.4s")

    def test_millisecond_stamps_still_sort_and_prune(self):
        db = _make_db()
        sid = db.add("s", "/s.py", "", "")
        now = datetime.datetime.now()
        db.record_run(RUN_SCRIPT, name="new", script_id=sid, started_at=now)
        db.record_run(RUN_SCRIPT, name="old", script_id=sid,
                      started_at=now - datetime.timedelta(days=200))
        self.assertEqual([r[4] for r in db.list_runs(script_id=sid)], ["new", "old"])
        self.assertEqual(db.prune_runs(90), 1)
        self.assertEqual([r[4] for r in db.list_runs(script_id=sid)], ["new"])


class TestRunHistoryFormatting(unittest.TestCase):

    def test_when_has_no_year(self):
        self.assertEqual(format_when("2026-09-14T14:03:09"), "09-14 14:03:09")

    def test_unparseable_stamp_renders_as_a_dash(self):
        # History outlives the code that wrote it; a bad stamp must not raise
        # inside a list redraw.
        self.assertEqual(format_when("not-a-date"), "—")
        self.assertIsNone(parse_stamp("not-a-date"))

    def test_seconds_below_a_minute(self):
        self.assertEqual(format_duration("2026-09-14T10:00:00", "2026-09-14T10:00:04"), "4.0s")

    def test_minutes_are_zero_padded(self):
        self.assertEqual(format_duration("2026-09-14T10:00:00", "2026-09-14T10:02:05"), "2m 05s")

    def test_missing_finish_has_no_duration(self):
        self.assertEqual(format_duration("2026-09-14T10:00:00", None), "—")

    def test_negative_duration_is_rejected(self):
        # A clock change shouldn't render "-3600.0s".
        self.assertEqual(format_duration("2026-09-14T10:00:00", "2026-09-14T09:00:00"), "—")

    def test_status_marks(self):
        self.assertIn("ok", format_status("ok"))
        self.assertIn("error", format_status("error"))
        self.assertEqual(format_status(None), "—")

    def test_unknown_status_passes_through(self):
        self.assertEqual(format_status("weird"), "weird")

    def test_exit_zero_is_shown_not_blanked(self):
        self.assertEqual(format_exit_code(0), "0")
        self.assertEqual(format_exit_code(None), "—")

    def test_step_rows_name_their_position(self):
        self.assertEqual(describe(_run_row(kind=RUN_STEP, step_index=3, name="build")),
                         "step 3  build")

    def test_non_step_rows_are_just_the_name(self):
        self.assertEqual(describe(_run_row(name="build")), "build")

    def test_columns_line_up_with_the_header(self):
        # The list is monospace; a row wider than its columns would shear the
        # whole table.
        header = header_row()
        at = header.index("WHAT")
        for row in (_run_row(name="probe"),
                    _run_row(name="probe", status="error", exit_code=127),
                    _run_row(name="probe", finished_at=None, status="stopped",
                             exit_code=None),
                    _run_row(name="probe", kind=RUN_STEP, step_index=12),
                    _run_row(name="probe", started_at="bad", finished_at=None,
                             status=None, exit_code=None)):
            with self.subTest(row=row):
                # Positional, not a search: the name can also occur inside an
                # earlier column's text.
                self.assertTrue(format_run_row(row)[at:].startswith(describe(row)))

    def test_summarize_counts(self):
        rows = [_run_row(status="ok"), _run_row(status="error"), _run_row(status="ok")]
        self.assertEqual(summarize(rows), "3 runs · 2 passed · 1 failed")

    def test_summarize_singular(self):
        self.assertIn("1 run ", summarize([_run_row()]))

    def test_summarize_empty(self):
        self.assertEqual(summarize([]), "No runs recorded yet.")


class _FakeProc:
    def __init__(self, returncode):
        self.returncode = returncode

    def poll(self):
        return self.returncode


class TestControllerWritesHistory(unittest.TestCase):
    """The controller is the only place a run gets recorded, so both the ad-hoc
    and the pipeline paths must land there."""

    def setUp(self):
        self.db = _make_db()
        self.reg = JobRegistry()
        self.q = _queue.Queue()
        self.finished = []
        self.ctl = JobController(
            self.reg, self.q, self.db,
            on_output=lambda *a: None, on_status=lambda *a: None,
            on_notify=lambda *a: None, on_started=lambda *a: None,
            on_finish=lambda j: self.finished.append(j),
            on_rename=lambda *a: None,
            launch=lambda *a, **k: None,
        )

    def _script_job(self, trigger=SOURCE_MANUAL):
        job = Job(1, "script", 7, None, "build", "job:1", "g", trigger=trigger)
        self.reg.add(job)
        return job

    def _pipeline_job(self, steps, total=None):
        job = Job(2, "pipeline", None, 3, "p", "job:2", "g", pipeline_name="Nightly",
                  pipeline_queue=list(steps), pipeline_total=total or len(steps))
        self.reg.add(job)
        return job

    def _step(self, sid, name, trigger_mode=TRIGGER_AFTER):
        return (sid, sid, name, __file__, "", "", None, trigger_mode)

    # ---- ad-hoc scripts ---------------------------------------------------

    def test_script_run_is_recorded(self):
        job = self._script_job()
        self.ctl.handle_step_done(job, 7, "ok")
        rows = self.db.list_runs(script_id=7)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][3], RUN_SCRIPT)
        self.assertEqual(rows[0][7], "ok")

    def test_script_failure_is_recorded(self):
        job = self._script_job()
        self.ctl.handle_step_done(job, 7, "error")
        self.assertEqual(self.db.list_runs(script_id=7)[0][7], "error")

    def test_exit_code_comes_from_the_process_handle(self):
        job = self._script_job()
        job.processes[None] = _FakeProc(3)
        self.ctl.handle_step_done(job, 7, "error")
        self.assertEqual(self.db.list_runs(script_id=7)[0][8], 3)

    def test_no_process_means_no_exit_code(self):
        # A launch failure never produced one.
        job = self._script_job()
        self.ctl.handle_step_done(job, 7, "error")
        self.assertIsNone(self.db.list_runs(script_id=7)[0][8])

    def test_job_trigger_is_carried_into_the_row(self):
        # Nothing sets a non-manual trigger yet; the scheduler will.
        job = self._script_job(trigger="schedule")
        self.ctl.handle_step_done(job, 7, "ok")
        self.assertEqual(self.db.list_runs(script_id=7)[0][10], "schedule")

    # ---- pipelines --------------------------------------------------------

    def test_each_step_gets_its_own_row(self):
        job = self._pipeline_job([self._step(1, "a"), self._step(2, "b")])
        self.ctl.run_next_pipeline_step(job)
        self.ctl.handle_step_done(job, 1, "ok", token=1)
        self.ctl.handle_step_done(job, 2, "ok", token=2)
        steps = [r for r in self.db.list_runs(pipeline_id=3) if r[3] == RUN_STEP]
        self.assertEqual(len(steps), 2)
        self.assertEqual(sorted(r[4] for r in steps), ["a", "b"])

    def test_step_rows_use_the_pipeline_trigger_source(self):
        job = self._pipeline_job([self._step(1, "a")])
        self.ctl.run_next_pipeline_step(job)
        self.ctl.handle_step_done(job, 1, "ok", token=1)
        step = [r for r in self.db.list_runs(pipeline_id=3) if r[3] == RUN_STEP][0]
        self.assertEqual(step[10], SOURCE_PIPELINE)

    def test_pipeline_summary_row_on_success(self):
        job = self._pipeline_job([self._step(1, "a")])
        self.ctl.run_next_pipeline_step(job)
        self.ctl.handle_step_done(job, 1, "ok", token=1)
        summary = [r for r in self.db.list_runs(pipeline_id=3) if r[3] == RUN_PIPELINE]
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0][7], "ok")
        self.assertEqual(summary[0][4], "Nightly")

    def test_pipeline_summary_row_on_failure_names_the_failed_step(self):
        job = self._pipeline_job([self._step(1, "a"), self._step(2, "b")])
        self.ctl.run_next_pipeline_step(job)
        self.ctl.handle_step_done(job, 1, "error", token=1)
        summary = [r for r in self.db.list_runs(pipeline_id=3) if r[3] == RUN_PIPELINE][0]
        self.assertEqual(summary[7], "error")
        self.assertEqual(summary[9], 1)

    def test_no_summary_row_while_steps_remain(self):
        job = self._pipeline_job([self._step(1, "a"), self._step(2, "b")])
        self.ctl.run_next_pipeline_step(job)
        self.ctl.handle_step_done(job, 1, "ok", token=1)
        self.assertEqual([r for r in self.db.list_runs(pipeline_id=3)
                          if r[3] == RUN_PIPELINE], [])

    def test_concurrent_group_members_each_get_a_row(self):
        # Settlement rewrites the group's status; the per-member rows must
        # still carry each member's own result.
        job = self._pipeline_job([self._step(1, "a"),
                                  self._step(2, "b", TRIGGER_WITH)])
        self.ctl.run_next_pipeline_step(job)
        self.ctl.handle_step_done(job, 1, "ok", token=1)
        self.ctl.handle_step_done(job, 2, "error", token=2)
        steps = {r[4]: r[7] for r in self.db.list_runs(pipeline_id=3) if r[3] == RUN_STEP}
        self.assertEqual(steps, {"a": "ok", "b": "error"})

    def test_a_history_failure_does_not_break_the_run(self):
        # History is secondary; a DB problem must not stop a pipeline.
        job = self._script_job()
        with mock.patch.object(self.db, "record_run", side_effect=RuntimeError("boom")):
            self.ctl.handle_step_done(job, 7, "ok")
        self.assertEqual(len(self.finished), 1)


# ---------------------------------------------------------------------------
# Scheduling — the date maths, then the storage
# ---------------------------------------------------------------------------
from ryos.scheduling import (  # noqa: E402
    CATCH_UP_ALL, CATCH_UP_ONCE, CATCH_UP_SKIP, DAILY, INTERVAL, MAX_CATCH_UP,
    WEEKLY, describe_spec, next_occurrence, normalize_spec,
    parse_time_of_day,
    preview, resolve_due,
)

MON = datetime.datetime(2026, 9, 14, 8, 30)   # a Monday morning


class TestNormalizeSpec(unittest.TestCase):
    """A corrupt or hand-edited row must disable its schedule, never raise."""

    def test_interval_minutes(self):
        self.assertEqual(normalize_spec(INTERVAL, {"minutes": 30}), {"minutes": 30})

    def test_interval_accepts_a_numeric_string(self):
        # The dialog hands over whatever was typed into the entry.
        self.assertEqual(normalize_spec(INTERVAL, {"minutes": "45"}), {"minutes": 45})

    def test_interval_below_one_minute_is_rejected(self):
        # Anything under the tick interval would fire faster than it is serviced.
        for bad in (0, -5):
            with self.subTest(minutes=bad):
                self.assertIsNone(normalize_spec(INTERVAL, {"minutes": bad}))

    def test_interval_garbage_is_rejected(self):
        for bad in ({"minutes": "soon"}, {"minutes": None}, {}, None, "nope"):
            with self.subTest(spec=bad):
                self.assertIsNone(normalize_spec(INTERVAL, bad))

    def test_daily_time_is_padded(self):
        self.assertEqual(normalize_spec(DAILY, {"at": "9:5"}), {"at": "09:05"})

    def test_daily_out_of_range_is_rejected(self):
        for bad in ("24:00", "12:60", "-1:00", "noon", ""):
            with self.subTest(at=bad):
                self.assertIsNone(normalize_spec(DAILY, {"at": bad}))

    def test_weekly_days_are_deduped_and_sorted(self):
        self.assertEqual(normalize_spec(WEEKLY, {"at": "09:00", "days": [4, 0, 4]}),
                         {"at": "09:00", "days": [0, 4]})

    def test_weekly_out_of_range_days_are_dropped(self):
        self.assertEqual(normalize_spec(WEEKLY, {"at": "09:00", "days": [1, 9, -2]}),
                         {"at": "09:00", "days": [1]})

    def test_weekly_with_no_days_is_rejected(self):
        # It would never fire, so it must not be storable as enabled.
        self.assertIsNone(normalize_spec(WEEKLY, {"at": "09:00", "days": []}))
        self.assertIsNone(normalize_spec(WEEKLY, {"at": "09:00", "days": "mon"}))

    def test_unknown_spec_type_is_rejected(self):
        self.assertIsNone(normalize_spec("cron", {"expr": "* * * * *"}))

    def test_parse_time_of_day_passes_through_a_time(self):
        t = datetime.time(7, 30)
        self.assertEqual(parse_time_of_day(t), t)


class TestNextOccurrence(unittest.TestCase):

    def test_interval_adds_the_delta(self):
        self.assertEqual(next_occurrence(INTERVAL, {"minutes": 30}, MON),
                         MON + datetime.timedelta(minutes=30))

    def test_daily_later_today(self):
        self.assertEqual(next_occurrence(DAILY, {"at": "09:00"}, MON),
                         datetime.datetime(2026, 9, 14, 9, 0))

    def test_daily_already_passed_rolls_to_tomorrow(self):
        self.assertEqual(next_occurrence(DAILY, {"at": "08:00"}, MON),
                         datetime.datetime(2026, 9, 15, 8, 0))

    def test_exactly_now_still_advances(self):
        # Strictly-after, or a just-fired schedule would hand back the same
        # moment and fire again on the next tick forever.
        at_nine = datetime.datetime(2026, 9, 14, 9, 0)
        self.assertEqual(next_occurrence(DAILY, {"at": "09:00"}, at_nine),
                         datetime.datetime(2026, 9, 15, 9, 0))

    def test_weekly_picks_today_when_it_is_still_ahead(self):
        self.assertEqual(next_occurrence(WEEKLY, {"at": "18:30", "days": [0]}, MON),
                         datetime.datetime(2026, 9, 14, 18, 30))

    def test_weekly_wraps_to_next_week(self):
        # Monday 08:30 asking for Mondays at 08:00 -> next Monday.
        self.assertEqual(next_occurrence(WEEKLY, {"at": "08:00", "days": [0]}, MON),
                         datetime.datetime(2026, 9, 21, 8, 0))

    def test_weekly_finds_the_nearest_of_several_days(self):
        nxt = next_occurrence(WEEKLY, {"at": "09:00", "days": [0, 2, 4]}, MON)
        self.assertEqual(nxt, datetime.datetime(2026, 9, 14, 9, 0))

    def test_month_rollover(self):
        eve = datetime.datetime(2026, 9, 30, 23, 0)
        self.assertEqual(next_occurrence(DAILY, {"at": "09:00"}, eve),
                         datetime.datetime(2026, 10, 1, 9, 0))

    def test_year_rollover(self):
        eve = datetime.datetime(2026, 12, 31, 23, 0)
        self.assertEqual(next_occurrence(DAILY, {"at": "09:00"}, eve),
                         datetime.datetime(2027, 1, 1, 9, 0))

    def test_leap_day(self):
        eve = datetime.datetime(2028, 2, 28, 23, 0)
        self.assertEqual(next_occurrence(DAILY, {"at": "09:00"}, eve),
                         datetime.datetime(2028, 2, 29, 9, 0))

    def test_unusable_spec_yields_none(self):
        self.assertIsNone(next_occurrence(DAILY, {"at": "25:00"}, MON))
        self.assertIsNone(next_occurrence("cron", {}, MON))


class TestDaylightSaving(unittest.TestCase):
    """'Daily at 09:00' means 09:00 on the wall clock, both sides of a change.

    The maths is naive-local by design, and the next run is recomputed from a
    real timestamp rather than by adding a fixed delta -- adding deltas is what
    drifts by an hour twice a year.
    """

    def test_spring_forward_keeps_the_wall_clock_time(self):
        # 2026-03-29 is the European spring-forward Sunday.
        before = datetime.datetime(2026, 3, 28, 10, 0)
        runs = preview(DAILY, {"at": "09:00"}, before, 3)
        self.assertTrue(all(r.hour == 9 and r.minute == 0 for r in runs), runs)
        self.assertEqual([r.date().isoformat() for r in runs],
                         ["2026-03-29", "2026-03-30", "2026-03-31"])

    def test_autumn_back_keeps_the_wall_clock_time(self):
        before = datetime.datetime(2026, 10, 24, 10, 0)
        runs = preview(DAILY, {"at": "09:00"}, before, 3)
        self.assertTrue(all(r.hour == 9 for r in runs), runs)

    def test_weekly_keeps_its_weekday_across_the_change(self):
        runs = preview(WEEKLY, {"at": "09:00", "days": [6]},
                       datetime.datetime(2026, 3, 20, 10, 0), 3)
        self.assertTrue(all(r.weekday() == 6 for r in runs), runs)


class TestPreview(unittest.TestCase):

    def test_returns_the_requested_count_in_order(self):
        runs = preview(INTERVAL, {"minutes": 15}, MON, 4)
        self.assertEqual(len(runs), 4)
        self.assertEqual(runs, sorted(runs))

    def test_each_entry_is_strictly_later(self):
        runs = preview(DAILY, {"at": "09:00"}, MON, 5)
        self.assertTrue(all(b > a for a, b in zip(runs, runs[1:])))

    def test_unusable_spec_previews_nothing(self):
        self.assertEqual(preview(WEEKLY, {"at": "09:00", "days": []}, MON, 5), [])

    def test_zero_count(self):
        self.assertEqual(preview(DAILY, {"at": "09:00"}, MON, 0), [])


class TestResolveDue(unittest.TestCase):
    """What a schedule owes after RYOS has been closed."""

    SPEC = (DAILY, {"at": "09:00"})

    def test_not_due_yet_changes_nothing(self):
        later = datetime.datetime(2026, 9, 15, 9, 0)
        times, nxt = resolve_due(*self.SPEC, later, MON)
        self.assertEqual((times, nxt), (0, later))

    def test_never_scheduled_just_gets_a_next_time(self):
        times, nxt = resolve_due(*self.SPEC, None, MON)
        self.assertEqual(times, 0)
        self.assertEqual(nxt, datetime.datetime(2026, 9, 14, 9, 0))

    def test_skip_runs_nothing_but_moves_on(self):
        missed = datetime.datetime(2026, 9, 12, 9, 0)
        now = datetime.datetime(2026, 9, 14, 10, 0)
        times, nxt = resolve_due(*self.SPEC, missed, now, CATCH_UP_SKIP)
        self.assertEqual(times, 0)
        self.assertGreater(nxt, now)

    def test_once_runs_exactly_one_however_many_were_missed(self):
        missed = datetime.datetime(2026, 8, 1, 9, 0)      # six weeks of misses
        now = datetime.datetime(2026, 9, 14, 10, 0)
        times, nxt = resolve_due(*self.SPEC, missed, now, CATCH_UP_ONCE)
        self.assertEqual(times, 1)
        self.assertGreater(nxt, now)

    def test_all_runs_each_missed_occurrence(self):
        missed = datetime.datetime(2026, 9, 12, 9, 0)
        now = datetime.datetime(2026, 9, 14, 10, 0)
        times, _ = resolve_due(*self.SPEC, missed, now, CATCH_UP_ALL)
        self.assertEqual(times, 3)                        # 12th, 13th, 14th

    def test_all_is_capped(self):
        # A laptop closed for a fortnight must not come back to a stampede.
        missed = datetime.datetime(2026, 9, 1, 0, 0)
        now = datetime.datetime(2026, 9, 14, 0, 0)
        times, _ = resolve_due(INTERVAL, {"minutes": 1}, missed, now, CATCH_UP_ALL)
        self.assertEqual(times, MAX_CATCH_UP)

    def test_next_is_always_in_the_future(self):
        now = datetime.datetime(2026, 9, 14, 10, 0)
        for mode in (CATCH_UP_SKIP, CATCH_UP_ONCE, CATCH_UP_ALL):
            with self.subTest(mode=mode):
                _times, nxt = resolve_due(*self.SPEC,
                                          datetime.datetime(2026, 9, 1, 9, 0),
                                          now, mode)
                self.assertGreater(nxt, now)

    def test_a_clock_jump_backwards_does_not_rewind_the_schedule(self):
        # next_run_at is recomputed from `now`, never from the stale value.
        stale = datetime.datetime(2026, 9, 20, 9, 0)
        now = datetime.datetime(2026, 9, 14, 10, 0)
        times, nxt = resolve_due(*self.SPEC, stale, now, CATCH_UP_ONCE)
        self.assertEqual((times, nxt), (0, stale))

    def test_unusable_spec_stops_scheduling(self):
        times, nxt = resolve_due(WEEKLY, {"at": "09:00", "days": []}, MON, MON)
        self.assertEqual(times, 0)
        self.assertIsNone(nxt)


class TestDescribe(unittest.TestCase):

    def test_minutes(self):
        self.assertEqual(describe_spec(INTERVAL, {"minutes": 30}), "Every 30 minutes")

    def test_singular_minute(self):
        self.assertEqual(describe_spec(INTERVAL, {"minutes": 1}), "Every 1 minute")

    def test_whole_hours_read_as_hours(self):
        self.assertEqual(describe_spec(INTERVAL, {"minutes": 120}), "Every 2 hours")

    def test_daily(self):
        self.assertEqual(describe_spec(DAILY, {"at": "09:00"}), "Daily at 09:00")

    def test_weekly_names_its_days(self):
        self.assertEqual(describe_spec(WEEKLY, {"at": "18:30", "days": [0, 2]}),
                         "Mon, Wed at 18:30")

    def test_invalid_says_so(self):
        self.assertEqual(describe_spec(DAILY, {"at": "nope"}), "Invalid schedule")


class TestScheduleStorage(unittest.TestCase):

    def setUp(self):
        self.db = _make_db()
        self.sid = self.db.add("s", "/s.py", "", "", "G")
        self.now = datetime.datetime(2026, 9, 14, 10, 0)

    def _add(self, **kw):
        opts = dict(script_id=self.sid, spec_type=DAILY,
                    spec=json.dumps({"at": "09:00"}))
        opts.update(kw)
        return self.db.add_schedule("script", **opts)

    def test_disabled_by_default(self):
        # A schedule that started firing before its owner saw the preview
        # would be a nasty surprise.
        self._add()
        self.assertEqual(self.db.get_schedule(script_id=self.sid)[6], 0)

    def test_round_trip(self):
        self._add(enabled=True, catch_up=CATCH_UP_SKIP,
                  next_run_at=self.now)
        row = self.db.get_schedule(script_id=self.sid)
        self.assertEqual(row[4], DAILY)
        self.assertEqual(json.loads(row[5]), {"at": "09:00"})
        self.assertEqual(row[6], 1)
        self.assertEqual(row[7], CATCH_UP_SKIP)

    def test_due_when_next_run_has_passed(self):
        self._add(enabled=True, next_run_at=self.now - datetime.timedelta(hours=1))
        self.assertEqual(len(self.db.due_schedules(self.now)), 1)

    def test_not_due_before_its_time(self):
        self._add(enabled=True, next_run_at=self.now + datetime.timedelta(hours=1))
        self.assertEqual(self.db.due_schedules(self.now), [])

    def test_disabled_is_never_due(self):
        self._add(enabled=False, next_run_at=self.now - datetime.timedelta(days=1))
        self.assertEqual(self.db.due_schedules(self.now), [])

    def test_null_next_run_is_due(self):
        # Otherwise a schedule enabled without one would sit inert forever.
        self._add(enabled=True, next_run_at=None)
        self.assertEqual(len(self.db.due_schedules(self.now)), 1)

    def test_marking_fired_advances_and_clears_due(self):
        sched = self._add(enabled=True, next_run_at=self.now - datetime.timedelta(hours=1))
        self.db.mark_schedule_fired(sched, self.now + datetime.timedelta(days=1), self.now)
        self.assertEqual(self.db.due_schedules(self.now), [])
        row = self.db.get_schedule(script_id=self.sid)
        self.assertIsNotNone(row[9])            # last_run_at recorded

    def test_marking_without_a_last_run_leaves_it_alone(self):
        # A skipped run advances next_run_at but must not claim it ran.
        sched = self._add(enabled=True, next_run_at=self.now)
        self.db.mark_schedule_fired(sched, self.now + datetime.timedelta(days=1))
        self.assertIsNone(self.db.get_schedule(script_id=self.sid)[9])

    def test_scheduled_ids_only_lists_enabled(self):
        self._add(enabled=True)
        other = self.db.add("o", "/o.py", "", "", "G")
        self.db.add_schedule("script", script_id=other, spec_type=DAILY,
                             spec=json.dumps({"at": "09:00"}), enabled=False)
        scripts, pipelines = self.db.scheduled_ids()
        self.assertEqual(scripts, {self.sid})
        self.assertEqual(pipelines, set())

    def test_pipeline_schedules_are_separate(self):
        pid = self.db.create_pipeline("P", "G")
        self.db.add_schedule("pipeline", pipeline_id=pid, spec_type=DAILY,
                             spec=json.dumps({"at": "09:00"}), enabled=True)
        scripts, pipelines = self.db.scheduled_ids()
        self.assertEqual(pipelines, {pid})
        self.assertEqual(scripts, set())
        self.assertIsNotNone(self.db.get_schedule(pipeline_id=pid))

    def test_delete(self):
        sched = self._add()
        self.db.delete_schedule(sched)
        self.assertIsNone(self.db.get_schedule(script_id=self.sid))

    def test_update_replaces_the_spec(self):
        sched = self._add()
        self.db.update_schedule(sched, spec_type=INTERVAL,
                                spec=json.dumps({"minutes": 15}),
                                catch_up=CATCH_UP_ALL, enabled=True,
                                next_run_at=self.now)
        row = self.db.get_schedule(script_id=self.sid)
        self.assertEqual(row[4], INTERVAL)
        self.assertEqual(row[7], CATCH_UP_ALL)
        self.assertEqual(row[6], 1)

    def test_no_schedule_reads_as_none(self):
        self.assertIsNone(self.db.get_schedule(script_id=self.sid))


# ---------------------------------------------------------------------------
# Row widths (tripwire for the widened-tuple regression class)
# ---------------------------------------------------------------------------

class TestRowWidthsArePinned(unittest.TestCase):
    """Widening a DB row has broken a fixed-arity unpack in the UI three times.

    db.get() grew temp_param and later env_vars/work_dir, breaking
    ScriptCard._run; list_pipeline_steps grew trigger_mode and later the same
    two columns, breaking the pipeline editor so its step list came up empty
    (issue #2). Both shipped, because the headless suite mocks Tk and never
    executes those widget paths.

    These pins do not stop anyone widening a row -- they make it deliberate.
    When one fails, update the number here AND check that accessor's consumers
    slice (row[:N]) rather than unpacking a fixed number of names.
    """

    EXPECTED_WIDTHS = {
        "list_all": 12,
        "get": 9,
        "list_pipelines": 4,
        "list_pipeline_steps": 14,
        "list_param_presets": 3,
        "list_runs": 11,
        "list_schedules": 11,
        "list_groups_with_meta": 2,
    }

    @classmethod
    def setUpClass(cls):
        cls.db = _make_db()
        cls.db.create_group("G")     # db.add() doesn't create the group row
        cls.sid = cls.db.add("s", "/s.py", "--p", "python", "G")
        cls.pid = cls.db.create_pipeline("P", "G")
        cls.db.add_pipeline_step(cls.pid, cls.sid)
        cls.db.replace_param_presets(cls.sid, [("fast", "--fast")])
        cls.db.record_run(RUN_SCRIPT, name="s", script_id=cls.sid,
                          started_at=datetime.datetime.now(), status="ok")
        cls.db.add_schedule("script", script_id=cls.sid, spec_type=DAILY,
                            spec=json.dumps({"at": "09:00"}))

    def _rows(self, name):
        calls = {
            "list_all": lambda: self.db.list_all(),
            "get": lambda: [self.db.get(self.sid)],
            "list_pipelines": lambda: self.db.list_pipelines("G"),
            "list_pipeline_steps": lambda: self.db.list_pipeline_steps(self.pid),
            "list_param_presets": lambda: self.db.list_param_presets(self.sid),
            "list_runs": lambda: self.db.list_runs(script_id=self.sid),
            "list_schedules": lambda: self.db.list_schedules(script_id=self.sid),
            "list_groups_with_meta": lambda: self.db.list_groups_with_meta(),
        }
        return calls[name]()

    def test_widths(self):
        for name, width in self.EXPECTED_WIDTHS.items():
            with self.subTest(accessor=name):
                rows = self._rows(name)
                self.assertTrue(rows, f"{name} returned nothing to measure")
                self.assertEqual(
                    len(rows[0]), width,
                    f"{name} row width changed ({len(rows[0])} != {width}). "
                    f"Update the pin AND check its consumers slice row[:N] "
                    f"instead of unpacking a fixed number of names.")

    def test_every_pinned_accessor_still_exists(self):
        for name in self.EXPECTED_WIDTHS:
            with self.subTest(accessor=name):
                self.assertTrue(callable(getattr(self.db, name, None)))


class TestPipelineEditorUnpacksDefensively(unittest.TestCase):
    """The editor's step rows must be sliced, not unpacked whole.

    The GUI smoke test covers this behaviourally, but that only runs under
    Xvfb; this catches a reintroduction in the headless suite too.
    """

    SRC = Path(__file__).resolve().parents[1] / "ryos" / "ui" / "pipeline.py"

    def test_no_fixed_arity_unpack_of_a_step_row(self):
        tree = ast.parse(self.SRC.read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                target = node.targets[0]
                value = node.value
            elif isinstance(node, ast.For):
                target, value = node.target, node.iter
            else:
                continue
            if not isinstance(target, ast.Tuple):
                continue
            # A slice (row[:8]) or a starred name is width-tolerant.
            if isinstance(value, ast.Subscript) and isinstance(value.slice, ast.Slice):
                continue
            if any(isinstance(e, ast.Starred) for e in target.elts):
                continue
            if len(target.elts) >= 6:
                offenders.append(node.lineno)
        self.assertEqual(offenders, [],
                         "pipeline.py unpacks a wide row at these lines; "
                         "slice it (row[:8]) so a new column can't empty the list")


# ---------------------------------------------------------------------------
# Per-step failure policy (on_failure / retries / run_when)
# ---------------------------------------------------------------------------
from ryos.db import (  # noqa: E402
    FAIL_CONTINUE, FAIL_STOP, WHEN_ALWAYS, WHEN_ON_FAILURE, WHEN_ON_SUCCESS,
)
from ryos.job_controller import (  # noqa: E402
    should_run_step, step_on_failure, step_retries, step_run_when,
)
from ryos.ui.pipeline import _policy_marks  # noqa: E402


def _policy_step(name="s", *, mode=TRIGGER_AFTER, on_failure=FAIL_STOP,
                 retries=0, run_when=WHEN_ALWAYS, path=None):
    """A 13-wide step row, the shape list_pipeline_steps returns."""
    return (1, 1, name, path or __file__, "", "", None, mode, None, "",
            on_failure, retries, run_when)


class TestStepPolicyReaders(unittest.TestCase):
    """Rows narrower than 13 predate these columns and must read as defaults."""

    def test_defaults_from_a_full_row(self):
        row = _policy_step()
        self.assertEqual(step_on_failure(row), FAIL_STOP)
        self.assertEqual(step_retries(row), 0)
        self.assertEqual(step_run_when(row), WHEN_ALWAYS)

    def test_short_row_reads_as_default(self):
        short = (1, 1, "s", "/s.py", "", "", None, TRIGGER_AFTER)
        self.assertEqual(step_on_failure(short), FAIL_STOP)
        self.assertEqual(step_retries(short), 0)
        self.assertEqual(step_run_when(short), WHEN_ALWAYS)

    def test_values_are_read_back(self):
        row = _policy_step(on_failure=FAIL_CONTINUE, retries=3,
                           run_when=WHEN_ON_FAILURE)
        self.assertEqual(step_on_failure(row), FAIL_CONTINUE)
        self.assertEqual(step_retries(row), 3)
        self.assertEqual(step_run_when(row), WHEN_ON_FAILURE)

    def test_unusable_retries_read_as_zero(self):
        # This sits on the run path; a bad value must not raise mid-pipeline.
        for bad in ("lots", None, -4):
            with self.subTest(retries=bad):
                self.assertEqual(step_retries(_policy_step(retries=bad)), 0)


class TestShouldRunStep(unittest.TestCase):
    """The condition is the whole of run_when's behaviour, so pin every case."""

    def test_always_runs_normally(self):
        self.assertTrue(should_run_step(_policy_step(), failed=False, stopping=False))
        self.assertTrue(should_run_step(_policy_step(), failed=True, stopping=False))

    def test_always_is_skipped_once_stopping(self):
        # This is what reproduces the original behaviour, where a failure
        # cleared the queue outright.
        self.assertFalse(should_run_step(_policy_step(), failed=True, stopping=True))

    def test_on_success_needs_a_clean_run(self):
        step = _policy_step(run_when=WHEN_ON_SUCCESS)
        self.assertTrue(should_run_step(step, failed=False, stopping=False))
        self.assertFalse(should_run_step(step, failed=True, stopping=False))

    def test_on_success_is_skipped_after_a_tolerated_failure(self):
        # A continue step's failure still counts as "something has failed".
        step = _policy_step(run_when=WHEN_ON_SUCCESS)
        self.assertFalse(should_run_step(step, failed=True, stopping=False))

    def test_on_failure_needs_a_failure(self):
        step = _policy_step(run_when=WHEN_ON_FAILURE)
        self.assertFalse(should_run_step(step, failed=False, stopping=False))
        self.assertTrue(should_run_step(step, failed=True, stopping=False))

    def test_on_failure_survives_stopping(self):
        # Cleanup steps are precisely the ones that must still run.
        step = _policy_step(run_when=WHEN_ON_FAILURE)
        self.assertTrue(should_run_step(step, failed=True, stopping=True))

    def test_short_rows_behave_like_always(self):
        short = (1, 1, "s", "/s.py", "", "", None, TRIGGER_AFTER)
        self.assertTrue(should_run_step(short, failed=False, stopping=False))
        self.assertFalse(should_run_step(short, failed=True, stopping=True))


class TestPolicyMarks(unittest.TestCase):
    """Only deviations are marked, so ordinary pipelines look untouched."""

    def test_all_defaults_mark_nothing(self):
        self.assertEqual(_policy_marks(_policy_step()), "")

    def test_short_row_marks_nothing(self):
        self.assertEqual(_policy_marks((1, 1, "s", "/s.py", "", "", None, "after")), "")

    def test_continue(self):
        self.assertIn("!", _policy_marks(_policy_step(on_failure=FAIL_CONTINUE)))

    def test_retries(self):
        self.assertIn("↻3", _policy_marks(_policy_step(retries=3)))

    def test_conditions(self):
        self.assertIn("?ok", _policy_marks(_policy_step(run_when=WHEN_ON_SUCCESS)))
        self.assertIn("?fail", _policy_marks(_policy_step(run_when=WHEN_ON_FAILURE)))


class TestStepPolicyStorage(unittest.TestCase):

    def setUp(self):
        self.db = _make_db()
        self.sid = self.db.add("s", "/s.py", "", "", "G")
        self.pid = self.db.create_pipeline("P", "G")
        self.db.add_pipeline_step(self.pid, self.sid)
        self.step_id = self.db.list_pipeline_steps(self.pid)[0][0]

    def _row(self):
        return self.db.list_pipeline_steps(self.pid)[0]

    def test_defaults_reproduce_the_old_behaviour(self):
        row = self._row()
        self.assertEqual((row[10], row[11], row[12]),
                         (FAIL_STOP, 0, WHEN_ALWAYS))

    def test_set_and_read_back(self):
        self.db.set_step_policy(self.step_id, on_failure=FAIL_CONTINUE,
                                retries=2, run_when=WHEN_ON_FAILURE)
        row = self._row()
        self.assertEqual((row[10], row[11], row[12]),
                         (FAIL_CONTINUE, 2, WHEN_ON_FAILURE))

    def test_none_leaves_a_field_untouched(self):
        self.db.set_step_policy(self.step_id, retries=4)
        self.db.set_step_policy(self.step_id, on_failure=FAIL_CONTINUE)
        row = self._row()
        self.assertEqual(row[11], 4, "retries was clobbered")
        self.assertEqual(row[10], FAIL_CONTINUE)

    def test_unknown_values_are_clamped(self):
        # These columns are NOT NULL and drive branching; a stray value would
        # make a step neither one thing nor the other at runtime.
        self.db.set_step_policy(self.step_id, on_failure="maybe",
                                retries=-3, run_when="whenever")
        row = self._row()
        self.assertEqual((row[10], row[11], row[12]),
                         (FAIL_STOP, 0, WHEN_ALWAYS))

    def test_no_arguments_is_a_noop(self):
        self.db.set_step_policy(self.step_id)
        self.assertEqual(self._row()[10], FAIL_STOP)

    def test_clone_pipeline_carries_the_policy(self):
        self.db.set_step_policy(self.step_id, on_failure=FAIL_CONTINUE,
                                retries=2, run_when=WHEN_ON_FAILURE)
        new_id = self.db.clone_pipeline(self.pid)
        row = self.db.list_pipeline_steps(new_id)[0]
        self.assertEqual((row[10], row[11], row[12]),
                         (FAIL_CONTINUE, 2, WHEN_ON_FAILURE))

    def test_clone_group_carries_the_policy(self):
        self.db.create_group("G")
        self.db.set_step_policy(self.step_id, on_failure=FAIL_CONTINUE, retries=1)
        self.db.clone_group("G", "G2")
        new_pid = self.db.list_pipelines("G2")[0][0]
        row = self.db.list_pipeline_steps(new_pid)[0]
        self.assertEqual((row[10], row[11]), (FAIL_CONTINUE, 1))

    def test_export_import_round_trip(self):
        self.db.set_step_policy(self.step_id, on_failure=FAIL_CONTINUE,
                                retries=2, run_when=WHEN_ON_FAILURE)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        self.db.export_to_file(path)
        other = _make_db()
        other.import_from_file(path)
        pid = other.list_pipelines("G")[0][0]
        row = other.list_pipeline_steps(pid)[0]
        self.assertEqual((row[10], row[11], row[12]),
                         (FAIL_CONTINUE, 2, WHEN_ON_FAILURE))

    def test_import_clamps_hostile_values(self):
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w",
                                         delete=False, encoding="utf-8") as f:
            json.dump({
                "version": 6,
                "groups": [{"name": "G", "sort_order": 0, "base_dir": ""}],
                "scripts": [{"name": "a", "path": "/a.py", "params": "",
                             "interpreter": "", "order_index": 0,
                             "group_name": "G", "presets": []}],
                "pipelines": [{"name": "P2", "group_name": "G", "sort_order": 0,
                               "steps": [{"script_path": "/a.py",
                                          "on_failure": "sometimes",
                                          "retries": "many",
                                          "run_when": "whenever"}]}],
            }, f)
            path = f.name
        other = _make_db()
        other.import_from_file(path)
        pid = [p[0] for p in other.list_pipelines("G") if p[1] == "P2"][0]
        row = other.list_pipeline_steps(pid)[0]
        self.assertEqual((row[10], row[11], row[12]),
                         (FAIL_STOP, 0, WHEN_ALWAYS))


class TestPipelineFailurePolicy(unittest.TestCase):
    """End-to-end through the real controller, with scripted step outcomes.

    The default case must stay byte-identical to the behaviour before any of
    this existed: a failure stops the run and later steps never start.
    """

    def setUp(self):
        self.outcomes: dict = {}
        self.launched: list = []
        self.notified: list = []
        self.reg = JobRegistry()
        self.q = _queue.Queue()
        self.ctl = JobController(
            self.reg, self.q, _make_db(),
            on_output=lambda *a: None, on_status=lambda *a: None,
            on_notify=lambda t, b: self.notified.append(t),
            on_started=lambda *a: None, on_finish=lambda *a: None,
            on_rename=lambda *a: None, launch=self._launch,
        )

    def _launch(self, job, spec, name, sid, token=None):
        self.launched.append(name)
        seq = self.outcomes.get(name, ["ok"])
        status = seq.pop(0) if len(seq) > 1 else (seq[0] if seq else "ok")
        self.q.put(("done_tag", job.job_id, sid, status, "ok", "", token))

    def _run(self, steps, outcomes=None):
        self.outcomes = {k: list(v) for k, v in (outcomes or {}).items()}
        job = Job(1, "pipeline", None, 1, "p", "job:1", "g", pipeline_name="P",
                  pipeline_queue=list(steps), pipeline_total=len(steps))
        self.reg.add(job)
        self.ctl.run_next_pipeline_step(job)
        for _ in range(200):
            if self.q.empty():
                break
            self.ctl.pump()
        return job

    @property
    def verdict(self):
        if not self.notified:
            return "unfinished"
        return "ok" if "passed" in self.notified[-1] else "error"

    # ---- the default must not have changed ----

    def test_default_failure_stops_the_run(self):
        self._run([_policy_step("a"), _policy_step("b"), _policy_step("c")],
                  {"b": ["error"]})
        self.assertEqual(self.launched, ["a", "b"])
        self.assertEqual(self.verdict, "error")

    def test_default_clean_run_passes(self):
        self._run([_policy_step("a"), _policy_step("b")])
        self.assertEqual(self.launched, ["a", "b"])
        self.assertEqual(self.verdict, "ok")

    # ---- continue ----

    def test_continue_lets_the_run_carry_on(self):
        self._run([_policy_step("a"),
                   _policy_step("b", on_failure=FAIL_CONTINUE),
                   _policy_step("c")], {"b": ["error"]})
        self.assertEqual(self.launched, ["a", "b", "c"])

    def test_a_tolerated_failure_does_not_fail_the_run(self):
        self._run([_policy_step("a", on_failure=FAIL_CONTINUE)], {"a": ["error"]})
        self.assertEqual(self.verdict, "ok")

    # ---- retries ----

    def test_retry_until_success(self):
        self._run([_policy_step("a", retries=2)], {"a": ["error", "error", "ok"]})
        self.assertEqual(self.launched, ["a", "a", "a"])
        self.assertEqual(self.verdict, "ok")

    def test_retries_are_bounded(self):
        self._run([_policy_step("a", retries=1)], {"a": ["error"]})
        self.assertEqual(self.launched, ["a", "a"])
        self.assertEqual(self.verdict, "error")

    def test_no_retry_on_success(self):
        self._run([_policy_step("a", retries=3)])
        self.assertEqual(self.launched, ["a"])

    def test_retry_then_continue(self):
        # Retries exhaust first, then the failure policy decides.
        self._run([_policy_step("a", retries=1, on_failure=FAIL_CONTINUE),
                   _policy_step("b")], {"a": ["error"]})
        self.assertEqual(self.launched, ["a", "a", "b"])
        self.assertEqual(self.verdict, "ok")

    # ---- run_when ----

    def test_on_failure_step_runs_after_a_failure(self):
        self._run([_policy_step("a"), _policy_step("b"),
                   _policy_step("cleanup", run_when=WHEN_ON_FAILURE)],
                  {"b": ["error"]})
        self.assertEqual(self.launched, ["a", "b", "cleanup"])

    def test_the_run_still_fails_after_a_successful_cleanup(self):
        # A cleanup step succeeding must not turn the pipeline green.
        self._run([_policy_step("a"),
                   _policy_step("cleanup", run_when=WHEN_ON_FAILURE)],
                  {"a": ["error"]})
        self.assertEqual(self.verdict, "error")

    def test_on_failure_step_is_skipped_on_a_clean_run(self):
        self._run([_policy_step("a"),
                   _policy_step("cleanup", run_when=WHEN_ON_FAILURE)])
        self.assertEqual(self.launched, ["a"])
        self.assertEqual(self.verdict, "ok")

    def test_on_success_step_is_skipped_after_a_tolerated_failure(self):
        self._run([_policy_step("a", on_failure=FAIL_CONTINUE),
                   _policy_step("b", run_when=WHEN_ON_SUCCESS)],
                  {"a": ["error"]})
        self.assertEqual(self.launched, ["a"])

    def test_a_queue_of_only_skippable_steps_still_finishes(self):
        # Regression: skipping emptied the queue without anything reaching a
        # terminal state, so the job sat in Running forever.
        self._run([_policy_step("a"),
                   _policy_step("b", run_when=WHEN_ON_FAILURE)])
        self.assertNotEqual(self.verdict, "unfinished")

    # ---- concurrent groups ----

    def test_a_tolerated_member_failure_does_not_poison_the_group(self):
        self._run([_policy_step("a"),
                   _policy_step("b", mode=TRIGGER_WITH, on_failure=FAIL_CONTINUE),
                   _policy_step("c")], {"b": ["error"]})
        self.assertEqual(self.launched, ["a", "b", "c"])
        self.assertEqual(self.verdict, "ok")

    def test_a_stop_member_failure_fails_the_group(self):
        self._run([_policy_step("a"), _policy_step("b", mode=TRIGGER_WITH),
                   _policy_step("c")], {"b": ["error"]})
        self.assertEqual(self.launched, ["a", "b"])
        self.assertEqual(self.verdict, "error")

    def test_retry_relaunches_only_the_failing_member(self):
        # Retrying the group would re-run siblings that already succeeded.
        self._run([_policy_step("a"),
                   _policy_step("b", mode=TRIGGER_WITH, retries=1)],
                  {"b": ["error", "ok"]})
        self.assertEqual(self.launched, ["a", "b", "b"])
        self.assertEqual(self.verdict, "ok")


# ---------------------------------------------------------------------------
# Output-panel find (ryos.search)
# ---------------------------------------------------------------------------
from ryos.search import find_spans, step_match  # noqa: E402


class TestFindSpans(unittest.TestCase):
    """Offsets, not line/column: Tk takes '1.0 + N chars' directly."""

    def test_single_match(self):
        self.assertEqual(find_spans("hello world", "world"), [(6, 11)])

    def test_several_matches(self):
        self.assertEqual(find_spans("ab ab ab", "ab"), [(0, 2), (3, 5), (6, 8)])

    def test_case_insensitive(self):
        self.assertEqual(find_spans("Hello HELLO hello", "hello"),
                         [(0, 5), (6, 11), (12, 17)])

    def test_matches_do_not_overlap(self):
        # "aa" in "aaaa" is two matches, not three.
        self.assertEqual(find_spans("aaaa", "aa"), [(0, 2), (2, 4)])

    def test_blank_needle_matches_nothing(self):
        # Highlighting every character the moment the box is focused would be
        # useless and slow.
        self.assertEqual(find_spans("anything", ""), [])

    def test_empty_haystack(self):
        self.assertEqual(find_spans("", "x"), [])

    def test_no_match(self):
        self.assertEqual(find_spans("abc", "zzz"), [])

    def test_needle_longer_than_haystack(self):
        self.assertEqual(find_spans("ab", "abcdef"), [])

    def test_spans_are_usable_slices(self):
        hay = "the ERROR was an ERROR"
        for start, end in find_spans(hay, "error"):
            with self.subTest(start=start):
                self.assertEqual(hay[start:end].lower(), "error")

    def test_newlines_are_just_characters(self):
        # The offsets index the raw buffer, newlines included.
        self.assertEqual(find_spans("a\nb\nab", "ab"), [(4, 6)])


class TestStepMatch(unittest.TestCase):

    def test_no_matches(self):
        self.assertIsNone(step_match(0, None))
        self.assertIsNone(step_match(0, 3))

    def test_first_step_forward_lands_on_the_first(self):
        self.assertEqual(step_match(3, None, True), 0)

    def test_first_step_backward_lands_on_the_last(self):
        self.assertEqual(step_match(3, None, False), 2)

    def test_forward_advances(self):
        self.assertEqual([step_match(3, c, True) for c in (0, 1)], [1, 2])

    def test_forward_wraps(self):
        self.assertEqual(step_match(3, 2, True), 0)

    def test_backward_wraps(self):
        self.assertEqual(step_match(3, 0, False), 2)

    def test_single_match_stays_put(self):
        self.assertEqual(step_match(1, 0, True), 0)
        self.assertEqual(step_match(1, 0, False), 0)

    def test_round_trip_returns_to_the_start(self):
        idx = None
        for _ in range(4):
            idx = step_match(4, idx, True)
        self.assertEqual(idx, 3)
        self.assertEqual(step_match(4, idx, True), 0)


# ---------------------------------------------------------------------------
# Bulk-run capacity (ryos.jobs.split_by_capacity)
# ---------------------------------------------------------------------------
from ryos.jobs import split_by_capacity  # noqa: E402


class TestSplitByCapacity(unittest.TestCase):
    """Resolved once, up front, so the caller refuses the remainder with a
    single message instead of one rejection box per script."""

    def test_everything_fits(self):
        self.assertEqual(split_by_capacity(5, 0, 10), (5, 0))

    def test_partial_fit(self):
        self.assertEqual(split_by_capacity(5, 8, 10), (2, 3))

    def test_exactly_full(self):
        self.assertEqual(split_by_capacity(5, 10, 10), (0, 5))

    def test_fills_the_last_slot(self):
        self.assertEqual(split_by_capacity(1, 9, 10), (1, 0))

    def test_zero_cap_means_unlimited(self):
        # The setting uses <= 0 for "no limit".
        self.assertEqual(split_by_capacity(5, 99, 0), (5, 0))

    def test_negative_cap_means_unlimited(self):
        self.assertEqual(split_by_capacity(4, 99, -1), (4, 0))

    def test_nothing_requested(self):
        self.assertEqual(split_by_capacity(0, 3, 10), (0, 0))

    def test_registry_over_the_cap(self):
        # Shouldn't happen, but must not yield negative capacity.
        self.assertEqual(split_by_capacity(3, 20, 10), (0, 3))

    def test_negative_inputs_are_clamped(self):
        self.assertEqual(split_by_capacity(-2, 0, 10), (0, 0))
        self.assertEqual(split_by_capacity(3, -5, 10), (3, 0))

    def test_the_two_halves_always_account_for_everything(self):
        for requested in range(0, 8):
            for running in range(0, 8):
                for cap in (0, 1, 5, 10):
                    with self.subTest(requested=requested, running=running, cap=cap):
                        can, skipped = split_by_capacity(requested, running, cap)
                        self.assertEqual(can + skipped, requested)
                        self.assertGreaterEqual(can, 0)
                        self.assertGreaterEqual(skipped, 0)

    def test_never_exceeds_the_cap(self):
        for running in range(0, 12):
            with self.subTest(running=running):
                can, _ = split_by_capacity(20, running, 10)
                self.assertLessEqual(running + can, max(running, 10))


# ---------------------------------------------------------------------------
# Launcher steps (issue #5)
# ---------------------------------------------------------------------------

class TestLauncherStepRelease(unittest.TestCase):
    """A launcher step is settled without waiting for its process to exit.

    The ordering is the delicate part: the step must be settled through the
    normal completion path *first*, and only then marked released -- marking it
    first would make handle_step_done ignore the very call releasing it, which
    is exactly the bug the first attempt shipped.
    """

    def setUp(self):
        self.db = _make_db()
        self.launched = []
        self.finished = []
        self.reg = JobRegistry()
        self.q = _queue.Queue()
        self.ctl = JobController(
            self.reg, self.q, self.db,
            on_output=lambda *a: None, on_status=lambda *a: None,
            on_notify=lambda *a: None, on_started=lambda *a: None,
            on_finish=lambda j: self.finished.append(j),
            on_rename=lambda *a: None,
            launch=lambda job, spec, name, sid, tok=None:
                self.launched.append((name, tok)),
        )

    def _job(self, steps):
        job = Job(1, "pipeline", None, 1, "p", "job:1", "g", pipeline_name="P",
                  pipeline_queue=list(steps), pipeline_total=len(steps))
        self.reg.add(job)
        return job

    def _step(self, sid, name):
        return (sid, sid, name, __file__, "", "", None, TRIGGER_AFTER,
                None, "", FAIL_STOP, 0, WHEN_ALWAYS, 0)

    def test_release_advances_to_the_next_step(self):
        job = self._job([self._step(1, "launcher"), self._step(2, "next")])
        self.ctl.run_next_pipeline_step(job)
        self.assertEqual([n for n, _ in self.launched], ["launcher"])
        released = self.ctl.release_launcher_step(job, 1, 1)
        self.assertTrue(released)
        self.assertEqual([n for n, _ in self.launched], ["launcher", "next"])

    def test_release_settles_before_marking(self):
        # If the token were marked released first, handle_step_done would
        # ignore it and the pipeline would never move.
        job = self._job([self._step(1, "launcher"), self._step(2, "next")])
        self.ctl.run_next_pipeline_step(job)
        self.ctl.release_launcher_step(job, 1, 1)
        self.assertIn(1, job.released_steps)
        self.assertNotIn(1, job.group_pending)

    def test_the_real_completion_is_ignored_afterwards(self):
        job = self._job([self._step(1, "launcher"), self._step(2, "next")])
        self.ctl.run_next_pipeline_step(job)
        self.ctl.release_launcher_step(job, 1, 1)
        before = list(self.launched)
        # The launcher finally exits, long after it was released.
        self.ctl.handle_step_done(job, 1, "error", token=1)
        self.assertEqual(self.launched, before,
                         "a late launcher completion disturbed the run")
        self.assertFalse(job.pipeline_stopping,
                         "a late launcher failure failed the pipeline")

    def test_a_late_completion_cannot_consume_another_pending_step(self):
        # Without the released_steps guard this hits the untagged fallback,
        # which pops an unrelated pending token -- corrupting a later group.
        job = self._job([self._step(1, "launcher"), self._step(2, "next")])
        self.ctl.run_next_pipeline_step(job)
        self.ctl.release_launcher_step(job, 1, 1)
        pending_now = set(job.group_pending)
        self.ctl.handle_step_done(job, 1, "ok", token=1)
        self.assertEqual(job.group_pending, pending_now,
                         "a late completion consumed the running step")

    def test_release_records_history_for_the_step(self):
        job = self._job([self._step(7, "launcher")])
        self.ctl.run_next_pipeline_step(job)
        self.ctl.release_launcher_step(job, 1, 7)
        steps = [r for r in self.db.list_runs(pipeline_id=1) if r[3] == RUN_STEP]
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0][7], "ok")

    def test_release_is_a_noop_once_the_step_finished(self):
        job = self._job([self._step(1, "launcher"), self._step(2, "next")])
        self.ctl.run_next_pipeline_step(job)
        self.ctl.handle_step_done(job, 1, "ok", token=1)     # exited on its own
        launched_after = list(self.launched)
        self.assertFalse(self.ctl.release_launcher_step(job, 1, 1))
        self.assertEqual(self.launched, launched_after)

    def test_release_is_a_noop_on_a_stopped_run(self):
        job = self._job([self._step(1, "launcher"), self._step(2, "next")])
        self.ctl.run_next_pipeline_step(job)
        job.stopped = True
        self.assertFalse(self.ctl.release_launcher_step(job, 1, 1))

    def test_release_completes_a_one_step_pipeline(self):
        job = self._job([self._step(1, "launcher")])
        self.ctl.run_next_pipeline_step(job)
        self.ctl.release_launcher_step(job, 1, 1)
        self.assertEqual(len(self.finished), 1,
                         "releasing the only step did not finish the pipeline")

    def test_detached_flag_reaches_the_step_row(self):
        db = _make_db()
        db.create_group("G")
        sid = db.add("launcher", "/l.py", "", "", "G", detached=1)
        plain = db.add("plain", "/p.py", "", "", "G")
        pid = db.create_pipeline("P", "G")
        db.add_pipeline_step(pid, sid)
        db.add_pipeline_step(pid, plain)
        rows = db.list_pipeline_steps(pid)
        self.assertEqual(rows[0][13], 1)
        self.assertEqual(rows[1][13], 0)


# ---------------------------------------------------------------------------
# Documentation drift
# ---------------------------------------------------------------------------

class TestDocsMatchTheCode(unittest.TestCase):
    """The reference docs drifted three months behind the code once already.

    By the time anyone noticed, API_REFERENCE documented list_pipeline_steps as
    a 7-tuple that had been 14 fields for months, and 23 of 61 public ScriptDB
    methods were missing entirely. Stale prose is cheap to tolerate and
    expensive to trust, so the parts that can be checked mechanically are
    checked here, on every push.

    These assertions are deliberately shallow -- they check that names exist
    and that specific known-wrong claims are gone. They cannot tell whether a
    description is *good*, only whether it is about something real.
    """

    ROOT = Path(__file__).resolve().parents[1]

    def _read(self, *parts):
        return (self.ROOT.joinpath(*parts)).read_text(encoding="utf-8")

    def test_every_public_scriptdb_method_is_documented(self):
        import inspect
        api = self._read("docs", "API_REFERENCE.md")
        section = api[api.index("## `ryos.db`"):api.index("## `ryos.interpreter`")]
        documented = {n for n in re.findall(r"`([a-z_][a-z0-9_]*)\(", section)
                      if not n.startswith("_")}
        actual = {n for n, _ in inspect.getmembers(ScriptDB, inspect.isfunction)
                  if not n.startswith("_")}
        missing = sorted(actual - documented)
        self.assertEqual(missing, [],
                         f"undocumented ScriptDB methods: {missing}")

    def test_the_reference_documents_no_phantom_methods(self):
        import inspect
        api = self._read("docs", "API_REFERENCE.md")
        section = api[api.index("## `ryos.db`"):api.index("## `ryos.interpreter`")]
        documented = {n for n in re.findall(r"`([a-z_][a-z0-9_]*)\(", section)
                      if not n.startswith("_")}
        actual = {n for n, _ in inspect.getmembers(ScriptDB, inspect.isfunction)
                  if not n.startswith("_")}
        phantom = sorted(documented - actual - {"max", "int"})
        self.assertEqual(phantom, [],
                         f"documented but nonexistent: {phantom}")

    def test_row_shapes_in_the_docs_match_the_queries(self):
        # The exact failure that shipped twice: a widened row, documented at
        # its old width.
        api = self._read("docs", "API_REFERENCE.md")
        db = _make_db()
        db.create_group("G")
        sid = db.add("s", "/s.py", "", "", "G")
        pid = db.create_pipeline("P", "G")
        db.add_pipeline_step(pid, sid)
        for claim in (f"list of **{len(db.list_pipeline_steps(pid)[0])}-tuples**",
                      f"{len(db.get(sid))}-tuple or `None`",
                      f"list of {len(db.list_all()[0])}-tuples"):
            # Assert on a short message: dumping the whole document here makes
            # the real failure unreadable.
            self.assertTrue(claim in api,
                            f"API_REFERENCE does not say {claim!r} -- a row "
                            f"was widened without updating the docs")

    def test_architecture_names_every_core_module(self):
        arch = self._read("docs", "ARCHITECTURE.md")
        core = [f.stem for f in (self.ROOT / "ryos").glob("*.py")
                if not f.stem.startswith("_")]
        unmentioned = sorted(m for m in core if m not in arch)
        self.assertEqual(unmentioned, [],
                         f"ARCHITECTURE.md never mentions: {unmentioned}")

    def test_claude_md_describes_process_termination_correctly(self):
        # Handles moved to Job.processes when concurrent steps landed; the old
        # claim sent readers to a field that is empty for any pipeline.
        claude = self._read("CLAUDE.md")
        self.assertIn("Job.processes", claude)
        self.assertNotIn("stored in `self.current_process`; `Stop` button", claude)


# ---------------------------------------------------------------------------
# Cloning carries everything that defines an item
# ---------------------------------------------------------------------------

class TestCloneCarriesEverything(unittest.TestCase):
    """Clone used to copy the obvious fields and silently drop the rest.

    Each of these is a field that was lost. The worst two were not cosmetic:
    a cloned launcher lost `detached` and went back to blocking its pipeline
    (the behaviour issue #5 removed), and a cloned pipeline lost its per-step
    params_override, so the copy looked correct in the editor and ran with the
    wrong arguments.

    The rule these pin down: a clone differs from its source in name, id and
    group only. Run history is the one deliberate exception -- the copy has
    not run yet.
    """

    def setUp(self):
        self.db = _make_db()
        self.db.create_group("G")
        self.sid = self.db.add("launcher", "/l.py", "", "", "G", detached=1)
        self.db.set_script_color(self.sid, "red")
        self.db.set_favorite_script(self.sid, True)
        self.pid = self.db.create_pipeline("P", "G")
        self.db.set_pipeline_color(self.pid, "blue")
        self.db.set_favorite_pipeline(self.pid, True)
        self.step = self.db.add_pipeline_step(self.pid, self.sid)
        self.db.update_pipeline_step_params(self.step, "--override-me")

    def _script_in(self, group):
        return [r for r in self.db.list_all() if r[8] == group][0]

    # -- clone_group ------------------------------------------------------
    def test_clone_group_keeps_a_launcher_a_launcher(self):
        self.db.clone_group("G", "G copy")
        clone = self._script_in("G copy")
        self.assertTrue(self.db.is_detached(clone[0]),
                        "cloned launcher lost `detached` and would block its "
                        "pipeline")

    def test_clone_group_carries_script_colour_and_favourite(self):
        self.db.clone_group("G", "G copy")
        clone = self._script_in("G copy")
        self.assertEqual(clone[10], 1)          # is_favorite
        self.assertEqual(clone[11], "red")      # label_color

    def test_clone_group_carries_pipeline_colour_and_favourite(self):
        self.db.clone_group("G", "G copy")
        _pid, _name, fav, color = self.db.list_pipelines("G copy")[0]
        self.assertEqual((fav, color), (1, "blue"))

    def test_clone_group_carries_step_param_overrides(self):
        self.db.clone_group("G", "G copy")
        new_pid = self.db.list_pipelines("G copy")[0][0]
        self.assertEqual(self.db.list_pipeline_steps(new_pid)[0][6],
                         "--override-me")

    def test_clone_group_leaves_run_history_behind(self):
        # The deliberate exception: the copy has not run.
        self.db.mark_run(self.sid)
        self.db.mark_run_status(self.sid, "error")
        self.db.clone_group("G", "G copy")
        clone = self._script_in("G copy")
        self.assertIsNone(clone[6], "clone inherited last_run_at")
        self.assertIsNone(clone[7], "clone inherited last_run_status")

    # -- clone_pipeline ---------------------------------------------------
    def test_clone_pipeline_carries_step_param_overrides(self):
        new_id = self.db.clone_pipeline(self.pid)
        self.assertEqual(self.db.list_pipeline_steps(new_id)[0][6],
                         "--override-me",
                         "the copy would run with the wrong arguments")

    def test_clone_pipeline_carries_colour_and_favourite(self):
        new_id = self.db.clone_pipeline(self.pid)
        row = [p for p in self.db.list_pipelines("G") if p[0] == new_id][0]
        self.assertEqual((row[2], row[3]), (1, "blue"))
