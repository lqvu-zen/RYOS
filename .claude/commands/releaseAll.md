Create a new GitHub release for RYOS with two assets: the standalone exe and a portable zip for running from source.

## Steps

1. Get the latest version tag from https://github.com/lqvu-zen/RYOS/releases and ask the user for the next version tag (e.g. `v1.2.0`) and release notes if not provided.

2. Update `__version__` in `ryos/__init__.py` to match the new version tag (without the `v` prefix):
```bash
cd D:/Projects/RYOS && grep -n "__version__" ryos/__init__.py 2>&1
```
Edit the line so it reads `__version__ = "<new_version>"` (e.g. `"1.2.0"`).

3. Rebuild the exe with the latest changes:
```bash
cd D:/Projects/RYOS && uv run --with nuitka --with tkinterdnd2 python -m nuitka --onefile --python-flag=-m --assume-yes-for-downloads --msvc=latest --windows-console-mode=disable --windows-icon-from-ico=icon.ico --enable-plugin=tk-inter --include-package=tkinterdnd2 --include-package-data=tkinterdnd2 --include-data-files=icon.ico=icon.ico --output-filename=RYOS.exe --output-dir=dist --remove-output ryos 2>&1
```

4. Verify the build succeeded:
```bash
ls -lh D:/Projects/RYOS/dist/RYOS.exe
```

5. Create the portable source zip (`RYOS-portable.zip`) containing everything needed to run from Python/batch:
```bash
cd D:/Projects/RYOS && powershell -Command "
  Compress-Archive -Force -Path ryos, pyproject.toml, run.bat, install_uv.bat, icon.ico -DestinationPath dist/RYOS-portable.zip
" 2>&1
```

Verify the zip was created:
```bash
ls -lh D:/Projects/RYOS/dist/RYOS-portable.zip
```

6. Commit and push the version bump (and any other uncommitted changes) before tagging:
```bash
cd D:/Projects/RYOS && git status 2>&1
```
Stage `ryos/__init__.py` (plus any other modified files) and commit with message `Bump version to <new_version>`, then push.

7. Create the GitHub release with both assets attached:
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

8. After the release is published, bump `__version__` in `ryos/__init__.py` to the next patch dev version (e.g. `"1.2.1-dev"`) so the in-tree version is always ahead of the last release. Commit with message `Begin <next_version> development` and push.

9. Report the release URL back to the user.
