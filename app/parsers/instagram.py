"""Instagram public-profile event parser.

Instagram's logged-out HTML no longer exposes a reliable feed payload. The
parser therefore uses Instaloader in a short-lived subprocess. The subprocess
is deliberately isolated so an Instagram hang cannot block the main bot.
"""

import html
import logging
import re
import subprocess
import sys
import json
from datetime import datetime
from urllib.parse import urlparse

from app.date_utils import parse_event_dates
from app.parsers.base import EventParser

logger = logging.getLogger(__name__)

PROFILE_TIMEOUT = 20
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
        payload = _fetch_posts(self.handle)
        if payload is None:
            print(
                f"Instagram @{self.handle}: fetch failed or timed out",
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


def _fetch_posts(handle: str) -> list[dict] | None:
    code = r'''
import json
import sys
import instaloader

handle = sys.argv[1]
context = instaloader.Instaloader(
    download_pictures=False,
    download_videos=False,
    download_video_thumbnails=False,
    save_metadata=False,
    compress_json=False,
    quiet=True,
    max_connection_attempts=1,
)
profile = instaloader.Profile.from_username(context.context, handle)
items = []
for index, post in enumerate(profile.get_posts()):
    if index >= 30:
        break
    caption = (post.caption or "").strip()
    if not caption:
        continue
    items.append({
        "caption": caption,
        "date": post.date_utc.isoformat(),
        "url": f"https://www.instagram.com/p/{post.shortcode}/",
    })
print(json.dumps(items, ensure_ascii=False))
'''
    try:
        result = subprocess.run(
            [sys.executable, "-c", code, handle],
            capture_output=True,
            text=True,
            timeout=PROFILE_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("Instagram @%s timed out after %ss", handle, PROFILE_TIMEOUT)
        return None
    except OSError as exc:
        logger.warning("Instagram @%s subprocess failed: %s", handle, exc)
        return None

    if result.returncode != 0:
        logger.warning(
            "Instagram @%s failed: %s",
            handle,
            (result.stderr or "").strip()[-500:],
        )
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.warning("Instagram @%s returned invalid post data", handle)
        return None

    return data if isinstance(data, list) else []


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
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
