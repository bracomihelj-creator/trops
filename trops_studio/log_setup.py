"""Rotacijski dnevnik samo za to namestitev (brez gesel in payloadov)."""
from __future__ import annotations
import logging
from logging.handlers import RotatingFileHandler
from trops_studio.config import LOG_DIR

def setup_logging() -> None:
    root = logging.getLogger()
    if any(getattr(h, '_trops', False) for h in root.handlers):
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(LOG_DIR / 'trops.log', maxBytes=2_000_000, backupCount=5, encoding='utf-8')
    handler._trops = True
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    root.addHandler(handler)
    root.setLevel(logging.INFO)
