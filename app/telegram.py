"""Telegram Bot API helpers for scheduled GitHub Actions runs."""
import json
from pathlib import Path
import requests
import sys
from app.handlers import handle_callback, handle_message
from app.database import get_chat_state, get_source_by_url, update_source_comment
from app.source_detector import normalize_url
from app.sync import sync_all, sync_pinned_telegram_chat, sync_source_by_url

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
    """Configure the bot profile while keeping the persistent reply keyboard as navigation."""
    api_call(
        token,
        "setMyDescription",
        {
            "description": (
                "👋 Добро пожаловать в Stay Alive Cyprus!\n\n"
                "События на Кипре: концерты, выставки, вечеринки, "
                "дегустации, маркеты и другие причины выйти из дома.\n\n"
                "Нажми Start, чтобы открыть бота."
            )
        },
    )
    api_call(
        token,
        "setMyShortDescription",
        {
            "short_description": (
                "События на Кипре: концерты, искусство, "
                "вечеринки, еда и другие планы."
            )
        },
    )

    # Telegram keeps bot commands registered server-side unless they are
    # explicitly deleted. Remove the old command menu so it cannot duplicate
    # the persistent reply keyboard.
    api_call(token, "deleteMyCommands")

    # Return the chat menu button to Telegram's default behavior. With no
    # commands registered, there is no redundant command list to open.
    api_call(
        token,
        "setChatMenuButton",
        {"menu_button": {"type": "default"}},
    )
    print("Telegram profile configured; command menu cleared.")


def answer_callback(token: str, callback_id: str, text: str | None = None) -> None:
    """Acknowledge an inline-button tap immediately from the polling worker."""
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text[:200]
    api_call(token, "answerCallbackQuery", payload)


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

    for update in updates:
        update_offset = update["update_id"] + 1
        chat_id = None
        progress_message_id = None
        try:
            callback = update.get("callback_query")
            if callback:
                callback_id = callback.get("id")
                data = (callback.get("data") or "").strip()
                message = callback.get("message") or {}
                chat_id = (message.get("chat") or {}).get("id")
                message_id = message.get("message_id")
                print(
                    "Telegram callback: "
                    f"id={callback_id} chat_id={chat_id} "
                    f"message_id={message_id} data={data!r}"
                )
                try:
                    reply_chat_id, reply_text, keyboard = handle_callback(callback)
                    api_call(token, "answerCallbackQuery", {"callback_query_id": callback_id})
                    print(
                        f"Telegram callback handled: chat_id={reply_chat_id} "
                        f"text_len={len(reply_text or '')}"
                    )
                    if reply_chat_id is not None:
                        sent_id = send_message(
                            token,
                            reply_chat_id,
                            reply_text,
                            keyboard,
                            parse_mode="HTML",
                        )
                        print(
                            f"Telegram callback response sent: chat_id={reply_chat_id} "
                            f"message_id={sent_id}"
                        )
                except Exception as exc:
                    print(f"Telegram callback failed for data={data!r}: {exc}", file=sys.stderr)
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
            else:
                message = update.get("message")
                if not message:
                    print(f"Telegram update {update.get('update_id')} has no message/callback")
                else:
                    print(
                        f"Telegram message: update_id={update.get('update_id')}, "
                        f"chat_id={(message.get('chat') or {}).get('id')}, "
                        f"text={message.get('text', '')!r}"
                    )
                    chat_id = (message.get("chat") or {}).get("id")
                    if chat_id is not None:
                        text = (message.get("text") or "").strip()

                        if (
                            text.split("@", 1)[0] == "/pins"
                            and (message.get("chat") or {}).get("type") in ("group", "supergroup")
                        ):
                            source_url = "https://t.me/+0C0Mu-Xz4HAxMGNi"
                            source = get_source_by_url(source_url)
                            if not source:
                                send_message(token, chat_id, "Источник закрепов не найден в базе.", parse_mode=None)
                            else:
                                comment = source["comment"] or ""
                                import re
                                if re.search(r"chat_id=-?\d+", comment):
                                    comment = re.sub(r"chat_id=-?\d+", f"chat_id={chat_id}", comment)
                                else:
                                    comment = f"{comment}; chat_id={chat_id}"
                                update_source_comment(source_url, comment)
                                try:
                                    added = sync_pinned_telegram_chat(token, chat_id, source_url)
                                    send_message(
                                        token,
                                        chat_id,
                                        f"📌 Закреп проверен. Новых событий: {added}.\n\n"
                                        "Теперь этот чат можно обновлять автоматически.",
                                        parse_mode=None,
                                    )
                                except Exception as exc:
                                    send_message(
                                        token,
                                        chat_id,
                                        f"❌ Не удалось прочитать закреп: {exc}",
                                        parse_mode=None,
                                    )
                        else:
                            # Event views get an immediate acknowledgement before any
                            # source refresh. This is important because a slow upstream source
                            # must never make Telegram look completely dead.
                            needs_sync = text in ("📅 Сегодня", "🗓 На этой неделе")
                            progress_message_id = None

                            if needs_sync:
                                try:
                                    progress_message_id = send_message(
                                        token,
                                        chat_id,
                                        "🔎 Обновляю события…\n\nПроверяю свежие данные и сразу покажу результат.",
                                        parse_mode=None,
                                    )
                                    print(
                                        f"Telegram progress sent: chat_id={chat_id} "
                                        f"message_id={progress_message_id}"
                                    )
                                except Exception as progress_exc:
                                    print(
                                        f"Telegram progress message failed: {progress_exc}",
                                        file=sys.stderr,
                                    )

                            awaiting_source = get_chat_state(chat_id) == "awaiting_source"
                            source_url = normalize_url(text) if awaiting_source else ""
                            reply_text, keyboard = handle_message(message)

                            if awaiting_source and source_url:
                                # Adding a source should not wait for the next 5-minute
                                # GitHub schedule. Parse just this source now, then show
                                # the normal confirmation together with the sync result.
                                check_message_id = send_message(
                                    token,
                                    chat_id,
                                    "🔎 Источник добавлен. Проверяю его прямо сейчас…",
                                    parse_mode=None,
                                )
                                try:
                                    synced = sync_source_by_url(source_url)
                                    print(f"Telegram targeted source sync: {synced} new events")
                                    reply_text += (
                                        f"\\n\\n🔎 Проверка завершена: новых событий — {synced}."
                                    )
                                except Exception as sync_exc:
                                    print(f"Telegram targeted source sync failed: {sync_exc}", file=sys.stderr)
                                    reply_text += (
                                        "\\n\\n⚠️ Источник добавлен, но проверить его сейчас не удалось. "
                                        "Повторю при следующей синхронизации."
                                    )
                                if check_message_id is not None:
                                    try:
                                        edit_message(token, chat_id, check_message_id, reply_text, keyboard, parse_mode=None)
                                    except Exception as exc:
                                        print(f"Telegram source-sync edit failed: {exc}", file=sys.stderr)
                                continue

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
                                    print(
                                        f"Telegram progress updated: chat_id={chat_id} "
                                        f"message_id={progress_message_id}"
                                    )
                                except Exception as exc:
                                    print(
                                        f"Telegram edit failed; keeping the single progress message: {exc}",
                                        file=sys.stderr,
                                    )
                            else:
                                sent_id = send_message(token, chat_id, reply_text, keyboard)
                                print(
                                    f"Telegram response sent: chat_id={chat_id} "
                                    f"message_id={sent_id}"
                                )

        except Exception as exc:
            print(
                f"Telegram update failed: update_id={update.get('update_id')} "
                f"error={exc}",
                file=sys.stderr,
            )
            if chat_id is not None:
                try:
                    error_text = "⚠️ Не удалось обработать запрос. Попробуй ещё раз."
                    if progress_message_id is not None:
                        edit_message(token, chat_id, progress_message_id, error_text, parse_mode=None)
                    else:
                        send_message(token, chat_id, error_text, parse_mode=None)
                except Exception as notify_exc:
                    print(f"Telegram error notification failed: {notify_exc}", file=sys.stderr)
        finally:
            # Advance Telegram offset even when this update fails. This prevents
            # one broken request from blocking every later update in the batch.
            save_offset(update_offset)
            print(f"Telegram poll: saved offset={update_offset}")

    return True

