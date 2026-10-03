"""Parser for pinned messages in Telegram chats.

The bot must be a member of the chat. Telegram's Bot API exposes the
current pinned message through getChat(chat_id).
"""

import re
from datetime import datetime

import requests

from app.parsers.base import EventParser
from app.parsers.telegram import _event, _extract_event, _extract_price, _infer_category

API_TIMEOUT = 25


class TelegramPinnedParser(EventParser):
    def __init__(self, token: str, chat_id: int, source_url: str):
        self.token = token
        self.chat_id = chat_id
        self.source_url = source_url

    def parse(self) -> list[dict]:
        response = requests.post(
            f"https://api.telegram.org/bot{self.token}/getChat",
            json={"chat_id": self.chat_id},
            timeout=API_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram getChat failed: {data}")

        pinned = (data.get("result") or {}).get("pinned_message")
        if not pinned:
            print(f"Telegram pinned chat {self.chat_id}: no pinned message", flush=True)
            return []

        text = _message_text(pinned)
        if not text:
            return []

        events = _parse_pinned_text(text, self.source_url, pinned)
        print(
            f"Telegram pinned chat {self.chat_id}: {len(events)} events parsed",
            flush=True,
        )
        return events


def _message_text(message: dict) -> str:
    text = message.get("text") or message.get("caption") or ""
    if isinstance(text, str):
        return text.strip()
    return ""


def _parse_pinned_text(text: str, source_url: str, message: dict) -> list[dict]:
    """Extract one or more events from a pinned digest.

    Supports common digest layouts where a date appears on a line and the
    preceding line contains the event title. For a single event, Telegram's
    generic parser is used first.
    """
    generic = _extract_event(text)
    if generic:
        title, date_value, end_date, time_value = generic
        return [_event(
            title[:200],
            text[:4000],
            date_value,
            end_date,
            time_value,
            _find_city(text),
            _infer_category(text),
            _message_url(message, source_url),
            source_url,
            _infer_category(text),
        )]

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    events = []
    pending_title = ""
    for line in lines:
        parsed = _extract_event(line)
        if parsed:
            title, date_value, end_date, time_value = parsed
            if len(title) < 4 or _looks_like_date_only(title):
                title = pending_title
            if len(title) < 4:
                title = f"Telegram event — {datetime.now():%d.%m}"
            events.append(_event(
                title[:200],
                line[:4000],
                date_value,
                end_date,
                time_value,
                _find_city(text),
                _infer_category(text),
                _message_url(message, source_url),
                source_url,
                _infer_category(text),
            ))
            pending_title = ""
        elif not _looks_like_footer(line):
            pending_title = line[:200]

    return _dedupe(events)


def _message_url(message: dict, fallback: str) -> str:
    message_id = message.get("message_id")
    if message_id:
        return f"{fallback.rstrip('/')}/c/{message_id}"
    return fallback


def _find_city(text: str) -> str:
    cities = (
        "Limassol", "Nicosia", "Larnaca", "Paphos", "Ayia Napa",
        "Protaras", "Paralimni", "Famagusta", "Polis", "Latchi", "Troodos",
        "Лимассол", "Никосия", "Ларнака", "Пафос",
    )
    for city in cities:
        if re.search(rf"\b{re.escape(city)}\b", text, re.I):
            return city
    return ""


def _looks_like_date_only(text: str) -> bool:
    value = text.strip()
    return bool(re.fullmatch(r"(?:\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?|\d{1,2}\s+[A-Za-zА-Яа-я]+(?:\s+\d{4})?)", value))


def _looks_like_footer(line: str) -> bool:
    lower = line.casefold()
    return any(marker in lower for marker in ("http://", "https://", "подписывайтесь", "subscribe"))


def _dedupe(events: list[dict]) -> list[dict]:
    unique = []
    seen = set()
    for event in events:
        key = (
            event.get("title", "").casefold().strip(),
            event.get("date", ""),
            event.get("time", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)
    return unique
