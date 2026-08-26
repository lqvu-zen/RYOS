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


class HoverPreview:
    """Delayed rich popup showing a builder-supplied preview of a card's details.

    Like Tooltip but the body is built by a caller-supplied ``builder(inner)``
    callback instead of a plain string, and leave-detection is containment-aware
    (walks up from the pointer's widget under it) so sweeping across a card's
    internal labels doesn't flicker the popup closed.
    """

    def __init__(self, card, anchor, builder, delay=1000):
        self._card = card
        self._anchor = anchor
        self._builder = builder
        self._delay = delay
        self._job = None
        self._verify_job = None
        self._popup = None

        self._bind_tree(anchor)
        card.bind("<Destroy>", self._on_destroy, add="+")

    def _bind_tree(self, widget):
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        # <Button-1>/<Button-3> are more specific than <ButtonPress> in Tk's
        # bind dispatch, so a widget with its own click handler (e.g. the
        # pipeline name label, or right-click menus) would never reach
        # <ButtonPress> — bind the concrete buttons too so a click always
        # dismisses the preview before an existing click popup opens.
        for seq in ("<ButtonPress>", "<Button-1>", "<Button-2>", "<Button-3>", "<MouseWheel>"):
            widget.bind(seq, self._on_press, add="+")
        for child in widget.winfo_children():
            self._bind_tree(child)

    def _on_enter(self, _e=None):
        self._cancel_verify()
        if self._popup:
            return
        if not self._job:
            try:
                self._job = self._card.after(self._delay, self._show)
            except tk.TclError:
                pass

    def _on_leave(self, _e=None):
        # <Leave> fires on the parent every time the pointer crosses into a
        # child widget, so an immediate hide would make the preview flicker
        # (or never appear) on a multi-label card. Verify shortly after.
        self._cancel_verify()
        try:
            self._verify_job = self._card.after(120, self._verify_left)
        except tk.TclError:
            pass

    def _on_press(self, _e=None):
        self._cancel_job()
        self._cancel_verify()
        self._hide()

    def _on_destroy(self, _e=None):
        self._cancel_job()
        self._cancel_verify()
        self._hide()

    def _verify_left(self):
        self._verify_job = None
        try:
            x, y = self._card.winfo_pointerxy()
            under = self._card.winfo_containing(x, y)
        except tk.TclError:
            under = None
        w = under
        while w is not None:
            if w is self._anchor:
                return  # pointer is still inside the anchor subtree
            w = w.master
        self._cancel_job()
        self._hide()

    def _cancel_job(self):
        if self._job:
            try:
                self._card.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def _cancel_verify(self):
        if self._verify_job:
            try:
                self._card.after_cancel(self._verify_job)
            except tk.TclError:
                pass
            self._verify_job = None

    def _show(self):
        self._job = None
        if self._popup:
            return
        try:
            x, y = self._card.winfo_pointerxy()
            popup = tk.Toplevel(self._card.winfo_toplevel())
            popup.wm_overrideredirect(True)
            popup.configure(bg=C["border"])
            inner = tk.Frame(popup, bg=C["card_bg"])
            inner.pack(padx=1, pady=1)
            self._builder(inner)

            popup.update_idletasks()
            pw, ph = popup.winfo_reqwidth(), popup.winfo_reqheight()
            sw, sh = popup.winfo_screenwidth(), popup.winfo_screenheight()
            # Flip to the other side of the pointer near a screen edge rather
            # than clamping in place — clamping can leave the popup sitting
            # under the pointer, which triggers <Leave> on the card and a
            # show/hide flicker loop.
            px = x + 16 if x + 16 + pw <= sw else x - pw - 16
            py = y + 20 if y + 20 + ph <= sh else y - ph - 20
            popup.geometry(f"+{max(0, px)}+{max(0, py)}")
            self._popup = popup
        except tk.TclError:
            self._popup = None

    def _hide(self):
        if self._popup:
            try:
                self._popup.destroy()
            except tk.TclError:
                pass
            self._popup = None


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
