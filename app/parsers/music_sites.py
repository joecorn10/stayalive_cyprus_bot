"""Music Hall / Live Music Zone event parser."""
import re
from datetime import datetime
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from app.parsers.base import EventParser

HEADERS = {"User-Agent": "StayAliveCyprusBot/1.0"}

class MusicSiteParser(EventParser):
    def __init__(self, url: str):
        self.url = url

    def parse(self) -> list[dict]:
        response = requests.get(self.url, timeout=25, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        lines = [re.sub(r"\\s+", " ", x).strip() for x in soup.get_text("\n").splitlines() if x.strip()]
        events = []
        seen = set()
        for i, line in enumerate(lines):
            parsed = self._date(line)
            if not parsed:
                continue
            date_value = parsed
            title = self._title(lines, i)
            if not title:
                continue
            key = (title.casefold(), date_value)
            if key in seen:
                continue
            seen.add(key)
            events.append({
                "title": title[:200],
                "description": "",
                "date": date_value,
                "end_date": date_value,
                "time": "",
                "venue": "Music Hall",
                "city": "Limassol",
                "price": "",
                "ticket_url": self._ticket(soup, title),
                "source_url": self.url,
                "image_url": "",
                "category": "🎵 Музыка",
            })
        return events

    @staticmethod
    def _date(line: str):
        m = re.fullmatch(r"(\\d{1,2})/(\\d{1,2})(?:/(\\d{2,4}))?", line)
        if not m:
            return None
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3) or datetime.now().year)
        if year < 100:
            year += 2000
        if 1 <= day <= 31 and 1 <= month <= 12:
            return f"{year:04d}-{month:02d}-{day:02d}"
        return None

    @staticmethod
    def _title(lines, index):
        skip = {"sunday","monday","tuesday","wednesday","thursday","friday","saturday",
                "buy ticket","купить билет","reserve","image","menu","contacts","gallery"}
        for offset in range(1, 7):
            pos = index - offset
            if pos < 0:
                break
            value = lines[pos].strip()
            lower = value.casefold()
            if not value or lower in skip:
                continue
            if value.startswith(("http://","https://","t.me/")):
                continue
            if any(x in lower for x in ("buy ticket","купить билет","reserve","follow up")):
                continue
            if len(value) > 100 or len(value.split()) > 14:
                continue
            return value.strip(" -—:|")
        return ""

    @staticmethod
    def _ticket(soup, title):
        key = title.casefold()[:25]
        for link in soup.find_all("a", href=True):
            label = " ".join(link.stripped_strings).casefold()
            if "buy ticket" not in label and "купить билет" not in label:
                continue
            parent = link
            for _ in range(4):
                if parent.parent:
                    parent = parent.parent
            block = " ".join(parent.get_text(" ", strip=True).split()).casefold()
            if key in block:
                return urljoin("https://musichall.cy/", link["href"])
        return ""
