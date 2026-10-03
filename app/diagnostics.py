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


# Raw HTML shape diagnostics
import requests
from bs4 import BeautifulSoup
resp = requests.get(URL, timeout=20, headers={"User-Agent": "StayAliveCyprusBot/1.0"})
soup = BeautifulSoup(resp.text, "html.parser")
raw_text = soup.get_text("\n")
report["http"] = {"status": resp.status_code, "content_length": len(resp.text)}
report["html_matches"] = {
    "october_lines": [x.strip() for x in raw_text.splitlines() if "October" in x][:30],
    "time_lines": [x.strip() for x in raw_text.splitlines() if "19:30" in x][:30],
    "russian_lines": [x.strip() for x in raw_text.splitlines() if "Русский" in x][:30],
}
Path("data/stantar_diagnostic.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(report["http"], ensure_ascii=False))
print(json.dumps(report["html_matches"], ensure_ascii=False, indent=2))

idx = raw_text.find("Русский Стендап")
report["html_matches"]["around_russian"] = raw_text.splitlines()[max(0, len(raw_text[:idx].splitlines())-8):len(raw_text[:idx].splitlines())+4]
idx = raw_text.find("Русский Стендап")
report["html_matches"]["around_russian"] = raw_text.splitlines()[max(0, len(raw_text[:idx].splitlines())-10):len(raw_text[:idx].splitlines())+8]
Path("data/stantar_diagnostic.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")

# trigger after parser fix

report["html_matches"]["raw_russian_html"] = resp.text[max(0, resp.text.find("Русский Стендап")-2500):resp.text.find("Русский Стендап")+1000]
Path("data/stantar_diagnostic.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")

# validate card parser

pos = resp.text.find("Sunday, 4 October")
report["html_matches"]["raw_sunday_html"] = resp.text[max(0,pos-1200):pos+500]
Path("data/stantar_diagnostic.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")

# validate nearest-date card parser

# final parser validation

# validate aria date parsing

# clean serialized validation
