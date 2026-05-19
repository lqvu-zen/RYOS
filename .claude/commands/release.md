Create a new GitHub release for RYOS.

## Steps

1. Ask the user for the version tag (e.g. `v1.1.0`) and release notes if not provided.

2. Rebuild the exe with the latest changes:
```bash
cd D:/Projects/RYOS && uv run --with pyinstaller pyinstaller RYOS.spec --noconfirm 2>&1
```

3. Verify the build succeeded:
```bash
ls -lh D:/Projects/RYOS/dist/RYOS.exe
```

4. Commit and push any uncommitted changes before tagging:
```bash
cd D:/Projects/RYOS && git status 2>&1
```

5. Create the GitHub release with the exe attached:
```bash
cd D:/Projects/RYOS && gh release create <version> dist/RYOS.exe --title "<version>" --notes "<release notes>" 2>&1
```

6. Report the release URL back to the user.
