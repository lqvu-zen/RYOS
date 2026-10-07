"""The headless runner: runs with no window, through the same JobHost.

These start real (tiny) Python scripts, as the window would. Each test has
its own throwaway database and folder.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ryos.db import FAIL_CONTINUE, SOURCE_AGENT, SOURCE_CLI, ScriptDB  # noqa: E402
from ryos.headless import (MAX_LINES, PIPELINE, SCRIPT, TIMEOUT,  # noqa: E402
                           HeadlessError, HeadlessRunner, Run, Target, resolve)
from ryos.jobs import STOPPED  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = ScriptDB(self.tmp / "t.db")
        for g in ("A", "B"):
            self.db.create_group(g)
        self.runner = HeadlessRunner(self.db, {"launcher_release_seconds": 0})
        self.addCleanup(self.runner.stop_all)

    def script(self, name: str, body: str, group: str = "A", params: str = "",
               detached: int = 0) -> int:
        path = self.tmp / f"{name.replace(' ', '_')}_{group}.py"
        path.write_text(body, encoding="utf-8")
        return self.db.add(name, str(path), params, sys.executable, group, 0, detached)

    def target(self, kind, item_id):
        return resolve(self.db, kind, f"#{item_id}")


class TestResolve(_Base):
    def setUp(self):
        super().setUp()
        self.a = self.script("build", "")
        self.b = self.script("build", "", group="B")
        self.only = self.script("lint", "")
        self.pipe = self.db.create_pipeline("ship", "A")

    def test_a_unique_name_group_name_or_id(self):
        self.assertEqual(resolve(self.db, SCRIPT, "lint").item_id, self.only)
        self.assertEqual(resolve(self.db, SCRIPT, "B/build").item_id, self.b)
        self.assertEqual(resolve(self.db, SCRIPT, f"#{self.a}").item_id, self.a)
        self.assertEqual(resolve(self.db, PIPELINE, "ship"),
                         Target(PIPELINE, self.pipe, "ship", "A"))

    def test_a_name_in_two_groups_is_refused_with_both(self):
        with self.assertRaises(HeadlessError) as cm:
            resolve(self.db, SCRIPT, "build")
        self.assertIn("'A/build'", str(cm.exception))
        self.assertIn("'B/build'", str(cm.exception))

    def test_not_found(self):
        for kind, ref in ((SCRIPT, "nope"), (SCRIPT, "#999"), (PIPELINE, "lint")):
            with self.subTest(ref), self.assertRaises(HeadlessError):
                resolve(self.db, kind, ref)


class TestRunningAScript(_Base):
    def test_output_and_a_pass(self):
        sid = self.script("hello", "print('one')\nprint('two')\n")
        run = self.runner.wait(self.runner.start_script(self.target(SCRIPT, sid)), 30)
        self.assertEqual((run.status, run.exit_code), ("ok", 0))
        # What the window shows: the script's lines, then the exit footer.
        self.assertEqual(list(run.lines)[:2], ["one", "two"])
        self.assertIn("exit code 0", run.tail(1)[0])
        self.assertIsNotNone(run.finished_at)

    def test_a_failure_keeps_its_exit_code(self):
        sid = self.script("boom", "import sys\nprint('bad', file=sys.stderr)\nsys.exit(3)\n")
        run = self.runner.wait(self.runner.start_script(self.target(SCRIPT, sid)), 30)
        self.assertEqual((run.status, run.exit_code), ("error", 3))
        self.assertIn("bad", run.lines)

    def test_parameters_and_presets(self):
        sid = self.script("args", "import sys\nprint(' '.join(sys.argv[1:]))\n",
                          params="--own")
        self.db.replace_param_presets(sid, [("quick", "--quick 1")])
        t = self.target(SCRIPT, sid)
        for kwargs, want in (({}, "--own"), ({"params": "--x y"}, "--x y"),
                             ({"preset": "quick"}, "--quick 1")):
            with self.subTest(**kwargs):
                run = self.runner.wait(self.runner.start_script(t, **kwargs), 30)
                self.assertEqual(run.lines[0], want)
        with self.assertRaisesRegex(HeadlessError, "no preset 'slow'.*'quick'"):
            self.runner.start_script(t, preset="slow")
        with self.assertRaisesRegex(HeadlessError, "not both"):
            self.runner.start_script(t, params="-a", preset="quick")

    def test_a_timeout_stops_it(self):
        sid = self.script("slow", "import time\nprint('started', flush=True)\ntime.sleep(60)\n")
        run = self.runner.wait(self.runner.start_script(self.target(SCRIPT, sid)), 1.0)
        self.assertEqual(run.status, TIMEOUT)
        # History says what happened to the process: it was stopped.
        self.assertEqual(self.db.list_runs(script_id=sid)[0][7], STOPPED)

    def test_stop(self):
        sid = self.script("slow", "import time\ntime.sleep(60)\n")
        run = self.runner.start_script(self.target(SCRIPT, sid))
        self.runner.stop(run)
        self.assertEqual(self.runner.wait(run, 30).status, STOPPED)

    def test_the_same_script_twice_is_refused(self):
        sid = self.script("slow", "import time\ntime.sleep(60)\n")
        t = self.target(SCRIPT, sid)
        self.runner.start_script(t)
        with self.assertRaisesRegex(HeadlessError, "already running"):
            self.runner.start_script(t)

    def test_a_missing_file_is_refused(self):
        sid = self.db.add("ghost", str(self.tmp / "nope.py"), "", sys.executable, "A")
        with self.assertRaisesRegex(HeadlessError, "File Not Found"):
            self.runner.start_script(self.target(SCRIPT, sid))

    def test_a_launcher_is_released(self):
        sid = self.script("server", "import time\nprint('up', flush=True)\ntime.sleep(60)\n",
                          detached=1)
        run = self.runner.wait(self.runner.start_script(self.target(SCRIPT, sid)), 30)
        self.assertEqual((run.status, run.exit_code), ("ok", None))

    def test_history_says_who_started_it(self):
        sid = self.script("hello", "print('hi')\n")
        self.runner.wait(self.runner.start_script(self.target(SCRIPT, sid)), 30)
        agent = HeadlessRunner(self.db, trigger=SOURCE_AGENT)
        agent.wait(agent.start_script(self.target(SCRIPT, sid)), 30)
        self.assertEqual([r[10] for r in self.db.list_runs(script_id=sid)],
                         [SOURCE_AGENT, SOURCE_CLI])

    def test_output_streams_to_the_caller(self):
        seen = []
        runner = HeadlessRunner(self.db, on_output=lambda run, text, tag: seen.append(text))
        sid = self.script("hello", "print('hi')\n")
        runner.wait(runner.start_script(self.target(SCRIPT, sid)), 30)
        self.assertIn("hi", "".join(seen))


class TestRunningAPipeline(_Base):
    def pipeline(self, *script_ids):
        pid = self.db.create_pipeline("ship", "A")
        steps = [self.db.add_pipeline_step(pid, sid) for sid in script_ids]
        return pid, steps

    def test_steps_run_in_order(self):
        one = self.script("one", "print('first')\n")
        two = self.script("two", "print('second')\n")
        pid, _ = self.pipeline(one, two)
        run = self.runner.wait(self.runner.start_pipeline(self.target(PIPELINE, pid)), 30)
        self.assertEqual(run.status, "ok")
        out = list(run.lines)
        self.assertLess(out.index("first"), out.index("second"))

    def test_a_failed_step_stops_it_unless_told_to_continue(self):
        bad = self.script("bad", "import sys\nsys.exit(1)\n")
        after = self.script("after", "print('after ran')\n")
        pid, steps = self.pipeline(bad, after)
        run = self.runner.wait(self.runner.start_pipeline(self.target(PIPELINE, pid)), 30)
        self.assertEqual(run.status, "error")
        self.assertNotIn("after ran", run.lines)

        self.db.set_step_policy(steps[0], on_failure=FAIL_CONTINUE)
        run = self.runner.wait(self.runner.start_pipeline(self.target(PIPELINE, pid)), 30)
        self.assertEqual(run.status, "ok")
        self.assertIn("after ran", run.lines)

    def test_a_retry(self):
        marker = self.tmp / "tried"
        flaky = self.script("flaky", (
            "import pathlib, sys\n"
            f"m = pathlib.Path({str(marker)!r})\n"
            "if not m.exists():\n    m.write_text('x')\n    sys.exit(1)\n"
            "print('second try')\n"))
        pid, steps = self.pipeline(flaky)
        self.db.set_step_policy(steps[0], retries=1)
        run = self.runner.wait(self.runner.start_pipeline(self.target(PIPELINE, pid)), 30)
        self.assertEqual(run.status, "ok")
        self.assertIn("second try", run.lines)

    def test_stop(self):
        slow = self.script("slow", "import time\ntime.sleep(60)\n")
        never = self.script("never", "print('never')\n")
        pid, _ = self.pipeline(slow, never)
        run = self.runner.start_pipeline(self.target(PIPELINE, pid))
        self.runner.stop(run)
        run = self.runner.wait(run, 30)
        self.assertEqual(run.status, STOPPED)
        self.assertNotIn("never", run.lines)

    def test_an_empty_pipeline_is_refused(self):
        pid = self.db.create_pipeline("empty", "A")
        with self.assertRaisesRegex(HeadlessError, "Empty Pipeline"):
            self.runner.start_pipeline(self.target(PIPELINE, pid))


class TestRunOutput(unittest.TestCase):
    """The bounded buffer: lines kept, lines dropped, paging past drops."""

    def make(self, keep=3):
        run = Run(1, Target(SCRIPT, 1, "x", "A"), started_at=None)  # type: ignore[arg-type]
        run.lines = deque(maxlen=keep)
        return run

    def test_lines_split_across_chunks(self):
        run = self.make(10)
        run._add("a\r\nb")
        run._add("c\nd")
        run._close()
        self.assertEqual(list(run.lines), ["a", "bc", "d"])

    def test_old_lines_are_dropped_and_paging_skips_them(self):
        run = self.make(3)
        run._add("".join(f"{i}\n" for i in range(5)))
        self.assertEqual((run.total, run.dropped), (5, 2))
        self.assertEqual(run.page(0, 2), (["2", "3"], 4))
        self.assertEqual(run.page(4, 10), (["4"], 5))
        self.assertEqual(run.page(5, 10), ([], 5))

    def test_the_default_cap(self):
        self.assertGreaterEqual(MAX_LINES, 1000)


if __name__ == "__main__":
    os.environ.setdefault("RYOS_NO_TOASTS", "1")
    unittest.main()
