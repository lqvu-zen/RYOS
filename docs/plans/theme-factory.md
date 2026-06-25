# Theme Factory — Design & Implementation Plan

Status: draft for review · Owner: TBD · No code yet

## Goal

Give RYOS a real theming system: refined built-in light/dark palettes, several
additional polished presets, and a user-facing **theme creator** where someone
edits a small, curated set of colors and gets a complete, readable theme. Custom
themes are named, saved, and selectable alongside the built-ins.

## Why this needs a design (not just "add more dicts")

Today each theme in `ryos/ui/theme.py` is a hand-written dict of ~60 color keys
(`THEMES["light"]`, `THEMES["dark"]`). That is already a lot to keep consistent
for two themes; adding presets and — worse — letting users hand-pick 60 values
would be unmaintainable and would routinely produce unreadable combinations.

The plan's core idea is to **derive** the full ~60-key palette from a small seed
(7 curated colors + a light/dark base). The same derivation powers built-in presets
(defined as seeds) and custom themes (user-edited seeds). This keeps presets
consistent, makes the custom creator safe by construction, and shrinks the
surface area users can break.

## Current state (what we build on)

- `ryos/ui/theme.py`: `THEMES` (named palettes), `C` (the live mutable palette),
  `apply_theme(name, accent)` (swaps `C`, can overlay a custom accent via
  `_shade`), `_configure_ttk_styles()`, `_flat_button()`, snap helper.
- Widgets read `C["..."]` **at creation time**, so a live theme change requires a
  rebuild — which already exists: `RYOSApp._apply_appearance()` calls
  `apply_theme()` then `_rebuild_ui()`.
- The Appearance tab (`dialogs.py`) already does **live preview** (the `theme`
  StringVar has a trace), **revert-on-cancel** (`_original_appearance`), and an
  accent-color picker. Theme switching is solved; we are extending what a "theme"
  is and how it is chosen.
- Settings: `theme` (active name) and `accent_color` (optional override), saved
  in `settings.json`. No database involvement.

This is a strong foundation: the risky part (live re-theme + rebuild + revert) is
done. The work is the palette model, the presets, and the creator UI.

## Design

### 1. Seed model + palette derivation (the foundation)

New top-level module `ryos/themes.py` (pure logic, **no tkinter**, so it is unit
testable and respects the one-way `ui/* → top-level` dependency rule):

- A **seed** is a small dict: `mode` (`"light"` | `"dark"`) plus a curated set of
  **7 editable colors** (6 base + the header):
  - `bg` — app canvas
  - `surface` — card / dialog background
  - `border` — dividers / card outlines
  - `accent` — brand / primary
  - `text` — primary text
  - `text_muted` — secondary text
  - `header_bg` — top header bar
- `build_palette(seed) -> dict` expands a seed into the **complete** ~60-key
  palette that `C` expects, using `_shade`-style math and the `mode` to pick
  contrast direction and the output-panel/menu/tooltip surfaces:
  - hovers and borders are shades of `bg`/`surface`;
  - `accent2`, `accent_wash`, and the mod/create button families derive from
    `accent` (this logic already exists in `apply_theme` and moves here);
  - `fg_on_dark`, tab colors, status-bar bg derive from `mode` + surfaces;
  - semantic colors (`ok`, `running`, `error`, warn family, pipeline accent) and
    the signature `bolt` gold are sensible mode-aware defaults, not user-edited;
  - the terminal output panel (`out_*`) stays dark by default in every theme
    (preserves the current look) — revisit later if we want light terminals.
- `build_palette` **guarantees key parity**: any key in today's `THEMES["light"]`
  that isn't derived is filled from a reference base palette, so no widget can
  ever hit a missing-key `KeyError`.

The existing `light` and `dark` become seeds; their derived palettes should match
the current look closely (a chance to refine them deliberately).

### 2. Built-in presets

Ship these built-in seeds in `ryos/themes.py`, alongside the refined **Light**
and **Dark**: **Nord**, **Solarized Light**, **Solarized Dark**,
**High-contrast** (accessibility), and **Sepia / Warm** — seven built-in themes
total. Each is just the 7-color seed; derivation does the rest.

### 3. Custom theme creator

- **Selector**: in the Appearance tab, replace the Light/Dark radio with a theme
  selector (a dropdown / combobox) listing all built-in + custom themes.
  Selecting one re-themes live (reuses the existing trace → `_apply_appearance`).
- **Editor**: a new `ryos/ui/theme_editor.py` (`ThemeEditorDialog`) with the 7
  color pickers, a **name** field, a small **live preview** (a mock card +
  button + text sample rendered from a candidate palette), and Save/Cancel.
  - "Create from current" pre-fills the editor with the active theme's seed.
  - A **contrast check** (WCAG-style ratio) warns inline if `text`/`text_muted`
    on `bg`/`surface` falls below a readability threshold — the curated set plus
    this guard is what makes custom themes "hard to make ugly."
- **Edit / delete** existing custom themes from the selector.

### 4. Persistence

- Custom theme seeds live in a new `themes.json` in the app data dir (alongside
  `settings.json`), via `load_custom_themes()` / `save_custom_themes()` in
  `ryos/themes.py` (reusing `_APPDATA` from `settings.py`). Keeping them out of
  `settings.json` mirrors the existing split (e.g. the QR index) and keeps each
  file small. Corrupt-file handling falls back to "no custom themes" with a log
  warning, matching `_load_settings`.
- `settings["theme"]` stores the active theme name (built-in **or** custom).
  `accent_color` stays as an optional overlay for backward compatibility.

### 5. Resolution flow

`apply_theme(name, accent)` becomes: resolve `name` → seed (built-in table or
loaded custom themes) → `build_palette(seed)` → overlay `accent` if set → update
`C` → `_configure_ttk_styles()`. If `name` is unknown (e.g. a deleted custom
theme), fall back to `light` so the app always starts.

## Files touched

- **New** `ryos/themes.py` — seeds, `build_palette`, contrast util, custom-theme
  load/save. Pure, no tkinter.
- **New** `ryos/ui/theme_editor.py` — `ThemeEditorDialog` (pickers + preview).
- `ryos/ui/theme.py` — import seeds/`build_palette` from `ryos.themes`; rework
  `apply_theme` to resolve via the seed model; keep `C`, `_flat_button`,
  `_configure_ttk_styles`, snap. `THEMES` becomes derived from the seeds.
- `ryos/ui/dialogs.py` — Appearance tab: theme selector + "Create / edit theme…"
  entry point; keep live-preview/revert wiring.
- `ryos/settings.py` — no schema change required (reuse `theme`/`accent_color`);
  exposes `_APPDATA`/path already.
- `tests/test_ryos.py` — new tests (below).
- `ryos/__init__.py` — **no version bump**; per the updated policy the version is
  bumped only at release time, never per feature.

## Phasing (each phase independently shippable & reviewable)

1. **Foundation, no visible change.** Add `ryos/themes.py` with the seed model
   and `build_palette`; refactor `light`/`dark` into seeds; route `apply_theme`
   through it. Land the parity + contrast tests. The app should look identical.
2. **Presets.** Add the new preset seeds; swap the Light/Dark radio for the theme
   selector. Live preview already works.
3. **Custom creator.** `ThemeEditorDialog`, `themes.json` persistence, and
   create/edit/delete wired into the selector.
4. **Sharing.** Export a custom theme to a JSON file and import one, reusing the
   existing import/export plumbing.

## Testing & verification

Non-UI logic gets real unit tests in `tests/test_ryos.py`:

- **Key parity**: for every built-in seed, `build_palette` produces every key
  present in the current `THEMES["light"]` (guards against `KeyError` at widget
  creation).
- **Valid output**: every derived value is a `#rrggbb` string.
- **Contrast**: `text`/`text_muted` vs `bg`/`surface` meets the chosen threshold
  for each built-in preset; the contrast util itself has known-value tests.
- **Persistence**: custom themes round-trip through `themes.json`; a corrupt file
  falls back to empty without raising.
- **Resolution**: unknown/deleted theme name falls back to `light`.

UI verification (manual / `run-ryos` screenshot driver): switch among presets
with live preview, cancel reverts, create → save → reselect a custom theme,
delete it, restart and confirm the saved choice persists; confirm no regression
to run/stop, groups, output panel, drag-drop, pipeline editor.

## Risks & mitigations

- **Missing key → KeyError**: parity test + reference-fill in `build_palette`.
- **Unreadable custom themes**: curated seed + contrast warning in the editor.
- **Output panel legibility** across light themes: keep `out_*` dark by default;
  treat light terminals as a later, optional follow-up.
- **Backward compatibility**: existing `theme`/`accent_color` settings continue
  to resolve; `light`/`dark` remain valid names.
- **Scope creep in the editor**: ship the 7 curated colors only; full-palette
  editing is explicitly out of scope for v1.

## Decisions (resolved)

1. **Presets**: refined Light & Dark, plus Nord, Solarized Light, Solarized Dark,
   High-contrast, and Sepia / Warm — seven built-in themes.
2. **Selector**: a dropdown / combobox in the Appearance tab.
3. **Curated seed**: 7 editable colors — `bg`, `surface`, `border`, `accent`,
   `text`, `text_muted`, `header_bg` — with everything else derived.
4. **Sharing**: yes — export/import custom themes as JSON (added as Phase 4).
