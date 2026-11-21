"""Combobox z živim filtrom — tipkanje filtrira, konto se potrdi šele ob izbiri."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Any, Callable, Sequence


_NAV_KEYS = frozenset(
    {
        "Up",
        "Down",
        "Left",
        "Right",
        "Return",
        "KP_Enter",
        "Tab",
        "Escape",
        "Prior",
        "Next",
        "Home",
        "End",
        "BackSpace",
        "Delete",
    }
)


class FilteredCombobox(ttk.Combobox):
    """
    Editable Combobox z ločenim prikazom in potrjeno vrednostjo.

    - med tipkanjem se filtrira seznam; textvariable (konto) se NE spreminja
    - ob izbiri / Enter / FocusOut (veljavna šifra) se vrednost potrdi
    - prepreči ttk autocomplete, ki pokvari »41« → »4 — …«
    """

    def __init__(
        self,
        master: Any = None,
        *,
        filter_provider: Callable[[str], Sequence[str]] | None = None,
        select_all_on_focus: bool = True,
        textvariable: tk.Variable | None = None,
        **kwargs: Any,
    ) -> None:
        values = kwargs.pop("values", ())
        self._all_values: list[str] = [str(v) for v in (values or ())]
        self._filter_provider = filter_provider
        self._filtering = False
        self._typing = False
        self._committing = False
        self._syncing = False
        self._typed = ""
        self._expanded = False

        # Poslovna vrednost (odhodek…) — samo ob commit
        self._commit_var = textvariable
        self._display_var = tk.StringVar()
        if textvariable is not None:
            try:
                self._display_var.set(str(textvariable.get() or ""))
            except tk.TclError:
                pass
            textvariable.trace_add("write", self._on_commit_var_external)
        kwargs["textvariable"] = self._display_var
        kwargs["values"] = tuple(self._all_values)
        super().__init__(master, **kwargs)
        if str(self.cget("state")) == "readonly":
            return
        self.bind("<KeyPress>", self._on_keypress, add="+")
        self.bind("<KeyRelease>", self._on_keyrelease, add="+")
        self.bind("<<ComboboxSelected>>", self._on_selected, add="+")
        self.bind("<FocusOut>", self._on_focus_out, add="+")
        self.bind("<Return>", self._on_return, add="+")
        self.bind("<FocusIn>", self._on_focus_in, add="+")
        self.bind("<ButtonPress-1>", self._on_press_widen, add="+")
        self.bind("<Down>", self._on_press_widen, add="+")
        self.bind("<Alt-Down>", self._on_press_widen, add="+")
        if not select_all_on_focus:
            self._select_all_on_focus = False
        else:
            self._select_all_on_focus = True

    # --- javni API ---------------------------------------------------------

    def get(self) -> str:  # type: ignore[override]
        """Pri tipkanju vrni prikaz; sicer potrjeno vrednost."""
        if self._typing:
            return str(self._display_var.get() or "")
        if self._commit_var is not None:
            try:
                return str(self._commit_var.get() or "")
            except tk.TclError:
                pass
        return str(self._display_var.get() or "")

    def set_values(self, values: Sequence[Any]) -> None:
        self._all_values = [str(v) for v in values]
        if self._typing:
            return
        if self._filter_provider is not None and len(self._all_values) > 80:
            self._set_display_values(self._all_values[:80])
        else:
            self._set_display_values(self._all_values)

    def set_universe(self, values: Sequence[Any]) -> None:
        self._all_values = [str(v) for v in values]

    def is_typing(self) -> bool:
        return bool(self._typing)

    # --- interno -----------------------------------------------------------

    def configure(self, cnf: Any = None, **kwargs: Any) -> Any:
        if isinstance(cnf, dict):
            kwargs = {**cnf, **kwargs}
            cnf = None
        if "values" in kwargs and not self._filtering:
            self._all_values = [str(v) for v in (kwargs["values"] or ())]
        return super().configure(cnf, **kwargs)

    config = configure

    def _set_display_values(self, values: Sequence[str]) -> None:
        self._filtering = True
        try:
            super().configure(values=tuple(values))
        finally:
            self._filtering = False

    def _on_commit_var_external(self, *_args: object) -> None:
        if self._typing or self._committing or self._syncing:
            return
        if self._commit_var is None:
            return
        self._syncing = True
        try:
            self._display_var.set(self._normalize_code(str(self._commit_var.get() or "")))
        finally:
            self._syncing = False

    def _needle(self, raw: str) -> str:
        text = str(raw or "").strip()
        if not text:
            return ""
        if "—" in text:
            left = text.split("—", 1)[0].strip()
            return left
        return text

    def _matches(self, needle: str) -> list[str]:
        if self._filter_provider is not None:
            try:
                return [str(v) for v in self._filter_provider(needle)]
            except Exception:
                pass
        text = str(needle or "").casefold().strip()
        if not text:
            return list(self._all_values)
        prefix = [v for v in self._all_values if v.casefold().startswith(text)]
        rest = [
            v
            for v in self._all_values
            if text in v.casefold() and not v.casefold().startswith(text)
        ]
        return prefix + rest

    def _exact_or_unique_match(self, needle: str) -> str | None:
        n = self._needle(needle)
        if not n:
            return None
        matches = self._matches(n)
        if not matches:
            return None
        # natančna šifra
        for label in matches:
            code = label.split("—", 1)[0].strip()
            if code.casefold() == n.casefold() or label.casefold() == n.casefold():
                return label
        # edini zadetek
        if len(matches) == 1:
            return matches[0]
        return None

    def _put_display(self, text: str) -> None:
        """Nastavi prikaz brez sprožitve commit."""
        self._syncing = True
        try:
            self._display_var.set(text)
            try:
                self.icursor("end")
                self.selection_clear()
            except tk.TclError:
                pass
        finally:
            self._syncing = False

    @staticmethod
    def _normalize_code(value: str) -> str:
        text = str(value or "").strip()
        if "—" in text:
            text = text.split("—", 1)[0].strip()
        if not text or text in {"0", "0000"}:
            return ""
        return text

    def _commit(self, label_or_code: str) -> None:
        text = str(label_or_code or "").strip()
        code = self._normalize_code(text)
        self._typing = False
        self._typed = ""
        # Prikaz: oznaka iz seznama, sicer gola šifra
        display = text if (code and "—" in text) else code
        self._put_display(display)
        if self._commit_var is None:
            return
        # V SQL/poslovno vrednost vedno samo šifra (nikoli 0000)
        self._committing = True
        try:
            self._commit_var.set(code)
        finally:
            self._committing = False

    def _combo_font(self) -> tkfont.Font:
        raw = str(self.cget("font") or "") or "TkDefaultFont"
        try:
            return tkfont.nametofont(raw)
        except tk.TclError:
            return tkfont.Font(font=raw)

    def _needed_width_px(self) -> int:
        font = self._combo_font()
        texts = [str(self._display_var.get() or "")]
        try:
            texts.extend(str(v) for v in (self.cget("values") or ())[:80])
        except tk.TclError:
            pass
        texts.extend(str(v) for v in self._all_values[:40])
        longest = max((font.measure(t) for t in texts if t), default=0)
        return min(max(longest + 44, self.winfo_width()), 780)

    def _size_popdown(self) -> None:
        """Širina spustnega seznama = najdaljša oznaka, ne širina polja."""
        try:
            self.update_idletasks()
            popdown = self.tk.call("ttk::combobox::PopdownWindow", str(self))
            listbox = f"{popdown}.f.l"
            font = self._combo_font()
            px = self._needed_width_px()
            char_w = max(font.measure("0"), 1)
            self.tk.call(listbox, "configure", "-width", max(24, px // char_w))
            self.tk.call("wm", "geometry", popdown, f"{px}x")
        except tk.TclError:
            pass

    def _expand_for_text(self) -> None:
        if self._expanded:
            self._size_popdown()
            return
        try:
            self.update_idletasks()
            parent = self.nametowidget(self.winfo_parent())
            x, y = self.winfo_x(), self.winfo_y()
            h = max(self.winfo_height(), 22)
            need = self._needed_width_px()
            max_w = max(8, parent.winfo_width() - x - 8)
            width = min(need, max_w)
            if width <= self.winfo_width() + 8:
                self._size_popdown()
                return
            self.place(in_=parent, x=x, y=y, width=width, height=h)
            self.lift()
            self._expanded = True
            self._size_popdown()
        except tk.TclError:
            self._size_popdown()

    def _collapse_width(self) -> None:
        if not self._expanded:
            return
        try:
            popdown = self.tk.call("ttk::combobox::PopdownWindow", str(self))
            if int(self.tk.call("winfo", "ismapped", popdown)):
                return
        except tk.TclError:
            pass
        try:
            if self.focus_get() is self:
                return
        except tk.TclError:
            pass
        self._expanded = False
        try:
            self.place_forget()
        except tk.TclError:
            pass

    def _on_press_widen(self, _event: tk.Event | None = None) -> None:
        self.after_idle(self._expand_for_text)

    def _on_focus_in(self, _event: tk.Event | None = None) -> None:
        self.after_idle(self._expand_for_text)
        if getattr(self, "_select_all_on_focus", True) and not self._typing:
            self.after_idle(lambda: self.selection_range(0, "end"))

    def _on_keypress(self, event: tk.Event) -> None:
        if event.state & 0x4:
            return
        if event.keysym in {"Tab", "Escape", "Up", "Down", "Return", "KP_Enter"}:
            return
        self._typing = True
        # Ob označitvi celotnega polja začni tipkanje na novo
        try:
            if self.selection_present():
                self._typed = ""
        except tk.TclError:
            pass

    def _on_keyrelease(self, event: tk.Event) -> None:
        if event.state & 0x4:
            return
        if event.keysym in {"Tab", "Escape", "Up", "Down", "Return", "KP_Enter"}:
            return
        if event.keysym in {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R"}:
            return

        raw = str(self._display_var.get() or "")
        # Če je ttk dopolnil na »4 — Stroški«, ohrani samo tipkano šifro
        if "—" in raw:
            needle = self._needle(raw)
            self._typed = needle
            self._put_display(needle)
        else:
            needle = raw.strip()
            self._typed = needle

        matches = self._matches(needle)
        self._set_display_values(matches)
        # Ne kliči Post — na Windowsu to pokvari vnos (podvoji znake, vsili izbiro).
        # Uporabnik odpre seznam s puščico / Alt+Down; vrednosti so že filtrirane.

    def _on_selected(self, _event: object | None = None) -> None:
        self._commit(str(self._display_var.get() or ""))
        if self._filter_provider is None:
            self.after_idle(self._restore_all)

    def _label_ok(self, label: str) -> bool:
        """Zavrni oznake »⚠ ni v Minimax« — niso veljavna izbira."""
        return "⚠" not in str(label or "")

    def _code_in_universe(self, code: str) -> bool:
        code = self._normalize_code(code)
        if not code:
            return False
        for label in self._all_values:
            left = str(label).split("—", 1)[0].strip()
            if left == code and self._label_ok(label):
                return True
        for label in self._matches(code):
            left = str(label).split("—", 1)[0].strip()
            if left == code and self._label_ok(label):
                return True
        return False

    def _try_commit_display(self) -> bool:
        """Potrdi izbiro ali polno šifro, ki obstaja v Minimax seznamu."""
        raw = str(self._display_var.get() or "")
        match = self._exact_or_unique_match(raw)
        if match and self._label_ok(match):
            self._commit(match)
            return True
        code = self._normalize_code(self._needle(raw))
        if code and len(code) >= 4 and self._code_in_universe(code):
            # uporabi oznako iz seznama, če obstaja
            for label in self._matches(code):
                if str(label).split("—", 1)[0].strip() == code and self._label_ok(label):
                    self._commit(label)
                    return True
            self._commit(code)
            return True
        return False

    def _on_return(self, _event: object | None = None) -> str | None:
        if self._try_commit_display():
            return "break"
        return "break"

    def _on_focus_out(self, _event: object | None = None) -> None:
        self.after_idle(self._collapse_width)
        if self._committing:
            return
        if self._try_commit_display():
            return
        # Delni vnos (npr. »4«, »41«) — vrni zadnji potrjeni konto
        self._typing = False
        self._typed = ""
        if self._commit_var is not None:
            try:
                prev = self._normalize_code(str(self._commit_var.get() or ""))
                if prev != str(self._commit_var.get() or ""):
                    self._committing = True
                    try:
                        self._commit_var.set(prev)
                    finally:
                        self._committing = False
                self._put_display(prev)
            except tk.TclError:
                pass
        if self._filter_provider is None:
            self._restore_all()
        elif self._all_values:
            seed = self._all_values[:80] if len(self._all_values) > 80 else self._all_values
            self._set_display_values(seed)

    def _restore_all(self) -> None:
        if self._filter_provider is not None:
            return
        if tuple(self.cget("values")) != tuple(self._all_values):
            self._set_display_values(self._all_values)
