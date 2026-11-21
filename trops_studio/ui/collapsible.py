"""Panel s klikom na naslov: − razširi / + skrči (panela +/-)."""

from __future__ import annotations

import tkinter as tk
from typing import Callable


class CollapsibleSection(tk.Frame):
    """Panel s klikom na naslov: − (odprt) / + (zaprt)."""

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        *,
        bg: str,
        fg: str = "#f3f6ff",
        muted: str = "#a5b0c8",
        initially_open: bool = True,
        padx: int = 6,
        pady: int = 4,
        accent: str = "#6b4cff",
        on_toggle: Callable[[bool], None] | None = None,
    ) -> None:
        super().__init__(parent, bg=bg, highlightbackground=accent, highlightthickness=1)
        self._title = title
        self._open = bool(initially_open)
        self._on_toggle = on_toggle
        header = tk.Frame(self, bg=accent, cursor="hand2")
        header.pack(fill="x")
        self._hdr_lbl = tk.Label(
            header,
            text=self._header_text(),
            bg=accent,
            fg="#ffffff",
            font=("Segoe UI", 10, "bold"),
            anchor="w",
            cursor="hand2",
            padx=10,
            pady=6,
        )
        self._hdr_lbl.pack(side="left", fill="x", expand=True)
        self._hint = tk.Label(
            header,
            text=self._hint_text(),
            bg=accent,
            fg="#d7d0ff",
            font=("Segoe UI", 8, "bold"),
            cursor="hand2",
            padx=10,
            pady=6,
        )
        self._hint.pack(side="right")
        self._bind_header_click(header)
        self.body = tk.Frame(self, bg=bg, padx=padx, pady=pady)
        if self._open:
            self.body.pack(fill="x", expand=False)

    def _bind_header_click(self, widget: tk.Misc) -> None:
        widget.bind("<Button-1>", self._on_header_click)
        for child in widget.winfo_children():
            self._bind_header_click(child)

    def _on_header_click(self, _event: tk.Event | None = None) -> None:
        self.toggle()

    def _mark(self) -> str:
        return "−" if self._open else "+"

    def _header_text(self) -> str:
        return f"{self._mark()}  {self._title}"

    def _hint_text(self) -> str:
        return "klik: skrči  −" if self._open else "klik: razširi  +"

    def toggle(self) -> None:
        self.set_open(not self._open)

    def set_open(self, open_: bool) -> None:
        want = bool(open_)
        if want == self._open:
            return
        self._open = want
        self._hdr_lbl.configure(text=self._header_text())
        self._hint.configure(text=self._hint_text())
        if self._open:
            self.body.pack(fill="both" if getattr(self, "_expand_body", False) else "x", expand=bool(getattr(self, "_expand_body", False)))
        else:
            self.body.pack_forget()
        if self._on_toggle is not None:
            self._on_toggle(self._open)

    def set_expand_body(self, expand: bool = True) -> None:
        """Če True, body zapolni višino (za tabele v panelu)."""
        self._expand_body = bool(expand)
        if self._open:
            self.body.pack_forget()
            self.body.pack(fill="both", expand=True)
