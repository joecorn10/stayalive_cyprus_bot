"""Parser for Cyprus Underground event listings.

Cyprus Underground is a JavaScript-rendered event directory.
Use the normal HTTP parser first and fall back to local Playwright
browser rendering when the event cards are not present in server HTML.
"""

import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.date_utils import parse_event_dates
from app.parsers.base import EventParser
from app.parsers.website import WebsiteParser

HEADERS = {"User-Agent": "StayAliveCyprusBot/1.0"}

DATE_RE = re.compile(
    r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)(?:\s+(20\d{2}))?$",
    re.I,
)

DATE_RE_ALT = re.compile(
    r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?[\s./-]+"
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)(?:[\s,]+(20\d{2}))?$",
    re.I,
)

TIME_RE = re.compile(
    r"^(\d{1,2}:\d{2})(?:\s*[-–]\s*(\d{1,2}:\d{2}))?$"
)

CITY_RE = re.compile(
    r"\b(Limassol|Nicosia|Larnaca|Paphos|Famagusta)\b",
    re.I,
)


class CyprusUndergroundParser(EventParser):
    def __init__(self, url: str):
        self.url = url.rstrip("/") + "/"

    def parse(self) -> list[dict]:
        # ---------------------------------------------------------------
        # 1. Cheap HTTP / JSON-LD path
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
        # 2. Local browser rendering
        # ---------------------------------------------------------------
        try:
            rendered = self._fetch_via_playwright()

            if rendered:
                events = self._parse_rendered_page(rendered)

                print(
                    f"CYPRUS_UNDERGROUND_PLAYWRIGHT | {len(events)} events"
                )

                if events:
                    return _unique(events)

        except Exception as exc:
            print(
                "CYPRUS_UNDERGROUND_PLAYWRIGHT_ERROR | "
                f"{type(exc).__name__}: {exc}"
            )

        # ---------------------------------------------------------------
        # 3. Final direct HTTP fallback
        # ---------------------------------------------------------------
        return self._text_cards()

    def _fetch_via_playwright(self) -> dict | None:
        """Render Cyprus Underground with a real local Chromium browser."""

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print(
                "CYPRUS_UNDERGROUND_PLAYWRIGHT | "
                "Playwright is not installed"
            )
            return None

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )

            page = browser.new_page(
                user_agent=HEADERS["User-Agent"],
                viewport={
                    "width": 1440,
                    "height": 1200,
                },
            )

            try:
                print(
                    "CYPRUS_UNDERGROUND_PLAYWRIGHT | "
                    "loading page"
                )

                page.goto(
                    self.url,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )

                # The site populates the event list asynchronously.
                page.wait_for_timeout(5000)

                # Trigger lazy-loaded content.
                page.evaluate(
                    """
                    () => {
                        window.scrollTo(0, document.body.scrollHeight);
                    }
                    """
                )

                page.wait_for_timeout(2500)

                page.evaluate(
                    """
                    () => {
                        window.scrollTo(0, 0);
                    }
                    """
                )

                page.wait_for_timeout(1000)

                text = page.locator("body").inner_text()

                links = page.locator('a[href*="/event/"]')

                event_links = []

                for i in range(links.count()):
                    link = links.nth(i)

                    try:
                        href = link.get_attribute("href") or ""
                        label = link.inner_text().strip()

                        if "/event/" not in href:
                            continue

                        event_links.append(
                            {
                                "url": urljoin(self.url, href),
                                "text": re.sub(
                                    r"\s+",
                                    " ",
                                    label,
                                ).strip(),
                            }
                        )
                    except Exception:
                        continue

                print(
                    "CYPRUS_UNDERGROUND_PLAYWRIGHT_DATA | "
                    f"text_chars={len(text)} "
                    f"event_links={len(event_links)}"
                )

                return {
                    "text": text,
                    "links": event_links,
                }

            finally:
                browser.close()

    def _parse_rendered_page(self, rendered: dict) -> list[dict]:
        text = rendered.get("text", "")
        links = rendered.get("links", [])

        if not text:
            return []

        lines = _clean_lines(text)

        return self._parse_lines(lines, links)

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
            [
                {
                    "url": urljoin(self.url, href),
                    "text": "",
                }
                for href in event_links
            ],
        )

        print(
            f"CYPRUS_UNDERGROUND_TEXT | {len(events)} events"
        )

        return _unique(events)

    def _parse_lines(
        self,
        lines: list[str],
        event_links: list[dict],
    ) -> list[dict]:
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
                return

            title = _find_title(card[:time_index])

            if not title:
                card = []
                return

            time_value = card[time_index]

            venue = ""

            if time_index + 1 < len(card):
                venue = card[time_index + 1]

            city_match = CITY_RE.search(venue)
            city = city_match.group(1) if city_match else ""

            if city:
                venue = CITY_RE.sub(
                    "",
                    venue,
                ).strip(" ,-–")

            price_match = re.search(
                r"€\s?\d+(?:[.,]\d+)?",
                " ".join(card),
            )

            clean_title = re.sub(
                r"\s*-?\s*€\s?\d+(?:[.,]\d+)?",
                "",
                title,
            ).strip()

            ticket_url = _match_event_url(
                clean_title,
                event_links,
            )

            if not ticket_url:
                ticket_url = self.url

            description_lines = []

            for i, value in enumerate(card):
                if i == time_index:
                    continue

                if value == title:
                    continue

                if value == venue:
                    continue

                if TIME_RE.match(value):
                    continue

                if _looks_like_ui(value):
                    continue

                description_lines.append(value)

            events.append(
                {
                    "title": clean_title[:200],
                    "description": " · ".join(
                        description_lines
                    )[:4000],
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

            if _looks_like_ui(line):
                continue

            card.append(line)

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
    ignored = {
        "search",
        "genre:",
        "genres:",
        "events",
        "event",
        "i",
    }

    for line in lines:
        clean = line.strip()

        if not clean:
            continue

        if clean.casefold() in ignored:
            continue

        if TIME_RE.match(clean):
            continue

        if _looks_like_ui(clean):
            continue

        return clean

    return ""


def _looks_like_ui(value: str) -> bool:
    value = value.strip().casefold()

    if not value:
        return True

    return value in {
        "search",
        "genre:",
        "genres:",
        "location",
        "location permission required",
        "events",
        "event",
        "i",
        "more",
        "load more",
    }


def _match_event_url(
    title: str,
    event_links: list[dict],
) -> str:
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

        elif (
            title_norm in label_norm
            or label_norm in title_norm
        ):
            score = 80

        else:
            title_words = set(title_norm.split())
            label_words = set(label_norm.split())

            if title_words and label_words:
                overlap = len(
                    title_words & label_words
                )

                score = int(
                    60
                    * overlap
                    / max(len(title_words), 1)
                )

        if score > best_score:
            best_score = score
            best_url = href

    if best_score >= 45:
        return best_url

    return ""


def _normalize_match_text(value: str) -> str:
    value = value.lower()

    value = re.sub(
        r"€\s?\d+(?:[.,]\d+)?",
        "",
        value,
    )

    value = re.sub(
        r"[^a-z0-9]+",
        " ",
        value,
    )

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


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
