"""Povezave na eDavki (FURS) za Projest / zastopane zavezance."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import urlencode
from webbrowser import open as open_url

# Seznam carinskih deklaracij (MRN) — DDV od uvoza prek obračuna (polje 26)
EDAVKI_MRN_DECLARATIONS_URL = (
    "https://edavki.durs.si/EdavkiPortal/PersonalPortal/CommonPages/Documents/DDV_Deklaracija.aspx"
)

# Zamenjava zavezanca (če nisi že na Projest)
EDAVKI_DEPUTY_LIST_URL = (
    "https://edavki.durs.si/EdavkiPortal/PersonalPortal/Pages/Logout/DeputyList.aspx"
)

PROJEST_TAX_ID = "14446669"
PROJEST_NAME = "PROJEST TRGOVINSKA DEJAVNOST D.O.O."


def _open_in_chrome(url: str) -> bool:
    chrome_candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for browser in chrome_candidates:
        if not browser.is_file():
            continue
        try:
            subprocess.Popen(
                [str(browser), "--new-tab", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        except OSError:
            continue
    return bool(open_url(url))


def open_edavki_mrn_declarations(*, prefer_deputy_list: bool = False) -> bool:
    """
    Odpre eDavki seznam MRN (carinske deklaracije) za vpogled polja 26.

    Zahteva prijavo v eDavkih; če ni izbran Projest, uporabi Zamenjava zavezanca.
    """
    url = EDAVKI_DEPUTY_LIST_URL if prefer_deputy_list else EDAVKI_MRN_DECLARATIONS_URL
    return _open_in_chrome(url)


def open_edavki_mrn_dates(
    *,
    date_from: str,
    date_to: str,
    tax_number: str = PROJEST_TAX_ID,
    company_name: str = PROJEST_NAME,
) -> bool:
    """Odpre eDavki MRN, vpiše Datum od/do in klikne Išči."""
    query = urlencode(
        {
            "kirkpr_from": str(date_from or "").strip(),
            "kirkpr_to": str(date_to or "").strip(),
            "kirkpr_tax": re.sub(r"\D", "", tax_number or ""),
            "kirkpr_firm": str(company_name or "").strip()[:120],
            "kirkpr_search": "1",
        }
    )
    return _open_in_chrome(f"{EDAVKI_MRN_DECLARATIONS_URL}?{query}")
