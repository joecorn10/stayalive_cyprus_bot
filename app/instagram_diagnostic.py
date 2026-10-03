"""Diagnostic runner for the Instagram parser.

Usage:
    INSTAGRAM_DIAGNOSTIC_URL=https://www.instagram.com/zebra_limassol/ \
    python -m app.instagram_diagnostic
"""

import html
import os
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from app.parsers.instagram import (
    InstagramParser,
    _canonical_profile_url,
    _fetch_posts,
    _parse_datetime,
)


def main() -> None:
    raw_url = os.getenv(
        "INSTAGRAM_DIAGNOSTIC_URL",
        "https://www.instagram.com/zebra_limassol/",
    )
    url = _canonical_profile_url(raw_url)
    handle = urlparse(url).path.strip("/").split("/")[0]

    print(f"Instagram diagnostic: @{handle}")
    print(f"URL: {url}")

    parser = InstagramParser(url)
    posts = _fetch_posts(url)
    if posts is None:
        print("Parser result: no posts returned")
        return

    print(f"Posts extracted: {len(posts)}")
    print(f"Posts with captions: {sum(bool(p.get('caption')) for p in posts)}")
    print(f"Posts with dates: {sum(bool(p.get('date')) for p in posts)}")

    events = []
    for post in posts:
        event = parser._caption_to_event(
            post.get("caption", ""),
            post_date=_parse_datetime(post.get("date")),
            post_url=post.get("url") or url,
        )
        if event:
            events.append(event)

    print(f"Events parsed: {len(events)}")

    for index, post in enumerate(posts[:5], 1):
        caption = html.unescape(post.get("caption", "")).replace("\n", " ")
        print(f"POST {index}: {post.get('url', '')}")
        print(f"  date: {post.get('date') or '-'}")
        print(f"  caption: {caption[:300] or '-'}")

    for index, event in enumerate(events[:5], 1):
        print(f"EVENT {index}: {event['title']}")
        print(f"  date: {event['date']}")
        print(f"  time: {event['time'] or '-'}")
        print(f"  source: {event['source_url']}")

        
if __name__ == "__main__":
    main()
