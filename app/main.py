"""Application entry point for GitHub Actions."""
import sys
from app.config import TELEGRAM_BOT_TOKEN
from app.telegram import poll_once

def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    changed = poll_once(TELEGRAM_BOT_TOKEN)
    print("Processed Telegram updates." if changed else "No new Telegram updates.")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Bot error: {exc}", file=sys.stderr)
        raise
