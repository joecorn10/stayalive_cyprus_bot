"""Minimal Telegram Bot API client and long-polling loop."""

import time

import requests

from app.handlers import handle_message


API_TIMEOUT = 35
POLL_TIMEOUT = 30
RETRY_DELAY = 5


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


def run_polling(token: str) -> None:
    offset = None
    print("Stay Alive Cyprus Bot is running…")

    while True:
        try:
            payload = {
                "timeout": POLL_TIMEOUT,
                "allowed_updates": ["message"],
            }
            if offset is not None:
                payload["offset"] = offset

            result = api_call(token, "getUpdates", payload)

            for update in result.get("result", []):
                offset = update["update_id"] + 1
                message = update.get("message")
                if not message:
                    continue

                chat = message.get("chat") or {}
                chat_id = chat.get("id")
                if chat_id is None:
                    continue

                reply_text, keyboard = handle_message(message)
                send_message(token, chat_id, reply_text, keyboard)

        except requests.RequestException as exc:
            print(f"Telegram network error: {exc}")
            time.sleep(RETRY_DELAY)
        except Exception as exc:
            print(f"Bot error: {exc}")
            time.sleep(RETRY_DELAY)
