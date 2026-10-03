"""Persistent Telegram webhook service for Stay Alive Cyprus."""

import os
import threading

from flask import Flask, jsonify, request

from app.handlers import handle_callback, handle_message
from app.telegram import api_call, edit_message, send_message

app = Flask(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()


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
    payload = {"url": url, "drop_pending_updates": False}
    if WEBHOOK_SECRET:
        payload["secret_token"] = WEBHOOK_SECRET

    try:
        result = api_call(TOKEN, "setWebhook", payload)
        print(f"Telegram webhook configured: {url} result={result}")
    except Exception as exc:
        print(f"Telegram webhook setup failed: {exc}")


def _valid_request() -> bool:
    if not WEBHOOK_SECRET:
        return True
    return request.headers.get("X-Telegram-Bot-Api-Secret-Token", "") == WEBHOOK_SECRET


def _process_update(update: dict) -> None:
    try:
        if "callback_query" in update:
            callback = update["callback_query"]
            callback_id = callback.get("id")
            if callback_id:
                try:
                    api_call(TOKEN, "answerCallbackQuery", {"callback_query_id": callback_id})
                except Exception as exc:
                    print(f"Telegram callback acknowledgement failed: {exc}")

            chat_id, reply_text, keyboard = handle_callback(callback)
            if chat_id is not None:
                message = callback.get("message") or {}
                message_id = message.get("message_id")
                if message_id:
                    try:
                        edit_message(
                            TOKEN,
                            chat_id,
                            message_id,
                            reply_text,
                            keyboard,
                            parse_mode="HTML",
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
            return

        message = update.get("message")
        if not message:
            return

        chat_id = (message.get("chat") or {}).get("id")
        text = (message.get("text") or "").strip()
        if chat_id is None:
            return

        needs_sync = text in ("📅 Сегодня", "🗓 На этой неделе")
        progress_message_id = None

        if needs_sync:
            try:
                progress_message_id = send_message(
                    TOKEN,
                    chat_id,
                    "🔎 Обновляю события…\n\nПроверяю свежие данные и сразу покажу результат.",
                    parse_mode=None,
                )
            except Exception as exc:
                print(f"Telegram progress message failed: {exc}")

        reply_text, keyboard = handle_message(message)

        if progress_message_id is not None:
            try:
                edit_message(
                    TOKEN,
                    chat_id,
                    progress_message_id,
                    reply_text,
                    keyboard,
                    parse_mode=None,
                )
            except Exception as exc:
                print(f"Telegram progress edit failed: {exc}")
                send_message(TOKEN, chat_id, reply_text, keyboard, parse_mode=None)
        else:
            send_message(TOKEN, chat_id, reply_text, keyboard)

    except Exception as exc:
        print(f"Telegram webhook update failed: {exc}")
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

    # Return 200 immediately so Telegram never waits for event syncing/parsing.
    # The actual handler runs in a short-lived background thread.
    threading.Thread(
        target=_process_update,
        args=(update,),
        daemon=True,
    ).start()
    return jsonify({"ok": True})


configure_webhook()
