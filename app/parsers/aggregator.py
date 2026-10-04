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
        pattern = LINK_PATTERNS[self.source_name]
        discovery_urls = _discovery_urls(self.url, self.source_name)

        pages: list[tuple[str, str]] = []
        seen_pages: set[str] = set()
        queue = list(discovery_urls)

        while queue and len(pages) < MAX_PAGES:
            page_url = queue.pop(0)
            if page_url in seen_pages:
                continue
            seen_pages.add(page_url)

            try:
                response = requests.get(page_url, timeout=45, headers=HEADERS)
                response.raise_for_status()
            except requests.RequestException as exc:
                logger.warning("%s fetch failed: %s", self.source_name, exc)
                continue

            pages.append((page_url, response.text))
            soup = BeautifulSoup(response.text, "html.parser")

            # Prefer real pagination links when the site exposes them.
            for link in soup.find_all("a", href=True):
                href = urljoin(page_url, link["href"]).split("#", 1)[0]
                if _is_pagination_link(link, href, page_url) and href not in seen_pages:
                    queue.append(href)

            # Cyprus.BZ can omit pagination controls from server-rendered HTML.
            # Probe its conventional ?page=N form as a bounded fallback.
            if self.source_name == "Cyprus.BZ":
                for page_number in range(2, MAX_PAGES + 1):
                    href = _page_url(page_url, page_number)
                    if href not in seen_pages and href not in queue:
                        queue.append(href)

        links = []
        seen_links = set()
        events = []

        for page_url, html in pages:
            soup = BeautifulSoup(html, "html.parser")

            for link in soup.find_all("a", href=True):
                href = urljoin(page_url, link["href"]).split("#", 1)[0]
                if not pattern.match(href):
                    continue
                if href.rstrip("/") == page_url.rstrip("/"):
                    continue
                if href in seen_links:
                    continue
                seen_links.add(href)
                links.append(href)

            try:
                events.extend(_parse_jsonld_events(html, page_url))
            except Exception:
                logger.exception(
                    "%s listing JSON-LD parse failed: %s",
                    self.source_name,
                    page_url,
                )

        # Parse all discovered unique event pages up to a safe upper bound,
        # instead of only the first 80 links from one catalogue page.
        for href in links[:300]:
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
            "%s discovery: %s pages, %s event links, %s parsed events",
            self.source_name,
            len(pages),
            len(links),
            len(unique),
        )
        print(
            f"{self.source_name} discovery: {len(pages)} pages, "
            f"{len(links)} event links, {len(unique)} parsed events",
            flush=True,
        )
        return unique
def _discovery_urls(url: str, source_name: str) -> tuple[str, ...]:
    base = url.rstrip("/")
    if source_name == "Cyprus.BZ":
        urls = [base]
        if base.endswith("cyprus.bz"):
            urls.append(f"{base}/events/today")
        return tuple(dict.fromkeys(urls))
    return (url,)


def _page_url(url: str, page_number: int) -> str:
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["page"] = str(page_number)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _is_pagination_link(link, href: str, page_url: str) -> bool:
    text = " ".join(link.stripped_strings).strip().casefold()
    rel = " ".join(link.get("rel", [])).casefold()
    aria = str(link.get("aria-label", "")).casefold()
    if any(token in text for token in ("next", "след", "»", "›")):
        return True
    if "next" in rel or "next" in aria:
        return True

    from urllib.parse import parse_qs, urlsplit
    current = parse_qs(urlsplit(page_url).query).get("page", ["1"])[0]
    candidate = parse_qs(urlsplit(href).query).get("page", [None])[0]
    return candidate is not None and candidate != current


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
