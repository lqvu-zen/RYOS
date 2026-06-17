# RYOS Screen Map

A working map of every screen the end-user tutorial covers: how to reach it, what to
capture, and the example data to use. This reflects the build at the time of writing.

**The live screen always wins.** RYOS's UI moves faster than this file. If what you see
disagrees with what's written here, document what's on screen and note the difference for
the user. Re-read the actual labels on each screenshot before writing the step.

## Window regions (for the "Main window" tour)

Top to bottom, the main window has:

- **Group tabs** across the top — one tab per group, plus a **+** to add a group, and an
  **Options ▾** menu on the right.
- **Header buttons** (right side of the tab row): **+ Script**, **+ Group**, **+ Pipeline**.
  These are the primary "add" actions. (The old TUTORIAL.md wrongly files these under
  Options ▾ — verify on screen.)
- **Collapsible sections**: a **▸ Pipelines** section and a **▸ Scripts** section. Click a
  header to collapse/expand.
- **Cards**: each script or pipeline is a card with a language/type badge, name, path, last-run
  status, and right-aligned buttons **⚙ (edit) ▶ (run) ⏹ (stop)**.
- **Output panel** at the bottom (**▸ Output**) — collapsed by default; expands to show run
  logs with per-run tabs.
- **Quick Run bar** (optional, per group) — only shown when enabled and the group has a base
  directory.

Capture: the whole window with a few example cards present.

## Section-by-section

### 1. Main window tour
- Reach: just the default window after launch, with sample cards loaded.
- Capture: full window. This is the orientation shot — make sure tabs, a couple of cards,
  and the (collapsed) Output header are all visible.

### 2. Adding a script
- Reach: click **+ Script** in the header. (Dragging a script file onto the window also opens
  this dialog pre-filled — worth a second screenshot if you cover drag-and-drop.)
- The dialog has: **Name**, **File path** (with **Browse**), **Parameters** (optional),
  **Custom interpreter** (optional), **Group**, and **Save**.
- Capture: the dialog filled in with a believable example — Name "Backup DB", path like
  `C:\scripts\backup.py`. Then capture the new card in the list after Save.

### 3. Running a script + output panel
- Reach: click **▶** on a script card. Then expand **▸ Output**.
- Capture: (a) the card showing a run state / last-run status, and (b) the expanded Output
  panel with real stdout. The seed script "Hello – Python" or "Flood Output" gives good output.
- Output panel controls to mention: save log (💾), copy (⎘), clear (🗑); stderr shows in red.

### 4. Groups (tabs)
- Reach: click **+** in the tab bar to add a group; **right-click a tab** for the context menu
  (Rename, Clone Group, Base directory…, Export group, Delete Group).
- Capture: the tab right-click menu open, and the multi-tab state after creating a group.

### 5. Parameters, prompts, presets
- Reach: open a script's edit dialog (**⚙**) and use the **Parameters** field.
- Concepts: a `"$token"` in params triggers a prompt at run time; presets save named argument
  sets.
- Capture: the Parameters field with an example like `--output "$output_folder" --verbose`,
  and the run-time prompt popup if you can trigger it.

### 6. Pipelines
- Reach: click **+ Pipeline** (name it), which opens the pipeline editor. Edit later via **⚙**
  on the pipeline card.
- Editor: **+ Add step** (pick a script), reorder with **↑ / ↓**, **✕ Remove**, **Save**.
- Capture: the editor with 2–3 steps added, and the pipeline running in the Output panel
  (shows "Step 1/N" progress).

### 7. Quick Run bar
- Reach: enable **Show Quick Run bar** in Advanced Options (requires the group to have a base
  directory). The bar appears per group.
- Capture: the bar with an autocomplete suggestion showing.

### 8. Import / export
- Reach: **Options ▾** → **Export all groups** / **Import config**. Per-group export is on the
  tab right-click menu.
- Capture: the Options menu open showing these entries; optionally the import Merge/Replace prompt.

### 9. Advanced Options (settings tour)
- Reach: **Options ▾** → **⚙ Advanced options…**.
- Tabs/sections: Startup, Window, Output, Appearance (theme, accent, compact, card size),
  Quick Run, Notifications & updates.
- Capture: one shot per tab you want to document, or just the most useful ones (Appearance,
  Window, Notifications).

### 10. Tips
- No new screens needed; pull from features already shown (collapsible sections, last-run
  badges, drag-to-reorder, auto-interpreter detection).

## Options ▾ menu entries (verify live)

Select scripts · Export all groups · Import config · ⚙ Advanced options… · 🔔 Check for
updates · 🗑 Delete All. ("Select scripts" toggles a bulk-delete mode with checkboxes.)

## Example data to use

Use neutral, believable names so screenshots look real without exposing the user's machine:

- Scripts: "Backup DB" (`C:\scripts\backup.py`), "Deploy Site" (`C:\scripts\deploy.ps1`),
  "Hello – Python" (from `tests/`).
- Group: "Work".
- Pipeline: "Deploy" with steps Build → Test → Publish.

Or run `uv run tests/seed_db.py` for a ready-made set of Hello-world scripts in several
languages.
