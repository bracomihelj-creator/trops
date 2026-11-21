"""Majhni barvni gumbi (kot KirKpr pill)."""

from __future__ import annotations

import tkinter as tk
from typing import Callable


class PillButton(tk.Label):
    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        command: Callable[[], None] | None = None,
        *,
        bg: str = "#3a4a6b",
        fg: str = "#ffffff",
        hover: str = "#4f8cff",
        padx: int = 12,
        pady: int = 5,
        **kwargs,
    ) -> None:
        super().__init__(
            parent,
            text=text,
            bg=bg,
            fg=fg,
            padx=padx,
            pady=pady,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
            **kwargs,
        )
        self._bg = bg
        self._hover = hover
        self._command = command
        self.bind("<Enter>", lambda _e: self.configure(bg=self._hover))
        self.bind("<Leave>", lambda _e: self.configure(bg=self._bg))
        self.bind("<Button-1>", self._click)

    def _click(self, _event: tk.Event | None = None) -> None:
        if self._command:
            self._command()

    def set_active(self, active: bool, *, active_bg: str = "#4f8cff", idle_bg: str | None = None) -> None:
        self._bg = active_bg if active else (idle_bg or "#3a4a6b")
        self.configure(bg=self._bg)


def pill(
    parent: tk.Misc,
    text: str,
    command: Callable[[], None] | None = None,
    *,
    kind: str = "grey",
) -> PillButton:
    palette = {
        "grey": ("#3a4a6b", "#ffffff", "#52658a"),
        "blue": ("#4f8cff", "#ffffff", "#6aa0ff"),
        "green": ("#34c77b", "#07170e", "#57dda0"),
        "yellow": ("#ffcc66", "#1a1400", "#f0c85a"),
        "purple": ("#8b7cff", "#ffffff", "#a296ff"),
    }
    bg, fg, hover = palette.get(kind, palette["grey"])
    return PillButton(parent, text, command, bg=bg, fg=fg, hover=hover)
