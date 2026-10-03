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

            start_date, end_date, time_value = _extract_detail_datetime(href)
            if not start_date:
                # Keep the listing-page parser as a fallback.
                start_date, end_date, time_value = _extract_datetime(card_text)
            if not start_date:
                continue

            seen_urls.add(href)
            events.append({
                "title": title[:200],
                "description": card_text[:2000],
                "date": start_date,
                "end_date": end_date,
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


def _extract_detail_datetime(url: str) -> tuple[str, str, str]:
    try:
        response = requests.get(url, timeout=15, headers=HEADERS)
        response.raise_for_status()
    except requests.RequestException:
        return "", "", ""

    soup = BeautifulSoup(response.text, "html.parser")
    text = " ".join(soup.get_text(" ", strip=True).split())

    # ETKO event pages expose a dedicated Date/Time section.
    date_match = re.search(
        r"\bDate\s+(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+(\d{1,2})\b",
        text,
        re.IGNORECASE,
    )
    if not date_match:
        return "", "", ""

    month = MONTHS[date_match.group(1).lower()]
    day = int(date_match.group(2))
    year = datetime.now().year
    date_value = f"{year:04d}-{month:02d}-{day:02d}"

    time_match = re.search(
        r"\bTime\s+([01]?\d|2[0-3]):([0-5]\d)\b",
        text,
        re.IGNORECASE,
    )
    time_value = f"{time_match.group(1)}:{time_match.group(2)}" if time_match else ""

    return date_value, date_value, time_value


def _extract_datetime(text: str) -> tuple[str, str, str]:
    match = re.search(
        r"\b(\d{1,2})\.(\d{1,2})\s*(?:-|–|—)\s*(\d{1,2})\.(\d{1,2})\b",
        text,
    )
    if match:
        year = datetime.now().year
        start_day, start_month = int(match.group(1)), int(match.group(2))
        end_day, end_month = int(match.group(3)), int(match.group(4))
        start = f"{year:04d}-{start_month:02d}-{start_day:02d}"
        end = f"{year:04d}-{end_month:02d}-{end_day:02d}"
        return start, end, _extract_time(text)

    match = re.search(
        r"\b([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?"
        r"(?:\s*(?:-|–|—)\s*([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?)?"
        r"\s*(\d{4})?\b",
        text,
        re.IGNORECASE,
    )
    if match:
        start_month = MONTHS.get(match.group(1).lower())
        if start_month:
            start_day = int(match.group(2))
            end_month = MONTHS.get((match.group(3) or match.group(1)).lower())
            end_day = int(match.group(4) or start_day)
            year = int(match.group(5)) if match.group(5) else datetime.now().year
            start = f"{year:04d}-{start_month:02d}-{start_day:02d}"
            end = f"{year:04d}-{end_month:02d}-{end_day:02d}"
            return start, end, _extract_time(text)

    return "", "", ""


def _extract_time(text: str) -> str:
    match = re.search(r"\b([01]?\d|2[0-3]):[0-5]\d\b", text)
    return match.group(0) if match else ""
