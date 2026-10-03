"""Telegram update handlers."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import TIMEZONE
from app.database import (
    add_source,
    database_stats,
    get_chat_state,
    init_db,
    list_events,
    list_recent_events,
    list_sources,
    set_chat_state,
)
from app.keyboards import main_menu
from app.source_detector import detect_source, normalize_url

WELCOME_TEXT = (
    "👋 Добро пожаловать в Stay Alive Cyprus!\n\n"
    "Концерты, выставки, вечеринки и другие причины выйти из дома.\n\n"
    "Выбирай, что хочешь посмотреть:"
)
HELP_TEXT = (
    "Используй кнопки ниже, чтобы смотреть события на Кипре.\n\n"
    "Источники уже подключены, сейчас собираю первую ленту."
)


def cyprus_today() -> datetime.date:
    return datetime.now(ZoneInfo(TIMEZONE)).date()


def format_sources() -> str:
    sources = list_sources()
    if not sources:
        return "📚 Источники\n\nПока источников нет."

    lines = ["📚 Источники", ""]
    for source in sources:
        status = "🟢" if source["enabled"] else "⚪"
        lines.append(f"{status} {source['name']} — {source['type']}")
        details = []
        if source["category"]:
            details.append(source["category"])
        if source["city"]:
            details.append(source["city"])
        if details:
            lines.append(f"   {' · '.join(details)}")
        if source["comment"]:
            lines.append(f"   {source['comment']}")
    return "\n".join(lines)


def format_events(title: str, events) -> str:
    if not events:
        return f"{title}\n\nПока событий не нашёл. Следующая проверка уже скоро 🔎"

    lines = [title, ""]
    for event in events[:30]:
        lines.append(f"🎵 {event['title']}")
        event_date = event["date"]
        if event["end_date"] and event["end_date"] != event["date"]:
            event_date = f"{event['date']} → {event['end_date']}"
        details = [f"📅 {event_date}"]
        if event["time"]:
            details.append(f"🕘 {event['time']}")
        if event["venue"]:
            details.append(f"📍 {event['venue']}")
        elif event["city"]:
            details.append(f"📍 {event['city']}")
        if event["price"]:
            details.append(f"💶 {event['price']}")
        lines.append(" · ".join(details))
        if event["ticket_url"]:
            lines.append(f"🔗 {event['ticket_url']}")
        lines.append("")
    return "\n".join(lines).strip()


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
        "Источник:",
        "🟢 ETKO — парсер подключён",
    ]
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

    if text == "📅 Сегодня":
        set_chat_state(chat_id, "idle")
        today = cyprus_today()
        return format_events("📅 Сегодня", list_events(today.isoformat(), today.isoformat())), main_menu()

    if text == "🗓 На этой неделе":
        set_chat_state(chat_id, "idle")
        today = cyprus_today()
        end = today + timedelta(days=6)
        return format_events("🗓 На этой неделе", list_events(today.isoformat(), end.isoformat())), main_menu()

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
