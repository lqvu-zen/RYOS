"""Subprocess execution worker for jobs.

Runs a command and streams its output through a queue. UI-independent — the
only channel back to the app is the queue — so it runs on a worker thread and
can be unit-tested with a real subprocess and a plain ``queue.Queue``.

Queue protocol (each item is a tuple keyed by its first element):
    ("stdout", job_id, line)
    ("stderr", job_id, line)                              launch failure detail
    ("done",     job_id, script_id, "error", message)     launch failed, no process
    ("done_tag", job_id, script_id, status, tag, footer)  process finished (status ok/error)
"""
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime

from .interpreter import working_dir_for
from .logger import get_logger

_log = get_logger("runner")


def run_subprocess(output_queue, job, cmd, name, script_id, log_output=False):
    """Launch cmd, stream stdout to output_queue, and post a completion item.

    Sets job.current_process so the UI can terminate it. Never raises: launch
    failures are reported on the queue as a "done"/"error" item.
    """
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            text=True,
            cwd=working_dir_for(cmd),
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        job.current_process = proc
    except FileNotFoundError as e:
        _log.error("Interpreter/file not found for %s: %s", name, e)
        output_queue.put(("stderr", job.job_id, f"[ERROR] {e}\n"))
        output_queue.put(("done", job.job_id, script_id, "error", f"❌ Interpreter/file not found: {name}\n"))
        return
    except Exception as e:
        _log.error("Failed to launch %s: %s", name, e)
        output_queue.put(("stderr", job.job_id, f"[ERROR] {e}\n"))
        output_queue.put(("done", job.job_id, script_id, "error", f"❌ Error: {name}\n"))
        return

    assert proc.stdout is not None
    for line in proc.stdout:
        output_queue.put(("stdout", job.job_id, line))
        if log_output:
            _log.debug("[%s] %s", name, line.rstrip())

    proc.wait()
    rc = proc.returncode
    tag = "ok" if rc == 0 else "stderr"
    status = "ok" if rc == 0 else "error"
    if rc == 0:
        _log.info("Done: %s | exit=%s", name, rc)
    else:
        _log.error("Done: %s | exit=%s", name, rc)
    output_queue.put((
        "done_tag", job.job_id, script_id, status, tag,
        f"\n  exit code {rc}  ·  {datetime.now().strftime('%H:%M:%S')}\n",
    ))



@dataclass
class OutputAction:
    """What the UI should do with one drained queue item.

    Decodes the queue protocol into a flat decision so the drain loop in the UI
    is a straight translation to widget calls — and so the index handling is
    unit-testable without Tkinter.
    """
    text: str | None        # text to append (None = append nothing)
    tag: str | None          # output tag: "info" / "stderr" / "ok" / None (stdout default)
    status: str | None       # last_run_status to record (None = not a completion)
    sid: int | None          # script id for a completion (None otherwise)
    step_done: bool          # whether this item completes a run step


def decode_output_item(item: tuple) -> OutputAction:
    """Translate one output-queue item into an OutputAction (see run_subprocess)."""
    kind = item[0]
    if kind == "done":
        return OutputAction(text=item[4], tag="info", status=item[3], sid=item[2], step_done=True)
    if kind == "done_tag":
        return OutputAction(text=item[5], tag=item[4], status=item[3], sid=item[2], step_done=True)
    if kind == "stderr":
        return OutputAction(text=item[2], tag="stderr", status=None, sid=None, step_done=False)
    return OutputAction(text=item[2], tag=None, status=None, sid=None, step_done=False)
