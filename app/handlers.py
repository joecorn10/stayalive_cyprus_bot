"""Telegram update handlers."""

from app.database import init_db, list_sources
from app.keyboards import main_menu

WELCOME_TEXT = (
    "👋 Welcome to Stay Alive Cyprus!\n\n"
    "Events, concerts, exhibitions, parties and other reasons to leave the house.\n\n"
    "Choose what you want to see:"
)
HELP_TEXT = (
    "Use the buttons below to browse Cyprus events.\n\n"
    "Sources and event aggregation will be connected next."
)


def format_sources() -> str:
    sources = list_sources()
    if not sources:
        return (
            "📚 Resources\n\n"
            "No sources yet.\n\n"
            "Use ➕ Add Source to add a website, Telegram, Instagram or Facebook page."
        )
    lines = ["📚 Resources", ""]
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
    if text == "📅 Today":
        return "📅 Today\n\nThe event feed is coming next.", main_menu()
    if text == "🗓 This Week":
        return "🗓 This Week\n\nThe weekly event feed is coming next.", main_menu()
    if text == "📚 Resources":
        return format_sources(), main_menu()
    if text == "➕ Add Source":
        return "➕ Add Source\n\nSend me a URL and I'll add it to the source directory.", main_menu()
    return "I don't know that one yet. Use the buttons below 👇", main_menu()
