"""The command line: list, run and wait for scripts and pipelines without
the window.

    ryos list [--json]
    ryos run <script> [--preset LABEL | --params="..."] [--timeout S] [--json]
    ryos pipeline <pipeline> [--timeout S] [--json]
    ryos add <file> [--name N] [--group G] [--workdir DIR] [--params="..."] [--expose] [--yes]
    ryos edit <script> [--name N] [--group G] [--workdir DIR] [--params="..."] [--yes]
    ryos remove <script> [--yes]
    ryos expose <script> on|off [--pipeline] [--yes]
    ryos preset add <script> <label> --params="..."   |   ryos preset remove <script> <label>
    ryos history [<script>] [--pipeline] [--limit N] [--json]

Adding, editing, removing and exposing follow the script dialog's own rules
(``ryos/manage.py``). Letting agents run something, and removing, ask at
the terminal; without one -- an agent calling ryos-cli, say -- they refuse
unless given ``--yes`` (docs/plans/release-2.3.0.md, A2). A running window
rebuilds its rows after any change.

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

from . import __version__, buildinfo, manage
from . import history as runhistory
from .db import SOURCE_CLI, NewerDatabaseError, ScriptDB
from .headless import (PIPELINE, SCRIPT, TIMEOUT, HeadlessError, HeadlessRunner,
                       Run, Target, resolve)
from .jobs import STOPPED

COMMANDS = ("list", "run", "pipeline", "mcp",
            "add", "edit", "remove", "expose", "preset", "history", "version")

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
                    "Plain `ryos` (or RYOS.exe) opens the window.",
        epilog="Name a script or pipeline by its name, group/name or #id. "
               f"Exit codes: the script's own; {EXIT_FAILED} failed; "
               f"{EXIT_TIMEOUT} timed out; {EXIT_REFUSED} refused by RYOS; "
               f"{EXIT_INTERRUPTED} interrupted.")
    p.add_argument("--version", action="version",
                   version=f"RYOS {__version__} ({buildinfo.describe()})")
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

    sub.add_parser("mcp", help="Serve the scripts and pipelines made available to "
                               "agents over MCP (stdio). Needs the mcp extra.")

    params_help = "Write --params=\"--flag value\" when they start with a dash."
    yes_help = "Don't ask; do it (also when RYOS would ask about the path)."

    add = sub.add_parser("add", help="Add a script.")
    add.add_argument("file", metavar="FILE")
    add.add_argument("--name", help="The name to use (default: the file name).")
    add.add_argument("--group", default="", help="Its group (made if new).")
    add.add_argument("--workdir", metavar="DIR", help="The folder it runs in.")
    add.add_argument("--params", default="", metavar="TEXT",
                     help="The parameters it runs with. " + params_help)
    add.add_argument("--expose", action="store_true",
                     help="Let AI agents run it (asks at the terminal).")
    add.add_argument("--yes", action="store_true", help=yes_help)

    ed = sub.add_parser("edit", help="Change a script's name, group, folder or parameters.")
    ed.add_argument("ref", metavar="SCRIPT")
    ed.add_argument("--name")
    ed.add_argument("--group")
    ed.add_argument("--workdir", metavar="DIR")
    ed.add_argument("--params", metavar="TEXT", help=params_help)
    ed.add_argument("--yes", action="store_true", help=yes_help)

    rm = sub.add_parser("remove", help="Remove a script (asks first).")
    rm.add_argument("ref", metavar="SCRIPT")
    rm.add_argument("--yes", action="store_true", help="Don't ask.")

    ex = sub.add_parser("expose", help="Let AI agents run a script or pipeline, or stop.")
    ex.add_argument("ref", metavar="SCRIPT")
    ex.add_argument("state", choices=("on", "off"))
    ex.add_argument("--pipeline", action="store_true", help="REF names a pipeline.")
    ex.add_argument("--yes", action="store_true", help="Don't ask (turning it on asks).")

    pre = sub.add_parser("preset", help="Add or remove a script's saved preset.")
    pre_sub = pre.add_subparsers(dest="preset_action", required=True)
    pa = pre_sub.add_parser("add", help="Save a preset.")
    pa.add_argument("ref", metavar="SCRIPT")
    pa.add_argument("label")
    pa.add_argument("--params", required=True, metavar="TEXT", help=params_help)
    pr = pre_sub.add_parser("remove", help="Remove a preset.")
    pr.add_argument("ref", metavar="SCRIPT")
    pr.add_argument("label")

    ve = sub.add_parser("version", help="This RYOS's version; --check asks GitHub "
                                         "whether a newer one is out.")
    ve.add_argument("--check", action="store_true",
                    help="Check for a newer release, and name the file to download.")

    hi = sub.add_parser("history", help="What has run, newest first.")
    hi.add_argument("ref", nargs="?", metavar="SCRIPT")
    hi.add_argument("--pipeline", action="store_true", help="REF names a pipeline.")
    hi.add_argument("--limit", type=int, default=20, metavar="N")
    hi.add_argument("--json", action="store_true", help="Print JSON.")
    return p


# -- list ----------------------------------------------------------------------

def _listing(db: ScriptDB) -> dict:
    """What ``list`` shows. Never a script's environment: it can hold secrets."""
    exposed = db.agent_exposed_ids(SCRIPT)
    scripts = [{"id": row[0], "name": row[1], "group": row[8] or "",
                "ref": Target(SCRIPT, row[0], row[1], row[8] or "").ref,
                "presets": [label for _pid, label, _p in db.list_param_presets(row[0])],
                "agents": row[0] in exposed}
               for row in db.list_all()]
    exposed_pipes = db.agent_exposed_ids(PIPELINE)
    pipelines = []
    for group in [*db.list_groups(), ""]:
        for pid, name, *_ in db.list_pipelines(group):
            pipelines.append({"id": pid, "name": name, "group": group,
                              "ref": Target(PIPELINE, pid, name, group).ref,
                              "steps": len(db.list_pipeline_steps(pid)),
                              "agents": pid in exposed_pipes})
    return {"scripts": scripts, "pipelines": pipelines}


def _print_listing(listing: dict, out: TextIO) -> None:
    def notes(*parts):
        return "  ".join(x for x in parts if x)

    agents = "available to agents"
    rows = [(f"#{s['id']}", "script", s["ref"],
             notes(f"presets: {', '.join(s['presets'])}" if s["presets"] else "",
                   agents if s["agents"] else ""))
            for s in listing["scripts"]]
    rows += [(f"#{p['id']}", "pipeline", p["ref"],
              notes(f"{p['steps']} step{'s' if p['steps'] != 1 else ''}",
                    agents if p["agents"] else ""))
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


# -- managing scripts -------------------------------------------------------

def _ask_at_terminal(question: str) -> bool | None:
    """Ask a yes/no question at the terminal; None when there is no terminal
    to ask at (an agent calling ryos-cli, a scheduled task)."""
    if not (sys.stdin and sys.stdin.isatty()):
        return None
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return None


def _agreed(question: str, yes: bool, ask, what: str) -> None:
    """Go on when --yes, or a person said yes; refuse otherwise."""
    if yes:
        return
    answer = ask(question)
    if answer is None:
        raise manage.ManageError(f"{what} needs you at a terminal to say yes: "
                                 "run it in one, or add --yes.")
    if not answer:
        raise manage.ManageError("Left as it was.")


def _find(db: ScriptDB, kind: str, ref: str):
    try:
        return resolve(db, kind, ref)
    except HeadlessError as e:
        raise manage.ManageError(str(e)) from None


def _history_rows(rows: list) -> list[dict]:
    return [{"id": r[0], "kind": r[3], "name": r[4], "started_at": r[5],
             "finished_at": r[6], "status": r[7], "exit_code": r[8],
             "step": r[9], "by": r[10]} for r in rows]


def _manage(args, db: ScriptDB, out: TextIO, ask, rebuild_window) -> int:
    """add / edit / remove / expose / preset / history. Raises ManageError."""
    command = args.command
    if command == "history":
        kind = PIPELINE if args.pipeline else SCRIPT
        target = _find(db, kind, args.ref) if args.ref else None
        rows = manage.history(db, target, max(1, args.limit))
        if args.json:
            print(json.dumps(_history_rows(rows)), file=out)
        elif not rows:
            print("Nothing has run yet.", file=out)
        else:
            print(runhistory.header_row(), file=out)
            for row in rows:
                print(runhistory.format_run_row(row), file=out)
        return EXIT_OK
    if command == "add":
        if args.expose:
            _agreed(f"Let AI agents run {args.file}?", args.yes, ask,
                    "Letting agents run a script")
        target = manage.add_script(db, args.file, name=args.name, group=args.group,
                                   work_dir=args.workdir, params=args.params,
                                   expose=args.expose, confirmed=args.yes)
        said = f"Added {target.ref} (#{target.item_id})"
        said += ", available to agents." if args.expose else "."
    elif command == "edit":
        target = manage.edit_script(db, _find(db, SCRIPT, args.ref), name=args.name,
                                    group=args.group, work_dir=args.workdir,
                                    params=args.params, confirmed=args.yes)
        said = f"Changed {target.ref}."
    elif command == "remove":
        target = _find(db, SCRIPT, args.ref)
        steps = manage.pipelines_using(db, target)
        also = (f" It is a step of {', '.join(repr(n) for n in steps)}, which lose it."
                if steps else "")
        _agreed(f"Remove {target.ref}?{also}", args.yes, ask, "Removing a script")
        manage.remove_script(db, target)
        said = f"Removed {target.ref}."
    elif command == "expose":
        target = _find(db, PIPELINE if args.pipeline else SCRIPT, args.ref)
        on = args.state == "on"
        if on:
            _agreed(f"Let AI agents run {target.ref}?", args.yes, ask,
                    "Letting agents run something")
        changed = manage.set_exposed(db, target, on)
        state = "available to agents" if on else "not available to agents"
        said = f"{target.ref} is {state}." + ("" if changed else " (It already was.)")
    else:                                   # preset add / remove
        target = _find(db, SCRIPT, args.ref)
        if args.preset_action == "add":
            manage.add_preset(db, target, args.label, args.params)
            said = f"Saved preset {args.label!r} for {target.ref}."
        else:
            manage.remove_preset(db, target, args.label)
            said = f"Removed preset {args.label!r} from {target.ref}."
    print(said, file=out)
    rebuild_window()
    return EXIT_OK


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


def _rebuild_running_window() -> None:
    from .single_instance import REBUILD, signal_running
    signal_running(REBUILD)


def main(argv: list[str], *, db: ScriptDB | None = None, settings: dict | None = None,
         out: TextIO | None = None, err: TextIO | None = None,
         notify_window: Callable[[], object] | None = None,
         rebuild_window: Callable[[], object] | None = None,
         ask: Callable[[str], bool | None] | None = None,
         fetch_release: Callable[[], object] | None = None) -> int:
    """Run one command. Everything with an effect outside this process is an
    argument, so tests pass throwaway ones; the defaults are the real ones."""
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    try:
        args = _parser().parse_args(argv)
    except SystemExit as e:             # --help, --version, or a bad line
        return e.code if isinstance(e.code, int) else EXIT_OK
    if args.command == "version":
        print(f"RYOS {__version__} ({buildinfo.describe()})", file=out)
        if not args.check:
            return EXIT_OK
        from . import notifications
        fetch = fetch_release or notifications._fetch_latest_release
        status, tag, url = notifications.update_status(fetch(), __version__)
        print(notifications.version_check_text(status, tag, url, __version__,
                                               buildinfo.download_name()), file=out)
        return EXIT_FAILED if status == notifications.UNREACHABLE else EXIT_OK
    if args.command == "mcp":
        # Its own start-up: it logs to ryos-mcp.log, and it is long-lived.
        from .mcpserver import serve
        return serve()
    if settings is None or db is None:
        from .logger import setup_logging
        from .settings import LOG_DIR, _load_settings
        settings = _load_settings() if settings is None else settings
        setup_logging(settings.get("logging_enabled", True),
                      settings.get("log_level", "INFO"), LOG_DIR / "ryos-cli.log")
        try:
            db = ScriptDB() if db is None else db
        except NewerDatabaseError as e:
            print(f"ryos: {e}", file=err)
            return EXIT_REFUSED
    # Every command can print a mark the console's code page lacks: history's
    # "✓ OK", a name, a script's own output.
    for stream in (out, err):
        _readable(stream)
    if args.command in ("add", "edit", "remove", "expose", "preset", "history"):
        try:
            return _manage(args, db, out, ask or _ask_at_terminal,
                           rebuild_window or _rebuild_running_window)
        except manage.ManageError as e:
            print(f"ryos: {e}", file=err)
            return EXIT_REFUSED
    if args.command == "list":
        listing = _listing(db)
        if args.json:
            print(json.dumps(listing), file=out)
        else:
            _print_listing(listing, out)
        return EXIT_OK
    return _run(args, db, settings, out, err,
                notify_window if notify_window is not None else _notify_running_window)
