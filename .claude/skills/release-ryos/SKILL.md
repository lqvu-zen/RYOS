---
name: release-ryos
description: 'Cut a new GitHub release of the RYOS desktop app — bump the version, build the Windows exe, smoke-test it, package the download zips, tag, and publish. Use this whenever the user wants to ship RYOS: "cut a release", "release v1.6.5", "publish a new version", "ship it", "build the exe and put it on GitHub", "make a new build", or "tag a release". Also use it when the user has finished a batch of features/fixes and says it''s time to get them out to users. This skill carries the exact version scheme, the cx_Freeze build command, the exe smoke-test gate, the windows + portable zip packaging, and the gh release steps, so the process is repeatable and safe. It runs on Windows with uv and an authenticated gh CLI. Do NOT use it to write features (use add-ryos-feature), fix bugs (use fix-ryos-bug), or just launch the app locally (use run-ryos).'
---

# Releasing RYOS

RYOS ships as a GitHub release with two downloadable assets: **`RYOS-windows.zip`** (the frozen `RYOS.exe` plus its DLLs, for users who just want to run it) and **`RYOS-portable.zip`** (the source, for users who run it from Python via `run.bat`). The release is tagged in the repo `lqvu-zen/RYOS`, and the app's built-in update check (`ryos/notifications.py`) compares the running `__version__` against the latest GitHub tag — so the tag, the assets, and `__version__` must all line up.

Releasing is **not a design problem** — it's a deterministic runbook, so unlike `add-ryos-feature` and `fix-ryos-bug` there are no design/review subagents here. You run it inline. The safety comes from **hard gates**: CI must be green on the commit you're shipping, the build must succeed, the exe must survive a smoke test *showing the version you just built*, and both zips must contain the expected files — stop and report at any gate that fails rather than publishing a broken release. A gate that fails for an unexpected reason is worth a minute's diagnosis before you either abort or work around it; the smoke test in particular has a known false failure, documented in step 4. (Drafting release notes from the commit log is the one step you may hand to a cheap Haiku/Sonnet subagent if you like; everything else is yours.)

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

Then check the latest published tag (`gh release list -R lqvu-zen/RYOS -L 5` or the releases page) and confirm the next version with the user — patch for fixes, minor for notable features, based on the last released version. Gather release notes; if the user didn't give any, draft them from `git log <last-tag>..HEAD --oneline` and show them for approval. Don't invent a version or notes silently.

Notes are for users, not for the changelog: say what changed for someone using the app, and flag anything that will behave differently than it did before.

### 2. Set `__version__`

```bash
cd D:/Projects/RYOS && grep -n "__version__" ryos/__init__.py
```

Edit the line to the concrete version, e.g. `__version__ = "1.6.5"`. (Optional polish: `setup_cxfreeze.py` carries its own hardcoded `version=` string used only for exe metadata, and it drifts — if you care about correct file metadata, update it to match; it does not affect the update check.)

### 3. Build the exe

Clear the old build first, so nothing stale can be packaged or smoke-tested by mistake:

```bash
cd D:/Projects/RYOS && rm -rf dist/cxfreeze build && uv run --with cx_Freeze python setup_cxfreeze.py build_exe 2>&1 | tail -3
```

This writes `dist/cxfreeze/` with `RYOS.exe` and its DLLs. Confirm it exists and stop if it doesn't:

```bash
ls -lh D:/Projects/RYOS/dist/cxfreeze/RYOS.exe
```

> `build.bat` and `build_cxfreeze.bat` run the same command — cx_Freeze is the only packager and the sole release path.

### 4. Smoke-test the exe — hard gate

A release that crashes on launch is worse than no release, so prove the exe starts before going further. `tests/launch_smoke.py` launches it the way the maintainer needs it launched:

- **Never on the first screen.** The maintainer works there (and may be in a game). With no flag, the app runs on Qt's offscreen platform and no window appears anywhere; `--visible` puts it on the second screen (`tests/smoke_screen.py`), and falls back to the primary only when there is one monitor — so check `smoke_screen()` before using `--visible`. Never launch `RYOS.exe` directly with `Start-Process`: its window opens wherever Windows places it.
- **Throwaway data, no registry writes.** `APPDATA` points at a temp folder, `RYOS_NO_REGISTRY=1` and `RYOS_NO_TOASTS=1`, so no notification pops up and the real database, settings and run-at-login entry are never touched; the smoke fails if anything in the real `%APPDATA%\RYOS` changed.
- **`RYOS_ALLOW_MULTIPLE=1`**, so the maintainer's own running RYOS is neither signalled nor made to swallow the launch. (Without it, the single-instance guard makes the new exe hand off and exit 0 — which looks like a crash. Never "fix" that by killing the maintainer's instance.)
- **It checks the version.** The app logs `RYOS <version> starting`; the smoke fails unless that is the version in `ryos/__init__.py`, which is what proves you are testing the build you just made rather than a stale `dist/`.

Run it twice — offscreen, then on the second screen, which also proves the frozen Windows platform plugin (`qwindows.dll`) loads:

```bash
cd D:/Projects/RYOS && uv run python tests/launch_smoke.py --exe dist/cxfreeze/RYOS.exe
cd D:/Projects/RYOS && uv run python -c "import sys; sys.path.insert(0,'tests'); from smoke_screen import _monitor_work_areas as a; print(len(a()), 'monitor(s)')"
cd D:/Projects/RYOS && uv run python tests/launch_smoke.py --exe dist/cxfreeze/RYOS.exe --visible   # only with 2+ monitors
```

**If either fails, stop and report — do not release.**

Then check the upgrade path on a copy of an older database, if one exists (`%APPDATA%\RYOS\scripts.db.backup-*`, or one the maintainer names). `--db` opens a *copy*; the real file is never opened:

```bash
cd D:/Projects/RYOS && uv run python tests/real_data_smoke.py --db "$APPDATA/RYOS/scripts.db.backup-<date>"
```

It prints the schema step and what changed (`schema: v7 -> v8; pipeline steps 59 -> 0`). A count that drops is a stop until you know why: open another copy with `sqlite3` and confirm the rows were ones the migration is meant to remove (v8's `_migrate_drop_orphans` removes only steps, presets and schedules whose script or pipeline is gone) — and say so in the release notes.

### 5. Package both assets — hard gate

The Windows build zip (the contents of the cx_Freeze folder):

```powershell
Compress-Archive -Force -Path D:\Projects\RYOS\dist\cxfreeze\* -DestinationPath D:\Projects\RYOS\dist\RYOS-windows.zip
```

The portable source zip (everything needed to run from source). Built with Python rather than `Compress-Archive`, which would sweep in every local `__pycache__` (95 stale bytecode files, tripling the zip, in 2.0.0's first attempt):

```bash
cd D:/Projects/RYOS && uv run --no-project python - <<'EOF'
import zipfile
from pathlib import Path
with zipfile.ZipFile("dist/RYOS-portable.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for p in sorted(Path("ryos").rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            z.write(p, p.as_posix())
    for f in ("pyproject.toml", "run.bat", "install_uv.bat", "icon.ico"):
        z.write(f, f)
    names = z.namelist()
missing = [f for f in ("pyproject.toml", "run.bat", "install_uv.bat", "icon.ico",
                       "ryos/__init__.py") if f not in names]
caches = sum("__pycache__" in n for n in names)
print(f"{len(names)} entries; missing {missing or 'nothing'}; {caches} cache files")
raise SystemExit(1 if missing or caches else 0)
EOF
```

Verify the Windows zip carries the exe, and stop if either check fails:

```powershell
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead("D:\Projects\RYOS\dist\RYOS-windows.zip")
$entries = $zip.Entries.Name; $zip.Dispose()
if ($entries -notcontains "RYOS.exe") { Write-Error "RYOS-windows.zip has no RYOS.exe — aborting"; exit 1 }
Write-Output "RYOS-windows.zip verified ($($entries.Count) entries)"
```

### 6. Commit and push the version bump

Tag the published code, so commit the version bump (and any other intended changes) first. Stage deliberately — **never** `dist/`, `build/`, `scripts.db`, or `__pycache__`:

```bash
cd D:/Projects/RYOS && git status
cd D:/Projects/RYOS && git add ryos/__init__.py <other intended files> && git commit -m "Bump version to <X.Y.Z>" && git push
```

### 7. Create the GitHub release

Only once CI is green on the version-bump commit (`gh run watch <id> --exit-status`). Write the notes to a file in the scratchpad rather than quoting them on the command line, where backticks and `$` get mangled:

```bash
cd D:/Projects/RYOS && gh release create v<X.Y.Z> dist/RYOS-windows.zip dist/RYOS-portable.zip \
  -R lqvu-zen/RYOS --target main --title "v<X.Y.Z>" --notes-file <notes.md> 2>&1
```

Include the download guidance in the notes so users know which asset to grab:

```
<user-approved notes>

## Downloads
- **RYOS-windows.zip** — Windows build; extract and run `RYOS.exe` inside.
- **RYOS-portable.zip** — run from source; extract and double-click `run.bat` (needs uv; run `install_uv.bat` first if needed).
```

### 8. Clear `dist/`

The zips are on GitHub now; stale builds left in `dist/` are how an old exe gets smoke-tested or attached next time:

```bash
cd D:/Projects/RYOS && rm -rf dist/* build
```

### 9. Report

Give the user the release URL (`gh` prints it), the version shipped, the two assets attached, and a one-line confirmation that the smoke test and zip checks passed. Note anything you skipped or that needs follow-up.
