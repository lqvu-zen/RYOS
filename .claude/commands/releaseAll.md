Create a new GitHub release for RYOS with two assets: the standalone exe and a portable zip for running from source.

## Steps

1. Get the latest version tag from https://github.com/lqvu-zen/RYOS/releases and ask the user for the next version tag (e.g. `v1.2.0`) and release notes if not provided.

2. Rebuild the exe with the latest changes:
```bash
cd D:/Projects/RYOS && uv run --with pyinstaller pyinstaller RYOS.spec --noconfirm 2>&1
```

3. Verify the build succeeded:
```bash
ls -lh D:/Projects/RYOS/dist/RYOS.exe
```

4. Create the portable source zip (`RYOS-portable.zip`) containing everything needed to run from Python/batch:
```bash
cd D:/Projects/RYOS && powershell -Command "
  Compress-Archive -Force -Path script_runner.py, run.bat, install_uv.bat, icon.ico -DestinationPath dist/RYOS-portable.zip
" 2>&1
```

Verify the zip was created:
```bash
ls -lh D:/Projects/RYOS/dist/RYOS-portable.zip
```

5. Commit and push any uncommitted changes before tagging:
```bash
cd D:/Projects/RYOS && git status 2>&1
```
If there are uncommitted changes, stage and commit them before proceeding.

6. Create the GitHub release with both assets attached:
```bash
cd D:/Projects/RYOS && gh release create <version> dist/RYOS.exe dist/RYOS-portable.zip \
  --title "<version>" \
  --notes "<release notes>" 2>&1
```

The release notes should briefly describe both download options, for example:

```
<user-provided notes>

## Downloads
- **RYOS.exe** — standalone executable, no installation needed
- **RYOS-portable.zip** — run from source with Python; extract and double-click `run.bat` (requires [uv](https://docs.astral.sh/uv/), run `install_uv.bat` first if needed)
```

7. Report the release URL back to the user.
