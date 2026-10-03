"""Application entry point."""

from app.config import TELEGRAM_BOT_TOKEN
from app.telegram import run_polling


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. Add it to your environment before starting the bot."
        )
    run_polling(TELEGRAM_BOT_TOKEN)


if __name__ == "__main__":
    main()
