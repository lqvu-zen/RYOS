"""Write ryos-samples.json: the sample scripts, ready for Options -> Import config.

    uv run python samples/make_import.py

The file holds absolute paths, so it is generated for wherever this folder
is rather than kept in git. It is built through a throwaway database and the
app's own export, so it is exactly what import expects; your RYOS data is
not touched.
"""

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Before ryos is imported: it picks its data folder from APPDATA.
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ryos-samples-")
sys.path.insert(0, str(HERE.parent))

from ryos.db import (FAIL_CONTINUE, TRIGGER_WITH, WHEN_ON_FAILURE,  # noqa: E402
                     ScriptDB)

GROUP = "Samples"


def main() -> int:
    db = ScriptDB(Path(os.environ["APPDATA"]) / "samples.db")
    db.create_group(GROUP, base_dir=str(HERE))

    def add(name, rel, params="", **kw):
        return db.add(name, str(HERE / rel), params, "", GROUP, **kw)

    hello = add("Say hello", "hello.py", "--name RYOS",
                env_vars='{"RYOS_SAMPLE": "set by RYOS"}')
    db.replace_param_presets(hello, [(p, p) for p in
                                     ("--name RYOS", "--loud", "--loud --name Team")])
    db.set_favorite_script(hello, True)
    fail = add("Always fails", "fail.py")
    db.set_script_color(fail, "red")
    flaky = add("Flaky", "flaky.py")
    slow = add("Count a minute", "slow_counter.py")
    noisy = add("Lots of output", "noisy.py")
    add("Ask each run", "ask_name.py", temp_param=1)
    report = add("Write a report", "write_report.py")
    cleanup = add("Cleanup", "cleanup.py")
    add("List folder", "tools/list_folder.bat")
    add("System info", "tools/system_info.ps1")

    morning = db.create_pipeline("Morning report", GROUP)
    for sid in (hello, report):
        db.add_pipeline_step(morning, sid)

    resilient = db.create_pipeline("Resilient", GROUP)
    for sid in (flaky, fail, cleanup, hello):
        db.add_pipeline_step(resilient, sid)
    steps = db.list_pipeline_steps(resilient)
    db.set_step_policy(steps[0][0], on_failure=FAIL_CONTINUE, retries=3)
    db.set_step_policy(steps[1][0], on_failure=FAIL_CONTINUE)
    db.set_step_policy(steps[2][0], run_when=WHEN_ON_FAILURE)

    side = db.create_pipeline("Side by side", GROUP)
    for sid in (slow, noisy):
        db.add_pipeline_step(side, sid)
    db.set_step_trigger_mode(db.list_pipeline_steps(side)[1][0], TRIGGER_WITH)

    out = HERE / "ryos-samples.json"
    n_scripts, n_pipes = db.export_to_file(str(out), GROUP)
    print(f"Wrote {out}: {n_scripts} scripts, {n_pipes} pipelines.")
    print("In RYOS: Options -> Import config -> this file -> No (merge).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
