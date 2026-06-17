# Contributing to RYOS

Thanks for hacking on RYOS. This guide gets you from a fresh clone to a green
test run, then explains the conventions the codebase expects.

## Prerequisites

- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** — the only
  thing you need to install. It provisions Python ≥3.10, creates the
  environment, and installs dependencies on demand. On Windows you can run
  `install_uv.bat`.
- **Tkinter** — bundled with Python on Windows and macOS. On Debian/Ubuntu the
  app (not the tests) needs the system package: `sudo apt install python3-tk`.

No manual `pip install` or virtualenv setup is required.

## Get it running

```bash
git clone https://github.com/lqvu-zen/RYOS.git
cd RYOS
uv run ryos            # launches the app; double-clicking run.bat does the same
```

`uv` reads `pyproject.toml`, builds an isolated environment, installs the lone
runtime dependency (`tkinterdnd2`), and invokes the `ryos` console-script
(`ryos.__main__:main`).

## Run the tests and linter

```bash
uv run --no-project --with pytest pytest -q   # ~160 tests, runs headless
uvx ruff check .                              # lint
```

The test suite mocks `tkinter`, so it runs without a display — the same way CI
does. `--no-project` skips the project sync because the tests manage `sys.path`
themselves and need no system Tk. Only `tests/test_ryos.py` is collected; the
other files in `tests/` (e.g. `hello_python.py`, `slow_counter.py`) are sample
scripts used as subprocess fixtures, not test modules — see the
`[tool.pytest.ini_options]` block in `pyproject.toml`.

To seed a database with sample scripts for manual UI testing:

```bash
uv run python tests/seed_db.py
```

## Project layout

```
ryos/
  __main__.py        entry point (ryos console-script)
  db.py              ScriptDB — all SQLite
  interpreter.py     extension→interpreter, command building
  settings.py        paths, defaults, load/save
  quickrun.py        pure Quick Run helpers
  jobs.py            Job, JobRegistry, format_elapsed
  runner.py          subprocess worker + output-queue decoding
  notifications.py   toast + GitHub update check
  logger.py          rotating-file logging
  startup.py         Windows run-at-login registry
  ui/                Tkinter layer (app, cards, dialogs, pipeline, theme, widgets)
tests/               test_ryos.py + runnable sample scripts
docs/                this guide, ARCHITECTURE.md, API_REFERENCE.md
```

Read `docs/ARCHITECTURE.md` first — it explains the two-layer design and the
threading/queue model that most changes have to respect.

## Conventions

**Keep the core UI-free.** The modules in the table above (everything outside
`ryos/ui/`) must not import `tkinter`. That separation is what lets the test
suite run headless. If you need Tk types in a core module for annotations only,
use `from __future__ import annotations` like `jobs.py` does.

**Never touch a Tk widget from a worker thread.** Subprocess output flows back
through the `queue.Queue` and is drained on the main thread by the
`after(80, ...)` timer. New background work should follow the same pattern.

**Put new business logic in a testable place.** The `★` modules (`quickrun`,
`jobs`, `runner`) exist because logic was pulled out of `app.py` so it could be
unit-tested. Prefer adding a pure function/class you can test directly over
growing `RYOSApp`.

**Schema changes go through migrations.** Don't edit `_ensure_baseline()` (it's
frozen at the v1 schema). Add an entry to `_MIGRATIONS` in `db.py` keyed by the
new `user_version`; it runs exactly once per database.

**Settings are additive.** Add a key with a sensible default to
`_SETTINGS_DEFAULTS` in `settings.py`. `_load_settings()` merges stored values
over the defaults, so old `settings.json` files keep working.

**Lint rules.** Ruff is configured to a focused set (`E4`, `E7`, `E9`, `F`) in
`pyproject.toml` — line-length (`E501`) and ambiguous-name (`E741`) are
deliberately off. Match the existing style rather than reformatting wholesale.

## Adding a new script type

To support a new file extension, add it in two places in `interpreter.py`:
`detect_interpreter()` (the extension→command map) and `_script_tag()` (the
badge label and colour). If it's a runnable type users might Quick-Run, also add
the extension to `quick_run_index_extensions` in `settings.py`. Add a case to
`TestDetectInterpreter` in `tests/test_ryos.py`.

## Submitting changes

1. Branch from `main`.
2. Make the change; add or update tests in `tests/test_ryos.py`.
3. Run `uvx ruff check .` and the test command above — both must pass.
4. Open a PR. CI runs ruff + pytest on Ubuntu and Windows across Python
   3.10 and 3.13; all four jobs must be green.

## Building a release executable

The primary packager is cx_Freeze (produces a folder you zip and distribute):

```bash
uv run --with cx_Freeze --with tkinterdnd2 python setup_cxfreeze.py build_exe
# or double-click build.bat / build_cxfreeze.bat
```

Output lands in `dist/cxfreeze/` (`RYOS.exe` plus DLLs). Bump `__version__` in
`ryos/__init__.py` before tagging a release — `pyproject.toml` reads the
version from there.
