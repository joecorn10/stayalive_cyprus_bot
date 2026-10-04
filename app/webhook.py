"""Persistent Telegram webhook service for Stay Alive Cyprus.

The Render webhook is the single Telegram update consumer. GitHub Actions does
not poll Telegram while this webhook is active.
"""

import os
import threading

from flask import Flask, jsonify, request

from app.handlers import handle_callback, handle_message
from app.telegram import (
    api_call,
    edit_message,
    send_message,
    send_navigation_message,
)
from app.database import get_chat_state
from app.source_detector import normalize_url
from app.sync import sync_source_by_url

app = Flask(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
STANTAR_URL = "https://stantarkkomety.com/festival/tickets"


def _webhook_path() -> str:
    return "/telegram/webhook"


def configure_webhook() -> None:
    if not TOKEN:
        print("Telegram webhook: TELEGRAM_BOT_TOKEN is not configured")
        return

    base_url = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    if not base_url:
        print("Telegram webhook: RENDER_EXTERNAL_URL is not available yet")
        return

    url = f"{base_url}{_webhook_path()}"
    payload = {
        "url": url,
        "drop_pending_updates": False,
        "allowed_updates": ["message", "callback_query"],
    }
    if WEBHOOK_SECRET:
        payload["secret_token"] = WEBHOOK_SECRET

    try:
        # Telegram may keep a valid webhook URL while delivery becomes stale
        # after a runtime restart. Reset it on boot without dropping updates.
        current = api_call(TOKEN, "getWebhookInfo", {}).get("result", {})
        current_url = (current.get("url") or "").strip()
        if current_url == url:
            api_call(TOKEN, "deleteWebhook", {"drop_pending_updates": False})
            print("Telegram webhook reset before re-registration; pending updates preserved.")

        result = api_call(TOKEN, "setWebhook", payload)
        print(f"Telegram webhook configured: {url} result={result}")
        try:
            info = api_call(TOKEN, "getWebhookInfo", {})
            print(
                "Telegram webhook info: "
                f"url={(info.get("result") or {}).get("url")!r} "
                f"pending={(info.get("result") or {}).get("pending_update_count")} "
                f"last_error={(info.get("result") or {}).get("last_error_message")!r} "
                f"last_error_at={(info.get("result") or {}).get("last_error_date")}"
            )
        except Exception as exc:
            print(f"Telegram webhook info failed: {exc}")
    except Exception as exc:
        print(f"Telegram webhook setup failed: {exc}")


def _valid_request() -> bool:
    if not WEBHOOK_SECRET:
        return True
    return request.headers.get("X-Telegram-Bot-Api-Secret-Token", "") == WEBHOOK_SECRET


def _process_update(update: dict) -> None:
    """Process exactly one Telegram update and produce at most one visible reply."""
    try:
        callback = update.get("callback_query")
        if callback:
            callback_id = callback.get("id")
            callback_data = (callback.get("data") or "").strip()
            if callback_id:
                try:
                    callback_notice = None
                    if callback_data in ("main:today", "main:week"):
                        callback_notice = "⏳ Загружаю результаты…"
                    payload = {"callback_query_id": callback_id}
                    if callback_notice:
                        payload["text"] = callback_notice
                    api_call(TOKEN, "answerCallbackQuery", payload)
                except Exception as exc:
                    print(f"Telegram callback acknowledgement failed: {exc}")

            chat_id, reply_text, keyboard = handle_callback(callback)
            if chat_id is None:
                return

            message = callback.get("message") or {}
            message_id = message.get("message_id")
            if message_id:
                try:
                    # Inline navigation edits the message that was clicked.
                    # No second visible message is created.
                    edit_message(
                        TOKEN,
                        chat_id,
                        message_id,
                        reply_text,
                        keyboard,
                        parse_mode="HTML",
                    )
                    print(
                        "Telegram webhook callback edited: "
                        f"chat_id={chat_id} message_id={message_id} "
                        f"data={(callback.get('data') or '').strip()!r}"
                    )
                except Exception as exc:
                    print(f"Telegram callback edit failed: {exc}")
                    send_message(
                        TOKEN,
                        chat_id,
                        reply_text,
                        keyboard,
                        parse_mode="HTML",
                    )
            else:
                send_message(
                    TOKEN,
                    chat_id,
                    reply_text,
                    keyboard,
                    parse_mode="HTML",
                )
            return

        message = update.get("message")
        if not message:
            return

        chat_id = (message.get("chat") or {}).get("id")
        if chat_id is None:
            return

        text = (message.get("text") or "").strip()
        print(
            "Telegram webhook message: "
            f"update_id={update.get('update_id')} chat_id={chat_id} text={text!r}"
        )

        awaiting_source = get_chat_state(chat_id) == "awaiting_source"
        source_url = normalize_url(text) if awaiting_source else ""

        # handle_message contains the existing command/menu logic and, for
        # Today/Week, refreshes Stantar before returning the final snapshot.
        # The webhook itself is already running off the HTTP request thread, so
        # this does not block Telegram's webhook acknowledgement.
        reply_text, keyboard = handle_message(message)

        if awaiting_source and source_url:
            # Preserve the existing "check this source now" behavior, but keep
            # it to one visible message: send one temporary message and edit it
            # into the final result.
            check_message_id = send_navigation_message(
                TOKEN,
                chat_id,
                "🔎 Источник добавлен. Проверяю его прямо сейчас…",
                parse_mode=None,
            )
            try:
                synced = sync_source_by_url(source_url)
                print(f"Telegram targeted source sync: {synced} new events")
                reply_text += f"\\n\\n🔎 Проверка завершена: новых событий — {synced}."
            except Exception as sync_exc:
                print(
                    f"Telegram targeted source sync failed: {sync_exc}",
                )
                reply_text += (
                    "\\n\\n⚠️ Источник добавлен, но проверить его сейчас не удалось. "
                    "Повторю при следующей синхронизации."
                )

            if check_message_id is not None:
                try:
                    edit_message(
                        TOKEN,
                        chat_id,
                        check_message_id,
                        reply_text,
                        keyboard,
                        parse_mode=None,
                    )
                except Exception as exc:
                    print(f"Telegram source-sync edit failed: {exc}")
            return

        # This also removes the legacy ReplyKeyboard in the same visible
        # message flow. From this point onward navigation is inline-only.
        sent_id = send_navigation_message(
            TOKEN,
            chat_id,
            reply_text,
            keyboard,
        )
        print(
            f"Telegram webhook response sent: chat_id={chat_id} message_id={sent_id}"
        )

    except Exception as exc:
        print(
            f"Telegram webhook update failed: "
            f"update_id={update.get('update_id')} error={exc}"
        )
        message = update.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        if chat_id is not None:
            try:
                send_message(
                    TOKEN,
                    chat_id,
                    "⚠️ Не удалось обработать запрос. Попробуй ещё раз.",
                    parse_mode=None,
                )
            except Exception as notify_exc:
                print(f"Telegram webhook error notification failed: {notify_exc}")


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "stayalive-cyprus-webhook"})


@app.post("/telegram/webhook")
def telegram_webhook():
    if not _valid_request():
        return jsonify({"ok": False}), 403

    update = request.get_json(silent=True) or {}
    if not update:
        return jsonify({"ok": False, "error": "empty update"}), 400

    # Acknowledge Telegram immediately. The actual work happens in one
    # short-lived background thread per update.
    threading.Thread(
        target=_process_update,
        args=(update,),
        daemon=True,
    ).start()
    return jsonify({"ok": True})


configure_webhook()
