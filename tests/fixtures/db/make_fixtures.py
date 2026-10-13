#!/usr/bin/env python3
"""Make the fixture databases: one per past release, written by that
release's own code, so an upgrade test opens exactly what a user has.

    uv run python tests/fixtures/db/make_fixtures.py               # the default tags
    uv run python tests/fixtures/db/make_fixtures.py v2.4.0        # one new release
    ... --force                                                    # overwrite

Each tag's `ryos/` is taken with `git archive` into a folder outside the
repository and run in its own Python, with APPDATA pointing there too:
importing `ryos.settings` creates the data folder, and it must never be the
real one. The content uses only what every one of these releases can write
(newer features behind `hasattr`), and every path is under C:\\RYOS-fixture,
so no fixture holds anything from this machine.

Run by hand when a release adds a schema version; never in CI (it needs the
git tags). The tests only ever read copies of the files it writes.
"""

import argparse
import io
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_TAGS = ["v1.11.2", "v2.0.0", "v2.1.2", "v2.2.0", "v2.3.0"]

# Run inside the old release's Python: argv[1] is the database to write,
# argv[2] the version the archived ryos/ must say it is.
BUILDER = r'''
import json
import sys

import ryos
from ryos.db import ScriptDB

path, want = sys.argv[1], sys.argv[2]
if ryos.__version__ != want:
    raise SystemExit(f"imported ryos {ryos.__version__} from {ryos.__file__}, not {want}")
BASE = "C:\\RYOS-fixture"
SCRIPTS = BASE + "\\scripts"
db = ScriptDB(path)

db.create_group("Fixture", SCRIPTS)
db.create_group("Second")
hello = db.add("hello", SCRIPTS + "\\hello.py", "--name fixture", "", "Fixture",
               env_vars=json.dumps({"FIXTURE": "1"}), work_dir=BASE + "\\work")
fail = db.add("fail", SCRIPTS + "\\fail.py", "", "", "Fixture")
slow = db.add("slow", BASE + "\\other\\slow.py", "--seconds 5", "", "Second")
notes = db.add("notes", BASE + "\\loose\\notes.ps1", "",
               "powershell -NoProfile -ExecutionPolicy Bypass -File", "")
db.set_favorite_script(hello, True)
db.set_script_color(hello, "teal")
db.replace_param_presets(hello, [("quick", "--name quick"), ("loud", "--name loud --shout")])

both = db.create_pipeline("Both", "Fixture")
first = db.add_pipeline_step(both, hello)
second = db.add_pipeline_step(both, fail)
db.set_step_trigger_mode(second, "with")
db.set_step_policy(first, retries=2)
db.set_step_policy(second, on_failure="continue", run_when="on_success")
db.update_pipeline_step_params(second, "--loud")
db.set_favorite_pipeline(both, True)
db.set_pipeline_color(both, "red")

db.add_schedule("script", script_id=slow, spec_type="interval",
                spec=json.dumps({"minutes": 60}), enabled=False)
# Enabled, but not due for a very long time: opening the fixture must not
# fire it and add history.
db.add_schedule("pipeline", pipeline_id=both, spec_type="daily",
                spec=json.dumps({"at": "03:00"}), enabled=True,
                next_run_at="2099-01-01T03:00:00")

runs = [("script", hello, None, "hello", "ok", 0, None, "manual"),
        ("script", fail, None, "fail", "failed", 3, None, "manual"),
        ("pipeline", None, both, "Both", "failed", 3, None, "schedule"),
        ("step", hello, both, "hello", "ok", 0, 0, "pipeline"),
        ("script", notes, None, "notes", "ok", 0, None, "startup")]
for i, (kind, sid, pid, name, status, code, step, source) in enumerate(runs):
    db.record_run(kind, name=name, script_id=sid, pipeline_id=pid,
                  started_at=f"2026-01-0{i + 1}T09:00:00",
                  finished_at=f"2026-01-0{i + 1}T09:00:02",
                  status=status, exit_code=code, step_index=step, trigger_source=source)

if hasattr(db, "set_agent_exposed"):
    db.set_agent_exposed("script", hello, True)
    db.set_agent_exposed("pipeline", both, True)
'''


def _name(tag: str) -> str:
    """The full tag: two releases of one minor version can differ in schema."""
    return f"{tag}.db"


def _archive(tag: str, into: Path) -> None:
    blob = subprocess.run(["git", "archive", "--format=tar", tag, "ryos"], cwd=ROOT,
                          capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
        tar.extractall(into, filter="data")


def make(tag: str, out: Path) -> None:
    work = Path(tempfile.mkdtemp(prefix=f"ryos-fixture-{tag}-"))
    try:
        src = work / "src"
        src.mkdir()
        _archive(tag, src)
        built = work / "fixture.db"
        env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
        env.update(PYTHONPATH=str(src), APPDATA=str(work / "appdata"),
                   RYOS_NO_REGISTRY="1", RYOS_NO_TOASTS="1")
        subprocess.run([sys.executable, "-c", BUILDER, str(built), tag.lstrip("v")],
                       cwd=str(work), env=env, check=True)
        with sqlite3.connect(built) as conn:
            conn.execute("VACUUM")
        conn.close()
        shutil.copyfile(built, out)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(tags: list, force: bool) -> int:
    for tag in tags:
        out = HERE / _name(tag)
        if out.exists() and not force:
            print(f"{out.name} exists; --force to overwrite it")
            return 1
        make(tag, out)
        with sqlite3.connect(f"file:{out}?mode=ro", uri=True) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        print(f"{tag}: wrote {out.name} (schema {version})")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tags", nargs="*", default=DEFAULT_TAGS)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    raise SystemExit(main(args.tags, args.force))
