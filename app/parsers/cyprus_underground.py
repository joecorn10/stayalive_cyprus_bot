"""Parser for Cyprus Underground event listings.

Cyprus Underground is a JavaScript-rendered event directory.
The parser uses three layers:

1. Generic WebsiteParser for JSON-LD / normal HTML.
2. Apify Web Scraper with a real browser when the page is JS-rendered.
3. Direct requests/text parsing as a cheap final fallback.
"""

import os
import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.date_utils import parse_event_dates
from app.parsers.base import EventParser
from app.parsers.website import WebsiteParser

HEADERS = {"User-Agent": "StayAliveCyprusBot/1.0"}

APIFY_URL = (
    "https://api.apify.com/v2/actors/"
    "apify~web-scraper/run-sync-get-dataset-items"
)

DATE_RE = re.compile(
    r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)(?:\s+(20\d{2}))?$",
    re.I,
)

# Also accept common formats that can appear after JS rendering.
DATE_RE_ALT = re.compile(
    r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?[\s./-]+"
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)(?:[\s,]+(20\d{2}))?$",
    re.I,
)

TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?:\s*[-–]\s*(\d{1,2}:\d{2}))?$")

CITY_RE = re.compile(
    r"\b(Limassol|Nicosia|Larnaca|Paphos|Famagusta)\b",
    re.I,
)


class CyprusUndergroundParser(EventParser):
    def __init__(self, url: str):
        self.url = url.rstrip("/") + "/"

    def parse(self) -> list[dict]:
        # ---------------------------------------------------------------
        # 1. Cheap path: normal HTML / JSON-LD
        # ---------------------------------------------------------------
        try:
            structured = WebsiteParser(self.url).parse()
        except Exception as exc:
            print(
                "CYPRUS_UNDERGROUND_STRUCTURED_ERROR | "
                f"{type(exc).__name__}: {exc}"
            )
            structured = []

        if structured:
            for event in structured:
                event["category"] = "Nightlife"
                event["source_url"] = self.url

                if not event.get("ticket_url"):
                    event["ticket_url"] = self.url

            print(
                f"CYPRUS_UNDERGROUND_STRUCTURED | {len(structured)} events"
            )
            return _unique(structured)

        # ---------------------------------------------------------------
        # 2. Browser-rendered path: Apify
        # ---------------------------------------------------------------
        try:
            rendered = self._fetch_via_apify()

            if rendered:
                events = self._parse_rendered_listing(rendered)

                if events:
                    print(
                        f"CYPRUS_UNDERGROUND_APIFY | {len(events)} events"
                    )
                    return _unique(events)

                print("CYPRUS_UNDERGROUND_APIFY | 0 parsed events")

        except Exception as exc:
            print(
                "CYPRUS_UNDERGROUND_APIFY_ERROR | "
                f"{type(exc).__name__}: {exc}"
            )

        # ---------------------------------------------------------------
        # 3. Final cheap fallback
        # ---------------------------------------------------------------
        return self._text_cards()

    def _fetch_via_apify(self) -> dict | None:
        """Render the page in a real browser through Apify.

        The browser returns the final visible text plus all event detail
        links. This is intentionally more generic than relying on CSS
        classes which can change frequently on the source website.
        """

        token = os.getenv("APIFY_API_TOKEN")

        if not token:
            print("CYPRUS_UNDERGROUND_APIFY | APIFY_API_TOKEN missing")
            return None

        page_function = r"""
async function pageFunction(context) {
    const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

    // Give the site's JavaScript time to populate the event directory.
    await sleep(4000);

    // Trigger lazy-loaded event cards.
    window.scrollTo(0, document.body.scrollHeight);
    await sleep(2500);

    // A second scroll catches pages that progressively load more cards.
    window.scrollTo(0, 0);
    await sleep(1000);

    const links = Array.from(
        document.querySelectorAll('a[href*="/event/"]')
    ).map(a => ({
        url: a.href,
        text: (a.innerText || a.textContent || "").trim()
    }));

    return {
        url: location.href,
        text: document.body.innerText || document.body.textContent || "",
        links
    };
}
"""

        payload = {
            "startUrls": [{"url": self.url}],
            "pageFunction": page_function,
            "maxRequestsPerCrawl": 1,
            "maxConcurrency": 1,
        }

        response = requests.post(
            APIFY_URL,
            params={"token": token},
            json=payload,
            timeout=180,
        )

        print(
            "CYPRUS_UNDERGROUND_APIFY_HTTP | "
            f"status={response.status_code}"
        )

        response.raise_for_status()

        data = response.json()

        if not isinstance(data, list) or not data:
            print("CYPRUS_UNDERGROUND_APIFY | empty dataset")
            return None

        # run-sync-get-dataset-items normally returns one item per page.
        item = data[0]

        if not isinstance(item, dict):
            print("CYPRUS_UNDERGROUND_APIFY | invalid dataset item")
            return None

        text = item.get("text", "")
        links = item.get("links", [])

        print(
            "CYPRUS_UNDERGROUND_APIFY_DATA | "
            f"text_chars={len(text)} links={len(links)}"
        )

        return {
            "text": text,
            "links": links,
        }

    def _parse_rendered_listing(self, rendered: dict) -> list[dict]:
        """Parse the visible browser-rendered listing."""

        text = rendered.get("text", "")
        links = rendered.get("links", [])

        if not text:
            return []

        lines = _clean_lines(text)

        # Keep only actual event URLs.
        event_links = []
        for item in links:
            if not isinstance(item, dict):
                continue

            href = item.get("url", "")
            label = item.get("text", "")

            if href and "/event/" in href:
                event_links.append(
                    {
                        "url": href,
                        "text": re.sub(r"\s+", " ", label).strip(),
                    }
                )

        return self._parse_lines(lines, event_links)

    def _text_cards(self) -> list[dict]:
        response = requests.get(
            self.url,
            timeout=20,
            headers=HEADERS,
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        event_links = [
            a.get("href", "")
            for a in soup.find_all("a", href=True)
            if "/event/" in a.get("href", "")
        ]

        print(
            "CYPRUS_UNDERGROUND_HTML | "
            f"status={response.status_code} "
            f"bytes={len(response.text)} "
            f"event_links={len(event_links)}"
        )

        lines = _clean_lines(
            soup.get_text("\n")
        )

        events = self._parse_lines(
            lines,
            [{"url": url, "text": ""} for url in event_links],
        )

        print(f"CYPRUS_UNDERGROUND_TEXT | {len(events)} events")

        return _unique(events)

    def _parse_lines(
        self,
        lines: list[str],
        event_links: list[dict],
    ) -> list[dict]:
        """Convert the listing's visible text into normalized events."""

        events: list[dict] = []

        current_date = None
        card: list[str] = []

        def flush() -> None:
            nonlocal card

            if not current_date or not card:
                card = []
                return

            time_index = next(
                (
                    i
                    for i, value in enumerate(card)
                    if TIME_RE.match(value)
                ),
                None,
            )

            if time_index is None:
                card = []
                return

            # The event title is normally the first meaningful line.
            title = _find_title(card[:time_index])

            if not title:
                card = []
                return

            time_value = card[time_index]

            # The line after the time is usually the venue.
            venue = ""
            if time_index + 1 < len(card):
                venue = card[time_index + 1]

            city_match = CITY_RE.search(venue)
            city = city_match.group(1) if city_match else ""

            if city:
                venue = CITY_RE.sub("", venue).strip(" ,-–")

            price_match = re.search(
                r"€\s?\d+(?:[.,]\d+)?",
                " ".join(card),
            )

            clean_title = re.sub(
                r"\s*-?\s*€\s?\d+(?:[.,]\d+)?",
                "",
                title,
            ).strip()

            ticket_url = self.url

            matched_url = _match_event_url(
                clean_title,
                card,
                event_links,
            )

            if matched_url:
                ticket_url = matched_url

            description_lines = [
                value
                for i, value in enumerate(card)
                if i != time_index
                and value != title
                and value != venue
                and not TIME_RE.match(value)
            ]

            events.append(
                {
                    "title": clean_title[:200],
                    "description": " · ".join(description_lines)[:4000],
                    "date": current_date,
                    "end_date": current_date,
                    "time": time_value,
                    "venue": venue[:200],
                    "city": city[:100],
                    "price": (
                        price_match.group(0).replace(" ", "")
                        if price_match
                        else ""
                    ),
                    "ticket_url": ticket_url,
                    "source_url": self.url,
                    "image_url": "",
                    "category": "Nightlife",
                }
            )

            card = []

        for line in lines:
            parsed_date = _parse_date_line(line)

            if parsed_date:
                flush()
                current_date = parsed_date
                card = []
                continue

            if not current_date:
                continue

            # Navigation/UI noise.
            if line.casefold() in {
                "search",
                "genre:",
                "genres:",
                "i",
                "events",
                "event",
            }:
                continue

            card.append(line)

            # Most cards end immediately after their time.
            if TIME_RE.match(line):
                flush()

        flush()

        return _unique(events)


def _clean_lines(text: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", line)
        .strip()
        .lstrip("# ")
        .strip()
        for line in text.splitlines()
        if line.strip()
    ]


def _parse_date_line(line: str):
    match = DATE_RE.match(line) or DATE_RE_ALT.match(line)

    if not match:
        return None

    day, month, year = match.groups()

    year = int(year) if year else datetime.now().year

    parsed = parse_event_dates(
        f"{day} {month} {year}",
        default_year=year,
    )

    return parsed[0] if parsed else None


def _find_title(lines: list[str]) -> str:
    """Find the first useful event-title line."""

    ignored = {
        "search",
        "genre:",
        "genres:",
        "events",
        "event",
    }

    for line in lines:
        clean = line.strip()

        if not clean:
            continue

        if clean.casefold() in ignored:
            continue

        if TIME_RE.match(clean):
            continue

        # Skip obvious UI/category labels.
        if clean.lower().startswith(("genre:", "genres:")):
            continue

        return clean

    return ""


def _match_event_url(
    title: str,
    card: list[str],
    event_links: list[dict],
) -> str:
    """Match an event title to the corresponding /event/ URL."""

    if not event_links:
        return ""

    title_norm = _normalize_match_text(title)

    if not title_norm:
        return ""

    best_url = ""
    best_score = 0

    for item in event_links:
        href = item.get("url", "")
        label = item.get("text", "")

        if not href:
            continue

        label_norm = _normalize_match_text(label)

        if not label_norm:
            continue

        score = 0

        if title_norm == label_norm:
            score = 100
        elif title_norm in label_norm or label_norm in title_norm:
            score = 80
        else:
            title_words = set(title_norm.split())
            label_words = set(label_norm.split())

            if title_words and label_words:
                overlap = len(title_words & label_words)
                score = int(
                    60 * overlap / max(len(title_words), 1)
                )

        if score > best_score:
            best_score = score
            best_url = href

    if best_score >= 45:
        return best_url

    # Last resort: compare the URL slug with the title.
    title_slug = re.sub(
        r"[^a-z0-9]+",
        "-",
        title.lower(),
    ).strip("-")

    for item in event_links:
        href = item.get("url", "")
        slug = href.rstrip("/").rsplit("/", 1)[-1].lower()

        if (
            slug
            and title_slug
            and (
                title_slug[:30] in slug
                or slug[:30] in title_slug
            )
        ):
            return href

    return ""


def _normalize_match_text(value: str) -> str:
    value = value.lower()
    value = re.sub(r"€\s?\d+(?:[.,]\d+)?", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _unique(events: list[dict]) -> list[dict]:
    seen = set()
    result = []

    for event in events:
        key = (
            event.get("title", "").casefold(),
            event.get("date", ""),
            event.get("time", ""),
            event.get("venue", "").casefold(),
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(event)

    return result
