"""Long-poll Telegram while a GitHub Actions runner is alive."""

import sys
import time

from app.config import TELEGRAM_BOT_TOKEN
from app.telegram import api_call, poll_once

# Finish before the next scheduled GitHub Actions run starts. This keeps the
# git-backed Telegram offset single-writer and avoids overlapping workers.
WORKER_SECONDS = 285
SLEEP_SECONDS = 1


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    webhook = api_call(TELEGRAM_BOT_TOKEN, "getWebhookInfo").get("result", {})
    webhook_url = (webhook.get("url") or "").strip()
    if webhook_url:
        print(f"Telegram worker skipped: webhook is active at {webhook_url}")
        return

    deadline = time.monotonic() + WORKER_SECONDS
    handled = False

    while time.monotonic() < deadline:
        try:
            if poll_once(TELEGRAM_BOT_TOKEN):
                handled = True
        except Exception as exc:
            print(f"Telegram poll error: {exc}", file=sys.stderr)
            time.sleep(SLEEP_SECONDS)
            continue

        time.sleep(SLEEP_SECONDS)

    print("Telegram worker finished." if handled else "Telegram worker finished with no updates.")


if __name__ == "__main__":
    main()
