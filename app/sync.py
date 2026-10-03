"""Event synchronization jobs."""

import hashlib
import logging

from app.database import init_db, upsert_events
from app.parsers.etko import EtkoParser

logger = logging.getLogger(__name__)


def sync_etko() -> int:
    parser = EtkoParser()
    events = parser.parse()

    normalized = []
    for event in events:
        raw = "|".join(
            str(event.get(key, "")).strip().lower()
            for key in ("title", "date", "time", "venue")
        )
        event["content_hash"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        event.setdefault("category", "События")
        normalized.append(event)

    return upsert_events(normalized)


def sync_all() -> int:
    init_db()
    try:
        added = sync_etko()
        logger.info("ETKO sync: %s new events", added)
        return added
    except Exception:
        logger.exception("ETKO sync failed")
        return 0
