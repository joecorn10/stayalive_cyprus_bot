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

    # Strip poster/catalogue decoration and metadata that should never become
    # the event name.
    value = re.sub(r"^[\\s#•·*_~🎉🎶🎵🎧🎸🥳✨🔥📅🪩🎭🎪🏃🍷🎨🛍👨‍👩‍👧]+", "", value).strip()
    value = re.sub(r"^(?:event|events|what'?s on|upcoming events)\\s*[:|—–-]\\s*", "", value, flags=re.I)
    value = re.sub(r"\\s+(?:at|@)\\s+[A-Z][A-Za-z0-9 .&'_-]{2,60}$", "", value, flags=re.I)

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

    # Some aggregators append the description directly to the title without
    # punctuation. Cut common description lead-ins before doing dedupe.
    value = re.split(
        r"\s+(?=(?:Это\s+|В\s+программе\b|Группа\s+|Португальский\s+артист\b|"
        r"Vienna\s+Schoenbrunn\s+Palace\s+Orchestra\b|"
        r"Два\s+вечера\b|На\s+сцене\s+|Гостей\s+жд[её]т\s+|"
        r"В\s+составе\s+дуэта\b))",
        value,
        maxsplit=1,
        flags=re.I,
    )[0].strip()

    # If a long title is actually a sentence-like description, keep its first
    # sentence rather than polluting the event catalogue.
    if len(value) > 120:
        sentence = re.split(r"(?<=[.!?])\s+", value, maxsplit=1)[0].strip()
        if 8 <= len(sentence) <= 120:
            value = sentence

    # Remove obvious description/metadata tails that have leaked into titles.
    value = re.split(
        r"\s+(?=(?:Location|Tickets?|Register|Registration|More info|Info|Price|"
        r"We meet|Bring|Doors?\s+open|Это|Группа|В программе|Гостей\s+жд|"
        r"Два\s+вечера|В\s+составе|Зарегистрироваться|Получить\s+стартовый\s+пакет)\b)",
        value,
        maxsplit=1,
        flags=re.I,
    )[0].strip()

    # A caption that begins with instructions is not a useful event title.
    if re.match(
        r"^(?:Принесите|Зарегистрироваться|Получить\s+стартовый|"
        r"Location\s*:|Tickets?\s*:|Register\b|Registration\b|"
        r"We\s+meet\b|Bring\s+your\b)",
        value,
        re.I,
    ):
        return "Event"

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
