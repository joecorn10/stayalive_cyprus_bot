"""SoldOut TicketBox event parser with Telegram fallback."""

import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.parsers.base import EventParser

HOME_URL = "https://www.soldoutticketbox.com/en/home"
TELEGRAM_URL = "https://t.me/s/SoldOutTicketsEvents"
HEADERS = {"User-Agent": "StayAliveCyprusBot/1.0"}

MONTHS_EN = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}
MONTHS_RU = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}
CITIES = (
    ("limassol", "Limassol"), ("nicosia", "Nicosia"),
    ("larnaca", "Larnaca"), ("paphos", "Paphos"),
    ("протарас", "Protaras"), ("айя-напа", "Ayia Napa"),
)


class SoldOutParser(EventParser):
    def __init__(self, url: str = HOME_URL):
        self.url = url

    def parse(self) -> list[dict]:
        try:
            response = requests.get(self.url, timeout=25, headers=HEADERS)
            response.raise_for_status()
            events = self._parse_website(response.text)
            if events:
                return events
        except requests.RequestException:
            pass

        # SoldOut's web property is protected from some server-side clients.
        # Their public Telegram channel mirrors the ticket catalogue, so use it
        # as a resilient fallback rather than dropping the whole source.
        return self._parse_telegram_fallback()

    def _parse_website(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        events = []
        seen = set()

        # Prefer semantic event links/cards when available.
        for link in soup.find_all("a", href=True):
            href = urljoin(self.url, link.get("href", ""))
            if "soldoutticketbox.com" not in href:
                continue

            title = _clean_title(link.get_text(" ", strip=True))
            if len(title) < 4 or title.casefold() in {"buy", "more", "login", "register"}:
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
            key = (title.casefold(), date_value, time_value)
            if key in seen:
                continue
            seen.add(key)

            events.append(_event(
                title, block, date_value, end_date, time_value,
                _extract_city(block), href, self.url,
            ))

        return events

    def _parse_telegram_fallback(self) -> list[dict]:
        response = requests.get(TELEGRAM_URL, timeout=20, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        events = []
        seen = set()

        for message in soup.select(".tgme_widget_message"):
            body = message.select_one(".tgme_widget_message_text")
            if not body:
                continue

            text = "\n".join(body.stripped_strings)
            parsed = _extract_telegram_event(text)
            if not parsed:
                continue

            title, date_value, end_date, time_value, venue, ticket_url = parsed
            key = (title.casefold(), date_value, end_date, venue.casefold())
            if key in seen:
                continue
            seen.add(key)

            post = message.select_one(".tgme_widget_message_date")
            post_url = post.get("href", TELEGRAM_URL) if post else TELEGRAM_URL
            events.append(_event(
                title[:200], text[:4000], date_value, end_date, time_value,
                venue, ticket_url or post_url, self.url,
            ))

        return events


def _extract_telegram_event(text: str):
    value = "\n".join(re.sub(r"[ \\t]+", " ", line).strip() for line in text.splitlines() if line.strip())

    # Accept the channel's common date formats: DD/MM/YYYY, DD.MM.YYYY,
    # and DD-MM-YYYY, optionally as a range, followed by a venue.
    date_match = re.search(
        r"(?:➡️\s*)?(\d{1,2})[./-](\d{1,2})[./-](\d{4})"
        r"(?:\s*[-–]\s*(\d{1,2})[./-](\d{1,2})[./-](\d{4}))?"
        r"\s*:\s*([^\n🎟]+)",
        value,
    )
    if not date_match:
        return None

    day, month, year = map(int, date_match.group(1, 2, 3))
    end_day = int(date_match.group(4) or day)
    end_month = int(date_match.group(5) or month)
    end_year = int(date_match.group(6) or year)
    venue = date_match.group(7).strip(" :,-")

    date_value = f"{year:04d}-{month:02d}-{day:02d}"
    end_date = f"{end_year:04d}-{end_month:02d}-{end_day:02d}"

    before = value[:date_match.start()].strip()
    # Drop promotional lead-in and keep the last meaningful line as title.
    lines = [re.sub(r"^[🤩🚨⭐️🔥🌟🎭🎻🪞\s]+", "", x).strip() for x in before.splitlines()]
    lines = [x for x in lines if len(x) >= 3]
    if not lines:
        return None
    title = re.sub(r"^SoldOut Tickets[^\n]*", "", lines[-1], flags=re.I).strip()
    if not title:
        return None

    time_match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", value)
    time_value = f"{int(time_match.group(1)):02d}:{time_match.group(2)}" if time_match else ""

    ticket_match = re.search(
        r"https?://(?:www\.)?(?:soldoutticketbox\.com|tinyurl\.com)/\S+",
        value,
        re.I,
    )
    ticket_url = ticket_match.group(0).rstrip(").,") if ticket_match else ""

    return title, date_value, end_date, time_value, venue, ticket_url


def _event(title, description, date_value, end_date, time_value, venue, ticket_url, source_url):
    return {
        "title": title,
        "description": description,
        "date": date_value,
        "end_date": end_date,
        "time": time_value,
        "venue": venue[:200],
        "city": _extract_city(venue),
        "price": _extract_price(description),
        "ticket_url": ticket_url,
        "source_url": source_url,
        "image_url": "",
        "category": "События",
    }


def _extract_date_time(text: str):
    match = re.search(
        r"(\d{2})/(\d{2})/(\d{2,4})(?:\s*[-–]\s*(\d{2})/(\d{2})/(\d{2,4}))?"
        r"(?:\s+|[^0-9])([01]?\d|2[0-3]):([0-5]\d)",
        text,
    )
    if not match:
        return None

    def iso(day, month, year):
        year = int(year)
        if year < 100:
            year += 2000
        return f"{year:04d}-{int(month):02d}-{int(day):02d}"

    return (
        iso(match.group(1), match.group(2), match.group(3)),
        iso(match.group(4) or match.group(1), match.group(5) or match.group(2), match.group(6) or match.group(3)),
        f"{int(match.group(7)):02d}:{match.group(8)}",
    )


def _extract_city(text: str) -> str:
    lower = text.casefold()
    for needle, city in CITIES:
        if needle in lower:
            return city
    return ""


def _extract_price(text: str) -> str:
    match = re.search(r"(?:From\s*)?€\s*\d+(?:[.,]\d+)?", text, re.I)
    return match.group(0) if match else ""


def _clean_title(text: str) -> str:
    value = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"^(buy|more|view)\s*$", "", value, flags=re.I).strip()
