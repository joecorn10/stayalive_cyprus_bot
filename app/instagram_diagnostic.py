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
    PROFILE_TIMEOUT,
    InstagramParser,
    _canonical_profile_url,
    _extract_posts,
    _parse_datetime,
)


def main() -> None:
    raw_url = os.getenv(
        "INSTAGRAM_DIAGNOSTIC_URL",
        "https://www.instagram.com/zebra_limassol/",
    )
    url = _canonical_profile_url(raw_url)
    handle = urlparse(url).path.strip("/").split("/")[0]

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    print(f"Instagram diagnostic: @{handle}")
    print(f"URL: {url}")

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=PROFILE_TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        print(f"HTTP request failed: {exc}")
        return

    print(f"HTTP status: {response.status_code}")
    print(f"Final URL: {response.url}")
    print(f"HTML length: {len(response.text)}")

    soup = BeautifulSoup(response.text, "html.parser")
    print(f"Script tags: {len(soup.find_all('script'))}")

    if response.status_code != 200:
        print("Parser result: cannot parse non-200 response")
        return

    posts = _extract_posts(response.text, url)
    print(f"Posts extracted: {len(posts)}")
    print(f"Posts with captions: {sum(bool(p.get('caption')) for p in posts)}")
    print(f"Posts with dates: {sum(bool(p.get('date')) for p in posts)}")

    parser = InstagramParser(url)
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
