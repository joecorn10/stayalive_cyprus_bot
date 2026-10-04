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
        if "identity_key" not in columns:
            conn.execute("ALTER TABLE events ADD COLUMN identity_key TEXT")
        if "categories" not in columns:
            conn.execute("ALTER TABLE events ADD COLUMN categories TEXT")

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
            ("Cyprus Journal", "https://t.me/cyprusjournal", "Telegram", "Cyprus events, culture and city life"),
            ("Cyprus Afisha", "https://t.me/cyprusafisha", "Telegram", "Cyprus events and nightlife listings"),
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
            canonical = canonical_source_url(row["url"])
            key = (canonical, str(row["type"] or "").casefold())
            keeper = keepers.get(key)

            if keeper is None:
                # A canonical row may already exist later in the table. Find it
                # before attempting UPDATE, otherwise SQLite hits UNIQUE(url).
                existing = conn.execute(
                    "SELECT * FROM sources WHERE url = ? AND id != ? LIMIT 1",
                    (canonical, row["id"]),
                ).fetchone()

                if existing is not None:
                    existing_key = (
                        canonical_source_url(existing["url"]),
                        str(existing["type"] or "").casefold(),
                    )
                    if existing_key == key:
                        keeper = existing
                        keepers[key] = keeper
                    else:
                        keeper = row
                        keepers[key] = keeper
                else:
                    keeper = row
                    keepers[key] = keeper

            if keeper["id"] != row["id"]:
                conn.execute(
                    """INSERT OR IGNORE INTO event_sources (event_id, source_id, source_url)
                       SELECT event_id, ?, source_url
                       FROM event_sources WHERE source_id = ?""",
                    (keeper["id"], row["id"]),
                )
                conn.execute(
                    "DELETE FROM event_sources WHERE source_id = ?", (row["id"],)
                )
                conn.execute("DELETE FROM sources WHERE id = ?", (row["id"],))
                removed += 1
                continue

            if canonical != row["url"]:
                conn.execute(
                    "UPDATE sources SET url = ? WHERE id = ?",
                    (canonical, row["id"]),
                )

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


def _identity_text(value: str) -> str:
    """Normalize titles/metadata for real-world event identity matching."""
    import re
    value = str(value or "").casefold()
    value = re.split(
        r"\s+(?=(?:location|tickets?|register|registration|more info|price|"
        r"doors?\s+open|we meet|bring your|в программе|программа|"
        r"группа|зарегистрироваться|получить\s+стартовый)\b)",
        value,
        maxsplit=1,
        flags=re.I,
    )[0]
    value = re.sub(r"[^a-z0-9а-яё]+", " ", value, flags=re.I)

    replacements = (
        (r"фестивал(?:ь|я|ю|ем|е|и|ей|ях)?", "festival"),
        (r"концерт(?:а|у|ом|е|ы|ов|ах)?", "concert"),
        (r"традицион(?:ный|ная|ное|ных|ного|ному|ным|ными)?", "traditional"),
        (r"вкус(?:ов|ами|ах|ы)?", "flavour"),
        (r"оливков(?:ый|ая|ое|ых|ого|ому|ым|ыми)?", "olive"),
        (r"дерев(?:о|ья|ьев|у|ом|ами)?", "tree"),
        (r"джаз(?:а|у|ом|е)?", "jazz"),
        (r"соул(?:а|у|ом|е)?", "soul"),
        (r"фанк(?:а|у|ом|е)?", "funk"),
        (r"крыше?", "rooftop"),
        (r"вечерин(?:ка|ки|ок|ку|кой|ках)?", "party"),
        (r"вино(?:а|у|ом|е|в)?", "wine"),
        (r"дегустаци(?:я|и|ю|ей|ях)?", "tasting"),
        (r"выставк(?:а|и|у|ой|ах)?", "exhibition"),
        (r"мастер[- ]класс(?:ы|а|ов|е|ах)?", "workshop"),
        (r"мероприяти(?:е|я|й|ям|ями|ях)?", "event"),
        (r"программ(?:а|ы|у|ой|е|ам|ами|ах)?", "program"),
        (r"семейн(?:ый|ая|ое|ых|ого|ому|ым|ыми)?", "family"),
        (r"праздник(?:а|у|ом|е|и|ов|ах)?", "celebration"),
        (r"день", "day"),
        (r"вечер(?:а|у|ом|е|и|ов|ах)?", "night"),
        (r"ноч(?:ь|и|ью|ей|ами)?", "night"),
    )
    for pattern, replacement in replacements:
        value = re.sub(rf"\b{pattern}\b", replacement, value, flags=re.I)

    translit = str.maketrans({
        "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"e","ж":"zh",
        "з":"z","и":"i","й":"y","к":"k","л":"l","м":"m","н":"n","о":"o",
        "п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f","х":"kh","ц":"ts",
        "ч":"ch","ш":"sh","щ":"shch","ъ":"","ы":"y","ь":"","э":"e","ю":"yu",
        "я":"ya",
    })
    value = value.translate(translit)
    value = re.sub(r"\bflavou?rs?\b", "flavour", value)
    value = re.sub(r"\bflavors?\b", "flavour", value)
    value = re.sub(r"\btrees\b", "tree", value)
    value = re.sub(r"\bolives\b", "olive", value)
    value = re.sub(r"\bmarkets\b", "market", value)
    value = re.sub(r"\bworkshops\b", "workshop", value)
    value = re.sub(r"\bexhibitions\b", "exhibition", value)
    return " ".join(value.split())


_IDENTITY_GENERIC = {
    "a", "an", "and", "at", "by", "for", "from", "in", "of", "on", "the", "to",
    "this", "with", "event", "events", "program", "programme", "schedule",
    "concert", "festival", "party", "night", "day", "celebration", "na",
}


def _identity_tokens(value: str) -> set[str]:
    import re
    return {
        token for token in re.findall(r"[a-z0-9]+", _identity_text(value))
        if token not in _IDENTITY_GENERIC and len(token) > 1
    }


def _identity_title_tokens(event: dict) -> set[str]:
    """Build semantic title tokens from the original source title only.

    The stored title is deliberately never translated. Identity is based on
    source title semantics plus structured event context, not a hidden
    translated copy in description.
    """
    return _identity_tokens(str(event.get("title", "") or ""))


def _identity_key(event: dict) -> str:
    import hashlib
    city = _identity_text(event.get("city", ""))
    venue = _identity_text(event.get("venue", ""))
    time = _identity_text(event.get("time", ""))
    title_tokens = _identity_title_tokens(event)
    title_tokens -= _identity_tokens(city)
    title_tokens -= _identity_tokens(venue)
    title_tokens -= _identity_tokens(time)
    parts = [
        str(event.get("date", "")).strip(),
        str(event.get("end_date") or event.get("date", "")).strip(),
        city,
        venue,
        time,
        " ".join(sorted(title_tokens)),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _event_key(event: dict) -> tuple:
    return (
        _identity_text(event.get("title", "")),
        event.get("date", ""),
        _identity_text(event.get("time", "")),
        _identity_text(event.get("venue", "")),
        _identity_text(event.get("city", "")),
    )


def _find_matching_event(conn: sqlite3.Connection, event: dict):
    identity = _identity_key(event)
    row = conn.execute(
        "SELECT * FROM events WHERE identity_key = ? LIMIT 1",
        (identity,),
    ).fetchone()
    if row:
        return row

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


def _event_semantic_score(event: dict) -> float:
    import re
    title = str(event.get("title") or "").strip()
    tokens = _identity_tokens(title)
    score = min(len(title), 160) / 160.0
    score += min(len(tokens), 10) * 0.08
    if re.search(r"\b(?:program|programme|schedule|мероприятий|мероприятия|программа)\b", title, re.I):
        score -= 0.35
    if len(title) < 8:
        score -= 0.25
    return score


def _find_fuzzy_event(conn: sqlite3.Connection, event: dict, exclude_id: int | None = None):
    """Find the same real-world event across languages and source formatting."""
    from difflib import SequenceMatcher
    import re

    city = _identity_text(event.get("city", ""))
    venue = _identity_text(event.get("venue", ""))
    time = _identity_text(event.get("time", ""))
    title_tokens = _identity_title_tokens(event)
    title_tokens -= _identity_tokens(city)
    title_tokens -= _identity_tokens(venue)
    title_tokens -= _identity_tokens(time)
    if not title_tokens:
        return None

    rows = conn.execute(
        """SELECT * FROM events
           WHERE date <= ? AND COALESCE(end_date, date) >= ?
           ORDER BY id""",
        (event.get("end_date") or event.get("date", ""), event.get("date", "")),
    ).fetchall()

    best = None
    best_score = 0.0
    event_ticket = _identity_text(event.get("ticket_url", ""))
    event_source = _identity_text(event.get("source_url", ""))

    for row in rows:
        if exclude_id is not None and row["id"] == exclude_id:
            continue
        other_tokens = _identity_title_tokens(dict(row))
        row_city = _identity_text(row["city"])
        row_venue = _identity_text(row["venue"])
        row_time = _identity_text(row["time"])
        row_ticket = _identity_text(row["ticket_url"])
        row_source = _identity_text(row["source_url"])

        # Structured identity outranks title wording.
        if event_ticket and row_ticket and event_ticket == row_ticket:
            best = row
            best_score = 1.50
            continue

        same_source_slot = (
            event.get("date", "") == row["date"]
            and (event.get("end_date") or event.get("date", "")) == (row["end_date"] or row["date"])
            and event_source and row_source and event_source == row_source
            and time == row_time
            and venue == row_venue
            and city == row_city
        )
        if same_source_slot and (title_tokens or other_tokens):
            best = row
            best_score = 1.35
            continue
        other_tokens -= _identity_tokens(row_city)
        other_tokens -= _identity_tokens(row_venue)
        other_tokens -= _identity_tokens(row_time)
        if not other_tokens:
            continue

        if city and row_city and city != row_city:
            continue
        venue_conflict = bool(venue and row_venue and venue != row_venue)
        time_conflict = bool(time and row_time and time != row_time)
        if time_conflict:
            continue

        intersection = len(title_tokens & other_tokens)
        overlap = intersection / max(1, min(len(title_tokens), len(other_tokens)))
        union = len(title_tokens | other_tokens)
        jaccard = intersection / max(1, union)
        sequence = SequenceMatcher(
            None,
            " ".join(sorted(title_tokens)),
            " ".join(sorted(other_tokens)),
        ).ratio()

        # A near-identical title on the same date/time/city is stronger
        # evidence than a venue string that differs between sources. This
        # catches cases like "Cyprus" vs "Village Square Paramali" for the
        # same festival and "Gymnasio Soleas" vs "Solea Gymnasium Evrychou".
        strong_title_match = overlap >= 0.95 or sequence >= 0.96
        if venue_conflict and not strong_title_match:
            continue

        context = 0.0
        if city and row_city and city == row_city:
            context += 0.08
        if venue and row_venue and venue == row_venue:
            context += 0.14
        if time and row_time and time == row_time:
            context += 0.10

        generic_fragment = bool(re.search(
            r"\b(?:program|programme|schedule|event|events|программа|мероприятий|мероприятия)\b",
            str(event.get("title") or ""), re.I
        ))
        other_generic_fragment = bool(re.search(
            r"\b(?:program|programme|schedule|event|events|программа|мероприятий|мероприятия)\b",
            str(row["title"] or ""), re.I
        ))
        subset_match = bool(title_tokens <= other_tokens or other_tokens <= title_tokens)

        score = max(overlap, jaccard * 1.15, sequence * 0.92)
        score += context

        accept = (
            overlap >= 0.80
            or sequence >= 0.90
            or (subset_match and (generic_fragment or other_generic_fragment) and overlap >= 0.65)
        )
        if accept and score > best_score:
            best_score = score
            best = row

    return best


def _merge_event_categories(*events) -> tuple[str, str]:
    """Merge categories from every source instead of letting the last source win."""
    values = []
    for event in events:
        if not event:
            continue
        raw = event.get("categories", "") if hasattr(event, "get") else ""
        try:
            parsed = json.loads(raw) if raw else []
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = []
        if not isinstance(parsed, list):
            parsed = []
        for value in parsed:
            category = canonical_category(value)
            if category and category not in values:
                values.append(category)
        category = canonical_category(event.get("category", "")) if hasattr(event, "get") else ""
        if category and category not in values:
            values.append(category)
    if not values:
        values = ["✨ Другое"]
    return values[0], json.dumps(values, ensure_ascii=False)


def _merge_event_rows(conn: sqlite3.Connection, keeper, duplicate) -> None:
    keeper_dict = dict(keeper)
    duplicate_dict = dict(duplicate)
    merged_category, merged_categories = _merge_event_categories(keeper_dict, duplicate_dict)

    def choose(field: str) -> str:
        a = str(keeper_dict.get(field) or "").strip()
        b = str(duplicate_dict.get(field) or "").strip()
        if not a:
            return b
        if not b:
            return a
        if field == "title":
            return a if _event_semantic_score(keeper_dict) >= _event_semantic_score(duplicate_dict) else b
        if field == "description":
            return a if len(a) >= len(b) else b
        return a

    merged = dict(keeper_dict)
    for field in ("title", "description", "date", "end_date", "time", "venue", "city", "price", "ticket_url", "source_url", "image_url"):
        merged[field] = choose(field)
    merged["category"] = merged_category
    merged["categories"] = merged_categories

    merged_identity = _identity_key(merged)

    conn.execute(
        """UPDATE events SET
           title=?, description=?, category=?, categories=?, date=?, end_date=?, time=?,
           venue=?, city=?, price=?, ticket_url=?, source_url=?, image_url=?,
           content_hash=?, identity_key=?, last_seen_at=CURRENT_TIMESTAMP
           WHERE id=?""",
        (
            merged["title"], merged["description"], merged["category"], merged["categories"], merged["date"],
            merged["end_date"], merged["time"], merged["venue"], merged["city"],
            merged["price"], merged["ticket_url"], merged["source_url"], merged["image_url"],
            keeper_dict.get("content_hash") or duplicate_dict.get("content_hash"),
            merged_identity, keeper["id"],
        ),
    )

    conn.execute(
        """INSERT OR IGNORE INTO event_sources (event_id, source_id, source_url)
           SELECT ?, source_id, source_url FROM event_sources WHERE event_id = ?""",
        (keeper["id"], duplicate["id"]),
    )
    conn.execute("DELETE FROM event_sources WHERE event_id = ?", (duplicate["id"],))
    conn.execute("DELETE FROM events WHERE id = ?", (duplicate["id"],))


def deduplicate_events() -> int:
    """Persistently merge semantic duplicates already present in the database."""
    init_db()
    merged = 0
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM events ORDER BY date, id").fetchall()
        for row in rows:
            current = conn.execute("SELECT * FROM events WHERE id = ?", (row["id"],)).fetchone()
            if not current:
                continue
            match = _find_fuzzy_event(conn, dict(current), exclude_id=current["id"])
            if match and match["id"] != current["id"]:
                keeper, duplicate = (
                    (current, match)
                    if _event_semantic_score(dict(current)) >= _event_semantic_score(dict(match))
                    else (match, current)
                )
                _merge_event_rows(conn, keeper, duplicate)
                merged += 1
        for row in conn.execute("SELECT * FROM events").fetchall():
            conn.execute(
                "UPDATE events SET identity_key = ? WHERE id = ?",
                (_identity_key(dict(row)), row["id"]),
            )
        conn.commit()
    return merged


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

            # One source page can contain many events. Prefer an exact
            # title match, but also match a unique source/date/time/venue slot.
            # The latter is important when an old DB row has a translated title
            # and the parser now correctly stores the original title.
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

            if not existing and source:
                # Telegram/Instagram/Facebook posts often have a different
                # source_url for every post. Match a unique event slot within
                # the registered source so an old translated title can be
                # replaced by the original title on the next sync.
                slot_rows = conn.execute(
                    """SELECT e.* FROM events e
                       JOIN event_sources es ON es.event_id = e.id
                       WHERE es.source_id = ?
                         AND e.date = ?
                         AND COALESCE(e.time, '') = ?
                         AND COALESCE(e.venue, '') = ?""",
                    (
                        source["id"],
                        event.get("date", ""),
                        event.get("time", ""),
                        event.get("venue", ""),
                    ),
                ).fetchall()
                if len(slot_rows) == 1:
                    existing = slot_rows[0]

            if not existing:
                slot_rows = conn.execute(
                    """SELECT * FROM events
                       WHERE source_url = ?
                         AND date = ?
                         AND COALESCE(time, '') = ?
                         AND COALESCE(venue, '') = ?""",
                    (
                        source_url,
                        event.get("date", ""),
                        event.get("time", ""),
                        event.get("venue", ""),
                    ),
                ).fetchall()
                if len(slot_rows) == 1:
                    existing = slot_rows[0]

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
            match = by_hash or existing or _find_matching_event(conn, event) or _find_fuzzy_event(conn, event)
            identity_key = _identity_key(event)

            if match:
                merged_category, merged_categories = _merge_event_categories(dict(match), event)
            else:
                merged_category = canonical_category(event.get("category", "")) or "✨ Другое"
                try:
                    parsed_categories = json.loads(event.get("categories", "") or "[]")
                except (TypeError, ValueError, json.JSONDecodeError):
                    parsed_categories = []
                if not isinstance(parsed_categories, list):
                    parsed_categories = []
                parsed_categories = [canonical_category(value) for value in parsed_categories if canonical_category(value)]
                if merged_category not in parsed_categories:
                    parsed_categories.insert(0, merged_category)
                merged_categories = json.dumps(list(dict.fromkeys(parsed_categories)), ensure_ascii=False)

            merged_description = str(event.get("description", "") or "").strip()
            if match:
                previous_description = str(match["description"] or "").strip()
                if len(previous_description) > len(merged_description):
                    merged_description = previous_description

            values = (
                event.get("title", ""),
                merged_description,
                merged_category,
                merged_categories,
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
                identity_key,
            )

            if match:
                conn.execute(
                    """UPDATE events SET
                       title = ?, description = ?, category = ?, categories = ?, date = ?,
                       end_date = ?, time = ?, venue = ?, city = ?, price = ?,
                       ticket_url = ?, source_url = ?, image_url = ?, content_hash = ?,
                       identity_key = ?, last_seen_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    values + (match["id"],),
                )
                event_id = match["id"]
            else:
                cursor = conn.execute(
                    """INSERT INTO events
                       (title, description, category, categories, date, end_date, time, venue, city,
                        price, ticket_url, source_url, image_url, content_hash, identity_key)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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


def _title_stem(token: str) -> str:
    """Lightweight Russian/English stemming for cross-source title matching."""
    token = str(token or "").lower()
    suffixes = (
        "иями", "ями", "ами", "ого", "ему", "ому", "ими", "ыми", "ьев",
        "ов", "ев", "ей", "ый", "ий", "ой", "ые", "ие", "ых", "их",
        "ым", "им", "ую", "юю", "ая", "яя", "ое", "ее", "ам", "ям",
        "ах", "ях", "ом", "ем", "ing", "ers", "ies", "es", "ed", "ly",
        "s", "а", "я", "ы", "и", "ь", "у", "ю", "е", "о",
    )
    for suffix in suffixes:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[:-len(suffix)]
    return token


def _display_title_tokens(title: str) -> set[str]:
    import re

    value = re.sub(r"[^a-z0-9а-яё]+", " ", str(title).lower(), flags=re.I)
    generic = {
        "festival", "festivals", "фестиваль", "фестивал", "дни", "день",
        "мероприятие", "event", "events", "праздник",
    }
    return {
        _title_stem(token)
        for token in value.split()
        if len(token) >= 4 and token not in generic
    }


def _looks_like_duplicate_event(a: sqlite3.Row, b: sqlite3.Row) -> bool:
    from difflib import SequenceMatcher
    import re

    from datetime import date as date_type

    def normalize(value):
        return " ".join(
            re.sub(r"[^a-z0-9а-яё]+", " ", str(value or "").lower(), flags=re.I).split()
        )

    # Sources may encode the same festival as one day vs. a date range.
    try:
        a_start = date_type.fromisoformat(str(a["date"]))
        b_start = date_type.fromisoformat(str(b["date"]))
        a_end = date_type.fromisoformat(str(a["end_date"] or a["date"]))
        b_end = date_type.fromisoformat(str(b["end_date"] or b["date"]))
    except (TypeError, ValueError):
        return False
    if a_end < b_start or b_end < a_start:
        return False

    # Missing venue/time in one source should not prevent a match.
    # Venue/city conflicts remain strong evidence of different events, while a
    # time conflict can be a parser/source formatting error for festivals.
    venue_conflict = False
    city_conflict = False
    time_conflict = False
    generic_locations = {"cyprus", "limassol", "nicosia", "larnaca", "paphos"}

    for field in ("time", "venue", "city"):
        left_value = normalize(a[field])
        right_value = normalize(b[field])
        if left_value and right_value and left_value != right_value:
            if field == "time":
                time_conflict = True
            elif field == "venue":
                venue_conflict = True
            else:
                city_conflict = True

    venue_a = normalize(a["venue"])
    venue_b = normalize(b["venue"])
    if venue_a in generic_locations or venue_b in generic_locations:
        venue_conflict = False
    city_a = normalize(a["city"])
    city_b = normalize(b["city"])
    if city_a in generic_locations or city_b in generic_locations:
        city_conflict = False

    if venue_conflict or city_conflict:
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

    # A very strong title match is allowed to survive a conflicting time
    # (common when one catalogue assigns a default 07:00 time).
    if time_conflict:
        return overlap >= 0.75 or similarity >= 0.88

    return overlap >= 0.67 or similarity >= 0.84


def deduplicate_exact_events() -> int:
    """Merge exact cross-source copies while preserving source provenance."""
    import re

    def normalize(value):
        return " ".join(
            re.sub(r"[^a-z0-9а-яё]+", " ", str(value or "").lower(), flags=re.I).split()
        )

    def compatible(a, b):
        from datetime import date as date_type

        try:
            a_start = date_type.fromisoformat(str(a["date"]))
            b_start = date_type.fromisoformat(str(b["date"]))
            a_end = date_type.fromisoformat(str(a["end_date"] or a["date"]))
            b_end = date_type.fromisoformat(str(b["end_date"] or b["date"]))
        except (TypeError, ValueError):
            return False
        if a_end < b_start or b_end < a_start:
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

            def strong_context_match(candidate, current):
                if not compatible(candidate, current):
                    return False
                time_a = normalize(candidate["time"])
                time_b = normalize(current["time"])
                venue_a = normalize(candidate["venue"])
                venue_b = normalize(current["venue"])
                category_a = normalize(candidate["category"])
                category_b = normalize(current["category"])

                # A generic location such as "Cyprus" is not a useful venue.
                generic_venues = {"cyprus", "limassol", "nicosia", "larnaca", "paphos"}
                if venue_a in generic_venues:
                    venue_a = ""
                if venue_b in generic_venues:
                    venue_b = ""

                # Same date + exact time + exact venue + same category is a
                # strong cross-source fingerprint, even when one title is
                # translated and the other is English.
                return (
                    time_a and time_b and time_a == time_b
                    and venue_a and venue_b and venue_a == venue_b
                    and category_a and category_b and category_a == category_b
                )

            keeper = next(
                (
                    candidate
                    for candidate in keepers
                    if compatible(candidate, row)
                    and (
                        (
                            normalize(candidate["title"]) == title
                            and (
                                not normalize(candidate["time"])
                                or not normalize(row["time"])
                                or normalize(candidate["time"]) == normalize(row["time"])
                            )
                        )
                        or _looks_like_duplicate_event(candidate, row)
                        or strong_context_match(candidate, row)
                    )
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
    """Read the prepared event catalogue without mutating or fuzzy-filtering it.

    Deduplication belongs to the sync pipeline. Running fuzzy deduplication on
    every Telegram view can hide legitimate events that happen on the same
    day, at the same venue, or share generic title words.
    """
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
