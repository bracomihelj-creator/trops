# -*- coding: utf-8 -*-
"""INSTALL.pyw — predpogoji Trops Studio 5.0.00 (kot Evidence / Pooblastila)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQ = ROOT / "requirements.txt"
PYW = ROOT / "Trops_Studio_V5.0.00.pyw"
NEEDED = ("host.py", "motor.py", "ui/index.html", "ui/app.css", "ui/app.js", "trops_studio_web/service.py")


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        return int(proc.returncode), ((proc.stdout or "") + (proc.stderr or "")).strip()
    except Exception as exc:
        return 1, str(exc)


def main() -> int:
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()

    if sys.version_info < (3, 10):
        messagebox.showerror("Trops Studio 5.0.00", f"Potreben je Python 3.10+.\nTrenutno: {sys.version}")
        return 1

    missing_files = [p for p in NEEDED if not (ROOT / p).is_file()]
    if missing_files:
        messagebox.showerror("Trops Studio 5.0.00", "Manjkajo datoteke:\n" + "\n".join(missing_files))
        return 1

    try:
        import webview  # noqa: F401
        wv_ok = True
    except ImportError:
        wv_ok = False

    if not wv_ok:
        if not messagebox.askyesno(
            "Trops Studio 5.0.00 — namestitev",
            "Manjka pywebview.\n\nNamestim iz requirements.txt?\n"
            "(SQLite / D:\\Trops podatki se ne spreminjajo.)",
        ):
            return 0
        code, out = _run([sys.executable, "-m", "pip", "install", "-r", str(REQ)])
        if code != 0:
            messagebox.showerror("Namestitev", f"pip ni uspel.\n\n{out[-2000:]}")
            return 1
        try:
            import webview  # noqa: F401
            wv_ok = True
        except ImportError:
            wv_ok = False

    msg = (
        "Trops Studio 5.0.00 pripravljen (vzorec Evidence 8).\n\n"
        f"Mapa: {ROOT}\n"
        f"Zagon: {PYW.name}\n"
        f"pywebview: {'OK' if wv_ok else 'PREVERI Edge WebView2 Runtime'}\n\n"
        "Želiš zagnati?"
    )
    if messagebox.askyesno("Trops Studio 5.0.00", msg):
        subprocess.Popen([sys.executable, str(PYW)], cwd=str(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
