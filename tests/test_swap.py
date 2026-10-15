"""Applying and rolling back an update (``ryos/swap.py``), on real temporary
folders, with waiting, starting RYOS and sleeping faked, and failures and
crashes injected at each step."""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ryos import settings, swap  # noqa: E402

OLD = {"RYOS.exe": b"old window", "ryos-cli.exe": b"old cli",
       "lib/python.dll": b"old dll " * 3, "lib/ryos/a.pyc": b"old a",
       "lib/old_only.pyc": b"gone in the new one"}
NEW = {"RYOS.exe": b"new window!!", "ryos-cli.exe": b"new cli, longer",
       "lib/python.dll": b"new dll", "lib/ryos/a.pyc": b"new a",
       "lib/new_only.pyc": b"only in the new one"}
AGENT_OLD = {"ryos-cli.exe": b"old agent", "lib/x.pyc": b"old x"}
AGENT_NEW = {"ryos-cli.exe": b"new agent!", "lib/x.pyc": b"new x"}


class _Crash(BaseException):
    pass


def write_tree(folder: Path, files: dict) -> None:
    for name, body in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)


def read_tree(folder: Path) -> dict:
    return {rel: (folder / rel).read_bytes() for rel in swap.tree_listing(folder)}


def write_zip(path: Path, files: dict) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name, body in files.items():
            z.writestr(name, body)
    return path


def counting(effects: swap.Effects, limit: int | None):
    calls = [0]

    def wrap(fn):
        def inner(*a, **k):
            calls[0] += 1
            if limit is not None and calls[0] >= limit:
                raise _Crash()
            return fn(*a, **k)
        return inner
    wrapped = {f.name: wrap(getattr(effects, f.name)) for f in dataclasses.fields(effects)}
    return swap.Effects(**wrapped), calls


class _Case(unittest.TestCase):
    old, new, which = OLD, NEW, "windows"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.place(self.tmp)

    def place(self, base: Path):
        self.base = base
        env = mock.patch.dict(os.environ, {"LOCALAPPDATA": str(base / "local")})
        env.start()
        self.addCleanup(env.stop)
        self.install = base / "apps" / "RYOS"
        write_tree(self.install, self.old)
        self.zip = write_zip(base / "RYOS-windows.zip", self.new)
        self.folders = swap.folders_for(self.install)
        self.spawned: list = []
        self.slept: list = []
        self.waited: list = []

    @property
    def jdir(self) -> Path:
        return settings.updates_root()

    def effects(self, **over) -> swap.Effects:
        def wait(pid, timeout):
            self.waited.append((pid, timeout))
            return True

        def spawn(argv, cwd):
            self.spawned.append((list(argv), Path(cwd)))
        base = dict(wait_for_exit=wait, spawn=spawn, sleep=self.slept.append)
        base.update(over)
        return swap.Effects(**base)

    def update(self, effects=None, **kw):
        kw.setdefault("restart", True)
        kw.setdefault("which", self.which)
        return swap.apply_update(self.install, self.zip, version="v9.0.0",
                                 from_version="1.0.0", effects=effects or self.effects(),
                                 **kw)

    def roll_back(self, effects=None, **kw):
        kw.setdefault("restart", True)
        return swap.roll_back(self.install, from_version="9.0.0",
                              effects=effects or self.effects(), **kw)

    def whole(self, folder: Path | None = None) -> str:
        found = read_tree(folder or self.install)
        if found == self.old:
            return "old"
        if found == self.new:
            return "new"
        self.fail(f"{folder or self.install} is half of each: {sorted(found)}")

    def beside(self) -> list[str]:
        return sorted(p.name for p in self.install.parent.iterdir())

    def journal(self) -> dict:
        return json.loads((self.jdir / swap.JOURNAL_NAME).read_text(encoding="utf-8"))

    def undone(self, result):
        self.assertEqual(result.code, swap.UNDONE, result.message)
        self.assertIn("antivirus", result.message)
        self.assertEqual(self.whole(), "old")
        self.assertEqual(self.beside(), ["RYOS"])
        self.assertEqual(self.journal()["state"], swap.UNDONE)
        self.assertIsNone(swap.rollback_available(self.install))


class TestApply(_Case):
    def test_update_swaps_in_place_with_the_exe_path_unchanged(self):
        exe = self.install / "RYOS.exe"
        result = self.update()
        self.assertEqual(result.code, swap.DONE, result.message)
        self.assertTrue(result.restarted)
        self.assertEqual(self.whole(), "new")
        self.assertEqual(self.whole(self.folders.previous), "old")
        self.assertEqual(self.spawned, [([str(exe)], self.install)])
        self.assertEqual(self.beside(), ["RYOS", "RYOS.previous"])
        self.assertEqual(self.journal()["state"], swap.DONE)
        self.assertEqual(swap.rollback_available(self.install), "1.0.0")

    def test_waits_for_each_pid_before_touching_anything(self):
        seen = []

        def wait(pid, timeout):
            seen.append((pid, timeout, self.beside(),
                         (self.jdir / swap.JOURNAL_NAME).exists()))
            return True
        result = self.update(self.effects(wait_for_exit=wait), wait_pids=[11, 22])
        self.assertEqual(result.code, swap.DONE, result.message)
        self.assertEqual(seen, [(11, swap.WAIT_SECONDS, ["RYOS"], False),
                                (22, swap.WAIT_SECONDS, ["RYOS"], False)])

    def test_refuses_when_ryos_does_not_exit(self):
        result = self.update(self.effects(wait_for_exit=lambda pid, t: pid != 22),
                             wait_pids=[11, 22])
        self.assertEqual(result.code, swap.REFUSED)
        self.assertIn("process 22", result.message)
        self.assertEqual(self.whole(), "old")
        self.assertEqual(self.beside(), ["RYOS"])
        self.assertFalse((self.jdir / swap.JOURNAL_NAME).exists())
        self.assertEqual(self.spawned, [])

    def test_old_previous_is_replaced(self):
        write_tree(self.folders.previous, {"RYOS.exe": b"ancient", "junk.txt": b"x"})
        self.jdir.mkdir(parents=True, exist_ok=True)
        (self.jdir / swap.PREVIOUS_NAME).write_text(json.dumps(
            {"format": 1, "install": str(self.install), "version": "0.1",
             "files": {"RYOS.exe": 7, "junk.txt": 1}}), encoding="utf-8")
        result = self.update()
        self.assertEqual(result.code, swap.DONE, result.message)
        self.assertEqual(self.whole(self.folders.previous), "old")
        self.assertEqual(swap.rollback_available(self.install), "1.0.0")


class TestAgentVariant(_Case):
    old, new, which = AGENT_OLD, AGENT_NEW, "agent"

    def test_agent_variant_restarts_nothing(self):
        result = self.update(restart=True)
        self.assertEqual(result.code, swap.DONE, result.message)
        self.assertFalse(result.restarted)
        self.assertEqual(self.spawned, [])
        self.assertEqual(self.whole(), "new")


class TestRollBack(_Case):
    def updated(self):
        result = self.update()
        self.assertEqual(result.code, swap.DONE, result.message)
        self.spawned.clear()

    def test_swaps_back_with_the_exe_path_unchanged(self):
        self.updated()
        result = self.roll_back()
        self.assertEqual(result.code, swap.DONE, result.message)
        self.assertEqual(self.whole(), "old")
        self.assertEqual(self.whole(self.folders.previous), "new")
        self.assertEqual(self.spawned, [([str(self.install / "RYOS.exe")], self.install)])
        self.assertEqual(self.beside(), ["RYOS", "RYOS.previous"])
        self.assertEqual(swap.rollback_available(self.install), "9.0.0")

    def test_rolling_back_twice_returns_to_the_new_one(self):
        self.updated()
        self.assertEqual(self.roll_back().code, swap.DONE)
        result = self.roll_back()
        self.assertEqual(result.code, swap.DONE, result.message)
        self.assertEqual(self.whole(), "new")
        self.assertEqual(self.whole(self.folders.previous), "old")

    def test_refuses_when_previous_does_not_match_its_manifest(self):
        self.updated()
        (self.folders.previous / "lib" / "python.dll").write_bytes(b"changed")
        result = self.roll_back()
        self.assertEqual(result.code, swap.REFUSED)
        self.assertIn("no longer the build", result.message)
        self.assertEqual(self.whole(), "new")
        self.assertEqual(self.spawned, [])
        self.assertIsNone(swap.rollback_available(self.install))

    def test_refuses_without_previous(self):
        result = self.roll_back()
        self.assertEqual(result.code, swap.REFUSED)
        self.assertIn("no earlier build", result.message)
        self.assertEqual(self.whole(), "old")
        self.assertEqual(self.beside(), ["RYOS"])

    def test_rollback_available(self):
        self.assertIsNone(swap.rollback_available(self.install))
        self.updated()
        self.assertEqual(swap.rollback_available(self.install), "1.0.0")
        (self.folders.previous / "extra").write_bytes(b"x")
        self.assertIsNone(swap.rollback_available(self.install))


class TestFailures(_Case):
    def test_extract_fails(self):
        def extract(zip_path, dest, manifest):
            Path(dest).mkdir()
            (Path(dest) / "RYOS.exe").write_bytes(b"half")
            raise OSError(5, "Access is denied", str(dest))
        self.undone(self.update(self.effects(extract=extract)))

    def test_missing_extracted_file(self):
        def extract(zip_path, dest, manifest):
            swap.extract_zip(zip_path, dest, manifest)
            (Path(dest) / "lib" / "python.dll").unlink()
        result = self.update(self.effects(extract=extract))
        self.undone(result)
        self.assertIn("lib/python.dll is missing", result.message)

    def test_wrong_size_extracted_file(self):
        def extract(zip_path, dest, manifest):
            swap.extract_zip(zip_path, dest, manifest)
            with open(Path(dest) / "RYOS.exe", "ab") as fh:
                fh.write(b"!")
        result = self.update(self.effects(extract=extract))
        self.undone(result)
        self.assertIn("RYOS.exe is 13 bytes, not 12", result.message)

    def failing_rename(self, src_of, dst_of):
        def rename(src, dst):
            if Path(src) == src_of and Path(dst) == dst_of:
                raise PermissionError(5, "Access is denied", str(src))
            swap._rename(src, dst)
        return rename

    def test_first_rename_keeps_failing(self):
        rename = self.failing_rename(self.install, self.folders.previous)
        result = self.update(self.effects(rename=rename))
        self.undone(result)
        self.assertEqual(self.slept, list(swap.RENAME_DELAYS))
        self.assertTrue(result.restarted)
        self.assertEqual(self.spawned, [([str(self.install / "RYOS.exe")], self.install)])

    def test_second_rename_keeps_failing(self):
        rename = self.failing_rename(self.folders.incoming, self.install)
        self.undone(self.update(self.effects(rename=rename)))

    def test_restart_fails_restores_and_restarts_old(self):
        def spawn(argv, cwd):
            if not self.spawned:
                self.spawned.append("failed")
                raise OSError(2, "No such file", argv[0])
            self.spawned.append((list(argv), Path(cwd)))
        result = self.update(self.effects(spawn=spawn))
        self.undone(result)
        self.assertTrue(result.restarted)
        self.assertEqual(self.spawned, ["failed",
                                        ([str(self.install / "RYOS.exe")], self.install)])

    def test_file_quarantined_after_swap(self):
        def rename(src, dst):
            swap._rename(src, dst)
            if Path(src) == self.folders.incoming and Path(dst) == self.install:
                (self.install / "lib" / "python.dll").unlink()
        result = self.update(self.effects(rename=rename))
        self.undone(result)
        self.assertIn("lib/python.dll is missing", result.message)

    def test_rename_retries_then_succeeds(self):
        fails = [2]

        def rename(src, dst):
            if Path(src) == self.install and fails[0]:
                fails[0] -= 1
                raise PermissionError(5, "Access is denied", str(src))
            swap._rename(src, dst)
        result = self.update(self.effects(rename=rename))
        self.assertEqual(result.code, swap.DONE, result.message)
        self.assertEqual(self.slept, [0.25, 0.5])
        self.assertEqual(self.whole(), "new")

    @unittest.skipUnless(sys.platform == "win32", "Windows refuses to rename a folder "
                                                  "with an open file only on Windows")
    def test_a_locked_file_in_the_install(self):
        with open(self.install / "lib" / "python.dll", "rb"):
            result = self.update()
        self.undone(result)
        self.assertEqual(self.slept, list(swap.RENAME_DELAYS))

    @unittest.skipUnless(sys.platform == "win32", "Windows refuses to rename a folder "
                                                  "with an open file only on Windows")
    def test_a_locked_file_in_the_new_tree(self):
        held = []

        def extract(zip_path, dest, manifest):
            swap.extract_zip(zip_path, dest, manifest)
            held.append(open(Path(dest) / "lib" / "python.dll", "rb"))

        def remove_tree(path):
            for fh in held:
                fh.close()
            swap._remove_tree(path)
        self.addCleanup(lambda: [fh.close() for fh in held])
        result = self.update(self.effects(extract=extract, remove_tree=remove_tree))
        self.undone(result)
        self.assertEqual(self.slept, list(swap.RENAME_DELAYS))

    def test_parent_not_writable(self):
        parent = self.install.parent
        if os.name == "posix" and os.geteuid() != 0:
            os.chmod(parent, 0o555)
            self.addCleanup(os.chmod, parent, 0o755)
            result = self.update()
        else:
            def denied(*paths):
                raise PermissionError(13, "Permission denied", str(paths[-1]))

            def extract(zip_path, dest, manifest):
                denied(dest)
            result = self.update(self.effects(extract=extract, rename=denied))
        os.chmod(parent, 0o755)
        self.undone(result)


class TestUnsafeZip(_Case):
    def refused(self, entries, which="windows"):
        with zipfile.ZipFile(self.zip, "w") as z:
            for entry in entries:
                if isinstance(entry, zipfile.ZipInfo):
                    z.writestr(entry, b"target")
                else:
                    z.writestr(entry, b"x")
        with self.assertRaises(swap.UnsafeZip):
            swap.zip_manifest(self.zip, which)
        result = self.update(which=which)
        self.assertEqual(result.code, swap.REFUSED, result.message)
        self.assertEqual(self.whole(), "old")
        self.assertEqual(self.beside(), ["RYOS"])
        self.assertFalse((self.jdir / swap.JOURNAL_NAME).exists())
        self.assertEqual(self.spawned, [])
        return result

    def test_dot_dot(self):
        self.refused([*NEW, "lib/../../evil.exe"])

    def test_absolute(self):
        self.refused([*NEW, "/evil.exe"])

    def test_drive_letter(self):
        self.refused([*NEW, "C:/evil.exe"])

    def test_symlink(self):
        link = zipfile.ZipInfo("lib/link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.refused([*NEW, link])

    def test_case_duplicates(self):
        self.refused([*NEW, "lib/Python.DLL"])

    def test_missing_variant_exe(self):
        result = self.refused(["ryos-cli.exe", "lib/x"])
        self.assertIn("RYOS.exe", result.message)

    def test_the_agent_zip_needs_only_the_cli(self):
        write_zip(self.zip, AGENT_NEW)
        self.assertEqual(swap.zip_manifest(self.zip, "agent"),
                         {k: len(v) for k, v in AGENT_NEW.items()})
        with self.assertRaises(swap.UnsafeZip):
            swap.zip_manifest(self.zip, "portable")


class TestJournal(_Case):
    def setUp(self):
        super().setUp()
        self.n = 0

    def fresh(self):
        self.n += 1
        self.place(self.tmp / f"n{self.n}")

    def updated(self):
        self.assertEqual(self.update().code, swap.DONE)

    def total(self, action) -> int:
        self.fresh()
        effects, calls = counting(self.effects(), None)
        self.assertEqual(action(effects).code, swap.DONE)
        return calls[0]

    def crash(self, action, at: int) -> None:
        effects, _calls = counting(self.effects(), at)
        with self.assertRaises(_Crash):
            action(effects)

    def check_settled(self, result, rollback: bool):
        if result is not None:
            self.assertIn(result.code, (swap.DONE, swap.UNDONE), result.message)
        in_place = self.whole()
        if os.path.lexists(self.folders.previous):
            other = self.whole(self.folders.previous)
            self.assertNotEqual(in_place, other)
            self.assertIsNotNone(swap.rollback_available(self.install))
        else:
            self.assertFalse(rollback)
            self.assertEqual(in_place, "old")
        for name in ("RYOS.incoming", "RYOS.incoming.part", "RYOS.outgoing"):
            self.assertFalse((self.install.parent / name).exists(), name)
        if (self.jdir / swap.JOURNAL_NAME).exists():
            self.assertIn(self.journal()["state"], (swap.DONE, swap.UNDONE))
        self.assertIsNone(swap.recover(effects=self.effects()))

    def test_crash_at_every_effect_call_is_finished_or_undone(self):
        total = self.total(lambda e: self.update(e, wait_pids=[7]))
        self.assertGreater(total, 15)
        for at in range(1, total + 1):
            with self.subTest(kind="update", at=at):
                self.fresh()
                self.crash(lambda e: self.update(e, wait_pids=[7]), at)
                self.check_settled(swap.recover(effects=self.effects()), rollback=False)

    def test_crash_at_every_effect_call_of_a_rollback_is_finished_or_undone(self):
        def total_rollback():
            self.fresh()
            self.updated()
            effects, calls = counting(self.effects(), None)
            self.assertEqual(self.roll_back(effects).code, swap.DONE)
            return calls[0]
        total = total_rollback()
        self.assertGreater(total, 10)
        for at in range(1, total + 1):
            with self.subTest(kind="rollback", at=at):
                self.fresh()
                self.updated()
                self.crash(lambda e: self.roll_back(e), at)
                self.check_settled(swap.recover(effects=self.effects()), rollback=True)

    def test_settle_at_start_never_moves_the_install(self):
        total = self.total(lambda e: self.update(e))
        for at in range(1, total + 1):
            with self.subTest(at=at):
                self.fresh()
                self.crash(lambda e: self.update(e), at)
                moved = []

                def rename(src, dst):
                    if self.install in (Path(src), Path(dst)):
                        moved.append((src, dst))
                    swap._rename(src, dst)
                result = swap.settle_at_start(self.install,
                                              effects=self.effects(rename=rename))
                self.assertEqual(moved, [])
                if os.path.lexists(self.install):
                    self.check_settled(result, rollback=False)
                else:
                    self.assertEqual(result.code, swap.STUCK)

    def test_settle_at_start_keeps_a_new_build_found_in_place_while_undoing(self):
        self.updated()
        journal = self.journal()
        journal["state"] = "unswap"
        (self.jdir / swap.JOURNAL_NAME).write_text(json.dumps(journal), encoding="utf-8")
        result = swap.settle_at_start(self.install, effects=self.effects())
        self.assertEqual(result.code, swap.DONE, result.message)
        self.assertIn("kept", result.message)
        self.assertEqual(self.whole(), "new")
        self.assertEqual(self.whole(self.folders.previous), "old")

    def crashed_mid_swap(self):
        renames = []

        def rename(src, dst):
            renames.append(src)
            if len(renames) == 3:
                raise _Crash()
            swap._rename(src, dst)
        with self.assertRaises(_Crash):
            self.update(self.effects(rename=rename))
        self.assertFalse(self.install.exists())

    def test_a_swap_in_progress_is_left_alone(self):
        self.crashed_mid_swap()
        before = sorted(os.listdir(self.install.parent))
        release = swap._hold_lock(self.jdir / swap.LOCK_NAME)
        self.assertIsNotNone(release)
        try:
            self.assertIsNone(swap.recover(effects=self.effects()))
            refused = self.update()
            self.assertEqual(refused.code, swap.REFUSED)
            self.assertEqual(refused.message, swap.IN_PROGRESS)
            self.assertEqual(sorted(os.listdir(self.install.parent)), before)
        finally:
            release()
        result = swap.recover(effects=self.effects())
        self.assertEqual(result.code, swap.UNDONE, result.message)
        self.assertEqual(self.whole(), "old")
        self.assertEqual(self.beside(), ["RYOS"])

    def test_unknown_journal_format_is_left_alone(self):
        self.crashed_mid_swap()
        path = self.jdir / swap.JOURNAL_NAME
        for text in (json.dumps({**self.journal(), "format": 99}), "not json {"):
            path.write_text(text, encoding="utf-8")
            self.assertIsNone(swap.recover(effects=self.effects()))
            self.assertIsNone(swap.settle_at_start(self.install, effects=self.effects()))
            self.assertEqual(path.read_text(encoding="utf-8"), text)
            self.assertFalse(self.install.exists())

    def test_inconsistent_folders_are_stuck_with_words(self):
        self.crashed_mid_swap()
        shutil.rmtree(self.folders.previous)
        result = swap.recover(effects=self.effects())
        self.assertEqual(result.code, swap.STUCK)
        for words in (str(self.install), str(self.folders.incoming),
                      str(self.folders.previous), "antivirus", "--recover"):
            self.assertIn(words, result.message)
        self.assertTrue(self.folders.incoming.exists())
        self.assertEqual(self.journal()["state"], "unswap")

    def test_an_unfinished_swap_is_undone_before_the_next_update(self):
        self.crashed_mid_swap()
        result = self.update()
        self.assertEqual(result.code, swap.DONE, result.message)
        self.assertEqual(self.whole(), "new")
        self.assertEqual(self.whole(self.folders.previous), "old")


class TestStaging(_Case):
    def test_stage_helper(self):
        exe = swap.stage_helper(self.zip, "v9.0.0", self.effects(), which="windows")
        self.assertEqual(exe, settings.updates_dir("v9.0.0") / "helper" / "ryos-cli.exe")
        self.assertEqual(read_tree(exe.parent), NEW)
        again = swap.stage_helper(self.zip, "v9.0.0", self.effects(), which="windows")
        self.assertEqual(again, exe)

    def test_stage_helper_refuses_an_unsafe_zip(self):
        write_zip(self.zip, {**NEW, "../evil": b"x"})
        with self.assertRaises(swap.UnsafeZip):
            swap.stage_helper(self.zip, "v9.0.0", self.effects(), which="windows")
        self.assertFalse((settings.updates_dir("v9.0.0") / "helper").exists())

    def test_stage_rollback_helper(self):
        exe = swap.stage_rollback_helper(self.install, self.effects())
        self.assertEqual(exe, settings.updates_root() / "rollback-helper" / "ryos-cli.exe")
        self.assertEqual(read_tree(exe.parent), OLD)
        self.assertEqual(swap.stage_rollback_helper(self.install, self.effects()), exe)

    def test_helper_argv_matches_the_contract(self):
        exe = Path("C:/u/helper/ryos-cli.exe")
        self.assertEqual(
            swap.helper_argv(exe, "C:/Apps/RYOS", version="v9.0.0", from_version="1.0.0",
                             wait_pids=[12, 34], restart=True),
            [str(exe), "apply-update", "--install", "C:/Apps/RYOS", "--version", "v9.0.0",
             "--from-version", "1.0.0", "--wait-pid", "12", "--wait-pid", "34",
             "--restart"])
        self.assertEqual(swap.helper_argv(exe, "C:/Apps/RYOS", rollback=True),
                         [str(exe), "apply-update", "--install", "C:/Apps/RYOS",
                          "--rollback"])
        for bad in ({}, {"version": "v1", "rollback": True}):
            with self.assertRaises(ValueError):
                swap.helper_argv(exe, "C:/Apps/RYOS", **bad)
        from ryos import cli
        args = cli._apply_update_parser().parse_args(
            swap.helper_argv(exe, "C:/Apps/RYOS", version="v9.0.0", wait_pids=[5],
                             restart=True)[2:])
        self.assertEqual((args.install, args.tag, args.wait_pid, args.restart),
                         ("C:/Apps/RYOS", "v9.0.0", [5], True))

    def test_a_drive_root_is_refused(self):
        root = Path(os.path.abspath(os.sep))
        with self.assertRaises(ValueError):
            swap.folders_for(root)


if __name__ == "__main__":
    unittest.main()
