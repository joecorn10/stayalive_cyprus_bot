"""Telegram reply keyboards."""


def main_menu() -> dict:
    return {
        "keyboard": [
            [{"text": "📅 Сегодня"}, {"text": "🗓 На этой неделе"}],
            [{"text": "📚 Источники"}, {"text": "➕ Добавить источник"}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }
