"""Parser for public Telegram channel previews (t.me/s/...)."""

import re
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from app.parsers.base import EventParser

HEADERS = {"User-Agent": "StayAliveCyprusBot/1.0"}
MONTHS_RU = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}
MONTHS_EN = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


class TelegramParser(EventParser):
    def __init__(self, url: str):
        self.url = url
        parsed = urlparse(url)
        self.channel = parsed.path.strip("/").split("/")[-1]

    def parse(self) -> list[dict]:
        if not self.channel or self.channel.startswith("+"):
            return []
        preview_url = f"https://t.me/s/{self.channel}"
        response = requests.get(preview_url, timeout=20, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        events = []
        for message in soup.select(".tgme_widget_message"):
            body = message.select_one(".tgme_widget_message_text")
            if not body:
                continue
            text = " ".join(body.stripped_strings)
            parsed = _extract_event(text)
            if not parsed:
                continue
            title, date_value, time_value = parsed
            link = message.select_one(".tgme_widget_message_date")
            source_url = link.get("href", self.url) if link else self.url
            events.append({
                "title": title[:200],
                "description": text[:2000],
                "date": date_value,
                "end_date": date_value,
                "time": time_value,
                "venue": "",
                "city": _extract_city(text),
                "price": _extract_price(text),
                "ticket_url": source_url,
                "source_url": source_url,
                "image_url": "",
                "category": "Музыка",
            })
        return events


def _extract_event(text: str):
    now = datetime.now()
    match = re.search(r"\b(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?\b", text)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        year = int(match.group(3) or now.year)
        if year < 100:
            year += 2000
        if 1 <= month <= 12 and 1 <= day <= 31:
            date_value = f"{year:04d}-{month:02d}-{day:02d}"
        else:
            return None
    else:
        match = re.search(r"\b(\d{1,2})\s+([А-Яа-я]+|[A-Za-z]+)(?:\s+(\d{4}))?", text)
        if not match:
            return None
        month = MONTHS_RU.get(match.group(2).lower()) or MONTHS_EN.get(match.group(2).lower())
        if not month:
            return None
        year = int(match.group(3) or now.year)
        date_value = f"{year:04d}-{month:02d}-{int(match.group(1)):02d}"
    time_match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
    time_value = f"{time_match.group(1)}:{time_match.group(2)}" if time_match else ""
    title = re.split(r"\b(?:\d{1,2}[./-]\d{1,2}|\d{1,2}\s+[А-Яа-я]+|\d{1,2}\s+[A-Za-z]+)\b", text, maxsplit=1)[0].strip(" —:-")
    if len(title) < 4:
        title = text[:120]
    return title, date_value, time_value


def _extract_city(text: str) -> str:
    for city in ("Limassol", "Nicosia", "Larnaca", "Paphos", "Protaras", "Ayia Napa"):
        if city.lower() in text.lower():
            return city
    return ""


def _extract_price(text: str) -> str:
    match = re.search(r"(?:€|EUR)\s*\d+(?:[.,]\d+)?", text, re.I)
    return match.group(0) if match else ""
