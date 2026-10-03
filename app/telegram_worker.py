"""Long-poll Telegram while a GitHub Actions runner is alive."""

import sys
import time

from app.config import TELEGRAM_BOT_TOKEN
from app.telegram import poll_once

# Keep the worker alive almost for the full GitHub Actions 5-minute schedule
# window, minimizing the gap in which Telegram updates cannot be received.
WORKER_SECONDS = 110
SLEEP_SECONDS = 1


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

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
