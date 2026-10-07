"""What an agent may do (``ryos/agenttools.py``), without an MCP client:
only what was made available, presets not free text, output in pages.

These run real tiny scripts through the real pump thread, against a
throwaway database.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ryos.agenttools import MAX_LINE, MAX_PAGE, AgentError, AgentTools  # noqa: E402
from ryos.db import SOURCE_AGENT, ScriptDB  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = ScriptDB(self.tmp / "t.db")
        for g in ("A", "B"):
            self.db.create_group(g)
        self.notified = 0

        def notify():
            self.notified += 1
        self.tools = AgentTools(self.db, {"launcher_release_seconds": 0},
                                notify_window=notify)
        self.addCleanup(self.tools.close)

    def script(self, name, body, group="A", exposed=True, params=""):
        path = self.tmp / f"{name.replace(' ', '_')}_{group}.py"
        path.write_text(body, encoding="utf-8")
        sid = self.db.add(name, str(path), params, sys.executable, group)
        self.db.set_agent_exposed("script", sid, exposed)
        return sid

    def finish(self, run_id):
        """Wait (through get_run's own wait) until the run is done.

        Each wait is past the lines already read: get_run counts any line
        past ``offset`` as news, so waiting from 0 returns at once after the
        first line and the tries ran out before a slow runner's script exited.
        """
        offset = 0
        for _ in range(60):
            got = self.tools.get_run(run_id, offset=offset, wait_seconds=1)
            if got["done"]:
                return self.tools.get_run(run_id)
            offset = got["next_offset"]
        self.fail("the run did not finish")


class TestOnlyWhatWasMadeAvailable(_Base):
    def setUp(self):
        super().setUp()
        self.open = self.script("deploy", "print('ok')\n")
        self.secret = self.script("wipe", "print('no')\n", exposed=False)
        self.twin = self.script("deploy", "print('ok')\n", group="B", exposed=False)

    def test_lists_only_available_items(self):
        self.assertEqual([s["ref"] for s in self.tools.list_scripts()], ["A/deploy"])
        pid = self.db.create_pipeline("ship", "A")
        hidden = self.db.create_pipeline("ship2", "A")
        self.db.add_pipeline_step(pid, self.open)
        self.db.set_agent_exposed("pipeline", pid, True)
        self.assertEqual([p["ref"] for p in self.tools.list_pipelines()], ["A/ship"])
        self.assertNotIn(hidden, [p["id"] for p in self.tools.list_pipelines()])

    def test_an_unavailable_item_is_not_there(self):
        for ref in ("wipe", f"#{self.secret}", "A/wipe"):
            with self.subTest(ref), self.assertRaisesRegex(AgentError, "available to agents"):
                self.tools.run_script(ref)

    def test_an_unavailable_twin_does_not_make_a_name_ambiguous(self):
        # B/deploy exists but is not available: "deploy" means A/deploy, and
        # the refusal of nothing names B's.
        run = self.tools.run_script("deploy")
        self.assertEqual(run["ref"], "A/deploy")

    def test_unticking_takes_effect_at_once(self):
        self.db.set_agent_exposed("script", self.open, False)
        self.assertEqual(self.tools.list_scripts(), [])
        with self.assertRaises(AgentError):
            self.tools.run_script("deploy")


class TestRunning(_Base):
    def test_a_run_reports_its_output_and_outcome(self):
        self.script("hello", "print('one')\nprint('two')\n")
        started = self.tools.run_script("hello")
        self.assertIn(started["status"], ("running", "ok"))
        done = self.finish(started["run_id"])
        self.assertEqual((done["status"], done["exit_code"]), ("ok", 0))
        self.assertEqual(done["lines"][:2], ["one", "two"])
        self.assertEqual(done["next_offset"], done["total_lines"])
        self.assertEqual(self.db.list_runs()[0][10], SOURCE_AGENT)

    def test_presets_by_label_and_nothing_else(self):
        sid = self.script("args", "import sys\nprint(' '.join(sys.argv[1:]))\n",
                          params="--own")
        self.db.replace_param_presets(sid, [("quick", "--quick")])
        self.assertEqual(self.finish(self.tools.run_script("args")["run_id"])["lines"][0],
                         "--own")
        self.assertEqual(
            self.finish(self.tools.run_script("args", "quick")["run_id"])["lines"][0],
            "--quick")
        with self.assertRaisesRegex(AgentError, "no preset"):
            self.tools.run_script("args", "--rm -rf")

    def test_a_failure(self):
        self.script("boom", "import sys\nsys.exit(5)\n")
        done = self.finish(self.tools.run_script("boom")["run_id"])
        self.assertEqual((done["status"], done["exit_code"]), ("error", 5))

    def test_stop(self):
        self.script("slow", "import time\nprint('up', flush=True)\ntime.sleep(60)\n")
        run_id = self.tools.run_script("slow")["run_id"]
        self.tools.stop_run(run_id)
        self.assertEqual(self.finish(run_id)["status"], "stopped")

    def test_not_twice_at_once(self):
        self.script("slow", "import time\ntime.sleep(60)\n")
        self.tools.run_script("slow")
        with self.assertRaisesRegex(AgentError, "already running"):
            self.tools.run_script("slow")

    def test_a_pipeline(self):
        one = self.script("one", "print('first')\n")
        pid = self.db.create_pipeline("ship", "A")
        self.db.add_pipeline_step(pid, one)
        self.db.set_agent_exposed("pipeline", pid, True)
        done = self.finish(self.tools.run_pipeline("ship")["run_id"])
        self.assertEqual(done["status"], "ok")
        self.assertIn("first", done["lines"])

    def test_a_running_window_is_told(self):
        self.script("hello", "print('hi')\n")
        self.finish(self.tools.run_script("hello")["run_id"])
        for _ in range(20):          # the pump tells it on its next turn
            if self.notified:
                break
            self.tools.get_run(1, wait_seconds=0.1)
        self.assertGreaterEqual(self.notified, 1)

    def test_an_unknown_run(self):
        with self.assertRaisesRegex(AgentError, "No run 999"):
            self.tools.get_run(999)


class TestOutputInPages(_Base):
    def test_pages_and_long_lines(self):
        self.script("chatty", (
            "for i in range(1200):\n    print(i)\n"
            f"print('x' * {MAX_LINE + 50})\n"))
        run_id = self.tools.run_script("chatty")["run_id"]
        self.finish(run_id)
        first = self.tools.get_run(run_id, limit=10_000)
        self.assertEqual(len(first["lines"]), MAX_PAGE)
        self.assertEqual(first["lines"][0], "0")
        rest = self.tools.get_run(run_id, offset=1200, limit=5)
        self.assertTrue(rest["lines"][0].endswith("…[line cut]"))
        self.assertLessEqual(len(rest["lines"][0]), MAX_LINE + 20)

    def test_wait_returns_as_soon_as_there_is_news(self):
        self.script("slow", "import time\nprint('started', flush=True)\ntime.sleep(60)\n")
        run_id = self.tools.run_script("slow")["run_id"]
        got = self.tools.get_run(run_id, wait_seconds=20)
        self.assertFalse(got["done"])
        self.assertEqual(got["lines"], ["started"])
        self.tools.stop_run(run_id)


if __name__ == "__main__":
    unittest.main()
