"""Event aggregator discovery parsers.

Fetch event links from public aggregator listing pages, then parse the
individual event pages using the generic JSON-LD event parser.
"""

import logging
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.parsers.base import EventParser
from app.parsers.website import WebsiteParser

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "StayAliveCyprusBot/1.0",
    "Accept-Language": "en-US,en;q=0.9",
}

LINK_PATTERNS = {
    "EventOr": re.compile(r"^https?://(?:www\\.)?eventor\\.com\\.cy/events/[^?#]+", re.I),
    "Cyprus.BZ": re.compile(r"^https?://(?:www\\.)?cyprus\\.bz/(?:ru/)?event/[^?#]+", re.I),
    "More.com": re.compile(r"^https?://(?:www\\.)?more\\.com/cy-(?:en|el)/tickets/[^?#]+", re.I),
}


class AggregatorParser(EventParser):
    def __init__(self, url: str, source_name: str):
        self.url = url
        self.source_name = source_name

    def parse(self) -> list[dict]:
        try:
            response = requests.get(
                self.url,
                timeout=20,
                headers=HEADERS,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("%s fetch failed: %s", self.source_name, exc)
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        links = []
        seen = set()
        pattern = LINK_PATTERNS[self.source_name]

        for link in soup.find_all("a", href=True):
            href = urljoin(self.url, link["href"])
            href = href.split("#", 1)[0]
            if not pattern.match(href):
                continue
            if href.rstrip("/") == self.url.rstrip("/"):
                continue
            if href in seen:
                continue
            seen.add(href)
            links.append(href)

        # The listing pages are dynamic on some aggregators. If they expose
        # fewer links than expected, still parse any JSON-LD Events directly.
        events = []
        for href in links[:40]:
            try:
                events.extend(WebsiteParser(href).parse())
            except requests.RequestException as exc:
                logger.debug("%s event page failed: %s", self.source_name, exc)
            except Exception:
                logger.exception("%s event parse failed: %s", self.source_name, href)

        unique = []
        event_keys = set()
        for event in events:
            key = (
                event.get("title", "").strip().lower(),
                event.get("date", ""),
                event.get("end_date", ""),
                event.get("venue", "").strip().lower(),
            )
            if not key[0] or not key[1] or key in event_keys:
                continue
            event_keys.add(key)
            unique.append(event)

        logger.info(
            "%s discovery: %s event links, %s parsed events",
            self.source_name,
            len(links),
            len(unique),
        )
        return unique
