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


def _offer_v4_data_copy(messagebox) -> None:
    """Ponudi KOPIJO (ne premik) podatkov iz ..\\Trops_v4\\data, če v5 še nima baz. v4 ostane nespremenjen."""
    import shutil

    v4_data = ROOT.parent / "Trops_v4" / "data"
    v5_data = ROOT / "data"
    if not v4_data.is_dir() or any(v5_data.glob("*.sqlite3")):
        return
    names = [p.name for p in v4_data.glob("*.sqlite3")]
    if not names:
        return
    if not messagebox.askyesno(
        "Trops Studio 5.0.00 — podatki",
        "V5 še nima lokalnih baz.\n\n"
        f"Kopiram baze in nastavitve iz:\n{v4_data}\n\n"
        f"({len(names)} baz: {', '.join(sorted(names)[:6])}{' …' if len(names) > 6 else ''})\n\n"
        "Kopija — v4 ostane nespremenjen. Ne = začni s prazno mapo data\\ "
        "(ali v settings.json nastavi data_dir).",
    ):
        return
    v5_data.mkdir(parents=True, exist_ok=True)
    skip = {"webview2_profile", "logs", "__pycache__"}
    copied = 0
    for src in v4_data.iterdir():
        if src.name in skip or src.name.startswith("_"):
            continue
        dst = v5_data / src.name
        if dst.exists():
            continue
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        copied += 1
    messagebox.showinfo("Trops Studio 5.0.00", f"Kopiranih {copied} datotek/map v {v5_data}.")


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

    _offer_v4_data_copy(messagebox)

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
