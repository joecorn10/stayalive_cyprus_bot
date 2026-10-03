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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS event_sources (
                event_id INTEGER NOT NULL,
                source_id INTEGER NOT NULL,
                source_url TEXT NOT NULL,
                PRIMARY KEY (event_id, source_id, source_url),
                FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
                FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_cache (
                cache_key TEXT PRIMARY KEY,
                synced_at TEXT NOT NULL
            )
        """)
        seed_sources = [
            ("Cyproplan", "https://cyproplan.com/", "Website", "Cyprus event aggregator"),
            ("ETKO Cyprus", "https://etkocyprus.com/events", "Website", "Events, concerts and parties"),
            ("SoldOut TicketBox", "https://www.soldoutticketbox.com/en/home", "Website", "Ticketing and event listings"),
            ("EventOr", "https://eventor.com.cy/", "Aggregator", "Cyprus-wide event discovery"),
            ("Cyprus.BZ", "https://cyprus.bz/", "Aggregator", "Cyprus-wide event discovery"),
            ("More.com Cyprus", "https://www.more.com/cy-en/tickets/", "Aggregator", "Ticketing and event listings"),
            ("Cyprus Journal Music", "https://t.me/cyprusjournalmusic", "Telegram", "Music and events in Cyprus"),
            ("Cyprus Beer Events", "https://t.me/cyprusBeerEvents", "Telegram", "Beer and events in Cyprus"),
            ("Cyproplan Telegram", "https://t.me/cyproplan", "Telegram", "Cyproplan events"),
            ("Cyprus Man Chat", "https://t.me/cyprus_man_chat", "Telegram", "Cyprus community and events"),
            ("Cyprus Events Group", "https://t.me/+xiXW5YRRXRg1Y2My", "Telegram", "Cyprus events group"),
            ("Cyprus Meetup Pinned", "https://t.me/+0C0Mu-Xz4HAxMGNi", "TelegramPinned", "Pinned events from Cyprus community chat; chat_id is learned when /pins is used in the chat"),
            ("Volta Wine Bar", "https://www.instagram.com/voltawinebar/", "Instagram", "Wine bar events and tastings"),
            ("Joools Limassol", "https://www.instagram.com/joools.limassol/", "Instagram", "Limassol events and lifestyle"),
            ("Synerjoy Cyprus", "https://www.instagram.com/synerjoy_cy/", "Instagram", "Community and events in Cyprus"),
            ("Cyprus Journal", "https://www.instagram.com/cyprus.journal/", "Instagram", "Cyprus events and culture"),
            ("Dead Grapes Osteria", "https://www.instagram.com/deadgrapes_osteria/", "Instagram", "Wine and food events"),
            ("Zebra Limassol", "https://www.instagram.com/zebra_limassol/", "Instagram", "Limassol events"),
            ("Poly Limassol", "https://www.instagram.com/poly.limassol/", "Instagram", "Limassol events and culture"),
            ("Kolla Cyprus", "https://www.instagram.com/kolla.cy/", "Instagram", "Cyprus events and community"),
            ("ETKO Limassol", "https://instagram.com/etko_limassol", "Instagram", "Events, concerts and electronic music"),
            ("Facebook Cyprus Discovery", "site:facebook.com/events Cyprus (Limassol OR Nicosia OR Larnaca OR Paphos) event", "FacebookDiscovery", "Public Facebook events discovered through search indexing"),
        ]
        conn.executemany(
            """INSERT OR IGNORE INTO sources
               (name, url, type, comment)
               VALUES (?, ?, ?, ?)""",
            seed_sources,
        )
        conn.execute(
            "UPDATE sources SET enabled = 0 WHERE name IN ('SoldOut TicketBox', 'More.com Cyprus')"
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


def get_source_by_url(url: str):
    init_db()
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM sources WHERE url = ?", (url,)
        ).fetchone()


def update_source_comment(url: str, comment: str) -> None:
    init_db()
    with get_connection() as conn:
        conn.execute(
            "UPDATE sources SET comment = ? WHERE url = ?", (comment, url)
        )
        conn.commit()


def _event_key(event: dict) -> tuple:
    import re
    title = re.sub(r"[^a-z0-9а-яё]+", " ", str(event.get("title", "")).lower(), flags=re.I)
    title = " ".join(title.split())
    venue = re.sub(r"[^a-z0-9а-яё]+", " ", str(event.get("venue", "")).lower(), flags=re.I)
    venue = " ".join(venue.split())
    return (
        title,
        event.get("date", ""),
        venue,
        str(event.get("city", "")).lower().strip(),
    )


def _find_matching_event(conn: sqlite3.Connection, event: dict):
    key = _event_key(event)
    rows = conn.execute(
        """SELECT * FROM events
           WHERE date = ?
             AND (COALESCE(city, '') = ? OR COALESCE(city, '') = '')
           ORDER BY id""",
        (key[1], key[3]),
    ).fetchall()
    for row in rows:
        if _event_key(dict(row)) == key:
            return row
    return None


def upsert_events(events: list[dict]) -> int:
    init_db()
    added = 0
    with get_connection() as conn:
        for event in events:
            source_url = event.get("source_url", "")
            source = conn.execute(
                "SELECT id FROM sources WHERE url = ?",
                (_source_root(source_url),),
            ).fetchone()

            # A parser may return a source URL belonging to the same registered
            # source but with a deeper path, so fall back to the exact source.
            if not source:
                source = conn.execute(
                    "SELECT id FROM sources WHERE url = ?",
                    (source_url,),
                ).fetchone()

            existing = conn.execute(
                "SELECT id FROM events WHERE source_url = ? LIMIT 1",
                (source_url,),
            ).fetchone()

            match = existing or _find_matching_event(conn, event)

            values = (
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
                source_url,
                event.get("image_url", ""),
                event.get("content_hash"),
            )

            if match:
                conn.execute(
                    """UPDATE events SET
                       title = ?, description = ?, category = ?, date = ?,
                       end_date = ?, time = ?, venue = ?, city = ?, price = ?,
                       ticket_url = ?, source_url = ?, image_url = ?, content_hash = ?,
                       last_seen_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    values + (match["id"],),
                )
                event_id = match["id"]
            else:
                cursor = conn.execute(
                    """INSERT INTO events
                       (title, description, category, date, end_date, time, venue, city,
                        price, ticket_url, source_url, image_url, content_hash)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    values,
                )
                event_id = cursor.lastrowid
                added += 1

            if source:
                conn.execute(
                    """INSERT OR IGNORE INTO event_sources
                       (event_id, source_id, source_url)
                       VALUES (?, ?, ?)""",
                    (event_id, source["id"], source_url),
                )

        conn.commit()
    return added


def _source_root(url: str) -> str:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.netloc == "etkocyprus.com" and "/events/" in parsed.path:
        return "https://etkocyprus.com/events"
    if parsed.netloc == "www.soldoutticketbox.com":
        return "https://www.soldoutticketbox.com/en/home"
    if parsed.netloc in ("eventor.com.cy", "www.eventor.com.cy"):
        return "https://eventor.com.cy/"
    if parsed.netloc in ("cyprus.bz", "www.cyprus.bz"):
        return "https://cyprus.bz/"
    if parsed.netloc == "www.more.com" and "/cy-" in parsed.path:
        return "https://www.more.com/cy-en/tickets/"
    if parsed.netloc == "cyproplan.com":
        return "https://cyproplan.com/"
    if parsed.netloc == "t.me":
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 1:
            return f"https://t.me/{parts[0]}"
    return url


def get_event(event_id: int):
    init_db()
    with get_connection() as conn:
        return conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()


def list_events(start_date: str, end_date: str) -> list[sqlite3.Row]:
    init_db()
    with get_connection() as conn:
        return conn.execute(
            """SELECT * FROM events
               WHERE date <= ? AND COALESCE(end_date, date) >= ?
               ORDER BY date, time, title COLLATE NOCASE""",
            (end_date, start_date),
        ).fetchall()



def cache_is_fresh(cache_key: str, ttl_minutes: int = 30) -> bool:
    init_db()
    from datetime import datetime, timedelta, timezone
    with get_connection() as conn:
        row = conn.execute(
            "SELECT synced_at FROM sync_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
    if not row:
        return False
    try:
        synced_at = datetime.fromisoformat(row["synced_at"])
    except (TypeError, ValueError):
        return False
    if synced_at.tzinfo is None:
        synced_at = synced_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - synced_at < timedelta(minutes=ttl_minutes)


def mark_cache_fresh(cache_key: str) -> None:
    init_db()
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO sync_cache (cache_key, synced_at)
               VALUES (?, ?)
               ON CONFLICT(cache_key) DO UPDATE SET synced_at = excluded.synced_at""",
            (cache_key, now),
        )
        conn.commit()


def list_event_sources(event_id: int) -> list[sqlite3.Row]:
    init_db()
    with get_connection() as conn:
        return conn.execute(
            """SELECT s.name, s.type, es.source_url
               FROM event_sources es
               JOIN sources s ON s.id = es.source_id
               WHERE es.event_id = ?
               ORDER BY s.name COLLATE NOCASE""",
            (event_id,),
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
