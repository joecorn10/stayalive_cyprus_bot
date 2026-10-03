"""Parser for public Telegram channel previews (t.me/s/...)."""

import re
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from app.parsers.base import EventParser

HEADERS = {"User-Agent": "StayAliveCyprusBot/1.0"}
MONTHS_RU = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}
MONTHS_EN = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}
CYPROPLAN_CITIES = (
    "Никосия", "Лимасол", "Ларнака", "Пафос", "Паралимни",
    "Протарас", "Айя-Напа", "Троодос", "Платрес", "Корнос",
    "Силику", "Аналионтас", "Потамиу", "Махерас",
)


class TelegramParser(EventParser):
    def __init__(self, url: str):
        self.url = url
        parsed = urlparse(url)
        self.channel = parsed.path.strip("/").split("/")[-1]

    def parse(self) -> list[dict]:
        if not self.channel or self.channel.startswith("+"):
            return []

        preview_url = f"https://t.me/s/{self.channel}"
        response = requests.get(preview_url, timeout=20, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        if self.channel.lower() == "cyproplan":
            return _parse_cyproplan(soup, self.url)

        return _parse_generic(soup, self.url)


def _parse_generic(soup: BeautifulSoup, source_url: str) -> list[dict]:
    events = []
    for message in soup.select(".tgme_widget_message"):
        body = message.select_one(".tgme_widget_message_text")
        if not body:
            continue
        text = " ".join(body.stripped_strings)
        parsed = _extract_event(text)
        if not parsed:
            continue
        title, date_value, end_date, time_value = parsed
        link = message.select_one(".tgme_widget_message_date")
        message_url = link.get("href", source_url) if link else source_url
        events.append(_event(
            title, text, date_value, end_date, time_value, "", "",
            message_url, source_url, "События",
        ))
    return events


def _parse_cyproplan(soup: BeautifulSoup, source_url: str) -> list[dict]:
    """Parse Cyproplan digest posts into one event per dated item.

    Cyproplan commonly publishes several events in a single Telegram post.
    The date may be on the same line as the title or on a separate line, so
    parsing is deliberately stateful rather than assuming one event == one line.
    """
    events = []
    seen = set()

    for message in soup.select(".tgme_widget_message"):
        body = message.select_one(".tgme_widget_message_text")
        if not body:
            continue

        lines = [line.strip() for line in body.get_text("\n").splitlines() if line.strip()]
        current_city = ""
        pending_url = ""
        last_candidate_lines: list[str] = []

        for index, line in enumerate(lines):
            if line.startswith("🇨🇾") or "Команда Cyproplan" in line:
                continue

            city = _cyproplan_city(line)
            if city is not None:
                current_city = city
                last_candidate_lines = []
                continue

            urls = re.findall(r"https?://[^\s)]+", line)
            if urls:
                pending_url = urls[0].rstrip(".,")
                # A URL can be attached to the event on the same line.
                if not _cyproplan_dates(line):
                    continue

            date_match = _cyproplan_dates(line)
            if not date_match:
                if not urls and not _looks_like_footer(line):
                    last_candidate_lines.append(line)
                    last_candidate_lines = last_candidate_lines[-3:]
                continue

            date_value, end_date = date_match

            # First try title + date on the same line.
            title = _clean_title(line)
            inline_title, inline_url = _cyproplan_title_and_url(body, line)
            if len(inline_title) > len(title):
                title = inline_title
            event_url = inline_url

            # If the date is on a standalone line, use the nearest preceding
            # meaningful line as the title. This is common in Cyproplan digests.
            if len(title) < 4 or _looks_like_date_only(title):
                for previous in reversed(last_candidate_lines):
                    candidate = _clean_title(previous)
                    if len(candidate) >= 4 and not _looks_like_date_only(candidate):
                        title = candidate
                        break

            # If the URL is on a separate line immediately before the date,
            # keep it attached to this event.
            event_url = event_url or pending_url or _message_url(message, source_url)
            pending_url = ""

            if not title or len(title) < 4 or _looks_like_date_only(title):
                last_candidate_lines = []
                continue

            time_value = _extract_time_range(line)
            description_lines = []
            for candidate in (line, *last_candidate_lines[-2:]):
                if candidate not in description_lines:
                    description_lines.append(candidate)
            description = " · ".join(description_lines)

            key = (
                re.sub(r"\s+", " ", title.lower()).strip(),
                date_value,
                end_date,
                current_city.lower(),
            )
            if key in seen:
                last_candidate_lines = []
                continue
            seen.add(key)

            events.append(_event(
                title[:200],
                description,
                date_value,
                end_date,
                time_value,
                current_city,
                _infer_category(description),
                event_url,
                source_url,
                _infer_category(description),
            ))
            last_candidate_lines = []

    return events


def _cyproplan_city(line: str) -> str | None:
    normalized = line.strip()
    if normalized == "Другие локации":
        return ""
    for city in CYPROPLAN_CITIES:
        if normalized.casefold() == city.casefold():
            return city
    return None


def _looks_like_footer(line: str) -> bool:
    lower = line.casefold()
    return any(marker in lower for marker in (
        "команда cyproplan",
        "подписывайтесь",
        "cyproplan.com",
        "instagram.com/cyproplan",
    ))


def _looks_like_date_only(text: str) -> bool:
    value = text.strip()
    return bool(_cyproplan_dates(value)) and len(re.sub(r"\d|[.\-–—:/ ]", "", value)) < 18


def _cyproplan_title_and_url(body, line: str) -> tuple[str, str]:
    event_url = ""
    for anchor in body.find_all("a", href=True):
        label = " ".join(anchor.stripped_strings)
        if label and label in line:
            event_url = anchor["href"]
            break
    return _clean_title(line), event_url


def _clean_title(line: str) -> str:
    text = line
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(
        r"\s*(?:до\s+)?\d{1,2}(?:\s*[-–]\s*\d{1,2})?\s+"
        r"(?:января|февраля|марта|апреля|мая|июня|июля|августа|"
        r"сентября|октября|ноября|декабря)\b.*$",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"\s*\b(?:\d{1,2}:\d{2})(?:\s*[-–]\s*\d{1,2}:\d{2})?\b.*$", "", text)
    text = re.sub(r"\s+", " ", text).strip(" .,:—-")
    text = re.sub(r"^[^\wА-Яа-яЁё]+", "", text)
    return text


def _cyproplan_dates(text: str):
    normalized = text.replace("–", "-").replace("—", "-")
    month_pattern = (
        r"(января|февраля|марта|апреля|мая|июня|июля|августа|"
        r"сентября|октября|ноября|декабря)"
    )

    # 26 сентября - 4 октября
    match = re.search(
        rf"(\d{{1,2}})\s+{month_pattern}\s*(?:,?[^0-9\n]{{0,25}}?)?"
        rf"(?:-|по)\s*(\d{{1,2}})\s+{month_pattern}",
        normalized,
        re.I,
    )
    if match:
        start_day, start_month = int(match.group(1)), MONTHS_RU[match.group(2).lower()]
        end_day, end_month = int(match.group(3)), MONTHS_RU[match.group(4).lower()]
        year = datetime.now().year
        start_year = year
        end_year = year + (1 if end_month < start_month else 0)
        return (
            f"{start_year:04d}-{start_month:02d}-{start_day:02d}",
            f"{end_year:04d}-{end_month:02d}-{end_day:02d}",
        )

    # 2-4 октября / 3-4 октября
    match = re.search(rf"(\d{{1,2}})\s*[-–]\s*(\d{{1,2}})\s+{month_pattern}", normalized, re.I)
    if match:
        month = MONTHS_RU[match.group(3).lower()]
        year = datetime.now().year
        return (
            f"{year:04d}-{month:02d}-{int(match.group(1)):02d}",
            f"{year:04d}-{month:02d}-{int(match.group(2)):02d}",
        )

    # до 15 октября
    match = re.search(rf"до\s+(\d{{1,2}})\s+{month_pattern}", normalized, re.I)
    if match:
        month = MONTHS_RU[match.group(2).lower()]
        year = datetime.now().year
        return (f"{year:04d}-{month:02d}-{int(match.group(1)):02d}", f"{year:04d}-{month:02d}-{int(match.group(1)):02d}")

    # 2 октября
    match = re.search(rf"\b(\d{{1,2}})\s+{month_pattern}", normalized, re.I)
    if match:
        month = MONTHS_RU[match.group(2).lower()]
        year = datetime.now().year
        day = int(match.group(1))
        return (f"{year:04d}-{month:02d}-{day:02d}", f"{year:04d}-{month:02d}-{day:02d}")

    return None


def _extract_time_range(text: str) -> str:
    match = re.search(
        r"\b([01]?\d|2[0-3]):([0-5]\d)(?:\s*[-–]\s*([01]?\d|2[0-3]):([0-5]\d))?",
        text,
    )
    if not match:
        return ""
    start = f"{int(match.group(1)):02d}:{match.group(2)}"
    if not match.group(3):
        return start
    return f"{start}-{int(match.group(3)):02d}:{match.group(4)}"


def _message_url(message, source_url: str) -> str:
    link = message.select_one(".tgme_widget_message_date")
    return link.get("href", source_url) if link else source_url


def _event(title, description, date_value, end_date, time_value, city, category, ticket_url, source_url, fallback_category):
    return {
        "title": title,
        "description": description,
        "date": date_value,
        "end_date": end_date,
        "time": time_value,
        "venue": "",
        "city": city,
        "price": _extract_price(description),
        "ticket_url": ticket_url,
        "source_url": ticket_url,
        "image_url": "",
        "category": category or fallback_category,
    }


def _extract_event(text: str):
    now = datetime.now()
    match = re.search(r"\b(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?\b", text)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        year = int(match.group(3) or now.year)
        if year < 100:
            year += 2000
        if 1 <= month <= 12 and 1 <= day <= 31:
            date_value = f"{year:04d}-{month:02d}-{day:02d}"
        else:
            return None
    else:
        match = re.search(r"\b(\d{1,2})\s+([А-Яа-я]+|[A-Za-z]+)(?:\s+(\d{4}))?", text)
        if not match:
            return None
        month = MONTHS_RU.get(match.group(2).lower()) or MONTHS_EN.get(match.group(2).lower())
        if not month:
            return None
        year = int(match.group(3) or now.year)
        date_value = f"{year:04d}-{month:02d}-{int(match.group(1)):02d}"
    time_match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
    time_value = f"{int(time_match.group(1)):02d}:{time_match.group(2)}" if time_match else ""
    title = re.split(r"\b(?:\d{1,2}[./-]\d{1,2}|\d{1,2}\s+[А-Яа-я]+|\d{1,2}\s+[A-Za-z]+)\b", text, maxsplit=1)[0].strip(" —:-")
    if len(title) < 4:
        title = text[:120]
    return title, date_value, date_value, time_value


def _extract_price(text: str) -> str:
    match = re.search(r"(?:€|EUR)\s*\d+(?:[.,]\d+)?", text, re.I)
    return match.group(0) if match else ""


def _infer_category(text: str) -> str:
    lower = text.lower()
    if any(x in lower for x in ("concert", "концерт", "джаз", "soul", "music", "музык")):
        return "Музыка"
    if any(x in lower for x in ("театр", "спектакл", "comedy", "комеди")):
        return "Театр"
    if any(x in lower for x in ("выстав", "art ", "арт-", "галере")):
        return "Искусство"
    if any(x in lower for x in ("фестиваль", "festival", "comic con")):
        return "Фестиваль"
    if any(x in lower for x in ("wine", "вино", "пив", "beer", "гастроном")):
        return "Еда и напитки"
    if any(x in lower for x in ("турнир", "забег", "спорт", "теннис")):
        return "Спорт"
    if any(x in lower for x in ("детск", "детский")):
        return "Для детей"
    return "События"
