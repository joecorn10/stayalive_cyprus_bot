"""Event synchronization jobs."""

# Scheduled sync also performs semantic category and duplicate cleanup.

import hashlib
import json
import re
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.database import deduplicate_events, get_source_by_url, init_db, list_sources, upsert_events
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
    "nightlife": "🪩 Nightlife",
    "вечеринки": "🪩 Nightlife",
    "вечеринка": "🪩 Nightlife",
    "parties": "🪩 Nightlife",
    "party": "🪩 Nightlife",
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
    ("🎭 Comedy", re.compile(r"\b(stand[- ]?up|standup|comedy|comedian|comic|open mic|improv|improvisation|roast|sketch comedy|funny|стендап|стендапер|комед\w*|комик\w*|юмор\w*|импровизац\w*|роуст|смешн\w*)\b", re.I)),
    ("🧑‍🏫 Воркшопы", re.compile(r"\b(workshop|workshops|masterclass|master class|class|classes|course|courses|seminar|seminars|lecture|lectures|talk|training|training session|lesson|lessons|hands[- ]?on|tutorial|воркшоп\w*|мастер[- ]?класс\w*|класс\w*|курс\w*|семинар\w*|лекци\w*|заняти\w*|обучени\w*|тренинг\w*|урок\w*|практикум\w*)\b", re.I)),
    ("🎪 Фестивали", re.compile(r"\b(festival|festivals|fest|festive|carnival|carnivals|фестиваль\w*|фест\w*|карнавал\w*|праздник\w*)\b", re.I)),
    ("🏃 Спорт и outdoor", re.compile(r"\b(run|running|runner|race|marathon|half marathon|trail run|trail running|hike|hiking|hiker|trek|trekking|walk|walking|bike|biking|cycling|cyclist|ride|yoga|pilates|fitness|workout|gym|football|basketball|volleyball|tennis|padel|swimming|surfing|kitesurfing|watersports|sport|sports|outdoor|nature|wellness|retreat|picnic|beach walk|climb|climbing|марафон\w*|забег\w*|бег\w*|пробег\w*|поход\w*|треккинг\w*|прогул\w*|велосипед\w*|велопрогул\w*|велозаезд\w*|йог\w*|пилатес\w*|фитнес\w*|трениров\w*|спорт\w*|футбол\w*|баскетбол\w*|волейбол\w*|теннис\w*|падел\w*|плаван\w*|серф\w*|кайтсерф\w*|аутдор|природ\w*|пикник\w*|скалолаз\w*|кемпинг\w*)\b", re.I)),
    ("🍷 Еда и вино", re.compile(r"\b(wine|wines|winery|winemaker|wine tasting|tasting|tastings|degustation|dinner|dinners|lunch|brunch|breakfast|food|foodie|chef|chefs|restaurant|restaurants|bistro|osteria|beer|beers|cocktail|cocktails|mixology|spirits|gin|whisky|whiskey|rum|aperitivo|aperitif|pairing|food pairing|gourmet|gastronomy|bakery|baking|street food|вино\w*|винодель\w*|виноград\w*|дегустац\w*|ужин\w*|обед\w*|бранч\w*|завтрак\w*|еда|ед\w*|гастроном\w*|шеф\w*|ресторан\w*|бистр\w*|остери\w*|пиво\w*|коктейл\w*|джин\w*|виски\w*|ром\w*|аперитив\w*|сочетани\w*|фуд\w*|кулинар\w*|выпечк\w*|вин\w*)\b", re.I)),
    ("🎨 Искусство", re.compile(r"\b(art|arts|artist|artists|artwork|artworks|gallery|galleries|exhibition|exhibitions|opening|vernissage|museum|museums|painting|paintings|sculpture|sculptures|photography|photo exhibition|photographer|illustration|illustrator|drawing|drawings|design|designer|craft|crafts|ceramics|pottery|installation|installations|visual arts|contemporary art|modern art|performance art|искусств\w*|худож\w*|арт\w*|выстав\w*|экспозиц\w*|галере\w*|музе\w*|живопис\w*|скульптур\w*|фотограф\w*|иллюстрац\w*|рисован\w*|дизайн\w*|дизайнер\w*|ремесл\w*|керамик\w*|гончар\w*|инсталляц\w*|перформанс\w*)\b", re.I)),
    ("🛍 Маркеты и шопинг", re.compile(r"\b(market|markets|bazaar|bazaars|flea market|flea markets|pop[- ]?up|popup|shopping|shop|shops|makers market|craft fair|design market|street market|farmers market|vintage market|маркет\w*|базар\w*|барахол\w*|ярмарк\w*|фримаркет|поп[- ]?ап|шопинг\w*|магазин\w*|дизайн[- ]?маркет\w*|фермерск\w*|винтажн\w*|крафт[- ]?маркет\w*)\b", re.I)),
    ("👨‍👩‍👧 Семья", re.compile(r"\b(kids|kid|children|child|family|families|family-friendly|for kids|for children|parents|baby|babies|toddler|teen|teens|дет\w*|ребён\w*|ребен\w*|семейн\w*|для детей|родител\w*|малыш\w*|подрост\w*)\b", re.I)),
    ("🎭 Театр и кино", re.compile(r"\b(theatre|theater|cinema|movie|movies|film|films|screening|screenings|play|plays|musical|opera|ballet|dance performance|contemporary dance|performing arts|stage|staged|театр\w*|кино\w*|фильм\w*|показ\w*|спектакл\w*|мюзикл\w*|опера\w*|балет\w*|хореограф\w*|танцевальн\w*|сцен\w*|постановк\w*)\b", re.I)),
    ("🪩 Nightlife", re.compile(r"\b(party|parties|club|clubs|club night|clubnight|rave|raves|disco|discotheque|nightlife|night life|dj|dj set|dj night|techno|hard techno|melodic techno|house music|deep house|tech house|afro house|melodic house|progressive house|minimal|minimal techno|psytrance|psy trance|trance|drum.?n.?bass|dnb|electro|electronic|electronica|indiedance|nu disco|downtempo|dancefloor|dance floor|all night long|afterparty|after party|warehouse party|вечерин\w*|клуб\w*|рейв\w*|дискотек\w*|ночн\w*|диджей|ди-джей|техно|хаус|транс|электро\w*|электронн\w*|танцпол\w*)\b", re.I)),
    ("🎵 Музыка", re.compile(r"\b(concert|concerts|live music|live|music|musician|musicians|band|bands|gig|gigs|singer|singers|vocal|vocalist|pianist|violin|orchestra|ensemble|choir|jazz|blues|soul|funk|rock|indie|acoustic|songwriter|jam|jamming|session|music night|concert hall|музык\w*|концерт\w*|группа\w*|пев\w*|вокал\w*|пианист\w*|скрипач\w*|оркестр\w*|ансамбл\w*|хор\w*|джаз\w*|блюз\w*|соул\w*|фанк\w*|рок\w*|инди\w*|акустик\w*|авторск\w*|джем\w*|сесс\w*)\b", re.I)),
)

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

def classify_event(event: dict) -> list[str]:
    """Return every meaningful category supported by the event."""
    source_url = str(event.get("source_url", "") or "").lower()
    title = str(event.get("title", "") or "")
    description = str(event.get("description", "") or "")
    venue = str(event.get("venue", "") or "")
    explicit = canonical_category(event.get("category"))

    if "stantarkkomety.com" in source_url:
        return ["🎭 Comedy"]

    title_scores = []
    all_scores = []
    for category, pattern in CATEGORY_RULES:
        score, reason = _category_score(category, title, description, venue, explicit)
        title_hits = len(pattern.findall(title))
        description_hits = len(pattern.findall(description))
        venue_hits = len(pattern.findall(venue))
        all_scores.append((score, category, reason, title_hits, description_hits, venue_hits))
        if title_hits:
            title_scores.append((title_hits * CATEGORY_WEIGHTS[category], category))

    # Multiple title themes are allowed: "Wine & Art Opening" -> Food + Art.
    if title_scores:
        title_scores.sort(key=lambda item: (-item[0], item[1]))
        selected = [category for _score, category in title_scores]
        best_title = title_scores[0][0]
        for score, category, _reason, _title_hits, desc_hits, venue_hits in all_scores:
            if category in selected:
                continue
            if desc_hits >= 2 and score >= max(4, best_title * 0.35):
                selected.append(category)
        return list(dict.fromkeys(selected)) or ([explicit] if explicit else ["✨ Другое"])

    # No title signal: keep multiple strong contextual categories when close
    # enough to the best signal.
    scores = [item for item in all_scores if item[0]]
    if not scores:
        return [explicit] if explicit else ["✨ Другое"]
    scores.sort(key=lambda item: (-item[0], item[1]))
    best_score = scores[0][0]
    selected = []
    for score, category, _reason, _title_hits, desc_hits, venue_hits in scores:
        if score < 2:
            continue
        if score >= max(2, best_score * 0.5) and (desc_hits >= 1 or venue_hits >= 2):
            selected.append(category)

    if explicit and explicit not in selected:
        explicit_score = next((score for score, cat, *_rest in scores if cat == explicit), 0)
        if not selected or explicit_score >= best_score * 0.5:
            selected.append(explicit)
    if not selected:
        selected = [scores[0][1]]

    if "cyprusunderground.com.cy" in source_url:
        electronic = re.search(
            r"\b(techno|house|deep house|tech house|minimal|progressive|psy|psytrance|drum.?n.?bass|dnb|electro|breaks|trance|club|rave|dj)\b",
            f"{title} {description} {venue}", re.I,
        )
        if electronic and "🪩 Nightlife" not in selected:
            selected.append("🪩 Nightlife")
    return list(dict.fromkeys(selected))


def _event_categories(event: dict) -> list[str]:
    """Read multi-category data with backward compatibility for old rows."""
    raw = event.get("categories", "")
    if raw:
        try:
            values = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError, json.JSONDecodeError):
            values = []
        if isinstance(values, list):
            result = [canonical_category(value) for value in values]
            return list(dict.fromkeys(value for value in result if value))
    category = canonical_category(event.get("category"))
    return [category] if category else ["✨ Другое"]


def _normalize(events: list[dict]) -> list[dict]:
    normalized = []
    for event in events:
        normalize_event_dates(event)
        translate_event(event)
        categories = classify_event(event)
        event["categories"] = json.dumps(categories, ensure_ascii=False)
        event["category"] = categories[0] if categories else "✨ Другое"
        raw = "|".join(str(event.get(key, "")).strip().lower() for key in ("title","date","end_date","time","venue","city"))
        event["content_hash"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        normalized.append(event)
    return normalized


def recategorize_existing_events() -> int:
    """Reclassify stored events using the current multi-category rules."""
    from app.database import get_connection
    changed = 0
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM events").fetchall()
        for row in rows:
            event = dict(row)
            event["category"] = ""
            event["categories"] = ""
            categories = classify_event(event)
            categories_json = json.dumps(categories, ensure_ascii=False)
            primary = categories[0] if categories else "✨ Другое"
            if primary != (row["category"] or "") or categories_json != (row["categories"] or ""):
                conn.execute("UPDATE events SET category = ?, categories = ? WHERE id = ?", (primary, categories_json, row["id"]))
                changed += 1
        conn.commit()
    return changed


def _parse_source(source) -> list[dict]:
    name = source["name"]
    if name == "ETKO Cyprus":
        return EtkoParser().parse()
    if name == "Cyproplan":
        return CyproplanParser().parse()
    if name == "SoldOut TicketBox":
        return SoldOutParser(source["url"]).parse()
    if name in {"Music Hall", "Live Music Zone"}:
        return MusicSiteParser(source["url"]).parse()
    if name == "Cyprus Underground":
        return CyprusUndergroundParser(source["url"]).parse()
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


def sync_source(source) -> int:
    """Sync one registered source without touching the rest of the catalogue."""
    init_db()
    events = _normalize(_parse_source(source))
    added = upsert_events(events)

    # Targeted syncs are used by Telegram Today/Week. Keep the visible
    # catalogue clean even when only one source was refreshed.
    recategorized = recategorize_existing_events()
    if recategorized:
        logger.info("Targeted sync reclassified %s existing events", recategorized)
    deduplicated = deduplicate_events()
    if deduplicated:
        logger.info("Targeted sync merged %s semantic duplicate events", deduplicated)

    logger.info("%s targeted sync: %s new events", source["name"], added)
    return added


def sync_source_by_url(url: str) -> int:
    """Sync the registered source identified by its canonical URL."""
    source = get_source_by_url(url)
    if not source:
        return 0
    return sync_source(source)


def sync_all() -> int:
    """Fetch sources concurrently, then write results to SQLite sequentially."""
    init_db()
    sources = [source for source in list_sources() if source["enabled"]]
    parsed: list[tuple[str, list[dict]]] = []

    with ThreadPoolExecutor(max_workers=min(6, max(1, len(sources)))) as executor:
        futures = {
            executor.submit(_parse_source, source): source["name"]
            for source in sources
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                events = _normalize(future.result())
                print(f"SOURCE_RESULT | {name} | {len(events)} events")
                parsed.append((name, events))
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

    recategorized = recategorize_existing_events()
    if recategorized:
        logger.info("Reclassified %s existing events", recategorized)

    deduplicated = deduplicate_events()
    if deduplicated:
        logger.info("Merged %s semantic duplicate events", deduplicated)

    return total


def sync_pinned_telegram_chat(token: str, chat_id: int, source_url: str) -> int:
    events = _normalize(TelegramPinnedParser(token, chat_id, source_url).parse())
    return upsert_events(events)
