"""The command line: list, run and wait for scripts and pipelines without
the window.

    ryos list [--json]
    ryos run <script> [--preset LABEL | --params="..."] [--timeout S] [--json]
    ryos pipeline <pipeline> [--timeout S] [--json]

A script or pipeline is named by its name, ``group/name`` or ``#id``
(``headless.resolve``). Runs go through the headless runner, so they are the
window's own runs -- same refusals, policies, history (marked ``cli``) -- with
no window, no toasts, no single-instance lock and no run-at-login write. A
running window is told to bring its cards up to date afterwards.

Output streams to stdout as it comes; with ``--json`` nothing streams, and
one JSON object is printed at the end. RYOS's own complaints go to stderr.

Exit codes: a script's own exit code (0 when it passed); 1 for a failed run
with no code of its own (a failed pipeline, a launch error); 2 for a command
line argparse could not read; and three that a script would rarely use, for
what RYOS itself did -- 124 timed out (as GNU ``timeout``), 125 refused (not
found, ambiguous, no such preset, missing file...), 130 interrupted. With
``--json`` the ``status`` field says which for certain.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Callable, TextIO

from . import __version__
from .db import SOURCE_CLI, ScriptDB
from .headless import (PIPELINE, SCRIPT, TIMEOUT, HeadlessError, HeadlessRunner,
                       Run, Target, resolve)
from .jobs import STOPPED

COMMANDS = ("list", "run", "pipeline")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
#: The run went past ``--timeout`` and was stopped (as GNU ``timeout``).
EXIT_TIMEOUT = 124
#: RYOS refused: not found, ambiguous, no such preset, missing file, empty
#: pipeline, already running.
EXIT_REFUSED = 125
#: Interrupted with Ctrl+C; the run was stopped.
EXIT_INTERRUPTED = 130

#: Lines of output ``--json`` includes by default.
DEFAULT_TAIL = 50


def is_cli(argv: list[str]) -> bool:
    """Whether a command line is for the CLI rather than the window. Plain
    ``ryos`` (and ``ryos --startup``) still opens the window."""
    return bool(argv) and (argv[0] in COMMANDS
                           or argv[0] in ("-h", "--help", "--version"))


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ryos",
        description="Run your scripts and pipelines without the window. "
                    "Plain `ryos` opens the window.",
        epilog="Name a script or pipeline by its name, group/name or #id. "
               f"Exit codes: the script's own; {EXIT_FAILED} failed; "
               f"{EXIT_TIMEOUT} timed out; {EXIT_REFUSED} refused by RYOS; "
               f"{EXIT_INTERRUPTED} interrupted.")
    p.add_argument("--version", action="version", version=f"RYOS {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    ls = sub.add_parser("list", help="List scripts and pipelines.")
    ls.add_argument("--json", action="store_true", help="Print JSON.")

    def common(sp):
        sp.add_argument("--timeout", type=float, metavar="SECONDS",
                        help="Stop the run after this long.")
        sp.add_argument("--json", action="store_true",
                        help="Print one JSON result at the end instead of streaming.")
        sp.add_argument("--tail", type=int, default=DEFAULT_TAIL, metavar="N",
                        help=f"Lines of output in the JSON result (default {DEFAULT_TAIL}).")

    run = sub.add_parser("run", help="Run a script and wait for it.")
    run.add_argument("ref", metavar="SCRIPT")
    how = run.add_mutually_exclusive_group()
    how.add_argument("--preset", metavar="LABEL", help="Use a saved preset's parameters.")
    how.add_argument("--params", metavar="TEXT",
                     help="Use these parameters instead of the script's own. "
                          "Write --params=\"--flag value\" when they start with a dash.")
    common(run)

    pipe = sub.add_parser("pipeline", help="Run a pipeline and wait for it.")
    pipe.add_argument("ref", metavar="PIPELINE")
    common(pipe)
    return p


# -- list ----------------------------------------------------------------------

def _listing(db: ScriptDB) -> dict:
    """What ``list`` shows. Never a script's environment: it can hold secrets."""
    scripts = [{"id": row[0], "name": row[1], "group": row[8] or "",
                "ref": Target(SCRIPT, row[0], row[1], row[8] or "").ref,
                "presets": [label for _pid, label, _p in db.list_param_presets(row[0])]}
               for row in db.list_all()]
    pipelines = []
    for group in [*db.list_groups(), ""]:
        for pid, name, *_ in db.list_pipelines(group):
            pipelines.append({"id": pid, "name": name, "group": group,
                              "ref": Target(PIPELINE, pid, name, group).ref,
                              "steps": len(db.list_pipeline_steps(pid))})
    return {"scripts": scripts, "pipelines": pipelines}


def _print_listing(listing: dict, out: TextIO) -> None:
    rows = [(f"#{s['id']}", "script", s["ref"],
             f"presets: {', '.join(s['presets'])}" if s["presets"] else "")
            for s in listing["scripts"]]
    rows += [(f"#{p['id']}", "pipeline", p["ref"],
              f"{p['steps']} step{'s' if p['steps'] != 1 else ''}")
             for p in listing["pipelines"]]
    if not rows:
        print("No scripts or pipelines yet.", file=out)
        return
    widths = [max(len(r[i]) for r in rows) for i in range(3)]
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip()
              + ("  " + r[3] if r[3] else ""), file=out)


# -- run -----------------------------------------------------------------------

def _exit_code(run: Run) -> int:
    if run.status == "ok":
        return EXIT_OK
    if run.status == TIMEOUT:
        return EXIT_TIMEOUT
    if run.status == STOPPED:
        return EXIT_INTERRUPTED
    return run.exit_code if run.exit_code else EXIT_FAILED


def _result(run: Run, tail: int) -> dict:
    finished = run.finished_at
    return {
        "kind": run.target.kind, "id": run.target.item_id, "ref": run.target.ref,
        "status": run.status, "exit_code": run.exit_code,
        "started_at": run.started_at.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds") if finished else None,
        "duration_seconds": (round((finished - run.started_at).total_seconds(), 3)
                             if finished else None),
        "output": run.tail(tail),
        "output_lines": run.total,
    }


def _refuse(message: str, as_json: bool, out: TextIO, err: TextIO) -> int:
    if as_json:
        print(json.dumps({"status": "refused", "error": message}), file=out)
    else:
        print(f"ryos: {message}", file=err)
    return EXIT_REFUSED


def _run(args, db: ScriptDB, settings: dict, out: TextIO, err: TextIO,
         notify_window: Callable[[], object]) -> int:
    kind = SCRIPT if args.command == "run" else PIPELINE
    def stream(_run: Run, text: str, _tag: str | None) -> None:
        out.write(text)
        out.flush()

    runner = HeadlessRunner(db, settings, trigger=SOURCE_CLI,
                            on_output=None if args.json else stream)
    try:
        target = resolve(db, kind, args.ref)
        if kind == SCRIPT:
            run = runner.start_script(target, params=args.params, preset=args.preset)
        else:
            run = runner.start_pipeline(target)
    except HeadlessError as e:
        return _refuse(str(e), args.json, out, err)
    try:
        try:
            runner.wait(run, args.timeout)
        except KeyboardInterrupt:
            print("\nryos: stopping…", file=err)
            runner.stop(run)
            runner.wait(run)
    finally:
        runner.stop_all()       # a second Ctrl+C must not leave it running
        notify_window()
    if args.json:
        print(json.dumps(_result(run, args.tail)), file=out)
    elif run.status == TIMEOUT:
        print(f"ryos: {run.target.ref} timed out after {args.timeout:g}s and was stopped.",
              file=err)
    return _exit_code(run)


# -- entry ---------------------------------------------------------------------

def _readable(stream: TextIO) -> None:
    """A Windows console's code page cannot print every character a script
    (or a pipeline's banner) writes; replace those rather than crash."""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(errors="replace")
        except (OSError, ValueError):
            pass


def _notify_running_window() -> None:
    from .single_instance import RELOAD, signal_running
    signal_running(RELOAD)


def main(argv: list[str], *, db: ScriptDB | None = None, settings: dict | None = None,
         out: TextIO | None = None, err: TextIO | None = None,
         notify_window: Callable[[], object] | None = None) -> int:
    """Run one command. Everything with an effect outside this process is an
    argument, so tests pass throwaway ones; the defaults are the real ones."""
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    try:
        args = _parser().parse_args(argv)
    except SystemExit as e:             # --help, --version, or a bad line
        return e.code if isinstance(e.code, int) else EXIT_OK
    if settings is None or db is None:
        from .logger import setup_logging
        from .settings import LOG_DIR, _load_settings
        settings = _load_settings() if settings is None else settings
        setup_logging(settings.get("logging_enabled", True),
                      settings.get("log_level", "INFO"), LOG_DIR / "ryos-cli.log")
        db = ScriptDB() if db is None else db
    if args.command == "list":
        listing = _listing(db)
        if args.json:
            print(json.dumps(listing), file=out)
        else:
            _print_listing(listing, out)
        return EXIT_OK
    for stream in (out, err):
        _readable(stream)
    return _run(args, db, settings, out, err,
                notify_window if notify_window is not None else _notify_running_window)
