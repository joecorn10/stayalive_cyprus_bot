"""Telegram inline keyboards."""

def main_menu(input_field_placeholder: str = "Выбери действие…") -> dict:
    return {
        "inline_keyboard": [
            [{"text": "📅 Сегодня", "callback_data": "main:today"}, {"text": "🗓 На этой неделе", "callback_data": "main:week"}],
            [{"text": "📚 Источники", "callback_data": "main:sources"}, {"text": "➕ Добавить источник", "callback_data": "main:add"}],
        ]
    }

def category_slug(category: str) -> str:
    mapping = {
        "🎵 Музыка": "music", "🎭 Comedy": "comedy", "🍷 Еда и вино": "food",
        "Еда и напитки": "food", "Еда и напиток": "food", "🍷 Еда и напитки": "food",
        "🎨 Искусство": "art", "🪩 Nightlife": "nightlife", "🎭 Театр и кино": "theatre",
        "🧑‍🏫 Воркшопы": "workshops", "🏃 Спорт и outdoor": "sport",
        "🛍 Маркеты и шопинг": "markets", "👨‍👩‍👧 Семья": "family",
        "🎪 Фестивали": "festivals", "✨ Другое": "other",
    }
    return mapping.get(category, "other")

def category_keyboard(categories: list[tuple[str, int]], period: str) -> dict:
    return {"inline_keyboard": [[{"text": f"{category} · {count}", "callback_data": f"category:{period}:{category_slug(category)}"}] for category, count in categories] + [[{"text": "← Главное меню", "callback_data": "main:menu"}]]}

def event_keyboard(events: list, period: str, category: str) -> dict:
    return {"inline_keyboard": [[{"text": str(event["title"])[:60], "callback_data": f"event:{event['id']}"}] for event in events] + [[{"text": "← Все направления", "callback_data": f"categories:{period}"}], [{"text": "← Главное меню", "callback_data": "main:menu"}]]}

def back_keyboard(period: str) -> dict:
    return {"inline_keyboard": [[{"text": "← Все направления", "callback_data": f"categories:{period}"}], [{"text": "← Главное меню", "callback_data": "main:menu"}]]}
