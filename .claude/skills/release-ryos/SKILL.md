---
name: release-ryos
description: 'Cut a new GitHub release of the RYOS desktop app — bump the version, build the Windows exe, smoke-test it, package the download zips, tag, and publish. Use this whenever the user wants to ship RYOS: "cut a release", "release v1.6.5", "publish a new version", "ship it", "build the exe and put it on GitHub", "make a new build", or "tag a release". Also use it when the user has finished a batch of features/fixes and says it''s time to get them out to users. This skill carries the exact version scheme, the cx_Freeze build command, the exe smoke-test gate, the windows + portable zip packaging, and the gh release steps, so the process is repeatable and safe. It runs on Windows with uv and an authenticated gh CLI. Do NOT use it to write features (use add-ryos-feature), fix bugs (use fix-ryos-bug), or just launch the app locally (use run-ryos).'
---

# Releasing RYOS

RYOS ships as a GitHub release with two downloadable assets: **`RYOS-windows.zip`** (the frozen `RYOS.exe` plus its DLLs, for users who just want to run it) and **`RYOS-portable.zip`** (the source, for users who run it from Python via `run.bat`). The release is tagged in the repo `lqvu-zen/RYOS`, and the app's built-in update check (`ryos/notifications.py`) compares the running `__version__` against the latest GitHub tag — so the tag, the assets, and `__version__` must all line up.

Releasing is **not a design problem** — it's a deterministic runbook, so unlike `add-ryos-feature` and `fix-ryos-bug` there are no design/review subagents here. You run it inline. The safety comes from **hard gates**: the build must succeed, the exe must survive a smoke test, and both zips must contain the expected files — stop and report at any gate that fails rather than publishing a broken release. (Drafting release notes from the commit log is the one step you may hand to a cheap Haiku/Sonnet subagent if you like; everything else is yours.)

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

### 1. Decide the version and notes

Check the latest published tag (`gh release list -R lqvu-zen/RYOS -L 5` or the releases page) and confirm the next version with the user — patch for fixes, minor for notable features, based on the last released version. Gather release notes; if the user didn't give any, draft them from `git log <last-tag>..HEAD --oneline` and show them for approval. Don't invent a version or notes silently.

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

A release that crashes on launch is worse than no release, so prove the exe starts before going further. Launch it, wait 4 seconds, confirm it's still alive, then kill it:

```powershell
$proc = Start-Process -FilePath "D:\Projects\RYOS\dist\cxfreeze\RYOS.exe" -PassThru
Start-Sleep -Seconds 4
if ($proc.HasExited) {
    Write-Error "RYOS.exe exited immediately (exit code $($proc.ExitCode)) — aborting release"
    exit 1
}
$proc.Kill()
Write-Output "RYOS.exe smoke test passed"
```

**If the exe exits before the 4-second mark, stop and report — do not release.**

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
