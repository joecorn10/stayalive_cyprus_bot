"""ETKO Cyprus event parser."""

from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.parsers.base import EventParser

ETKO_URL = "https://etkocyprus.com/events"


class EtkoParser(EventParser):
    def __init__(self, url: str = ETKO_URL):
        self.url = url

    def parse(self) -> list[dict]:
        response = requests.get(
            self.url,
            timeout=20,
            headers={"User-Agent": "StayAliveCyprusBot/1.0"},
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        events = []

        # ETKO pages use event cards/links; keep extraction deliberately
        # tolerant so small markup changes do not break the whole bot.
        seen = set()
        for link in soup.find_all("a", href=True):
            href = urljoin(self.url, link["href"])
            title = " ".join(link.get_text(" ", strip=True).split())
            if not title or "etkocyprus.com" not in href:
                continue
            if href.rstrip("/") == self.url.rstrip("/"):
                continue

            container = link
            for _ in range(3):
                if container.parent:
                    container = container.parent
            text = " ".join(container.get_text(" ", strip=True).split())
            key = (title.lower(), href)
            if key in seen:
                continue
            seen.add(key)

            date_value, time_value = _extract_datetime(text)
            if not date_value:
                continue

            events.append({
                "title": title[:200],
                "description": text[:2000],
                "date": date_value,
                "time": time_value,
                "venue": "ETKO",
                "city": "Limassol",
                "price": "",
                "ticket_url": href,
                "source_url": href,
                "image_url": "",
            })

        return events


def _extract_datetime(text: str) -> tuple[str, str]:
    # Common formats: 03/10/2026, 03.10.2026, 3 Oct 2026, etc.
    patterns = [
        ("%d/%m/%Y", r"d{1,2}/d{1,2}/d{4}"),
        ("%d.%m.%Y", r"d{1,2}.d{1,2}.d{4}"),
        ("%d-%m-%Y", r"d{1,2}-d{1,2}-d{4}"),
    ]
    import re

    for fmt, pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                date_value = datetime.strptime(match.group(), fmt).date().isoformat()
                time_match = re.search(r"([01]?d|2[0-3]):[0-5]d", text)
                return date_value, time_match.group() if time_match else ""
            except ValueError:
                pass

    return "", ""
