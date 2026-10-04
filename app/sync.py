"""Event synchronization jobs."""

import hashlib
import re
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.database import get_source_by_url, init_db, list_sources, upsert_events
from app.date_utils import normalize_event_dates
from app.parsers.cyproplan import CyproplanParser
from app.parsers.cyprus_underground import CyprusUndergroundParser
from app.parsers.etko import EtkoParser
from app.parsers.website import WebsiteParser
from app.parsers.aggregator import AggregatorParser
from app.parsers.facebook import FacebookParser, FacebookDiscoveryParser
from app.parsers.instagram import InstagramParser
from app.parsers.soldout import SoldOutParser
from app.parsers.music_sites import MusicSiteParser
from app.parsers.telegram import TelegramParser
from app.parsers.telegram_pinned import TelegramPinnedParser
from app.translator import translate_event

logger = logging.getLogger(__name__)


CATEGORY_ALIASES = {
    "музыка": "🎵 Музыка",
    "comedy": "🎭 Comedy",
    "стендап": "🎭 Comedy",
    "комедия": "🎭 Comedy",
    "еда и напитки": "🍷 Еда и вино",
    "еда и напиток": "🍷 Еда и вино",
    "food": "🍷 Еда и вино",
    "food & drink": "🍷 Еда и вино",
    "food and drinks": "🍷 Еда и вино",
    "еда": "🍷 Еда и вино",
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

CATEGORY_LABELS = {
    "🎵 Музыка",
    "🎭 Comedy",
    "🍷 Еда и вино",
    "🎨 Искусство",
    "🪩 Nightlife",
    "🎭 Театр и кино",
    "🧑‍🏫 Воркшопы",
    "🏃 Спорт и outdoor",
    "🛍 Маркеты и шопинг",
    "👨‍👩‍👧 Семья",
    "🎪 Фестивали",
    "✨ Другое",
}

def canonical_category(category: str) -> str:
    value = str(category or "").strip()
    if not value:
        return ""
    if value in CATEGORY_LABELS:
        return value

    # Sources use slightly different labels (singular/plural, English/Russian,
    # or a leading emoji). Normalize them to one UI category.
    plain = re.sub(r"^[^A-Za-zА-Яа-яЁё]+", "", value).strip().casefold()
    if plain in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[plain]

    for alias, label in CATEGORY_ALIASES.items():
        if plain.startswith(alias + " ") or plain.startswith(alias + "/"):
            return label

    if plain in {"event", "events", "событие", "события"}:
        return ""
    return value

CATEGORY_RULES = (
    ("🎭 Comedy", re.compile(r"\b(stand[- ]?up|comedy|comedian|open mic|стендап|стендапер|комед\w*|комик\w*|юмор)\b", re.I)),
    ("🧑‍🏫 Воркшопы", re.compile(r"\b(workshop|masterclass|master class|class|seminar|lecture|course|мастер[- ]?класс|воркшоп|семинар|лекци|курс|занят)\b", re.I)),
    ("🎪 Фестивали", re.compile(r"\b(festival|фестиваль|карнавал|carnival|fest)\b", re.I)),
    ("🏃 Спорт и outdoor", re.compile(r"\b(run|running|hike|hiking|trek|trekking|picnic|nature|yoga|fitness|football|basketball|cycling|sport|outdoor|марафон|бег|поход|пикник|природ|треккинг|йог|фитнес|футбол|баскетбол|велопрогул|спорт)\b", re.I)),
    ("🍷 Еда и вино", re.compile(r"\b(wine|tasting|dinner|food|chef|restaurant|winery|beer|cocktail|дегустац|вино|ужин|еда|шеф|ресторан|вин|пиво|коктейл|гастроном)\b", re.I)),
    ("🎨 Искусство", re.compile(r"\b(art|gallery|exhibition|opening|museum|painting|sculpture|photo|искусств|выстав|галере|музе|живопис|скульптур|фото)\b", re.I)),
    ("🛍 Маркеты и шопинг", re.compile(r"\b(market|bazaar|flea|pop[- ]?up|shopping|makers|craft fair|маркет|базар|ярмарк|барахол|шопинг|дизайн[- ]?маркет)\b", re.I)),
    ("👨‍👩‍👧 Семья", re.compile(r"\b(kids|children|family|families|дет\w*|семейн|для детей)\b", re.I)),
    ("🎭 Театр и кино", re.compile(r"\b(theatre|theater|cinema|movie|film|screening|play|театр|кино|фильм|показ|спектакл)\b", re.I)),
    ("🪩 Nightlife", re.compile(r"\b(party|club|rave|disco|nightlife|вечерин\w*|клуб\w*|рейв|дискотек|ночн\w*|танц\w*)\b", re.I)),
    ("🎵 Музыка", re.compile(r"\b(concert|live music|music|band|gig|singer|pianist|concerts|музык\w*|концерт\w*|диджей|ди-джей|группа|певец|джаз|джем|jazz|blues)\b", re.I)),
)

# Category detection is deliberately title-first and weighted. The old
# first-match regex made generic words in descriptions (e.g. "night" or
# "music") swallow hikes, workshops and festivals into Nightlife/Music.
CATEGORY_WEIGHTS = {
    "🎭 Comedy": 7,
    "🧑‍🏫 Воркшопы": 7,
    "🎪 Фестивали": 7,
    "🏃 Спорт и outdoor": 7,
    "🍷 Еда и вино": 6,
    "🎨 Искусство": 6,
    "🛍 Маркеты и шопинг": 6,
    "👨‍👩‍👧 Семья": 6,
    "🎭 Театр и кино": 6,
    "🪩 Nightlife": 6,
    "🎵 Музыка": 5,
}

def _category_score(category: str, title: str, description: str, venue: str, explicit: str) -> tuple[int, str]:
    pattern = dict(CATEGORY_RULES)[category]
    title_hits = len(pattern.findall(title))
    description_hits = len(pattern.findall(description))
    venue_hits = len(pattern.findall(venue))
    score = title_hits * CATEGORY_WEIGHTS[category] + description_hits * 2 + venue_hits
    reasons = []
    if title_hits:
        reasons.append(f"title={title_hits}")
    if description_hits:
        reasons.append(f"description={description_hits}")
    if venue_hits:
        reasons.append(f"venue={venue_hits}")
    if explicit == category:
        score += 3
        reasons.append("source_category")
    return score, ",".join(reasons)

def classify_event(event: dict) -> str:
    source_url = str(event.get("source_url", "") or "").lower()
    title = str(event.get("title", "") or "")
    description = str(event.get("description", "") or "")
    venue = str(event.get("venue", "") or "")
    explicit = canonical_category(event.get("category"))

    # Strong source-specific facts.
    if "stantarkkomety.com" in source_url:
        return "🎭 Comedy"

    scores = []
    for category, _pattern in CATEGORY_RULES:
        score, reason = _category_score(category, title, description, venue, explicit)
        if score:
            scores.append((score, category, reason))

    # Cyprus Underground is a nightlife source, but not every listing should
    # be forced into Nightlife. Only use the source as a tie-breaker when the
    # event itself looks like a club/electronic-music event.
    if "cyprusunderground.com.cy" in source_url:
        electronic = re.search(
            r"\b(techno|house|deep house|tech house|minimal|progressive|psy|psytrance|drum.?n.?bass|dnb|electro|breaks|trance|club|rave|dj)\b",
            f"{title} {description} {venue}",
            re.I,
        )
        if electronic:
            scores.append((6, "🪩 Nightlife", "cyprus_underground"))

    if not scores:
        return explicit or "✨ Другое"

    # Require a meaningful lead over a generic source category.
    scores.sort(key=lambda item: (-item[0], item[1]))
    best_score, best_category, _reason = scores[0]
    if explicit and explicit in CATEGORY_WEIGHTS:
        explicit_score = next((s for s, cat, _ in scores if cat == explicit), 0)
        if best_category != explicit and best_score < explicit_score + 3:
            return explicit
    return best_category

