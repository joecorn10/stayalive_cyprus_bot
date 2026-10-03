"""Public Facebook page event parser.

Facebook's official Events API is access-restricted, so this parser deliberately
uses only publicly served page HTML. It is best-effort and fails softly when
Facebook serves a login/challenge page instead of event data.
"""

import json
import logging
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.parsers.base import EventParser

logger = logging.getLogger(__name__)

TIMEZONE = "Asia/Nicosia"

MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


class FacebookParser(EventParser):
    """Parse events exposed on a public Facebook Page."""

    def __init__(self, url: str):
        self.url = self._page_url(url)

    @staticmethod
    def _page_url(url: str) -> str:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        if path.lower().endswith("/events"):
            path = path[:-7].rstrip("/")
        return f"https://www.facebook.com{path or '/'}"

    def _get(self, url: str) -> str:
        response = requests.get(
            url,
            timeout=20,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        response.raise_for_status()
        return response.text

    def parse(self) -> list[dict]:
        urls = [self.url + "/events", self.url]
        seen = set()
        events = []

        for url in urls:
            try:
                html = self._get(url)
            except requests.RequestException as exc:
                logger.warning("Facebook fetch failed for %s: %s", url, exc)
                continue

            page_events = self._parse_html(html, url)
            for event in page_events:
                key = (
                    event.get("source_url", ""),
                    event.get("title", "").strip().lower(),
                    event.get("date", ""),
                )
                if key not in seen and event.get("title") and event.get("date"):
                    seen.add(key)
                    events.append(event)

        return events

    def _parse_html(self, html: str, page_url: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        events = []

        # First use schema.org Event objects when Facebook exposes them.
        for node in soup.find_all("script", type="application/ld+json"):
            raw = node.string or node.get_text()
            try:
                data = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue

            candidates = data if isinstance(data, list) else [data]
            for item in candidates:
                if isinstance(item, dict) and item.get("@type") == "Event":
                    event = self._from_jsonld(item, page_url)
                    if event:
                        events.append(event)

        # Fallback: inspect event links and their nearby text.
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if "/events/" not in href:
                continue

            title = " ".join(link.stripped_strings).strip()
            if not title or len(title) < 3:
                continue

            absolute = urljoin(page_url, href)
            block = link.parent.get_text(" ", strip=True) if link.parent else title
            date = self._extract_date(block)
            if not date:
                continue

            events.append({
                "title": title[:300],
                "description": block[:1500],
                "date": date,
                "end_date": "",
                "time": self._extract_time(block),
                "venue": "",
                "city": self._infer_city(block),
                "price": "",
                "ticket_url": "",
                "source_url": absolute,
                "image_url": "",
                "category": self._infer_category(block),
            })

        return events

    def _from_jsonld(self, item: dict, page_url: str) -> dict | None:
        start = item.get("startDate")
        if not start:
            return None

        try:
            dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        except ValueError:
            return None

        end_date = ""
        if item.get("endDate"):
            try:
                end_dt = datetime.fromisoformat(str(item["endDate"]).replace("Z", "+00:00"))
                end_date = end_dt.date().isoformat()
            except ValueError:
                pass

        location = item.get("location") or {}
        if isinstance(location, list):
            location = location[0] if location else {}
        address = location.get("address") if isinstance(location, dict) else {}
        if isinstance(address, str):
            venue = str(location.get("name", "")) if isinstance(location, dict) else ""
            city = self._infer_city(address)
        else:
            venue = str(location.get("name", "")) if isinstance(location, dict) else ""
            city = str(address.get("addressLocality", "")) if isinstance(address, dict) else ""

        offers = item.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}

        return {
            "title": str(item.get("name", "")).strip()[:300],
            "description": str(item.get("description", "")).strip()[:3000],
            "date": dt.date().isoformat(),
            "end_date": end_date,
            "time": dt.strftime("%H:%M"),
            "venue": venue[:200],
            "city": city[:100],
            "price": str(offers.get("price", "")).strip() if isinstance(offers, dict) else "",
            "ticket_url": str(offers.get("url", "")).strip() if isinstance(offers, dict) else "",
            "source_url": urljoin(page_url, str(item.get("url", "")).strip()),
            "image_url": self._image_url(item.get("image")),
            "category": self._infer_category(
                f"{item.get('name', '')} {item.get('description', '')}"
            ),
        }

    @staticmethod
    def _image_url(value) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list) and value:
            return str(value[0])
        if isinstance(value, dict):
            return str(value.get("url", ""))
        return ""

    @staticmethod
    def _extract_date(text: str) -> str:
        now = datetime.now()
        normalized = re.sub(r"\s+", " ", text)
        match = re.search(
            r"\b(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\s+"
            r"(\w+)\s+(\d{1,2})(?:,\s*(\d{4}))?",
            normalized,
            re.I,
        )
        if not match:
            match = re.search(
                r"\b(\w+)\s+(\d{1,2})(?:,\s*(\d{4}))?\b",
                normalized,
                re.I,
            )
        if not match:
            return ""

        month = MONTHS.get(match.group(1).lower())
        if not month:
            return ""
        year = int(match.group(3) or now.year)
        try:
            return datetime(year, month, int(match.group(2))).date().isoformat()
        except ValueError:
            return ""

    @staticmethod
    def _extract_time(text: str) -> str:
        match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(AM|PM)\b", text, re.I)
        if not match:
            return ""
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        if match.group(3).lower() == "pm" and hour != 12:
            hour += 12
        if match.group(3).lower() == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"

    @staticmethod
    def _infer_city(text: str) -> str:
        lowered = text.lower()
        for city in (
            "Limassol", "Nicosia", "Larnaca", "Paphos", "Ayia Napa",
            "Paralimni", "Protaras", "Polis", "Troodos",
        ):
            if city.lower() in lowered:
                return city
        return ""

    @staticmethod
    def _infer_category(text: str) -> str:
        lowered = text.lower()
        groups = {
            "Музыка": ("concert", "music", "dj", "live", "techno", "house", "jazz"),
            "Театр": ("theatre", "theater", "театр"),
            "Ночная жизнь": ("party", "club", "rave", "nightlife"),
            "Искусство": ("art", "gallery", "exhibition", "museum"),
            "Фестиваль": ("festival", "фестиваль"),
            "Еда и напитки": ("food", "wine", "beer", "gastronomy"),
        }
        for category, keywords in groups.items():
            if any(keyword in lowered for keyword in keywords):
                return category
        return "События"
