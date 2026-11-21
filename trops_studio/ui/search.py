from __future__ import annotations

import re
from typing import Any, Sequence

from trops_studio.money import date_text, money_text, parse_date


def search_tokens(query: str) -> list[str]:
    return [part for part in re.sub(r"\s+", " ", (query or "").strip().casefold()).split(" ") if part]


def haystack_matches(tokens: Sequence[str], chunks: Sequence[Any]) -> bool:
    if not tokens:
        return True
    haystack = " ".join(str(chunk or "").casefold() for chunk in chunks)
    return all(token in haystack for token in tokens)


def row_search_chunks(row: dict[str, Any], *, extra: Sequence[Any] = ()) -> list[Any]:
    chunks: list[Any] = list(extra)
    for key, value in row.items():
        if key == "raw_json":
            continue
        text = str(value or "").strip()
        if not text:
            continue
        chunks.append(text)
        if key.endswith("_date") or "date" in key:
            try:
                parsed = parse_date(text)
            except Exception:
                parsed = None
            if parsed:
                chunks.append(date_text(parsed))
                chunks.append(parsed.isoformat())
        if re.fullmatch(r"-?\d+(?:\.\d+)?", text.replace(",", ".")):
            try:
                chunks.append(money_text(text))
            except Exception:
                pass
    return chunks
