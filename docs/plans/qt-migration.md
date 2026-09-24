# RYOS — Tk → Qt Migration Plan

_Created 2026-09-21 at v1.11.2 · binding: **PySide6** · strategy: **extract first, then port alongside**_
_Companion to [`../tech-debt-2026-09-21.md`](../tech-debt-2026-09-21.md). Every figure here was measured, not estimated; the measuring scripts are named at each step so they can be re-run._

## Why

Four drivers, all pointing the same way:

- **Visual ceiling.** Tk cannot be made to look current, and no amount of theming work changes that.
- **Layout bugs keep shipping.** Issues #3, #7 and the invisible failure badge were all Tk pack-geometry faults — pack order deciding width allocation, parent-vs-master stacking. Qt's size policies make that class structurally rarer.
- **Richer widgets.** Tables, dockable panels, model/view, animation — things Tk does badly or not at all.
- **Cross-platform runway.** Better Linux/macOS behaviour and a toolkit with a longer future.

A fifth benefit is testing: this environment has `event_generate` inert and `wait_visibility()` hanging, so synthetic-input tests are impossible today. `QTest` delivers real event synthesis, which makes the interaction tests that could not be written writable.

## Why this codebase can take it

The one-way import rule held **essentially perfectly**. Measured across all 30 modules:

| | Modules | Lines | Fate |
| --- | ---: | ---: | --- |
| Core | 21 | **4,576** | survives unchanged |
| `ryos/ui/` | 9 | **7,067** | rewritten |

There are zero runtime `tkinter` imports outside `ryos/ui/`. The two apparent exceptions are both correct: `jobs.py` imports tkinter only under `TYPE_CHECKING` (three field annotations to retype), and `__main__.py` imports `ui.app` because that is what an entry point does.

**94 of 97 test classes — 655 tests — survive untouched.** Only `TestPipelineEditorTheming`, `TestSearchFilterRefreshRealTk` and `TestPlacementCallSites` touch the toolkit. `tests/gui_smoke.py` (771 lines, 16 checks) is entirely Tk widget introspection and gets rewritten against `QTest`.

Qt also retires real code: `tkinterdnd2`, `pystray` and `pillow` all go (native drag-drop, `QSystemTrayIcon`), as does most of the `ctypes` / `MonitorFromPoint` work in `screens.py`, since `QScreen` gives work areas cross-platform.

## What this does not fix

**Qt will not fix `app.py`.** Ported as-is it becomes a `QMainWindow` with 145 methods, and register item 6 travels with it. That is the entire argument for extracting first: every line moved out of `app.py` into a UI-free controller is a line never written twice.

## Phase 1 — Extract, on Tk (ships incrementally)

`RYOSApp`'s 145 methods clustered by concern, with toolkit density per cluster (`scratchpad/find_seams.py`):

| Concern | Methods | Lines | Toolkit calls | Action |
| --- | ---: | ---: | ---: | --- |
| Quick Run | 16 | **493** | 21 | **extract** |
| Jobs / running | 19 | **354** | 14 | **extract** |
| Groups / tabs | 16 | 199 | 10 | **extract** |
| Drag & drop | 10 | 158 | 4 | **extract** |
| Cards / sections | 18 | 540 | 74 | leave — rewrite in Qt |
| Search / filter | 13 | 217 | 22 | leave — rewrite in Qt |
| Output panel | 11 | 193 | 27 | leave — rewrite in Qt |
| *(unclassified)* | 31 | 549 | 35 | triage during the above |

> **This revises the June plan.** `docs/plans/refactor-plan.md` named `SearchController` as the main remaining structural step. Measurement says otherwise: search/filter is only 217 lines and carries the second-highest toolkit density in the file, so extracting it buys little and most of it gets rewritten anyway. **Quick Run is the prize** — 493 lines, 16% of the file, and `quickrun.py` already exists as its pure half, so the seam is proven and there is somewhere to put it.

### Order

Each step follows the `JobController` pattern: UI-free, callbacks injected at construction, unit-tested, suite green before moving on.

1. **Drag & drop → `dragdrop.py`** — 158 lines, 4 toolkit calls. Smallest and purest; a warm-up that proves the pattern holds outside `JobController`, into a module that already exists.
2. **Quick Run → `QuickRunController`** — 493 lines. The big win.
3. **Jobs / running → fold into `JobController`** — 354 lines, into the best-tested module in the project.
4. **Groups / tabs → `GroupController`** — 199 lines.

**Target: `app.py` 3,145 → ~1,940 lines**, with ~1,200 lines becoming toolkit-free core.

> **Outcome, 2026-09-22 — the target was wrong, and the work was still worth doing.**
> `app.py` finished at **3,014**, down 131 lines rather than ~1,200. The seam table
> measures whole methods, but only their *decisions* move; the widget code they were
> tangled in stays until the port. What Phase 1 actually bought:
>
> - **66 new tests** over logic that was previously unreachable without a display —
>   drag rules, the Quick Run index, launch preflight, group CRUD.
> - **One new UI-free module** (`quickrun_index.py`, 232 lines) and three grown
>   (`dragdrop.py`, `grouping.py`, `job_controller.py`).
> - **Quick Run's first end-to-end check**, closing most of register item 2.
> - **Four real bugs found in the extractions themselves**, each caught by a test
>   written against the newly-reachable code: `clear()` resetting the disk gate,
>   `SKIP_DIRS` duplicated instead of shared, every refusal routed through
>   `showerror`, and the drag threshold.
>
> Judge phases like these by what becomes testable, not by the line count.

**Exit criteria:** 655+ tests green, ruff clean, mypy clean on both platforms, GUI smoke exit 0, and a release cut at the end so the extractions reach users on Tk. Nothing in Phase 1 is staked on the port happening.

## Phase 2 — Port alongside

Build `ryos/qtui/` **next to** `ryos/ui/`, not in place of it. Tk keeps working the whole way; `__main__` flips only at parity. A big-bang replacement leaves no working app for the duration, which for a single-maintainer project is the wrong risk.

Bottom-up, because each layer is used by the next:

1. **`theme.py` → QSS.** `build_palette()` survives untouched as the generator; template a stylesheet from it instead of setting `bg=`/`fg=` per widget. The design system's token half comes along unchanged.
2. **`widgets.py`.** `Tooltip` and `ScrollingLabel` are native in Qt — mostly deletion.
3. **`cards.py`.** The visual core. See the decision below.
4. **`dialogs.py`.** Densest widget code in the project (234 constructors in 1,864 lines), but mechanical.
5. **`pipeline.py`, `theme_editor.py`.**
6. **The shell** — window, menus, output panel, search, tabs.

**Exit criteria per module:** the Tk version still runs, and the Qt version passes an equivalent `QTest` check.

## Decisions to settle early

Expensive to reverse, so take them before writing the shell.

**Cards: plain widgets or model/view?** Plain widgets in a `QScrollArea` mirror what exists and port fast. `QListView` + a delegate scales to thousands of cards and is substantially more work. With 8 themes × 3 card sizes × compact mode already in play, **start with plain widgets** — revisit only if card counts grow.

**Styling: QSS from the palette.** Generate one stylesheet per theme from `build_palette()` rather than styling widgets individually. This is strictly better than the current `C`-dict propagation and keeps theming a core concern.

**Design system.** 48 files, 18 component previews, four days old. The token/palette half is toolkit-independent and survives; the component guidance is written about Tk widgets and needs rewriting as each component ports. `design-system/build.py` reads `build_palette()`, `_script_tag()` and `HIGHLIGHT_SEEDS`, all of which are core — so the generator itself survives.

## Packaging: measured

A throwaway PySide6 app shaped like RYOS's shell (tabs, a scrolling card list,
a four-button row per card, an output pane, a status bar) built with cx_Freeze
and smoke-tested by launching it and asserting on its window title.

| Build | Folder | Zipped | Runs? |
| --- | ---: | ---: | :--: |
| Untuned | 364 MB | **151.1 MB** | ✅ |
| Module excludes | 92 MB | 36.8 MB | ✅ |
| Excludes + DLL prune | 56 MB | **23.3 MB** | ✅ |
| *Today's Tk build* | *~49 MB* | *19.7 MB* | |

**So the real cost is +3.6 MB on the download, not the 40–80 MB this plan
originally guessed.** The untuned figure is the trap: cx_Freeze bundles every
Qt module it can find, and `Qt6WebEngineCore.dll` alone is **195 MB** — a whole
browser engine, for an app that renders no HTML.

Two levers, in order of payoff:

1. **`excludes` for unused PySide6 submodules** (WebEngine, QML/Quick, Qt3D,
   Multimedia, Charts, Designer, Pdf, Sql, Bluetooth, …). 364 → 92 MB. This is
   declarative and belongs in `setup_cxfreeze.py`.
2. **Dropping the DLLs the excludes cannot reach.** Module excludes stop the
   Python bindings but not the sibling DLLs in the package directory, so
   `Qt6Quick`, `Qt6Qml`, `Qt6Pdf`, `Qt6OpenGL`, the `translations/` tree and
   the bundled OpenSSL pair survive. 92 → 56 MB.

**Lever 2 needs care.** Deleting DLLs post-build fails at *runtime*, not build
time, so a later feature that reaches for `QtSvg` or `QtNetwork` would ship
broken. Express it as `bin_excludes` in the build config rather than an rm, and
keep the exe smoke test in the release runbook — it already asserts the window
title, which is exactly the check that catches a missing Qt plugin.

RYOS needs `QtCore`, `QtGui`, `QtWidgets`. Nothing in the current feature set
needs Qt's network stack (the GitHub update check uses `urllib`) or SVG.

## Costs to accept up front

- **Download size: 19.7 MB → 23.3 MB, but only if the build is tuned.** Measured, not estimated — see below.
- **`gui_smoke.py` is rewritten** — 771 lines, 16 checks. Mitigated by `QTest` making the replacements better than the originals.
- **A second UI in the tree** for the duration of Phase 2.
- **Licensing:** PySide6 is LGPL, so a closed-source or commercial build stays possible. (PyQt6 would be GPL-or-paid, which would bind RYOS itself.)

## Open questions

- ~~Does `cx_Freeze` + PySide6 produce a working single-folder build on Windows, and at what size?~~ **Answered 2026-09-22 — yes, and the size is a tuning problem, not a Qt problem.**
- Keep `tkinterdnd2`-style OS file drops? Qt handles this natively; confirm the behaviour matches on Windows.
- Does the single-instance handoff (`single_instance.py`, raw win32) still work, or should it become `QLocalServer`/`QLocalSocket`? The latter is cross-platform and would retire more ctypes.

## Status

| Phase | State |
| --- | --- |
| 1.1 Drag & drop extraction | **done 2026-09-22** (`8f589fb`) — rules extracted, 16 tests; `app.py` unchanged in size, see note |
| 1.2 Quick Run controller | **done 2026-09-22** — index extracted to `quickrun_index.py`, 17 tests, +1 smoke check; `app.py` 3,145 → 3,033 |
| 1.3 Jobs into `JobController` | **done 2026-09-22** — launch preflight extracted as LaunchPlan/Refusal, 13 tests; `app.py` 3,033 → 3,017 |
| 1.4 Group controller | **done 2026-09-22** — CRUD rules into `grouping.py`, 20 tests; `app.py` 3,017 → 3,014 |
| 2.0 Packaging measured | **done 2026-09-22** — 23.3 MB zipped when tuned; see Packaging |
| 2.1 `theme.py` → QSS | **done 2026-09-22** — `qtui/stylesheet.py`, 13 unit tests + `tests/qt_smoke.py` |
| 2.2 `widgets.py` | **done 2026-09-22** — Tooltip/HoverPreview mostly deleted; marquee maths shared via `ryos/marquee.py`, 13 tests |
| 2.3 `cards.py` | **done 2026-09-22** — rules shared via `ryos/cardstyle.py`; Qt cards + smoke check pinning #3, #4, #7 |
| 2.4 `dialogs.py` | **done 2026-09-23** — validation + settings schema extracted (36 tests, dialogs.py’s first coverage); Qt options form generated from the schema; the remaining seven dialogs in `qtui/smalldialogs.py`, with `scheduleform.py` shared (29 tests) |
| 2.5 `pipeline.py`, `theme_editor.py` | **done 2026-09-22** — step rules + theme-form rules extracted (33 tests); Qt pipeline editor; `verdict.py` consolidates three copies of the same shape |
| 2.6 The shell | **in progress** — window, tabs, cards, search, output panel, re-theming, `JobBridge` (real scripts and pipelines run through Qt), and the running-jobs section with stop |
| 2.7 Parity | **not started** — see below |
| 2.8 Flip `__main__` | blocked on 2.7 |

**1.1 note — the extraction did not shrink ** (3,145 → 3,153). The decisions were small; what they were tangled in is widget code that stays until the port. Expect the same shape from 1.2–1.4: the line count falls less than the seam table suggests, because that table measures whole methods while only their decisions move. The real win is UI-free, tested rules that survive the rewrite — treat the ~1,200-line target as optimistic.

### Parity: what the Qt shell still lacks

Recorded 2026-09-23. The Qt side runs scripts and pipelines, but the next
release is to be the Qt one, so everything below has to exist before
`__main__` flips.

| Missing on Qt | Size in the Tk app | Notes |
| --- | --- | --- |
| ~~Quick Run bar~~ | — | **Done 2026-09-23.** Bar rules in `quickrun.py`, submit flow in `quickrun_actions.py`, both shared with Tk. The Qt bar's index hand-off uses `MainThreadInvoker`; `QTimer.singleShot` was tried and verified never to fire from the worker thread. |
| ~~Drag-and-drop reordering~~ | — | **Done 2026-09-23.** Rules and the database side (`apply_move`, `apply_reorder`, `outside_base_warning`) shared in `dragdrop.py`; `qtui/dragdrop.py` uses real `QDrag`. Tabs are keyed by group, so dropping on "Ungrouped" moves to `""`. The reload after a drop is deferred a turn, since it replaces the widget still handling the event. Favorites is a drop target since 2026-09-24 (see Favourites and sections). |
| ~~Tray icon~~ | — | **Done 2026-09-24.** `qtui/tray.py` is a `QSystemTrayIcon` fed the same job snapshot as the pystray tray. Its menu, its tooltip and the close/minimise/start/quit rules come from `traypolicy.py`, shared with Tk. The shell now handles close (tray, prompt, quit), minimise-to-tray, start minimised, jumping to a job from the tray, and quit (asks when jobs are alive, then stops them). Found on the way: the Qt shell had no close handling at all, so closing it left running jobs unmanaged. Settings saving and application quit default to doing nothing in the shell, and the real entry point passes them in at the flip, so no test can write real settings. |
| ~~Schedule tick~~ | — | **Done 2026-09-23.** The sweep is `schedule_runner.run_due`, shared with Tk; `JobBridge` runs it on its own `QTimer`. A scheduled refusal goes to the status line, not a modal box. Found on the way: the Qt bridge never unregistered finished jobs (they held the cap and blocked their schedules), and Tk disabled schedules on ungrouped pipelines as "missing". Both fixed. |
| ~~Context menus on cards and tabs~~ | — | **Done 2026-09-23.** The menus are data in `cardmenu.py`, drawn by both toolkits; the group-menu decisions live in `grouping.py`. The ☆ button now works too. Qt cannot colour one menu entry red, so Delete relies on its glyph and its prompt. Found on the way: Tk's Clone dropped `detached`, env vars and working folder (issue #5 again for a cloned launcher), and renaming a group onto an existing name raised `IntegrityError` in Tk. Both fixed. |
| ~~Select mode / run selected~~ | — | **Done 2026-09-23.** Wording and the run-selected plan are shared in `selection.py`. Qt's select bar is under Options, and covers the scripts on the current tab. Found on the way: a refused run in Qt (job cap, missing file) did nothing and said nothing. It now says why, as Tk does. |
| ~~Group management from the shell~~ | — | **Done 2026-09-24.** The tab menu has rename, clone, base folder, export and delete. There is also a + button for New Group, tabs reorder by drag (saved on release, and Ungrouped stays last), and Options has Export all, Import and Delete All, with wording shared in `configio.py`. Found on the way: Tk's Delete All counted only the cards on screen but deleted every script in the database. Fixed in both. Still open, and older than the port: deleting a script leaves any pipeline steps that used it (there are no foreign keys). |
| ~~Pipeline editor persistence~~ | — | **Done 2026-09-24.** Rebuilt on the database like the Tk editor. Name, add, remove, reorder, "with previous", the three policy fields and the per-step preset are each saved as they change. The rules and wording are shared in `pipelinesteps.py`. It opens from the menu and from the card's ⚙. The editors had drifted on the "run when" wording and the legend, and are now one. Fixed in Tk: changing a step's preset dropped its policy marks from the row. |
| ~~Script dialog~~ | — | **Done 2026-09-24.** `qtui/scriptdialog.py` has every Tk field: group, a relative path under the group's base folder, presets, ask-for-parameter, launcher, working folder, environment variables and Delete. It loads and saves through `scriptform.load_form` / `save_form`, which Tk now uses too. Add Script is in the shell (it asks for a first group if there are none), and the script card's ⚙ opens it. **Deliberate difference:** Tk saves a new preset, and overwrites the script's parameters, as soon as it is added, so Cancel does not undo it. Qt writes nothing until Save. Decide which to keep before the flip. |
| ~~Single-instance handoff~~ | — | **Done 2026-09-24.** Reuses `single_instance.py` unchanged: its listener fills a queue, and `attach_instance` drains it on a UI-thread `QTimer`. `QLocalServer` was the plan, but sharing one implementation beats two. Restoring on the cursor's monitor waits for the multi-monitor item below. |
| ~~Update check and notifications~~ | — | **Done 2026-09-24.** The shell has an update banner and Options → Check for updates, and `check_for_updates()` is there for the entry point to call at start. What a result means and what to say is `notifications.update_status` and friends, shared with Tk. Job-finished toasts were not wired in Qt at all; they now follow `notify_on_complete`. The fetch, the toast and opening the release page are all injected. The fetch and toast default to doing nothing, so tests make no network calls and pop no toasts, and the entry point passes the real ones at the flip. |
| ~~Window geometry, snap-to-corner, multi-monitor~~ | — | **Done 2026-09-24.** Placement decisions (`initial_geometry`, `snap_position`, `follows_cursor`, the geometry string) are in `screens.py`, shared with Tk. Qt reads work areas from `QScreen` in `qtui/placement.py`. The shell opens on the cursor's monitor (a login launch restores in place), snaps to a corner, sets always-on-top, remembers its geometry even when quit from the tray, and restores to the cursor's monitor on a second launch. Measured on a mixed-scaling desktop (100% + 125%): Tk (DPI-unaware) and Qt report identical work areas, so one saved geometry serves both. Also found: the Qt Options dialog existed but nothing opened it. It is now under Options, and applies size, always-on-top, snap and card layout as Tk does. |
| ~~Favourites and sections~~ | — | **Done 2026-09-24.** Each Qt group page is now collapsible Favorites, Pipelines and Scripts sections (`qtui/sections.py`), as in Tk. Contents, texts and collapse state come from `sections.py`, which Tk now uses too. A favourite shows in both places. Moves and drops in Favorites act among favourites, on the one shared script order, as in Tk. Collapse state lasts the session and is kept across reloads. |
| **Open: window grows a few pixels (intermittent)** | — | Seen 2026-09-24 in the Qt smoke on the maintainer's machine: in some runs, every placed window came out 1px wider on each side and 8px taller at the top (asked 540x640+1100+50, got client 542x648, frame 1099,42). It came in bursts (3 of 3 runs, then 18 of 18 clean), never in isolation, and re-applying the size did not help when tried in a clean run. Saved and reapplied, it would **grow the window on every start**, so this must be understood before the flip. `set_geometry_string` now logs a warning with both sizes and the frame margins whenever it happens, and the smoke's placement check reports the frame, client, screen and margins. |
| "All" tab | `_refresh_cards` with no active group | Tk has an All tab showing every group, each under its own header with its own sections. Qt has no All tab. |
| Running section per group | `_render_running_section` | Tk shows each group's running jobs inside that group's page. Qt has one running list under the tabs. Decide whether to match Tk or keep the single list. |
| ~~Theme editor~~ | — | **Done 2026-09-24.** `qtui/theme_editor.py` edits a seed with a live preview and contrast warnings. `qtui/appearance.py` (Options → Appearance…) is Tk's Appearance tab: pick a theme, create/edit/delete/export/import custom themes, set the themes folder, and set the accent, all previewed live. Cancel restores the look it opened with. Palette resolution (`palette_for`, `theme_choices`) moved from `ui/theme.py` into `themes.py`, and the tab's rules into `themeform.py`. Tk uses both, and gives palettes identical to before on every theme, with and without an accent. **Deliberate difference:** Tk locks Appearance while jobs run, because it rebuilds its widgets. Qt restyles in place, so it does not. |

**A process note, recorded because it cost something.** `tests/` is ignored
by default in `.gitignore`, with named files allowlisted back in, and
`tests/qt_smoke.py` was never added — so for the whole of phase 2 the Qt
smoke existed only on one machine while the commit history described it as
committed. It was tracked in `7b4bdcd`, and `TestDocumentedHarnessesAreTracked`
now fails if a documented harness is ignored again.

_Update this table as steps land, and record any measurement that contradicts the plan — the seam table above is a snapshot and will drift as `app.py` shrinks._
