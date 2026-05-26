"""Reusable Tk widgets."""
import tkinter as tk
import tkinter.font as tkfont


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
