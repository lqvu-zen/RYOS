# -*- coding: utf-8 -*-
"""
Unit tests for RYOS non-UI layers: ScriptDB, detect_interpreter, build_command.
Run with:  uv run python -m pytest tests/test_ryos.py -v
       or: uv run python -m unittest discover -s tests -v
"""
import json
import os
import re
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
        self.assertEqual(data["version"], 3)
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
        self.assertEqual(self.db.list_pipelines("G"), [(pid, "Deploy", 0)])

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

    def test_delete_pipeline_cascades_steps(self):
        pid = self.db.create_pipeline("P", "G")
        self.db.add_pipeline_step(pid, self.s1)
        self.db.delete_pipeline(pid)
        self.assertEqual(self.db.list_pipelines("G"), [])
        self.assertEqual(self.db.list_pipeline_steps(pid), [])

    def test_rename_pipeline(self):
        pid = self.db.create_pipeline("Old", "G")
        self.db.rename_pipeline(pid, "New")
        self.assertEqual(self.db.list_pipelines("G"), [(pid, "New", 0)])

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
            launch=lambda job, cmd, name, sid: self.rec["launch"].append((cmd, name, sid)),
            now=lambda: _dt(2020, 1, 1, 12, 0, 0),
        )
        self._tmp = tempfile.NamedTemporaryFile(suffix=".py", delete=False)
        self._tmp.write(b"print('hi')\n")
        self._tmp.close()

    def tearDown(self):
        os.unlink(self._tmp.name)

    def _step(self, sid=1, name="s1", params="", override=None):
        return (sid, sid, name, self._tmp.name, params, "", override)

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
        bad = (1, 1, "gone", "/no/such/file.py", "", "", None)
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
        cmd = self.rec["launch"][0][0]
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
