"""SQL-first tok: lokalno delo → Potrdi (ready) → Sinhroniziraj Minimax."""

from __future__ import annotations

# Delo samo v SQLite (usklajevanje, knjiženje, dodajanje)
SYNC_LOCAL = "local"
# Potrjeno — čaka na Minimax API / XML
SYNC_READY = "ready"
# Uspešno poslano / povezano z Minimax
SYNC_SYNCED = "synced"
# Zadnji poskus sync spodletel
SYNC_ERROR = "error"

SYNC_STATUSES: tuple[str, ...] = (SYNC_LOCAL, SYNC_READY, SYNC_SYNCED, SYNC_ERROR)

SYNC_LABELS: dict[str, str] = {
    SYNC_LOCAL: "SQL (osnutek)",
    SYNC_READY: "Pripravljeno za Minimax",
    SYNC_SYNCED: "Sinhronizirano",
    SYNC_ERROR: "Napaka sync",
}


def normalize_sync_status(value: str | None) -> str:
    text = str(value or "").strip().casefold()
    mapping = {s.casefold(): s for s in SYNC_STATUSES}
    return mapping.get(text, SYNC_LOCAL)


def sync_label(value: str | None) -> str:
    return SYNC_LABELS.get(normalize_sync_status(value), SYNC_LABELS[SYNC_LOCAL])
