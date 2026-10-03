"""Telegram Bot API helpers for scheduled GitHub Actions runs."""
import json
from pathlib import Path
import requests
from app.handlers import handle_message
API_TIMEOUT = 35
STATE_PATH = Path("data/telegram_offset.json")

def api_call(token: str, method: str, payload: dict | None = None) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    response = requests.post(url, json=payload or {}, timeout=API_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error: {data}")
    return data

def send_message(token: str, chat_id: int, text: str, reply_markup: dict | None = None) -> None:
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    api_call(token, "sendMessage", payload)

def load_offset() -> int | None:
    if not STATE_PATH.exists():
        return None
    return json.loads(STATE_PATH.read_text(encoding="utf-8")).get("offset")

def save_offset(offset: int) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({"offset": offset}, indent=2) + "\n", encoding="utf-8")

def poll_once(token: str) -> bool:
    offset = load_offset()
    payload = {"timeout": 10, "allowed_updates": ["message"]}
    if offset is not None:
        payload["offset"] = offset
    updates = api_call(token, "getUpdates", payload).get("result", [])
    if not updates:
        return False
    latest_offset = offset
    for update in updates:
        latest_offset = update["update_id"] + 1
        message = update.get("message")
        if not message:
            continue
        chat_id = (message.get("chat") or {}).get("id")
        if chat_id is None:
            continue
        reply_text, keyboard = handle_message(message)
        send_message(token, chat_id, reply_text, keyboard)
    if latest_offset is not None:
        save_offset(latest_offset)
        return True
    return False
