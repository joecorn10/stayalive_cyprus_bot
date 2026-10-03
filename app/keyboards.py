"""Telegram reply and inline keyboards."""

def main_menu() -> dict:
    return {
        "keyboard": [
            [{"text": "📅 Сегодня"}, {"text": "🗓 На этой неделе"}],
            [{"text": "📚 Источники"}, {"text": "➕ Добавить источник"}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }

def category_keyboard(categories: list[tuple[str, int]], period: str) -> dict:
    return {"inline_keyboard": [[{
        "text": f"{category} · {count}",
        "callback_data": f"category:{period}:{category}",
    }] for category, count in categories]}

def back_keyboard(period: str) -> dict:
    return {"inline_keyboard": [[{
        "text": "← Все направления",
        "callback_data": f"categories:{period}",
    }]]}
