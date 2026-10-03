"""Best-effort parser for public Instagram profiles.

Instagram does not provide a stable unauthenticated profile API. This adapter
therefore treats Instagram as a source of public post captions and metadata.
It deliberately stays generic: any profile can be added as a source.
"""

import html
import json
import logging
import re
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from app.date_utils import parse_event_dates
from app.parsers.base import EventParser

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; StayAliveCyprusBot/1.0)",
    "Accept-Language": "en-US,en;q=0.9",
}

EVENT_WORDS = re.compile(
    r"\b(event|events|party|concert|live|dj|djs|wine|tasting|dinner|"
    r"market|workshop|exhibition|opening|festival|night|brunch|popup|"
    r"дегустац|концерт|вечерин|фестивал|маркет|выстав|ужин|мастер-класс)\b",
    re.I,
)
TIME_RE = re.compile(r"\b(?:at\s*)?(?:[01]?\d|2[0-3])(?::[0-5]\d)?\s*(?:am|pm)?\b", re.I)


class InstagramParser(EventParser):
    def __init__(self, url: str):
        self.url = _canonical_profile_url(url)
        self.handle = urlparse(self.url).path.strip("/").split("/")[0]

    def parse(self) -> list[dict]:
        try:
            response = requests.get(
                self.url,
                timeout=20,
                headers=HEADERS,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Instagram @%s fetch failed: %s", self.handle, exc)
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        texts = []

        description = _meta(soup, "description")
        if description:
            texts.append(description)

        # Instagram has changed its embedded payload format several times.
        # Collect caption-like strings without depending on one private schema.
        for script in soup.find_all("script"):
            raw = script.string or script.get_text()
            if not raw or "caption" not in raw.lower():
                continue
            texts.extend(_extract_caption_strings(raw))

        # Also inspect visible text as a last-resort fallback.
        visible = soup.get_text(" ", strip=True)
        if visible:
            texts.append(visible[:30000])

        events = []
        seen = set()
        for text in texts:
            event = self._caption_to_event(text)
            if not event:
                continue
            key = (event["title"].lower(), event["date"], event["time"])
            if key in seen:
                continue
            seen.add(key)
            events.append(event)

        print(
            f"Instagram @{self.handle}: {len(events)} events parsed",
            flush=True,
        )
        return events

    def _caption_to_event(self, text: str) -> dict | None:
        text = html.unescape(re.sub(r"\s+", " ", text)).strip()
        if not text or len(text) < 20:
            return None

        dates = parse_event_dates(text, default_year=datetime.now().year)
        if not dates:
            return None
        if not EVENT_WORDS.search(text) and not TIME_RE.search(text):
            return None

        # Use the first compact sentence/line as a conservative title.
        chunks = re.split(r"\s*[|•·]\s*|(?<=[.!?])\s+", text)
        title = next(
            (
                c.strip(" -–—#")
                for c in chunks
                if 5 <= len(c.strip()) <= 160
                and not parse_event_dates(c, default_year=datetime.now().year)
            ),
            "",
        )
        if not title:
            title = f"Instagram event — @{self.handle}"

        time_match = TIME_RE.search(text)
        time_value = time_match.group(0).strip() if time_match else ""

        city = _find_city(text)
        price = _find_price(text)

        return {
            "title": title[:200],
            "description": text[:4000],
            "date": dates[0],
            "end_date": dates[1],
            "time": time_value,
            "venue": "",
            "city": city,
            "price": price,
            "ticket_url": self.url,
            "source_url": self.url,
            "image_url": "",
            "category": "События",
        }


def _canonical_profile_url(url: str) -> str:
    parsed = urlparse(url)
    handle = parsed.path.strip("/").split("/")[0]
    return f"https://www.instagram.com/{handle}/"


def _meta(soup: BeautifulSoup, prop: str) -> str:
    node = soup.find("meta", attrs={"name": prop}) or soup.find(
        "meta", attrs={"property": f"og:{prop}"}
    )
    return str(node.get("content") or "").strip() if node else ""


def _extract_caption_strings(raw: str) -> list[str]:
    values = []
    patterns = (
        r'"text"\s*:\s*"((?:\\.|[^"\\]){10,4000})"',
        r'"caption"\s*:\s*"((?:\\.|[^"\\]){10,4000})"',
    )
    for pattern in patterns:
        for match in re.findall(pattern, raw):
            try:
                values.append(json.loads('"' + match + '"'))
            except json.JSONDecodeError:
                values.append(match)
    return values[:200]


def _find_city(text: str) -> str:
    cities = (
        "Limassol", "Nicosia", "Larnaca", "Paphos", "Ayia Napa",
        "Protaras", "Paralimni", "Famagusta", "Polis", "Latchi", "Troodos",
        "Лимассол", "Никосия", "Ларнака", "Пафос",
    )
    for city in cities:
        if re.search(rf"\b{re.escape(city)}\b", text, re.I):
            return city
    return ""


def _find_price(text: str) -> str:
    match = re.search(r"(?:€|EUR)\s*\d+(?:[.,]\d+)?|\b\d+(?:[.,]\d+)?\s*€", text, re.I)
    return match.group(0).replace("EUR", "€").strip() if match else ""
