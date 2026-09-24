"""The tray and the window's life: what shows, and what closing does.

Toolkit-free and pystray-free, so the Tk app (pystray) and the Qt shell
(`QSystemTrayIcon`) share one set of rules: the tooltip and menu for a
snapshot of running jobs, and what closing, minimising, starting minimised,
quitting and a second launch each do.
"""

from __future__ import annotations

from dataclasses import dataclass

# NOTIFYICONDATAW.szTip is WCHAR[128]; ctypes raises rather than truncating,
# so an over-long tooltip has to be clamped here or the update would fail.
TIP_MAX = 127
MENU_LABEL_MAX = 60

SHOW = "show"
EXIT = "exit"
_JOB_PREFIX = "job:"


def _ellipsize(text: str, limit: int) -> str:
    """Clamp text to `limit` characters, marking the cut with an ellipsis."""
    text = " ".join(text.split())          # tooltips collapse whitespace anyway
    if len(text) <= limit:
        return text
    return text[:limit - 1].rstrip() + "…"


def tray_title(job_names, base: str) -> str:
    """Tooltip text for a set of running jobs. Pure; `base` is the idle text.

    One job shows its full label (that is the interesting case when you are
    waiting on a pipeline); several collapse to a count plus names, because the
    128-character cap would truncate them into uselessness otherwise.
    """
    job_names = list(job_names)
    if not job_names:
        return _ellipsize(base, TIP_MAX)
    if len(job_names) == 1:
        return _ellipsize(f"{base} — {job_names[0]}", TIP_MAX)
    return _ellipsize(
        f"{base} — {len(job_names)} running: " + ", ".join(job_names), TIP_MAX)


@dataclass(frozen=True)
class TrayEntry:
    """One tray-menu row. ``key`` is None for a separator."""

    key: str | None
    label: str = ""
    default: bool = False


def job_key(job_id: int) -> str:
    return f"{_JOB_PREFIX}{job_id}"


def job_from_key(key: str) -> int | None:
    if not key.startswith(_JOB_PREFIX):
        return None
    try:
        return int(key[len(_JOB_PREFIX):])
    except ValueError:
        return None


def tray_menu(jobs) -> list[TrayEntry]:
    """Running jobs first, then Show / Exit.

    'Show RYOS' is the default action, so a click on the icon restores the
    window whatever is running.
    """
    entries = [TrayEntry(job_key(int(jid)), _ellipsize(str(label), MENU_LABEL_MAX))
               for jid, label in jobs]
    if entries:
        entries.append(TrayEntry(None))
    entries += [TrayEntry(SHOW, "Show RYOS", default=True), TrayEntry(None),
                TrayEntry(EXIT, "Exit")]
    return entries


# --- the window's life ------------------------------------------------------------

HIDE = "hide"            # to the tray
MINIMIZE = "minimize"    # to the taskbar, when there is no tray
PROMPT = "prompt"        # ask whether to hide or quit
QUIT = "quit"
NOTHING = "nothing"

PROMPT_TRAY = "tray"     # the answers CloseToTrayPromptDialog gives
PROMPT_QUIT = "quit"
PROMPT_CANCEL = "cancel"


def on_close(settings: dict, tray_available: bool) -> str:
    """What the window's close button does."""
    if not tray_available:
        return QUIT
    if settings.get("close_to_tray"):
        return HIDE
    if settings.get("prompt_close_to_tray", True):
        return PROMPT
    return QUIT


def after_prompt(settings: dict, answer: str, dont_ask: bool) -> tuple[str, bool]:
    """(what to do, whether to save settings) for a close-prompt answer.

    Updates ``settings`` in place. Choosing the tray remembers it, which also
    stops the prompt; "don't ask" alone only stops the prompt. Cancel -- the
    prompt dismissed any other way -- does nothing, never quits.
    """
    changed = False
    if dont_ask:
        settings["prompt_close_to_tray"] = False
        changed = True
    if answer == PROMPT_TRAY:
        settings["close_to_tray"] = True
        settings["prompt_close_to_tray"] = False
        return HIDE, True
    if answer == PROMPT_QUIT:
        return QUIT, changed
    return NOTHING, False


def on_minimize(tray_available: bool, hidden: bool) -> str:
    """Minimising goes to the tray when there is one."""
    return HIDE if tray_available and not hidden else NOTHING


def on_start(settings: dict, tray_available: bool) -> str:
    """Where a start-minimised launch puts the window."""
    if not settings.get("start_minimized"):
        return NOTHING
    return HIDE if tray_available else MINIMIZE


def restore_follows_cursor(verb: str) -> bool:
    """A second launch asked to restore the window on the cursor's monitor."""
    return verb == "RESTORE_CURSOR"


def quit_prompt(running: int) -> tuple[str, str] | None:
    """(title, question) before quitting with jobs alive, or None."""
    if running <= 0:
        return None
    label = "jobs are" if running > 1 else "job is"
    return ("Still Running",
            f"{running} script {label} still running. Exit anyway?")
