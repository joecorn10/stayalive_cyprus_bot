"""Event synchronization jobs."""

import hashlib
import logging

from app.database import init_db, list_sources, upsert_events
from app.parsers.cyproplan import CyproplanParser
from app.parsers.etko import EtkoParser
from app.parsers.soldout import SoldOutParser
from app.parsers.telegram import TelegramParser

logger = logging.getLogger(__name__)


def _normalize(events: list[dict]) -> list[dict]:
    normalized = []
    for event in events:
        raw = "|".join(
            str(event.get(key, "")).strip().lower()
            for key in ("title", "date", "time", "venue")
        )
        event["content_hash"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        event.setdefault("category", "События")
        normalized.append(event)
    return normalized


def sync_etko() -> int:
    return upsert_events(_normalize(EtkoParser().parse()))


def sync_cyproplan() -> int:
    return upsert_events(_normalize(CyproplanParser().parse()))


def sync_soldout() -> int:
    return upsert_events(_normalize(SoldOutParser().parse()))


def sync_telegram_source(url: str) -> int:
    return upsert_events(_normalize(TelegramParser(url).parse()))


def sync_all() -> int:
    init_db()
    total = 0
    parsers = {
        "ETKO Cyprus": lambda: sync_etko(),
        "Cyproplan": lambda: sync_cyproplan(),
        "SoldOut TicketBox": lambda: sync_soldout(),
    }

    for source in list_sources():
        if not source["enabled"]:
            continue
        name = source["name"]
        try:
            if name in parsers:
                added = parsers[name]()
            elif source["type"] == "Telegram":
                added = sync_telegram_source(source["url"])
            else:
                continue
            total += added
            logger.info("%s sync: %s new events", name, added)
        except Exception:
            logger.exception("%s sync failed", name)
    return total
