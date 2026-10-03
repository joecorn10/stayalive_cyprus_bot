"""Lightweight event text translation to Russian."""

import re
import logging
import requests

logger = logging.getLogger(__name__)

URL = "https://translate.googleapis.com/translate_a/single"
HEADERS = {"User-Agent": "StayAliveCyprusBot/1.0"}


def _has_latin(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]", text or ""))


def translate_to_russian(text: str, max_chars: int = 5000) -> str:
    text = str(text or "").strip()
    if not text or not _has_latin(text):
        return text
    try:
        response = requests.get(
            URL,
            params={
                "client": "gtx",
                "sl": "auto",
                "tl": "ru",
                "dt": "t",
                "q": text[:max_chars],
            },
            headers=HEADERS,
            timeout=8,
        )
        response.raise_for_status()
        data = response.json()
        parts = data[0] if isinstance(data, list) and data else []
        translated = "".join(
            str(part[0]) for part in parts
            if isinstance(part, list) and part and part[0]
        ).strip()
        return translated or text
    except Exception as exc:
        logger.debug("Translation failed: %s", exc)
        return text


def translate_event(event: dict) -> dict:
    # Keep venue/city names untouched. Translate human-facing event text.
    event["title"] = translate_to_russian(event.get("title", ""), max_chars=300)
    if event.get("description"):
        event["description"] = translate_to_russian(
            event["description"], max_chars=5000
        )
    return event
