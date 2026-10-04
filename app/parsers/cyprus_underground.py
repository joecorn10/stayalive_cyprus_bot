"""Parser for Cyprus Underground listing cards."""
import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from app.date_utils import parse_event_dates
from app.parsers.base import EventParser

DATE_RE = re.compile(r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday) (\d{1,2})(?:st|nd|rd|th)? (January|February|March|April|May|June|July|August|September|October|November|December)(?: (20\d{2}))?$", re.I)
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
CITY_RE = re.compile(r"\b(Limassol|Nicosia|Larnaca|Paphos|Famagusta)\b", re.I)

class CyprusUndergroundParser(EventParser):
    def __init__(self, url: str):
        self.url = url.rstrip("/") + "/"

    def parse(self) -> list[dict]:
        r = requests.get(self.url, timeout=20, headers={"User-Agent": "StayAliveCyprusBot/1.0"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        lines = [re.sub(r"\s+", " ", x).strip() for x in soup.get_text("\n").splitlines() if x.strip()]
        events, date, card = [], None, []

        def flush():
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
            city_m = CITY_RE.search(venue)
            city = city_m.group(1) if city_m else ""
            if city:
                venue = CITY_RE.sub("", venue).strip()
            price_m = re.search(r"€\s?\d+(?:[.,]\d+)?", title)
            event = {
                "title": re.sub(r"\s*-?\s*€\s?\d+(?:[.,]\d+)?", "", title).strip()[:200],
                "description": " · ".join(card[1:ti])[:4000],
                "date": date, "end_date": date, "time": card[ti],
                "venue": venue[:200], "city": city[:100],
                "price": price_m.group(0).replace(" ", "") if price_m else "",
                "ticket_url": self.url, "source_url": self.url,
                "image_url": "", "category": "Nightlife",
            }
            if not any((e["title"], e["date"], e["time"], e["venue"]) == (event["title"], event["date"], event["time"], event["venue"]) for e in events):
                events.append(event)
            card = []

        for line in lines:
            m = DATE_RE.match(line)
            if m:
                flush()
                day, month, year = m.groups()
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
        return events
