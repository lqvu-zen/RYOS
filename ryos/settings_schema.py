"""What each setting is, so a form can be built from data rather than by hand.

`ui/dialogs.AdvancedOptionsDialog` builds five tabs of controls and then parses
them back in `_save`, where the numeric fields were five near-identical
``try/except ValueError`` blocks differing only in their bounds and fallback.
That arithmetic is the same whichever toolkit draws the form, so it lives here
and both front-ends coerce through it (docs/plans/qt-migration.md).

Pure: no toolkit, no widget, no settings file. `coerce()` never raises and
never returns something the app cannot use — an unparseable entry falls back
to the documented default rather than propagating a bad value into settings.
"""

from __future__ import annotations

from dataclasses import dataclass

from .settings import _SETTINGS_DEFAULTS

# Tabs, in the order the dialog shows them.
APPEARANCE = "Appearance"
STARTUP = "Startup & Window"
OUTPUT = "Output"
QUICK_RUN = "Quick Run"
LOGGING = "Logging"
TABS = (APPEARANCE, STARTUP, OUTPUT, QUICK_RUN, LOGGING)

# Control kinds a front-end must be able to draw.
BOOL = "bool"
INT = "int"
TEXT = "text"
CHOICE = "choice"
LIST = "list"


@dataclass(frozen=True)
class Field:
    """One setting: what it is, where it belongs, and what values are legal."""

    key: str
    kind: str
    label: str
    tab: str
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple = ()
    help: str = ""
    #: What an empty box means, when that is not simply the default. In the
    #: Tk dialog this was implicit in `int(entry.get() or N)` guards, where N
    #: was sometimes the minimum rather than the default -- clearing
    #: "Maximum parallel jobs" meant *no limit*, not "back to 10". Recorded
    #: rather than changed.
    empty: int | None = None

    @property
    def default(self):
        return _SETTINGS_DEFAULTS[self.key]

    @property
    def on_empty(self):
        """The value an empty entry produces."""
        return self.default if self.empty is None else self.empty


#: Every setting the options dialog exposes. Settings not listed here are
#: internal state the user never edits directly (window_geometry, last_group,
#: theme and accent_color, which the Appearance tab drives through its own
#: previewing controls rather than a plain field).
FIELDS: tuple[Field, ...] = (
    # -- Appearance --------------------------------------------------------
    Field("compact_mode", BOOL, "Compact cards (denser layout)", APPEARANCE),
    Field("card_size", CHOICE, "Card size", APPEARANCE,
          choices=("small", "medium", "large")),
    Field("hover_preview", BOOL, "Show details on hover (compact mode)",
          APPEARANCE),
    # -- Startup & window --------------------------------------------------
    Field("always_on_top", BOOL, "Keep window on top", STARTUP),
    Field("snap_corner", CHOICE, "Snap to corner", STARTUP,
          choices=("none", "top_left", "top_right", "bottom_left",
                   "bottom_right")),
    Field("window_width", INT, "Window width", STARTUP, minimum=400,
          help="Below 400 the button strip clips."),
    Field("window_height", INT, "Window height", STARTUP, minimum=300),
    Field("remember_last_group", BOOL, "Reopen the last group", STARTUP),
    Field("remember_window_geometry", BOOL, "Remember window position", STARTUP),
    Field("open_on_cursor_monitor", BOOL, "Open on the monitor under the cursor",
          STARTUP),
    Field("start_minimized", BOOL, "Start minimised", STARTUP),
    Field("close_to_tray", BOOL, "Close to tray instead of exiting", STARTUP),
    Field("prompt_close_to_tray", BOOL, "Ask before closing to tray", STARTUP),
    # -- Output ------------------------------------------------------------
    Field("max_output_lines", INT, "Maximum output lines", OUTPUT, minimum=100,
          help="Older lines are dropped; a low cap keeps a flooding script "
               "from filling memory.", empty=100),
    Field("max_parallel_jobs", INT, "Maximum parallel jobs", OUTPUT, minimum=0,
          help="0 means no limit.", empty=0),
    Field("launcher_release_seconds", INT, "Launcher release delay (s)", OUTPUT,
          minimum=0,
          help="How long a launcher script is held before the pipeline moves "
               "on.", empty=0),
    Field("auto_open_output", BOOL, "Open the output panel on run", OUTPUT),
    Field("auto_clear_output", BOOL, "Clear output between runs", OUTPUT),
    Field("auto_scroll_output", BOOL, "Scroll to the newest output", OUTPUT),
    Field("notify_on_complete", BOOL, "Notify when a run finishes", OUTPUT),
    Field("history_retention_days", INT, "Keep run history for (days)", OUTPUT,
          minimum=0, help="0 disables pruning; history is kept forever."),
    # -- Quick Run ---------------------------------------------------------
    Field("quick_run_enabled", BOOL, "Enable the Quick Run bar", QUICK_RUN),
    Field("quick_run_autocomplete", BOOL, "Suggest as you type", QUICK_RUN),
    Field("quick_run_index_extensions", LIST, "Indexed extensions", QUICK_RUN,
          help="Blank indexes every file."),
    Field("quick_run_index_max_files", INT, "Maximum files indexed", QUICK_RUN,
          minimum=0, empty=0),
    Field("quick_run_index_ttl", INT, "Index lifetime (s)", QUICK_RUN,
          minimum=0),
    Field("quick_run_max_suggestions", INT, "Suggestions shown", QUICK_RUN,
          minimum=1),
    # -- Logging -----------------------------------------------------------
    Field("logging_enabled", BOOL, "Write a log file", LOGGING),
    Field("log_level", CHOICE, "Log level", LOGGING,
          choices=("DEBUG", "INFO", "WARNING", "ERROR")),
    Field("log_runs_output", BOOL, "Log script output too", LOGGING),
    Field("auto_check_update", BOOL, "Check for updates on start", LOGGING),
    Field("themes_dir", TEXT, "Themes folder", APPEARANCE),
)

BY_KEY: dict[str, Field] = {f.key: f for f in FIELDS}


def fields_for(tab: str) -> tuple[Field, ...]:
    """The fields on one tab, in declaration order."""
    return tuple(f for f in FIELDS if f.tab == tab)


def coerce(key: str, raw):
    """A usable value for ``key`` from whatever the form produced.

    Never raises. An entry that cannot be read falls back to the documented
    default rather than letting a bad value into settings, which is what the
    five hand-written try/except blocks in `_save` were each doing.
    """
    spec = BY_KEY.get(key)
    if spec is None:
        return raw
    if spec.kind == BOOL:
        return bool(raw)
    if spec.kind == INT:
        text = str(raw).strip()
        if not text:
            return clamp(spec.on_empty, spec)
        try:
            value = int(text)
        except (TypeError, ValueError):
            return spec.default
        return clamp(value, spec)
    if spec.kind == CHOICE:
        return raw if raw in spec.choices else spec.default
    if spec.kind == LIST:
        if isinstance(raw, (list, tuple)):
            return list(raw)
        return spec.default
    return "" if raw is None else str(raw)


def clamp(value: int, spec: Field) -> int:
    """Pull an integer inside the field's bounds."""
    if spec.minimum is not None:
        value = max(spec.minimum, value)
    if spec.maximum is not None:
        value = min(spec.maximum, value)
    return value


def coerce_all(raw: dict) -> dict:
    """Coerce every known key in ``raw``, passing anything unknown through."""
    return {k: coerce(k, v) for k, v in raw.items()}
