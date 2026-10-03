"""Telegram reply keyboards."""


def main_menu() -> dict:
    return {
        "keyboard": [
            [{"text": "📅 Today"}, {"text": "🗓 This Week"}],
            [{"text": "📚 Resources"}, {"text": "➕ Add Source"}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }
