# RYOS Tutorial — v1.7.6

**RYOS (Run Your Own Scripts)** is a lightweight desktop app for saving and running scripts with a single click. No terminal, no memorizing paths — just click ▶.

> A page-by-page user guide with screenshot slots also lives in [`docs/tutorial/`](docs/tutorial/README.md).

---

## Installation

### Option A — Standalone executable
Download `RYOS.exe` and double-click it. No installation required.

### Option B — Portable (run from source)
1. Download and extract `RYOS-portable.zip`.
2. If you don't have [uv](https://docs.astral.sh/uv/) installed, double-click `install_uv.bat` once.
3. Double-click `run.bat` to launch.

> **Note:** RYOS stores your data (`scripts.db`, `settings.json`, and logs) in `%APPDATA%\RYOS` on Windows (or `~/.local/share/RYOS` elsewhere). If an older version kept these files next to the executable, RYOS migrates them automatically on first launch.

---

## The Main Window

```
┌──────────────────────────────────────────────────────────────┐
│  ⚡ RYOS              [⚙] [+ Pipeline] [+ Group] [+ Script]   │  ← Header
├──────────────────────────────────────────────────────────────┤
│  [Work] [Personal] [+]                                 [All]  │  ← Group tabs
├──────────────────────────────────────────────────────────────┤
│  📁 D:/scripts                                          [⚡]   │  ← Quick Run bar
├──────────────────────────────────────────────────────────────┤
│  ▼ RUNNING   No script is currently running.                  │
│  ▼ PIPELINES                                                  │
│  ┌────────────────────────────────────────────┐  ⚙   ▶       │  ← Pipeline card
│  │ ⚡ PIPELINE  Deploy · 3 steps               │              │
│  └────────────────────────────────────────────┘              │
│  ▼ SCRIPTS                                                    │
│  ┌────────────────────────────────────────────┐  ⚙   ▶       │  ← Script card
│  │ Python  Backup DB   ✓ OK                    │              │
│  └────────────────────────────────────────────┘              │
├──────────────────────────────────────────────────────────────┤
│  Output                         Close All · Clear · Show Output│  ← Output bar
└──────────────────────────────────────────────────────────────┘
```

The **header** holds the ⚡ RYOS logo on the left and four controls on the right:

| Control | What it does |
|---|---|
| **⚙** | Opens the **Options** menu (Select scripts · Export all groups · Import config · Advanced options… · Check for updates · Delete All). |
| **+ Pipeline** | Create a new pipeline. |
| **+ Group** | Create a new group (tab). |
| **+ Script** | Add a new script card. |

> The add buttons live in the header. (Earlier versions filed them under an "Options ▾" menu; they're now header buttons, and the ⚙ icon is the Options menu.)

---

## Groups

Groups are tabs at the top of the window for organising scripts and pipelines. Each group can also have a **base directory** that powers the Quick Run bar.

| Action | How |
|---|---|
| Create a group | Click **+ Group** in the header, or **+** in the tab bar |
| Switch group | Click its tab |
| See all groups at once | Click **All** on the right of the tab row |
| Rename a group | Right-click the tab → **Rename** |
| Clone a group | Right-click the tab → **Clone Group** |
| Set a base directory | Right-click the tab → **Base directory…** |
| Export a group's config | Right-click the tab → **Export group** |
| Delete a group | Right-click the tab → **Delete Group** |
| Move a script between groups | Drag its card onto another group's tab |

---

## Scripts

### Adding a script
1. Click **+ Script** in the header, or drag a script file directly onto the window.
2. Fill in:
   - **Name** — a friendly label shown on the card.
   - **Base dir** — the group's base folder (shown for reference); picked paths are relative to it.
   - **Path** — path to your script (`.py`, `.bat`, `.cmd`, `.sh`, `.ps1`, etc.). Click **Browse…** or drag a file onto the window.
   - **Parameters** *(optional)* — command-line arguments passed every run; supports quoting.
   - **+ Preset** *(optional)* — save the current Parameters as a named **preset**.
   - **Interpreter** *(optional)* — leave blank for auto-detection, or pick/enter one (e.g. `python`, `node`).
   - **Group** — which group to save the script under.
   - **Ask for a temporary parameter on each run (not saved)** — prompt for one-off arguments every run (adds a **TEMP PARAM** badge to the card).
3. Click **Save**.

### The script card

```
┌───────────────────────────────────────────────┬───┬───┐
│  Python   Backup DB                            │ ⚙ │ ▶ │
│  backup.py · Last run 14:32 · ✓ OK             │   │   │
└───────────────────────────────────────────────┴───┴───┘
```

| Button | Action |
|---|---|
| **⚙** | Edit the script (name, path, params, interpreter). |
| **▶** | Run the script (the green button). |
| **⏹** | Stop the running script (active while a run is in progress). |

Each card shows a type badge (e.g. **Python**), the file name, the last-run time, and a green **✓ OK** or red **✗ Failed** badge. Right-click a card for more options such as **Edit**, **Clone**, and **Delete**.

### Reordering scripts
Drag a script card up or down to reorder it within the group. Drag it onto a different group tab to move it there.

### Parameters, presets & prompts
- **Fixed parameters** — type arguments into the **Parameters** field; they're passed every run. Quoting works, so `--name "My File"` is one value.
- **Presets** — save several named argument sets with **+ Preset**; pick one from the card's dropdown at run time.
- **Temporary parameters** — tick **"Ask for a temporary parameter on each run (not saved)"**. The card gets a **TEMP PARAM** badge, and each run opens a **Run with temp param** box. What you type is used for that run only and appended to any saved parameters.

---

## Pipelines

A pipeline runs a sequence of scripts one after another, stopping if any step fails.

### Creating a pipeline
1. Click **+ Pipeline** in the header.
2. Enter a name and confirm.
3. The pipeline editor opens automatically.

### Editing a pipeline
Click **⚙** on a pipeline card (or right-click → **Edit**) to open the **Edit Pipeline** dialog. In the editor:
- Pick a script from the **Add Step** dropdown and click **Add**.
- Select a step and use **▲ Up** / **▼ Down** to reorder, or **✕ Remove** to delete it.
- Use **Step preset** to choose which saved preset a step runs with.
- Click **Save** when done.

### Running a pipeline
Click **▶** on the pipeline card. The output panel shows each step's progress (*Step 1/N*, *Step 2/N*, …). If a step fails, the pipeline stops. Click **⏹** to abort at any point.

### Cloning a pipeline
Right-click a pipeline card → **Clone** to create an exact copy including all steps.

---

## Output Panel

The output panel appears at the bottom and shows what your scripts printed. Click the **Output** bar (or **Show Output**) to expand it.

- **Per-run tabs** — one tab per recent run (named after the script), plus an **All** tab. Each tab has an **✕** to close it.
- **Command line** — the exact command RYOS ran, shown in blue, including the interpreter and any parameters.
- **Output** — the program's `stdout`; anything on `stderr` appears in **red**.
- **Summary** — a green line such as `exit code 0` with the finish time.

| Control | Action |
|---|---|
| **Close All** | Close every run tab and clear the view. |
| **Clear** | Clear the current run's text. |
| **Hide Output** / **Show Output** | Collapse or expand the panel. |

The status line at the bottom of the window (*Ready.* / *Done.*) reflects the app's current state.

---

## Drag and Drop

- **Files onto the window** — drops a script file and pre-fills the Add Script dialog.
- **Cards within the list** — drag to reorder.
- **Cards onto a group tab** — moves the script or pipeline to that group.

---

## Select Mode (Bulk Delete)

1. Click **⚙** → **Select scripts**.
2. Tick the checkboxes on the cards you want to remove.
3. Click **Delete selected** in the bar that appears, or **Select all** to tick everything.
4. Exit the mode to cancel without deleting.

---

## Import & Export

### Export
- **All groups:** Click **⚙** → **Export all groups** — saves a `.json` file with every group, script, and pipeline.
- **Single group:** Right-click its tab → **Export group**.

### Import
Click **⚙** → **Import config**, then choose:
- **Replace** — replaces scripts in the groups found in the file; leaves other groups untouched.
- **Merge** — adds new scripts, skips any whose file path already exists in the group.

---

## Advanced Options

Click **⚙** → **Advanced options…**. Settings are split across five tabs.

### Appearance
| Setting | Description |
|---|---|
| **Theme** | Choose **Light** or **Dark** (the bundled themes), an imported theme from the gallery, or a custom theme; re-themes live |
| **Create / Edit / Delete theme** | Build a custom theme in the editor — pick a light/dark base + 7 core colours (with live preview and contrast warnings), plus an optional Advanced section for ~12 more; edit or delete your own themes |
| **Export / Import theme** | Save a custom theme to a `.json` file or load one back, for sharing |
| **Accent colour** | Pick a custom highlight colour, or reset to the default |
| **Compact cards** | Tighter spacing to fit more cards on screen |
| **Card size** | Small / Medium / Large card rows |

### Startup
| Setting | Description |
|---|---|
| **Start with Windows** | Adds RYOS to the Windows startup registry key |
| **Always on top** | RYOS floats above other windows |
| **Remember last active group** | Reopen on the group you used last |
| **Start minimized** | Window starts hidden in the taskbar |
| **Check for updates on startup** | Compare against the latest GitHub release |
| **Remember window size and position** | Restores size and position from last session |
| **Open on the screen where the cursor is** | Manual launches open on the monitor under the mouse (carrying over the remembered position); login launches restore the last screen. Off = always restore the last screen |
| **Window size** | Set a fixed width × height in pixels |
| **Snap to screen corner** | Auto-positions the window in a screen corner of the monitor it opens on — Bottom right / Bottom left / Top right / Top left / Off |

### Output
| Setting | Description |
|---|---|
| **Auto-clear output before each run** | Clears the log each time a new script starts |
| **Auto-scroll to bottom** | Keeps the latest output in view |
| **Notify when script / pipeline completes** | Windows notification on completion |
| **Max output lines** | Truncates old output to keep the log fast |
| **Max parallel jobs (0 = unlimited)** | How many scripts may run at once |

### Quick Run
| Setting | Description |
|---|---|
| **Show Quick Run bar** | Toggle the bar (requires a group base directory) |
| **Show suggestions as you type** | Suggest matching filenames as you type |
| **Index file types** | Which file extensions the Quick Run index includes (empty = index everything) |
| **Index max files** | Cap on how many files are indexed (0 = unlimited) |
| **Clear index cache** | Rebuild the file index from scratch |

### Logging
| Setting | Description |
|---|---|
| **Logging** | Turn the app's diagnostic log on or off |
| **Log level** | How much detail to record |
| **Log run output** | Also record each run's output to the log |

---

## Tips

- **Collapsible sections** — click the **▼ RUNNING / PIPELINES / SCRIPTS** headers to fold sections you rarely use.
- **Last-run status** — cards show the time of the last run and a **✓ OK** or **✗ Failed** badge.
- **Auto-interpreter** — RYOS detects the right interpreter from the file extension (`.py` → `python`, `.bat` → `cmd`, `.ps1` → `powershell`, `.sh` → `bash`, etc.). Override in the script's **Interpreter** field.
- **Presets vs. temp params** — save reusable argument sets as **presets**; use the **TEMP PARAM** prompt for one-off values.
- **Back up your setup** — **⚙ → Export all groups** saves everything to a `.json` you can re-import later or on another machine.
