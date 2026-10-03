"""One-shot Stantar Kkomety pipeline diagnostic."""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from app.parsers.website import WebsiteParser
from app.sync import _normalize, canonical_category

URL = "https://stantarkkomety.com/festival/tickets"

raw = WebsiteParser(URL).parse()
normalized = _normalize([dict(event) for event in raw])

db = sqlite3.connect("events.db")
db.row_factory = sqlite3.Row
rows = db.execute(
    """SELECT id,title,category,date,end_date,time,venue,city,source_url
       FROM events
       WHERE date BETWEEN '2026-10-03' AND '2026-10-05'
          OR title LIKE '%Стендап%'
          OR title LIKE '%Stand-up%'
          OR title LIKE '%comedy%'
       ORDER BY date,time,title"""
).fetchall()

report = {
    "generated_at_utc": datetime.utcnow().isoformat() + "Z",
    "parser_count": len(raw),
    "normalized_count": len(normalized),
    "parser_oct4": [
        {k: e.get(k) for k in ("title","date","end_date","time","venue","city","category","source_url")}
        for e in normalized if e.get("date") == "2026-10-04"
    ],
    "db_rows_relevant": [dict(r) for r in rows],
    "db_comedy_rows": [
        dict(r) for r in rows if canonical_category(r["category"]) == "🎭 Comedy"
    ],
    "checks": {
        "parser_has_oct4": any(e.get("date") == "2026-10-04" for e in normalized),
        "parser_has_russian_show": any("Русский Стендап" in str(e.get("title")) for e in normalized),
        "parser_classifies_comedy": any(
            "Русский Стендап" in str(e.get("title")) and e.get("category") == "🎭 Comedy"
            for e in normalized
        ),
        "db_has_oct4": any(r["date"] == "2026-10-04" for r in rows),
        "db_has_comedy": any(canonical_category(r["category"]) == "🎭 Comedy" for r in rows),
    },
}

Path("data/stantar_diagnostic.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(json.dumps(report, ensure_ascii=False, indent=2))

# trigger diagnostic
