"""The command line: ``ryos list`` / ``run`` / ``pipeline``.

Most tests call ``cli.main`` with a throwaway database and a stand-in for
"tell the running window"; one runs the real entry point in a child process
with APPDATA pointed at a temp folder, to prove the CLI path never takes the
instance lock, writes run-at-login or imports Qt.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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
        env = {**os.environ, "APPDATA": str(data), "RYOS_NO_REGISTRY": "1",
               "RYOS_NO_TOASTS": "1"}
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


if __name__ == "__main__":
    unittest.main()
