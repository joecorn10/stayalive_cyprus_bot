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
    assert database._identity_tokens(a["title"]) == database._identity_tokens(b["title"])
    assert database._identity_key(a) == database._identity_key(b)


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
    assert database._identity_tokens(a["title"]) == database._identity_tokens(b["title"])
    assert database._identity_key(a) == database._identity_key(b)


def test_upsert_merges_translated_event():
    with tempfile.TemporaryDirectory() as tmp:
        database.DATABASE_PATH = Path(tmp) / "events.db"
        database.init_db()

        first = _event("Doros (Traditional Flavours Festival)", city="Doros")
        second = _event("Дорос (Фестиваль традиционных вкусов)", city="Doros")
        database.upsert_events([first])
        assert database.upsert_events([second]) == 0

        with database.get_connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_persistent_dedupe_merges_existing_semantic_duplicates():
    with tempfile.TemporaryDirectory() as tmp:
        database.DATABASE_PATH = Path(tmp) / "events.db"
        database.init_db()

        a = _event("A night of Jazz, Soul & Funk on the rooftop", time="16:00", venue="Rooftop")
        b = _event("Вечер джаза, соула и фанка на крыше", time="16:00", venue="Rooftop")
        database.upsert_events([a])

        b["content_hash"] = "different"
        b["identity_key"] = database._identity_key(b)
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


def test_title_category_beats_noisy_description():
    from app.sync import classify_event

    picnic = {
        "title": "Место для пикника Кавалларкас",
        "description": "Join us for music, dancing and a night of fun.",
        "category": "",
        "source_url": "",
        "venue": "",
    }
    theatre = {
        "title": "The Corridor. A Contemporary Dance Performance",
        "description": "An evening with music, DJs and a lively atmosphere.",
        "category": "",
        "source_url": "",
        "venue": "",
    }
    party = {
        "title": "Sunday Reunion",
        "description": "DJ set, house music and dancing all night long.",
        "category": "",
        "source_url": "",
        "venue": "",
    }

    assert classify_event(picnic) == ["🏃 Спорт и outdoor"]
    assert classify_event(theatre) == ["🎭 Театр и кино"]
    assert classify_event(party) == ["🪩 Nightlife"]


def test_semantic_dedupe_ignores_venue_formatting_when_title_is_exact():
    with tempfile.TemporaryDirectory() as tmp:
        database.DATABASE_PATH = Path(tmp) / "events.db"
        database.init_db()

        a = _event(
            "Фестиваль древних оливковых деревьев в деревне Парамали",
            time="08:00",
            venue="Cyprus",
            city="Cyprus",
        )
        b = _event(
            "Фестиваль древних оливковых деревьев в деревне Парамали",
            time="08:00",
            venue="Village Square Paramali",
            city="Cyprus",
        )
        database.upsert_events([a])
        b["content_hash"] = "different"
        b["identity_key"] = database._identity_key(b)
        with database.get_connection() as conn:
            conn.execute(
                """INSERT INTO events
                   (title, description, category, date, end_date, time, venue, city,
                    price, ticket_url, source_url, image_url, content_hash, identity_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                tuple(b[k] for k in (
                    "title", "description", "category", "date", "end_date", "time",
                    "venue", "city", "price", "ticket_url", "source_url", "image_url",
                    "content_hash", "identity_key",
                )),
            )
            conn.commit()

        assert database.deduplicate_events() == 1



def test_cleanup_expired_events_removes_only_finished_events():
    with tempfile.TemporaryDirectory() as tmp:
        database.DATABASE_PATH = Path(tmp) / "events.db"
        database.init_db()
        database.upsert_events([
            _event("Finished", date="2026-10-04"),
            _event("Today", date="2026-10-05"),
            _event("Future", date="2026-10-06"),
            _event("Multiday", date="2026-10-01", end_date="2026-10-05"),
        ])
        assert database.cleanup_expired_events("2026-10-05", dry_run=True) == 1
        with database.get_connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 4
        assert database.cleanup_expired_events("2026-10-05") == 1
        with database.get_connection() as conn:
            titles = {row[0] for row in conn.execute("SELECT title FROM events")}
            assert titles == {"Today", "Future", "Multiday"}


def test_cleanup_expired_events_removes_event_source_links():
    with tempfile.TemporaryDirectory() as tmp:
        database.DATABASE_PATH = Path(tmp) / "events.db"
        database.init_db()
        event = _event("Finished", date="2026-10-04")
        database.upsert_events([event])
        database.add_source("Test source", "https://example.com/source/", "Website")
        source = database.get_source_by_url("https://example.com/source/")
        assert source is not None
        with database.get_connection() as conn:
            event_id = conn.execute("SELECT id FROM events").fetchone()[0]
            conn.execute(
                "INSERT OR IGNORE INTO event_sources (event_id, source_id, source_url) VALUES (?, ?, ?)",
                (event_id, source["id"], source["url"]),
            )
            conn.commit()
        assert database.cleanup_expired_events("2026-10-05") == 1
        with database.get_connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM event_sources").fetchone()[0] == 0
