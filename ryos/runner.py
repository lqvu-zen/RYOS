"""Subprocess execution worker for jobs.

Runs a command and streams its output through a queue. UI-independent — the
only channel back to the app is the queue — so it runs on a worker thread and
can be unit-tested with a real subprocess and a plain ``queue.Queue``.

Queue protocol (each item is a tuple keyed by its first element):
    ("stdout", job_id, line)
    ("stderr", job_id, line)                              launch failure detail
    ("done",     job_id, script_id, "error", message)     launch failed, no process
    ("done_tag", job_id, script_id, status, tag, footer)  process finished (status ok/error)
Every shape above may carry one extra trailing element, a step_token, appended
only when the producer supplies one (concurrent pipeline steps); untagged
callers keep the shorter tuple unchanged.
"""
import codecs
import io
import locale
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime

from .interpreter import RunSpec, working_dir_for
from .logger import get_logger

_log = get_logger("runner")

#: How long a step's output is still read after its process exits. What the
#: script itself wrote is at most a pipe buffer by then, so this loses none of
#: its lines; a normal run reaches end-of-file at once and never waits. Only a
#: process the script left running (``start /b``, a build server) still holds
#: the pipe -- and the step is not kept waiting for it (issue #26).
DRAIN_SECONDS = 1.0


def child_env(env: dict | None, base=None) -> dict | None:
    """The environment a run starts with: ``env`` (None = RYOS's own), plus
    PYTHONUNBUFFERED=1 unless either already sets it.

    stdout and stderr share one pipe, and Python block-buffers stdout into a
    pipe but not stderr -- so a failing script's error lines arrived before
    the output printed ahead of them. Unbuffered, they keep their order. A
    value the machine or the script sets wins.
    """
    source = (os.environ if base is None else base) if env is None else env
    if "PYTHONUNBUFFERED" in source:
        return env
    return {**source, "PYTHONUNBUFFERED": "1"}


def terminate_tree(proc, *, platform=None, run=subprocess.run) -> None:
    """Stop a run and everything it started.

    On Windows ``terminate()`` ends only the process RYOS launched. A batch
    file's own children (python, a game client) survive it, so ``taskkill /T``
    takes the whole tree (issue #12). A step is done once its own process
    exits (see run_subprocess; a launcher's aside), so whatever it left
    behind no longer keeps the job running. Never raises: a process already gone is the outcome
    Stop wanted.
    """
    if proc is None or proc.poll() is not None:
        return
    if (platform or sys.platform) == "win32":
        try:
            run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False)
        except OSError:
            pass
        if proc.poll() is not None:
            return
    try:
        proc.terminate()
    except OSError:
        pass


def run_subprocess(output_queue, job, spec, name, script_id, log_output=False, step_token=None,
                   follow_leftovers=False):
    """Launch a run, stream stdout to output_queue, and post a completion item.

    `spec` is a RunSpec. A bare command list is also accepted and given the
    default working directory and an inherited environment — exactly what every
    caller did before per-script environments existed.

    A step is done when its process exits, not when its output pipe closes: a
    process the script leaves running inherits the pipe and may hold it for
    hours (issue #26). Its output is read for DRAIN_SECONDS more, then the
    done item is posted and anything later is discarded. With
    ``follow_leftovers`` (a launcher, whose run the UI releases on its own)
    the output is followed to end-of-file as before.

    Sets job.current_process (and job.processes[step_token]) so the UI can
    terminate it. Never raises: launch failures are reported on the queue as
    a "done"/"error" item.
    """
    if not isinstance(spec, RunSpec):
        spec = RunSpec(cmd=list(spec), cwd=working_dir_for(spec), env=None)
    cmd = spec.cmd
    def _put(item):
        # Token is appended only when one is supplied, so the tuple shape for
        # ad-hoc script runs (step_token=None) stays byte-identical to before
        # this feature — existing exact-tuple-equality tests keep passing.
        if step_token is not None:
            item = item + (step_token,)
        output_queue.put(item)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            # Nobody can type into a hidden run, so a `pause` or input() would
            # wait forever and the job could never finish (issue #12). With no
            # stdin they get end-of-file at once and the run carries on.
            stdin=subprocess.DEVNULL,
            # Binary: _forward_output decodes it, without ever raising.
            bufsize=0,
            cwd=spec.cwd,
            env=child_env(spec.env),
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        job.current_process = proc
        job.processes[step_token] = proc
        # Stop sets job.stopped, then terminates what is in job.processes. A
        # Stop that came while Popen was starting found nothing to terminate,
        # so this side looks too: one of the two always sees the other.
        if job.stopped:
            terminate_tree(proc)
    except FileNotFoundError as e:
        _log.error("Interpreter/file not found for %s: %s", name, e)
        _put(("stderr", job.job_id, f"[ERROR] {e}\n"))
        _put(("done", job.job_id, script_id, "error", f"❌ Interpreter/file not found: {name}\n"))
        return
    except Exception as e:
        _log.error("Failed to launch %s: %s", name, e)
        _put(("stderr", job.job_id, f"[ERROR] {e}\n"))
        _put(("done", job.job_id, script_id, "error", f"❌ Error: {name}\n"))
        return

    stream = _Stream()
    reader = threading.Thread(
        target=_forward_output, args=(proc, stream, _put, job.job_id, name, log_output),
        daemon=True)
    reader.start()
    if follow_leftovers:
        reader.join()
    proc.wait()
    reader.join(DRAIN_SECONDS)
    rc = proc.returncode
    tag = "ok" if rc == 0 else "stderr"
    status = "ok" if rc == 0 else "error"
    if rc == 0:
        _log.info("Done: %s | exit=%s", name, rc)
    else:
        _log.error("Done: %s | exit=%s", name, rc)
    # Under the reader's lock, so no line of this step lands after its done.
    with stream.lock:
        stream.cut = True
        if stream.partial:
            _put(("stdout", job.job_id, stream.partial))
            if log_output:
                _log.debug("[%s] %s", name, stream.partial.rstrip())
            stream.partial = ""
        _put((
            "done_tag", job.job_id, script_id, status, tag,
            f"\n  exit code {rc}  ·  {datetime.now().strftime('%H:%M:%S')}\n",
        ))


class _Stream:
    """What run_subprocess and its reader thread share about one step's output."""

    def __init__(self):
        self.lock = threading.Lock()
        self.cut = False     # the done item is posted: forward nothing more
        self.partial = ""    # text after the last newline, not yet posted


def _forward_output(proc, stream, put, job_id, name, log_output) -> None:
    """Read a run's output pipe to end-of-file, posting one item per line.

    os.read returns whatever is there, so a last prompt with no newline is not
    trapped in a buffer; it is held as the partial line and posted at the cut.
    The decoder is what text=True used (locale encoding, universal newlines)
    but replaces a byte it cannot decode instead of raising -- a raise here
    killed the thread before the done item, and the run never ended. After
    the cut the pipe is still drained, so a leftover process never blocks on
    a full pipe or gets a broken pipe.
    """
    decoder = io.IncrementalNewlineDecoder(
        codecs.getincrementaldecoder(locale.getpreferredencoding(False))(errors="replace"),
        translate=True)

    def forward(text):
        with stream.lock:
            if stream.cut:
                return
            *lines, stream.partial = (stream.partial + text).split("\n")
            for line in lines:
                put(("stdout", job_id, line + "\n"))
                if log_output:
                    _log.debug("[%s] %s", name, line.rstrip())

    try:
        fd = proc.stdout.fileno()
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            forward(decoder.decode(chunk))
        forward(decoder.decode(b"", final=True))
    except (OSError, ValueError):
        pass
    finally:
        try:
            proc.stdout.close()
        except OSError:
            pass


@dataclass
class OutputAction:
    """What the UI should do with one drained queue item.

    Decodes the queue protocol into a flat decision so the drain loop in the UI
    is a straight translation to widget calls — and so the index handling is
    unit-testable without a display.
    """
    text: str | None        # text to append (None = append nothing)
    tag: str | None          # output tag: "info" / "stderr" / "ok" / None (stdout default)
    status: str | None       # last_run_status to record (None = not a completion)
    sid: int | None          # script id for a completion (None otherwise)
    step_done: bool          # whether this item completes a run step
    token: object = None     # step_token, when the producer supplied one


def decode_output_item(item: tuple) -> OutputAction:
    """Translate one output-queue item into an OutputAction (see run_subprocess).

    A trailing step_token is optional on every shape (omitted for ad-hoc
    script runs), so its presence is detected from the tuple's length rather
    than a fixed index.
    """
    kind = item[0]
    if kind == "done":
        token = item[5] if len(item) > 5 else None
        return OutputAction(text=item[4], tag="info", status=item[3], sid=item[2], step_done=True, token=token)
    if kind == "done_tag":
        token = item[6] if len(item) > 6 else None
        return OutputAction(text=item[5], tag=item[4], status=item[3], sid=item[2], step_done=True, token=token)
    if kind == "stderr":
        token = item[3] if len(item) > 3 else None
        return OutputAction(text=item[2], tag="stderr", status=None, sid=None, step_done=False, token=token)
    token = item[3] if len(item) > 3 else None
    return OutputAction(text=item[2], tag=None, status=None, sid=None, step_done=False, token=token)
