# RYOS UI/UX heuristics

A checklist tuned to RYOS: a single-window, mouse-and-keyboard, local desktop tool for running scripts. Use it to judge each screen. These are lenses, not laws — when a heuristic doesn't fit a screen, say why rather than forcing it. Skip anything irrelevant to the screen under review.

## 1. Visual hierarchy
- The primary action on any screen should be the most prominent thing. On a script card that's **Run** (`C["btn_run_bg"]`, emerald). Secondary actions (⚙ modify, ▶+ run-with-param) should read as clearly secondary (`C["btn_neutral_bg"]`).
- Card title vs. path: the script name should dominate; the path is supporting (`C["path_fg"]`, smaller). Check the two aren't competing.
- Group tabs: the active tab must be unmistakably active. Check `_apply_tab_style` — active vs. inactive should differ in more than a hairline.

## 2. Spacing & alignment
- Consistent padding. RYOS uses `padx`/`pady` throughout — look for one-off values that break rhythm (e.g. a card with `pady=5` next to one with `pady=8`).
- Cards should breathe: enough gap between cards that they read as distinct objects, not a wall.
- Buttons in a row should align on a baseline and have even gaps. Watch for ragged right edges from mismatched `width=` values.
- Dialogs: form labels and fields should align into columns, not stagger.

## 3. Colour & contrast
- Text-on-background contrast should be comfortable. The dark output panel (`out_bg` #1e1e1e) with `out_stdout` #d4d4d4 is good; check muted text like `path_fg` (#626975 on white) and `fg_on_dark_2` (#aaaaaa on navy) — muted is fine for secondary text but must stay legible.
- Semantic colour should be consistent: green = run/success, red = stop/error, amber = warning/select-mode. Flag any place these are crossed.
- Don't rely on colour alone to convey state — pair it with an icon or label (e.g. the ⏹ Stop button changes colour *and* enabled-look between idle and live; the status badges use ✓ / ▶ / ✕ glyphs alongside colour). This also helps colour-blind users.

## 4. Affordances & feedback
- Anything clickable should look clickable and react on hover. RYOS uses `cursor="hand2"` + a hover colour swap in `_flat_button`; check that custom widgets (canvas labels, tab wrappers) do the same.
- Destructive actions (delete script/group, clone) should be distinguishable and ideally confirmed. Check context menus use `menu_danger` for destructive items.
- Running feedback: when a script runs, the user must see it start (elapsed timer, RUNNING badge, output appearing). Stale or silent states are a usability bug.
- Tooltips (via `widgets.Tooltip`) should explain icon-only buttons (⚙, ▶+, ⏹). An icon with no label and no tooltip is a guessing game.

## 5. Empty & edge states
- First-run / empty group: does the user see a helpful empty state ("No scripts yet — drag a file here or click +Script") or a blank void? Empty states are prime onboarding real estate.
- Long content: long script names use `ScrollingLabel`; check long paths, long group names, and many cards don't break layout or overflow.
- Error states: failed runs should be obvious (✕ Failed badge, `out_stderr` red) without hunting.

## 6. Consistency
- Buttons of the same role should look identical everywhere (all "create" buttons share `btn_create_bg`). Flag parallel styles doing the same job.
- Typography: one family (`Segoe UI`), a small set of sizes/weights. Flag random font sizes.
- Iconography: the same concept should use the same glyph across screens (don't use ▶ for run in one place and ► in another).
- Corner radius, border weight, and elevation cues should be uniform across cards and dialogs.

## 7. Layout & responsiveness (desktop sense)
- The window resizes — content should reflow sanely, not clip or leave huge dead space. Check what happens narrow and wide.
- Scrolling: the card area should scroll smoothly with a visible, usable scrollbar; the dark output panel should auto-scroll to newest output but let the user scroll back.
- Modal dialogs should be sized to their content and centred over the parent, not tiny or oversized.

## 8. Keyboard & accessibility
- Desktop users expect keyboard support: Tab order through dialog fields, Enter to submit, Esc to cancel. Check dialogs bind these.
- Focus should be visible. Disabled controls should look disabled (the idle Stop button is a good model).
- Hit targets: icon buttons should be comfortably clickable (not 12px squares). `padx`/`pady` in `_flat_button` set this.

## 9. Copy & microcopy
- Button and label text should be specific ("Run", "Add Script") over vague ("OK", "Go"). See the `design:ux-copy` skill if deep copy work is needed.
- Error and confirm messages should say what happened and what to do next, in plain language.
- Title case / sentence case should be consistent across labels.

## What's load-bearing — don't break it
Per `CLAUDE.md`: output flows worker-thread → `Queue` → main-loop `after(80,...)`; never write to the Text widget off-thread. The Quick Run bar re-packs with `pack(after=banner)` to preserve order. Process handle lives in `self.current_process`. A UI change must leave these intact.
