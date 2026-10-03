"""Telegram update handlers."""

from app.database import init_db, list_sources
from app.keyboards import main_menu

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
        if source["comment"]:
            lines.append(f"   {source['comment']}")
    return "\n".join(lines)


def handle_message(message: dict) -> tuple[str, dict]:
    init_db()
    text = (message.get("text") or "").strip()

    if text in ("/start", "/help"):
        return (WELCOME_TEXT if text == "/start" else HELP_TEXT), main_menu()
    if text == "📅 Сегодня":
        return "📅 Сегодня\n\nЛента событий скоро появится.", main_menu()
    if text == "🗓 На этой неделе":
        return "🗓 На этой неделе\n\nНедельная лента событий скоро появится.", main_menu()
    if text == "📚 Источники":
        return format_sources(), main_menu()
    if text == "➕ Добавить источник":
        return "➕ Добавить источник\n\nОтправь мне URL, и я добавлю его в каталог источников.", main_menu()
    return "Пока я этого не умею. Используй кнопки ниже 👇", main_menu()
