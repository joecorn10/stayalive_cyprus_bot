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
    if not response.ok:
        try:
            details = response.json()
        except ValueError:
            details = response.text
        raise RuntimeError(
            f"Telegram API HTTP {response.status_code} for {method}: {details}"
        )
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error for {method}: {data}")
    return data


def send_message(
    token: str,
    chat_id: int,
    text: str,
    reply_markup: dict | None = None,
    parse_mode: str | None = "HTML",
) -> int | None:
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup
    result = api_call(token, "sendMessage", payload)
    return (result.get("result") or {}).get("message_id")


def edit_message(
    token: str,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: dict | None = None,
    parse_mode: str | None = "HTML",
) -> None:
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
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


def telegram_diagnostics(token: str) -> None:
    me = api_call(token, "getMe").get("result", {})
    webhook = api_call(token, "getWebhookInfo").get("result", {})
    print(
        "Telegram diagnostics: "
        f"bot=@{me.get('username')} id={me.get('id')} "
        f"webhook_url={webhook.get('url')!r} "
        f"pending={webhook.get('pending_update_count', 0)} "
        f"last_error={webhook.get('last_error_message')!r}"
    )


def poll_once(token: str) -> bool:
    telegram_diagnostics(token)
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
                parse_mode=None,
            )

        reply_text, keyboard = handle_message(message)

        if needs_sync and progress_message_id is not None:
            try:
                edit_message(
                    token,
                    chat_id,
                    progress_message_id,
                    reply_text,
                    parse_mode=None,
                )
            except Exception as exc:
                print(
                    f"Telegram edit failed, sending result separately: {exc}",
                    file=sys.stderr,
                )
                try:
                    send_message(
                        token,
                        chat_id,
                        reply_text,
                        keyboard,
                        parse_mode=None,
                    )
                except Exception as send_exc:
                    print(
                        f"Telegram fallback send failed: {send_exc}",
                        file=sys.stderr,
                    )
        else:
            send_message(token, chat_id, reply_text, keyboard)
    if latest_offset is not None:
        save_offset(latest_offset)
        print(f"Telegram poll: saved offset={latest_offset}")
        return True
    return False

# Diagnostic run trigger.
