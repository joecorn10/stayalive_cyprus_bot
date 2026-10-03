"""Cyproplan event parser."""

import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.parsers.base import EventParser

URL = "https://cyproplan.com/"
HEADERS = {"User-Agent": "StayAliveCyprusBot/1.0"}
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


class CyproplanParser(EventParser):
    def __init__(self, url: str = URL):
        self.url = url

    def parse(self) -> list[dict]:
        response = requests.get(self.url, timeout=25, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        events = []
        seen = set()

        for link in soup.find_all("a", href=True):
            href = urljoin(self.url, link["href"])
            if "cyproplan.com" not in href or href.rstrip("/") == self.url.rstrip("/"):
                continue
            text = " ".join(link.get_text(" ", strip=True).split())
            if len(text) < 4:
                continue
            if not any(token in href.lower() for token in ("/event", "/events/")):
                continue

            card = link
            for _ in range(5):
                if card.parent:
                    card = card.parent
            card_text = " ".join(card.get_text(" ", strip=True).split())
            parsed = _extract_datetime(card_text)
            if not parsed or href in seen:
                continue

            date_value, end_date, time_value = parsed
            seen.add(href)
            events.append({
                "title": text[:200],
                "description": card_text[:2000],
                "date": date_value,
                "end_date": end_date,
                "time": time_value,
                "venue": _extract_venue(card_text),
                "city": _extract_city(card_text),
                "price": _extract_price(card_text),
                "ticket_url": href,
                "source_url": href,
                "image_url": "",
                "category": _extract_category(card_text),
            })
        return events


def _extract_datetime(text: str):
    now = datetime.now()
    patterns = [
        r"\b([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(\d{4}))?",
        r"\b(\d{1,2})\s+([A-Za-z]+)(?:\s*,?\s*(\d{4}))?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        if pattern.startswith(r"\b([A"):
            month_name, day, year = match.group(1), int(match.group(2)), match.group(3)
        else:
            day, month_name, year = int(match.group(1)), match.group(2), match.group(3)
        month = MONTHS.get(month_name.lower())
        if not month:
            continue
        year = int(year) if year else now.year
        date_value = f"{year:04d}-{month:02d}-{day:02d}"
        time_match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
        time_value = f"{time_match.group(1)}:{time_match.group(2)}" if time_match else ""
        return date_value, date_value, time_value
    return None


def _extract_venue(text: str) -> str:
    lines = [x.strip(" .") for x in re.split(r"\s{2,}|\n", text) if x.strip()]
    return next((x for x in lines if "venue" in x.lower()), "")


def _extract_city(text: str) -> str:
    cities = ("Limassol", "Nicosia", "Larnaca", "Paphos", "Protaras", "Ayia Napa")
    for city in cities:
        if city.lower() in text.lower():
            return city
    return ""


def _extract_price(text: str) -> str:
    match = re.search(r"(?:€|EUR\s*)\s*\d+(?:[.,]\d+)?", text)
    return match.group(0) if match else ""


def _extract_category(text: str) -> str:
    mapping = {
        "music": "Музыка", "concert": "Музыка", "festival": "Фестиваль",
        "art": "Искусство", "theater": "Театр", "theatre": "Театр",
        "sport": "Спорт", "food": "Еда", "kids": "Для детей",
        "business": "Бизнес", "education": "Образование",
    }
    lower = text.lower()
    for key, value in mapping.items():
        if key in lower:
            return value
    return "События"
