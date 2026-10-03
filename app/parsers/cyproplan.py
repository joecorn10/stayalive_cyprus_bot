"""Cyproplan event parser.

Cyproplan exposes a public event catalogue and individual /event/... pages.
The catalogue can be rendered differently depending on the client, so the
parser uses several discovery pages and then enriches each event from its
detail page.
"""

import json
import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.parsers.base import EventParser

BASE_URL = "https://cyproplan.com/"
DISCOVERY_URLS = (
    "https://cyproplan.com/",
    "https://cyproplan.com/index_m",
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; StayAliveCyprusBot/1.0)",
    "Accept-Language": "en-US,en;q=0.8",
}
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


class CyproplanParser(EventParser):
    def __init__(self, url: str = BASE_URL):
        self.url = url

    def parse(self) -> list[dict]:
        session = requests.Session()
        session.headers.update(HEADERS)

        event_urls: list[str] = []
        seen_urls: set[str] = set()

        for discovery_url in DISCOVERY_URLS:
            try:
                response = session.get(discovery_url, timeout=20)
                response.raise_for_status()
            except requests.RequestException:
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            for link in soup.find_all("a", href=True):
                href = urljoin(discovery_url, link["href"]).split("#", 1)[0]
                if not _is_event_url(href) or href in seen_urls:
                    continue
                seen_urls.add(href)
                event_urls.append(href)

        events = []
        for event_url in event_urls:
            try:
                event = _parse_event_page(session, event_url)
            except requests.RequestException:
                continue
            except Exception:
                continue
            if event:
                events.append(event)

        return events


def _is_event_url(url: str) -> bool:
    return (
        url.startswith("https://cyproplan.com/event/")
        and url.rstrip("/") != "https://cyproplan.com/event"
    )


def _parse_event_page(session: requests.Session, url: str) -> dict | None:
    response = session.get(url, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    structured = _json_ld(soup)
    title = (
        structured.get("name")
        or _meta(soup, "og:title")
        or _heading(soup)
    )
    if not title:
        return None
    title = _clean(title)

    text = " ".join(soup.stripped_strings)
    date_value, end_date = _extract_dates(soup, structured, text)
    if not date_value:
        return None

    time_value = _extract_time(soup, structured, text)
    venue, city = _extract_location(soup, structured, text)
    price = _extract_price(soup, structured, text)
    image_url = (
        structured.get("image")
        if isinstance(structured.get("image"), str)
        else _meta(soup, "og:image")
    ) or ""
    ticket_url = _external_ticket_url(soup, url)

    description = _description(soup, structured, text)
    category = _extract_category(text)

    return {
        "title": title[:200],
        "description": description[:4000],
        "date": date_value,
        "end_date": end_date or date_value,
        "time": time_value,
        "venue": venue,
        "city": city,
        "price": price,
        "ticket_url": ticket_url or url,
        "source_url": url,
        "image_url": image_url,
        "category": category,
    }


def _json_ld(soup: BeautifulSoup) -> dict:
    """Return the first Event object, including JSON-LD @graph wrappers."""
    for node in soup.select('script[type="application/ld+json"]'):
        raw = node.string or node.get_text()
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue

        candidates = []
        if isinstance(data, list):
            candidates.extend(data)
        elif isinstance(data, dict):
            candidates.append(data)
            graph = data.get("@graph")
            if isinstance(graph, list):
                candidates.extend(graph)

        for item in candidates:
            if not isinstance(item, dict):
                continue
            event_type = item.get("@type")
            types = event_type if isinstance(event_type, list) else [event_type]
            if "Event" in types or "startDate" in item:
                return item
            nested = item.get("event")
            if isinstance(nested, dict):
                return nested
    return {}
def _meta(soup: BeautifulSoup, name: str) -> str:
    node = soup.find("meta", attrs={"property": name}) or soup.find(
        "meta", attrs={"name": name}
    )
    return _clean(node.get("content", "")) if node else ""


def _heading(soup: BeautifulSoup) -> str:
    for tag in soup.find_all(["h1", "h2"], limit=5):
        value = _clean(tag.get_text(" ", strip=True))
        if value:
            return value
    return ""


def _extract_dates(soup: BeautifulSoup, structured: dict, text: str):
    """Extract an inclusive event date range from structured or visible page data."""
    start = structured.get("startDate")
    end = structured.get("endDate")
    if isinstance(start, dict):
        start = start.get("startDate") or start.get("date")
    if isinstance(end, dict):
        end = end.get("endDate") or end.get("date")
    if start:
        parsed = _iso_date(start)
        if parsed:
            return parsed, _iso_date(end) or parsed

    year = datetime.now().year
    month = r"(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
    month_map = {**MONTHS, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
                 "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12}

    # Search the whole page, but support all common Cyproplan range layouts.
    candidate = text.replace("–", "-").replace("—", "-")

    match = re.search(
        rf"\b{month}\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*"
        rf"(?:\([^)]*\))?\s*-\s*"
        rf"{month}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b",
        candidate, re.I,
    )
    if match:
        sm = month_map[match.group(1).lower()]
        em = month_map[match.group(3).lower()]
        ey = year + (1 if em < sm else 0)
        return f"{year:04d}-{sm:02d}-{int(match.group(2)):02d}", f"{ey:04d}-{em:02d}-{int(match.group(4)):02d}"

    match = re.search(
        rf"\b{month}\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*-\s*(\d{{1,2}})(?:st|nd|rd|th)?\b",
        candidate, re.I,
    )
    if match:
        m = month_map[match.group(1).lower()]
        return f"{year:04d}-{m:02d}-{int(match.group(2)):02d}", f"{year:04d}-{m:02d}-{int(match.group(3)):02d}"

    match = re.search(
        rf"\b(\d{{1,2}})\s+{month}\s*-\s*(\d{{1,2}})\s+{month}\b",
        candidate, re.I,
    )
    if match:
        sm = month_map[match.group(2).lower()]
        em = month_map[match.group(4).lower()]
        ey = year + (1 if em < sm else 0)
        return f"{year:04d}-{sm:02d}-{int(match.group(1)):02d}", f"{ey:04d}-{em:02d}-{int(match.group(3)):02d}"

    match = re.search(
        rf"\b(\d{{1,2}})\s*-\s*(\d{{1,2}})\s+{month}\b",
        candidate, re.I,
    )
    if match:
        m = month_map[match.group(3).lower()]
        return f"{year:04d}-{m:02d}-{int(match.group(1)):02d}", f"{year:04d}-{m:02d}-{int(match.group(2)):02d}"

    match = re.search(
        rf"\b{month}\s+(\d{{1,2}})\s*-\s*(\d{{1,2}})\b",
        candidate, re.I,
    )
    if match:
        m = month_map[match.group(1).lower()]
        return f"{year:04d}-{m:02d}-{int(match.group(2)):02d}", f"{year:04d}-{m:02d}-{int(match.group(3)):02d}"

    # Single date fallback.
    match = re.search(rf"\b{month}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", candidate, re.I)
    if match:
        m = month_map[match.group(1).lower()]
        value = f"{year:04d}-{m:02d}-{int(match.group(2)):02d}"
        return value, value

    return None, None
def _iso_date(value: str | None) -> str | None:
    if not value:
        return None
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(value))
    return match.group(0) if match else None


def _extract_time(soup: BeautifulSoup, structured: dict, text: str) -> str:
    value = structured.get("startDate")
    if value:
        match = re.search(r"T(\d{2}:\d{2})", str(value))
        if match:
            start = match.group(1)
            end_value = structured.get("endDate")
            end_match = re.search(r"T(\d{2}:\d{2})", str(end_value or ""))
            return f"{start}-{end_match.group(1)}" if end_match else start

    match = re.search(
        r"\b([01]?\d|2[0-3]):([0-5]\d)\s*[-–]\s*([01]?\d|2[0-3]):([0-5]\d)\b",
        text,
    )
    if match:
        return f"{int(match.group(1)):02d}:{match.group(2)}-{int(match.group(3)):02d}:{match.group(4)}"
    match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
    return f"{int(match.group(1)):02d}:{match.group(2)}" if match else ""


def _extract_location(soup: BeautifulSoup, structured: dict, text: str):
    location = structured.get("location")
    if isinstance(location, dict):
        name = _clean(location.get("name", ""))
        address = location.get("address", {})
        if isinstance(address, dict):
            city = _clean(address.get("addressLocality", ""))
        else:
            city = ""
        if name or city:
            return name, city

    # The rendered page normally places the venue immediately before the city.
    lines = [_clean(x) for x in soup.stripped_strings if _clean(x)]
    cities = ("Limassol", "Lemesos", "Nicosia", "Larnaca", "Paphos", "Protaras", "Ayia Napa")
    for index, line in enumerate(lines):
        if any(city.lower() in line.lower() for city in cities):
            city = next(city for city in cities if city.lower() in line.lower())
            venue = lines[index - 1] if index else ""
            if venue and len(venue) < 160:
                return venue, "Limassol" if city == "Lemesos" else city
    return "", ""


def _extract_price(soup: BeautifulSoup, structured: dict, text: str) -> str:
    offers = structured.get("offers")
    if isinstance(offers, dict):
        price = offers.get("price")
        if price is not None:
            return "Free" if str(price) == "0" else f"{price} €"
    if re.search(r"\bFree\b", text, re.I):
        return "Free"
    match = re.search(r"(?:Price:\s*)?(\d+(?:[.,]\d+)?)\s*€", text, re.I)
    return f"{match.group(1)} €" if match else ""


def _external_ticket_url(soup: BeautifulSoup, page_url: str) -> str:
    for link in soup.find_all("a", href=True):
        href = urljoin(page_url, link["href"])
        if not href.startswith("http") or "cyproplan.com" in href:
            continue
        label = _clean(link.get_text(" ", strip=True)).lower()
        if any(x in label for x in ("ticket", "buy", "register", "registration", "билет")):
            return href
    return ""


def _description(soup: BeautifulSoup, structured: dict, text: str) -> str:
    if structured.get("description"):
        return _clean(structured["description"])
    node = soup.find(string=re.compile(r"About", re.I))
    if node:
        parent = node.parent
        value = parent.parent.get_text(" ", strip=True) if parent and parent.parent else ""
        return _clean(value)
    return text[:4000]


def _extract_category(text: str) -> str:
    lower = text.lower()
    mapping = (
        (("concert", "music", "jazz", "soul"), "Музыка"),
        (("theater", "theatre", "comedy", "stand-up"), "Театр"),
        (("art", "gallery", "exhibition"), "Искусство"),
        (("festival",), "Фестиваль"),
        (("sport", "race", "run", "tournament"), "Спорт"),
        (("food", "wine", "beer", "gastronom"), "Еда и напитки"),
        (("kid", "children", "family"), "Для детей"),
        (("business", "conference", "education"), "Бизнес"),
    )
    for words, category in mapping:
        if any(word in lower for word in words):
            return category
    return "События"


def _clean(value: str) -> str:
    return " ".join(str(value or "").split()).strip()
