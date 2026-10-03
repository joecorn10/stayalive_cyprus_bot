"""Event synchronization jobs."""

import hashlib
import re
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
from app.parsers.telegram_pinned import TelegramPinnedParser
from app.translator import translate_event

logger = logging.getLogger(__name__)


CATEGORY_ALIASES = {
    "музыка": "🎵 Музыка",
    "music": "🎵 Музыка",
    "концерт": "🎵 Музыка",
    "концерты": "🎵 Музыка",
    "festival": "🎪 Фестивали",
    "festivals": "🎪 Фестивали",
    "фестиваль": "🎪 Фестивали",
    "фестивали": "🎪 Фестивали",
    "theatre": "🎭 Театр и кино",
    "theater": "🎭 Театр и кино",
    "театр": "🎭 Театр и кино",
    "кино": "🎭 Театр и кино",
    "art": "🎨 Искусство",
    "искусство": "🎨 Искусство",
    "спорт": "🏃 Спорт и outdoor",
    "outdoor": "🏃 Спорт и outdoor",
    "market": "🛍 Маркеты и шопинг",
    "маркет": "🛍 Маркеты и шопинг",
    "workshop": "🧑‍🏫 Воркшопы",
    "воркшоп": "🧑‍🏫 Воркшопы",
    "семья": "👨‍👩‍👧 Семья",
    "family": "👨‍👩‍👧 Семья",
    "events": "",
    "события": "",
}

def canonical_category(category: str) -> str:
    value = str(category or "").strip()
    if not value:
        return ""
    return CATEGORY_ALIASES.get(value.casefold(), value)

CATEGORY_RULES = (
    ("🎵 Музыка", re.compile(r"\b(concert|live|music|dj|djs|band|gig|singer|pianist|музык|концерт|диджей|ди-джей|группа|певец|джаз|techno|house)\b", re.I)),
    ("🍷 Еда и вино", re.compile(r"\b(wine|tasting|dinner|food|chef|restaurant|winery|дегустац|вино|ужин|еда|шеф|ресторан|вин|гастроном)\b", re.I)),
    ("🎨 Искусство", re.compile(r"\b(art|gallery|exhibition|opening|museum|painting|sculpture|искусств|выстав|галере|музе|живопис|скульптур|фото)\b", re.I)),
    ("🪩 Nightlife", re.compile(r"\b(party|club|night|rave|disco|nightlife|вечерин|клуб|рейв|ночь|танц)\b", re.I)),
    ("🎭 Театр и кино", re.compile(r"\b(theatre|theater|cinema|movie|film|screening|play|театр|кино|фильм|показ|спектакл)\b", re.I)),
    ("🧑‍🏫 Воркшопы", re.compile(r"\b(workshop|masterclass|class|seminar|lecture|course|мастер[- ]?класс|воркшоп|семинар|лекци|курс|занят)\b", re.I)),
    ("🏃 Спорт и outdoor", re.compile(r"\b(run|running|hike|hiking|yoga|fitness|football|basketball|cycling|sport|outdoor|марафон|бег|поход|йог|фитнес|футбол|баскетбол|велопрогул|спорт)\b", re.I)),
    ("🛍 Маркеты и шопинг", re.compile(r"\b(market|bazaar|flea|pop[- ]?up|shopping|makers|craft fair|маркет|базар|ярмарк|барахол|шопинг|дизайн[- ]?маркет)\b", re.I)),
    ("👨‍👩‍👧 Семья", re.compile(r"\b(kids|children|family|families|дет|семейн|для детей)\b", re.I)),
    ("🎪 Фестивали", re.compile(r"\b(festival|фестиваль|карнавал|carnival)\b", re.I)),
)

def classify_event(event: dict) -> str:
    explicit = canonical_category(event.get("category"))
    if explicit:
        return explicit
    text = " ".join(str(event.get(key, "")) for key in ("title", "description", "venue", "city"))
    for category, pattern in CATEGORY_RULES:
        if pattern.search(text):
            return category
    return "✨ Другое"

def _normalize(events: list[dict]) -> list[dict]:
    normalized = []
    for event in events:
        normalize_event_dates(event)
        translate_event(event)
        event["category"] = classify_event(event)
        raw = "|".join(str(event.get(key, "")).strip().lower() for key in ("title", "date", "end_date", "time", "venue", "city", "category"))
        event["content_hash"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
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
    if source["type"] == "TelegramPinned":
        match = re.search(r"chat_id=(-?\\d+)", source["comment"] or "")
        if not match:
            logger.info("%s: chat_id not registered yet", name)
            return []
        from app.config import TELEGRAM_BOT_TOKEN
        return TelegramPinnedParser(
            TELEGRAM_BOT_TOKEN,
            int(match.group(1)),
            source["url"],
        ).parse()
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


def sync_pinned_telegram_chat(token: str, chat_id: int, source_url: str) -> int:
    events = _normalize(TelegramPinnedParser(token, chat_id, source_url).parse())
    return upsert_events(events)
