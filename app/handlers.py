"""Telegram update handlers."""

from datetime import date, datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from app.config import TIMEZONE
from app.database import (
    add_source,
    database_stats,
    get_chat_state,
    init_db,
    get_event,
    list_events,
    list_event_sources,
    list_recent_events,
    list_sources,
    set_chat_state,
)
from app.keyboards import back_keyboard, category_keyboard, event_keyboard, main_menu
from app.source_detector import detect_source, normalize_url
from app.sync import canonical_category, sync_all

WELCOME_TEXT = (
    "👋 Добро пожаловать в Stay Alive Cyprus!\n\n"
    "Концерты, выставки, вечеринки и другие причины выйти из дома.\n\n"
    "Выбирай, что хочешь посмотреть:"
)
HELP_TEXT = (
    "Используй кнопки ниже, чтобы смотреть события на Кипре.\n\n"
    "Источники уже подключены, сейчас собираю первую ленту."
)

MONTH_NAMES = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


def cyprus_today() -> datetime.date:
    return datetime.now(ZoneInfo(TIMEZONE)).date()


def format_sources() -> str:
    sources = list_sources()
    if not sources:
        return "📚 Источники\n\nПока источников нет."

    lines = ["📚 Источники", ""]
    for source in sources:
        status = "🟢" if source["enabled"] else "⚪"
        lines.append(f"{status} {source['name']} · {source['type']}")
        if source["comment"]:
            lines.append(f"   {source['comment']}")
    return "\n".join(lines)


def _date_label(value: str) -> str:
    date = datetime.fromisoformat(value).date()
    return f"{date.day} {MONTH_NAMES[date.month]}, {WEEKDAYS[date.weekday()]}"


def _event_active_on(event, day: date) -> bool:
    start = datetime.fromisoformat(event["date"]).date()
    end = (
        datetime.fromisoformat(event["end_date"]).date()
        if event["end_date"]
        else start
    )
    return start <= day <= end


def _category_icon(category: str) -> str:
    category = (category or "").lower()
    if "музык" in category or "concert" in category:
        return "🎵"
    if "театр" in category:
        return "🎭"
    if "искус" in category or "art" in category:
        return "🎨"
    if "спорт" in category:
        return "🏃"
    if "фестив" in category:
        return "🎪"
    return "✨"


def format_events(
    title: str,
    events,
    display_date: date | None = None,
) -> tuple[str, dict | None]:
    if not events:
        return f"{title}\n\nПока событий не нашёл. Следующая проверка уже скоро 🔎", None
    counts = {}
    for event in events:
        category = canonical_category(event["category"]) or "✨ Другое"
        counts[category] = counts.get(category, 0) + 1
    categories = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    period = "today" if display_date else "week"
    return (
        f"{title}\n\nВыбери направление — события раскроются отдельным списком 👇",
        category_keyboard(categories, period),
    )

def format_category_events(category: str, events, period: str) -> tuple[str, dict | None]:
    selected = [event for event in events if (canonical_category(event["category"]) or "✨ Другое") == category]
    if not selected:
        return f"{category}\n\nПока событий в этом направлении нет.", back_keyboard(period)
    lines = [f"{category} · {len(selected)}", ""]
    current_day = None
    for event in selected[:30]:
        event_day = datetime.fromisoformat(event["date"]).date()
        day_key = event_day.isoformat()
        if day_key != current_day:
            if current_day is not None:
                lines.append("")
            lines.append(f"📅 {_date_label(event['date'])}")
            lines.append("")
            current_day = day_key
        lines.append(f"• {str(event['title'])}")
        meta = []
        if event["time"]:
            meta.append(f"🕐 {str(event['time'])}")
        if event["venue"]:
            meta.append(f"📍 {str(event['venue'])}")
        elif event["city"]:
            meta.append(f"📍 {str(event['city'])}")
        if event["price"]:
            meta.append(f"💶 {str(event['price'])}")
        if meta:
            lines.append(" · ".join(meta))
        if event["end_date"] and event["end_date"] != event["date"]:
            lines.append(f"↳ до {_date_label(event['end_date'])}")
        lines.append("")
    return "\n".join(lines).rstrip(), event_keyboard(selected[:30], period, category)


def format_event_details(event) -> tuple[str, dict | None]:
    if not event:
        return "Не нашёл это событие. Возможно, оно уже исчезло из источника.", None

    title = escape(str(event["title"]))
    lines = [f"{_category_icon(event['category'])} {title}", ""]
    lines.append(f"📅 {_date_label(event['date'])}")
    if event["end_date"] and event["end_date"] != event["date"]:
        lines.append(f"↳ до {_date_label(event['end_date'])}")
    if event["time"]:
        lines.append(f"🕐 {escape(str(event['time']))}")
    if event["venue"]:
        lines.append(f"📍 {escape(str(event['venue']))}")
    elif event["city"]:
        lines.append(f"📍 {escape(str(event['city']))}")
    if event["price"]:
        lines.append(f"💶 {escape(str(event['price']))}")

    sources = list_event_sources(event["id"])
    if sources:
        names = []
        for source in sources:
            if source["name"] not in names:
                names.append(source["name"])
        lines.append(f"📚 {escape(' · '.join(names))}")

    source_url = str(event["source_url"] or "").strip()
    if source_url:
        lines.append(f'🔗 <a href="{escape(source_url, quote=True)}">Источник события</a>')

    if event["description"]:
        description = " ".join(str(event["description"]).split())
        if len(description) > 1200:
            description = description[:1197].rstrip() + "…"
        lines.extend(["", escape(description)])

    keyboard = None
    if event["ticket_url"]:
        keyboard = {"inline_keyboard": [[{"text": "🎟 Билеты / источник", "url": event["ticket_url"]}]]}
    return "\n".join(lines), keyboard


def format_status() -> str:
    stats = database_stats()
    lines = [
        "🔧 Статус",
        "",
        f"📚 Источники: {stats['sources']} ({stats['enabled_sources']} активных)",
        f"🎫 События в базе: {stats['events']}",
        f"🔮 Будущие события: {stats['upcoming']}",
        f"🕐 Последний event seen: {stats['latest_event_seen']}",
        "",
        "Активные источники:",
    ]
    for source in list_sources():
        if source["enabled"]:
            lines.append(f"🟢 {source['name']}")
    recent = list_recent_events(5)
    if recent:
        lines += ["", "Последние записи:"]
        for event in recent:
            end = event["end_date"] or event["date"]
            date_text = event["date"] if end == event["date"] else f"{event['date']} → {end}"
            lines.append(f"• {date_text} — {event['title']}")
    return "\n".join(lines)


def handle_add_source(chat_id: int, text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "Не вижу URL. Пришли ссылку, например:\nhttps://etkocyprus.com/events"

    url = normalize_url(lines[0])
    if not url:
        return "Похоже, это не URL 🤔\n\nПришли ссылку вида:\nhttps://example.com"

    comment = "\n".join(lines[1:]).strip()
    source = detect_source(url, comment)
    added = add_source(
        source["name"], source["url"], source["type"],
        source["comment"], source["category"], source["city"],
    )
    set_chat_state(chat_id, "idle")

    if not added:
        return f"ℹ️ Этот источник уже есть в каталоге.\n\n🔗 {source['name']}\n{source['url']}"

    details = [
        f"🔗 {source['name']}",
        f"Тип: {source['type']}",
        f"Категория: {source['category']}",
    ]
    if source["city"]:
        details.append(f"📍 {source['city']}")
    details.append("🟢 Мониторинг: включён")
    if source["comment"]:
        details.append(f"\n💬 {source['comment']}")
    return "✅ Источник добавлен\n\n" + "\n".join(details)


def handle_callback(callback: dict) -> tuple[int | None, str, dict | None]:
    data = (callback.get("data") or "").strip()
    message = callback.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    if data.startswith("categories:"):
        period = data.split(":", 1)[1]
        today = cyprus_today()
        end = today if period == "today" else today + timedelta(days=6)
        events = list_events(today.isoformat(), end.isoformat())
        title = "📅 Сегодня" if period == "today" else "🗓 На этой неделе"
        return chat_id, *format_events(title, events, display_date=today if period == "today" else None)

    if data.startswith("category:"):
        parts = data.split(":", 2)
        if len(parts) != 3:
            return chat_id, "Не удалось открыть направление.", None
        period, slug = parts[1], parts[2]
        category_map = {
            "music": "🎵 Музыка",
            "food": "🍷 Еда и вино",
            "art": "🎨 Искусство",
            "nightlife": "🪩 Nightlife",
            "theatre": "🎭 Театр и кино",
            "workshops": "🧑‍🏫 Воркшопы",
            "sport": "🏃 Спорт и outdoor",
            "markets": "🛍 Маркеты и шопинг",
            "family": "👨‍👩‍👧 Семья",
            "festivals": "🎪 Фестивали",
            "other": "✨ Другое",
        }
        category = category_map.get(slug)
        if not category:
            return chat_id, "Неизвестное направление.", None
        today = cyprus_today()
        end = today if period == "today" else today + timedelta(days=6)
        events = list_events(today.isoformat(), end.isoformat())
        return chat_id, *format_category_events(category, events, period)

    if not data.startswith("event:"):
        return chat_id, "Неизвестное действие.", None
    try:
        event_id = int(data.split(":", 1)[1])
    except ValueError:
        return chat_id, "Не удалось открыть событие.", None
    return chat_id, *format_event_details(get_event(event_id))


_SYNC_IN_PROGRESS = False

def handle_message(message: dict) -> tuple[str, dict]:
    init_db()
    text = (message.get("text") or "").strip()
    chat_id = (message.get("chat") or {}).get("id")

    if chat_id is None:
        return "Не удалось определить чат.", main_menu()

    if text in ("/start", "/help"):
        set_chat_state(chat_id, "idle")
        return (WELCOME_TEXT if text == "/start" else HELP_TEXT), main_menu()

    if text == "/status" or text == "🔧 Статус":
        set_chat_state(chat_id, "idle")
        return format_status(), main_menu()

    if text == "/debug":
        set_chat_state(chat_id, "idle")
        return format_status(), main_menu()

    global _SYNC_IN_PROGRESS
    if text == "📅 Сегодня":
        set_chat_state(chat_id, "idle")
        if _SYNC_IN_PROGRESS:
            return "⏳ Я уже обновляю события. Подожди пару секунд и повтори.", main_menu()
        _SYNC_IN_PROGRESS = True
        try:
            print("On-demand event sync: today")
            sync_all()
        finally:
            _SYNC_IN_PROGRESS = False
        today = cyprus_today()
        text, keyboard = format_events(
            "📅 Сегодня",
            list_events(today.isoformat(), today.isoformat()),
            display_date=today,
        )
        return text, keyboard or main_menu()

    if text == "🗓 На этой неделе":
        set_chat_state(chat_id, "idle")
        if _SYNC_IN_PROGRESS:
            return "⏳ Я уже обновляю события. Подожди пару секунд и повтори.", main_menu()
        _SYNC_IN_PROGRESS = True
        try:
            print("On-demand event sync: week")
            sync_all()
        finally:
            _SYNC_IN_PROGRESS = False
        today = cyprus_today()
        end = today + timedelta(days=6)
        text, keyboard = format_events("🗓 На этой неделе", list_events(today.isoformat(), end.isoformat()))
        return text, keyboard or main_menu()

    if text == "📚 Источники":
        set_chat_state(chat_id, "idle")
        return format_sources(), main_menu()

    if text == "➕ Добавить источник":
        set_chat_state(chat_id, "awaiting_source")
        return (
            "➕ Добавить источник\n\n"
            "Отправь URL. Если хочешь, добавь комментарий на следующей строке.\n\n"
            "Например:\n"
            "https://instagram.com/etko_limassol\n"
            "Хорошие концерты и электронная музыка"
        ), main_menu()

    if get_chat_state(chat_id) == "awaiting_source":
        return handle_add_source(chat_id, text), main_menu()

    return "Пока я этого не умею. Используй кнопки ниже 👇", main_menu()
