from __future__ import annotations

import calendar
import re
from datetime import date
from pathlib import Path
from typing import Sequence

PERIOD_CHOICES = (
    "januar", "februar", "marec", "april", "maj", "junij",
    "julij", "avgust", "september", "oktober", "november", "december",
    "jan-mar", "apr-jun", "jul-sep", "okt-dec", "jan-jun", "jul-dec", "jan-dec",
)

_MONTH_NAMES = {
    "januar": 1, "februar": 2, "marec": 3, "april": 4, "maj": 5, "junij": 6,
    "julij": 7, "avgust": 8, "september": 9, "oktober": 10, "november": 11, "december": 12,
}


def month_bounds(year: int, month: int) -> tuple[date, date]:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def previous_month_bounds(today: date | None = None) -> tuple[date, date]:
    """Privzeto obdobje: celoten prejšnji mesec (julij → junij)."""
    day = today or date.today()
    if day.month == 1:
        return month_bounds(day.year - 1, 12)
    return month_bounds(day.year, day.month - 1)


def previous_quarter_bounds(today: date | None = None) -> tuple[date, date]:
    """Prejšnji koledarski kvartal (julij → 1.4.–30.6.)."""
    day = today or date.today()
    current_q = (day.month - 1) // 3  # 0=Q1 … 3=Q4
    if current_q == 0:
        return date(day.year - 1, 10, 1), date(day.year - 1, 12, 31)
    start_m = (current_q - 1) * 3 + 1
    end_m = start_m + 2
    return date(day.year, start_m, 1), date(
        day.year, end_m, calendar.monthrange(day.year, end_m)[1]
    )


def default_period_for_ddv_cadence(
    cadence: str,
    today: date | None = None,
) -> tuple[date, date]:
    """Mesečni → prejšnji mesec; tromesečni → prejšnji kvartal."""
    kind = (cadence or "").strip().casefold()
    if kind in {"quarterly", "tromesecni", "tromesečni", "kvartal"}:
        return previous_quarter_bounds(today)
    if kind in {"yearly", "letni", "letno"}:
        day = today or date.today()
        return date(day.year - 1, 1, 1), date(day.year - 1, 12, 31)
    return previous_month_bounds(today)


def period_bounds(year: int, label: str) -> tuple[date, date] | None:
    text = (label or "").strip().casefold()
    if text in _MONTH_NAMES:
        return month_bounds(year, _MONTH_NAMES[text])
    ranges = {
        "jan-mar": (1, 3),
        "apr-jun": (4, 6),
        "jul-sep": (7, 9),
        "okt-dec": (10, 12),
        "jan-jun": (1, 6),
        "jul-dec": (7, 12),
        "jan-dec": (1, 12),
    }
    if text not in ranges:
        return None
    start_m, end_m = ranges[text]
    start = date(year, start_m, 1)
    end = date(year, end_m, calendar.monthrange(year, end_m)[1])
    return start, end


def period_label_for_range(start: date, end: date) -> str:
    if start.year == end.year and start.month == end.month and start.day == 1:
        last = calendar.monthrange(start.year, start.month)[1]
        if end.day == last:
            for name, month in _MONTH_NAMES.items():
                if month == start.month:
                    return name
    if start.year == end.year and start.day == 1:
        mapping = {
            (1, 3): "jan-mar",
            (4, 6): "apr-jun",
            (7, 9): "jul-sep",
            (10, 12): "okt-dec",
            (1, 6): "jan-jun",
            (7, 12): "jul-dec",
            (1, 12): "jan-dec",
        }
        key = (start.month, end.month)
        if key in mapping and end.day == calendar.monthrange(end.year, end.month)[1]:
            return mapping[key]
    return "januar" if start.month == 1 else next(
        (name for name, month in _MONTH_NAMES.items() if month == start.month),
        "januar",
    )


def parse_si_date(text: str) -> date | None:
    raw = (text or "").strip()
    if not raw:
        return None
    for sep in (".", "-", "/"):
        parts = raw.split(sep)
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            continue
        a, b, c = int(parts[0]), int(parts[1]), int(parts[2])
        if len(parts[0]) == 4:
            y, m, d = a, b, c
        elif len(parts[2]) == 4:
            d, m, y = a, b, c
        else:
            continue
        try:
            return date(y, m, d)
        except ValueError:
            return None
    return None


def format_si_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def period_stamp(day: date | None) -> str:
    if day is None:
        return ""
    return f"{day.year:04d}{day.month:02d}"


def bounds_from_period_stamp(stamp: str) -> tuple[date, date] | None:
    digits = re.sub(r"\D", "", stamp or "")
    if len(digits) < 6:
        return None
    year, month = int(digits[:4]), int(digits[4:6])
    if year < 1990 or not 1 <= month <= 12:
        return None
    return month_bounds(year, month)


def revision_suffix(rev: int) -> str:
    number = max(1, int(rev or 1))
    return "" if number <= 1 else f"-{number}"


def infer_period_stamp(paths: Sequence[Path | str], fallback: date | None = None) -> str:
    """YYYYMM iz imena mape/datoteke (202607, julij 2026)."""
    for raw in paths:
        if not raw:
            continue
        path = Path(str(raw))
        text = f"{path.name} {path.parent.name} {path.parent.parent.name}"
        match = re.search(r"(20\d{2})[-_ ]?(0[1-9]|1[0-2])", text)
        if match:
            return f"{match.group(1)}{match.group(2)}"
        year_match = re.search(r"(20\d{2})", text)
        folded = text.casefold()
        for name, month in _MONTH_NAMES.items():
            if name in folded and year_match:
                return f"{year_match.group(1)}{month:02d}"
    return period_stamp(fallback)
