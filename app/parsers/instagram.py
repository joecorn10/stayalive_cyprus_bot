"""Instagram public-profile event parser.

Instagram's logged-out HTML no longer exposes a reliable feed payload, so the
parser uses Instaloader for public posts and keeps a small HTML fallback for
profile metadata. No Instagram login or credentials are used.
"""

import html
import logging
import re
from datetime import datetime
from urllib.parse import urlparse

from app.date_utils import parse_event_dates
from app.parsers.base import EventParser

logger = logging.getLogger(__name__)

EVENT_WORDS = re.compile(
    r"\b(event|events|party|concert|live|dj|djs|wine|tasting|dinner|"
    r"market|workshop|exhibition|opening|festival|night|brunch|popup|"
    r"команд|дегустац|концерт|вечерин|фестивал|маркет|выстав|ужин|"
    r"мастер[- ]?класс|событи)\b",
    re.I,
)

TIME_RE = re.compile(
    r"(?<!\d)(?:at\s*)?(?:"
    r"(?:0?[1-9]|1[0-2])(?::[0-5]\d)?\s*(?:am|pm)"
    r"|(?:[01]?\d|2[0-3]):[0-5]\d"
    r")(?!\d)",
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
        try:
            import instaloader
        except ImportError:
            logger.error("Instagram parser requires instaloader")
            return []

        try:
            context = instaloader.Instaloader(
                download_pictures=False,
                download_videos=False,
                download_video_thumbnails=False,
                save_metadata=False,
                compress_json=False,
                quiet=True,
                max_connection_attempts=2,
            )
            profile = instaloader.Profile.from_username(context.context, self.handle)
            posts = profile.get_posts()
        except Exception as exc:
            logger.warning("Instagram @%s fetch failed: %s", self.handle, exc)
            return []

        events = []
        seen = set()
        checked = 0

        # Recent posts are enough for an events feed. Stop after 30 posts so
        # one active profile cannot consume the whole GitHub Actions run.
        for post in posts:
            checked += 1
            if checked > 30:
                break

            caption = (post.caption or "").strip()
            if not caption:
                continue

            event = self._caption_to_event(
                caption,
                post_date=post.date_utc,
                post_url=f"https://www.instagram.com/p/{post.shortcode}/",
            )
            if not event:
                continue

            key = (
                event["title"].casefold(),
                event["date"],
                event["time"],
            )
            if key in seen:
                continue
            seen.add(key)
            events.append(event)

        print(
            f"Instagram @{self.handle}: {len(events)} events parsed "
            f"from {checked} posts",
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

        default_year = (post_date or datetime.now()).year
        dates = parse_event_dates(text, default_year=default_year)
        if not dates:
            return None

        # Avoid turning ordinary posts mentioning a date into events.
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
