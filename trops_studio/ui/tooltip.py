from __future__ import annotations

import tkinter as tk


class ToolTip:
    """Tooltip nad/pod gumbom; brez belega bliska v kotu zaslona."""

    def __init__(
        self,
        widget: tk.Widget,
        text: str,
        *,
        wraplength: int = 360,
        delay_ms: int = 450,
    ) -> None:
        self.widget = widget
        self.text = text
        self.wraplength = wraplength
        self.delay_ms = delay_ms
        self.window: tk.Toplevel | None = None
        self._after_id: str | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event: tk.Event | None = None) -> None:
        self._cancel_schedule()
        if not self.text:
            return
        try:
            self._after_id = self.widget.after(self.delay_ms, self._show)
        except tk.TclError:
            self._after_id = None

    def _cancel_schedule(self) -> None:
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except (tk.TclError, ValueError):
                pass
            self._after_id = None

    def _show(self) -> None:
        self._after_id = None
        if self.window or not self.text:
            return
        try:
            if not self.widget.winfo_ismapped():
                return
            self.widget.update_idletasks()
        except tk.TclError:
            return

        tip = tk.Toplevel(self.widget)
        self.window = tip
        tip.withdraw()
        tip.wm_overrideredirect(True)
        try:
            tip.configure(bg="#20345d")
        except tk.TclError:
            pass
        try:
            tip.wm_attributes("-topmost", True)
        except tk.TclError:
            pass

        tk.Label(
            tip,
            text=self.text,
            bg="#20345d",
            fg="#f3f6ff",
            relief="solid",
            borderwidth=1,
            padx=9,
            pady=5,
            font=("Segoe UI", 9),
            justify="left",
            wraplength=self.wraplength,
        ).pack()
        tip.update_idletasks()

        tip_w = max(tip.winfo_reqwidth(), 1)
        tip_h = max(tip.winfo_reqheight(), 1)

        wx = self.widget.winfo_rootx()
        wy = self.widget.winfo_rooty()
        wh = max(self.widget.winfo_height(), 1)
        ww = max(self.widget.winfo_width(), 1)

        screen_w = self.widget.winfo_screenwidth()
        screen_h = self.widget.winfo_screenheight()
        margin = 8
        taskbar = 48

        x = wx + 8
        y = wy - tip_h - 6  # privzeto NAD gumbom (spodnji gumbi)
        if y < margin:
            y = wy + wh + 6
        if y + tip_h + taskbar > screen_h:
            y = max(margin, screen_h - tip_h - taskbar)
        if y < margin:
            y = margin

        if x + tip_w + margin > screen_w:
            x = screen_w - tip_w - margin
        if x < margin:
            x = margin
        if wx + ww > screen_w - 80:
            x = max(margin, min(wx + ww - tip_w, screen_w - tip_w - margin))

        tip.wm_geometry(f"+{int(x)}+{int(y)}")
        try:
            tip.deiconify()
            tip.lift()
        except tk.TclError:
            self._hide()

    def _hide(self, _event: tk.Event | None = None) -> None:
        self._cancel_schedule()
        if self.window:
            try:
                self.window.destroy()
            except tk.TclError:
                pass
            self.window = None
