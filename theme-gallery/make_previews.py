#!/usr/bin/env python3
"""Generate an SVG preview for every theme in this folder and a GALLERY.md
index, so themes can be browsed and downloaded straight from GitHub.

Run from anywhere:  python theme-gallery/make_previews.py
Outputs:            theme-gallery/previews/<id>.svg, theme-gallery/GALLERY.md

Previews are rendered from a theme's 7-colour seed (plus the fixed Run-green and
terminal colours), so no dependency on the app — drop a new theme JSON in and
re-run.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PREVIEWS = HERE / "previews"

# Order: light/dark first (templates), then the rest alphabetically.
_FIRST = ["light", "dark"]


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def preview_svg(name: str, seed: dict) -> str:
    s = seed
    w, h = 440, 250
    swatch_keys = ["bg", "surface", "border", "accent", "text", "text_muted", "header_bg"]
    sw_w = 40
    swatches = "".join(
        f'<rect x="{16 + i * (sw_w + 6)}" y="202" width="{sw_w}" height="26" rx="4" '
        f'fill="{s[k]}" stroke="#00000022"/>'
        for i, k in enumerate(swatch_keys)
    )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" font-family="Segoe UI, Arial, sans-serif">
  <rect width="{w}" height="{h}" rx="10" fill="{s['bg']}"/>
  <rect width="{w}" height="40" rx="10" fill="{s['header_bg']}"/>
  <rect y="20" width="{w}" height="20" fill="{s['header_bg']}"/>
  <text x="16" y="26" fill="#ffffff" font-size="14" font-weight="bold">⚡ RYOS — {_esc(name)}</text>
  <rect x="16" y="52" width="{w - 32}" height="92" rx="8" fill="{s['surface']}" stroke="{s['border']}"/>
  <text x="30" y="80" fill="{s['text']}" font-size="15" font-weight="bold">deploy.py</text>
  <text x="30" y="100" fill="{s['text_muted']}" font-size="11">C:\\scripts\\deploy.py</text>
  <rect x="30" y="112" width="58" height="22" rx="5" fill="#2ecc71"/>
  <text x="59" y="127" fill="#ffffff" font-size="11" font-weight="bold" text-anchor="middle">Run</text>
  <rect x="96" y="112" width="74" height="22" rx="5" fill="{s['accent']}"/>
  <text x="133" y="127" fill="#ffffff" font-size="11" font-weight="bold" text-anchor="middle">Modify</text>
  <rect x="16" y="154" width="{w - 32}" height="34" rx="6" fill="#1e1e1e"/>
  <text x="28" y="175" font-family="Consolas, monospace" font-size="11">
    <tspan fill="#d4d4d4">stdout </tspan><tspan fill="#ff6b6b">stderr </tspan><tspan fill="#5aa9e6">status</tspan>
  </text>
  {swatches}
</svg>
'''


def main() -> None:
    PREVIEWS.mkdir(exist_ok=True)
    themes = []
    for fp in HERE.glob("*.json"):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        seed = data.get("seed")
        name = data.get("name") or fp.stem
        if not isinstance(seed, dict):
            continue
        themes.append((fp.stem, name, seed))

    def order(item):
        stem = item[0]
        return (_FIRST.index(stem) if stem in _FIRST else len(_FIRST), item[1].lower())

    themes.sort(key=order)

    for stem, name, seed in themes:
        (PREVIEWS / f"{stem}.svg").write_text(preview_svg(name, seed), encoding="utf-8")

    lines = ["# Theme gallery — previews", "",
             "Pick a theme, then download its `.json` and **Import…** it in RYOS",
             "(⚙ → Advanced options → Appearance → Import…).", ""]
    for stem, name, seed in themes:
        lines += [f"## {name}", "",
                  f"![{name} preview](previews/{stem}.svg)", "",
                  f"[⬇ Download {stem}.json]({stem}.json)", ""]
    (HERE / "GALLERY.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Generated {len(themes)} previews + GALLERY.md")


if __name__ == "__main__":
    main()
