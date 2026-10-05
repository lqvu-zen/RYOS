# Theme gallery

Extra themes for RYOS that are **not** bundled with the app — only **Light** and
**Dark** ship by default. **[Browse the previews in GALLERY.md »](GALLERY.md)**:
each one is the RYOS window itself in that theme.

Download any `.json` here and add it to your themes:

- In RYOS: **Options → Appearance… → Import…** (maximised, **Appearance** is
  also on the rail down the left edge). Or use **Browse…** there to find your
  themes folder and drop the file in.
- Or copy the file straight into your themes folder (the path shown under
  "Themes folder" in Appearance; default `%APPDATA%\RYOS\themes\`). It loads on
  next launch.

Available: Nord, Solarized Light, Solarized Dark, High Contrast, Sepia, Ocean
Depths, Sunset Boulevard, Forest Canopy, Midnight Galaxy, Tech Innovation, and
Golden Hour. (Several are adapted from the Anthropic theme-factory palettes.)

`light.json` and `dark.json` are the built-in themes' seeds, included as a
starting **template** — import one, then Edit it to build your own theme from a
familiar base.

Each file is a normal RYOS theme export (a `name` + 7-colour `seed`), so anything
you create and **Export…** from the app can live here too — contributions welcome.
After adding one, refresh the previews and the index:

    uv run python theme-gallery/make_previews.py
