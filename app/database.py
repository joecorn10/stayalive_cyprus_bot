"""SQLite database layer."""

import sqlite3
from pathlib import Path

from app.config import DATABASE_PATH


def get_connection() -> sqlite3.Connection:
    path = Path(DATABASE_PATH)
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL,
                comment TEXT,
                category TEXT,
                city TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_checked_at TEXT,
                last_success_at TEXT,
                last_error TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_state (
                chat_id INTEGER PRIMARY KEY,
                state TEXT NOT NULL DEFAULT 'idle',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        seed_sources = [
            ("Cyproplan", "https://cyproplan.com/", "Website", "Cyprus event aggregator"),
            ("ETKO Cyprus", "https://etkocyprus.com/events", "Website", "Events, concerts and parties"),
            ("SoldOut TicketBox", "https://www.soldoutticketbox.com/en/home", "Website", "Ticketing and event listings"),
        ]
        conn.executemany(
            """INSERT OR IGNORE INTO sources
               (name, url, type, comment)
               VALUES (?, ?, ?, ?)""",
            seed_sources,
        )
        conn.commit()


def list_sources() -> list[sqlite3.Row]:
    init_db()
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM sources ORDER BY enabled DESC, name COLLATE NOCASE"
        ).fetchall()


def add_source(
    name: str,
    url: str,
    source_type: str,
    comment: str = "",
    category: str = "",
    city: str = "",
) -> bool:
    init_db()
    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO sources
               (name, url, type, comment, category, city)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, url, source_type, comment, category, city),
        )
        conn.commit()
        return cursor.rowcount == 1


def get_chat_state(chat_id: int) -> str:
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT state FROM chat_state WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        return row["state"] if row else "idle"


def set_chat_state(chat_id: int, state: str) -> None:
    init_db()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO chat_state (chat_id, state)
               VALUES (?, ?)
               ON CONFLICT(chat_id) DO UPDATE SET
                 state = excluded.state,
                 updated_at = CURRENT_TIMESTAMP""",
            (chat_id, state),
        )
        conn.commit()
