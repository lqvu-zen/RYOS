# Tips

## Compact rows

**Options → Options… → Cards → Compact cards** puts each script on one line — star, name, kind, how it last went, Run — so a long list fits. Point at a row for a moment to see its path and parameters.

![The window in compact mode: one-line rows, each with a star, the name, its kind (PYTHON, BATCH, PIPE) and a small Run button](images/12-compact.png)

## Run or delete several at once

**Options → Select scripts or pipelines** adds a tick box to every script and pipeline; click a row to tick it. Tick the ones you want, then **Run selected** or **Delete selected**. **Select All** ticks them all; **Options → Cancel select** leaves the mode.

![Select mode: a yellow bar saying "2 of 10 selected" with Select All, Run selected and Delete selected, and tick boxes beside the scripts](images/12-select-mode.png)

## Dark, or your own colours

**Options → Appearance…** switches theme. Every colour in RYOS follows the theme — rows, pills, the header and the output alike.

![The RYOS window in the Dark theme](images/12-dark.png)

## Small things

- **Highlight a name.** Right-click → **Highlight** colours a row's name, to make one stand out in a long list.
- **Let RYOS pick the interpreter.** Leave **Interpreter** blank: `.py` runs with Python, `.ps1` with PowerShell, and so on. Fill it in only to override.
- **Keyboard.** RYOS starts in the search box: type to filter, **Esc** to clear, **↓** to go into the list. There the arrow keys (and **Home**, **End**, **Page Up/Down**) move between rows, **Enter** runs the row, **F2** edits it, **Ctrl+C** copies it (then **Ctrl+V** on a row in another group pastes it there) and the **Menu** key (or **Shift+F10**) opens its right-click menu, which holds everything its hover buttons do. In select mode, **Space** (or a click) ticks a row. **Tab** moves between the header, the list and the output; in a dialog **Enter** presses the highlighted button and **Esc** closes it.
- **Keep it running in the tray.** **Options… → Startup & Window → Close to tray instead of exiting** keeps RYOS (and your schedules) running when you close the window.
- **Report a bug.** Click the bug icon at the right end of the status bar (or **Help → Report a bug…**). It opens a new issue on GitHub already filled in with your RYOS, Windows, Python and Qt versions, your theme and layout — write what happened and submit it. Nothing is sent until you do. A small box then shows where the log is; see [If something goes wrong](#if-something-goes-wrong).
- **Back up.** **File → Export all groups…** now and then, and your setup is one import away.

## If something goes wrong

**Where the log is.** Choose **Help → Open log folder** and the folder opens. It is `%APPDATA%\RYOS\logs`. In a terminal, `ryos-cli version` prints the folder and each log this download writes.

**What is in it.** Up to three files, each written by a different part of RYOS:

- `ryos.log` — the window
- `ryos-cli.log` — the command line (`ryos-cli`)
- `ryos-mcp.log` — AI agents (`ryos-cli mcp`), in downloads that have them

**Turning it on, or up.** **Options… → Logging** has **Write a log file**, and the level of detail. If the log is off, turn it on and make the problem happen again.

**Then report it.** **Help → Report a bug…** opens a new issue on GitHub and shows where the log is, with a button that opens its folder. Drag the file into the issue, but have a look first: it can contain your script paths and output.

---
[← Settings and appearance](11-settings.md) · [Contents](README.md) · [Next: The command line and AI agents →](13-command-line-and-agents.md)
