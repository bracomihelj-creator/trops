"""Samostojen Minimax API dostop za Projest (brez GUI KirKpr)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trops_studio.config import DATA_DIR, PACKAGE_ROOT
from trops_studio.kirkpr_bridge import VENDOR_ROOT, ensure_kirkpr_on_path

# WebUI seznam temeljnic — odpri po uspešni oddaji / XML uvozu
MINIMAX_TEMELJNICE_URL = (
    "https://moj.minimax.si/SI/VA/WebUI/Temeljnica/Temeljnica.aspx?pgat=pgatdr&prkn="
)

# Seznam OS; nov vnos: +Nov → OsnovnoSredstvoEdit.aspx
MINIMAX_OS_LIST_URL = (
    "https://moj.minimax.si/SI/VA/WebUI/OsnovnoSredstvo/OsnovnoSredstvo.aspx"
)
MINIMAX_OS_EDIT_URL = (
    "https://moj.minimax.si/SI/VA/WebUI/OsnovnoSredstvo/OsnovnoSredstvoEdit.aspx"
)
MINIMAX_OS_NEW_URL = MINIMAX_OS_EDIT_URL


def _open_minimax_url(url: str) -> bool:
    import subprocess
    from webbrowser import open as open_url

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
    try:
        return bool(open_url(url))
    except Exception:
        return False


def open_minimax_temeljnice() -> bool:
    """Odpri Minimax WebUI → Temeljnice (pregled osnutkov)."""
    return _open_minimax_url(MINIMAX_TEMELJNICE_URL)


def open_minimax_osnovna_sredstva(*, new: bool = False) -> bool:
    """Odpri Minimax WebUI → seznam OS (new=True → Edit / +Nov)."""
    return _open_minimax_url(MINIMAX_OS_EDIT_URL if new else MINIMAX_OS_LIST_URL)


@dataclass
class ApiCheckResult:
    ok: bool
    settings_path: str
    organisation_id: str = ""
    organisation_label: str = ""
    accounts: int = 0
    customers: int = 0
    message: str = ""


def settings_candidates() -> list[Path]:
    """Isti viri kot KirKpr + Projest data/minimax_api_settings.json."""
    ensure_kirkpr_on_path()
    from minimax_api_client import shared_settings_candidates  # type: ignore

    paths = [
        DATA_DIR / "minimax_api_settings.json",
        PACKAGE_ROOT / "minimax_api_settings.json",
        VENDOR_ROOT / "minimax_api_settings.json",
    ]
    paths.extend(shared_settings_candidates(base_dir=VENDOR_ROOT))
    paths.extend(shared_settings_candidates(base_dir=PACKAGE_ROOT.parent))
    # unikatno, ohrani vrstni red
    seen: set[str] = set()
    out: list[Path] = []
    for path in paths:
        key = str(path.resolve()) if path.exists() or True else str(path)
        try:
            key = str(path.expanduser())
        except Exception:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def resolve_settings_path(configured: str = "") -> Path:
    if configured.strip():
        return Path(configured).expanduser().resolve()
    candidates = settings_candidates()
    return next((p for p in candidates if p.is_file()), candidates[0])


def open_minimax_client(org_id: str | int) -> Any:
    """Prijava + izbira organizacije (Org_ID podjetja)."""
    ensure_kirkpr_on_path()
    from minimax_api_client import ApiSettings, MinimaxClient  # type: ignore

    settings_path = resolve_settings_path()
    if not settings_path.is_file():
        raise FileNotFoundError(
            "Manjka Minimax nastavitvena datoteka.\n"
            f"Pričakovano npr.: {DATA_DIR / 'minimax_api_settings.json'}\n"
            "ali skupni blagajna_minimax_settings.json (DavčnaBlagajna)."
        )
    settings = ApiSettings.from_file(settings_path)
    client = MinimaxClient(settings)
    client.authenticate()
    org_raw = str(org_id or getattr(settings, "organisation_id", "") or "").strip()
    if org_raw:
        try:
            client.select_organisation(int(org_raw))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Neveljaven Org_ID: {org_raw!r}") from exc
    return client


def check_minimax_api(org_id: str | int) -> ApiCheckResult:
    """Preveri prijavo, org, katalog kontov/strank (kot KirKpr predpreverjanje)."""
    settings_path = resolve_settings_path()
    try:
        client = open_minimax_client(org_id)
    except Exception as exc:
        return ApiCheckResult(
            ok=False,
            settings_path=str(settings_path),
            message=f"Prijava ni uspela: {exc}",
        )
    org = str(getattr(client, "organisation_id", "") or org_id or "")
    label = ""
    try:
        label = str(client.organisation_label() or "")
    except Exception:
        label = org
    accounts = 0
    customers = 0
    try:
        catalog = client.account_catalog() or {}
        accounts = len(catalog) if isinstance(catalog, dict) else len(list(catalog))
    except Exception:
        accounts = 0
    try:
        # lahka poizvedba — _all lahko traja; poskusi customers page
        rows = list(client._all("customers"))
        customers = len(rows)
    except Exception:
        try:
            client.refresh_references()
            customers = -1  # neznano, a refresh OK
        except Exception as exc:
            return ApiCheckResult(
                ok=False,
                settings_path=str(settings_path),
                organisation_id=org,
                organisation_label=label,
                accounts=accounts,
                message=f"Org OK, vendar customers/refresh ni uspel: {exc}",
            )
    return ApiCheckResult(
        ok=True,
        settings_path=str(settings_path),
        organisation_id=org,
        organisation_label=label or org,
        accounts=accounts,
        customers=max(customers, 0),
        message=(
            f"Minimax OK · Org {label or org} · konti {accounts}"
            + (f" · stranke {customers}" if customers >= 0 else "")
            + f"\nNastavitve: {settings_path}"
        ),
    )
