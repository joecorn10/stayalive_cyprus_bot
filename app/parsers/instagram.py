"""Instagram public-profile event parser.

Use the public profile HTML when available, with Apify as the primary fallback
when GitHub Actions hits Instagram's login wall or rate limit. Internal API
and Jina Reader remain secondary fallbacks.
"""

import html
import json
import logging
import os
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

        if not _looks_like_event(text):
            return None

        dates = parse_event_dates(
            text,
            default_year=(post_date or datetime.now()).year,
        )
        if not dates:
            return None

        title = _find_title(text)
        time_value = _find_event_time(text)

        return {
            "title": title[:200],
            "description": text[:4000],
            "date": dates[0],
            "end_date": dates[1],
            "time": time_value,
            "venue": _find_venue(text),
            "city": _find_city(text),
            "price": _find_price(text),
            "ticket_url": post_url or self.url,
            "source_url": post_url or self.url,
            "image_url": "",
            "category": _find_category(text),
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
        logger.warning(
            "Instagram profile request failed for %s; trying Apify fallback: %s",
            profile_url,
            exc,
        )
        return (
            _fetch_via_apify(profile_url)
            or _fetch_via_mobile_api(profile_url)
            or _fetch_via_reader(profile_url)
        )

    final_path = urlparse(response.url).path.lower()
    if response.status_code != 200:
        logger.warning(
            "Instagram profile returned HTTP %s for %s; trying Apify fallback",
            response.status_code,
            profile_url,
        )
        return _fetch_via_apify(profile_url) or _fetch_via_mobile_api(profile_url) or _fetch_via_reader(profile_url)

    if "/accounts/login" in final_path:
        logger.warning(
            "Instagram profile is behind a login wall for %s; trying Apify fallback",
            profile_url,
        )
        return _fetch_via_apify(profile_url) or _fetch_via_mobile_api(profile_url) or _fetch_via_reader(profile_url)

    return _extract_posts(response.text, profile_url)


def _fetch_via_apify(profile_url: str) -> list[dict] | None:
    """Fetch recent public Instagram posts through Apify's official scraper."""
    token = os.getenv("APIFY_API_TOKEN", "").strip()
    username = urlparse(profile_url).path.strip("/").split("/")[0]
    if not token or not username:
        return None

    endpoint = (
        "https://api.apify.com/v2/actors/"
        "apify~instagram-profile-scraper/"
        "run-sync-get-dataset-items"
    )
    payload = {"usernames": [username]}

    try:
        response = requests.post(
            endpoint,
            params={"token": token},
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=120,
        )
        if not 200 <= response.status_code < 300:
            logger.warning(
                "Apify Instagram scraper returned HTTP %s for @%s: %s",
                response.status_code,
                username,
                response.text[:300],
            )
            return None
        items = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Apify Instagram scraper failed for @%s: %s", username, exc)
        return None

    if not isinstance(items, list):
        logger.warning(
            "Apify Instagram scraper returned unexpected data for @%s",
            username,
        )
        return None

    posts = []
    for profile in items:
        if not isinstance(profile, dict):
            continue
        if profile.get("error"):
            logger.warning(
                "Apify could not scrape @%s: %s",
                username,
                profile.get("errorDescription") or profile.get("error"),
            )
            continue

        raw_posts = profile.get("latestPosts") or []
        if isinstance(raw_posts, dict):
            raw_posts = [raw_posts]

        for item in raw_posts:
            if not isinstance(item, dict):
                continue

            caption = (
                item.get("caption")
                or item.get("text")
                or item.get("description")
                or ""
            )
            post_url = (
                item.get("url")
                or item.get("postUrl")
                or item.get("permalink")
                or item.get("shortCode")
                or profile_url
            )
            if isinstance(post_url, str) and post_url.startswith("http") is False:
                post_url = f"https://www.instagram.com/p/{post_url}/"

            date_value = (
                item.get("timestamp")
                or item.get("takenAtTimestamp")
                or item.get("takenAt")
                or item.get("publishedAt")
                or item.get("date")
            )
            posts.append({
                "url": str(post_url),
                "caption": str(caption),
                "date": date_value,
            })

    logger.info(
        "Apify Instagram scraper extracted %s posts from @%s",
        len(posts),
        username,
    )
    return posts or None


def _fetch_via_mobile_api(profile_url: str) -> list[dict] | None:
    """Try Instagram's internal public profile endpoint before external fallbacks."""
    username = urlparse(profile_url).path.strip("/").split("/")[0]
    if not username:
        return None

    endpoint = (
        "https://i.instagram.com/api/v1/users/web_profile_info/"
        f"?username={requests.utils.quote(username)}"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Mobile Safari/537.36"
        ),
        "X-IG-App-ID": "936619743392459",
        "Accept": "application/json",
        "Referer": profile_url,
    }
    try:
        response = requests.get(
            endpoint,
            headers=headers,
            timeout=PROFILE_TIMEOUT,
            allow_redirects=True,
        )
        if response.status_code != 200:
            logger.warning(
                "Instagram internal profile API returned HTTP %s for @%s",
                response.status_code,
                username,
            )
            return None
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Instagram internal profile API failed: %s", exc)
        return None

    user = (payload.get("data") or {}).get("user") or {}
    raw_items = (
        user.get("edge_owner_to_timeline_media", {}).get("edges")
        or user.get("edge_web_media", {}).get("edges")
        or user.get("items")
        or []
    )
    posts = []
    for item in raw_items:
        node = item.get("node", item) if isinstance(item, dict) else {}
        caption = (
            ((node.get("edge_media_to_caption") or {}).get("edges") or [{}])[0]
            .get("node", {})
            .get("text", "")
        )
        if not caption:
            caption = (node.get("caption") or {}).get("text", "")
        timestamp = node.get("taken_at_timestamp") or node.get("taken_at")
        shortcode = node.get("shortcode") or node.get("code")
        post_url = (
            f"https://www.instagram.com/p/{shortcode}/"
            if shortcode
            else profile_url
        )
        posts.append({
            "url": post_url,
            "caption": caption,
            "date": timestamp,
        })

    logger.info(
        "Instagram internal profile API extracted %s posts from @%s",
        len(posts),
        username,
    )
    return posts or None


def _fetch_via_reader(profile_url: str) -> list[dict] | None:
    """Fallback through Jina Reader when Instagram blocks anonymous HTML."""
    reader_url = "https://r.jina.ai/" + profile_url
    try:
        response = requests.get(
            reader_url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=PROFILE_TIMEOUT + 10,
        )
    except requests.RequestException as exc:
        logger.warning("Instagram Reader fallback failed: %s", exc)
        return None

    if response.status_code != 200:
        logger.warning(
            "Instagram Reader fallback returned HTTP %s for %s",
            response.status_code,
            profile_url,
        )
        return None

    posts = _extract_posts(response.text, profile_url)
    if posts:
        logger.info(
            "Instagram Reader fallback extracted %s posts from %s",
            len(posts),
            profile_url,
        )
    else:
        logger.warning(
            "Instagram Reader fallback returned content but no posts for %s",
            profile_url,
        )
    return posts


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

    # Instagram may return a login page with unrelated URLs such as
    # /p/en_US/. Never treat those as real posts.
    if "/accounts/login/" in page.lower() or "login/?next=" in page.lower():
        logger.warning("Instagram returned a login page; no public posts available")
        return []

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


def _looks_like_event(text: str) -> bool:
    """Return True when the caption is actually promoting an event."""
    if not (EVENT_WORDS.search(text) or TIME_RE.search(text)):
        return False

    external_place = re.search(
        r"(?:📍|at)\s*([A-Za-z][A-Za-z0-9 .&'_-]{2,60})",
        text,
        re.I,
    )
    partner_context = re.search(
        r"\b(?:partner|sponsor|sponsored|in partnership|proud partner|"
        r"treating the winning team)\b",
        text,
        re.I,
    )
    return not (external_place and partner_context)


def _find_title(text: str) -> str:
    """Extract an event title from common Instagram caption structures."""
    # Poster-style heading.
    first = re.split(r"\s{2,}|\n", text, maxsplit=1)[0].strip(" -–—#")
    if 4 <= len(first) <= 100 and not parse_event_dates(
        first, default_year=datetime.now().year
    ) and not TIME_RE.fullmatch(first):
        if re.search(r"[A-Za-zА-Яа-я]", first):
            return first

    # Performer / program title.
    explicit = re.search(
        r"\b(?:on our stage|featuring|feat\.?|ft\.?)\s*[:—-]\s*"
        r"([^.!?]+)",
        text,
        re.I,
    )
    if explicit:
        candidate = explicit.group(1).strip(" -–—#")
        if 3 <= len(candidate) <= 100:
            return candidate

    opening = re.search(
        r"\b(?:we['’]re|we are)\s+opening\s+(?:the\s+)?"
        r"([^.!?—:]+)",
        text,
        re.I,
    )
    if opening:
        candidate = re.sub(r"\s+[-–—]\s+.*$", "", opening.group(1).strip())
        if 3 <= len(candidate) <= 100:
            return candidate

    lead = re.match(
        r"^(.{4,100}?)(?:\s+at\s+|\s+[-–—:]\s+|\s+join us\b)",
        text,
        re.I,
    )
    if lead:
        candidate = lead.group(1).strip(" -–—:#")
        if not parse_event_dates(candidate, default_year=datetime.now().year):
            return candidate

    chunks = re.split(r"\s*[|•·]\s*|(?<=[.!?])\s+|\s+—\s+", text)
    for chunk in chunks:
        candidate = chunk.strip(" -–—#\\n")
        if 5 <= len(candidate) <= 160 and not parse_event_dates(
            candidate, default_year=datetime.now().year
        ) and not TIME_RE.fullmatch(candidate):
            if not re.fullmatch(r"(?:https?://|www\.)\S+", candidate, re.I):
                return candidate

    return "Instagram event"


def _find_event_time(text: str) -> str:
    """Find a time explicitly associated with the event."""
    match = re.search(
        r"\b(?:at|from|doors?\s+(?:open|at)|starts?\s+at|kick(?:s|ing)?\s+off\s+at)\s*("
        + TIME_RE.pattern + r")",
        text,
        re.I,
    )
    if match:
        return match.group(1).strip()

    return ""


def _find_venue(text: str) -> str:
    """Extract an explicitly named venue; do not guess from the profile."""
    match = re.search(r"📍\s*([^\n.!?]{2,100})", text, re.I)
    if match:
        return match.group(1).strip(" -–—")

    match = re.search(
        r"\b(?:at)\s+([A-Z][A-Za-z0-9 .&'_-]{2,70})",
        text,
    )
    if match:
        return match.group(1).strip(" -–—,")

    return ""


def _find_category(text: str) -> str:
    lowered = text.casefold()
    categories = (
        ("Концерты", ("concert", "live music", "live", "band", "dj")),
        ("Вечеринки", ("party", "night", "oktoberfest")),
        ("Дегустации", ("tasting", "дегустац")),
        ("Выставки", ("exhibition", "gallery opening", "выстав")),
        ("Мастер-классы", ("workshop", "мастер-класс")),
        ("Маркеты", ("market", "popup", "pop-up", "маркет")),
    )
    for category, words in categories:
        if any(word in lowered for word in words):
            return category
    return "События"


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
