"""Shared date-range parsing for event sources."""

import re
from datetime import datetime

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}

def _date(year: int, month: int, day: int) -> str:
    return f"{year:04d}-{month:02d}-{day:02d}"

def parse_event_dates(text: str, *, default_year: int | None = None) -> tuple[str, str] | None:
    """Parse a single date or an inclusive date range from human/ISO text."""
    if not text:
        return None
    text = str(text).strip().replace("–", "-").replace("—", "-")
    year = default_year or datetime.now().year

    # ISO date/datetime, including explicit ranges.
    iso = re.search(r"(\d{4}-\d{2}-\d{2})(?:T[^\s]+)?\s*(?:-|->|to)\s*(\d{4}-\d{2}-\d{2})", text, re.I)
    if iso:
        return iso.group(1), iso.group(2)
    iso = re.search(r"\b(\d{4}-\d{2}-\d{2})(?:T[^\s]+)?\b", text)
    if iso:
        return iso.group(1), iso.group(1)

    # 2-4 October / October 2-4 / 2 October - 4 October.
    names = "|".join(sorted(MONTHS, key=len, reverse=True))
    m = re.search(rf"\b(\d{{1,2}})\s*-\s*(\d{{1,2}})\s+({names})\b", text, re.I)
    if m:
        month = MONTHS[m.group(3).lower()]
        return _date(year, month, int(m.group(1))), _date(year, month, int(m.group(2)))
    m = re.search(rf"\b({names})\s+(\d{{1,2}})\s*-\s*(\d{{1,2}})\b", text, re.I)
    if m:
        month = MONTHS[m.group(1).lower()]
        return _date(year, month, int(m.group(2))), _date(year, month, int(m.group(3)))
    m = re.search(rf"\b(\d{{1,2}})\s+({names})\s*-\s*(\d{{1,2}})\s+({names})\b", text, re.I)
    if m:
        sm, em = MONTHS[m.group(2).lower()], MONTHS[m.group(4).lower()]
        ey = year + (1 if em < sm else 0)
        return _date(year, sm, int(m.group(1))), _date(ey, em, int(m.group(3)))

    # Numeric ranges such as 02.10-04.10 or 02/10-04/10.
    m = re.search(r"\b(\d{1,2})[./](\d{1,2})\s*-\s*(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?\b", text)
    if m:
        y = int(m.group(5)) if m.group(5) else year
        return _date(y, int(m.group(2)), int(m.group(1))), _date(y, int(m.group(4)), int(m.group(3)))

    # "until 4 October" / "до 4 октября" is treated as a single explicit
    # endpoint here; sources should provide the start date separately when possible.
    m = re.search(rf"\b(?:until|до)\s+(\d{{1,2}})\s+({names})\b", text, re.I)
    if m:
        month = MONTHS[m.group(2).lower()]
        value = _date(year, month, int(m.group(1)))
        return value, value

    # Single named date.
    m = re.search(rf"\b({names})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s*(\d{{4}}))?\b", text, re.I)
    if m:
        y = int(m.group(3)) if m.group(3) else year
        value = _date(y, MONTHS[m.group(1).lower()], int(m.group(2)))
        return value, value
    m = re.search(rf"\b(\d{{1,2}})\s+({names})(?:\s+(\d{{4}}))?\b", text, re.I)
    if m:
        y = int(m.group(3)) if m.group(3) else year
        value = _date(y, MONTHS[m.group(2).lower()], int(m.group(1)))
        return value, value

    return None

def normalize_event_dates(event: dict) -> dict:
    """Ensure every normalized event has a valid inclusive end_date."""
    start = str(event.get("date") or "").strip()
    end = str(event.get("end_date") or "").strip()
    if start:
        parsed_start = parse_event_dates(start)
        if parsed_start:
            start = parsed_start[0]
    if end:
        parsed_end = parse_event_dates(end)
        if parsed_end:
            end = parsed_end[0]
    if start and not end:
        parsed = parse_event_dates(str(event.get("description") or ""))
        if parsed:
            start = start or parsed[0]
            end = parsed[1]
    event["date"] = start
    event["end_date"] = end or start
    return event
