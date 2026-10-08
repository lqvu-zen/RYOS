---
name: release-ryos
description: 'Cut a new GitHub release of the RYOS desktop app — bump the version, build the Windows exe, smoke-test it, package the download zips, tag, and publish. Use this whenever the user wants to ship RYOS: "cut a release", "release v1.6.5", "publish a new version", "ship it", "build the exe and put it on GitHub", "make a new build", or "tag a release". Also use it when the user has finished a batch of features/fixes and says it''s time to get them out to users. This skill carries the exact version scheme, the cx_Freeze build command, the exe smoke-test gate, the windows + portable zip packaging, and the gh release steps, so the process is repeatable and safe. It runs on Windows with uv and an authenticated gh CLI. Do NOT use it to write features (use add-ryos-feature), fix bugs (use fix-ryos-bug), or just launch the app locally (use run-ryos).'
---

# Releasing RYOS

RYOS ships as a GitHub release with three downloadable assets, built and checked by `build_release.py`: **`RYOS-windows.zip`** (`RYOS.exe` and the console `ryos-cli.exe`, MCP server inside, for most users), **`RYOS-agent.zip`** (`ryos-cli.exe` alone, no window and no Qt — RYOS Agent) and **`RYOS-portable.zip`** (the source, run with uv via `run.bat`), plus `SHA256SUMS.txt`. The release is tagged in the repo `lqvu-zen/RYOS`, and the app's built-in update check (`ryos/notifications.py`) compares the running `__version__` against the latest GitHub tag — so the tag, the assets, and `__version__` must all line up.

Releasing is **not a design problem** — it's a deterministic runbook, so unlike `add-ryos-feature` and `fix-ryos-bug` there is no design subagent here, and you run the steps inline. There is one independent check: before anything is pushed or published, a fresh `ryos-reviewer` in release mode confirms this is the *right* release (step 5), because the build and smoke gates only prove each zip builds and starts. The safety comes from **hard gates**: CI must be green on the commit you're shipping, the build must succeed, the exe must survive a smoke test *showing the version you just built*, every zip must contain the expected files, and the release review must print `READY TO PUBLISH` — stop and report at any gate that fails rather than publishing a broken release. A gate that fails for an unexpected reason is worth a minute's diagnosis before you either abort or work around it; the smoke test in particular has a known false failure, documented in step 4. (Drafting release notes from the commit log is the one step you may hand to a cheap Haiku/Sonnet subagent if you like; everything else is yours.)

## Environment this needs

This runs on the maintainer's **Windows** machine, because the exe is built and smoke-tested there:

- `uv` installed (drives the build in an isolated env).
- `gh` CLI installed and authenticated to GitHub (`gh auth status`) — it creates the release and uploads assets.
- PowerShell (for the smoke test and zip packaging).
- A working tree you're willing to commit and push from, on the release branch (`main`).

If you're somewhere without a display or without Windows (e.g. a Linux sandbox), you **cannot** build or smoke-test the exe — say so plainly and stop; do not fake a release.

## Version scheme

`__version__` (in `ryos/__init__.py`) is bumped **only here, at release time** — never per feature or fix. Between releases the tree simply holds the last published version; there is no `-dev` suffix. A release sets the next concrete version:

- Release `X.Y.Z`: set `__version__ = "X.Y.Z"` (no `-dev`, no `v` prefix). `pyproject.toml` reads the version dynamically from this line via hatchling, so this is the single source.

The tag on GitHub uses the `v` prefix (`vX.Y.Z`); `__version__` does not.

## The steps

### 1. Check CI, then decide the version and notes

First confirm the commit you're about to ship is green:

```bash
cd D:/Projects/RYOS && git status --porcelain && gh run list -L 3 --json conclusion,status,headSha,displayTitle \
  --jq '.[] | "\(.status)\t\(.conclusion // "-")\t\(.headSha[0:7])\t\(.displayTitle)"'
```

The tree must be clean and `HEAD` must have a **successful** run. CI has sat red for several commits without anyone noticing, so treat a failure — or a run still in progress — as a stop: fix it or wait, don't release on top of it. (A long build can run while CI finishes, but don't *publish* until it's green.)

Then check the latest published tag (`gh release list -R lqvu-zen/RYOS -L 5` or the releases page) and **ask the user for the version number, and wait for the answer** before building — you may suggest one (patch for fixes, minor for notable features, based on the last released version), but the maintainer names it. A bare "release" or "go ahead" is not approval of a version suggested earlier in the conversation: 2.1.0 shipped that way, and the maintainer asked never to repeat it. Gather release notes; if the user didn't give any, draft them from `git log <last-tag>..HEAD --oneline` and show them for approval. Don't invent a version or notes silently.

Notes are for users, not for the changelog: say what changed for someone using the app, and flag anything that will behave differently than it did before.

### 2. Set `__version__`

```bash
cd D:/Projects/RYOS && grep -n "__version__" ryos/__init__.py
```

Edit the line to the concrete version, e.g. `__version__ = "1.6.5"`. (Optional polish: `setup_cxfreeze.py` carries its own hardcoded `version=` string used only for exe metadata, and it drifts — if you care about correct file metadata, update it to match; it does not affect the update check.)

### 3. Build and package every download — hard gate

One script builds both exes from clean folders, zips all three downloads, checks what each holds and must not hold, and writes `SHA256SUMS.txt`:

```bash
cd D:/Projects/RYOS && uv run --extra mcp --with cx_Freeze python build_release.py 2>&1 | tail -8
```

It ends with `build_release done`, a size per zip (2.3.0: windows about 37 MB, agent about 19 MB, portable under 1 MB) and the checksums file. It stops with exit 1 on any problem: an exe missing, no MCP SDK in an exe, Qt or the window in the agent build, a `__pycache__` or `_build_info.py` in the source. **If it fails, stop and report.** The builds stay in `dist/cxfreeze/` (Windows) and `dist/cxfreeze-agent/` (agent) for the smoke tests.

> `build.bat` / `build_cxfreeze.bat` build only the Windows folder, for development; releases go through `build_release.py`.

There is nothing to package by hand. Don't use `Compress-Archive` for the portable zip: it sweeps in every local `__pycache__` (95 stale bytecode files, tripling the zip, in 2.0.0's first attempt).

### 4. Smoke-test the builds — hard gate

A release that crashes on launch is worse than no release, so prove both builds start before going further. `tests/launch_smoke.py` launches them the way the maintainer needs it launched:

- **Never on the first screen.** The maintainer works there (and may be in a game). With no flag, the app runs on Qt's offscreen platform and no window appears anywhere; `--visible` puts it on the second screen (`tests/smoke_screen.py`), and falls back to the primary only when there is one monitor — so check `smoke_screen()` before using `--visible`. Never launch `RYOS.exe` directly with `Start-Process`: its window opens wherever Windows places it.
- **Throwaway data, no registry writes.** `APPDATA` points at a temp folder, `RYOS_NO_REGISTRY=1` and `RYOS_NO_TOASTS=1`, so no notification pops up and the real database, settings and run-at-login entry are never touched; the smoke fails if anything in the real `%APPDATA%\RYOS` changed.
- **`RYOS_ALLOW_MULTIPLE=1`**, so the maintainer's own running RYOS is neither signalled nor made to swallow the launch. (Without it, the single-instance guard makes the new exe hand off and exit 0 — which looks like a crash. Never "fix" that by killing the maintainer's instance.)
- **It checks the version.** The app logs `RYOS <version> starting`; the smoke fails unless that is the version in `ryos/__init__.py`, which is what proves you are testing the build you just made rather than a stale `dist/`.
- **It checks the command line and MCP too:** `ryos-cli.exe --version`, `list` and a real `run`, then `ryos-cli.exe mcp` spoken to as plain JSON-RPC (initialize, the tool list, `list_scripts`).

The Windows build twice — offscreen, then on the second screen, which also proves the frozen Windows platform plugin (`qwindows.dll`) loads — then the agent build:

```bash
cd D:/Projects/RYOS && uv run python tests/launch_smoke.py --exe dist/cxfreeze/RYOS.exe
cd D:/Projects/RYOS && uv run python -c "import sys; sys.path.insert(0,'tests'); from smoke_screen import _monitor_work_areas as a; print(len(a()), 'monitor(s)')"
cd D:/Projects/RYOS && uv run python tests/launch_smoke.py --exe dist/cxfreeze/RYOS.exe --visible   # only with 2+ monitors
cd D:/Projects/RYOS && uv run python tests/launch_smoke.py --cli-only dist/cxfreeze-agent/ryos-cli.exe
```

The agent smoke also checks the build says `RYOS <version> (RYOS Agent)` and carries no Qt and no window. **If any fails, stop and report — do not release.**

Then check the upgrade path on a copy of an older database, if one exists (`%APPDATA%\RYOS\scripts.db.backup-*`, or one the maintainer names), and on a copy of the current data. `--db` opens a *copy*; the real file is never opened:

```bash
cd D:/Projects/RYOS && uv run python tests/real_data_smoke.py --db "$APPDATA/RYOS/scripts.db.backup-<date>"
cd D:/Projects/RYOS && uv run python tests/real_data_smoke.py
```

It prints the schema step and what changed (`schema: v7 -> v10; pipeline steps 59 -> 0`). A count that drops is a stop until you know why: open another copy with `sqlite3` and confirm the rows were ones the migration is meant to remove (v8's `_migrate_drop_orphans` removes only steps, presets and schedules whose script or pipeline is gone) — and say so in the release notes. The current-data check also opens every script in the script dialog and fails if an unchanged save would change one (it caught 2.2.0's outside-folder bug).

### 5. Release review — hard gate

The builds start; now confirm this is the *right* release before anything is pushed. Spawn a fresh reviewer, which hasn't seen this session:

```
Agent({ description: "Release review v<X.Y.Z>", subagent_type: "ryos-reviewer", prompt: <brief> })
```

(If `ryos-reviewer` isn't listed, use `subagent_type: "general-purpose"`, `model: "opus"`, `effort: "high"`, and paste `.claude/agents/ryos-reviewer.md` at the top of the brief.)

The brief starts with **"Release mode."** and includes, verbatim:

- the version being released and the last released tag (`gh release list -R lqvu-zen/RYOS -L 1`);
- the approved release notes from step 1, including the "Which download?" section;
- the **expected lineup** below;
- the last lines of the `build_release.py` output (step 3) and every smoke-test result (step 4);
- the release plan's final step with its "Done when" items (`docs/plans/release-<X.Y.Z>.md`), if there is one.

Expected lineup (**update this table whenever the downloads change**, together with `problems_in()` in `build_release.py`):

| Zip | Variant | Must contain | Must not contain |
|---|---|---|---|
| `RYOS-windows.zip` | `windows` | `RYOS.exe`, `ryos-cli.exe`, the `mcp` package (`lib/mcp/`) | — |
| `RYOS-agent.zip` | `agent` | `ryos-cli.exe`, the `mcp` package (`lib/mcp/`) | `RYOS.exe`, `qtui`, Qt / PySide6 / shiboken6 |
| `RYOS-portable.zip` | source | the source, `ryos/__init__.py`, `run.bat`, `install_uv.bat` | `__pycache__`, `_build_info.py` |
| all | | | `scripts.db`, a settings file, `__pycache__` in the source |

`SHA256SUMS.txt` lists exactly these three zips.

If the reviewer reports BLOCKERS, fix them (rebuilding and re-smoking if any build changed) and review again. Go on to step 6 only on `READY TO PUBLISH`. Then show the user every **needs a human** item it listed, such as the clean-machine test of each MCP build, and **wait for them to confirm each one** before publishing.

### 6. Commit and push the version bump

Tag the published code, so commit the version bump (and any other intended changes) first. Stage deliberately — **never** `dist/`, `build/`, `scripts.db`, or `__pycache__`:

```bash
cd D:/Projects/RYOS && git status
cd D:/Projects/RYOS && git add ryos/__init__.py <other intended files> && git commit -m "Bump version to <X.Y.Z>" && git push
```

### 7. Create the GitHub release

Only once CI is green on the version-bump commit (`gh run watch <id> --exit-status`). Write the notes to a file in the scratchpad rather than quoting them on the command line, where backticks and `$` get mangled:

```bash
cd D:/Projects/RYOS && gh release create v<X.Y.Z> dist/RYOS-windows.zip dist/RYOS-agent.zip \
  dist/RYOS-portable.zip dist/SHA256SUMS.txt \
  -R lqvu-zen/RYOS --target main --title "v<X.Y.Z>" --notes-file <notes.md> 2>&1
```

Include the download guidance in the notes so users know which asset to grab:

```
<user-approved notes>

## Which download?
- **RYOS-windows.zip** — the app: extract and run `RYOS.exe`. `ryos-cli.exe` beside it is the command line and the MCP server for AI agents (`ryos-cli.exe mcp`).
- **RYOS-agent.zip** — RYOS Agent: just `ryos-cli.exe`, for letting Claude run an allow-list of your scripts without the app. See the guide's RYOS Agent page.
- **RYOS-portable.zip** — run from source: extract and double-click `run.bat` (needs uv; run `install_uv.bat` first if needed).
- **SHA256SUMS.txt** — checksums of the three zips.
```

### 8. Clear `dist/`

The zips are on GitHub now; stale builds left in `dist/` are how an old exe gets smoke-tested or attached next time:

```bash
cd D:/Projects/RYOS && rm -rf dist/* build
```

### 9. Report

Give the user the release URL (`gh` prints it), the version shipped, the assets attached, and a one-line confirmation that the smoke test and zip checks passed and that the release review printed `READY TO PUBLISH`. Note anything you skipped or that needs follow-up.
