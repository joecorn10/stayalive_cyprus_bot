"""Telegram Bot API helpers for scheduled GitHub Actions runs."""
import json
from pathlib import Path
import requests
import sys
from app.handlers import handle_callback, handle_message
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

def send_message(token: str, chat_id: int, text: str, reply_markup: dict | None = None) -> int | None:
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    result = api_call(token, "sendMessage", payload)
    return (result.get("result") or {}).get("message_id")


def edit_message(token: str, chat_id: int, message_id: int, text: str, reply_markup: dict | None = None) -> None:
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    api_call(token, "editMessageText", payload)

def load_offset() -> int | None:
    if not STATE_PATH.exists():
        return None
    return json.loads(STATE_PATH.read_text(encoding="utf-8")).get("offset")

def save_offset(offset: int) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({"offset": offset}, indent=2) + "\n", encoding="utf-8")

def poll_once(token: str) -> bool:
    offset = load_offset()
    payload = {"timeout": 10, "allowed_updates": ["message", "callback_query"]}
    if offset is not None:
        payload["offset"] = offset
    print(f"Telegram poll: offset={offset}, allowed_updates={payload['allowed_updates']}")
    updates = api_call(token, "getUpdates", payload).get("result", [])
    print(f"Telegram poll: received {len(updates)} update(s)")
    if updates:
        print("Telegram update ids:", [update.get("update_id") for update in updates])
    if not updates:
        return False
    latest_offset = offset
    for update in updates:
        latest_offset = update["update_id"] + 1
        callback = update.get("callback_query")
        if callback:
            print(f"Telegram callback: id={callback.get('id')}")
            chat_id, reply_text, keyboard = handle_callback(callback)
            api_call(token, "answerCallbackQuery", {"callback_query_id": callback["id"]})
            if chat_id is not None:
                send_message(token, chat_id, reply_text, keyboard)
            continue

        message = update.get("message")
        if not message:
            print(f"Telegram update {update.get('update_id')} has no message/callback")
            continue
        print(
            f"Telegram message: update_id={update.get('update_id')}, "
            f"chat_id={(message.get('chat') or {}).get('id')}, "
            f"text={message.get('text', '')!r}"
        )
        chat_id = (message.get("chat") or {}).get("id")
        if chat_id is None:
            continue

        text = (message.get("text") or "").strip()
        needs_sync = text in ("📅 Сегодня", "🗓 На этой неделе")

        progress_message_id = None
        if needs_sync:
            progress_message_id = send_message(
                token,
                chat_id,
                "🔎 Ищу свежие события…\n\nПроверяю источники, это займёт несколько секунд.",
            )

        reply_text, keyboard = handle_message(message)

        if needs_sync and progress_message_id is not None:
            try:
                edit_message(token, chat_id, progress_message_id, reply_text, keyboard)
            except Exception as exc:
                print(f"Telegram edit failed, sending result separately: {exc}", file=sys.stderr)
                send_message(token, chat_id, reply_text, keyboard)
        else:
            send_message(token, chat_id, reply_text, keyboard)
    if latest_offset is not None:
        save_offset(latest_offset)
        print(f"Telegram poll: saved offset={latest_offset}")
        return True
    return False

# Diagnostic run trigger.
