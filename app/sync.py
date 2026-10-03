"""Event synchronization jobs."""

import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

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
            for key in ("title", "date", "end_date", "time", "venue", "city")
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


def _run_source(source) -> tuple[str, int]:
    name = source["name"]
    try:
        if name == "ETKO Cyprus":
            added = sync_etko()
        elif name == "Cyproplan":
            added = sync_cyproplan()
        elif name == "SoldOut TicketBox":
            added = sync_soldout()
        elif source["type"] == "Telegram":
            added = sync_telegram_source(source["url"])
        else:
            return name, 0
        return name, added
    except Exception:
        logger.exception("%s sync failed", name)
        return name, 0


def sync_all() -> int:
    """Sync enabled sources concurrently so one slow source does not block all others."""
    init_db()
    sources = [source for source in list_sources() if source["enabled"]]
    total = 0

    # Parsers do network I/O. Run them concurrently, but each parser still
    # performs its own short SQLite transaction when it has results.
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(sources)))) as executor:
        futures = [executor.submit(_run_source, source) for source in sources]
        for future in as_completed(futures):
            name, added = future.result()
            total += added
            logger.info("%s sync: %s new events", name, added)

    return total
