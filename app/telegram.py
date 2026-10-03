"""Telegram Bot API helpers for scheduled GitHub Actions runs."""
import json
from pathlib import Path
import requests
import sys
from app.handlers import handle_callback, handle_message
from app.database import get_source_by_url, update_source_comment
from app.sync import sync_pinned_telegram_chat

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
    # Keep inline links clickable, but never generate webpage previews.
    payload["link_preview_options"] = {"is_disabled": True}
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
    # Keep inline links clickable, but never generate webpage previews.
    payload["link_preview_options"] = {"is_disabled": True}
    api_call(token, "editMessageText", payload)


def delete_message(token: str, chat_id: int, message_id: int) -> None:
    api_call(
        token,
        "deleteMessage",
        {"chat_id": chat_id, "message_id": message_id},
    )


def load_offset() -> int | None:
    if not STATE_PATH.exists():
        return None
    return json.loads(STATE_PATH.read_text(encoding="utf-8")).get("offset")


def save_offset(offset: int) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({"offset": offset}, indent=2) + "\n", encoding="utf-8")


def configure_telegram_menu(token: str) -> None:
    """Configure Telegram's visible command menu for an empty/new chat."""
    api_call(
        token,
        "setMyCommands",
        {
            "commands": [
                {"command": "start", "description": "Открыть Stay Alive Cyprus"},
                {"command": "today", "description": "События сегодня"},
                {"command": "week", "description": "События на этой неделе"},
                {"command": "sources", "description": "Источники"},
                {"command": "add", "description": "Добавить источник"},
                {"command": "status", "description": "Статус бота"},
            ]
        },
    )
    api_call(
        token,
        "setChatMenuButton",
        {"menu_button": {"type": "commands"}},
    )
    print("Telegram menu configured.")


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
            callback_id = callback.get("id")
            data = (callback.get("data") or "").strip()
            message = callback.get("message") or {}
            callback_chat_id = (message.get("chat") or {}).get("id")
            message_id = message.get("message_id")
            print(
                "Telegram callback: "
                f"id={callback_id} chat_id={callback_chat_id} "
                f"message_id={message_id} data={data!r}"
            )
            try:
                chat_id, reply_text, keyboard = handle_callback(callback)
                api_call(
                    token,
                    "answerCallbackQuery",
                    {"callback_query_id": callback_id},
                )
                if chat_id is not None:
                    if message_id is not None:
                        try:
                            edit_message(
                                token,
                                chat_id,
                                message_id,
                                reply_text,
                                keyboard,
                            )
                            print(
                                "Telegram callback handled by editing message: "
                                f"chat_id={chat_id} message_id={message_id}"
                            )
                        except Exception as edit_exc:
                            print(
                                f"Telegram callback edit failed: {edit_exc}",
                                file=sys.stderr,
                            )
                            # If Telegram rejects an edit for an old message,
                            # fall back to a clean replacement.
                            try:
                                delete_message(token, chat_id, message_id)
                            except Exception as delete_exc:
                                print(
                                    f"Telegram callback stale-message delete failed: {delete_exc}",
                                    file=sys.stderr,
                                )
                            send_message(token, chat_id, reply_text, keyboard)
                    else:
                        send_message(token, chat_id, reply_text, keyboard)
            except Exception as exc:
                print(
                    f"Telegram callback failed for data={data!r}: {exc}",
                    file=sys.stderr,
                )
                try:
                    api_call(
                        token,
                        "answerCallbackQuery",
                        {
                            "callback_query_id": callback_id,
                            "text": "Не удалось открыть. Попробуй ещё раз.",
                        },
                    )
                except Exception:
                    pass
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
        if text.split("@", 1)[0] == "/pins" and (message.get("chat") or {}).get("type") in ("group", "supergroup"):
            source_url = "https://t.me/+0C0Mu-Xz4HAxMGNi"
            source = get_source_by_url(source_url)
            if not source:
                send_message(token, chat_id, "Источник закрепов не найден в базе.", parse_mode=None)
                continue

            comment = source["comment"] or ""
            import re
            if re.search(r"chat_id=-?\\d+", comment):
                comment = re.sub(r"chat_id=-?\\d+", f"chat_id={chat_id}", comment)
            else:
                comment = f"{comment}; chat_id={chat_id}"
            update_source_comment(source_url, comment)

            try:
                added = sync_pinned_telegram_chat(token, chat_id, source_url)
                send_message(
                    token,
                    chat_id,
                    f"📌 Закреп проверен. Новых событий: {added}.\\n\\nТеперь этот чат можно обновлять автоматически.",
                    parse_mode=None,
                )
            except Exception as exc:
                send_message(
                    token,
                    chat_id,
                    f"❌ Не удалось прочитать закреп: {exc}",
                    parse_mode=None,
                )
            continue

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
                    keyboard,
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
