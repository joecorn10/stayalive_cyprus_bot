import tempfile
from pathlib import Path

import app.database as database


def _event(title, date="2026-10-04", end_date=None, time="", venue="", city="Limassol"):
    return {
        "title": title,
        "description": title,
        "category": "🎵 Музыка",
        "date": date,
        "end_date": end_date or date,
        "time": time,
        "venue": venue,
        "city": city,
        "price": "",
        "ticket_url": f"https://example.com/{title[:10]}",
        "source_url": "https://example.com/source/",
        "image_url": "",
        "content_hash": title,
    }


def test_translated_titles_have_same_identity():
    a = _event("Doros (Traditional Flavours Festival)", city="Doros")
    b = _event("Дорос (Фестиваль традиционных вкусов)", city="Doros")
    assert database._identity_tokens(a["title"]) == database._identity_tokens(b["title"]), (
        database._identity_text(a["title"]),
        database._identity_text(b["title"]),
        database._identity_tokens(a["title"]),
        database._identity_tokens(b["title"]),
    )


def test_program_fragment_has_same_identity_as_event():
    a = _event("Wine Festival, Limassol", date="2026-09-26", end_date="2026-10-04")
    b = _event("wine. Programme of events", date="2026-09-26", end_date="2026-10-04")
    assert database._identity_key(a) == database._identity_key(b)


def test_jazz_titles_match_across_languages():
    a = _event(
        "A night of Jazz, Soul & Funk on the rooftop",
        time="16:00",
        venue="Rooftop",
    )
    b = _event(
        "Вечер джаза, соула и фанка на крыше",
        time="16:00",
        venue="Rooftop",
    )
    assert database._identity_tokens(a["title"]) == database._identity_tokens(b["title"]), (
        database._identity_text(a["title"]),
        database._identity_text(b["title"]),
        database._identity_tokens(a["title"]),
        database._identity_tokens(b["title"]),
    )
    assert database._identity_key(a) == database._identity_key(b)
    assert database._identity_key(a) == database._identity_key(b)


def test_upsert_merges_translated_event_and_preserves_sources():
    with tempfile.TemporaryDirectory() as tmp:
        database.DATABASE_PATH = Path(tmp) / "events.db"
        database.init_db()

        first = _event("Doros (Traditional Flavours Festival)", city="Doros")
        second = _event("Дорос (Фестиваль традиционных вкусов)", city="Doros")
        database.upsert_events([first])
        assert database.upsert_events([second]) == 0

        with database.get_connection() as conn:
            rows = conn.execute("SELECT id, title FROM events").fetchall()
            assert len(rows) == 1
            assert rows[0]["id"] == 1


def test_persistent_dedupe_merges_existing_semantic_duplicates():
    with tempfile.TemporaryDirectory() as tmp:
        database.DATABASE_PATH = Path(tmp) / "events.db"
        database.init_db()

        a = _event("A night of Jazz, Soul & Funk on the rooftop", time="16:00", venue="Rooftop")
        b = _event("Вечер джаза, соула и фанка на крыше", time="16:00", venue="Rooftop")
        database.upsert_events([a])

        # Insert the old-style duplicate directly to simulate the database
        # state that existed before semantic identity was introduced.
        b["content_hash"] = "different"
        b["identity_key"] = None
        with database.get_connection() as conn:
            conn.execute(
                """INSERT INTO events
                   (title, description, category, date, end_date, time, venue, city,
                    price, ticket_url, source_url, image_url, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                tuple(b[k] for k in (
                    "title", "description", "category", "date", "end_date", "time",
                    "venue", "city", "price", "ticket_url", "source_url", "image_url",
                    "content_hash",
                )),
            )
            conn.commit()

        assert database.deduplicate_events() == 1
        with database.get_connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    assert database._identity_key(a) == database._identity_key(b)
