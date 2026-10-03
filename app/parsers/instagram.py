"""Instagram public-profile event parser.

Use the public profile HTML instead of Instaloader's internal API. Instagram
currently rate-limits the internal web_profile_info endpoint aggressively from
GitHub Actions, so the parser only uses the normal public profile request and
extracts post captions/URLs from the returned HTML.
"""

import html
import json
import logging
import re
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from app.date_utils import parse_event_dates
from app.parsers.base import EventParser

logger = logging.getLogger(__name__)

PROFILE_TIMEOUT = 15
MAX_POSTS = 30

EVENT_WORDS = re.compile(
    r"\b(event|events|party|concert|live|dj|djs|wine|tasting|dinner|"
    r"market|workshop|exhibition|opening|festival|night|brunch|popup|"
    r"дегустац|концерт|вечерин|фестивал|маркет|выстав|ужин|"
    r"мастер[- ]?класс|событи)\b",
    re.I,
)
TIME_RE = re.compile(
    r"(?<!\d)(?:(?:at\s*)?(?:0?[1-9]|1[0-2])(?::[0-5]\d)?\s*(?:am|pm)"
    r"|(?:[01]?\d|2[0-3]):[0-5]\d)(?!\d)",
    re.I,
)
CITY_NAMES = (
    "Limassol", "Nicosia", "Larnaca", "Paphos", "Ayia Napa",
    "Protaras", "Paralimni", "Famagusta", "Polis", "Latchi", "Troodos",
    "Лимассол", "Никосия", "Ларнака", "Пафос",
)


class InstagramParser(EventParser):
    def __init__(self, url: str):
        self.url = _canonical_profile_url(url)
        self.handle = urlparse(self.url).path.strip("/").split("/")[0]

    def parse(self) -> list[dict]:
        payload = _fetch_posts(self.url)
        if payload is None:
            print(
                f"Instagram @{self.handle}: fetch failed",
                flush=True,
            )
            return []

        events = []
        seen = set()
        for item in payload:
            event = self._caption_to_event(
                item.get("caption", ""),
                post_date=_parse_datetime(item.get("date")),
                post_url=item.get("url") or self.url,
            )
            if not event:
                continue
            key = (event["title"].casefold(), event["date"], event["time"])
            if key in seen:
                continue
            seen.add(key)
            events.append(event)

        print(
            f"Instagram @{self.handle}: {len(events)} events parsed "
            f"from {len(payload)} posts",
            flush=True,
        )
        return events

    def _caption_to_event(
        self,
        text: str,
        *,
        post_date: datetime | None = None,
        post_url: str | None = None,
    ) -> dict | None:
        text = html.unescape(re.sub(r"\s+", " ", text)).strip()
        if not text or len(text) < 20:
            return None

        dates = parse_event_dates(
            text,
            default_year=(post_date or datetime.now()).year,
        )
        if not dates:
            return None
        if not EVENT_WORDS.search(text) and not TIME_RE.search(text):
            return None

        title = _find_title(text)
        time_match = TIME_RE.search(text)
        time_value = time_match.group(0).strip() if time_match else ""

        return {
            "title": title[:200],
            "description": text[:4000],
            "date": dates[0],
            "end_date": dates[1],
            "time": time_value,
            "venue": "",
            "city": _find_city(text),
            "price": _find_price(text),
            "ticket_url": post_url or self.url,
            "source_url": post_url or self.url,
            "image_url": "",
            "category": "События",
        }


def _fetch_posts(profile_url: str) -> list[dict] | None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    try:
        response = requests.get(
            profile_url,
            headers=headers,
            timeout=PROFILE_TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        logger.warning("Instagram profile request failed: %s", exc)
        return None

    if response.status_code != 200:
        logger.warning(
            "Instagram profile returned HTTP %s for %s",
            response.status_code,
            profile_url,
        )
        return None

    return _extract_posts(response.text, profile_url)


def _extract_posts(page: str, profile_url: str) -> list[dict]:
    """Extract public Instagram posts from several HTML/JSON layouts.

    Instagram changes its profile markup frequently. Do not depend on one
    internal API or one exact React structure. Prefer structured embedded JSON,
    then fall back to post URLs plus nearby caption text.
    """

    posts: list[dict] = []
    seen_urls: set[str] = set()

    def add_post(url: str, caption: str = "", date: str | None = None) -> None:
        if not url or not _is_post_url(url):
            return
        url = _canonical_post_url(url)
        if url in seen_urls:
            existing = next((item for item in posts if item["url"] == url), None)
            if existing:
                if caption and not existing["caption"]:
                    existing["caption"] = caption
                if date and not existing["date"]:
                    existing["date"] = date
            return
        seen_urls.add(url)
        posts.append({"url": url, "caption": caption or "", "date": date})

    soup = BeautifulSoup(page, "html.parser")

    # 1. JSON-LD and all embedded JSON objects. Modern Instagram has used
    # several nested shapes for the same public post data.
    for script in soup.find_all("script"):
        raw = script.string or script.get_text() or ""
        if not raw:
            continue

        if script.get("type") == "application/ld+json":
            try:
                data = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                data = None
            if data is not None:
                for item in _walk_json(data):
                    _add_json_post(item, add_post)

        # Some script blocks contain JSON with escaped slashes/quotes.
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            data = None
        if data is not None:
            for item in _walk_json(data):
                _add_json_post(item, add_post)

        # If the whole script is not valid JSON, still recover the common
        # caption/date fields from escaped JSON fragments.
        _extract_caption_fragments(raw, add_post)

    # 2. Explicit post URLs are still useful even when Instagram does not
    # expose structured metadata.
    for match in re.finditer(
        r'https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/[A-Za-z0-9_-]+/?',
        page,
        re.I,
    ):
        add_post(match.group(0))

    escaped = page.replace("\\/", "/")
    for match in re.finditer(
        r'https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/[A-Za-z0-9_-]+/?',
        escaped,
        re.I,
    ):
        add_post(match.group(0))

    # 3. A number of builds expose only relative post links.
    for match in re.finditer(
        r'href=["\'](/(?:p|reel|tv)/[A-Za-z0-9_-]+/?)["\']',
        page,
        re.I,
    ):
        add_post(f"https://www.instagram.com{match.group(1)}")

    # 4. Last-resort caption recovery: when a caption is present in the HTML
    # but is not attached to a structured post object, associate it with the
    # nearest post URL in the source text.
    if posts:
        _attach_nearby_captions(page, posts)

    return posts[:MAX_POSTS]


def _add_json_post(item, add_post) -> None:
    if not isinstance(item, dict):
        return

    code = item.get("shortcode") or item.get("code")
    url = item.get("url") or item.get("permalink")
    if not url and code:
        url = f"https://www.instagram.com/p/{code}/"

    caption = item.get("caption") or item.get("description") or ""
    if isinstance(caption, dict):
        caption = (
            caption.get("text")
            or (caption.get("edges") or [{}])[0].get("node", {}).get("text", "")
            if caption
            else ""
        )

    # Legacy GraphQL shape: edge_media_to_caption.edges[0].node.text
    if not caption:
        edge = item.get("edge_media_to_caption") or item.get("edge_media_to_caption")
        if isinstance(edge, dict):
            edges = edge.get("edges") or []
            if edges and isinstance(edges[0], dict):
                caption = (edges[0].get("node") or {}).get("text", "")

    date = (
        item.get("datePublished")
        or item.get("uploadDate")
        or item.get("taken_at_timestamp")
        or item.get("taken_at")
    )

    if isinstance(date, (int, float)):
        date = datetime.fromtimestamp(date).isoformat()

    if isinstance(url, str):
        add_post(url, str(caption or ""), str(date) if date else None)


def _extract_caption_fragments(raw: str, add_post) -> None:
    text = raw.replace("\\/", "/")

    # Match a caption object together with a nearby shortcode/permalink.
    for match in re.finditer(
        r'"(?:shortcode|code)"\s*:\s*"([A-Za-z0-9_-]+)"(?P<body>.{0,12000})',
        text,
        re.I | re.S,
    ):
        body = match.group("body")
        caption_match = re.search(
            r'"(?:caption|text)"\s*:\s*"((?:\\.|[^"\\])*)"',
            body,
            re.I,
        )
        date_match = re.search(
            r'"(?:taken_at_timestamp|taken_at|datePublished|uploadDate)"\s*:\s*"?([0-9T:+.\-Z]+)"?',
            body,
            re.I,
        )
        caption = ""
        if caption_match:
            try:
                caption = json.loads(f'"{caption_match.group(1)}"')
            except json.JSONDecodeError:
                caption = caption_match.group(1).replace("\\n", " ")
        date = date_match.group(1) if date_match else None
        add_post(
            f"https://www.instagram.com/p/{match.group(1)}/",
            caption,
            date,
        )


def _attach_nearby_captions(page: str, posts: list[dict]) -> None:
    """Associate visible/embedded caption strings with the nearest post URL."""
    candidates = []
    for match in re.finditer(
        r'"(?:caption|text|title)"\s*:\s*"((?:\\.|[^"\\])*)"',
        page,
        re.I,
    ):
        raw = match.group(1)
        try:
            caption = json.loads(f'"{raw}"')
        except json.JSONDecodeError:
            caption = raw.replace("\\\\n", " ")
        caption = html.unescape(re.sub(r"\s+", " ", caption)).strip()
        if len(caption) >= 20:
            candidates.append((match.start(), caption))

    if not candidates:
        return

    for post in posts:
        if post["caption"]:
            continue
        marker = page.find(post["url"].replace("https://www.instagram.com", ""))
        if marker < 0:
            continue
        nearby = min(candidates, key=lambda item: abs(item[0] - marker))
        if abs(nearby[0] - marker) <= 20000:
            post["caption"] = nearby[1]

def _walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _is_post_url(url: str) -> bool:
    try:
        path = urlparse(url).path
    except ValueError:
        return False
    return bool(re.match(r"^/(?:p|reel|tv)/[A-Za-z0-9_-]+/?$", path, re.I))


def _canonical_post_url(url: str) -> str:
    parsed = urlparse(url)
    return f"https://www.instagram.com{parsed.path.rstrip('/')}/"


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _canonical_profile_url(url: str) -> str:
    parsed = urlparse(url)
    handle = parsed.path.strip("/").split("/")[0]
    return f"https://www.instagram.com/{handle}/"


def _find_title(text: str) -> str:
    chunks = re.split(r"\s*[|•·]\s*|(?<=[.!?])\s+|\s+—\s+", text)
    for chunk in chunks:
        candidate = chunk.strip(" -–—#\n")
        if not (5 <= len(candidate) <= 160):
            continue
        if parse_event_dates(candidate, default_year=datetime.now().year):
            continue
        if re.fullmatch(r"(?:https?://|www\.)\S+", candidate, re.I):
            continue
        return candidate
    return "Instagram event"


def _find_city(text: str) -> str:
    for city in CITY_NAMES:
        if re.search(rf"\b{re.escape(city)}\b", text, re.I):
            return city
    return ""


def _find_price(text: str) -> str:
    match = re.search(
        r"(?:€|EUR)\s*\d+(?:[.,]\d+)?|\b\d+(?:[.,]\d+)?\s*€",
        text,
        re.I,
    )
    return match.group(0).replace("EUR", "€").strip() if match else ""
