"""ETKO Cyprus event parser."""

import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.parsers.base import EventParser

ETKO_URL = "https://etkocyprus.com/events"
HEADERS = {"User-Agent": "StayAliveCyprusBot/1.0"}

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


class EtkoParser(EventParser):
    def __init__(self, url: str = ETKO_URL):
        self.url = url

    def parse(self) -> list[dict]:
        response = requests.get(self.url, timeout=20, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        events = []
        seen_urls = set()

        for link in soup.find_all("a", href=True):
            href = urljoin(self.url, link["href"])
            if not href.startswith("https://etkocyprus.com/events/"):
                continue
            if href.rstrip("/") == self.url.rstrip("/") or href in seen_urls:
                continue

            title = " ".join(link.get_text(" ", strip=True).split())
            if not title:
                continue

            card = link
            for _ in range(4):
                if card.parent:
                    card = card.parent
            card_text = " ".join(card.get_text(" ", strip=True).split())

            date_value, time_value = _extract_datetime(card_text)
            if not date_value:
                continue

            seen_urls.add(href)
            events.append({
                "title": title[:200],
                "description": card_text[:2000],
                "date": date_value,
                "time": time_value,
                "venue": "ETKO",
                "city": "Limassol",
                "price": "",
                "ticket_url": href,
                "source_url": href,
                "image_url": "",
                "category": "Музыка",
            })

        return events


def _extract_datetime(text: str) -> tuple[str, str]:
    match = re.search(
        r"\b(\d{1,2})\.(\d{1,2})\s*(?:-|–|—)\s*(\d{1,2})\.(\d{1,2})\b",
        text,
    )
    if match:
        year = datetime.now().year
        day, month = int(match.group(1)), int(match.group(2))
        return f"{year:04d}-{month:02d}-{day:02d}", _extract_time(text)

    match = re.search(
        r"\b([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?"
        r"(?:\s*(?:-|–|—)\s*[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?)?"
        r"\s*(\d{4})?\b",
        text,
        re.IGNORECASE,
    )
    if match:
        month = MONTHS.get(match.group(1).lower())
        if month:
            year = int(match.group(3)) if match.group(3) else datetime.now().year
            day = int(match.group(2))
            return f"{year:04d}-{month:02d}-{day:02d}", _extract_time(text)

    return "", ""


def _extract_time(text: str) -> str:
    match = re.search(r"\b([01]?\d|2[0-3]):[0-5]\d\b", text)
    return match.group(0) if match else ""
