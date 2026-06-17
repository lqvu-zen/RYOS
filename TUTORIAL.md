# RYOS Tutorial — v1.7.5

**RYOS (Run Your Own Scripts)** is a lightweight desktop app for saving and running scripts with a single click. No terminal, no memorizing paths — just click ▶.

---

## Installation

### Option A — Standalone executable
Download `RYOS.exe` and double-click it. No installation required.

### Option B — Portable (run from source)
1. Download and extract `RYOS-portable.zip`.
2. If you don't have [uv](https://docs.astral.sh/uv/) installed, double-click `install_uv.bat` once.
3. Double-click `run.bat` to launch.

> **Note:** Both options store `scripts.db` and `settings.json` next to the executable / `run.bat`. Move these files together to keep your data.

---

## The Main Window

```
┌─────────────────────────────────────────────────────┐
│  [Work] [Personal] [+]          [Options ▾]         │  ← Group tabs
├─────────────────────────────────────────────────────┤
│  ▸ Pipelines                                        │  ← Collapsible section
│  ┌──────────────────────────────────────────────┐   │
│  │ ⚡ PIPELINE  Deploy                 │⚙│▶│⏹│  │   │  ← Pipeline card
│  └──────────────────────────────────────────────┘   │
│  ▸ Scripts                                          │  ← Collapsible section
│  ┌──────────────────────────────────────────────┐   │
│  │ 🐍 PY  Backup DB                   │⚙│▶│⏹│  │   │  ← Script card
│  └──────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────┤
│  ▸ Output — Backup DB                               │  ← Output panel
└─────────────────────────────────────────────────────┘
```

---

## Groups

Groups are tabs at the top of the window for organising scripts and pipelines.

| Action | How |
|---|---|
| Create a group | Click **+** in the tab bar |
| Switch group | Click its tab |
| Rename a group | Right-click the tab → **Rename** |
| Delete a group | Right-click the tab → **Delete Group** |
| Reorder groups | Drag a tab left or right |
| Export a group's config | Right-click the tab → **Export group** |

---

## Scripts

### Adding a script
1. Click **Options ▾** → **Add script**, or drag a script file directly onto the window.
2. Fill in:
   - **Name** — a friendly label shown on the card.
   - **File path** — path to your script (`.py`, `.bat`, `.sh`, `.ps1`, etc.). Click **Browse** or drag a file onto the field.
   - **Parameters** *(optional)* — command-line arguments, supports quoting and `"$input"` prompts.
   - **Custom interpreter** *(optional)* — overrides auto-detection (e.g. `python3.11`, `node`).
   - **Group** — which group to save the script under.
3. Click **Save**.

### The script card

```
┌─────────────────────────────────────────┬───┬───┬───┐
│ ■  🐍 PY  ▶ RUNNING                     │ ⚙ │ ▶ │ ⏹ │
│    Backup DB                            │   │   │   │
│    C:\scripts\backup.py                 │   │   │   │
│    Last run: 14:32  ✓ OK               │   │   │   │
└─────────────────────────────────────────┴───┴───┴───┘
```

| Button | Action |
|---|---|
| **⚙** | Edit the script (name, path, params, interpreter) |
| **▶** | Run the script |
| **⏹** | Stop the running script (red when active, gray when idle) |

Right-click a card for more options: **Edit**, **Clone**, **Delete**, **Move to top**.

### Reordering scripts
Drag a script card up or down to reorder it within the group. Drag it onto a different group tab to move it there.

### Parameters & prompts
In the **Parameters** field, wrap a token in double-quotes with a `$` prefix to get a popup prompt at run time:

```
--output "$output_folder" --verbose
```

When you click ▶, RYOS will ask you for the value of `output_folder` before running.

### Parameter presets
For a script you run with different arguments, save named **presets** instead of editing the card each time. In the Add/Edit Script dialog, save the current Parameters as a named preset; at run time, pick the preset you want. This keeps a single card flexible across several common argument sets.

---

## Pipelines

A pipeline runs a sequence of scripts one after another, stopping if any step fails.

### Creating a pipeline
1. Click **Options ▾** → **Add pipeline**.
2. Enter a name and click **OK**.
3. The pipeline editor opens automatically.

### Editing a pipeline
Click **⚙** on a pipeline card (or right-click → **Edit**).

In the editor:
- Click **+ Add step** to pick a script from the current group.
- Select a step and click **↑ / ↓** to reorder, or **✕ Remove** to delete it.
- Click **Save** when done.

### Running a pipeline
Click **▶** on the pipeline card. The output panel shows each step's progress.

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚡  Deploy  ·  3 steps
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
────────────────────────────────────────
Step 1/3:  Build
────────────────────────────────────────
...
```

Click **⏹** to abort the pipeline at any point.

### Cloning a pipeline
Right-click a pipeline card → **Clone** to create an exact copy including all steps.

---

## Output Panel

The output panel appears at the bottom and shows stdout/stderr from the last run.

| Control | Action |
|---|---|
| Click the **▸ Output** header | Expand / collapse the panel |
| **💾** | Save the log to a `.txt` file |
| **⎘** | Copy the entire log to clipboard |
| **🗑** | Clear the log |

Output is colour-coded: normal text, **stderr** in red, status lines in blue, success summary in green.

---

## Drag and Drop

- **Files onto the window** — drops a script file and pre-fills the Add Script dialog.
- **Cards within the list** — drag to reorder.
- **Cards onto a group tab** — moves the script or pipeline to that group.

---

## Select Mode (Bulk Delete)

1. Click **Options ▾** → **Select scripts**.
2. Tick the checkboxes on the cards you want to remove.
3. Click **Delete selected** in the bar that appears, or **Select all** to tick everything.
4. Click **✕ Cancel select** (or the same menu entry) to exit without deleting.

---

## Import & Export

### Export
- **All groups:** Click **Options ▾** → **Export config** — saves a `.json` file with every group, script, and pipeline.
- **Single group:** Right-click its tab → **Export group**.

### Import
Click **Options ▾** → **Import config**, then choose:
- **Yes (Replace)** — replaces scripts in the groups found in the file; leaves other groups untouched.
- **No (Merge)** — adds new scripts, skips any whose file path already exists in the group.

---

## Advanced Options

Click **Options ▾** → **Advanced options**.

### Startup
| Setting | Description |
|---|---|
| **Start with Windows** | Adds RYOS to the Windows startup registry key |
| **Start minimized** | Window starts hidden in the taskbar |

### Window
| Setting | Description |
|---|---|
| **Always on top** | RYOS floats above other windows |
| **Snap to corner** | Auto-positions the window in a screen corner on launch — Bottom right / Bottom left / Top right / Top left / Off |
| **Window size** | Set a fixed width × height in pixels |
| **Remember window position and size** | Restores size and position from last session |

### Output
| Setting | Description |
|---|---|
| **Max output lines** | Truncates old output to keep the log fast (default 2000) |
| **Auto-clear output on run** | Clears the log each time a new script starts |
| **Auto-scroll to bottom** | Keeps the latest output in view |

### Appearance
| Setting | Description |
|---|---|
| **Theme** | Light or dark colour scheme |
| **Accent colour** | Pick a custom highlight colour, or reset to the default |
| **Compact mode** | Tighter spacing to fit more cards on screen |
| **Card size** | Small / medium / large card rows |

### Quick Run
| Setting | Description |
|---|---|
| **Show Quick Run bar** | Toggle the bar (requires a group base directory) |
| **Autocomplete** | Suggest matching filenames as you type |
| **Indexed extensions** | Which file types the Quick Run index includes |
| **Clear index cache** | Rebuild the file index for a base directory |

### Notifications & updates
| Setting | Description |
|---|---|
| **Notify when script / pipeline completes** | Windows toast on completion |
| **Check for updates on startup** | Compare against the latest GitHub release |

---

## Tips

- **Collapsible sections** — click the **▸ Pipelines** or **▸ Scripts** header to collapse a section you rarely use.
- **Long names** — script and pipeline names scroll automatically on the card if they're too long to fit.
- **Last run status** — cards show the time of the last run and a **✓ OK** or **✕ Failed** badge.
- **No blink** — clicking ▶ or ⏹ updates the card in-place; the list never rebuilds mid-run.
- **Auto-interpreter** — RYOS detects the right interpreter from the file extension (`.py` → `python`, `.bat` → `cmd`, `.ps1` → `powershell`, `.sh` → `bash`, etc.). Override in the script's **Custom interpreter** field.
