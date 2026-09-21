# RYOS design system

The interface language of the app, extracted from this repository and published
as a browsable reference that agents and designers can build on.

**Published at:** https://claude.ai/artifact/ERRx6EbMiAZoWYsEyD754d
(private — share it from the page's Share menu before sending the link on.)

Everything the published system serves lives under `project/`, which is the
source of truth. The artifact is a view of it.

## Layout

```
build.py                    regenerates the derived half; --check gates CI
project/
  README.md                 the brand book: principles, colour, type, spacing, writing
  themes.md                 the seed -> palette engine, and all thirteen seeds
  accessibility.md          the contrast mechanisms, and where the palettes miss
  tokens.json               GENERATED - 94 tokens across 8 themes
  components/<Name>/        README.md (guidelines) + preview.html (live preview)
  components/Cover/         the system's cover; no README, by design
  assets/AppIcon/           GENERATED pngs + svg, plus an authored README
```

## Generated vs authored

`build.py` owns exactly this, and overwrites it:

- `project/tokens.json` — palettes resolved through `build_palette()`, the
  script-tag fills from `_script_tag()`, the highlight seeds from
  `HIGHLIGHT_SEEDS`
- `project/assets/AppIcon/ryos-{16,32,64,256}.png` — extracted from `icon.ico`
- `project/assets/AppIcon/ryos-mark.svg` — the polygon `make_icon.py` draws

Everything else is written by hand and the script never touches it. The one
hand-written thing *inside* `tokens.json` is the per-token usage note, which
lives in the `USAGE` table at the top of `build.py`.

## Commands

```bash
python design-system/build.py           # rebuild the generated files
python design-system/build.py --check   # exit 1 if they are stale (what CI runs)
python design-system/build.py --audit   # the WCAG contrast table, all 8 themes
```

No dependencies beyond the standard library; it mocks tkinter the way
`tests/test_ryos.py` does, so it runs on a headless runner.

## Keeping it current

`TestDesignSystemIsCurrent` in `tests/test_ryos.py` runs `--check` on every
push, so a palette edit that isn't reflected here fails CI with the file names.
The fix is always `python design-system/build.py` plus a commit.

Three changes need a hand-edit as well, and the script will tell you:

- **a new palette key** — add a usage note to `USAGE` in `build.py`, or the
  build exits with the key name
- **a new script extension** in `_script_tag()` — add it to `TAG_ORDER`, same
  deal
- **a new component, or changed behaviour in one** — write or update
  `project/components/<Name>/README.md` and `preview.html`. Nothing checks this
  automatically; it is a review question.

## Publishing an update

The repository is the source of truth; publishing pushes `project/` to the
artifact. Ask Claude Code, in a session with the Artifact tool:

> Republish the RYOS design system from `design-system/project/` to
> https://claude.ai/artifact/ERRx6EbMiAZoWYsEyD754d — read the artifact's
> `SKILL.md` first and follow its revising order.

Two rules from that `SKILL.md` matter and are easy to get wrong: images under
`assets/` are **uploads**, not published files, and the index
(`project/design-system.json`) is re-read and sent **last**, on its own, so a
stale copy can't undo an edit someone made in the page meanwhile. The index is
deliberately not committed here — it carries upload ids that only the artifact
knows.

## Known gaps

- The previews are HTML renditions of Tk widgets, not the widgets themselves.
  RYOS is a Python desktop app, so there is no component bundle to ship; each
  preview is built from the real construction and its README names the source
  file, but they are recreations and will drift if nobody looks.
- Eight of thirteen themes ship; the format caps a system at eight. The other
  five are documented as seeds in `themes.md`.
- Eight colour pairs are below their contrast floor. They are the app's real
  values, recorded rather than corrected — see `accessibility.md`.
