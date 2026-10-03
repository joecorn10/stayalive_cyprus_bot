"""Generic JSON-LD event parser for public websites."""

import json
import re
from datetime import datetime
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
        if "stantarkkomety.com" in self.url:
            stantar_events = self._stantar_cards(soup)
            if stantar_events:
                return stantar_events
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
        # Some modern event sites render their programme as semantic HTML instead
        # of JSON-LD. Fall back to a structured card parser first, then the
        # generic date/time/venue line parser.
        if not events:
            events = self._html_schedule_events(soup)
        return events

    def _stantar_cards(self, soup: BeautifulSoup) -> list[dict]:
        """Parse Stantar Kkomety's individual festival cards from stable semantics."""
        month_map = {
            "jan": "January", "feb": "February", "mar": "March",
            "apr": "April", "may": "May", "jun": "June",
            "jul": "July", "aug": "August", "sep": "September",
            "oct": "October", "nov": "November", "dec": "December",
        }
        year_match = re.search(r"\b(20\d{2})\b", soup.get_text(" ", strip=True))
        default_year = int(year_match.group(1)) if year_match else datetime.now().year
        meta_re = re.compile(
            r"^(\d{1,2}:\d{2})\s*[–—-]\s*(\d{1,2}:\d{2})\s*[·•]\s*(.+)$"
        )
        date_re = re.compile(
            r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{1,2})\s+"
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b",
            re.I,
        )
        events = []

        for card in soup.find_all("li", class_=re.compile(r"individualCard", re.I)):
            meta = card.find(class_=re.compile(r"showMeta", re.I))
            title_node = card.find("h3")
            if not meta or not title_node:
                continue

            match = meta_re.match(re.sub(r"\s+", " ", meta.get_text(" ", strip=True)))
            if not match:
                continue

            aria_text = " ".join(
                str(a.get("aria-label") or "") for a in card.find_all("a")
            )
            date_match = date_re.search(aria_text)
            if not date_match:
                continue

            month = month_map[date_match.group(2).lower()]
            parsed = parse_event_dates(
                f"{date_match.group(1)} {month} {default_year}",
                default_year=default_year,
            )
            if not parsed:
                continue

            title = re.sub(r"\s+", " ", title_node.get_text(" ", strip=True)).strip()
            start_time, _, venue = match.groups()
            ticket = card.find("a", href=True, class_=re.compile(r"buySingle", re.I))
            if not ticket:
                ticket = card.find(
                    "a", href=True,
                    string=re.compile(r"buy\s*tickets|купить\s*билет", re.I),
                )

            events.append({
                "title": title[:200],
                "description": "",
                "date": parsed[0],
                "end_date": parsed[0],
                "time": start_time,
                "venue": venue[:200],
                "city": "Limassol",
                "price": "",
                "ticket_url": urljoin(self.url, ticket["href"]) if ticket else "",
                "source_url": self.url,
                "image_url": "",
                "category": _website_category(title),
            })

        return events

    def _card_schedule_events(self, soup: BeautifulSoup) -> list[dict]:
        """Parse event-card based schedules where time/title are separate DOM nodes."""
        date_re = re.compile(
            r"^(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday),?\s+"
            r"\d{1,2}\s+(?:january|february|march|april|may|june|july|august|"
            r"september|october|november|december)$",
            re.I,
        )
        meta_re = re.compile(
            r"^(\d{1,2}:\d{2})\s*[–—-]\s*(\d{1,2}:\d{2})\s*[·•]\s*(.+)$"
        )
        default_year = datetime.now().year
        year_match = re.search(r"\b(20\d{2})\b", soup.get_text(" ", strip=True))
        if year_match:
            default_year = int(year_match.group(1))

        events = []

        for node in soup.find_all("li"):
            classes = " ".join(node.get("class", []))
            if "individualCard" not in classes:
                continue

            # Find the nearest preceding date heading in document order. Some
            # React sites render the heading as a div rather than an h2.
            current_date = None

            # Prefer an explicit date in the ticket link's aria-label. This is
            # resilient to React layouts where the visible day heading is not
            # represented as one DOM text node.
            aria_text = " ".join(
                str(a.get("aria-label") or "") for a in node.find_all("a")
            )
            aria_date = re.search(
                r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{1,2})\s+"
                r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b",
                aria_text,
                re.I,
            )
            if aria_date:
                month_map = {
                    "jan": "January", "feb": "February", "mar": "March",
                    "apr": "April", "may": "May", "jun": "June",
                    "jul": "July", "aug": "August", "sep": "September",
                    "oct": "October", "nov": "November", "dec": "December",
                }
                month = month_map[aria_date.group(2).lower()]
                parsed = parse_event_dates(
                    f"{aria_date.group(1)} {month} {default_year}",
                    default_year=default_year,
                )
                current_date = parsed[0] if parsed else None

            if not current_date:
                for previous_tag in node.find_all_previous():
                    heading = re.sub(r"\s+", " ", previous_tag.get_text(" ", strip=True)).strip()
                    if date_re.match(heading):
                        parsed = parse_event_dates(heading, default_year=default_year)
                        current_date = parsed[0] if parsed else None
                        break
            if not current_date:
                continue

            meta = node.find(class_=re.compile(r"showMeta", re.I))
            title_node = node.find("h3")
            if not meta or not title_node:
                continue

            meta_text = re.sub(r"\s+", " ", meta.get_text(" ", strip=True))
            match = meta_re.match(meta_text)
            if not match:
                continue

            title = re.sub(r"\s+", " ", title_node.get_text(" ", strip=True)).strip()
            start_time, end_time, venue = match.groups()
            ticket = node.find(
                "a",
                href=True,
                string=re.compile(r"buy\s*tickets|купить\s*билет", re.I),
            )
            if not ticket:
                ticket = node.find("a", class_=re.compile(r"buySingle", re.I), href=True)

            events.append({
                "title": title[:200],
                "description": "",
                "date": current_date,
                "end_date": current_date,
                "time": start_time,
                "venue": venue[:200],
                "city": "Limassol" if "limassol" in soup.get_text(" ", strip=True).lower() else "",
                "price": "",
                "ticket_url": urljoin(self.url, ticket["href"]) if ticket else "",
                "source_url": self.url,
                "image_url": "",
                "category": _website_category(title),
            })

        return events

    def _html_schedule_events(self, soup: BeautifulSoup) -> list[dict]:
        card_events = self._card_schedule_events(soup)
        if card_events:
            return card_events

        text = soup.get_text("\n")
        lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
        lines = [line.lstrip("# ").strip() for line in lines if line.strip()]

        date_re = re.compile(
            r"^(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday),?\s+"
            r"\d{1,2}\s+(?:january|february|march|april|may|june|july|august|"
            r"september|october|november|december)$",
            re.I,
        )
        time_re = re.compile(
            r"^(\d{1,2}:\d{2})\s*[–—-]\s*(\d{1,2}:\d{2})\s*[·•]\s*(.+)$"
        )
        split_time_start_re = re.compile(r"^(\d{1,2}:\d{2})$")
        split_time_end_re = re.compile(
            r"^[–—-]\s*(\d{1,2}:\d{2})\s*[·•]\s*(.+)$"
        )
        languages = {
            "english", "русский", "greek", "cypriot greek",
            "bosnian · croatian · serbian",
        }

        default_year = datetime.now().year
        year_match = re.search(r"\b(20\d{2})\b", text)
        if year_match:
            default_year = int(year_match.group(1))

        events: list[dict] = []
        current_date: str | None = None
        pending: tuple[str, str, str] | None = None
        pending_start: str | None = None
        ticket_links: list[str] = [
            urljoin(self.url, a.get("href", "").strip())
            for a in soup.find_all("a")
            if a.get("href") and re.search(r"buy\s*tickets|купить\s*билет", a.get_text(" ", strip=True), re.I)
        ]
        ticket_index = 0

        for line in lines:
            date_match = date_re.match(line)
            if date_match:
                parsed = parse_event_dates(line, default_year=default_year)
                current_date = parsed[0] if parsed else None
                pending = None
                pending_start = None
                continue

            time_match = time_re.match(line)
            if time_match and current_date:
                pending = time_match.groups()
                pending_start = None
                continue

            # Some sites split a schedule row into separate text nodes:
            # "19:30" followed by "–20:30 · Da Vinci".
            if current_date and not pending:
                start_match = split_time_start_re.match(line)
                if start_match:
                    pending_start = start_match.group(1)
                    continue
                if pending_start:
                    split_match = split_time_end_re.match(line)
                    if split_match:
                        pending = (pending_start, split_match.group(1), split_match.group(2))
                        pending_start = None
                        continue
                    pending_start = None

            if not pending or not current_date:
                continue
            if line.casefold() in languages:
                continue
            if line.casefold().startswith(("buy tickets", "купить билет")):
                continue

            start_time, _, venue = pending
            ticket_url = ticket_links[ticket_index] if ticket_index < len(ticket_links) else ""
            ticket_index += 1
            events.append({
                "title": line[:200],
                "description": "",
                "date": current_date,
                "end_date": current_date,
                "time": start_time,
                "venue": venue[:200],
                "city": "Limassol" if "limassol" in text.lower() else "",
                "price": "",
                "ticket_url": ticket_url,
                "source_url": self.url,
                "image_url": "",
                "category": _website_category(line),
            })
            pending = None
            pending_start = None

        unique: list[dict] = []
        seen = set()
        for event in events:
            key = (event["title"].casefold(), event["date"], event["time"], event["venue"].casefold())
            if key not in seen:
                seen.add(key)
                unique.append(event)
        return unique

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
            "category": _website_category(title),
        }

def _website_category(text: str) -> str:
    value = str(text or "")
    if re.search(r"(?i)\b(stand[- ]?up|comedy|comedian|open mic|стендап|стендапер|комеди|юмор)\b", value):
        return "🎭 Comedy"
    return "События"


def _time(value: str) -> str:
    m = re.search(r"T(\d{2}:\d{2})", value)
    return m.group(1) if m else ""


def _end_date(end_dates, start_dates):
    if end_dates:
        return end_dates[1] if len(end_dates) > 1 else end_dates[0]
    return start_dates[1] if len(start_dates) > 1 else start_dates[0]
