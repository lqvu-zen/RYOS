# Settings and appearance

The **Options** menu holds the settings, the look, and a few switches:

![The Options menu: Options…, Appearance…, Start with Windows, Select scripts and Delete All](images/11-options-menu.png)

| Entry | What it does |
| --- | --- |
| **Options…** | The settings below. |
| **Appearance…** | Themes and the accent colour. |
| **Start with Windows** | Start RYOS when you sign in (needed for schedules to run). |
| **Select scripts** | Tick several scripts to run or delete them together. See [Tips](12-tips.md). |
| **Delete All…** | Remove every group, script and pipeline, after asking. Export first if you might want them back. |

## Options…

Settings are grouped in tabs. Change what you like and click **Save**.

**Cards**

![The Cards tab: Compact cards, Card size, Show details on hover, and Maximised: list on the left, details on the right](images/11-options-cards.png)

- **Compact cards** — one line per row. See [Tips](12-tips.md).
- **Card size** — small, medium or large rows.
- **Show details on hover (compact mode)** — pointing at a compact row shows its path and parameters.
- **Maximised: list on the left, details on the right** — see [The maximised layout](09-maximised-layout.md).

**Startup & Window**

![The Startup & Window tab: keep on top, snap to corner, window width and height, reopen the last group, remember the position, open on the monitor under the cursor, start minimised, close to tray, and ask before closing to tray](images/11-options-startup-window.png)

Where the window opens and how big, whether it stays on top, whether it reopens the last group, and whether closing it keeps RYOS running in the system tray (so schedules keep firing).

**Output**

![The Output tab: maximum output lines, maximum parallel jobs, launcher release delay, open the output panel on run, clear output between runs, scroll to the newest output, notify when a run finishes, and keep run history for (days)](images/11-options-output.png)

How much output to keep, how many scripts may run at once, whether the panel opens and clears by itself, notifications, and how long run history is kept.

**Quick Run**

![The Quick Run tab: enable the Quick Run bar, suggest as you type, indexed extensions, maximum files indexed, index lifetime and suggestions shown](images/11-options-quick-run.png)

Whether the Quick Run bar is offered, what it indexes and how many suggestions it shows. See [Quick Run](08-quick-run.md).

**Logging**

![The Logging tab: write a log file, log level, log script output too, and check for updates on start](images/11-options-logging.png)

RYOS's own log file (on or off, how detailed, whether it records script output) and whether to check for updates when RYOS starts. Mostly useful when something goes wrong.

## Appearance…

![The Appearance dialog: a Theme drop-down set to Light; Create…, Edit…, Delete, Export… and Import…; the themes folder with Browse… and Open; and the accent colour with Choose… and Reset](images/11-appearance.png)

- **Theme** — **Light** and **Dark** come with RYOS; more (Nord, Solarized, High Contrast, Sepia…) are in the [theme gallery](../../theme-gallery/). Drop a theme's `.json` into the **Themes folder**, or **Import…** it. The window changes as you pick.
- **Create…** makes your own theme from seven colours, with a live preview and a warning if any text would be hard to read. **Edit…**, **Delete** and **Export…** work on themes you made.
- **Accent colour** — the colour of the main buttons and highlights. **Reset** goes back to the theme's own.

---
[← Import and export](10-import-export.md) · [Contents](README.md) · [Next: Tips →](12-tips.md)
