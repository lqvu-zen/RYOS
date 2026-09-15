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

```bash
cd D:/Projects/RYOS && uv run --with cx_Freeze --with tkinterdnd2 python setup_cxfreeze.py build_exe 2>&1
```

This writes `dist/cxfreeze/` with `RYOS.exe` and its DLLs. Confirm it exists and stop if it doesn't:

```bash
ls -lh D:/Projects/RYOS/dist/cxfreeze/RYOS.exe
```

> `build.bat` and `build_cxfreeze.bat` run the same command — cx_Freeze is the only packager and the sole release path.

### 4. Smoke-test the exe — hard gate

A release that crashes on launch is worse than no release, so prove the exe starts before going further. Launch it, wait, confirm it's still alive **and showing the version you just built**, then kill it.

Two details matter, and both have bitten a real release:

- **`RYOS_ALLOW_MULTIPLE=1` is required.** The maintainer usually has their own RYOS open while releasing. Without this, the single-instance guard (`ryos/single_instance.py`) makes the new exe hand off to the running one and **exit cleanly with code 0** — which looks exactly like a crash to the check below, and aborts a perfectly good release. Never "fix" this by killing the maintainer's running instance; set the variable, which the guard explicitly honours.
- **Check the window title.** A build that silently reused a stale `dist/cxfreeze` would pass a liveness-only check. The title carries `__version__`, so asserting on it proves you are testing the build you just made, and that the GUI actually came up rather than the process merely surviving.
- **`$proc.Refresh()` before reading `MainWindowTitle`.** The property is cached on the `Process` object from when it was created, so without a refresh it reads empty however long you sleep — which looks like a stale build and aborts a good release. Poll rather than sleeping a fixed time: the window appears in well under a second.

```powershell
$env:RYOS_ALLOW_MULTIPLE = "1"     # don't hand off to an already-running RYOS
$expected = "<X.Y.Z>"              # the version set in step 2
$proc = Start-Process -FilePath "D:\Projects\RYOS\dist\cxfreeze\RYOS.exe" -PassThru
$title = ""
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    if ($proc.HasExited) { break }
    $proc.Refresh()                # MainWindowTitle is cached without this
    if ($proc.MainWindowTitle) { $title = $proc.MainWindowTitle; break }
}
if ($proc.HasExited) {
    Write-Error "RYOS.exe exited immediately (exit code $($proc.ExitCode)) — aborting release"
    exit 1
}
Write-Output ("still alive; main window title: " + $title)
if ($title -notlike "*$expected*") {
    $proc.Kill()
    Write-Error "window title does not show $expected — stale build? aborting"
    exit 1
}
Start-Sleep -Seconds 5             # and it must still be up a few seconds later
$proc.Refresh()
if ($proc.HasExited) {
    Write-Error "RYOS.exe died after opening its window — aborting release"
    exit 1
}
$proc.Kill()
Remove-Item Env:\RYOS_ALLOW_MULTIPLE
Write-Output "RYOS.exe smoke test passed"
```

**If the exe exits early, or the title doesn't carry the expected version, stop and report — do not release.**

If it does exit immediately, check `%APPDATA%\RYOS\logs\ryos.log` before concluding the build is broken: `"Another RYOS instance is already running; exiting"` means the guard fired and the variable above wasn't set, not that anything is wrong with the exe.

### 5. Package both assets — hard gate

The Windows build zip (the contents of the cx_Freeze folder):

```powershell
Compress-Archive -Force -Path D:\Projects\RYOS\dist\cxfreeze\* -DestinationPath D:\Projects\RYOS\dist\RYOS-windows.zip
```

The portable source zip (everything needed to run from source):

```bash
cd D:/Projects/RYOS && powershell -Command "Compress-Archive -Force -Path ryos, pyproject.toml, run.bat, install_uv.bat, icon.ico -DestinationPath dist/RYOS-portable.zip" 2>&1
```

Verify the portable zip actually contains the required files, and stop if any are missing:

```powershell
$zip = [System.IO.Compression.ZipFile]::OpenRead("D:\Projects\RYOS\dist\RYOS-portable.zip")
$entries = $zip.Entries.Name; $zip.Dispose()
$missing = @("pyproject.toml","run.bat","install_uv.bat","icon.ico") | Where-Object { $entries -notcontains $_ }
if ($missing) { Write-Error "RYOS-portable.zip missing: $($missing -join ', ') — aborting"; exit 1 }
Write-Output "RYOS-portable.zip verified"
```

### 6. Commit and push the version bump

Tag the published code, so commit the version bump (and any other intended changes) first. Stage deliberately — **never** `dist/`, `build/`, `scripts.db`, or `__pycache__`:

```bash
cd D:/Projects/RYOS && git status
cd D:/Projects/RYOS && git add ryos/__init__.py <other intended files> && git commit -m "Bump version to <X.Y.Z>" && git push
```

### 7. Create the GitHub release

```bash
cd D:/Projects/RYOS && gh release create v<X.Y.Z> dist/RYOS-windows.zip dist/RYOS-portable.zip \
  --title "v<X.Y.Z>" \
  --notes "<release notes>" 2>&1
```

Include the download guidance in the notes so users know which asset to grab:

```
<user-approved notes>

## Downloads
- **RYOS-windows.zip** — Windows build; extract and run `RYOS.exe` inside.
- **RYOS-portable.zip** — run from source; extract and double-click `run.bat` (needs uv; run `install_uv.bat` first if needed).
```

### 8. Report

Give the user the release URL (`gh` prints it), the version shipped, the two assets attached, and a one-line confirmation that the smoke test and zip checks passed. Note anything you skipped or that needs follow-up.
