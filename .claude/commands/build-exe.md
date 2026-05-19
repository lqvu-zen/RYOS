Rebuild dist/ScriptRunner.exe from the latest source using PyInstaller.

Run this command:

```bash
cd D:/Projects/RYOS && uv run --with pyinstaller pyinstaller ScriptRunner.spec --noconfirm 2>&1
```

After the build completes, confirm the output by checking the file size of `dist/ScriptRunner.exe` and report whether the build succeeded or failed.
