"""Telegram update handlers."""

from app.database import (
    add_source,
    get_chat_state,
    init_db,
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
    "Каталог источников и сбор событий скоро подключим."
)


def format_sources() -> str:
    sources = list_sources()
    if not sources:
        return (
            "📚 Источники\n\n"
            "Пока источников нет.\n\n"
            "Используй ➕ Добавить источник, чтобы добавить сайт, Telegram, Instagram или Facebook."
        )

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


def handle_add_source(chat_id: int, text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "Не вижу URL. Пришли ссылку, например:\nhttps://etkocyprus.com/events"

    url = normalize_url(lines[0])
    if not url:
        return (
            "Похоже, это не URL 🤔\n\n"
            "Пришли ссылку вида:\n"
            "https://example.com"
        )

    comment = "\n".join(lines[1:]).strip()
    source = detect_source(url, comment)
    added = add_source(
        source["name"],
        source["url"],
        source["type"],
        source["comment"],
        source["category"],
        source["city"],
    )
    set_chat_state(chat_id, "idle")

    if not added:
        return (
            "ℹ️ Этот источник уже есть в каталоге.\n\n"
            f"🔗 {source['name']}\n"
            f"{source['url']}"
        )

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

    if text == "📅 Сегодня":
        set_chat_state(chat_id, "idle")
        return "📅 Сегодня\n\nЛента событий скоро появится.", main_menu()

    if text == "🗓 На этой неделе":
        set_chat_state(chat_id, "idle")
        return "🗓 На этой неделе\n\nНедельная лента событий скоро появится.", main_menu()

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
