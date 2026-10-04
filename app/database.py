"""SQLite database layer."""

import sqlite3
from pathlib import Path
from urllib.parse import urlparse

from app.config import DATABASE_PATH


def canonical_source_url(url: str) -> str:
    """Canonicalize registered source URLs so tracking params do not create duplicates."""
    value = str(url or "").strip()
    if not value:
        return value
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return value
    host = parsed.netloc.casefold()
    path = parsed.path.rstrip("/")
    if host in {"instagram.com", "www.instagram.com"}:
        handle = path.strip("/").split("/")[0]
        if handle:
            return f"https://www.instagram.com/{handle.casefold()}/"
    if host == "t.me":
        segment = path.strip("/").split("/")[0]
        if segment:
            return f"https://t.me/{segment}"
    return value.split("#", 1)[0].split("?", 1)[0].rstrip("/") + "/"

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
            ("Urban Sketchers Cyprus", "https://www.instagram.com/urbansketcherscyprus", "Instagram", "Urban sketching, sketch walks and drawing meetups in Cyprus"),
            ("The Warehouse by IT Quarter", "https://www.instagram.com/the_warehouse_cy/", "Instagram", "The Warehouse Limassol events, concerts, exhibitions and markets"),
            ("Flydance.co", "https://www.instagram.com/flydance.co/", "Instagram", "Electronic music events, parties and festivals in Cyprus"),
            ("Facebook Shared Source", "https://www.facebook.com/share/1A24pimvMP/", "Facebook", "Facebook shared source; resolve target page before relying on event parsing"),
            ("artUS Cyprus", "https://artuscy.com/", "Website", "Art events, exhibitions and creative workshops"),
            ("Stantar Kkomety", "https://stantarkkomety.com/festival/tickets", "Website", "Limassol Comedy Festival tickets and programme"),
            ("Music Hall", "https://musichall.cy/", "Website", "Music Hall Limassol events and concerts"),
            ("Music Hall Telegram", "https://t.me/livemusichall", "Telegram", "Music Hall Limassol live programme and ticket announcements"),
            ("Live Music Zone", "https://livemusiczone.fun/", "Website", "Live music events and tickets in Cyprus"),
            ("Cyprus Underground", "https://www.cyprusunderground.com.cy/", "Website", "Electronic music, club nights, techno, house and rave events across Cyprus"),
            ("Facebook Cyprus Discovery", "site:facebook.com/events Cyprus (Limassol OR Nicosia OR Larnaca OR Paphos) event", "FacebookDiscovery", "Public Facebook events discovered through search indexing"),
        ]
        seed_sources = [
            (name, canonical_source_url(url), source_type, comment)
            for name, url, source_type, comment in seed_sources
        ]
        conn.executemany(
            """INSERT OR IGNORE INTO sources
               (name, url, type, comment)
               VALUES (?, ?, ?, ?)""",
            seed_sources,
        )
        conn.execute(
            "UPDATE sources SET enabled = 1 WHERE name = 'SoldOut TicketBox'"
        )
        conn.execute(
            "UPDATE sources SET enabled = 0 WHERE name = 'More.com Cyprus'"
        )
        conn.commit()

    deduplicate_sources()


def deduplicate_sources() -> int:
    """Merge source registrations that resolve to the same canonical URL."""
    removed = 0
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM sources ORDER BY id").fetchall()
        keepers = {}
        for row in rows:
            key = (canonical_source_url(row["url"]), str(row["type"] or "").casefold())
            keeper = keepers.get(key)
            if keeper is None:
                keepers[key] = row
                canonical = canonical_source_url(row["url"])
                if canonical != row["url"]:
                    conn.execute("UPDATE sources SET url = ? WHERE id = ?", (canonical, row["id"]))
                continue
            conn.execute(
                """INSERT OR IGNORE INTO event_sources (event_id, source_id, source_url)
                   SELECT event_id, ?, source_url
                   FROM event_sources WHERE source_id = ?""",
                (keeper["id"], row["id"]),
            )
            conn.execute("DELETE FROM event_sources WHERE source_id = ?", (row["id"],))
            conn.execute("DELETE FROM sources WHERE id = ?", (row["id"],))
            removed += 1
        conn.commit()
    return removed

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
        canonical_url = canonical_source_url(url)
        cursor = conn.execute(
            """INSERT OR IGNORE INTO sources
               (name, url, type, comment, category, city)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, canonical_url, source_type, comment, category, city),
        )
        conn.commit()
        return cursor.rowcount == 1


def get_source_by_url(url: str):
    init_db()
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM sources WHERE url = ?", (canonical_source_url(url),)
        ).fetchone()


def update_source_comment(url: str, comment: str) -> None:
    init_db()
    with get_connection() as conn:
        conn.execute(
            "UPDATE sources SET comment = ? WHERE url = ?", (comment, canonical_source_url(url))
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
        str(event.get("time", "")).lower().strip(),
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
        (key[1], key[4]),
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

            # One source page can contain many events. Do not treat source_url
            # alone as the event identity.
            existing = conn.execute(
                """SELECT * FROM events
                   WHERE source_url = ?
                     AND date = ?
                     AND COALESCE(time, '') = ?
                     AND COALESCE(venue, '') = ?
                     AND title = ?
                   LIMIT 1""",
                (
                    source_url,
                    event.get("date", ""),
                    event.get("time", ""),
                    event.get("venue", ""),
                    event.get("title", ""),
                ),
            ).fetchone()

            # A content hash can collide when the same event is syndicated by
            # multiple sources. Reuse the existing row instead of letting the
            # UNIQUE constraint abort the whole source batch.
            by_hash = None
            if event.get("content_hash"):
                by_hash = conn.execute(
                    "SELECT * FROM events WHERE content_hash = ? LIMIT 1",
                    (event.get("content_hash"),),
                ).fetchone()
            # Prefer an exact content-hash match over a looser source/date match.
            # Otherwise updating the looser match can create a duplicate hash.
            match = by_hash or existing or _find_matching_event(conn, event)

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


def _display_title_tokens(title: str) -> set[str]:
    import re

    value = re.sub(r"[^a-z0-9а-яё]+", " ", str(title).lower(), flags=re.I)
    generic = {
        "festival", "festivals", "фестиваль", "фестивал", "дни", "день",
        "мероприятие", "event", "events", "праздник",
    }
    return {
        token for token in value.split()
        if len(token) >= 4 and token not in generic
    }


def _looks_like_duplicate_event(a: sqlite3.Row, b: sqlite3.Row) -> bool:
    from difflib import SequenceMatcher
    import re

    if a["date"] != b["date"]:
        return False

    def normalize(value):
        return " ".join(
            re.sub(r"[^a-z0-9а-яё]+", " ", str(value or "").lower(), flags=re.I).split()
        )

    # Missing venue/time in one source should not prevent a match, but
    # conflicting values are a strong signal that these are different events.
    for field in ("time", "venue", "city"):
        left_value = normalize(a[field])
        right_value = normalize(b[field])
        if left_value and right_value and left_value != right_value:
            return False

    left = _display_title_tokens(a["title"])
    right = _display_title_tokens(b["title"])
    if not left or not right:
        return False

    overlap = len(left & right) / min(len(left), len(right))
    similarity = SequenceMatcher(
        None,
        " ".join(sorted(left)),
        " ".join(sorted(right)),
    ).ratio()

    # Category is intentionally ignored: classification can differ between
    # sources and should never create two cards for the same event.
    return overlap >= 0.67 or similarity >= 0.84


def deduplicate_exact_events() -> int:
    """Merge exact cross-source copies while preserving source provenance."""
    import re

    def normalize(value):
        return " ".join(
            re.sub(r"[^a-z0-9а-яё]+", " ", str(value or "").lower(), flags=re.I).split()
        )

    def compatible(a, b):
        if a["date"] != b["date"]:
            return False

        time_a, time_b = normalize(a["time"]), normalize(b["time"])
        if time_a and time_b and time_a != time_b:
            return False

        venue_a, venue_b = normalize(a["venue"]), normalize(b["venue"])
        if venue_a and venue_b and venue_a != venue_b:
            return False

        city_a, city_b = normalize(a["city"]), normalize(b["city"])
        if city_a and city_b and city_a != city_b:
            return False

        return True

    removed = 0
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM events ORDER BY id").fetchall()
        keepers = []

        for row in rows:
            title = normalize(row["title"])
            if not title:
                continue

            keeper = next(
                (
                    candidate
                    for candidate in keepers
                    if normalize(candidate["title"]) == title
                    and compatible(candidate, row)
                ),
                None,
            )
            if keeper is None:
                keepers.append(row)
                continue

            # Preserve every source attached to the duplicate before removing it.
            conn.execute(
                """INSERT OR IGNORE INTO event_sources (event_id, source_id, source_url)
                   SELECT ?, source_id, source_url
                   FROM event_sources
                   WHERE event_id = ?""",
                (keeper["id"], row["id"]),
            )
            conn.execute("DELETE FROM event_sources WHERE event_id = ?", (row["id"],))
            conn.execute("DELETE FROM events WHERE id = ?", (row["id"],))
            removed += 1

        conn.commit()

    return removed

def list_events(start_date: str, end_date: str) -> list[sqlite3.Row]:
    init_db()
    deduplicate_exact_events()
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM events
               WHERE date <= ? AND COALESCE(end_date, date) >= ?
               ORDER BY date, time, title COLLATE NOCASE""",
            (end_date, start_date),
        ).fetchall()

    unique = []
    for row in rows:
        if any(_looks_like_duplicate_event(row, existing) for existing in unique):
            continue
        unique.append(row)
    return unique



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
