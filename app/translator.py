""""Lightweight event text translation to Russian."""

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


def normalize_event_title(title: str) -> str:
    """Turn scraped titles into concise, human-readable event names."""
    value = str(title or "").strip()
    if not value:
        return value

    # Remove common catalogue noise while preserving the actual event name.
    value = re.sub(
        r"^(?:event|events|cyprus underground|cyprus events)\s*[:|—–-]\s*",
        "",
        value,
        flags=re.I,
    )
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s*\|\s*", " — ", value)
    value = re.sub(r"\s+[–—-]\s*$", "", value)
    value = value.strip(" -–—|•·")
    value = re.sub(r"([!?.,:;]){2,}", r"\1", value)

    # Some aggregators incorrectly expose the first part of the description
    # as the event name. Keep legitimate titles intact, but cut obvious
    # sentence-like catalogue blobs at the first sentence boundary.
    if len(value) > 120:
        sentence = re.split(r"(?<=[.!?])\s+", value, maxsplit=1)[0].strip()
        if 8 <= len(sentence) <= 120:
            value = sentence

    # Normalize separators so equivalent titles from different sources hash
    # to the same event identity.
    value = re.sub(r"\s*[|]\s*", " — ", value)
    value = re.sub(r"\s*[-–—]\s*", " — ", value)
    value = re.sub(r"\s+—\s+", " — ", value)
    value = re.sub(r"(?:\s+—){2,}", " —", value)
    value = re.sub(r"\s+", " ", value).strip(" -–—|•·")
    return value[:200].strip()


def translate_event(event: dict) -> dict:
    # Keep event titles, venue names, city names and brands in their original form.
    event["title"] = normalize_event_title(event.get("title", ""))
    if event.get("description"):
        event["description"] = translate_to_russian(
            event["description"], max_chars=5000
        )
    return event
