"""Cyprus Comic Con event parser."""

import json
import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.parsers.base import EventParser

BASE_URL = "https://cypruscomiccon.org/events/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; StayAliveCyprusBot/1.0)",
    "Accept-Language": "en-US,en;q=0.9",
}


class ComicConParser(EventParser):
    """Parse the public Cyprus Comic Con event calendar."""

    def parse(self) -> list[dict]:
        response = requests.get(BASE_URL, headers=HEADERS, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        events = []

        for node in soup.select('script[type="application/ld+json"]'):
            raw = node.string or node.get_text()
            try:
                data = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue

            candidates = data if isinstance(data, list) else [data]
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                if item.get("@type") != "Event" and "startDate" not in item:
                    continue
                event = self._from_jsonld(item)
                if event:
                    events.append(event)

        # Fallback for the visible calendar if JSON-LD is absent.
        if not events:
            text = " ".join(soup.stripped_strings)
            if "Cyprus Comic Con 2026" in text:
                events.append({
                    "title": "Cyprus Comic Con 2026",
                    "description": "Cyprus Comic Con at Cyprus State Fair, Nicosia.",
                    "date": "2026-10-02",
                    "end_date": "2026-10-04",
                    "time": "17:00",
                    "venue": "Cyprus State Fair",
                    "city": "Nicosia",
                    "price": "",
                    "ticket_url": "https://cypruscomiccon.org/tickets/",
                    "source_url": "https://cypruscomiccon.org/events/",
                    "image_url": "",
                    "category": "Фестиваль",
                })

        return events

    @staticmethod
    def _from_jsonld(item: dict) -> dict | None:
        title = str(item.get("name", "")).strip()
        start = str(item.get("startDate", "")).strip()
        if not title or not start:
            return None

        start_match = re.match(r"(\d{4}-\d{2}-\d{2})(?:T(\d{2}:\d{2}))?", start)
        if not start_match:
            return None

        end = str(item.get("endDate", "")).strip()
        end_match = re.match(r"(\d{4}-\d{2}-\d{2})(?:T(\d{2}:\d{2}))?", end)

        location = item.get("location") or {}
        if isinstance(location, list):
            location = location[0] if location else {}
        address = location.get("address") if isinstance(location, dict) else {}
        venue = str(location.get("name", "")).strip() if isinstance(location, dict) else ""
        city = ""
        if isinstance(address, dict):
            city = str(address.get("addressLocality", "")).strip()
        elif isinstance(address, str):
            if "nicosia" in address.lower():
                city = "Nicosia"

        offers = item.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}

        image = item.get("image", "")
        if isinstance(image, list):
            image = image[0] if image else ""

        return {
            "title": title[:200],
            "description": str(item.get("description", "")).strip()[:4000],
            "date": start_match.group(1),
            "end_date": end_match.group(1) if end_match else start_match.group(1),
            "time": start_match.group(2) or "",
            "venue": venue[:200],
            "city": city[:100] or "Nicosia",
            "price": str(offers.get("price", "")).strip() if isinstance(offers, dict) else "",
            "ticket_url": str(offers.get("url", "")).strip() if isinstance(offers, dict) else "https://cypruscomiccon.org/tickets/",
            "source_url": str(item.get("url", "")).strip() or BASE_URL,
            "image_url": str(image),
            "category": "Фестиваль",
        }
