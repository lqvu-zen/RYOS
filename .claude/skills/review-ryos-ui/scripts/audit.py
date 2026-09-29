"""Measure what a UI review can measure, so the eye is spent on what it can't.

    uv run python .claude/skills/review-ryos-ui/scripts/audit.py [--theme ID ...]

Builds the real window off screen (the run-ryos driver: a throwaway data
folder loaded with samples/, nothing shown on any monitor), opens every
dialog the way the window does, and walks each screen's widgets. Writes
``.claude/discarded/ui-audit-<date>.md`` and prints a summary.

What it checks -- each finding is a lead to look at, not a verdict:

* **Target size** -- a clickable thing under 24x24 px (WCAG 2.2, 2.5.8).
* **Unnamed controls** -- a button whose text has no letters (a glyph or an
  icon) and no accessible name; with no tooltip either, nobody can tell
  what it does. A screen reader reads the glyph ("✎") or nothing.
* **Unlabelled inputs** -- a field no label is linked to (setBuddy, a form
  layout row, an accessible name or a placeholder).
* **Keyboard reach** -- an interactive widget with Qt.NoFocus.
* **Hover-only controls** -- hidden until the pointer comes (rows keep their
  space for them). Each needs another way in: the right-click menu, a key.
* **Clipped text** -- a label or button whose text is wider than its room
  (elided and scrolling labels are exempt: shortening is their job).
* **Default button** -- a dialog Enter does nothing in.
* **Tab order** -- Tab moving back up the dialog.
* **Contrast** -- key text/fill pairs in every shipped theme, measured.
* **Tokens** -- hard-coded colours in ryos/qtui/*.py, and every font size
  in use (a scale should have a handful).
* **Colour blindness** -- the main screenshots re-rendered as a person with
  deuteranopia sees them (``*_deutan.png`` beside the screenshots): Run,
  Retry, OK and Failed must still tell apart.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / ".claude" / "skills" / "run-ryos"))
import driver  # noqa: E402  -- points APPDATA at a throwaway folder on import

from PySide6.QtCore import QCoreApplication, QEvent, Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView,  # noqa: E402
                               QAbstractSpinBox, QCheckBox, QComboBox, QDialog,
                               QFormLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QRadioButton, QSlider, QTabBar,
                               QTextEdit, QWidget)

MIN_TARGET = 24
INTERACTIVE = (QAbstractButton, QLineEdit, QComboBox, QAbstractSpinBox,
               QAbstractItemView, QTabBar, QPlainTextEdit, QTextEdit, QSlider)
INPUTS = (QLineEdit, QComboBox, QAbstractSpinBox, QPlainTextEdit, QTextEdit)

# (label, foreground key, background key, minimum): the pairs a person reads
# most. drawn_colors() keys are prefixed "d:".
KEY_PAIRS = [
    ("row name", "name_fg", "card_bg", 4.5),
    ("row path / muted text", "d:muted_fg", "card_bg", 4.5),
    ("muted text on window", "d:muted_fg", "bg", 4.5),
    ("idle group pill", "d:pill_idle_fg", "bg", 4.5),
    ("chosen group pill", "d:pill_fg", "name_fg", 4.5),
    ("header text", "d:header_fg", "header_bg", 4.5),
    ("primary button", "d:primary_fg", "accent", 4.5),
    ("links / selected tab", "d:tab_selected_fg", "card_bg", 3.0),
    ("Run glyph", "btn_run_fg", "btn_run_bg", 3.0),
    ("status bar", "d:status_fg", "status_bg", 4.5),
    ("output text", "out_stdout", "out_bg", 4.5),
    ("output errors", "out_stderr", "out_bg", 4.5),
]


# -- walking a screen -------------------------------------------------------------------
def _name(w: QWidget) -> str:
    text = w.text() if hasattr(w, "text") and callable(w.text) else ""
    text = (text or "").replace("&&", "&").strip()
    label = w.objectName() or type(w).__name__
    return f"{label} {text!r}" if text else label


def _has_letters(text: str) -> bool:
    return any(ch.isalpha() for ch in text)


def _labelled(w: QWidget, top: QWidget) -> bool:
    if w.accessibleName():
        return True
    if isinstance(w, QLineEdit) and w.placeholderText():
        return True
    if isinstance(w, QComboBox) and w.isEditable() and w.lineEdit().placeholderText():
        return True
    # The field, or the row widget it sits in (a field with a Browse button
    # beside it): a label may point at either.
    chain = [w]
    while chain[-1] is not top and chain[-1].parentWidget() is not None:
        chain.append(chain[-1].parentWidget())
    for label in top.findChildren(QLabel):
        if label.buddy() in chain:
            return True
    # Form layouts nest inside other layouts, so look at every one.
    for form in top.findChildren(QFormLayout):
        if any(form.labelForField(x) is not None for x in chain):
            return True
    return False


def _clipped(w: QWidget) -> bool:
    if type(w).__name__ in ("ElidedLabel", "ScrollingLabel"):
        return False
    if isinstance(w, QLabel):
        if w.wordWrap() or not w.text() or w.textFormat() == Qt.TextFormat.RichText \
                or w.text().lstrip().startswith("<"):
            return False
        fm = w.fontMetrics()
        need = max(fm.horizontalAdvance(line) for line in w.text().splitlines())
        return need > w.contentsRect().width() + 2
    if isinstance(w, QPushButton) and w.text():
        need = w.fontMetrics().horizontalAdvance(w.text().replace("&&", "&"))
        room = w.width() - 8 - (w.iconSize().width() + 4 if not w.icon().isNull() else 0)
        return need > room + 2
    return False


def _tab_jumps(top: QWidget) -> list[str]:
    """Places where Tab goes back up the screen by more than a row."""
    start = top.focusWidget() or top
    seen, chain = set(), []
    w = start.nextInFocusChain()
    while w is not None and id(w) not in seen and len(chain) < 300:
        seen.add(id(w))
        if (w.isVisibleTo(top) and w.focusPolicy() & Qt.FocusPolicy.TabFocus
                and w.isEnabled() and top.isAncestorOf(w)):
            chain.append(w)
        w = w.nextInFocusChain()
        if w is start:
            break
    jumps = []
    for a, b in zip(chain, chain[1:]):
        ya, yb = a.mapTo(top, a.rect().topLeft()).y(), b.mapTo(top, b.rect().topLeft()).y()
        if yb < ya - 20 and b is not chain[0]:
            jumps.append(f"{_name(a)} → {_name(b)} (up {ya - yb}px)")
    return jumps


def audit_screen(name: str, top: QWidget, findings: dict) -> None:
    """Walk ``top``'s widgets and file what each check finds under ``name``."""
    # Rows a reload replaced are only deleted when the loop gets to it.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    # The rows as they are at rest: the real pointer may sit over the
    # (invisible) window and have hovered some.
    cards = [w for w in top.findChildren(QWidget) if hasattr(w, "set_hovered")]
    for card in cards:
        card.set_hovered(False)
    driver.pump(0.2)
    widgets = [w for w in top.findChildren(QWidget) if w.isVisibleTo(top)
               # Qt's own parts of a spin box or combo box are the box.
               and not isinstance(w.parentWidget(), (QComboBox, QAbstractSpinBox))]
    hover_only = [b for card in cards for b in getattr(card, "_hover_only", ())
                  if isinstance(b, QAbstractButton)]
    add = findings[name]
    for w in widgets:
        if isinstance(w, QAbstractButton) and not isinstance(w, QTabBar):
            # A check box or radio button with a label is clickable along
            # its label, which makes the target wide; 16 px tall will do.
            labelled_tick = (isinstance(w, (QCheckBox, QRadioButton)) and w.text()
                             and w.height() >= 16)
            if (w.width() < MIN_TARGET or w.height() < MIN_TARGET) and not labelled_tick:
                add["target"].append(f"{_name(w)} is {w.width()}x{w.height()}")
            text = (w.text() or "").replace("&", "")
            if not _has_letters(text) and not w.accessibleName():
                tip = w.toolTip()
                add["unnamed"].append(f"{_name(w)}" + (f" (tooltip {tip!r} only)"
                                                       if tip else " -- no tooltip either"))
        if isinstance(w, INPUTS) and not (isinstance(w, (QPlainTextEdit, QTextEdit))
                                          and w.isReadOnly()):
            if not _labelled(w, top):
                add["unlabelled"].append(_name(w))
        if isinstance(w, INTERACTIVE) and w.focusPolicy() == Qt.FocusPolicy.NoFocus \
                and w.isEnabled():
            add["keyboard"].append(_name(w))
        if _clipped(w):
            add["clipped"].append(f"{_name(w)} ({w.width()}px)")
    for b in hover_only:            # hidden at rest, but controls all the same
        if not _has_letters((b.text() or "").replace("&", "")) and not b.accessibleName():
            add["unnamed"].append(f"{_name(b)} (hover-only; tooltip {b.toolTip()!r})")
    if hover_only:
        kinds = Counter(b.toolTip() or _name(b) for b in hover_only)
        add["hover"].append(f"{len(hover_only)} buttons on {len(cards)} rows: "
                            + ", ".join(f"{k} ×{n}" for k, n in kinds.most_common()))
    if isinstance(top, QDialog):
        buttons = [b for b in top.findChildren(QPushButton) if b.isVisibleTo(top)]
        if buttons and not any(b.isDefault() or b.autoDefault() for b in buttons):
            add["default"].append("no default button: Enter does nothing")
        add["taborder"].extend(_tab_jumps(top))


# -- colour and tokens ----------------------------------------------------------------------
def contrast_table() -> list[str]:
    from ryos.qtui.stylesheet import drawn_colors
    from ryos.themes import contrast_ratio, load_user_themes, resolve_palette, theme_choices
    customs = load_user_themes(ROOT / "theme-gallery")
    rows = []
    for theme_id, label in theme_choices(customs):
        pal = resolve_palette(theme_id, customs)
        d = drawn_colors(pal)
        for what, fg, bg, floor in KEY_PAIRS:
            f = d[fg[2:]] if fg.startswith("d:") else pal[fg]
            b = d[bg[2:]] if bg.startswith("d:") else pal[bg]
            ratio = contrast_ratio(f, b)
            if ratio < floor:
                rows.append(f"| {label} | {what} | `{f}` on `{b}` | {ratio:.2f} | {floor} |")
    return rows


def token_findings() -> tuple[list[str], Counter]:
    hexes, sizes = [], Counter()
    hex_re = re.compile(r"""["'][^"'\n]*?(#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3})\b""")
    size_re = re.compile(r"font-size:\s*\{?([\d.]+)\}?\s*(pt|px)")
    for path in sorted((ROOT / "ryos" / "qtui").glob("*.py")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0] if not line.lstrip().startswith(("f\"", "\"", "'")) \
                else line
            m = hex_re.search(line)
            if m and "c.get(" not in line and "noqa" not in line and code.strip():
                hexes.append(f"`{path.relative_to(ROOT).as_posix()}:{n}` {m.group(1)}")
            for size, unit in size_re.findall(line):
                sizes[f"{size}{unit}"] += 1
    return hexes, sizes


# -- colour blindness -------------------------------------------------------------------------
# Machado, Oliveira & Fernandes (2009), deuteranopia at full severity.
DEUTAN = ((0.367322, 0.860646, -0.227968),
          (0.280085, 0.672501, 0.047413),
          (-0.011820, 0.042940, 0.968881))


def simulate_deutan(src: Path) -> Path:
    img = QImage(str(src)).convertToFormat(QImage.Format.Format_RGB32)
    w, h = img.width(), img.height()
    buf = bytearray(img.constBits().tobytes())
    (a, b, c), (d, e, f), (g, hh, i) = DEUTAN
    cache: dict = {}
    for k in range(0, len(buf), 4):
        key = bytes(buf[k:k + 3])
        out = cache.get(key)
        if out is None:
            bl, gr, rd = key
            r2 = a * rd + b * gr + c * bl
            g2 = d * rd + e * gr + f * bl
            b2 = g * rd + hh * gr + i * bl
            out = bytes(max(0, min(255, int(v))) for v in (b2, g2, r2))
            cache[key] = out
        buf[k:k + 3] = out
    sim = QImage(bytes(buf), w, h, img.bytesPerLine(), QImage.Format.Format_RGB32).copy()
    dest = src.with_name(src.stem + "_deutan.png")
    sim.save(str(dest))
    return dest


# -- driving the screens ------------------------------------------------------------------------
def audit_theme(theme: str, findings: dict, shots: list) -> None:
    # Explicit: the compact window below saves its mode to the (throwaway)
    # settings, and the next theme's window would open compact.
    win = driver.window(theme, compact_mode=False)
    audit_screen(f"{theme}: main window", win, findings)
    shots.append(driver.shot(win, f"audit_main_{theme}"))
    # A failure, so Retry and "Failed" are on screen for the colour check.
    driver.card(win, "Always fails").run_button.click()
    driver.card(win, "Say hello").run_button.click()
    driver.idle(win)
    shots.append(driver.shot(win, f"audit_outcomes_{theme}"))

    def dialog(dlg):
        dlg.setAttribute(driver.HIDDEN)
        dlg.show()
        audit_screen(f"{theme}: {type(dlg).__name__}", dlg, findings)
        dlg.reject()
    win.run_dialog = dialog
    hello = driver.script_id("Say hello")
    win.edit_script(hello)
    from ryos.db import ScriptDB
    pid = next(p[0] for p in ScriptDB().list_pipelines("Samples") if p[1] == "Resilient")
    win.on_card_menu("pipeline", pid, "edit")
    win.on_card_menu("script", hello, "schedule")
    win.on_card_menu("script", hello, "history")
    win.open_options()
    win.open_appearance()
    win.new_group()
    win.resize(1280, 760)
    win.set_workspace(True)
    driver.card(win, "Say hello").activated.emit()
    audit_screen(f"{theme}: maximised", win, findings)
    win.bridge.stop()
    win.close()
    compact = driver.window(theme, compact_mode=True)
    audit_screen(f"{theme}: compact", compact, findings)
    compact.bridge.stop()
    compact.close()


TITLES = {
    "target": "Targets under 24x24 px",
    "unnamed": "Buttons with no name (glyph or icon only, no accessible name)",
    "unlabelled": "Inputs with no linked label",
    "keyboard": "Interactive widgets Tab can't reach (Qt.NoFocus)",
    "hover": "Hover-only controls (need another way in)",
    "clipped": "Text wider than its room",
    "default": "Dialogs with no default button",
    "taborder": "Tab order moving back up",
}


def write_report(findings: dict, contrast: list, hexes: list, sizes: Counter,
                 sims: list) -> Path:
    today = _dt.date.today().isoformat()
    out = ROOT / ".claude" / "discarded" / f"ui-audit-{today}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# RYOS UI audit ({today})", "",
             "Measured by `review-ryos-ui/scripts/audit.py`. Leads to check, not verdicts:",
             "a finding may be right for RYOS -- say why when you keep it.", ""]
    totals = Counter()
    for screen, checks in findings.items():
        for key, items in checks.items():
            totals[key] += len(items)
    lines += ["## Summary", "", "| Check | Count |", "|---|---|"]
    lines += [f"| {TITLES[k]} | {totals[k]} |" for k in TITLES]
    lines += [f"| Key colour pairs under their minimum (all themes) | {len(contrast)} |",
              f"| Hard-coded colours in ryos/qtui | {len(hexes)} |",
              f"| Distinct font sizes | {len(sizes)} |", ""]
    for key, title in TITLES.items():
        per = {s: c[key] for s, c in findings.items() if c[key]}
        if not per:
            continue
        lines += [f"## {title}", ""]
        for screen, items in per.items():
            lines.append(f"**{screen}**")
            for item, n in Counter(items).most_common():
                lines.append(f"- {item}" + (f"  ×{n}" if n > 1 else ""))
            lines.append("")
    lines += ["## Contrast below minimum", ""]
    lines += (["| Theme | Pair | Colours | Ratio | Minimum |", "|---|---|---|---|---|"]
              + contrast if contrast else ["Every key pair clears its minimum in every theme."])
    lines += ["", "## Hard-coded colours in ryos/qtui", ""]
    lines += [f"- {h}" for h in hexes] or ["None."]
    lines += ["", "## Font sizes in use", "",
              ", ".join(f"{s} ×{n}" for s, n in sorted(sizes.items(),
                                                     key=lambda kv: float(kv[0][:-2]))),
              "", "## Colour-blindness simulations (deuteranopia)", ""]
    lines += [f"- `{p.relative_to(ROOT).as_posix()}`" for p in sims]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--theme", nargs="*", default=["light", "dark"])
    args = parser.parse_args()
    driver.load_samples()
    findings: dict = defaultdict(lambda: defaultdict(list))
    shots: list = []
    for theme in args.theme:
        audit_theme(theme, findings, shots)
    sims = [simulate_deutan(p) for p in shots]
    contrast = contrast_table()
    hexes, sizes = token_findings()
    report = write_report(findings, contrast, hexes, sizes, sims)
    print(f"audit written: {report.relative_to(ROOT)}")
    for key, title in TITLES.items():
        n = sum(len(c[key]) for c in findings.values())
        print(f"  {n:4d}  {title}")
    print(f"  {len(contrast):4d}  key colour pairs under their minimum")
    print(f"  {len(hexes):4d}  hard-coded colours; {len(sizes)} distinct font sizes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
