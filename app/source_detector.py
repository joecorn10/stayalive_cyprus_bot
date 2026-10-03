"""Source URL detection and lightweight metadata inference."""

from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


CITY_KEYWORDS = {
    "Limassol": ("limassol",),
    "Nicosia": ("nicosia",),
    "Larnaca": ("larnaca",),
    "Paphos": ("paphos",),
    "Ayia Napa": ("ayia napa", "ayianapa"),
    "Paralimni": ("paralimni",),
    "Protaras": ("protaras",),
    "Polis": ("polis",),
    "Troodos": ("troodos",),
}

CATEGORY_KEYWORDS = {
    "Музыка": ("concert", "music", "dj", "live", "electronic", "techno", "house", "jazz", "gig", "музык"),
    "Театр": ("theatre", "theater", "theatre", "театр"),
    "Ночная жизнь": ("party", "club", "nightlife", "rave", "вечерин"),
    "Искусство": ("art", "gallery", "exhibition", "museum", "выстав"),
    "Фестиваль": ("festival", "фестиваль"),
    "Еда и напитки": ("food", "wine", "beer", "gastronomy", "restaurant", "еда", "вино", "пиво"),
}


def normalize_url(value: str) -> str:
    url = value.strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""

    # Do not treat arbitrary text as a website. Sources must have a real
    # hostname (for example example.com, instagram.com or t.me).
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if "." not in host:
        return ""

    # Instagram profile links often contain tracking parameters such as
    # ?stkn=.... They do not identify a different source, so keep only the
    # canonical profile path. This also prevents duplicate source records.
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if host in {"instagram.com", "instagr.am"}:
        path = parsed.path.rstrip("/")
        if path:
            return f"https://www.instagram.com{path}"
        return "https://www.instagram.com"

    return url


def detect_type(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if host in {"t.me", "telegram.me", "telegram.dog"}:
        return "Telegram"
    if host in {"instagram.com", "instagr.am"}:
        return "Instagram"
    if host in {"facebook.com", "fb.com", "m.facebook.com"}:
        return "Facebook"
    return "Website"


def _slug_name(url: str) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if parts:
        value = parts[-1].replace("_", " ").replace("-", " ")
        return value.title()
    return (parsed.hostname or "").removeprefix("www.").split(".")[0].title()


def fetch_title(url: str) -> str:
    try:
        response = requests.get(
            url,
            timeout=8,
            headers={"User-Agent": "StayAliveCyprusBot/1.0"},
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        return " ".join(title.split())[:120]
    except requests.RequestException:
        return ""


def detect_name(url: str, source_type: str) -> str:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")

    known = {
        "etkocyprus.com": "ETKO Cyprus",
        "cyproplan.com": "Cyproplan",
        "soldoutticketbox.com": "SoldOut TicketBox",
    }
    if host in known:
        return known[host]

    if source_type == "Website":
        title = fetch_title(url)
        if title:
            return title

    return _slug_name(url) or host or "Новый источник"


def infer_category(text: str) -> str:
    haystack = text.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            return category
    return "События"


def infer_city(text: str) -> str:
    haystack = text.lower()
    for city, keywords in CITY_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            return city
    return ""


def detect_source(url: str, comment: str = "") -> dict:
    source_type = detect_type(url)
    name = detect_name(url, source_type)
    context = f"{name} {url} {comment}"
    return {
        "name": name,
        "url": url,
        "type": source_type,
        "comment": comment,
        "category": infer_category(context),
        "city": infer_city(context),
    }
