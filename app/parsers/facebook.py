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



class FacebookDiscoveryParser(FacebookParser):
    """Discover public Facebook event URLs through search-engine indexing.

    This is intentionally a discovery layer, not a scrape of Facebook's
    personalized /events feed. Search engines may expose public event pages
    even when Facebook itself serves a login/challenge page to automation.
    """

    SEARCH_URL = "https://www.google.com/search"

    def __init__(self, query: str = "site:facebook.com/events Cyprus event"):
        super().__init__("https://www.facebook.com/events")
        self.query = query

    def parse(self) -> list[dict]:
        try:
            response = requests.get(
                self.SEARCH_URL,
                params={"q": self.query, "num": 20, "hl": "en"},
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
        except requests.RequestException as exc:
            logger.warning("Facebook discovery search failed: %s", exc)
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        candidates = []

        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            match = re.search(r"https?://(?:www\.)?facebook\.com/events/[^&?#\s]+", href)
            if not match:
                continue
            event_url = match.group(0).rstrip("/")
            title = " ".join(link.stripped_strings).strip()
            if not title:
                continue
            candidates.append((event_url, title))

        # Google can expose the same event several times.
        unique = []
        seen = set()
        for url, title in candidates:
            if url in seen:
                continue
            seen.add(url)
            unique.append((url, title))

        events = []
        for event_url, search_title in unique[:20]:
            event = self._parse_discovered_event(event_url, search_title)
            if event:
                events.append(event)

        logger.info("Facebook discovery: %s candidate URLs, %s parsed events", len(unique), len(events))
        return events

    def _parse_discovered_event(self, event_url: str, search_title: str) -> dict | None:
        # First try the public event page itself.
        try:
            html = self._get(event_url)
            parsed = self._parse_html(html, event_url)
            if parsed:
                return parsed[0]
        except requests.RequestException:
            pass

        # Search result titles often contain the event name, but without a
        # date we cannot safely turn them into an event.
        date = self._extract_date(search_title)
        if not date:
            return None

        return {
            "title": self._clean_discovery_title(search_title),
            "description": search_title[:1500],
            "date": date,
            "end_date": "",
            "time": self._extract_time(search_title),
            "venue": "",
            "city": self._infer_city(search_title),
            "price": "",
            "ticket_url": "",
            "source_url": event_url,
            "image_url": "",
            "category": self._infer_category(search_title),
        }

    @staticmethod
    def _clean_discovery_title(title: str) -> str:
        title = re.sub(r"\s*\|\s*Facebook\s*$", "", title, flags=re.I)
        title = re.sub(r"\s*-\s*Facebook\s*$", "", title, flags=re.I)
        return title.strip()[:300]

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
        urls = [
            self.url + "/events",
            self.url + "/upcoming_hosted_events",
            self.url,
        ]
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

        # Facebook may expose event payloads as JSON in script tags even when
        # the visible HTML is sparse.
        events.extend(self._parse_embedded_json(soup, page_url))

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

    def _parse_embedded_json(self, soup: BeautifulSoup, page_url: str) -> list[dict]:
        """Best-effort extraction from Facebook's embedded JSON payloads."""
        events = []
        for script in soup.find_all("script"):
            raw = script.string or script.get_text()
            if not raw or "event" not in raw.lower():
                continue

            for match in re.finditer(
                r'"(?:name|title)"\\s*:\\s*"([^"\\\\]{3,300})"[^{}]{0,2500}?'
                r'"(?:start_time|startTime|start_date|startDate)"\\s*:\\s*"?([^",}]{6,40})',
                raw,
                re.I,
            ):
                title = match.group(1)
                start = match.group(2).strip()
                date, time = self._parse_timestamp(start)
                if not date:
                    continue
                context = raw[max(0, match.start()-500):match.end()+500]
                events.append({
                    "title": title.strip(),
                    "description": "",
                    "date": date,
                    "end_date": "",
                    "time": time,
                    "venue": "",
                    "city": self._infer_city(title + " " + context),
                    "price": "",
                    "ticket_url": "",
                    "source_url": page_url,
                    "image_url": "",
                    "category": self._infer_category(title),
                })
        return events

    @staticmethod
    def _parse_timestamp(value: str) -> tuple[str, str]:
        value = value.strip().strip('"')
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.date().isoformat(), dt.strftime("%H:%M")
        except ValueError:
            pass
        match = re.search(r"(\\d{4})[-/](\\d{1,2})[-/](\\d{1,2})", value)
        if match:
            return (
                f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}",
                "",
            )
        return "", ""

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
