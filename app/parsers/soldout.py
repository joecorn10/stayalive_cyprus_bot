"""SoldOut TicketBox calendar parser."""

import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.parsers.base import EventParser

URL = "https://www.soldoutticketbox.com/en/calendar"
HEADERS = {"User-Agent": "StayAliveCyprusBot/1.0"}


class SoldOutParser(EventParser):
    def __init__(self, url: str = URL):
        self.url = url

    def parse(self) -> list[dict]:
        response = requests.get(self.url, timeout=25, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        text = " ".join(soup.get_text(" ", strip=True).split())
        events = []
        # Calendar pages expose date/time + title + venue as text. Use nearby
        # anchors where available and keep parsing deliberately conservative.
        for link in soup.find_all("a", href=True):
            title = " ".join(link.get_text(" ", strip=True).split())
            href = urljoin(self.url, link["href"])
            if len(title) < 4 or "soldoutticketbox.com" not in href:
                continue
            parent = link
            for _ in range(4):
                if parent.parent:
                    parent = parent.parent
            block = " ".join(parent.get_text(" ", strip=True).split())
            parsed = _extract_date_time(block)
            if not parsed:
                continue
            date_value, end_date, time_value = parsed
            if any(e["source_url"] == href for e in events):
                continue
            events.append({
                "title": title[:200],
                "description": block[:2000],
                "date": date_value,
                "end_date": end_date,
                "time": time_value,
                "venue": _extract_venue(block),
                "city": _extract_city(block),
                "price": _extract_price(block),
                "ticket_url": href,
                "source_url": href,
                "image_url": "",
                "category": "События",
            })
        return events


def _extract_date_time(text: str):
    match = re.search(
        r"(\d{2}/\d{2}/\d{2,4})(?:\s*-\s*(\d{2}/\d{2}/\d{2,4}))?\s+([01]?\d|2[0-3]):([0-5]\d)",
        text,
    )
    if not match:
        return None
    def iso(value):
        parts = value.split("/")
        year = int(parts[2])
        if year < 100:
            year += 2000
        return f"{year:04d}-{int(parts[1]):02d}-{int(parts[0]):02d}"
    return iso(match.group(1)), iso(match.group(2) or match.group(1)), f"{match.group(3)}:{match.group(4)}"


def _extract_venue(text: str) -> str:
    parts = text.split("|")
    return parts[-1].strip()[:120] if len(parts) > 1 else ""


def _extract_city(text: str) -> str:
    for city in ("Limassol", "Nicosia", "Larnaca", "Paphos", "Protaras", "Ayia Napa"):
        if city.lower() in text.lower():
            return city
    return ""


def _extract_price(text: str) -> str:
    match = re.search(r"(?:From\s*)?€\s*\d+(?:[.,]\d+)?", text, re.I)
    return match.group(0) if match else ""
