---
name: ryos-tutorial-generator
description: >-
  Generate an end-user tutorial for the RYOS desktop app as a set of Markdown
  pages with REAL screenshots captured from the live app. Use this whenever the
  user wants tutorial docs, a user guide, a getting-started guide, a how-to, a
  manual, a walkthrough, or "docs with images/screenshots" for RYOS — and also
  when they just say things like "document the app for users", "make a guide with
  pictures", "refresh the screenshots in the tutorial", or "TUTORIAL.md is out of
  date". Trigger even if the user doesn't say the word "screenshot": any request
  to produce or update visual, illustrated, or step-by-step user-facing
  documentation of RYOS belongs here. This skill drives RYOS with computer
  control, captures one screenshot per step, and assembles them into a clean,
  multi-page Markdown guide. Do NOT use it for developer/architecture docs, for
  adding features (use add-ryos-feature), or for pure UI critiques
  (use review-ryos-ui).
---

# RYOS Tutorial Generator

This skill produces an **end-user tutorial for RYOS as a set of Markdown pages with real
screenshots** of the running app. The point is a guide a non-technical person could follow,
where every step is backed by a picture of exactly what they'll see.

The core idea: **walk through RYOS in the same order the tutorial reads, and capture the
screen at each step as you go.** Don't write the prose first and bolt screenshots on
afterward — drive the app step by step, and at each step take the shot that illustrates it.
The walkthrough and the document are the same pass.

## Execution agent

Run this skill with the **`claude`** agent (spawn it via the Agent tool with
`subagent_type: "claude"`). That agent has full tool access, including the computer-control
tools this skill depends on (`request_access`, `screenshot`, clicks, typing). Hand it the
repo path, the chosen output location, and the task; let it carry out the capture-and-write
loop end to end and return the finished pages plus the shared `images/` folder.

Two caveats worth passing along when you delegate: desktop access still needs the user's
approval (the agent must call `request_access` and the user approves each app), and RYOS must
be runnable on this machine for live capture. If neither computer-control nor a live RYOS is
available, don't silently fall back — say so and ask how to proceed.

## Keep the user in the loop

This skill operates the user's real computer, so confirm before each action that changes
their machine — don't assume a green light. The system's `request_access` prompt already
gates desktop control, but go a step further and pause to confirm at these points:

- **Before launching RYOS** — tell the user how you'll start it (`open_application`,
  `uv run ryos`, or `run.bat`) and wait for the OK, in case they want to launch it themselves
  or it's already open.
- **Before running the seed script** — `uv run tests/seed_db.py` writes to their `scripts.db`.
  Ask first; offer the "add a sample script through the UI" alternative if they'd rather not
  modify their database.
- **Before deleting or overwriting** anything in an existing `docs/tutorial/` (or other output
  folder) from a previous run.

When in doubt, narrate what you're about to do in one line and wait. The user can always stop
the run; make that easy, not surprising.

## Stopping a run

The user must be able to halt this skill at any time, and stopping must never lose work or
leave their machine in a weird state. Honor a stop the moment it's signalled — don't finish
"just one more" screenshot first.

- **Stop signals.** Treat any of these as an immediate stop: the user interrupts the agent in
  the chat; the user types **stop**, **pause**, **halt**, **cancel**, or **abort**; or the user
  answers "no" / declines at any confirmation gate. The confirmation pauses in "Keep the user
  in the loop" are themselves stop points — declining there ends the run.
- **On stop, exit cleanly.** Stop taking screenshots and clicking. Close any half-filled RYOS
  dialog you opened (press Esc / Cancel) so the app is left in a normal state. Don't delete the
  pages or images already produced.
- **Report where you stopped.** Tell the user which pages are complete, which one was in
  progress, and where the files are. Save every finished page and its images to the output
  folder before you report — partial-but-saved beats lost.
- **Make resuming easy.** Because pages are numbered and written one at a time, a later run can
  pick up from the first unwritten page. If the user asks to resume, check the output folder
  for existing pages and continue from there rather than starting over.

A clean abort that keeps finished work is always better than pushing through. When unsure
whether the user wants to stop, ask.

## Why capture live instead of trusting old docs

RYOS's UI drifts faster than its docs. (At time of writing, the buttons to add things live in
the header as **"+ Script" / "+ Group" / "+ Pipeline"**, but the old `TUTORIAL.md` still
describes them under an "Options ▾" menu.) That gap is the whole reason this skill exists:
**what's on screen is the source of truth.** Look at each screen before you describe it. If
the live UI disagrees with `references/ryos-screen-map.md` or with the existing `TUTORIAL.md`,
believe the screen, write what's actually there, and mention the drift to the user at the end
so they can fix the stale doc.

## Before you start

1. **Find the repo.** RYOS lives in the user's workspace (the folder they selected), typically
   with `ryos/`, `README.md`, and `TUTORIAL.md` at the root. Confirm the path.

2. **Pick the output location.** This guide is **split into one Markdown file per topic**
   inside a single folder, with a shared `images/` subfolder. Default to
   `<repo>/docs/tutorial/`:
   ```
   docs/tutorial/
   ├── README.md            ← index: intro + linked table of contents
   ├── 01-main-window.md
   ├── 02-adding-a-script.md
   ├── 03-running-and-output.md
   ├── 04-groups.md
   ├── 05-parameters-and-presets.md
   ├── 06-pipelines.md
   ├── 07-quick-run.md
   ├── 08-import-export.md
   ├── 09-settings.md
   ├── 10-tips.md
   └── images/              ← all screenshots, shared by every page
   ```
   Keeping every page in the same folder with one shared `images/` keeps links relative and
   the whole folder portable. Ask only if the location is ambiguous.

3. **Get computer access.** This skill controls the user's real desktop. Call `request_access`
   for RYOS (and whatever you'll use to launch it — a terminal, or File Explorer for
   `run.bat`). RYOS is a native app, so it's granted at **full tier** (clicks and typing
   work). A terminal/IDE is **click-only** (use the Bash tool for commands, not typing into
   it); a browser is **read-only**. Take a `screenshot` first to see the current desktop state
   before assuming anything.

4. **Launch RYOS if it isn't running** — after confirming with the user (see "Keep the user
   in the loop"). Prefer, in order: `open_application` if RYOS is installed as an app;
   otherwise have the user's terminal run `uv run ryos` from the repo root; otherwise
   double-click `run.bat` via File Explorer. Wait for the window, then bring it to the
   foreground. If RYOS is already open, just use it.

5. **Make the window screenshot-friendly.** A clean, consistent frame makes every shot look
   like it belongs to one guide:
   - Move the window toward the top-left and give it a **fixed, modest size** (RYOS has a
     window-size setting under Advanced Options → Window). ~900×650 reads well.
   - Use the **Light theme** unless the user asks for dark — light screenshots are easier to
     read in docs and print.
   - Note the window's on-screen rectangle from your first screenshot; you'll crop every
     capture to it (see "Screenshots" below).

6. **Have something to show.** Empty screens make a sad tutorial. You have two good options,
   and the second is usually better:
   - Run the seed script on the user's machine (`uv run tests/seed_db.py` from the repo) to
     populate example scripts — **only after asking**, since it writes to their `scripts.db` —
     **or**
   - Just create a sample script or two *through the UI as the first documented steps* — the
     act of adding them IS the "Adding a script" page, so you get realistic content and the
     screenshots for that page in one move. Prefer this; it's honest and efficient.

## The capture-and-write loop

Each section becomes its **own Markdown file** (see the file list under "Tutorial structure").
Work one file at a time, and for every step inside it repeat this tight loop — appending prose
and its image together so the two never drift apart. Finish and review a page before moving to
the next, so a long run leaves you with complete files rather than a half-written pile.

1. **Navigate** to the screen the section is about (the screen map tells you how to reach each
   one).
2. **Look.** Take a `screenshot`. Read what's actually on screen — labels, buttons, state.
3. **Act if the step is an action** (clicking "+ Script", filling a dialog). Perform the real
   clicks/typing so the screenshot shows a genuine state, e.g. a dialog filled in with a
   believable example rather than blank.
4. **Capture & crop.** Save the screenshot, then run the crop helper to trim it to the RYOS
   window (or to a dialog) and downscale it. Name it for the step (see conventions).
5. **Write the step.** Add a short heading, 1–3 sentences of plain-language instruction, and
   the image reference immediately below it. Write for someone who has never opened the app —
   name the button they click and what happens next.

Write the files in the order a new user would learn them — each filename maps to one page:

1. `01-main-window.md` — a tour of the regions (tabs, sections, cards, output panel)
2. `02-adding-a-script.md` — the Add Script dialog, field by field
3. `03-running-and-output.md` — running a script and reading the output panel
4. `04-groups.md` — organizing with groups (tabs)
5. `05-parameters-and-presets.md` — parameters, prompts, and presets
6. `06-pipelines.md` — create, add steps, run
7. `07-quick-run.md` — the Quick Run bar
8. `08-import-export.md` — import / export config
9. `09-settings.md` — Advanced Options tour
10. `10-tips.md` — tips and shortcuts

Drop or merge pages that don't match the live build, and add any you discover on screen. If
you change the set, keep the numeric prefixes contiguous and update the `README.md` index to
match.

## Screenshots

Consistency is what separates a real guide from a pile of screen grabs.

**Only ever show RYOS. This is a hard rule.** Every image in the guide must contain *only* the
RYOS window (or one of its dialogs) — never the desktop wallpaper, taskbar, system tray,
notifications, other applications, browser tabs, file paths from other windows, or anything
else on the user's screen. The user's screen is private; the tutorial is public. To enforce
this:

- Before each capture, bring RYOS to the **foreground** and make sure no other window overlaps
  it. If anything is on top of RYOS, the shot is unusable — fix it and recapture.
- The raw `screenshot` grabs the whole display, so you **must crop every shot to the RYOS
  window** (or tighter, to a dialog) with `scripts/process_screenshot.py` before it goes in the
  guide. A capture that still shows non-RYOS pixels is not done.
- After cropping, **look at the result** and confirm it shows nothing but RYOS. If you can't
  cleanly isolate the window — e.g. a notification popped over it — discard and retake.
- If you ever can't get a clean RYOS-only shot, leave the image out and tell the user, rather
  than ship a screenshot that leaks their screen.

- **One screenshot per step**, showing exactly the state described — no more, no less.
- **Crop to the window.** Full-desktop shots with wallpaper and taskbar look amateur and leak
  the user's other windows. Crop every capture to the RYOS window rectangle. For modal
  dialogs, crop tighter to the dialog.
- **Use the helper, don't hand-roll cropping each time.** `scripts/process_screenshot.py`
  crops to coordinates, optionally auto-trims a uniform border, downscales to a max width, and
  writes an optimized PNG. Run it on every shot so sizing and quality are uniform.
  ```bash
  python scripts/process_screenshot.py RAW.png OUT.png --crop LEFT TOP RIGHT BOTTOM --max-width 1000
  # or, for a dialog on a solid backdrop, let it trim the border automatically:
  python scripts/process_screenshot.py RAW.png OUT.png --autotrim --max-width 800
  ```
- **Name files for their step**, zero-padded so they sort in reading order:
  `01-main-window.png`, `02-add-script-dialog.png`, `03-run-output.png`, … All pages share the
  one `images/` folder, so link relatively from any page: `![Add Script dialog](images/02-add-script-dialog.png)`.
- **Privacy:** before each shot, make sure nothing sensitive is visible — real file paths from
  the user's machine, other apps, notifications. Use neutral example names/paths
  (`C:\scripts\backup.py`, "Backup DB") rather than whatever happens to be in their DB.

## Tutorial structure

**`README.md` is the index.** It opens with a one-paragraph "what is RYOS / who this is for"
and then a linked table of contents pointing at each page, so a reader lands here first and
navigates out:

```markdown
# RYOS — User Guide

<One-paragraph intro: what RYOS is and who this guide is for.>

## Contents

1. [The main window](01-main-window.md)
2. [Adding a script](02-adding-a-script.md)
3. [Running a script & the output panel](03-running-and-output.md)
... (one link per page, in order)
```

**Each topic page** follows the same rhythm so the set feels like one coherent guide. Give
every page an H1 title, a sentence of context, the steps, and — helpful for a split guide — a
short next/previous link at the bottom so readers can move between pages:

```markdown
# <Page title>

<One or two sentences of plain-language context — what this is and why you'd use it.>

## <Step or sub-topic>

<Numbered steps when it's a procedure; short prose when it's a concept.>

![<descriptive alt text>](images/NN-name.png)

---
← [Previous](0N-prev.md) · [Contents](README.md) · [Next](0N-next.md) →
```

Guidance on the writing itself: address the reader as "you", name buttons exactly as they
appear on screen (use the real glyphs, e.g. ▶ ⏹ ⚙), and keep each step to what the reader does
and what they'll see happen. Image paths are `images/NN-name.png` from every page since they
share one `images/` folder. Alt text should describe the image for someone who can't see it,
not just repeat the heading. Don't over-format — short paragraphs and the occasional small
table (like a button-reference table) read better than walls of bullets.

The existing root `TUTORIAL.md` is a strong content skeleton for what to cover and in what
order — read it for structure, but verify every claim against the live app, because parts of
it have already drifted from the current UI.

## Before you hand it over

- **Read the whole set end to end** as if you were a new user with the app open, following the
  `README.md` links from page to page. Does each screenshot match the step above it? Is
  anything described that isn't on screen, or on screen but undescribed?
- **Check the navigation.** Every `README.md` entry points at a real file; every page's
  next/previous/contents links resolve; the numeric prefixes are contiguous.
- **Check every image link resolves** (the file exists at `images/NN-name.png`) and that
  images are reasonably sized — not multi-megabyte full-desktop dumps.
- **List drift you found.** Tell the user any place where the live UI disagreed with the old
  docs, so they can update the stale source.
- Save the whole folder (all pages + the shared `images/`) to the chosen location and present
  the `README.md` index to the user as the entry point.

## Bundled resources

- `references/ryos-screen-map.md` — every RYOS screen this tutorial covers, how to reach it,
  what to capture there, and the example data to use. Read it before the capture loop; it saves
  you from rediscovering navigation on every run. **It's a starting map, not gospel — the live
  screen wins on any conflict.**
- `scripts/process_screenshot.py` — crop/trim/downscale a raw screenshot into a clean,
  doc-ready PNG. Use it on every capture for uniform sizing and quality.
