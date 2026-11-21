"""Statusi vrstic IR/PR — Access-podobno sortiranje napak iz Excela."""

from __future__ import annotations

# Shrani v DB `status`; filter v seznamu IR/PR.
STATUS_POGLEJ = "Poglej"
STATUS_POPRAVI = "Popravi"
STATUS_POPRAVLJENO = "Popravljeno"
STATUS_SHRANJENO = "Shranjeno"
STATUS_MANJKA_KONTO = "Manjka konto"

# Združljivost s starimi uvozi
STATUS_OSNUTEK = "OSNUTEK"
STATUS_PRIPRAVLJEN = "PRIPRAVLJEN"

ROW_STATUSES: tuple[str, ...] = (
    STATUS_POGLEJ,
    STATUS_POPRAVI,
    STATUS_POPRAVLJENO,
    STATUS_SHRANJENO,
    STATUS_MANJKA_KONTO,
    STATUS_OSNUTEK,
    STATUS_PRIPRAVLJEN,
)

# Privzeto ob uvozu / novi vrstici
DEFAULT_ROW_STATUS = STATUS_OSNUTEK

# Filter radio: (label, value)
STATUS_FILTER_CHOICES: tuple[tuple[str, str], ...] = (
    ("Vsi", "VSI"),
    ("Osnutek", STATUS_OSNUTEK),
    ("Popravi", STATUS_POPRAVI),
    ("Popravljeno", STATUS_POPRAVLJENO),
    ("Shranjeno", STATUS_SHRANJENO),
    ("Manjka konto", STATUS_MANJKA_KONTO),
    ("Pripravljen", STATUS_PRIPRAVLJEN),
    ("Poglej", STATUS_POGLEJ),
    ("Chk", "CHK"),
)


def normalize_status(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return DEFAULT_ROW_STATUS
    # case-insensitive match na znane
    lowered = {s.casefold(): s for s in ROW_STATUSES}
    return lowered.get(text.casefold(), text)


def status_filter_matches(row_status: str | None, filter_value: str, *, has_account: bool = True) -> bool:
    """Ali vrstica ustreza status filtru (vključno legacy OSNUTEK/PRIPRAVLJEN)."""
    wanted = str(filter_value or "VSI").strip()
    if wanted in {"VSI", "CHK"}:
        return True
    if wanted == "NO_ACCOUNT":
        return not has_account
    if wanted == STATUS_MANJKA_KONTO:
        # Status ali dejansko manjkajoč konto
        status = normalize_status(row_status)
        if status.casefold() == STATUS_MANJKA_KONTO.casefold():
            return True
        return not has_account
    status = normalize_status(row_status)
    # Skupine združljivosti
    groups: dict[str, set[str]] = {
        STATUS_POPRAVI.casefold(): {STATUS_POPRAVI.casefold(), STATUS_OSNUTEK.casefold()},
        STATUS_OSNUTEK.casefold(): {STATUS_OSNUTEK.casefold(), STATUS_POPRAVI.casefold()},
        STATUS_SHRANJENO.casefold(): {STATUS_SHRANJENO.casefold(), STATUS_PRIPRAVLJEN.casefold()},
        STATUS_PRIPRAVLJEN.casefold(): {STATUS_PRIPRAVLJEN.casefold(), STATUS_SHRANJENO.casefold()},
    }
    key = wanted.casefold()
    allowed = groups.get(key, {key})
    return status.casefold() in allowed
