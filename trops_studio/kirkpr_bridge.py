"""Trops Studio povezava na Minimax/KirKpr knjižnice (vendor + fallback)."""

from __future__ import annotations

import sys
from pathlib import Path

from trops_studio.config import KIRKPR_CURSOR_ROOT, PACKAGE_ROOT

VENDOR_ROOT = PACKAGE_ROOT / "vendor_kirkpr"


def ensure_kirkpr_on_path() -> Path:
    """
    Prednost: trops_studio/vendor_kirkpr (samostojen Minimax/DDV-O).
    Fallback: KirKpr_convert_cursor (moduli, ki jih v vendor_kirkpr ni: kirkpr_upn_qr,
    kirkpr_ajpes_iban, kirkpr_ddvo_placeholder_texts …).
    """
    roots: list[Path] = []
    if VENDOR_ROOT.is_dir():
        roots.append(VENDOR_ROOT)
    for root in (KIRKPR_CURSOR_ROOT,):
        if root.is_dir():
            roots.append(root)
    if not roots:
        raise FileNotFoundError(
            "Manjka vendor_kirkpr in KirKpr mapa "
            f"({VENDOR_ROOT} / {KIRKPR_CURSOR_ROOT})."
        )
    # Vendor najprej na sys.path (insert(0) v obratnem vrstnem redu)
    for root in reversed(roots):
        text = str(root)
        if text in sys.path:
            sys.path.remove(text)
        sys.path.insert(0, text)
    return roots[0]


def minimax_xsd_path() -> Path:
    ensure_kirkpr_on_path()
    for root in (VENDOR_ROOT, KIRKPR_CURSOR_ROOT):
        path = root / "miniMAXUvozKnjigovodstvo.xsd"
        if path.is_file():
            return path
    raise FileNotFoundError("Manjka miniMAXUvozKnjigovodstvo.xsd (vendor ali KirKpr).")


def ddvo_transforms_dir() -> Path:
    ensure_kirkpr_on_path()
    for root in (VENDOR_ROOT, KIRKPR_CURSOR_ROOT):
        path = root / "ddvo_transforms"
        if path.is_dir():
            return path
    raise FileNotFoundError("Manjka ddvo_transforms.")
