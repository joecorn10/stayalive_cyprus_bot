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
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                category TEXT,
                date TEXT NOT NULL,
                end_date TEXT,
                time TEXT,
                venue TEXT,
                city TEXT,
                price TEXT,
                ticket_url TEXT,
                source_url TEXT NOT NULL,
                image_url TEXT,
                content_hash TEXT UNIQUE,
                first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(events)")}
        if "end_date" not in columns:
            conn.execute("ALTER TABLE events ADD COLUMN end_date TEXT")
            conn.execute("UPDATE events SET end_date = date WHERE end_date IS NULL")

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
            ("Cyprus Journal Music", "https://t.me/cyprusjournalmusic", "Telegram", "Music and events in Cyprus"),
            ("Cyprus Beer Events", "https://t.me/cyprusBeerEvents", "Telegram", "Beer and events in Cyprus"),
            ("Cyproplan Telegram", "https://t.me/cyproplan", "Telegram", "Cyproplan events"),
            ("Cyprus Man Chat", "https://t.me/cyprus_man_chat", "Telegram", "Cyprus community and events"),
            ("Cyprus Events Group", "https://t.me/+xiXW5YRRXRg1Y2My", "Telegram", "Cyprus events group"),
            ("ETKO Limassol", "https://instagram.com/etko_limassol", "Instagram", "Events, concerts and electronic music"),
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


def add_source(name: str, url: str, source_type: str, comment: str = "",
               category: str = "", city: str = "") -> bool:
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


def upsert_events(events: list[dict]) -> int:
    init_db()
    added = 0
    with get_connection() as conn:
        for event in events:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO events
                   (title, description, category, date, end_date, time, venue, city,
                    price, ticket_url, source_url, image_url, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.get("title", ""),
                    event.get("description", ""),
                    event.get("category", ""),
                    event.get("date", ""),
                    event.get("end_date") or event.get("date", ""),
                    event.get("time", ""),
                    event.get("venue", ""),
                    event.get("city", ""),
                    event.get("price", ""),
                    event.get("ticket_url", ""),
                    event.get("source_url", ""),
                    event.get("image_url", ""),
                    event.get("content_hash"),
                ),
            )
            added += cursor.rowcount
        conn.commit()
    return added


def list_events(start_date: str, end_date: str) -> list[sqlite3.Row]:
    init_db()
    with get_connection() as conn:
        return conn.execute(
            """SELECT * FROM events
               WHERE date <= ? AND COALESCE(end_date, date) >= ?
               ORDER BY date, time, title COLLATE NOCASE""",
            (end_date, start_date),
        ).fetchall()


def database_stats() -> dict:
    init_db()
    with get_connection() as conn:
        sources = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        enabled_sources = conn.execute(
            "SELECT COUNT(*) FROM sources WHERE enabled = 1"
        ).fetchone()[0]
        events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        upcoming = conn.execute(
            "SELECT COUNT(*) FROM events WHERE COALESCE(end_date, date) >= date('now')"
        ).fetchone()[0]
        latest = conn.execute("SELECT MAX(last_seen_at) FROM events").fetchone()[0]
    return {
        "sources": sources,
        "enabled_sources": enabled_sources,
        "events": events,
        "upcoming": upcoming,
        "latest_event_seen": latest or "—",
    }


def list_recent_events(limit: int = 10) -> list[sqlite3.Row]:
    init_db()
    with get_connection() as conn:
        return conn.execute(
            """SELECT title, date, end_date, time, venue, city, source_url
               FROM events
               ORDER BY date DESC, time DESC, id DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()


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
