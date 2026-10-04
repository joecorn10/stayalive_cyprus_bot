"""Catalog quality diagnostics for event duplicates and category/title anomalies."""
import re
import sqlite3
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

DB = Path("events.db")

def norm(value):
    return " ".join(re.sub(r"[^a-z0-9а-яё]+", " ", str(value or "").lower(), flags=re.I).split())

def title_similarity(a, b):
    return SequenceMatcher(None, norm(a), norm(b)).ratio()

def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM events WHERE COALESCE(end_date,date) >= date('now') ORDER BY date,time,id"
    ).fetchall()

    by_day = defaultdict(list)
    for row in rows:
        by_day[row["date"]].append(row)

    candidates = []
    for day, items in by_day.items():
        for i, left in enumerate(items):
            for right in items[i + 1:]:
                if norm(left["title"]) == norm(right["title"]):
                    continue
                times = {norm(left["time"]), norm(right["time"])} - {""}
                venues = {norm(left["venue"]), norm(right["venue"])} - {""}
                if len(times) == 2 or len(venues) == 2:
                    continue
                sim = title_similarity(left["title"], right["title"])
                if sim >= 0.72:
                    candidates.append((sim, left, right))

    candidates.sort(key=lambda x: -x[0])

    counts = Counter(row["category"] or "✨ Другое" for row in rows)
    print("CATALOG_TOTAL", len(rows))
    print("CATEGORY_COUNTS", dict(counts))
    print("POSSIBLE_DUPLICATES", len(candidates))
    for sim, left, right in candidates[:80]:
        print(
            f"DUP_CANDIDATE | {sim:.2f} | {left['date']} | "
            f"{left['category']} | {left['title']} | {left['venue']} || "
            f"{right['category']} | {right['title']} | {right['venue']}"
        )

if __name__ == "__main__":
    main()
