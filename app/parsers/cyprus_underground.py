"""Parser for Cyprus Underground event listings.

Cyprus Underground is a server-rendered event directory. Prefer the site's
semantic/JSON-LD event data via the generic WebsiteParser, then fall back to
the listing text parser for layouts that do not expose structured data.
"""

import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.date_utils import parse_event_dates
from app.parsers.base import EventParser
from app.parsers.website import WebsiteParser

HEADERS = {"User-Agent": "StayAliveCyprusBot/1.0"}

DATE_RE = re.compile(
    r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)(?:\s+(20\d{2}))?$",
    re.I,
)
TIME_RE = re.compile(r"^(\d{1,2}:\d{2})$")
CITY_RE = re.compile(r"\b(Limassol|Nicosia|Larnaca|Paphos|Famagusta)\b", re.I)


class CyprusUndergroundParser(EventParser):
    def __init__(self, url: str):
        self.url = url.rstrip("/") + "/"

    def parse(self) -> list[dict]:
        # First use the generic parser: it already handles JSON-LD Event data
        # and structured card markup, including absolute event/ticket URLs.
        try:
            structured = WebsiteParser(self.url).parse()
        except Exception as exc:
            print(f"CYPRUS_UNDERGROUND_STRUCTURED_ERROR | {type(exc).__name__}: {exc}")
            structured = []

        if structured:
            for event in structured:
                event["category"] = "Nightlife"
                event["source_url"] = self.url
                if not event.get("ticket_url"):
                    event["ticket_url"] = event.get("source_url", self.url)
            print(f"CYPRUS_UNDERGROUND_STRUCTURED | {len(structured)} events")
            return _unique(structured)

        # Fallback for pages where the event cards are only exposed as text.
        return self._text_cards()

    def _text_cards(self) -> list[dict]:
        response = requests.get(self.url, timeout=20, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # Keep a small diagnostic in Actions logs so a future site markup
        # change is immediately visible instead of silently returning zero.
        event_links = [
            a.get("href", "")
            for a in soup.find_all("a", href=True)
            if "/event/" in a.get("href", "")
        ]
        print(
            "CYPRUS_UNDERGROUND_HTML | "
            f"status={response.status_code} bytes={len(response.text)} "
            f"event_links={len(event_links)}"
        )

        lines = [
            re.sub(r"\s+", " ", x).strip().lstrip("# ").strip()
            for x in soup.get_text("\n").splitlines()
            if x.strip()
        ]

        events: list[dict] = []
        date = None
        card: list[str] = []

        def flush() -> None:
            nonlocal card
            if not date or not card:
                card = []
                return

            ti = next((i for i, x in enumerate(card) if TIME_RE.match(x)), None)
            if ti is None or not card[0]:
                card = []
                return

            title = card[0]
            venue = card[ti + 1] if ti + 1 < len(card) else ""
            city_match = CITY_RE.search(venue)
            city = city_match.group(1) if city_match else ""
            if city:
                venue = CITY_RE.sub("", venue).strip()

            price_match = re.search(r"€\s?\d+(?:[.,]\d+)?", title)
            clean_title = re.sub(r"\s*-?\s*€\s?\d+(?:[.,]\d+)?", "", title).strip()

            # If the title appears in a real event link, use that detail URL.
            ticket_url = self.url
            for href in event_links:
                slug = href.rstrip("/").rsplit("/", 1)[-1]
                if slug and re.sub(r"[^a-z0-9]+", "-", clean_title.lower()).strip("-")[:30] in slug.lower():
                    ticket_url = urljoin(self.url, href)
                    break

            events.append(
                {
                    "title": clean_title[:200],
                    "description": " · ".join(card[1:ti])[:4000],
                    "date": date,
                    "end_date": date,
                    "time": card[ti],
                    "venue": venue[:200],
                    "city": city[:100],
                    "price": price_match.group(0).replace(" ", "") if price_match else "",
                    "ticket_url": ticket_url,
                    "source_url": self.url,
                    "image_url": "",
                    "category": "Nightlife",
                }
            )
            card = []

        for line in lines:
            match = DATE_RE.match(line)
            if match:
                flush()
                day, month, year = match.groups()
                year = int(year) if year else datetime.now().year
                parsed = parse_event_dates(f"{day} {month} {year}", default_year=year)
                date = parsed[0] if parsed else None
                card = []
                continue

            if not date or line.casefold() in {"search", "genre:", "i"}:
                continue

            card.append(line)
            if TIME_RE.match(line):
                flush()

        flush()
        print(f"CYPRUS_UNDERGROUND_TEXT | {len(events)} events")
        return _unique(events)


def _unique(events: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for event in events:
        key = (
            event.get("title", "").casefold(),
            event.get("date", ""),
            event.get("time", ""),
            event.get("venue", "").casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(event)
    return result
