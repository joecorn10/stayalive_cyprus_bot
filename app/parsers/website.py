"""Generic JSON-LD event parser for public websites."""

import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.date_utils import parse_event_dates
from app.parsers.base import EventParser

HEADERS = {"User-Agent": "StayAliveCyprusBot/1.0"}

class WebsiteParser(EventParser):
    def __init__(self, url: str):
        self.url = url

    def parse(self) -> list[dict]:
        response = requests.get(self.url, timeout=20, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        events = []
        seen = set()

        for node in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(node.string or node.get_text())
            except (TypeError, json.JSONDecodeError):
                continue
            candidates = data if isinstance(data, list) else data.get("@graph", []) if isinstance(data, dict) else []
            if isinstance(data, dict) and data.get("@type") == "Event":
                candidates = [data] + list(candidates)
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                types = item.get("@type", [])
                if "Event" not in (types if isinstance(types, list) else [types]):
                    continue
                event = self._event(item)
                if event:
                    key = (event["title"].lower(), event["date"], event["end_date"])
                    if key not in seen:
                        seen.add(key)
                        events.append(event)
        return events

    def _event(self, item: dict) -> dict | None:
        title = str(item.get("name") or "").strip()
        start_raw = str(item.get("startDate") or "").strip()
        end_raw = str(item.get("endDate") or "").strip()
        dates = parse_event_dates(start_raw)
        if not dates:
            return None
        end_dates = parse_event_dates(end_raw) if end_raw else dates
        location = item.get("location") or {}
        if isinstance(location, list):
            location = location[0] if location else {}
        venue = str(location.get("name") or "").strip() if isinstance(location, dict) else ""
        address = location.get("address") if isinstance(location, dict) else {}
        city = str(address.get("addressLocality") or "").strip() if isinstance(address, dict) else ""
        offers = item.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        image = item.get("image") or ""
        if isinstance(image, list):
            image = image[0] if image else ""
        return {
            "title": title[:200],
            "description": re.sub(r"\s+", " ", str(item.get("description") or "")).strip()[:4000],
            "date": dates[0],
            "end_date": _end_date(end_dates, dates),
            "time": _time(start_raw),
            "venue": venue[:200],
            "city": city[:100],
            "price": str(offers.get("price") or "").strip() if isinstance(offers, dict) else "",
            "ticket_url": str(offers.get("url") or "").strip() if isinstance(offers, dict) else "",
            "source_url": urljoin(self.url, str(item.get("url") or self.url)),
            "image_url": str(image),
            "category": "События",
        }

def _time(value: str) -> str:
    m = re.search(r"T(\d{2}:\d{2})", value)
    return m.group(1) if m else ""
\n\ndef _end_date(end_dates, start_dates):\n    if end_dates:\n        return end_dates[1] if len(end_dates) > 1 else end_dates[0]\n    return start_dates[1] if len(start_dates) > 1 else start_dates[0]\n