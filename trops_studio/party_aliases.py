"""Zapomni si vzorce nazivov (Open AI → OpenAI) za iskanje v Minimaxu."""
from __future__ import annotations

import json
import re
from typing import Any

from trops_studio.config import DATA_DIR
from trops_studio.money import sanitize_display_text

ALIASES_PATH = DATA_DIR / "party_name_aliases.json"

_SEED: dict[str, dict[str, Any]] = {
    "openai": {
        "canonical": "OpenAI",
        "aliases": ["open ai", "openai", "open-ai", "open ai llc", "openai, llc", "openai llc"],
    },
    "fiverr": {
        "canonical": "Fiverr",
        "aliases": ["fiverr", "fiverr international", "fiverr ltd"],
    },
}


def compact_alias(value: str) -> str:
    text = sanitize_display_text(value).casefold()
    return re.sub(r"[^a-z0-9]+", "", text)


def load_party_aliases() -> dict[str, dict[str, Any]]:
    store = {k: dict(v) for k, v in _SEED.items()}
    if ALIASES_PATH.is_file():
        try:
            payload = json.loads(ALIASES_PATH.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload, dict):
            for key, rec in payload.items():
                if not isinstance(rec, dict):
                    continue
                cur = store.setdefault(str(key), {"canonical": str(key), "aliases": []})
                if rec.get("canonical"):
                    cur["canonical"] = str(rec["canonical"])
                aliases = list(cur.get("aliases") or [])
                for alias in rec.get("aliases") or []:
                    if alias not in aliases:
                        aliases.append(str(alias))
                cur["aliases"] = aliases
                if rec.get("minimax_code"):
                    cur["minimax_code"] = str(rec["minimax_code"])
    return store


def save_party_aliases(store: dict[str, dict[str, Any]]) -> None:
    ALIASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALIASES_PATH.write_text(
        json.dumps(store, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def alias_search_terms(name: str) -> list[str]:
    """Iskalni nizi za Minimax: izvirnik + stisnjen + kanonični vzorec."""
    raw = sanitize_display_text(name)
    terms: list[str] = []
    for candidate in (raw, re.sub(r"\s+", "", raw)):
        if candidate and candidate not in terms:
            terms.append(candidate)
    compact = compact_alias(raw)
    if not compact:
        return terms
    store = load_party_aliases()
    for rec in store.values():
        aliases = [str(a) for a in rec.get("aliases") or []]
        keys = [compact_alias(str(rec.get("canonical") or ""))] + [compact_alias(a) for a in aliases]
        if compact in keys or any(compact and key and (compact in key or key in compact) for key in keys if len(key) >= 4):
            canon = sanitize_display_text(rec.get("canonical") or "")
            if canon and canon not in terms:
                terms.append(canon)
            for alias in aliases:
                a = sanitize_display_text(alias)
                if a and a not in terms:
                    terms.append(a)
    return terms


def remember_party_alias(
    seen_name: str,
    *,
    canonical: str = "",
    minimax_code: str = "",
) -> None:
    seen = sanitize_display_text(seen_name)
    official = sanitize_display_text(canonical) or seen
    key = compact_alias(official) or compact_alias(seen)
    if not key:
        return
    store = load_party_aliases()
    rec = store.setdefault(key, {"canonical": official, "aliases": []})
    rec["canonical"] = official or rec.get("canonical") or seen
    aliases = [str(a) for a in rec.get("aliases") or []]
    for alias in (seen, official):
        if alias and alias not in aliases:
            aliases.append(alias)
    rec["aliases"] = aliases
    if minimax_code:
        rec["minimax_code"] = str(minimax_code)
    save_party_aliases(store)


def names_match_alias(left: str, right: str) -> bool:
    a, b = compact_alias(left), compact_alias(right)
    if not a or not b:
        return False
    if a == b or (len(a) >= 5 and len(b) >= 5 and (a in b or b in a)):
        return True
    store = load_party_aliases()
    def keys(name: str) -> set[str]:
        c = compact_alias(name)
        out = {c} if c else set()
        for rec in store.values():
            pool = [str(rec.get("canonical") or "")] + [str(x) for x in rec.get("aliases") or []]
            comps = {compact_alias(x) for x in pool if x}
            if c in comps:
                out |= {x for x in comps if x}
        return out
    return bool(keys(left) & keys(right))
