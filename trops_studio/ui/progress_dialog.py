"""Modalni indikator napredka (sinhronizacija / dolgotrajni API klici)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable


class ProgressDialog(tk.Toplevel):
    """Preprost napredek z vrstico in sporočilom; UI ostane odziven."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        title: str = "Delam …",
        message: str = "Prosim počakaj …",
        cancelable: bool = False,
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_close_request)
        self._on_cancel = on_cancel
        self._cancelled = False
        self._closed = False

        self.geometry("460x140")
        self.minsize(420, 120)

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)

        self.msg_var = tk.StringVar(value=message)
        ttk.Label(frame, textvariable=self.msg_var, wraplength=420).pack(anchor="w", fill="x")

        self.detail_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.detail_var, style="Muted.TLabel", wraplength=420).pack(
            anchor="w", fill="x", pady=(6, 0)
        )

        self.bar = ttk.Progressbar(frame, mode="indeterminate", length=420)
        self.bar.pack(fill="x", pady=(12, 0))
        self.bar.start(12)

        self._pct_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self._pct_var, style="Muted.TLabel").pack(anchor="e", pady=(4, 0))

        if cancelable:
            btn = ttk.Button(frame, text="Prekini", command=self._request_cancel)
            btn.pack(anchor="e", pady=(8, 0))

        self.update_idletasks()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self._center_on(master)

    def _center_on(self, master: tk.Misc) -> None:
        try:
            self.update_idletasks()
            mw = master.winfo_rootx()
            mh = master.winfo_rooty()
            mw_w = master.winfo_width()
            mw_h = master.winfo_height()
            w = self.winfo_width()
            h = self.winfo_height()
            x = mw + max(0, (mw_w - w) // 2)
            y = mh + max(0, (mw_h - h) // 3)
            self.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def _request_cancel(self) -> None:
        self._cancelled = True
        self.detail_var.set("Prekinjam …")
        if self._on_cancel:
            self._on_cancel()

    def _on_close_request(self) -> None:
        # Med syncom ne zapri z X — samo preklic, če je na voljo
        if self._on_cancel:
            self._request_cancel()

    def set_message(self, text: str, *, detail: str = "") -> None:
        if self._closed:
            return
        self.msg_var.set(text)
        if detail:
            self.detail_var.set(detail)

    def set_progress(self, current: int, total: int, *, detail: str = "") -> None:
        """Determinate napredek; total<=0 → indeterminate."""
        if self._closed:
            return
        if detail:
            self.detail_var.set(detail)
        if total and total > 0:
            if str(self.bar["mode"]) != "determinate":
                self.bar.stop()
                self.bar.configure(mode="determinate", maximum=max(total, 1))
            self.bar["value"] = max(0, min(current, total))
            self.bar["maximum"] = max(total, 1)
            pct = int(100 * current / total) if total else 0
            self._pct_var.set(f"{current} / {total} ({pct} %)")
        else:
            if str(self.bar["mode"]) != "indeterminate":
                self.bar.configure(mode="indeterminate")
                self.bar.start(12)
            self._pct_var.set("")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.bar.stop()
        except tk.TclError:
            pass
        try:
            self.grab_release()
        except tk.TclError:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass
