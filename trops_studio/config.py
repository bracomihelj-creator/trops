r"""Centralna konfiguracija Trops Studio 5.

Vse poti na D:\ (Trops podatki, EvidencaFirm, KirKpr …) so zbrane tukaj.
Privzete vrednosti so ENAKE kot v 4.0.01. Po želji jih prepišeš v
``settings.json`` (ali ``settings.local.json``) v korenu aplikacije, npr.::

    {"data_dir": "D:\\PISARNA\\Python\\Trops_v4\\data", "trops_root": "D:\\Trops"}

Prazna ali manjkajoča vrednost = privzeto.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent
APP_ROOT = PACKAGE_ROOT.parent
SETTINGS_FILES = (APP_ROOT / "settings.local.json", APP_ROOT / "settings.json")


# Napake pri branju nastavitev (pokvarjen JSON …) — prikažejo se v UI kot opozorilo in v dnevniku.
SETTINGS_ERRORS: list[str] = []


def _load_settings() -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for path in reversed(SETTINGS_FILES):
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8-sig"))
                if isinstance(data, dict):
                    merged.update({k: v for k, v in data.items() if not str(k).startswith("_")})
        except (OSError, json.JSONDecodeError) as exc:
            # Pokvarjena nastavitev ne sme ustaviti zagona — velja privzeto, a uporabnik to vidi.
            SETTINGS_ERRORS.append(f"{path.name} ni berljiv ({exc}); veljajo privzete nastavitve.")
            continue
    return merged


SETTINGS: dict[str, Any] = _load_settings()


def setting_path(key: str, default: Path | str) -> Path:
    """Okolje TROPS_<KLJUČ> (npr. TROPS_DATA_DIR) > settings(.local).json > privzeto."""
    raw = os.environ.get(f"TROPS_{key.upper()}") or SETTINGS.get(key)
    if raw is None or not str(raw).strip():
        return Path(default)
    return Path(str(raw).strip())


DATA_DIR = setting_path("data_dir", APP_ROOT / "data")
LOG_DIR = DATA_DIR / "logs"
WEBVIEW_PROFILE_DIR = setting_path("webview_profile_dir", DATA_DIR / "webview2_profile")
# Privzeta / nedejavna baza (brez izbranega podjetja).
DEFAULT_DB = DATA_DIR / "trops_idle.sqlite3"
LEGACY_PROJEST_DB = DATA_DIR / "projest.sqlite3"


def company_db_path(zst: str | int | None) -> Path:
    """SQLite pot za podjetje: data/zst-{Zšt}.sqlite3."""
    digits = re.sub(r"\D", "", str(zst or ""))
    if not digits:
        return DEFAULT_DB
    return DATA_DIR / f"zst-{int(digits)}.sqlite3"


def migrate_legacy_projest_db() -> Path | None:
    """projest.sqlite3 → zst-21.sqlite3 (enkrat, če cilj še ne obstaja)."""
    target = company_db_path(21)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if LEGACY_PROJEST_DB.is_file() and not target.is_file():
        shutil.copy2(LEGACY_PROJEST_DB, target)
        return target
    return None

TROPS_ROOT = setting_path("trops_root", r"D:\Trops")
DEFAULT_TROPS = TROPS_ROOT / "21"
DEFAULT_IR_DARILA = DEFAULT_TROPS / "DDV" / "IF DARILA.xls"
DEFAULT_IR_FITNES = DEFAULT_TROPS / "DDV" / "IF FITNES.xls"
DEFAULT_PR = DEFAULT_TROPS / "DDV" / "KPF.xls"
DEFAULT_MINIMAX_OUT = DEFAULT_TROPS / "MiniMax"

# Integra (Zšt 20) — SQL TROPS backup / obdelava
DEFAULT_INTEGRA_TROPS = TROPS_ROOT / "20"
DEFAULT_INTEGRA_SQL = setting_path("integra_sql_dir", DEFAULT_INTEGRA_TROPS / "SQL")
DEFAULT_KONT_DBF = setting_path("kont_dbf", r"D:\Trops\dat\KONT2005.DBF")
KONT_DBF_FALLBACKS = (TROPS_ROOT / "dat" / "KONT.DBF", TROPS_ROOT / "dat" / "KONTO.DBF")

POWERSHELL_32 = Path(r"C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe")
PISARNA_PYTHON = setting_path("pisarna_python", r"D:\PISARNA\Python")
EVIDENCA_FIRM_ROOT = setting_path("evidenca_firm_root", PISARNA_PYTHON / "EvidencaFirm")
KIRKPR_CURSOR_ROOT = setting_path("kirkpr_cursor_root", PISARNA_PYTHON / "KirKpr_convert_cursor")
KIRKPR_LEGACY_ROOT = setting_path("kirkpr_legacy_root", PISARNA_PYTHON / "KirKpr_convert")
CHROME_ADD_ROOT = setting_path("chrome_add_root", PISARNA_PYTHON / "Chrome_add")
SMTP_SECRET_CANDIDATES = (
    CHROME_ADD_ROOT / "Minimax_forward" / "server" / "smtp_secret.bin",
    CHROME_ADD_ROOT / "DDVO_Oddaje" / "server" / "smtp_secret.bin",
    CHROME_ADD_ROOT / "EdavkiForward_Chrome" / "smtp_secret.bin",
)
KONTO62_WEBAPP_CANDIDATES = (
    CHROME_ADD_ROOT / "AktivniZavihek_WebApp",
    CHROME_ADD_ROOT / "Minimax_Odpiranje_Podjetij",
)
EVIDENCA_FIRM_REGISTRY_CANDIDATES = (
    EVIDENCA_FIRM_ROOT / "data" / "firme_evidenca.json",
    EVIDENCA_FIRM_ROOT / "firme_evidenca.json",
)

# Privzeti IR prihodek za PROJEST (iz temeljnica_PROJEST.XML) — ne 7601.
DEFAULT_IR_REVENUE_ACCOUNT = "7620"
# Prodaja blaga v EU (izven SI) — 7620 → 76301, splošna osnova brez DDV.
DEFAULT_IR_EU_REVENUE_ACCOUNT = "76301"
DEFAULT_PR_EXPENSE_ACCOUNT = "4190"
# Fallback konto za znesek »Ne gre v knjigo« (= ni v DDV / KIR-KPR).
# To NI poseben DDV konto — knjiži se samo temeljnica (npr. 4190, 9729 posojilo …).
DEFAULT_PR_EXCLUDED_ACCOUNT = "4190"

# Minimax šifra za fizične osebe / brez davčne (ena skupna stranka).
KONCNI_KUPCI_CODE = "01345"
KONCNI_KUPCI_NAME = "Končni kupci"
