"""SMTP predogled pred oddajo: urejanje Za/KP/zadeva/telo, test, pošlji."""

from __future__ import annotations

import tempfile
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable, Sequence

from trops_studio.ddvo_actions import GMAIL_SMTP_CC, GMAIL_SMTP_FROM, send_gmail_email
from trops_studio.kirkpr_bridge import ensure_kirkpr_on_path
from trops_studio.ui.tooltip import ToolTip


class SmtpComposeDialog(tk.Toplevel):
    """Pred oddajo vidiš kaj in kako gre — lahko urediš, testiraš SMTP, pošlješ."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        title: str = "E-pošta — predogled SMTP",
        to_addr: str = "",
        cc: str = GMAIL_SMTP_CC,
        subject: str = "",
        body_html: str = "",
        attachments: Sequence[Path] | None = None,
        on_sent: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.attachments = [Path(p) for p in (attachments or ()) if Path(p).is_file()]
        self.on_sent = on_sent
        self.sent = False
        self.title(title)
        self.transient(master)
        self.geometry("920x680")
        self.minsize(720, 520)

        self.to_var = tk.StringVar(value=str(to_addr or "").strip())
        self.cc_var = tk.StringVar(value=str(cc or "").strip())
        self.subject_var = tk.StringVar(value=str(subject or "").strip())
        self.status = tk.StringVar(value=self._smtp_status_text())

        top = ttk.Frame(self, padding=(12, 12, 12, 6))
        top.pack(fill="x")
        ttk.Label(
            top,
            text="Gmail SMTP — pred oddajo uredi sporočilo. Test preveri prijavo (in po želji pošlje nase).",
            style="Muted.TLabel",
            wraplength=880,
        ).pack(anchor="w")
        ttk.Label(top, textvariable=self.status, style="Muted.TLabel").pack(anchor="w", pady=(4, 0))

        form = ttk.Frame(self, padding=(12, 0, 12, 6))
        form.pack(fill="x")
        self._row(form, "Od", tk.StringVar(value=GMAIL_SMTP_FROM), readonly=True)
        self._row(form, "Za", self.to_var)
        self._row(form, "KP", self.cc_var)
        self._row(form, "Zadeva", self.subject_var, width=88)

        if self.attachments:
            names = ", ".join(p.name for p in self.attachments)
            ttk.Label(form, text=f"Priponke: {names}", style="Muted.TLabel").pack(anchor="w", pady=(4, 0))

        body_fr = ttk.Frame(self, padding=(12, 0, 12, 6))
        body_fr.pack(fill="both", expand=True)
        ttk.Label(body_fr, text="Telo (HTML — lahko urejaš):").pack(anchor="w")
        text_wrap = ttk.Frame(body_fr)
        text_wrap.pack(fill="both", expand=True, pady=(4, 0))
        ybar = ttk.Scrollbar(text_wrap, orient="vertical")
        self.body = tk.Text(text_wrap, wrap="word", font=("Consolas", 10), undo=True)
        self.body.pack(side="left", fill="both", expand=True)
        ybar.pack(side="right", fill="y")
        self.body.configure(yscrollcommand=ybar.set)
        ybar.configure(command=self.body.yview)
        self.body.insert("1.0", body_html or "")

        bar = ttk.Frame(self, padding=(12, 0, 12, 12))
        bar.pack(fill="x")
        btn_test = ttk.Button(bar, text="Test SMTP", command=self._test_smtp)
        btn_test.pack(side="left")
        ToolTip(btn_test, "Prijava na Gmail (brez oddaje stranki). Nato vpraša za test nase.")
        btn_prev = ttk.Button(bar, text="Predogled", command=self._preview)
        btn_prev.pack(side="left", padx=(8, 0))
        ToolTip(btn_prev, "Odpre trenutno telo v brskalniku.")
        ttk.Button(bar, text="Zapri", command=self.destroy).pack(side="right")
        btn_send = ttk.Button(bar, text="Pošlji stranki", style="Accent.TButton", command=self._send)
        btn_send.pack(side="right", padx=(0, 8))
        ToolTip(btn_send, "Pošlje urejeno sporočilo na Za + KP.")

    def _row(self, parent: tk.Misc, label: str, var: tk.StringVar, *, readonly: bool = False, width: int = 56) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label, width=8).pack(side="left")
        entry = ttk.Entry(row, textvariable=var, width=width)
        entry.pack(side="left", fill="x", expand=True)
        if readonly:
            entry.configure(state="readonly")

    def _smtp_status_text(self) -> str:
        try:
            ensure_kirkpr_on_path()
            import kirkpr_ddvo_smtp as ddvo_smtp  # type: ignore

            ok, note = ddvo_smtp.smtp_available()
            if ok:
                return f"SMTP vklopljen · Gmail {GMAIL_SMTP_FROM} · {note}"
            return f"SMTP ni pripravljen: {note}"
        except Exception as exc:
            return f"SMTP ni pripravljen: {exc}"

    def _body_html(self) -> str:
        return self.body.get("1.0", "end-1c")

    def _preview(self) -> None:
        html = self._body_html() or "<p>(prazno)</p>"
        path = Path(tempfile.gettempdir()) / "trops_smtp_preview.html"
        path.write_text(
            "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Predogled</title></head>"
            f"<body>{html}</body></html>",
            encoding="utf-8",
        )
        webbrowser.open(path.as_uri())

    def _test_smtp(self) -> None:
        try:
            ensure_kirkpr_on_path()
            import kirkpr_ddvo_smtp as ddvo_smtp  # type: ignore

            ok, note = ddvo_smtp.smtp_probe()
        except Exception as exc:
            messagebox.showerror("Test SMTP", str(exc), parent=self)
            return
        self.status.set(note)
        if not ok:
            messagebox.showerror("Test SMTP", note, parent=self)
            return
        if not messagebox.askyesno(
            "Test SMTP",
            f"{note}\n\nPošljem TEST nase ({GMAIL_SMTP_FROM}) z trenutnim besedilom?\n"
            "Stranka ne dobi ničesar.",
            parent=self,
        ):
            messagebox.showinfo("Test SMTP", note, parent=self)
            return
        try:
            sent = send_gmail_email(
                to_addr=GMAIL_SMTP_FROM,
                subject="[TEST] " + (self.subject_var.get() or "(brez zadeve)"),
                body_html=(
                    "<p><b>TEST SMTP</b> — to sporočilo je šlo nase, ne stranki.</p>"
                    f"<p>Za (stranka): {self.to_var.get() or '—'}</p>"
                    + self._body_html()
                ),
                cc="",
                attachments=self.attachments,
            )
        except Exception as exc:
            messagebox.showerror("Test SMTP", str(exc), parent=self)
            return
        messagebox.showinfo("Test SMTP", f"{note}\n\n{sent}", parent=self)

    def _send(self) -> None:
        to_addr = self.to_var.get().strip()
        if not to_addr:
            messagebox.showerror("Pošlji", "Manjka prejemnik (Za).", parent=self)
            return
        if not messagebox.askyesno(
            "Pošlji stranki",
            "Pošljem urejeno sporočilo?\n\n"
            f"Od: {GMAIL_SMTP_FROM}\n"
            f"Za: {to_addr}\n"
            f"KP: {self.cc_var.get().strip() or '—'}\n"
            f"Zadeva: {self.subject_var.get() or '—'}",
            parent=self,
        ):
            return
        try:
            note = send_gmail_email(
                to_addr=to_addr,
                subject=self.subject_var.get().strip() or "(brez zadeve)",
                body_html=self._body_html(),
                cc=self.cc_var.get().strip(),
                attachments=self.attachments,
            )
        except Exception as exc:
            messagebox.showerror("Pošlji", str(exc), parent=self)
            return
        self.sent = True
        if self.on_sent:
            self.on_sent(note)
        messagebox.showinfo("Pošlji", note, parent=self)
        self.destroy()
