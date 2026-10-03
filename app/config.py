"""Application configuration."""

import os


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
DATABASE_PATH = os.getenv("DATABASE_PATH", "events.db")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Nicosia")
