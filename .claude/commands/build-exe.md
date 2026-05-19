Rebuild dist/RYOS.exe from the latest source using PyInstaller.

Run this command:

```bash
cd D:/Projects/RYOS && uv run --with pyinstaller pyinstaller RYOS.spec --noconfirm 2>&1
```

After the build completes, confirm the output by checking the file size of `dist/RYOS.exe` and report whether the build succeeded or failed.
