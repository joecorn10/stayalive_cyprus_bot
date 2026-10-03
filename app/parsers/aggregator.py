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
    "EventOr": re.compile(r"^https?://(?:www\.)?eventor\.com\.cy/events?/[^?#]+", re.I),
    "Cyprus.BZ": re.compile(r"^https?://(?:www\.)?cyprus\.bz/(?:ru/)?events?/[^?#]+", re.I),
    "More.com": re.compile(r"^https?://(?:www\.)?more\.com/cy-(?:en|el)/tickets/[^?#]+", re.I),
}


class AggregatorParser(EventParser):
    def __init__(self, url: str, source_name: str):
        self.url = url
        self.source_name = source_name

    def parse(self) -> list[dict]:
        try:
            response = requests.get(
                self.url,
                timeout=45,
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

        # Some aggregators expose complete Event JSON-LD on the listing page,
        # while others expose individual event links. Parse both paths.
        events = []
        try:
            events.extend(_parse_jsonld_events(response.text, self.url))
        except Exception:
            logger.exception("%s listing JSON-LD parse failed", self.source_name)

        for href in links[:80]:
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
        )\n        print(\n            f"{self.source_name} discovery: {len(links)} event links, {len(unique)} parsed events",\n            flush=True,\n        )
        return unique


def _parse_jsonld_events(html: str, page_url: str) -> list[dict]:
    import json
    soup = BeautifulSoup(html, "html.parser")
    parser = WebsiteParser(page_url)
    events = []
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.string or node.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        candidates = []
        if isinstance(data, dict):
            if data.get("@type") == "Event":
                candidates.append(data)
            graph = data.get("@graph")
            if isinstance(graph, list):
                candidates.extend(graph)
            item_list = data.get("itemListElement")
            if isinstance(item_list, list):
                for entry in item_list:
                    if isinstance(entry, dict):
                        item = entry.get("item")
                        if isinstance(item, dict):
                            candidates.append(item)
        elif isinstance(data, list):
            candidates.extend(data)

        for item in candidates:
            if not isinstance(item, dict):
                continue
            types = item.get("@type", [])
            if "Event" not in (types if isinstance(types, list) else [types]):
                continue
            event = parser._event(item)
            if event:
                events.append(event)
    return events
