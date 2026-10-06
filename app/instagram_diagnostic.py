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
from curl_cffi import requests as curl_requests

from app.parsers.instagram import (
    _extract_posts,
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

    print("\n=== Instaloader test ===")
    try:
        import instaloader
        loader = instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            download_comments=False,
            download_geotags=False,
            save_metadata=False,
            compress_json=False,
            max_connection_attempts=1,
            request_timeout=30,
        )
        profile = instaloader.Profile.from_username(loader.context, handle)
        count = 0
        for post in profile.get_posts():
            count += 1
            print(f"INSTALOADER POST {count}: {post.shortcode}")
            print(f"  date: {post.date_utc.isoformat()}")
            print(f"  url: https://www.instagram.com/p/{post.shortcode}/")
            print(f"  caption: {(post.caption or '')[:180].replace(chr(10), ' ')}")
            if count >= 10:
                break
        print(f"Instaloader posts fetched: {count}")
    except Exception as exc:
        print(f"Instaloader ERROR: {type(exc).__name__}: {exc}")

    print("\n=== RSSHub test ===")
    import requests as std_requests
    for feed_url in (
        f"https://rsshub.app/instagram/2/user/{handle}",
        f"https://rsshub.app/instagram/user/{handle}",
    ):
        try:
            response = std_requests.get(feed_url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            print(f"RSSHub {feed_url}: HTTP {response.status_code}, bytes={len(response.content)}")
            print(f"  content-type: {response.headers.get('content-type', '-')}")
            print(f"  items: {response.text.count('<item>')}")
            print(f"  contains_handle: {handle.lower() in response.text.lower()}")
            print(f"  preview: {response.text[:300].replace(chr(10), ' ')}")
        except Exception as exc:
            print(f"RSSHub {feed_url}: ERROR {type(exc).__name__}: {exc}")

    print("\n=== UnSocial availability test ===")
    print("UnSocial is a desktop/local RSS server and requires an authenticated browser session to fetch Instagram posts.")
    print("Automated GitHub runner cannot perform a meaningful UnSocial Instagram scrape without a supplied Instagram browser session.")
    print("UnSocial status: requires local session test")
    
    print("\n=== curl_cffi fingerprint test ===")
    for impersonate in ("chrome", "safari", "safari_ios"):
        try:
            response = curl_requests.get(
                url,
                impersonate=impersonate,
                timeout=20,
                headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            body = response.text
            posts_from_html = _extract_posts(body, url)
            login_wall = "login" in body.lower() and "instagram" in body.lower()
            print(
                f"curl_cffi {impersonate}: HTTP {response.status_code}, "
                f"bytes={len(response.content)}, login_wall={login_wall}, "
                f"posts={len(posts_from_html)}"
            )
            for index, post in enumerate(posts_from_html[:3], 1):
                print(f"  CURL POST {index}: {post.get('url', '')}")
                print(f"    date: {post.get('date') or '-'}")
                print(f"    caption: {(post.get('caption') or '')[:180].replace(chr(10), ' ')}")
        except Exception as exc:
            print(f"curl_cffi {impersonate}: ERROR {exc}")

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
