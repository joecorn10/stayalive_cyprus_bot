"""Lightweight event text translation and Russian event comments."""

import logging
import re

import requests

logger = logging.getLogger(__name__)

URL = "https://translate.googleapis.com/translate_a/single"
HEADERS = {"User-Agent": "StayAliveCyprusBot/1.0"}

_METADATA_TAIL = re.compile(
    r"\s+(?=(?:Location|Tickets?|Register|Registration|More info|Info|Price|"
    r"We meet|Bring|Doors?\s+open|Get your tickets?|Link in bio|"
    r"Локация|Билеты|Регистрация|Подробнее|Цена|Встречаемся)\b)",
    re.I,
)

_BOILERPLATE = re.compile(
    r"(?:https?://\S+|www\.\S+|#\w+|"
    r"tickets?\b|register\b|registration\b|link in bio\b|"
    r"location\b|price\b|doors?\s+open\b|"
    r"билет\w*|регистрац\w*|локаци\w*|подробност\w*)",
    re.I,
)


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
    """Keep the original event language while removing obvious catalogue noise."""
    value = str(title or "").strip()
    if not value:
        return value

    value = re.sub(
        r"^[\s#•·*_~🎉🎶🎵🎧🎸🥳✨🔥📅🪩🎭🎪🏃🍷🎨🛍👨‍👩‍👧]+",
        "",
        value,
    ).strip()
    value = re.sub(
        r"^(?:event|events|what'?s on|upcoming events)\s*[:|—–-]\s*",
        "",
        value,
        flags=re.I,
    )
    value = re.sub(
        r"\s+(?:at|@)\s+[A-Z][A-Za-z0-9 .&'_-]{2,60}$",
        "",
        value,
        flags=re.I,
    )
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

    value = re.split(
        r"\s+(?=(?:Это\s+|В\s+программе\b|Группа\s+|Португальский\s+артист\b|"
        r"Vienna\s+Schoenbrunn\s+Palace\s+Orchestra\b|"
        r"Два\s+вечера\b|На\s+сцене\s+|Гостей\s+жд[её]т\s+|"
        r"В\s+составе\s+дуэта\b))",
        value,
        maxsplit=1,
        flags=re.I,
    )[0].strip()

    if len(value) > 120:
        sentence = re.split(r"(?<=[.!?])\s+", value, maxsplit=1)[0].strip()
        if 8 <= len(sentence) <= 120:
            value = sentence

    value = _METADATA_TAIL.split(value, maxsplit=1)[0].strip()

    if re.match(
        r"^(?:Принесите|Зарегистрироваться|Получить\s+стартовый|"
        r"Location\s*:|Tickets?\s*:|Register\b|Registration\b|"
        r"We\s+meet\b|Bring\s+your\b)",
        value,
        re.I,
    ):
        return "Event"

    value = re.sub(r"\s*[|]\s*", " — ", value)
    value = re.sub(r"\s*[-–—]\s*", " — ", value)
    value = re.sub(r"\s+—\s+", " — ", value)
    value = re.sub(r"(?:\s+—){2,}", " —", value)
    value = re.sub(r"\s+", " ", value).strip(" -–—|•·")
    return value[:200].strip()


def _short_source_description(text: str, max_chars: int = 220) -> str:
    """Extract useful source context without storing the original full caption."""
    value = re.sub(r"https?://\S+|www\.\S+", "", str(text or ""), flags=re.I)
    value = re.sub(r"\s+", " ", value).strip()
    value = _METADATA_TAIL.split(value, maxsplit=1)[0].strip()
    if not value or _BOILERPLATE.fullmatch(value):
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", value)
    useful = []
    for sentence in sentences:
        sentence = sentence.strip(" -–—|•")
        if not sentence:
            continue
        if _BOILERPLATE.search(sentence) and len(sentence) < 70:
            continue
        useful.append(sentence)
        if len(" ".join(useful)) >= max_chars:
            break
    return " ".join(useful)[:max_chars].rstrip(" ,;:-")


def _venue_phrase(event: dict) -> str:
    venue = str(event.get("venue") or "").strip()
    city = str(event.get("city") or "").strip()
    category = str(event.get("category") or "")
    if venue:
        if "Nightlife" in category:
            return f"в клубе {venue}"
        if "Еда и вино" in category:
            return f"в {venue}"
        return f"в {venue}"
    if city:
        return f"в {city}"
    return ""


def build_event_comment(event: dict) -> str:
    """Create a short Russian comment from source context, never from the title.

    The title is an identity-bearing source field and must never be translated
    into the stored description. This keeps the original event wording intact
    and prevents the description from becoming a hidden translation layer for
    deduplication.
    """
    source_description = _short_source_description(event.get("description", ""))
    translated = translate_to_russian(source_description, max_chars=450)
    translated = re.sub(r"\s+", " ", translated).strip()

    venue = _venue_phrase(event)
    if venue and venue.casefold() not in translated.casefold():
        translated = f"{translated} {venue}".strip()

    if len(translated) > 260:
        translated = re.split(r"(?<=[.!?])\s+", translated, maxsplit=1)[0].strip()
    return translated[:280].rstrip()


def translate_event(event: dict) -> dict:
    # IMPORTANT: title remains in the source language. Only the short comment
    # in description is Russian.
    event["title"] = normalize_event_title(event.get("title", ""))
    event["description"] = build_event_comment(event)
    return event
