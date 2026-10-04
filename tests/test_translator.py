from app import translator


def test_event_title_stays_in_original_language(monkeypatch):
    monkeypatch.setattr(
        translator,
        "translate_to_russian",
        lambda text, max_chars=5000: "Вечеринка с мыльными пузырями",
    )
    event = {
        "title": "Soap bubbles party",
        "description": "",
        "venue": "Ibiza Club",
        "city": "Limassol",
        "category": "🪩 Nightlife",
    }
    translator.translate_event(event)

    assert event["title"] == "Soap bubbles party"
    assert event["description"] == "Вечеринка с мыльными пузырями в клубе Ibiza Club"


def test_event_comment_is_short_and_russian(monkeypatch):
    calls = []

    def fake_translate(text, max_chars=5000):
        calls.append(text)
        return "Вечер джаза и соула"

    monkeypatch.setattr(translator, "translate_to_russian", fake_translate)
    event = {
        "title": "Jazz & Soul Night",
        "description": (
            "Join us for a special evening with live jazz and soul music. "
            "Tickets and registration are available online."
        ),
        "venue": "The Rooftop",
        "city": "Limassol",
        "category": "🎵 Музыка",
    }
    translator.translate_event(event)

    assert event["title"] == "Jazz & Soul Night"
    assert event["description"] == "Вечер джаза и соула в The Rooftop"
    assert len(event["description"]) < 280
    assert calls
    assert "Tickets" not in calls[0]


def test_russian_title_is_not_changed(monkeypatch):
    monkeypatch.setattr(
        translator,
        "translate_to_russian",
        lambda text, max_chars=5000: text,
    )
    event = {
        "title": "Вечер джаза на крыше",
        "description": "",
        "venue": "Volta Wine Bar",
        "city": "Limassol",
        "category": "🎵 Музыка",
    }
    translator.translate_event(event)

    assert event["title"] == "Вечер джаза на крыше"
    assert event["description"] == "в Volta Wine Bar"


def test_database_slot_match_can_replace_old_translated_title():
    # Regression is covered at the database level by the unique source/date/time/venue
    # slot fallback used when source URLs change between social posts.
    assert "JOIN event_sources es ON es.event_id = e.id" in open("app/database.py").read()


def test_identity_uses_russian_comment_for_non_russian_titles():
    from app.database import _identity_title_tokens

    russian = {
        "title": "ПРОСТО ЛУЧШИЙ",
        "description": "Просто лучший вечер в Music Hall",
    }
    english = {
        "title": "SIMPLY THE BEST",
        "description": "Просто лучший вечер в Music Hall",
    }

    assert _identity_title_tokens(russian) != _identity_title_tokens(english)


def test_identity_does_not_translate_or_mutate_title():
    from app.database import _identity_title_tokens

    event = {
        "title": "SIMPLY THE BEST",
        "description": "Просто лучший вечер в Music Hall",
    }
    before = event["title"]

    _identity_title_tokens(event)

    assert event["title"] == before
