"""When RYOS swaps in an update or rolls one back (``ryos/selfupdate.py``):
the pure rules and their words, the probes, and what start-up does, on real
temporary folders with the helper's spawn recorded instead of run."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ryos import selfupdate, swap  # noqa: E402
from ryos.db import ScriptDB  # noqa: E402
from ryos.notifications import _RELEASES_PAGE  # noqa: E402
from ryos.selfupdate import Process  # noqa: E402

OLD = {"RYOS.exe": b"old window", "ryos-cli.exe": b"old cli", "lib/a.pyc": b"old a"}
NEW = {"RYOS.exe": b"new window!", "ryos-cli.exe": b"new cli!", "lib/a.pyc": b"new a"}


class _Crash(BaseException):
    pass


def write_tree(folder: Path, files: dict) -> None:
    for name, body in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(body)


class TestDecide(unittest.TestCase):
    install = Path("C:/Apps/RYOS")

    def decide(self, kind=selfupdate.UPDATE, **over):
        kw = dict(where=selfupdate.WINDOW, which="windows", install=self.install,
                  current="1.0.0", target="v2.0.0", blockers=[], write_problem=None,
                  active_runs=0, due=0)
        kw.update(over)
        return selfupdate.decide(kind, **kw)

    def test_go(self):
        d = self.decide()
        self.assertEqual(d.verdict, selfupdate.GO)
        self.assertIsNone(d.warning)
        self.assertEqual(self.decide(where=selfupdate.CLI).text,
                         f"Update RYOS in {self.install} from 1.0.0 to 2.0.0?")

    def test_portable(self):
        for over in ({"which": "portable"}, {"install": None}):
            with self.subTest(**over):
                d = self.decide(**over)
                self.assertEqual(d.verdict, selfupdate.PORTABLE)
                self.assertIn("from source does not update itself", d.text)

    def test_nothing_staged_or_already_installed(self):
        self.assertEqual(self.decide(target=None).verdict, selfupdate.NOTHING)
        d = self.decide(target="v1.0.0")
        self.assertEqual(d.verdict, selfupdate.NOTHING)
        self.assertIn("already installed", d.text)
        self.assertEqual(self.decide(target="v0.9.0").verdict, selfupdate.NOTHING)

    def test_not_writable(self):
        problem = f"RYOS cannot write in {self.install.parent} (Access is denied)."
        d = self.decide(write_problem=problem)
        self.assertEqual(d.verdict, selfupdate.NOT_WRITABLE)
        self.assertIn(problem, d.text)
        self.assertIn("release page opens", d.text)
        d = self.decide(write_problem=problem, where=selfupdate.CLI)
        self.assertIn(problem, d.text)
        self.assertIn(_RELEASES_PAGE, d.text)

    def test_blocked_by_an_agents_mcp_server(self):
        held = [Process(4321, "ryos-cli.exe")]
        d = self.decide(blockers=held)
        self.assertEqual(d.verdict, selfupdate.BLOCKED)
        for words in ("ryos-cli.exe (process 4321)", str(self.install), "MCP server",
                      "Update the next time RYOS starts?"):
            self.assertIn(words, d.text)
        d = self.decide(blockers=held, where=selfupdate.CLI)
        self.assertIn("process 4321", d.text)
        self.assertIn("MCP server", d.text)
        self.assertIn("Close the agent and run `ryos-cli update` again.", d.text)
        d = self.decide(selfupdate.ROLLBACK, blockers=held)
        self.assertNotIn("next time", d.text)
        self.assertIn("close it", d.text)

    def test_blocked_by_the_window_from_the_cli(self):
        d = self.decide(blockers=[Process(77, "RYOS.exe")], where=selfupdate.CLI)
        self.assertEqual(d.verdict, selfupdate.BLOCKED)
        self.assertIn("RYOS is open (process 77)", d.text)
        self.assertIn("Restart to update", d.text)

    def test_busy(self):
        d = self.decide(active_runs=2, due=3)
        self.assertEqual(d.verdict, selfupdate.BUSY)
        self.assertIn("2 runs are going", d.text)
        self.assertIn("never stops a run", d.text)
        self.assertIn("1 run is going", self.decide(active_runs=1).text)

    def test_due_only(self):
        d = self.decide(due=1)
        self.assertEqual(d.verdict, selfupdate.DUE)
        self.assertIn("1 scheduled run is due within 5 minutes", d.text)

    def test_priority_order(self):
        everything = dict(which="portable", target=None, write_problem="no",
                          blockers=[Process(1, "ryos-cli.exe")], active_runs=1, due=1)
        order = [("which", "windows", selfupdate.NOTHING),
                 ("target", "v2.0.0", selfupdate.NOT_WRITABLE),
                 ("write_problem", None, selfupdate.BLOCKED),
                 ("blockers", [], selfupdate.BUSY),
                 ("active_runs", 0, selfupdate.DUE),
                 ("due", 0, selfupdate.GO)]
        self.assertEqual(self.decide(**everything).verdict, selfupdate.PORTABLE)
        for key, value, verdict in order:
            everything[key] = value
            self.assertEqual(self.decide(**everything).verdict, verdict, key)

    def test_rollback_with_nothing(self):
        d = self.decide(selfupdate.ROLLBACK, target=None)
        self.assertEqual(d.verdict, selfupdate.NOTHING)
        self.assertIn("no earlier build", d.text)

    def test_rollback_across_a_raised_compatible_from_warns(self):
        d = self.decide(selfupdate.ROLLBACK, target="1.0.0", db_needs=2, previous_accepts=1)
        self.assertEqual(d.verdict, selfupdate.GO)
        self.assertEqual(d.text, "Roll back RYOS to 1.0.0? RYOS restarts.")
        self.assertIn("layout 2", d.warning)
        self.assertIn("layout 1", d.warning)
        self.assertIn("RYOS 1.0.0", d.warning)
        busy = self.decide(selfupdate.ROLLBACK, target="1.0.0", db_needs=2,
                           previous_accepts=1, active_runs=1)
        self.assertEqual(busy.warning, d.warning)
        self.assertIsNone(self.decide(selfupdate.ROLLBACK, target="1.0.0", db_needs=2,
                                      previous_accepts=2).warning)
        self.assertIsNone(self.decide(db_needs=2, previous_accepts=1).warning)

    def test_rollback_with_unreadable_data_warns(self):
        d = self.decide(selfupdate.ROLLBACK, target="1.0.0", db_needs=None,
                        previous_accepts=1)
        self.assertEqual(d.verdict, selfupdate.GO)
        self.assertIn("could not read your data", d.warning)
        self.assertIsNone(self.decide(db_needs=None).warning)

    def test_words(self):
        self.assertEqual(selfupdate.ready_text("v2.4.0", "2.3.1"),
                         "Update ready \u2014 RYOS 2.4.0 (you have v2.3.1)")
        self.assertEqual(selfupdate.rollback_label("1.0.0"), "Roll back to RYOS 1.0.0\u2026")
        self.assertEqual(selfupdate.rollback_label(None), "Roll back to the previous version")
        self.assertIn("2 runs", selfupdate.waiting_text(2))
        self.assertIn("next time RYOS starts", selfupdate.at_start_text("v2.4.0"))


class TestDueSoon(unittest.TestCase):
    def test_only_enabled_schedules_due_within_five_minutes(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        db = ScriptDB(tmp / "t.db")
        db.create_group("G")
        sid = db.add("s", str(tmp / "s.py"), "", sys.executable, "G")
        now = datetime(2026, 10, 15, 12, 0, 0)
        self.assertEqual(selfupdate.due_soon(db, now), 0)
        for minutes, enabled in ((10, True), (3, False)):
            db.add_schedule("script", script_id=sid, spec_type="interval", spec="60",
                            enabled=enabled, next_run_at=now + timedelta(minutes=minutes))
        self.assertEqual(selfupdate.due_soon(db, now), 0)
        db.add_schedule("script", script_id=sid, spec_type="interval", spec="60",
                        enabled=True, next_run_at=now + timedelta(minutes=3))
        self.assertEqual(selfupdate.due_soon(db, now), 1)
        self.assertEqual(selfupdate.due_soon(db, now, timedelta(minutes=15)), 2)


class TestWriteProblem(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.install = self.tmp / "apps" / "RYOS"
        write_tree(self.install, OLD)

    def test_writable_gives_none_and_leaves_nothing(self):
        before = (sorted(os.listdir(self.install.parent)), sorted(os.listdir(self.install)))
        self.assertIsNone(selfupdate.write_problem(self.install))
        self.assertEqual((sorted(os.listdir(self.install.parent)),
                          sorted(os.listdir(self.install))), before)

    def test_the_parent_refusing_names_it(self):
        def denied(*_a, **_k):
            raise PermissionError(13, "Access is denied")
        with mock.patch("ryos.selfupdate.os.mkdir", denied):
            words = selfupdate.write_problem(self.install)
        self.assertIn(str(self.install.parent), words)
        self.assertIn("Access is denied", words)

    def test_the_folder_refusing_names_it(self):
        def denied(*_a, **_k):
            raise PermissionError(13, "Access is denied")
        with mock.patch("ryos.selfupdate.open", denied, create=True):
            words = selfupdate.write_problem(self.install)
        self.assertEqual(words, f"RYOS cannot write in {self.install} (Access is denied).")
        self.assertEqual(sorted(os.listdir(self.install.parent)), ["RYOS"])

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "geteuid")
                         and os.geteuid() != 0, "needs a non-root posix user")
    def test_a_read_only_parent(self):
        os.chmod(self.install.parent, 0o555)
        self.addCleanup(os.chmod, self.install.parent, 0o755)
        self.assertIn(str(self.install.parent), selfupdate.write_problem(self.install))


class TestRunningFrom(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "the process probe is Windows only")
    def test_finds_this_process_by_its_folder(self):
        folders = {Path(sys.executable).parent,
                   Path(getattr(sys, "_base_executable", sys.executable)).parent}
        found = [p for folder in folders for p in selfupdate.running_from(folder)]
        self.assertIn(os.getpid(), [p.pid for p in found])
        self.assertTrue(all(p.name.lower().endswith(".exe") for p in found))

    def test_an_empty_folder_runs_nothing(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.assertEqual(selfupdate.running_from(tmp), [])
        self.assertEqual(selfupdate.running_from(None), [])


class _Installed(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        env = mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.tmp / "local")})
        env.start()
        self.addCleanup(env.stop)
        self.install = self.tmp / "apps" / "RYOS"
        write_tree(self.install, OLD)
        self.zip = self.tmp / "RYOS-windows.zip"
        with zipfile.ZipFile(self.zip, "w") as z:
            for name, body in NEW.items():
                z.writestr(name, body)
        self.spawned: list = []
        self.slept: list = []
        self.blockers: list = []

    def effects(self, **over):
        base = dict(wait_for_exit=lambda pid, t: True,
                    spawn=lambda argv, cwd: self.spawned.append(("swap", list(argv))),
                    sleep=self.slept.append)
        base.update(over)
        return swap.Effects(**base)

    def updater(self, **over):
        base = dict(install=self.install, which="windows",
                    running_from=lambda _f: list(self.blockers),
                    write_problem=lambda _i: None,
                    staged=lambda tag: self.zip if tag == "v9.0.0" else None,
                    spawn=lambda argv, cwd: self.spawned.append((list(argv), Path(cwd))),
                    effects=self.effects(), pid=4242)
        base.update(over)
        return selfupdate.Updater(**base)

    def updated(self):
        result = swap.apply_update(self.install, self.zip, version="v9.0.0",
                                   from_version="1.0.0", which="windows", restart=True,
                                   effects=self.effects(), from_compatible=2)
        self.assertEqual(result.code, swap.DONE, result.message)
        self.spawned.clear()


class TestPrepare(_Installed):
    def test_update(self):
        argv, cwd = selfupdate.prepare(self.updater(), selfupdate.UPDATE, tag="v9.0.0",
                                       current="1.0.0", compatible_from=3, restart=True)
        self.assertEqual(Path(argv[0]).parent, cwd)
        self.assertEqual(argv[1:], ["apply-update", "--install", str(self.install),
                                    "--version", "v9.0.0", "--from-version", "1.0.0",
                                    "--from-compatible", "3", "--wait-pid", "4242",
                                    "--restart"])
        self.assertTrue(Path(argv[0]).is_file())

    def test_rollback(self):
        self.updated()
        argv, cwd = selfupdate.prepare(self.updater(), selfupdate.ROLLBACK, tag=None,
                                       current="9.0.0", compatible_from=2, restart=False)
        self.assertEqual(cwd, swap.journal_dir_for(self.install) / "rollback-helper")
        self.assertEqual(argv[1:], ["apply-update", "--install", str(self.install),
                                    "--rollback", "--from-version", "9.0.0",
                                    "--from-compatible", "2", "--wait-pid", "4242"])

    def test_errors_give_words(self):
        with self.assertRaises(swap.SwapError) as caught:
            selfupdate.prepare(self.updater(), selfupdate.UPDATE, tag="v8.0.0",
                               current="1.0.0", compatible_from=1, restart=True)
        self.assertIn("no longer downloaded and checked", str(caught.exception))
        with self.assertRaises(swap.SwapError) as caught:
            selfupdate.prepare(self.updater(), selfupdate.ROLLBACK, tag=None,
                               current="1.0.0", compatible_from=1, restart=True)
        self.assertIn("no earlier build", str(caught.exception))
        with self.assertRaises(swap.SwapError):
            selfupdate.prepare(selfupdate.Updater(), selfupdate.UPDATE, tag="v9.0.0",
                               current="1.0.0", compatible_from=1, restart=True)


class TestAtStart(_Installed):
    def start(self, updater=None, current="1.0.0", **kw):
        return selfupdate.at_start(current, updater or self.updater(), compatible_from=1,
                                   **kw)

    def test_from_source_does_nothing(self):
        self.assertEqual(selfupdate.at_start("1.0.0", selfupdate.Updater(),
                                             compatible_from=1),
                         selfupdate.AtStart(False, ()))
        self.assertFalse((self.tmp / "local").exists())

    def test_a_pending_request_is_carried_out_once(self):
        selfupdate.request_at_start(self.install, "v9.0.0")
        self.assertEqual(selfupdate.pending_at_start(self.install), "v9.0.0")
        started = self.start()
        self.assertTrue(started.applying)
        self.assertEqual(len(self.spawned), 1)
        argv, _cwd = self.spawned[0]
        self.assertEqual(argv[argv.index("--version") + 1], "v9.0.0")
        self.assertEqual(argv[argv.index("--wait-pid") + 1], "4242")
        self.assertIn("--restart", argv)
        self.assertIsNone(selfupdate.pending_at_start(self.install))
        self.assertEqual(self.start(), selfupdate.AtStart(False, ()))
        self.assertEqual(len(self.spawned), 1)

    def test_at_start_json_fields_are_pinned(self):
        selfupdate.request_at_start(self.install, "v9.0.0")
        path = swap.journal_dir_for(self.install) / "at-start.json"
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                         {"install": str(self.install), "tag": "v9.0.0"})

    def test_the_probes_run_once_and_their_answer_is_used(self):
        selfupdate.request_at_start(self.install, "v9.0.0")
        answers = [[Process(99, "ryos-cli.exe")], []]
        problems = [None, "RYOS cannot write in X (denied)."]
        calls = {"running": 0, "write": 0}

        def running(_folder):
            calls["running"] += 1
            return answers.pop(0)

        def write(_install):
            calls["write"] += 1
            return problems.pop(0)
        started = self.start(self.updater(running_from=running, write_problem=write))
        self.assertEqual(calls, {"running": 1, "write": 1})
        self.assertFalse(started.applying)
        (_level, _title, text), = started.notes
        self.assertIn("process 99", text)
        self.assertNotIn("None", text)

    def test_a_blocker_keeps_the_request_and_says_so(self):
        selfupdate.request_at_start(self.install, "v9.0.0")
        self.blockers.append(Process(99, "ryos-cli.exe"))
        started = self.start()
        self.assertFalse(started.applying)
        self.assertEqual(self.spawned, [])
        self.assertEqual(selfupdate.pending_at_start(self.install), "v9.0.0")
        (_level, _title, text), = started.notes
        self.assertIn("process 99", text)
        self.assertIn("next time it starts", text)

    def test_its_own_process_does_not_block(self):
        selfupdate.request_at_start(self.install, "v9.0.0")
        self.blockers.append(Process(4242, "RYOS.exe"))
        self.assertTrue(self.start().applying)

    def test_another_installs_request_is_ignored(self):
        other = self.tmp / "other" / "RYOS"
        write_tree(other, OLD)
        selfupdate.request_at_start(other, "v9.0.0")
        path = swap.journal_dir_for(self.install) / selfupdate.AT_START_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"install": str(other), "tag": "v9.0.0"}),
                        encoding="utf-8")
        self.assertEqual(self.start(), selfupdate.AtStart(False, ()))
        self.assertEqual(self.spawned, [])
        self.assertEqual(selfupdate.pending_at_start(other), "v9.0.0")

    def test_a_request_not_newer_or_no_longer_downloaded_is_dropped(self):
        for tag, current in (("v9.0.0", "9.0.0"), ("v8.0.0", "1.0.0")):
            with self.subTest(tag=tag):
                selfupdate.request_at_start(self.install, tag)
                self.assertFalse(self.start(current=current).applying)
                self.assertIsNone(selfupdate.pending_at_start(self.install))
        self.assertEqual(self.spawned, [])

    def test_the_last_result_is_noted_once(self):
        self.updated()
        notes = self.start(current="9.0.0").notes
        self.assertEqual(len(notes), 1)
        level, _title, text = notes[0]
        self.assertEqual(level, "info")
        self.assertIn("is now v9.0.0", text)
        self.assertEqual(self.start(current="9.0.0").notes, ())

    def test_a_helper_still_at_work_is_waited_for(self):
        jdir = swap.journal_dir_for(self.install)
        jdir.mkdir(parents=True)
        release = swap._hold_lock(jdir / swap.LOCK_NAME)
        self.assertIsNotNone(release)
        try:
            started = self.start(wait_seconds=1)
        finally:
            release()
        self.assertEqual(self.slept, [selfupdate.LOCK_POLL] * 4)
        self.assertEqual(started, selfupdate.AtStart(False, (selfupdate.IN_PROGRESS_NOTE,)))

    def test_a_stuck_settle_warns(self):
        renames: list = []

        def rename(src, dst):
            renames.append(src)
            if len(renames) == 3:
                swap._rename(src, dst)
                (self.install / "lib" / "a.pyc").unlink()
                raise _Crash()
            swap._rename(src, dst)
        with self.assertRaises(_Crash):
            swap.apply_update(self.install, self.zip, version="v9.0.0", which="windows",
                              effects=self.effects(rename=rename))
        started = self.start(current="1.0.0")
        self.assertFalse(started.applying)
        (level, _title, text), = started.notes
        self.assertEqual(level, "warning")
        self.assertIn("--recover", text)


if __name__ == "__main__":
    unittest.main()
