"""Theme palettes and the seed -> full-palette derivation engine.

Pure logic, no tkinter, so it is unit-testable and respects the one-way
`ui/* -> top-level` dependency rule (the UI imports from here, never the
reverse).

A *seed* is a small, user-editable description of a theme: a light/dark `mode`
plus 7 curated colors (see SEED_KEYS). `build_palette` expands a seed into the
complete colour dict the UI consumes (`ryos.ui.theme.C`). It starts from the
mode's REFERENCE palette so every key is always present (no missing-key
KeyError), then overlays the seed-derived colours. Built-in Light/Dark use their
hand-tuned REFERENCE palettes verbatim so the app looks identical; new presets
and user themes are produced by `build_palette`.
"""
import json
import logging
import re
from pathlib import Path

from .settings import DATA_DIR

_log = logging.getLogger("ryos.themes")

# The 7 curated colours a seed carries (besides "mode").
SEED_KEYS = ("bg", "surface", "border", "accent", "text", "text_muted", "header_bg")

# Optional advanced colours. A seed may carry any of these to override the value
# build_palette would otherwise derive; absent ones stay auto-derived. Each is
# (palette_key, label). Some have companion colours (hovers/variants) that
# build_palette refreshes from the override so the result stays coherent.
ADVANCED_KEYS = (
    ("btn_run_bg",      "Run button"),
    ("error",           "Error / failed"),
    ("out_bg",          "Terminal background"),
    ("out_stdout",      "Terminal text"),
    ("out_stderr",      "Terminal error text"),
    ("out_status",      "Terminal status text"),
    ("accent2",         "Accent (pressed)"),
    ("btn_neutral_bg",  "Neutral button"),
    ("tab_inactive_bg", "Inactive tab"),
    ("pipe_accent",     "Pipeline accent"),
    ("bolt",            "Logo bolt"),
    ("warn_bg",         "Warning background"),
)
_ADVANCED_SET = frozenset(k for k, _ in ADVANCED_KEYS)

# User-created themes persist here, separate from settings.json (keeps each file
# small, mirroring the QR-index split).
CUSTOM_THEMES_PATH = DATA_DIR / "themes.json"

# Hardcoded fallback palettes for the two base themes. The live REFERENCE used
# everywhere is built at the bottom of this module: it starts from this fallback
# and is overridden by light.json / dark.json when those load. Keeping the
# fallback in code means the app still themes correctly if the JSON is missing.
_REFERENCE_FALLBACK: dict[str, dict] = {
    "light": {
        "bg":          "#f0f2f5",
        "card_bg":     "#ffffff",
        "card_hover":  "#f5f7ff",
        "status_bg":   "#e8ebf0",
        "header_bg":   "#1e2a3a",
        "border":      "#dde2ea",
        "accent":      "#4a6fa5",
        "accent2":     "#3d5d8a",
        "accent_wash": "#eef2ff",
        "bolt":        "#FFD23F",
        "bolt_hover":  "#e6bc00",
        "name_fg":      "#1a1a2e",
        "path_fg":      "#626975",
        "fg_on_dark":   "#ffffff",
        "fg_on_dark_2": "#aaaaaa",
        "tab_fg":       "#2d3748",
        "btn_fg":            "#ffffff",
        "btn_run_bg":        "#2ecc71",
        "btn_run_hover":     "#27ae60",
        "btn_mod_bg":        "#4a6fa5",
        "btn_mod_hover":     "#3d5d8a",
        "btn_create_bg":     "#4a6fa5",
        "btn_create_hover":  "#3d5d8a",
        "btn_neutral_bg":    "#eef1f6",
        "btn_neutral_hover": "#dde3ee",
        "btn_neutral_fg":    "#5a6573",
        "btn_stop_idle":           "#3a3a3a",
        "btn_stop_idle_fg":        "#666666",
        "btn_stop_idle_active_fg": "#888888",
        "btn_stop_idle_hover":     "#4a4a4a",
        "btn_stop_active":         "#8b0000",
        "btn_stop_active_hover":   "#5a1a1a",
        "btn_dark_bg":       "#3a3a3a",
        "btn_dark_hover":    "#555555",
        "tab_inactive_bg":    "#e4e9f0",
        "tab_inactive_hover": "#d8dfe8",
        "ok":          "#2ecc71",
        "running":     "#27ae60",
        "error":       "#c0392b",
        "warn_bg":     "#fff7e6",
        "warn_border": "#f3d99a",
        "warn_fg":     "#7a4a00",
        "pipe_accent":  "#5c4bbd",
        "pipe_accent2": "#7060d0",
        "out_bg":         "#1e1e1e",
        "out_header":     "#2d2d2d",
        "out_tabbar":     "#252525",
        "out_stdout":     "#d4d4d4",
        "out_stderr":     "#ff6b6b",
        "out_status":     "#5aa9e6",
        "out_success":    "#4ec97a",
        "menu_bg":        "#2d2d2d",
        "menu_danger":    "#ff8080",
        "tooltip_bg":     "#2d2d2d",
        "tooltip_border": "#555555",
    },
    "dark": {
        "bg":          "#14181f",
        "card_bg":     "#1d232d",
        "card_hover":  "#262e3a",
        "status_bg":   "#1a1f27",
        "header_bg":   "#0f141b",
        "border":      "#2c3440",
        "accent":      "#5b8bd0",
        "accent2":     "#4a72ad",
        "accent_wash": "#22304a",
        "bolt":        "#FFD23F",
        "bolt_hover":  "#e6bc00",
        "name_fg":     "#e8ebf0",
        "path_fg":     "#9aa3b2",
        "fg_on_dark":  "#ffffff",
        "fg_on_dark_2":"#aaaaaa",
        "tab_fg":      "#c2cad6",
        "btn_fg":            "#ffffff",
        "btn_run_bg":        "#2ecc71",
        "btn_run_hover":     "#27ae60",
        "btn_mod_bg":        "#5b8bd0",
        "btn_mod_hover":     "#4a72ad",
        "btn_create_bg":     "#5b8bd0",
        "btn_create_hover":  "#4a72ad",
        "btn_neutral_bg":    "#2a323e",
        "btn_neutral_hover": "#353f4e",
        "btn_neutral_fg":    "#c2cad6",
        "btn_stop_idle":           "#3a3a3a",
        "btn_stop_idle_fg":        "#777777",
        "btn_stop_idle_active_fg": "#999999",
        "btn_stop_idle_hover":     "#4a4a4a",
        "btn_stop_active":         "#a01818",
        "btn_stop_active_hover":   "#7a1414",
        "btn_dark_bg":       "#2a323e",
        "btn_dark_hover":    "#3a4452",
        "tab_inactive_bg":    "#222a35",
        "tab_inactive_hover": "#2c3440",
        "ok":          "#2ecc71",
        "running":     "#27ae60",
        "error":       "#e05a5a",
        "warn_bg":     "#3a2f1a",
        "warn_border": "#5c4a26",
        "warn_fg":     "#f0c980",
        "pipe_accent":  "#7c6bdd",
        "pipe_accent2": "#8f80e0",
        "out_bg":         "#1e1e1e",
        "out_header":     "#2d2d2d",
        "out_tabbar":     "#252525",
        "out_stdout":     "#d4d4d4",
        "out_stderr":     "#ff6b6b",
        "out_status":     "#5aa9e6",
        "out_success":    "#4ec97a",
        "menu_bg":        "#2d2d2d",
        "menu_danger":    "#ff8080",
        "tooltip_bg":     "#2d2d2d",
        "tooltip_border": "#555555",
    },
}

# 7-colour seeds for the two hard-coded built-ins, pulled from REFERENCE. The
# preset themes live as JSON under ryos/presets/ (one file per theme, same
# envelope as Export) and are loaded at import — see the registry build at the
# bottom of this module. SEEDS / THEME_ORDER / THEME_LABELS / THEME_MODES are
# assembled there from these base seeds plus the loaded presets.
_BASE_SEEDS: dict[str, dict] = {
    "light": {
        "mode": "light",
        "bg":         _REFERENCE_FALLBACK["light"]["bg"],
        "surface":    _REFERENCE_FALLBACK["light"]["card_bg"],
        "border":     _REFERENCE_FALLBACK["light"]["border"],
        "accent":     _REFERENCE_FALLBACK["light"]["accent"],
        "text":       _REFERENCE_FALLBACK["light"]["name_fg"],
        "text_muted": _REFERENCE_FALLBACK["light"]["path_fg"],
        "header_bg":  _REFERENCE_FALLBACK["light"]["header_bg"],
    },
    "dark": {
        "mode": "dark",
        "bg":         _REFERENCE_FALLBACK["dark"]["bg"],
        "surface":    _REFERENCE_FALLBACK["dark"]["card_bg"],
        "border":     _REFERENCE_FALLBACK["dark"]["border"],
        "accent":     _REFERENCE_FALLBACK["dark"]["accent"],
        "text":       _REFERENCE_FALLBACK["dark"]["name_fg"],
        "text_muted": _REFERENCE_FALLBACK["dark"]["path_fg"],
        "header_bg":  _REFERENCE_FALLBACK["dark"]["header_bg"],
    },
}
_REF_KEYS = frozenset(_REFERENCE_FALLBACK["light"])

# Folder of bundled preset theme files (one JSON per theme). Sits next to this
# module so it ships with the package; setup_cxfreeze.py bundles it into builds.
PRESETS_DIR = Path(__file__).resolve().parent / "presets"


def _shade(hex_str: str, factor: float) -> str:
    """Darken (factor < 0) or lighten (factor > 0) a #rrggbb hex color."""
    h = hex_str.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    if factor < 0:
        r = int(r * (1 + factor))
        g = int(g * (1 + factor))
        b = int(b * (1 + factor))
    else:
        r = int(r + (255 - r) * factor)
        g = int(g + (255 - g) * factor)
        b = int(b + (255 - b) * factor)
    return f"#{max(0, min(255, r)):02x}{max(0, min(255, g)):02x}{max(0, min(255, b)):02x}"


def _rel_luminance(hex_str: str) -> float:
    """WCAG relative luminance of a #rrggbb color, in [0, 1]."""
    h = hex_str.lstrip("#")
    chan = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255.0
        chan.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = chan
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(c1: str, c2: str) -> float:
    """WCAG contrast ratio between two #rrggbb colors (1.0 .. 21.0)."""
    l1, l2 = _rel_luminance(c1), _rel_luminance(c2)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def build_palette(seed: dict, overrides: dict | None = None) -> dict:
    """Expand a 7-colour seed into the full palette the UI consumes.

    Starts from the mode's REFERENCE palette (so every key is present and the
    not-user-edited colours — semantic badges, the terminal output panel, menus,
    tooltips, the signature bolt gold — get sensible mode defaults), then
    overlays the seed colours and the values derived from them. `overrides` pins
    exact values last (used by presets that want to hand-tune a few keys)."""
    mode = seed.get("mode", "light")
    light = mode != "dark"
    base = dict(REFERENCE["light" if light else "dark"])

    bg = seed["bg"]
    surface = seed["surface"]
    border = seed["border"]
    accent = seed["accent"]
    text = seed["text"]
    muted = seed["text_muted"]
    header = seed["header_bg"]
    accent2 = _shade(accent, -0.15)

    base.update({
        "bg":          bg,
        "card_bg":     surface,
        "border":      border,
        "header_bg":   header,
        "accent":      accent,
        "name_fg":     text,
        "path_fg":     muted,
        "tab_fg":      text,
        "card_hover":  _shade(surface, -0.03 if light else 0.10),
        "status_bg":   _shade(bg, -0.05 if light else 0.05),
        "accent2":     accent2,
        "accent_wash": _shade(accent, 0.86 if light else -0.55),
        "btn_mod_bg":        accent,
        "btn_mod_hover":     accent2,
        "btn_create_bg":     accent,
        "btn_create_hover":  accent2,
        "btn_neutral_bg":    _shade(surface, -0.06 if light else 0.08),
        "btn_neutral_hover": _shade(surface, -0.12 if light else 0.14),
        "btn_neutral_fg":    muted,
        "tab_inactive_bg":    _shade(bg, -0.05 if light else 0.06),
        "tab_inactive_hover": _shade(bg, -0.10 if light else 0.11),
    })

    # Optional advanced overrides: pin the chosen key and refresh any companion
    # colour (hover/variant) so buttons and tabs stay coherent.
    adv = {k: seed[k] for k, _ in ADVANCED_KEYS if is_hex_color(seed.get(k))}
    base.update(adv)
    if "btn_run_bg" in adv:
        base["btn_run_hover"] = _shade(adv["btn_run_bg"], -0.12)
    if "btn_neutral_bg" in adv:
        base["btn_neutral_hover"] = _shade(adv["btn_neutral_bg"], -0.10 if light else 0.12)
    if "tab_inactive_bg" in adv:
        base["tab_inactive_hover"] = _shade(adv["tab_inactive_bg"], -0.06 if light else 0.08)
    if "pipe_accent" in adv:
        base["pipe_accent2"] = _shade(adv["pipe_accent"], 0.12)
    if "accent2" in adv:
        base["btn_mod_hover"] = base["btn_create_hover"] = adv["accent2"]

    if overrides:
        base.update(overrides)
    return base


_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}")


def is_hex_color(value) -> bool:
    """True if value is a '#rrggbb' string."""
    return isinstance(value, str) and bool(_HEX_RE.fullmatch(value))


def validate_seed(seed) -> list[str]:
    """Return a list of hard problems with a seed (empty list = structurally
    valid). Used to gate saving and to filter a corrupt themes.json on load."""
    problems = []
    if not isinstance(seed, dict):
        return ["theme must be an object"]
    if seed.get("mode") not in ("light", "dark"):
        problems.append("mode must be 'light' or 'dark'")
    for key in SEED_KEYS:
        if not is_hex_color(seed.get(key)):
            problems.append(f"{key} must be a #rrggbb color")
    # Advanced colours are optional, but if present must be valid.
    for key in _ADVANCED_SET:
        if key in seed and not is_hex_color(seed[key]):
            problems.append(f"{key} must be a #rrggbb color")
    return problems


def contrast_warnings(seed) -> list[str]:
    """Soft, non-fatal readability warnings for a seed (shown in the editor)."""
    out = []
    pairs = [
        ("text", "bg", 4.5, "Primary text on the background is low contrast"),
        ("text", "surface", 4.5, "Primary text on cards is low contrast"),
        ("text_muted", "bg", 3.0, "Secondary text on the background is low contrast"),
    ]
    for fg, bgk, threshold, msg in pairs:
        if is_hex_color(seed.get(fg)) and is_hex_color(seed.get(bgk)):
            ratio = contrast_ratio(seed[fg], seed[bgk])
            if ratio < threshold:
                out.append(f"{msg} ({ratio:.1f}:1, aim for {threshold:.0f}:1).")
    return out


def load_custom_themes(path=None) -> dict:
    """Load user themes from themes.json as {name: seed}. Missing or corrupt
    file -> {} (with no raise); structurally invalid entries are dropped."""
    p = Path(path) if path is not None else CUSTOM_THEMES_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {name: seed for name, seed in data.items()
            if isinstance(name, str) and not validate_seed(seed)}


def save_custom_themes(themes: dict, path=None) -> None:
    """Persist {name: seed} to themes.json. Best-effort; never raises."""
    p = Path(path) if path is not None else CUSTOM_THEMES_PATH
    try:
        p.write_text(json.dumps(themes, indent=2), encoding="utf-8")
    except OSError:
        pass


THEME_FILE_VERSION = 1


def export_theme(name: str, seed: dict, path) -> None:
    """Write a single custom theme to a shareable JSON file (an envelope with a
    name + seed). Raises OSError if the file can't be written."""
    payload = {"ryos_theme": THEME_FILE_VERSION, "name": name, "seed": dict(seed)}
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def import_theme(path) -> tuple[str, dict]:
    """Read a theme JSON file and return (name, seed). Accepts the export
    envelope, a bare seed, or a single {name: seed} mapping. Raises ValueError
    with a readable message if the file is unreadable or the seed is invalid."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Could not read theme file: {exc}")

    name, seed = "", None
    if isinstance(data, dict) and isinstance(data.get("seed"), dict):
        name = data["name"] if isinstance(data.get("name"), str) else ""
        seed = data["seed"]
    elif isinstance(data, dict) and "mode" in data:
        seed = data
    elif isinstance(data, dict) and len(data) == 1:
        (key, value), = data.items()
        if isinstance(value, dict):
            name, seed = (key if isinstance(key, str) else ""), value

    if not isinstance(seed, dict):
        raise ValueError("Not a RYOS theme file.")
    problems = validate_seed(seed)
    if problems:
        raise ValueError("Invalid theme — " + "; ".join(problems))
    return name, seed


def _read_theme_files(directory=None) -> list[dict]:
    """Parsed theme JSON dicts (each with a string `id`), sorted by filename.
    Unreadable or id-less files are skipped (logged)."""
    d = Path(directory) if directory is not None else PRESETS_DIR
    out: list[dict] = []
    try:
        files = sorted(d.glob("*.json"))
    except OSError:
        return out
    for fp in files:
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _log.warning("Skipping theme %s: %s", fp.name, exc)
            continue
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            _log.warning("Skipping theme %s: missing id", fp.name)
            continue
        out.append(data)
    return out


def _is_full_palette(palette) -> bool:
    """True if `palette` is a complete, valid colour dict (every reference key)."""
    return (isinstance(palette, dict) and _REF_KEYS <= set(palette)
            and all(is_hex_color(palette[k]) for k in _REF_KEYS))


def load_base_themes(directory=None) -> list[tuple[str, str, dict, dict]]:
    """(id, label, palette, seed) for theme files carrying a full palette — the
    base themes (light/dark). The palette is used verbatim; the seed feeds the
    editor's "create from current" pre-fill."""
    out = []
    for data in _read_theme_files(directory):
        pal = data.get("palette")
        if not _is_full_palette(pal):
            continue
        pid = data["id"]
        seed = data.get("seed")
        if not (isinstance(seed, dict) and not validate_seed(seed)):
            seed = _BASE_SEEDS.get(pid)
        label = data.get("name")
        out.append((pid, label if isinstance(label, str) and label else pid.capitalize(),
                    pal, seed))
    return out


def load_presets(directory=None) -> list[tuple[str, str, dict]]:
    """(id, label, seed) for seed-only theme files (the presets — anything that
    isn't a base theme). Invalid files are skipped (logged)."""
    out = []
    for data in _read_theme_files(directory):
        pid = data["id"]
        if pid in ("light", "dark") or _is_full_palette(data.get("palette")):
            continue  # a base theme, handled by load_base_themes
        seed = data.get("seed")
        if not isinstance(seed, dict) or validate_seed(seed):
            _log.warning("Skipping preset %s: invalid seed", pid)
            continue
        label = data.get("name")
        out.append((pid, label if isinstance(label, str) and label else pid, seed))
    return out


def _builtin_palette(name: str) -> dict:
    """Base themes (light/dark) use their full REFERENCE palette verbatim
    (identical look); every other built-in is derived from its seed."""
    if name in _FIXED_IDS:
        return dict(REFERENCE[name])
    return build_palette(SEEDS[name])


# ---- Assemble the live registry from the bundled JSON, with code fallbacks ----
# REFERENCE starts from the hardcoded fallback and is overridden by light.json /
# dark.json when they load, so the app themes correctly even if the JSON is gone.
REFERENCE: dict[str, dict] = {k: dict(v) for k, v in _REFERENCE_FALLBACK.items()}
SEEDS: dict[str, dict] = dict(_BASE_SEEDS)
THEME_LABELS: dict[str, str] = {"light": "Light", "dark": "Dark"}
_FIXED_IDS: set[str] = {"light", "dark"}

for _bid, _blabel, _bpalette, _bseed in load_base_themes():
    REFERENCE[_bid] = _bpalette
    if _bseed:
        SEEDS[_bid] = _bseed
    THEME_LABELS[_bid] = _blabel
    _FIXED_IDS.add(_bid)

_PRESETS = load_presets()
for _pid, _plabel, _pseed in _PRESETS:
    SEEDS[_pid] = _pseed
    THEME_LABELS[_pid] = _plabel

# light/dark first, then presets in file order.
THEME_ORDER: list[str] = ["light", "dark", *[pid for pid, _, _ in _PRESETS]]
THEME_MODES: dict[str, str] = {name: SEEDS[name]["mode"] for name in THEME_ORDER}

# Built-in theme palettes the UI selects among, keyed by id.
BUILTIN_THEMES: dict[str, dict] = {name: _builtin_palette(name) for name in THEME_ORDER}
