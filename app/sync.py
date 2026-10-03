"""Event synchronization jobs."""

import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.database import init_db, list_sources, upsert_events
from app.date_utils import normalize_event_dates
from app.parsers.cyproplan import CyproplanParser
from app.parsers.etko import EtkoParser
from app.parsers.website import WebsiteParser
from app.parsers.aggregator import AggregatorParser
from app.parsers.facebook import FacebookParser, FacebookDiscoveryParser
from app.parsers.instagram import InstagramParser
from app.parsers.soldout import SoldOutParser
from app.parsers.telegram import TelegramParser
from app.translator import translate_event

logger = logging.getLogger(__name__)


def _normalize(events: list[dict]) -> list[dict]:
    normalized = []
    for event in events:
        normalize_event_dates(event)
        translate_event(event)
        raw = "|".join(
            str(event.get(key, "")).strip().lower()
            for key in ("title", "date", "end_date", "time", "venue", "city")
        )
        event["content_hash"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        event.setdefault("category", "События")
        normalized.append(event)
    return normalized


def _parse_source(source) -> list[dict]:
    name = source["name"]
    if name == "ETKO Cyprus":
        return EtkoParser().parse()
    if name == "Cyproplan":
        return CyproplanParser().parse()
    if name == "SoldOut TicketBox":
        return []
    if name == "EventOr":
        return AggregatorParser(source["url"], "EventOr").parse()
    if name == "Cyprus.BZ":
        return AggregatorParser(source["url"], "Cyprus.BZ").parse()
    if name == "More.com Cyprus":
        return AggregatorParser(source["url"], "More.com").parse()
    if source["type"] == "Website":
        return WebsiteParser(source["url"]).parse()
    if source["type"] == "FacebookDiscovery":
        return FacebookDiscoveryParser(source["url"]).parse()
    if source["type"] == "Facebook":
        return FacebookParser(source["url"]).parse()
    if source["type"] == "Telegram":
        return TelegramParser(source["url"]).parse()
    if source["type"] == "Instagram":
        return InstagramParser(source["url"]).parse()
    return []


def sync_etko() -> int:
    return upsert_events(_normalize(EtkoParser().parse()))


def sync_cyproplan() -> int:
    return upsert_events(_normalize(CyproplanParser().parse()))


def sync_soldout() -> int:
    return upsert_events(_normalize(SoldOutParser().parse()))


def sync_telegram_source(url: str) -> int:
    return upsert_events(_normalize(TelegramParser(url).parse()))


def sync_all() -> int:
    """Fetch sources concurrently, then write results to SQLite sequentially."""
    init_db()
    sources = [source for source in list_sources() if source["enabled"]]
    parsed: list[tuple[str, list[dict]]] = []

    # Network I/O happens in parallel. SQLite writes happen afterwards in one
    # thread, avoiding "database is locked" races between parser workers.
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(sources)))) as executor:
        futures = {
            executor.submit(_parse_source, source): source["name"]
            for source in sources
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                parsed.append((name, _normalize(future.result())))
            except Exception:
                logger.exception("%s sync failed", name)

    total = 0
    for name, events in parsed:
        try:
            added = upsert_events(events)
            total += added
            logger.info("%s sync: %s new events", name, added)
        except Exception:
            logger.exception("%s database update failed", name)

    return total
