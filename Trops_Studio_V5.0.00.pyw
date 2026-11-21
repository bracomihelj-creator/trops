# -*- coding: utf-8 -*-
"""Trops Studio 5.0.00 — tanek zagon (kot Evidence_8.pyw → host.desktop)."""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _fatal(message: str) -> int:
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Trops Studio 5.0.00", message)
        root.destroy()
    except Exception:
        sys.stderr.write(message + "\n")
    return 1


def main() -> int:
    try:
        from host import desktop

        return int(desktop() or 0)
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, int):
            return code
        if code:
            return _fatal(str(code))
        return 0
    except Exception:
        return _fatal("Zagon ni uspel:\n\n" + traceback.format_exc()[-2000:])


if __name__ == "__main__":
    raise SystemExit(main())
