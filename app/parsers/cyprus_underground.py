"""Parser for Cyprus Underground's electronic-music event catalogue."""

import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.date_utils import parse_event_dates
from app.parsers.base import EventParser

HEADERS = {"User-Agent": "StayAliveCyprusBot/1.0"}
EVENT_HREF_RE = re.compile(r"/event/[^?#]+", re.I)
DATE_RE = re.compile(r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+(\d{1,2})(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|October|November|December)(?:\s+(20\d{2}))?\b", re.I)
TIME_RE = re.compile(r"\b(\d{1,2}:\d{2})\b")
PRICE_RE = re.compile(r"€\s?\d+(?:[.,]\d+)?", re.I)
CITIES = ("Limassol", "Nicosia", "Larnaca", "Paphos", "Famagusta")


class CyprusUndergroundParser(EventParser):
    def __init__(self, url: str):
        self.url = url.rstrip("/") + "/"

    def parse(self) -> list[dict]:
        response = requests.get(self.url, timeout=20, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        events, seen = [], set()

        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "")
            if not EVENT_HREF_RE.search(href):
                continue
            title = re.sub(r"\s+", " ", link.get_text(" ", strip=True)).strip()
            if not title or title.casefold() in {"book now", "more info"}:
                continue

            card = self._event_card(link)
            if not card:
                continue
            lines = self._lines(card)
            date = self._find_date(link)
            if not lines or not date:
                continue

            time_index = next((i for i, line in enumerate(lines) if TIME_RE.search(line)), None)
            if time_index is None:
                continue
            time = TIME_RE.search(lines[time_index]).group(1)
            venue = self._find_venue(lines, time_index)
            city = self._find_city(venue, lines)
            if city:
                venue = re.sub(re.escape(city) + r"\s*$", "", venue, flags=re.I).strip()

            price_match = PRICE_RE.search(title)
            price = price_match.group(0).replace(" ", "") if price_match else ""
            clean_title = PRICE_RE.sub("", title).strip(" -–—")
            image_url = ""
            image = card.find("img", src=True)
            if image:
                image_url = urljoin(self.url, str(image.get("src") or ""))

            key = (clean_title.casefold(), date, time, venue.casefold())
            if key in seen:
                continue
            seen.add(key)

            before_time = lines[:time_index]
            description = " · ".join(before_time[1:]) if len(before_time) > 2 else ""
            events.append({
                "title": clean_title[:200],
                "description": description[:4000],
                "date": date,
                "end_date": date,
                "time": time,
                "venue": venue[:200],
                "city": city[:100],
                "price": price,
                "ticket_url": urljoin(self.url, href),
                "source_url": self.url,
                "image_url": image_url,
                "category": "Nightlife",
            })
        return events

    @staticmethod
    def _event_card(link):
        node = link
        for _ in range(8):
            node = node.parent
            if not node:
                return None
            if TIME_RE.search(re.sub(r"\s+", " ", node.get_text(" ", strip=True))):
                return node
        return None

    @staticmethod
    def _lines(node):
        return [re.sub(r"\s+", " ", line).strip() for line in node.get_text("\n", strip=True).splitlines() if line.strip()]

    def _find_date(self, link):
        for node in link.find_all_previous(string=True):
            match = DATE_RE.search(re.sub(r"\s+", " ", str(node)).strip())
            if not match:
                continue
            day, month, year = match.groups()
            default_year = int(year) if year else datetime.now().year
            parsed = parse_event_dates(f"{day} {month} {default_year}", default_year=default_year)
            if parsed:
                return parsed[0]
        return ""

    @staticmethod
    def _find_venue(lines, time_index):
        for line in lines[time_index + 1:]:
            if line.casefold() in {"book now", "pay on door"} or DATE_RE.search(line):
                continue
            if len(line) <= 180 and not PRICE_RE.fullmatch(line):
                return line
        return ""

    @staticmethod
    def _find_city(venue, lines):
        for city in CITIES:
            if re.search(re.escape(city) + r"$", venue, re.I):
                return city
        for line in lines:
            for city in CITIES:
                if re.search(r"\b" + re.escape(city) + r"\b", line, re.I):
                    return city
        return ""
