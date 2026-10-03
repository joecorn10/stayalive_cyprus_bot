"""Application configuration."""

import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
DATABASE_PATH = os.getenv("DATABASE_PATH", "events.db")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Nicosia")
TELEGRAM_API_BASE = "https://api.telegram.org"
