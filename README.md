# RYOS — Run Your Own Scripts

A desktop app for saving and running scripts from a clean card-based UI. Supports Python, Node.js, Bash, PowerShell, Batch, and any other executable.

---

## Getting Started

**Run the standalone exe** (no Python needed):
```
RYOS.exe
```

**Run from source** (requires [uv](https://docs.astral.sh/uv/getting-started/installation/)):
```bash
run.bat
```

---

## How to Use

### Adding a Script

Click **+ Add Script** in the top-right corner. Fill in:

| Field | Description |
|-------|-------------|
| **Name** | Display name shown on the card |
| **Path** | Full path to the script file (e.g. `C:\scripts\backup.py`) |
| **Interpreter** | Leave blank to auto-detect from extension, or enter a custom command (e.g. `python -u`, `node`) |
| **Parameters** | Arguments passed to the script on each run (e.g. `--verbose output.txt`) |

Click **Save** to add it to your list.

### Running a Script

Click **Run** on any card. The script executes immediately in the background.

- The card's **last run time** updates after each execution.
- To see output, click **Show Output** at the bottom of the window.
- To stop a running script, click **Stop** in the output panel header.

### Output Panel

The output panel sits at the bottom of the window and is hidden by default.

- Click **Show Output / Hide Output** to toggle it.
- Drag the **divider** between the card list and the output panel to resize it.
- **stdout** appears in the default color; **stderr** appears in red.
- Use **Copy** to copy the full log to clipboard.
- Use **Clear** to wipe the log.

### Editing a Script

Click **Modify** on a card to change its name, path, interpreter, or parameters. Click **Save** to apply.

### Reordering Scripts

Use the **↑** and **↓** arrows on each card to move it up or down in the list.

### Deleting Scripts

**Single script** — click **Modify**, then **Delete** in the edit dialog.

**Multiple scripts** — open **Options → Select scripts**, check the cards you want to remove, then click **Delete Selected**.

**All scripts** — open **Options → Delete All**.

### Export / Import

Use **Options → Export config** to save your script list as a JSON file.

Use **Options → Import config** to restore from a JSON file. You can choose to:
- **Merge** — add imported scripts while keeping existing ones (duplicates are skipped)
- **Replace** — clear the current list and load the imported scripts

---

## Supported Script Types

| Extension | Interpreter |
|-----------|-------------|
| `.py` | Python |
| `.js` | node |
| `.ts` | ts-node |
| `.sh` | bash |
| `.ps1` | powershell |
| `.rb` | ruby |
| `.pl` | perl |
| `.php` | php |
| `.bat` `.cmd` `.exe` | direct |

Leave **Interpreter** blank for auto-detection, or type any custom command.

---

## Building the Executable

```bash
build.bat
# or:
uv run --with nuitka --with tkinterdnd2 python -m nuitka --onefile --python-flag=-m --assume-yes-for-downloads --msvc=latest --windows-console-mode=disable --windows-icon-from-ico=icon.ico --enable-plugin=tk-inter --include-package=tkinterdnd2 --include-package-data=tkinterdnd2 --include-data-files=icon.ico=icon.ico --output-filename=RYOS.exe --output-dir=dist --remove-output ryos
```

Output: `dist/RYOS.exe` — single file, no dependencies on the target machine. The database (`scripts.db`) is created next to the exe on first run. Requires MSVC (Visual Studio Build Tools 2022); the first build is slower than PyInstaller, subsequent builds are faster thanks to Nuitka's cache.
