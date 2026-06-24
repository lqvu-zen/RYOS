"""Reusable Tk widgets."""
import tkinter as tk
import tkinter.font as tkfont

from .theme import C


class Tooltip:
    """Delayed tooltip that appears near the pointer on hover."""

    def __init__(self, widget, text, delay=500):
        self._widget = widget
        self._text = text
        self._delay = delay
        self._job = None
        self._tip = None
        widget.bind("<Enter>",       self._on_enter,   add="+")
        widget.bind("<Leave>",       self._on_leave,   add="+")
        widget.bind("<ButtonPress>", self._on_leave,   add="+")
        widget.bind("<Destroy>",     self._on_destroy, add="+")

    def _on_enter(self, _e=None):
        self._cancel_job()
        self._job = self._widget.after(self._delay, self._show)

    def _on_leave(self, _e=None):
        self._cancel_job()
        self._hide()

    def _on_destroy(self, _e=None):
        self._cancel_job()
        self._hide()

    def _cancel_job(self):
        if self._job:
            try:
                self._widget.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def _show(self):
        if self._tip:
            return
        try:
            x, y = self._widget.winfo_pointerxy()
            self._tip = tk.Toplevel(self._widget)
            self._tip.wm_overrideredirect(True)
            self._tip.wm_geometry(f"+{x + 12}+{y + 18}")
            lbl = tk.Label(
                self._tip, text=self._text,
                bg=C["tooltip_bg"], fg=C["fg_on_dark"],
                font=("Segoe UI", 8),
                padx=6, pady=3,
                relief="flat", bd=1,
                highlightbackground=C["tooltip_border"], highlightthickness=1,
            )
            lbl.pack()
        except tk.TclError:
            self._tip = None

    def _hide(self):
        if self._tip:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None


class ScrollingLabel(tk.Canvas):
    """Clips and horizontally scrolls text that is wider than the widget."""
    _IDLE_MS = 1500
    _SPEED   = 1
    _TICK_MS = 25
    _GAP     = 80

    def __init__(self, parent, text, fg, bg, height=22):
        super().__init__(parent, bg=bg, highlightthickness=0, height=height)
        self._text   = text
        self._fg     = fg
        self._offset = 0
        self._job    = None
        self._tw     = 0
        self._font   = tkfont.Font(family="Segoe UI", size=11, weight="bold")

        self.bind("<Configure>", self._on_configure)
        self.bind("<Destroy>",   lambda e: self._cancel())
        self.bind("<Enter>",     lambda e: self._pause())
        self.bind("<Leave>",     lambda e: self._schedule())

    def _on_configure(self, e):
        self._tw = self._font.measure(self._text)
        self._offset = 0
        self._draw()
        self._schedule()

    def _draw(self):
        h = max(self.winfo_height(), 1)
        self.delete("all")
        self.create_text(-self._offset, h // 2,
                         text=self._text, font=self._font,
                         fill=self._fg, anchor="w")

    def _schedule(self):
        self._cancel()
        if self._tw > self.winfo_width():
            self._job = self.after(self._IDLE_MS, self._tick)

    def _tick(self):
        self._offset += self._SPEED
        self._draw()
        if self._offset >= self._tw + self._GAP:
            self._offset = 0
            self._draw()
            self._job = self.after(self._IDLE_MS, self._tick)
        else:
            self._job = self.after(self._TICK_MS, self._tick)

    def _pause(self):
        self._cancel()
        self._offset = 0
        self._draw()

    def _cancel(self):
        if self._job:
            self.after_cancel(self._job)
            self._job = None
