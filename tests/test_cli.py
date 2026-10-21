"""The command line: ``ryos list`` / ``run`` / ``pipeline``.

Most tests call ``cli.main`` with a throwaway database and a stand-in for
"tell the running window"; one runs the real entry point in a child process
with APPDATA pointed at a temp folder, to prove the CLI path never takes the
instance lock, writes run-at-login or imports Qt.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from ryos import __version__, cli  # noqa: E402
from ryos.db import FAIL_STOP, SOURCE_CLI, ScriptDB  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = ScriptDB(self.tmp / "t.db")
        for g in ("A", "B"):
            self.db.create_group(g)
        self.notified = 0

    def script(self, name, body, group="A", params="", env_vars=None):
        path = self.tmp / f"{name.replace(' ', '_')}_{group}.py"
        path.write_text(body, encoding="utf-8")
        return self.db.add(name, str(path), params, sys.executable, group,
                           env_vars=env_vars)

    def ryos(self, *argv):
        """(exit code, stdout, stderr) of one command."""
        out, err = io.StringIO(), io.StringIO()

        def notify():
            self.notified += 1
        code = cli.main(list(argv), db=self.db, settings={"launcher_release_seconds": 0},
                        out=out, err=err, notify_window=notify)
        return code, out.getvalue(), err.getvalue()


class TestWhichCommandLines(unittest.TestCase):
    def test_plain_ryos_still_opens_the_window(self):
        for argv in ([], ["--startup"]):
            self.assertFalse(cli.is_cli(argv), argv)
        for argv in (["list"], ["run", "x"], ["pipeline", "x"], ["--help"], ["--version"]):
            self.assertTrue(cli.is_cli(argv), argv)

    def test_version_and_help(self):
        out = io.StringIO()
        sys_stdout, sys.stdout = sys.stdout, out
        try:
            self.assertEqual(cli.main(["--version"]), 0)
            self.assertEqual(cli.main(["run", "--help"]), 0)
        finally:
            sys.stdout = sys_stdout
        self.assertIn(f"RYOS {__version__}", out.getvalue())
        self.assertIn("--preset", out.getvalue())

    def test_a_bad_command_line(self):
        err = io.StringIO()
        sys_stderr, sys.stderr = sys.stderr, err
        try:
            self.assertEqual(cli.main(["run", "x", "--preset", "a", "--params", "b"]),
                             cli.EXIT_USAGE)
        finally:
            sys.stderr = sys_stderr


class TestList(_Base):
    def test_lists_scripts_and_pipelines_without_their_environment(self):
        sid = self.script("build", "", env_vars="TOKEN=secret123")
        self.db.replace_param_presets(sid, [("quick", "--q")])
        pid = self.db.create_pipeline("ship", "B")
        self.db.add_pipeline_step(pid, sid)
        code, out, _ = self.ryos("list", "--json")
        self.assertEqual(code, 0)
        listing = json.loads(out)
        self.assertEqual(listing["scripts"], [
            {"id": sid, "name": "build", "group": "A", "ref": "A/build", "presets": ["quick"],
             "agents": False}])
        self.assertEqual(listing["pipelines"], [
            {"id": pid, "name": "ship", "group": "B", "ref": "B/ship", "steps": 1, "agents": False}])
        code, out, _ = self.ryos("list")
        self.assertIn("A/build", out)
        self.assertIn("presets: quick", out)
        self.assertIn("1 step", out)
        for text in (out, json.dumps(listing)):
            self.assertNotIn("secret123", text)

    def test_nothing_yet(self):
        self.assertIn("No scripts", self.ryos("list")[1])

    def test_one_group(self):
        a = self.script("build", "", group="A")
        self.script("deploy", "", group="B")
        pid = self.db.create_pipeline("ship", "A")
        self.db.set_agent_exposed("script", a, True)
        code, out, _ = self.ryos("list", "--group", "A")
        self.assertEqual(code, 0)
        self.assertIn("A/build", out)
        self.assertNotIn("B/deploy", out)
        self.assertIn("Not available to agents yet: A/ship (pipeline).", out)
        self.assertIn("ryos-cli expose --group A on", out)
        code, out, _ = self.ryos("list", "--group", "A", "--json")
        listing = json.loads(out)
        self.assertEqual([s["ref"] for s in listing["scripts"]], ["A/build"])
        self.assertEqual([p["id"] for p in listing["pipelines"]], [pid])
        self.db.set_agent_exposed("pipeline", pid, True)
        self.assertIn("All 2 in A are available to agents.",
                      self.ryos("list", "--group", "A")[1])
        self.db.create_group("Empty")
        self.assertIn("Empty has no scripts or pipelines yet.",
                      self.ryos("list", "--group", "Empty")[1])

    def test_an_unknown_group(self):
        code, out, err = self.ryos("list", "--group", "Nope")
        self.assertEqual((code, out), (cli.EXIT_REFUSED, ""))
        self.assertIn("The groups are: A, B.", err)
        code, out, _ = self.ryos("list", "--group", "Nope", "--json")
        self.assertEqual((code, json.loads(out)["status"]), (cli.EXIT_REFUSED, "refused"))


class TestRun(_Base):
    def test_a_pass_streams_its_output_and_tells_the_window(self):
        self.script("hello", "print('hi there')\n")
        code, out, err = self.ryos("run", "hello")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("hi there", out)
        self.assertEqual(self.notified, 1)

    def test_a_failure_exits_with_the_scripts_code(self):
        self.script("boom", "import sys\nsys.exit(3)\n")
        self.assertEqual(self.ryos("run", "boom")[0], 3)

    def test_json(self):
        sid = self.script("args", "import sys\nprint(' '.join(sys.argv[1:]))\n")
        self.db.replace_param_presets(sid, [("quick", "--fast 1")])
        code, out, _ = self.ryos("run", "A/args", "--preset", "quick", "--json")
        result = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual((result["status"], result["exit_code"], result["ref"]),
                         ("ok", 0, "A/args"))
        self.assertEqual(result["output"][0], "--fast 1")
        self.assertGreaterEqual(result["duration_seconds"], 0)
        self.assertEqual(self.db.list_runs(script_id=sid)[0][10], SOURCE_CLI)

    def test_outside_the_base_folder_adds_nothing_to_the_output(self):
        base = self.tmp / "base"
        base.mkdir()
        self.db.set_group_base_dir("A", str(base))
        self.script("away", "print('hi')\n")
        code, out, _ = self.ryos("run", "away")
        self.assertEqual((code, out.strip().splitlines()[0]), (0, "hi"))
        self.assertNotIn("Note:", out)
        _, out, _ = self.ryos("run", "away", "--json")
        result = json.loads(out)
        self.assertEqual(result["output"][0], "hi")
        self.assertNotIn("Note:", out)

    def test_params(self):
        self.script("args", "import sys\nprint('got', *sys.argv[1:])\n", params="--own")
        # Parameters usually start with a dash, so they are given with "=".
        self.assertIn("got --x 1", self.ryos("run", "args", "--params=--x 1")[1])
        self.assertIn("got plain", self.ryos("run", "args", "--params", "plain")[1])

    def test_refusals(self):
        self.script("build", "")
        self.script("build", "", group="B")
        cases = {
            ("run", "build"): "'A/build'",              # ambiguous: lists both
            ("run", "nope"): "No script named 'nope'",
            ("run", "A/build", "--preset", "x"): "no preset 'x'",
        }
        for argv, words in cases.items():
            with self.subTest(argv):
                code, out, err = self.ryos(*argv)
                self.assertEqual(code, cli.EXIT_REFUSED)
                self.assertIn(words, err)
                self.assertEqual(out, "")
        code, out, _ = self.ryos("run", "nope", "--json")
        self.assertEqual((code, json.loads(out)["status"]), (cli.EXIT_REFUSED, "refused"))
        self.assertEqual(self.notified, 0)          # nothing ran

    def test_a_timeout(self):
        self.script("slow", "import time\ntime.sleep(60)\n")
        code, _out, err = self.ryos("run", "slow", "--timeout", "0.5")
        self.assertEqual(code, cli.EXIT_TIMEOUT)
        self.assertIn("timed out", err)


class TestPipeline(_Base):
    def test_a_pass_and_a_failure(self):
        ok = self.script("ok", "print('step ok')\n")
        bad = self.script("bad", "import sys\nsys.exit(4)\n")
        good = self.db.create_pipeline("good", "A")
        self.db.add_pipeline_step(good, ok)
        broken = self.db.create_pipeline("broken", "A")
        step = self.db.add_pipeline_step(broken, bad)
        self.db.set_step_policy(step, on_failure=FAIL_STOP)
        code, out, _ = self.ryos("pipeline", "good")
        self.assertEqual(code, 0)
        self.assertIn("step ok", out)
        code, out, _ = self.ryos("pipeline", "broken", "--json")
        self.assertEqual((code, json.loads(out)["status"]), (cli.EXIT_FAILED, "error"))


class _Manage(_Base):
    """The management commands, through cli.main as a person would type them.
    ``answer`` is what the terminal says to a question: True, False, or None
    for no terminal (an agent calling ryos-cli)."""

    def setUp(self):
        super().setUp()
        self.answer = None
        self.questions = []
        self.rebuilt = 0

    def ryos(self, *argv):
        out, err = io.StringIO(), io.StringIO()

        def ask(question):
            self.questions.append(question)
            return self.answer

        def rebuild():
            self.rebuilt += 1
        code = cli.main(list(argv), db=self.db, settings={}, out=out, err=err,
                        notify_window=lambda: None, rebuild_window=rebuild, ask=ask)
        return code, out.getvalue(), err.getvalue()

    def file(self, name="backup.py", folder=None):
        folder = folder or self.tmp
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_text("print('ok')\n", encoding="utf-8")
        return str(path)


class TestAdd(_Manage):
    def test_adds_as_the_dialog_would_and_makes_the_group(self):
        code, out, _ = self.ryos("add", self.file(), "--group", "Tools", "--params=--fast")
        self.assertEqual(code, 0)
        self.assertIn("Added Tools/backup", out)
        rec = self.db.get(next(r[0] for r in self.db.list_all() if r[1] == "backup"))
        self.assertEqual((rec[1], rec[3], rec[4], rec[5]), ("backup", "--fast", "", "Tools"))
        self.assertIn("Tools", self.db.list_groups())
        self.assertEqual(self.rebuilt, 1)
        self.assertFalse(self.db.agent_exposed_ids("script"))

    def test_a_name_already_in_the_group_is_refused(self):
        self.ryos("add", self.file(), "--group", "Tools")
        code, _, err = self.ryos("add", self.file("other.py"), "--group", "Tools",
                                 "--name", "backup")
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertIn("already has a script named 'backup'", err)
        # In another group the same name is fine.
        self.assertEqual(self.ryos("add", self.file(), "--group", "Home")[0], 0)

    def test_questions_refuse_without_yes(self):
        missing = str(self.tmp / "not-yet.py")
        code, _, err = self.ryos("add", missing, "--group", "Tools")
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertIn("--yes", err)
        self.assertEqual(self.ryos("add", missing, "--group", "Tools", "--yes")[0], 0)
        base = self.tmp / "base"
        base.mkdir()
        self.db.create_group("Based", base_dir=str(base))
        code, _, err = self.ryos("add", self.file("away.py"), "--group", "Based")
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertIn("outside the base folder", err)

    def test_a_working_folder_must_exist(self):
        code, _, err = self.ryos("add", self.file(), "--workdir", str(self.tmp / "nope"))
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertIn("existing folder", err)

    def test_expose_needs_a_person(self):
        # No terminal (an agent): refused, and nothing added.
        code, _, err = self.ryos("add", self.file(), "--group", "Tools", "--expose")
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertIn("terminal", err)
        self.assertEqual(self.db.list_all(), [])
        self.answer = True
        self.assertEqual(self.ryos("add", self.file(), "--group", "Tools", "--expose")[0], 0)
        self.assertEqual(len(self.db.agent_exposed_ids("script")), 1)
        self.answer = None
        self.assertEqual(self.ryos("add", self.file("b.py"), "--expose", "--yes")[0], 0)
        self.assertEqual(len(self.db.agent_exposed_ids("script")), 2)


class TestEditRemoveExpose(_Manage):
    def setUp(self):
        super().setUp()
        self.ryos("add", self.file(), "--group", "Tools", "--params=--a")
        self.sid = self.db.list_all()[0][0]
        self.db.replace_param_presets(self.sid, [("full", "--full")])
        self.rebuilt = 0

    def test_edit_changes_what_was_given_only(self):
        self.answer = True
        self.ryos("expose", "Tools/backup", "on")
        code, out, _ = self.ryos("edit", "Tools/backup", "--params=--b", "--name", "nightly")
        self.assertEqual(code, 0)
        rec = self.db.get(self.sid)
        self.assertEqual((rec[1], rec[3]), ("nightly", "--b"))
        self.assertEqual([p[1] for p in self.db.list_param_presets(self.sid)], ["full"])
        self.assertTrue(self.db.is_agent_exposed("script", self.sid))

    def test_edit_refuses_a_taken_name(self):
        self.ryos("add", self.file("x.py"), "--group", "Tools")
        code, _, err = self.ryos("edit", "Tools/x", "--name", "backup")
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertIn("already has", err)

    def test_remove_asks_and_names_its_pipelines(self):
        pid = self.db.create_pipeline("ship", "Tools")
        self.db.add_pipeline_step(pid, self.sid)
        code, _, err = self.ryos("remove", "Tools/backup")         # no terminal
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.answer = False
        code, _, err = self.ryos("remove", "Tools/backup")
        self.assertIn("Left as it was", err)
        self.assertIn("'ship'", self.questions[-1])
        self.assertIsNotNone(self.db.get(self.sid))
        self.assertEqual(self.ryos("remove", "Tools/backup", "--yes")[0], 0)
        self.assertIsNone(self.db.get(self.sid))
        self.assertEqual(self.rebuilt, 1)

    def test_expose_on_and_off(self):
        code, _, err = self.ryos("expose", "Tools/backup", "on")        # no terminal
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertFalse(self.db.is_agent_exposed("script", self.sid))
        self.assertEqual(self.ryos("expose", "Tools/backup", "on", "--yes")[0], 0)
        self.assertTrue(self.db.is_agent_exposed("script", self.sid))
        # Turning it off never asks.
        code, out, _ = self.ryos("expose", "Tools/backup", "off")
        self.assertEqual((code, self.db.is_agent_exposed("script", self.sid)), (0, False))
        self.assertIn("not available to agents", out)
        pid = self.db.create_pipeline("ship", "Tools")
        self.assertEqual(self.ryos("expose", "Tools/ship", "on", "--pipeline", "--yes")[0], 0)
        self.assertTrue(self.db.is_agent_exposed("pipeline", pid))

    def test_presets(self):
        self.assertEqual(self.ryos("preset", "add", "Tools/backup", "quick",
                                   "--params=--fast")[0], 0)
        self.assertEqual([p[1:] for p in self.db.list_param_presets(self.sid)],
                         [("full", "--full"), ("quick", "--fast")])
        code, _, err = self.ryos("preset", "add", "Tools/backup", "quick", "--params=--x")
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertEqual(self.ryos("preset", "remove", "Tools/backup", "full")[0], 0)
        code, _, err = self.ryos("preset", "remove", "Tools/backup", "full")
        self.assertIn("has no preset 'full'", err)

    def test_list_says_what_agents_may_run(self):
        self.ryos("expose", "Tools/backup", "on", "--yes")
        code, out, _ = self.ryos("list", "--json")
        self.assertTrue(json.loads(out)["scripts"][0]["agents"])
        self.assertIn("available to agents", self.ryos("list")[1])

    def test_history(self):
        self.assertIn("Nothing has run yet", self.ryos("history")[1])
        cli.main(["run", "Tools/backup"], db=self.db, settings={}, out=io.StringIO(),
                 err=io.StringIO(), notify_window=lambda: None)
        code, out, _ = self.ryos("history", "Tools/backup")
        self.assertEqual(code, 0)
        self.assertIn("backup", out.splitlines()[1])
        rows = json.loads(self.ryos("history", "--json")[1])
        self.assertEqual((rows[0]["name"], rows[0]["status"], rows[0]["by"]),
                         ("backup", "ok", SOURCE_CLI))
        self.assertEqual(self.rebuilt, 0)          # reading changes nothing

    def test_history_prints_on_a_windows_console(self):
        # A console in cp1252 has no "✓": the mark is replaced, not a crash.
        cli.main(["run", "Tools/backup"], db=self.db, settings={}, out=io.StringIO(),
                 err=io.StringIO(), notify_window=lambda: None)
        raw = io.BytesIO()
        out = io.TextIOWrapper(raw, encoding="cp1252")
        code = cli.main(["history"], db=self.db, settings={}, out=out, err=io.StringIO(),
                        rebuild_window=lambda: None, ask=lambda q: None)
        out.flush()
        self.assertEqual(code, 0)
        self.assertIn(b"backup", raw.getvalue())


class TestExposeAGroup(_Manage):
    """`expose --group`: ticks "Available to agents" on what is in a group now."""

    def setUp(self):
        super().setUp()
        self.db.create_group("Tools")
        self.backup = self.script("backup", "", group="Tools")
        self.sync = self.script("sync", "", group="Tools")
        self.ship = self.db.create_pipeline("ship", "Tools")
        self.other = self.script("other", "", group="A")

    def exposed(self, kind="script"):
        return self.db.agent_exposed_ids(kind)

    def test_first_run_exposes_everything(self):
        self.answer = True
        code, out, _ = self.ryos("expose", "--group", "Tools", "on")
        self.assertEqual(code, 0)
        self.assertEqual(self.exposed(), {self.backup, self.sync})
        self.assertEqual(self.exposed("pipeline"), {self.ship})
        self.assertEqual(len(self.questions), 1)
        self.assertIn("Will make 3 available to agents: "
                      "Tools/backup, Tools/sync, Tools/ship (pipeline).", self.questions[0])
        self.assertNotIn("already", self.questions[0])
        self.assertIn("Made 3 available to agents", out)
        self.assertEqual(self.rebuilt, 1)
        self.assertNotIn(self.other, self.exposed())

    def test_a_second_run_asks_only_about_whats_new(self):
        self.answer = True
        self.ryos("expose", "--group", "Tools", "on")
        x = self.script("x", "", group="Tools")
        p2 = self.db.create_pipeline("p2", "Tools")
        self.questions.clear()
        code, out, _ = self.ryos("expose", "on", "--group", "Tools")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.questions), 1)
        self.assertIn("Will make 2 available to agents: Tools/x, Tools/p2 (pipeline).",
                      self.questions[0])
        self.assertIn("3 already are.", self.questions[0])
        self.assertNotIn("Tools/backup", self.questions[0])
        self.assertEqual(self.exposed(), {self.backup, self.sync, x})
        self.assertEqual(self.exposed("pipeline"), {self.ship, p2})
        self.assertIn("3 already were.", out)

    def test_nothing_new_exits_0_without_asking(self):
        self.answer = True
        self.ryos("expose", "--group", "Tools", "on")
        self.questions.clear()
        self.rebuilt = 0
        self.answer = None
        code, out, _ = self.ryos("expose", "--group", "Tools", "on")
        self.assertEqual(code, 0)
        self.assertIn("All 3 in Tools are already available to agents", out)
        self.assertEqual((self.questions, self.rebuilt), ([], 0))

    def test_off_clears_them_all_without_asking(self):
        self.answer = True
        self.ryos("expose", "--group", "Tools", "on")
        self.db.set_agent_exposed("script", self.other, True)
        self.questions.clear()
        self.answer = None
        code, out, _ = self.ryos("expose", "--group", "Tools", "off")
        self.assertEqual(code, 0)
        self.assertEqual(self.questions, [])
        self.assertEqual(self.exposed(), {self.other})
        self.assertEqual(self.exposed("pipeline"), set())
        self.assertIn("3 in Tools are no longer available to agents.", out)
        code, out, _ = self.ryos("expose", "--group", "Tools", "off")
        self.assertEqual(code, 0)
        self.assertIn("None in Tools was available to agents.", out)

    def test_unknown_group_is_refused(self):
        for name in ("Nope", "tools", "Ungrouped", ""):
            with self.subTest(name):
                code, out, err = self.ryos("expose", "--group", name, "on", "--yes")
                self.assertEqual(code, cli.EXIT_REFUSED)
                self.assertIn("The groups are: A, B, Tools.", err)
                self.assertEqual(out, "")
        self.assertEqual(self.exposed(), set())

    def test_empty_group_says_so(self):
        self.db.create_group("Empty")
        code, out, _ = self.ryos("expose", "--group", "Empty", "on")
        self.assertEqual(code, 0)
        self.assertIn("Empty has no scripts or pipelines yet.", out)
        self.assertEqual(self.questions, [])

    def test_refused_without_a_terminal_or_yes(self):
        code, _, err = self.ryos("expose", "--group", "Tools", "on")
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertIn("terminal", err)
        self.assertEqual(self.exposed(), set())
        self.answer = False
        code, _, err = self.ryos("expose", "--group", "Tools", "on")
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertIn("Left as it was", err)
        self.assertEqual(self.exposed(), set())
        self.answer = None
        self.assertEqual(self.ryos("expose", "--group", "Tools", "on", "--yes")[0], 0)
        self.assertEqual(self.exposed(), {self.backup, self.sync})

    def test_moving_in_later_grants_nothing(self):
        self.answer = True
        self.ryos("expose", "--group", "Tools", "on")
        code, _, _ = self.ryos("edit", "A/other", "--group", "Tools")
        self.assertEqual(code, 0)
        self.assertNotIn(self.other, self.exposed())

    def test_usage_errors(self):
        err = io.StringIO()
        sys_stderr, sys.stderr = sys.stderr, err
        try:
            for argv in (("expose", "Tools/backup", "on", "--group", "Tools"),
                         ("expose", "--group", "Tools", "on", "--pipeline"),
                         ("expose", "on")):
                with self.subTest(argv):
                    self.assertEqual(self.ryos(*argv)[0], cli.EXIT_USAGE)
        finally:
            sys.stderr = sys_stderr
        self.assertIn("--group alone", err.getvalue())
        self.assertIn("name a script or pipeline", err.getvalue())
        self.assertEqual(self.ryos("expose", "Tools/backup", "on", "--yes")[0], 0)
        self.assertEqual(self.exposed(), {self.backup})
        self.assertEqual(self.ryos("expose", "Tools/ship", "on", "--pipeline", "--yes")[0], 0)


class TestVersion(unittest.TestCase):
    def setUp(self):
        from unittest import mock
        self.local = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.local, ignore_errors=True)
        env = mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.local)})
        env.start()
        self.addCleanup(env.stop)

    def run_version(self, *argv, fetch=None):
        out = io.StringIO()
        code = cli.main(["version", *argv], db=None, settings={}, out=out,
                        err=io.StringIO(), fetch_release=fetch)
        return code, out.getvalue()

    def test_says_which_download(self):
        from ryos import buildinfo
        code, out = self.run_version()
        self.assertEqual(code, 0)
        self.assertIn(f"RYOS {__version__} ({buildinfo.describe_build()})", out)

    def test_names_the_build_commit(self):
        import types
        from unittest import mock
        fake = types.SimpleNamespace(VARIANT="windows-ai", COMMIT="1a2b3c4")
        want = f"RYOS {__version__} (Windows build with AI agents, 1a2b3c4)"
        with mock.patch.dict(sys.modules, {"ryos._build_info": fake}):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cli.main(["--version"], db=None, settings={},
                                          err=io.StringIO()), 0)
            self.assertEqual(out.getvalue().strip(), want)
            code, text = self.run_version()
            self.assertEqual(code, 0)
            self.assertEqual(text.splitlines()[0], want)
        with mock.patch.dict(sys.modules, {"ryos._build_info": None}):
            code, text = self.run_version()
            self.assertEqual(text.splitlines()[0], f"RYOS {__version__} (from source)")

    def test_says_where_the_logs_are(self):
        from ryos import settings
        code, out = self.run_version()
        self.assertEqual(code, 0)
        self.assertIn(str(settings.LOG_DIR), out)
        self.assertIn("ryos-cli.log", out)

    def test_dash_dash_version_stays_one_line(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["--version"], db=None, settings={},
                            err=io.StringIO())
        self.assertEqual(code, 0)
        self.assertEqual(len(out.getvalue().strip().splitlines()), 1)

    def test_check(self):
        from ryos import buildinfo
        code, out = self.run_version("--check", fetch=lambda: ("v99.0.0", "https://x/r"))
        self.assertEqual(code, 0)
        self.assertIn(f"Download {buildinfo.download_name()} from https://x/r", out)
        code, out = self.run_version("--check", fetch=lambda: (f"v{__version__}", "u"))
        self.assertIn("Up to date", out)
        code, out = self.run_version("--check", fetch=lambda: None)
        self.assertEqual(code, cli.EXIT_FAILED)
        self.assertIn("Could not reach GitHub", out)

    def test_check_says_whether_it_is_downloaded(self):
        import hashlib
        import types
        from unittest import mock
        from ryos import settings
        fetch = lambda: ("v99.0.0", "https://x/r")  # noqa: E731
        from ed25519_signer import TEST_PUBLIC, TEST_SEED, sig_file
        build = types.SimpleNamespace(VARIANT="windows", RELEASE_KEY=TEST_PUBLIC.hex())
        with mock.patch.dict(sys.modules, {"ryos._build_info": build}):
            code, out = self.run_version("--check", fetch=fetch)
            self.assertEqual(code, 0)
            self.assertIn("Download RYOS-windows.zip from https://x/r", out)
            self.assertIn("Not downloaded yet.", out)
            folder = settings.updates_dir("v99.0.0")
            folder.mkdir(parents=True)
            body = b"the new RYOS"
            (folder / "RYOS-windows.zip").write_bytes(body)
            sums = f"{hashlib.sha256(body).hexdigest()}  RYOS-windows.zip\n".encode()
            (folder / "SHA256SUMS.txt").write_bytes(sums)
            (folder / "SHA256SUMS.txt.sig").write_bytes(sig_file(TEST_SEED, "99.0.0", sums))
            code, out = self.run_version("--check", fetch=fetch)
        self.assertEqual(code, 0)
        self.assertIn("RYOS-windows.zip is downloaded and checked", out)
        self.assertIn(str(folder / "RYOS-windows.zip"), out)
        self.assertNotIn("Not downloaded yet", out)

    def test_check_from_source_keeps_todays_notice(self):
        from unittest import mock
        with mock.patch.dict(sys.modules, {"ryos._build_info": None}):
            code, out = self.run_version(
                "--check", fetch=lambda: ("v99.0.0", "https://x/r"))
        self.assertEqual(code, 0)
        self.assertIn("RYOS 99.0.0 is out (you have", out)
        self.assertIn("Download RYOS-portable.zip from https://x/r", out)
        self.assertNotIn("Not downloaded yet", out)
        self.assertNotIn("downloaded and checked", out)
        self.assertFalse((self.local / "RYOS").exists())


class TestVerify(unittest.TestCase):
    def setUp(self):
        import hashlib
        import types
        from ed25519_signer import TEST_PUBLIC, TEST_SEED, sig_file
        self.seed, self.sig_file = TEST_SEED, sig_file
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.zip = self.tmp / "RYOS-windows.zip"
        self.zip.write_bytes(b"the new RYOS")
        self.sums = (hashlib.sha256(b"the new RYOS").hexdigest().encode()
                     + b"  RYOS-windows.zip\n")
        self.sign("99.0.0")
        self.build = types.SimpleNamespace(VARIANT="windows", RELEASE_KEY=TEST_PUBLIC.hex())

    def sign(self, version, seed=None, sums=None):
        sums = self.sums if sums is None else sums
        (self.tmp / "SHA256SUMS.txt").write_bytes(sums)
        (self.tmp / "SHA256SUMS.txt.sig").write_bytes(
            self.sig_file(seed or self.seed, version, sums))

    def verify(self, path=None, build="default"):
        from unittest import mock
        out, err = io.StringIO(), io.StringIO()
        build = self.build if build == "default" else build
        with mock.patch.dict(sys.modules, {"ryos._build_info": build}):
            code = cli.main(["verify", str(path or self.zip)], db=None, settings=None,
                            out=out, err=err)
        return code, out.getvalue(), err.getvalue()

    def refused(self, *words, **kw):
        code, out, err = self.verify(**kw)
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("ryos: "), err)
        for said in words:
            self.assertIn(said, err)
        return err

    def test_verify_is_a_command(self):
        self.assertIn("verify", cli.COMMANDS)
        self.assertTrue(cli.is_cli(["verify", "x.zip"]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["--help"], db=None, settings={}), 0)
        self.assertIn("verify", out.getvalue())

    def test_a_good_zip_exits_0_naming_its_version(self):
        code, out, err = self.verify()
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "RYOS-windows.zip is RYOS 99.0.0: signed with this "
                                      "RYOS's release key and matching SHA256SUMS.txt.")
        self.assertEqual(err, "")

    def test_a_tampered_zip_is_refused_with_125(self):
        self.zip.write_bytes(b"the new RYOS, changed")
        self.refused("does not match its line in SHA256SUMS.txt")

    def test_a_tampered_sums_is_refused_with_125(self):
        (self.tmp / "SHA256SUMS.txt").write_bytes(self.sums + b"0" * 64 + b"  x.zip\n")
        self.refused("has been changed")

    def test_a_missing_signature_is_refused_with_125(self):
        (self.tmp / "SHA256SUMS.txt.sig").unlink()
        self.refused("there is no SHA256SUMS.txt.sig")

    def test_a_wrong_key_is_refused_with_125(self):
        from ed25519_signer import OTHER_SEED
        self.sign("99.0.0", seed=OTHER_SEED)
        self.refused("different key")

    def test_a_signed_older_version_is_refused_with_125(self):
        self.sign("1.0.0")
        self.refused("RYOS 1.0.0, older than this RYOS")

    def test_without_a_release_key_it_says_so(self):
        import types
        self.refused("carries no release key", build=None)
        self.refused("carries no release key", build=types.SimpleNamespace(VARIANT="windows"))

    def test_a_missing_zip_is_refused(self):
        self.refused("There is no file at", path=self.tmp / "nothing.zip")
        (self.tmp / "SHA256SUMS.txt").unlink()
        self.refused("There is no SHA256SUMS.txt beside RYOS-windows.zip")

    def test_needs_no_database_or_settings(self):
        from unittest import mock

        from ryos import logger, settings

        def boom(*_a, **_k):
            raise AssertionError("verify must not need this")
        with mock.patch.object(cli, "ScriptDB", boom), \
                mock.patch.object(settings, "_load_settings", boom), \
                mock.patch.object(logger, "setup_logging", boom):
            code, _out, err = self.verify()
        self.assertEqual(code, 0, err)


class TestApplyUpdate(unittest.TestCase):
    OLD = {"RYOS.exe": b"old window", "ryos-cli.exe": b"old cli", "lib/a.pyc": b"old"}
    NEW = {"RYOS.exe": b"new window", "ryos-cli.exe": b"new cli!", "lib/a.pyc": b"new a"}

    def setUp(self):
        import types
        from unittest import mock

        from ed25519_signer import TEST_PUBLIC

        from ryos import logger
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(os.chdir, os.getcwd())
        for patch in (mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.tmp / "local")}),
                      mock.patch.object(logger, "setup_logging", lambda *a, **k: None)):
            patch.start()
            self.addCleanup(patch.stop)
        self.install = self.tmp / "apps" / "RYOS"
        self.write(self.install, self.OLD)
        self.build = types.SimpleNamespace(VARIANT="windows", RELEASE_KEY=TEST_PUBLIC.hex())
        self.spawned: list = []
        self.waited: list = []

    @staticmethod
    def write(folder, files):
        for name, body in files.items():
            (folder / name).parent.mkdir(parents=True, exist_ok=True)
            (folder / name).write_bytes(body)

    def read(self):
        return {p.relative_to(self.install).as_posix(): p.read_bytes()
                for p in self.install.rglob("*") if p.is_file()}

    def stage(self, tag="v99.0.0"):
        import hashlib
        import zipfile

        from ed25519_signer import TEST_SEED, sig_file

        from ryos import settings
        folder = settings.updates_dir(tag)
        folder.mkdir(parents=True)
        zip_path = folder / "RYOS-windows.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            for name, body in self.NEW.items():
                z.writestr(name, body)
        sums = f"{hashlib.sha256(zip_path.read_bytes()).hexdigest()}  RYOS-windows.zip\n"
        (folder / "SHA256SUMS.txt").write_bytes(sums.encode())
        (folder / "SHA256SUMS.txt.sig").write_bytes(
            sig_file(TEST_SEED, tag.lstrip("v"), sums.encode()))

    def apply(self, *argv, build="default", install=None, **over):
        from unittest import mock

        from ryos import swap

        def wait(pid, timeout):
            self.waited.append(pid)
            return True

        def spawn(argv, cwd):
            self.spawned.append(list(argv))
        effects = swap.Effects(**{"wait_for_exit": wait, "spawn": spawn,
                                  "sleep": lambda s: None, **over})
        out, err = io.StringIO(), io.StringIO()
        build = self.build if build == "default" else build
        with mock.patch.dict(sys.modules, {"ryos._build_info": build}):
            code = cli.main(["apply-update", "--install", str(install or self.install), *argv],
                            db=None, settings=None, out=out, err=err,
                            swap_effects=effects)
        return code, out.getvalue(), err.getvalue()

    def test_is_a_hidden_cli_command(self):
        self.assertTrue(cli.is_cli(["apply-update", "--recover"]))
        self.assertNotIn("apply-update", cli.COMMANDS)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["--help"], db=None, settings={}), 0)
        self.assertNotIn("apply-update", out.getvalue())
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(cli.main(["frobnicate"], db=None, settings={}), cli.EXIT_USAGE)
        self.assertNotIn("apply-update", err.getvalue())

    def test_refused_from_source(self):
        code, _out, err = self.apply("--version", "v99.0.0", build=None)
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertIn("from source", err)
        self.assertEqual(self.read(), self.OLD)

    def test_refused_when_the_tag_is_not_downloaded(self):
        code, _out, err = self.apply("--version", "v99.0.0")
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertIn("not downloaded and checked", err)
        self.assertEqual(self.read(), self.OLD)

    def test_refused_when_the_helper_runs_inside_the_install(self):
        from unittest import mock
        self.stage()
        with mock.patch.object(cli, "_helper_dir", lambda: self.install / "lib"):
            code, _out, err = self.apply("--version", "v99.0.0")
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertIn("inside", err)
        self.assertEqual(self.read(), self.OLD)

    def test_applies_a_downloaded_update_and_rolls_back(self):
        self.stage()
        code, out, err = self.apply("--version", "v99.0.0", "--from-version", "1.0.0",
                                    "--wait-pid", "4242", "--restart")
        self.assertEqual(code, cli.EXIT_OK, err)
        self.assertIn("now v99.0.0", out)
        self.assertEqual(self.read(), self.NEW)
        self.assertEqual(self.waited, [4242])
        self.assertEqual(self.spawned, [[str(self.install / "RYOS.exe")]])
        code, out, err = self.apply("--rollback", "--from-version", "99.0.0")
        self.assertEqual(code, cli.EXIT_OK, err)
        self.assertEqual(self.read(), self.OLD)
        code, out, _err = self.apply("--recover")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("no unfinished update", out)

    def test_a_release_candidate_applies_like_a_release(self):
        self.stage("v99.0.0-rc2")
        code, out, err = self.apply("--version", "v99.0.0-rc2",
                                    "--from-version", "99.0.0-rc1")
        self.assertEqual(code, cli.EXIT_OK, err)
        self.assertIn("now v99.0.0-rc2", out)
        self.assertEqual(self.read(), self.NEW)
        code, _out, err = self.apply("--rollback", "--from-version", "99.0.0-rc2")
        self.assertEqual(code, cli.EXIT_OK, err)
        self.assertEqual(self.read(), self.OLD)

    def test_an_older_candidate_never_replaces_a_release(self):
        self.stage("v99.0.0-rc3")
        code, _out, _err = self.apply("--version", "v99.0.0-rc3",
                                      "--from-version", "99.0.0")
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertEqual(self.read(), self.OLD)

    def test_a_failed_swap_exits_1_and_nothing_to_roll_back_125(self):
        code, _out, err = self.apply("--rollback")
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertIn("no earlier build", err)
        self.stage()

        def extract(*_a):
            raise OSError(5, "Access is denied")
        code, _out, err = self.apply("--version", "v99.0.0", extract=extract)
        self.assertEqual(code, cli.EXIT_FAILED)
        self.assertIn("antivirus", err)
        self.assertEqual(self.read(), self.OLD)

    def test_an_update_already_installed_is_refused(self):
        self.stage()
        code, _out, err = self.apply("--version", "v99.0.0", "--from-version", "99.0.0")
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertIn("already installed", err)
        self.assertEqual(self.read(), self.OLD)

    def test_recover_uses_that_installs_journal(self):
        from ryos import swap
        self.stage()
        other = self.tmp / "other" / "RYOS"
        self.write(other, self.OLD)
        renames: list = []

        class Crash(BaseException):
            pass

        def rename(src, dst):
            renames.append(src)
            if len(renames) == 3:
                raise Crash()
            swap._rename(src, dst)
        from ryos import updates
        with self.assertRaises(Crash):
            swap.apply_update(self.install, updates.downloaded("v99.0.0", key=bytes.fromhex(
                self.build.RELEASE_KEY), which="windows"), version="v99.0.0",
                which="windows", effects=swap.Effects(rename=rename))
        self.assertFalse(self.install.exists())
        code, out, _err = self.apply("--recover", install=other)
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("no unfinished update", out)
        self.assertFalse(self.install.exists())
        code, _out, err = self.apply("--recover")
        self.assertEqual(code, cli.EXIT_FAILED)
        self.assertIn("undone", err)
        self.assertEqual(self.read(), self.OLD)

    def test_a_refusal_with_restart_starts_ryos_again(self):
        code, _out, err = self.apply("--version", "v99.0.0", "--wait-pid", "5", "--restart")
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertIn("not downloaded and checked", err)
        self.assertEqual(self.waited, [5])
        self.assertEqual(self.spawned, [[str(self.install / "RYOS.exe")]])
        self.spawned.clear()
        code, _out, _err = self.apply("--rollback", "--restart")
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertEqual(self.spawned, [[str(self.install / "RYOS.exe")]])

    def test_a_refusal_before_waiting_waits_then_starts_ryos_again(self):
        from ryos import swap
        self.NEW = {"ryos-cli.exe": b"new cli only", "lib/a.pyc": b"new a"}
        self.stage()
        waits: list = []

        def wait(pid, timeout):
            waits.append((pid, timeout))
            return True
        code, _out, err = self.apply("--version", "v99.0.0", "--wait-pid", "5", "--restart",
                                     wait_for_exit=wait)
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertIn("RYOS.exe", err)
        self.assertEqual(waits, [(5, swap.WAIT_SECONDS)])
        self.assertEqual(self.spawned, [[str(self.install / "RYOS.exe")]])
        self.assertEqual(self.read(), self.OLD)

    def test_ryos_that_did_not_exit_is_not_started_again(self):
        self.stage()
        code, _out, err = self.apply("--version", "v99.0.0", "--wait-pid", "5", "--restart",
                                     wait_for_exit=lambda pid, t: False)
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertIn("did not exit", err)
        self.assertEqual(self.spawned, [])

    def test_a_swap_in_progress_starts_nothing(self):
        from ryos import swap
        self.stage()
        jdir = swap.journal_dir_for(self.install)
        jdir.mkdir(parents=True, exist_ok=True)
        release = swap._hold_lock(jdir / swap.LOCK_NAME)
        try:
            code, _out, err = self.apply("--version", "v99.0.0", "--restart")
        finally:
            release()
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertIn(swap.IN_PROGRESS, err)
        self.assertEqual(self.spawned, [])

    def test_the_result_is_logged(self):
        self.stage()
        with self.assertLogs("ryos.cli", level="INFO") as logs:
            code, _out, err = self.apply("--version", "v99.0.0", "--from-version", "1.0.0")
        self.assertEqual(code, cli.EXIT_OK, err)
        self.assertTrue(any("now v99.0.0" in line for line in logs.output), logs.output)

    def test_a_bad_command_line_exits_2(self):
        for argv in ([], ["--version", "v1", "--rollback"], ["--wait-pid", "x", "--recover"]):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = cli.main(["apply-update", *argv], db=None, settings=None)
            self.assertEqual(code, cli.EXIT_USAGE, argv)
            self.assertIn("ryos apply-update", err.getvalue())


class TestUpdate(unittest.TestCase):
    OLD = {"RYOS.exe": b"old window", "ryos-cli.exe": b"old cli", "lib/a.pyc": b"old"}
    NEW = {"RYOS.exe": b"new window", "ryos-cli.exe": b"new cli!", "lib/a.pyc": b"new a"}

    def setUp(self):
        import zipfile
        from unittest import mock

        from ryos import logger, settings, swap, updates
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(os.chdir, os.getcwd())
        self.db_path = self.tmp / "data" / "scripts.db"
        for patch in (mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.tmp / "local")}),
                      mock.patch.object(logger, "setup_logging", lambda *a, **k: None),
                      mock.patch.object(settings, "DB_PATH", self.db_path)):
            patch.start()
            self.addCleanup(patch.stop)
        self.install = self.tmp / "apps" / "RYOS"
        TestApplyUpdate.write(self.install, self.OLD)
        self.zip = self.tmp / "RYOS-windows.zip"
        with zipfile.ZipFile(self.zip, "w") as z:
            for name, body in self.NEW.items():
                z.writestr(name, body)
        self.release = updates.Release("v99.0.0", "https://x/r", False, {})
        self.spawned: list = []
        self.downloads: list = []
        self.asked: list = []
        self.blockers: list = []
        self.problem = None
        self.swap = swap

    def updater(self, **over):
        from ryos import selfupdate
        base = dict(install=self.install, which="windows",
                    running_from=lambda _f: list(self.blockers),
                    write_problem=lambda _i: self.problem,
                    staged=lambda tag: self.zip if tag == "v99.0.0" else None,
                    spawn=lambda argv, cwd: self.spawned.append(list(argv)),
                    effects=self.swap.Effects(wait_for_exit=lambda p, t: True,
                                              spawn=lambda a, c: None,
                                              sleep=lambda s: None),
                    pid=4242)
        base.update(over)
        return selfupdate.Updater(**base)

    def update(self, *argv, updater="default", fetch="default", download=None, answer=None,
               settings=None):
        from ryos import updates
        out, err = io.StringIO(), io.StringIO()

        def ask(question):
            self.asked.append(question)
            return answer

        def fake_download(release):
            self.downloads.append(release.tag)
            return updates.Outcome(True, "ok", self.zip)
        code = cli.main(["update", *argv], db=None, settings=settings, out=out, err=err,
                        ask=ask, updater=self.updater() if updater == "default" else updater,
                        fetch_update=(lambda: self.release) if fetch == "default" else fetch,
                        download_update=download or fake_download)
        return code, out.getvalue(), err.getvalue()

    def refused(self, *words, argv=(), **kw):
        code, out, err = self.update(*argv, **kw)
        self.assertEqual(code, cli.EXIT_REFUSED, err)
        for said in words:
            self.assertIn(said, err)
        self.assertEqual(self.spawned, [])
        return err

    def updated_once(self, from_compatible=1):
        result = self.swap.apply_update(self.install, self.zip, version="v99.0.0",
                                        from_version="1.0.0", which="windows",
                                        effects=self.updater().effects,
                                        from_compatible=from_compatible)
        self.assertEqual(result.code, self.swap.DONE, result.message)

    def test_is_listed(self):
        self.assertIn("update", cli.COMMANDS)
        self.assertTrue(cli.is_cli(["update", "--rollback"]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["--help"], db=None, settings={}), 0)
        self.assertIn("update", out.getvalue())

    def test_from_source(self):
        from ryos import selfupdate
        self.refused("from source does not update itself", updater=selfupdate.Updater())
        self.assertEqual(self.downloads, [])

    def test_a_terminal_inside_the_install(self):
        os.chdir(self.install / "lib")
        try:
            self.refused("cd out of it", argv=("--yes",))
        finally:
            os.chdir(ROOT)

    def test_the_window_open(self):
        self.blockers.append(self.swap_process(77, "RYOS.exe"))
        self.refused("RYOS is open (process 77)", "Restart to update", argv=("--yes",))
        self.assertEqual(self.downloads, [])

    @staticmethod
    def swap_process(pid, name):
        from ryos.selfupdate import Process
        return Process(pid, name)

    def test_an_agents_mcp_server_open(self):
        self.blockers.append(self.swap_process(31337, "ryos-cli.exe"))
        self.refused("process 31337", "MCP server", "Close the agent", argv=("--yes",))
        self.blockers[:] = [self.swap_process(4242, "ryos-cli.exe")]
        code, _out, err = self.update("--yes")
        self.assertEqual(code, cli.EXIT_OK, err)

    def test_not_writable(self):
        from ryos.notifications import _RELEASES_PAGE
        self.problem = f"RYOS cannot write in {self.install.parent} (Access is denied)."
        self.refused("Access is denied", _RELEASES_PAGE, argv=("--yes",))
        self.assertEqual(self.downloads, [])
        self.assertFalse((self.tmp / "local").exists())

    def test_up_to_date(self):
        from ryos import updates
        code, out, _err = self.update(
            "--yes", fetch=lambda: updates.Release(f"v{__version__}", "u", False, {}))
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("Up to date", out)
        self.assertEqual((self.downloads, self.spawned), ([], []))

    def test_the_default_fetch_follows_the_option(self):
        from unittest import mock

        from ryos import updates
        for settings, want in (({"offer_release_candidates": True}, True), ({}, False)):
            asked: list = []

            def recorder(prereleases=False, **_kw):
                asked.append(prereleases)
                return None
            with self.subTest(settings=settings), \
                    mock.patch.object(updates, "fetch_release", recorder):
                code, _out, _err = self.update("--yes", fetch=None, settings=settings)
            self.assertEqual(code, cli.EXIT_FAILED)
            self.assertEqual(asked, [want])

    def test_unreachable(self):
        code, _out, err = self.update("--yes", fetch=lambda: None)
        self.assertEqual(code, cli.EXIT_FAILED)
        self.assertIn("Could not reach GitHub", err)
        self.assertEqual(self.spawned, [])

    def test_a_download_that_fails(self):
        from ryos import updates
        code, _out, err = self.update(
            "--yes", download=lambda r: updates.Outcome(False, "cut off"))
        self.assertEqual(code, cli.EXIT_FAILED)
        self.assertIn("cut off", err)
        self.refused("carries no release key", argv=("--yes",),
                     download=lambda r: updates.Outcome(False, updates.NO_KEY))

    def test_needs_a_terminal_or_yes_then_starts_the_helper(self):
        self.refused("needs you at a terminal")
        self.assertEqual(self.asked, [f"Update RYOS in {self.install} from {__version__} "
                                      "to 99.0.0?"])
        self.refused("Left as it was", answer=False)
        code, out, err = self.update("--yes")
        self.assertEqual(code, cli.EXIT_OK, err)
        self.assertEqual(len(self.spawned), 1)
        argv = self.spawned[0]
        self.assertEqual(argv[1:], ["apply-update", "--install", str(self.install),
                                    "--version", "v99.0.0", "--from-version", __version__,
                                    "--from-compatible", "1", "--wait-pid", "4242"])
        self.assertNotIn("--restart", argv)
        self.assertTrue(Path(argv[0]).is_file())
        self.assertIn("becomes 99.0.0 once this command ends", out)
        self.assertIn("ryos-cli.log", out)

    def test_rollback_with_nothing(self):
        self.refused("no earlier build", argv=("--rollback", "--yes"))

    def test_rollback(self):
        self.updated_once()
        code, out, err = self.update("--rollback", "--yes")
        self.assertEqual(code, cli.EXIT_OK, err)
        self.assertEqual(self.downloads, [])
        argv = self.spawned[0]
        self.assertIn("--rollback", argv)
        self.assertNotIn("--restart", argv)
        self.assertEqual(argv[argv.index("--wait-pid") + 1], "4242")
        self.assertIn("goes back to 1.0.0", out)
        self.assertNotIn("warning", err)

    def test_rollback_across_a_raised_compatible_from_warns(self):
        import sqlite3
        self.updated_once(from_compatible=1)
        self.db_path.parent.mkdir(parents=True)
        with contextlib.closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO meta VALUES ('compatible_from', '2')")
            conn.commit()
        self.refused("needs you at a terminal", argv=("--rollback",))
        self.assertIn("layout 2", self.asked[0])
        code, _out, err = self.update("--rollback", "--yes")
        self.assertEqual(code, cli.EXIT_OK, err)
        self.assertIn("warning", err)
        self.assertIn("layout 2", err)
        self.assertEqual(len(self.spawned), 1)

    def test_rollback_with_unreadable_data_warns(self):
        self.updated_once()
        self.db_path.parent.mkdir(parents=True)
        self.db_path.write_bytes(b"this is not a database, " * 100)
        self.refused("needs you at a terminal", argv=("--rollback",))
        self.assertIn("could not read your data", self.asked[0])
        code, _out, err = self.update("--rollback", "--yes")
        self.assertEqual(code, cli.EXIT_OK, err)
        self.assertIn("could not read your data", err)

    def test_a_newer_database_does_not_block_it(self):
        import sqlite3
        from unittest import mock
        self.db_path.parent.mkdir(parents=True)
        with contextlib.closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO meta VALUES ('compatible_from', '99')")
            conn.commit()

        def boom(*_a, **_k):
            raise AssertionError("update must not open the database")
        with mock.patch.object(cli, "ScriptDB", boom):
            code, _out, err = self.update("--yes")
        self.assertEqual(code, cli.EXIT_OK, err)


class TestMcpInTheBuildWithoutIt(unittest.TestCase):
    def test_says_which_download_has_it_and_exits_refused(self):
        import types
        from unittest import mock
        err = io.StringIO()
        build = types.SimpleNamespace(VARIANT="windows")
        with mock.patch.dict(sys.modules, {"ryos._build_info": build}), \
                mock.patch.object(sys, "stderr", err):
            self.assertEqual(cli.main(["mcp"]), cli.EXIT_REFUSED)
        said = err.getvalue()
        self.assertIn("isn't included in this download (RYOS-windows.zip)", said)
        self.assertIn("RYOS-windows-ai.zip", said)
        self.assertIn("RYOS-agent.zip", said)


class TestMcpWithoutTheSdk(unittest.TestCase):
    def test_says_how_to_get_it_and_exits_refused(self):
        from unittest import mock
        err = io.StringIO()
        # None in sys.modules makes `import mcp` fail, as with no SDK installed.
        with mock.patch.dict(sys.modules, {"mcp": None}), mock.patch.object(sys, "stderr", err):
            self.assertEqual(cli.main(["mcp"]), cli.EXIT_REFUSED)
        self.assertIn("--extra mcp", err.getvalue())


class TestTheRealEntryPoint(unittest.TestCase):
    def test_takes_no_lock_writes_no_startup_entry_and_imports_no_qt(self):
        data = Path(tempfile.mkdtemp())
        probe = (
            "import sys\n"
            "import ryos.__main__ as m\n"
            "def boom(*a, **k): raise AssertionError('not for the CLI')\n"
            "m.single_instance.acquire = boom\n"
            "m._sync_startup_command = boom\n"
            "sys.argv = ['ryos', 'list', '--json']\n"
            "code = m.main()\n"
            "print('QT' if 'PySide6' in sys.modules else 'NOQT', code)\n"
        )
        env = {**os.environ, "APPDATA": str(data), "LOCALAPPDATA": str(data / "local"),
               "RYOS_NO_REGISTRY": "1", "RYOS_NO_TOASTS": "1"}
        proc = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.strip().splitlines()
        self.assertEqual(json.loads(lines[0]), {"scripts": [], "pipelines": []})
        self.assertEqual(lines[-1], "NOQT 0")
        # Its own log: two processes must not both rotate the window's.
        logs = data / "RYOS" / "logs"
        self.assertTrue((logs / "ryos-cli.log").exists())
        self.assertFalse((logs / "ryos.log").exists())

    def test_apply_update_takes_no_lock_writes_no_startup_entry_and_imports_no_qt(self):
        data = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, data, ignore_errors=True)
        probe = (
            "import sys\n"
            "import ryos.__main__ as m\n"
            "def boom(*a, **k): raise AssertionError('not for the CLI')\n"
            "m.single_instance.acquire = boom\n"
            "m._sync_startup_command = boom\n"
            f"sys.argv = ['ryos', 'apply-update', '--install', {str(data / 'RYOS')!r}, "
            "'--recover']\n"
            "code = m.main()\n"
            "print('QT' if 'PySide6' in sys.modules else 'NOQT', code)\n"
        )
        env = {**os.environ, "APPDATA": str(data), "LOCALAPPDATA": str(data / "local"),
               "RYOS_NO_REGISTRY": "1", "RYOS_NO_TOASTS": "1"}
        proc = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip().splitlines()[-1], f"NOQT {cli.EXIT_REFUSED}")
        self.assertIn("from source", proc.stderr)

    def test_update_takes_no_lock_writes_no_startup_entry_and_imports_no_qt(self):
        data = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, data, ignore_errors=True)
        probe = (
            "import sys\n"
            "import ryos.__main__ as m\n"
            "def boom(*a, **k): raise AssertionError('not for the CLI')\n"
            "m.single_instance.acquire = boom\n"
            "m._sync_startup_command = boom\n"
            "sys.argv = ['ryos', 'update', '--yes']\n"
            "code = m.main()\n"
            "print('QT' if 'PySide6' in sys.modules else 'NOQT', code)\n"
        )
        env = {**os.environ, "APPDATA": str(data), "LOCALAPPDATA": str(data / "local"),
               "RYOS_NO_REGISTRY": "1", "RYOS_NO_TOASTS": "1"}
        proc = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip().splitlines()[-1], f"NOQT {cli.EXIT_REFUSED}")
        self.assertIn("from source does not update itself", proc.stderr)
        self.assertFalse((data / "RYOS" / "scripts.db").exists())


if __name__ == "__main__":
    unittest.main()
