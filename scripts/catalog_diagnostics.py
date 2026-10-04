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
    exact_duplicates = []
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

    seen = {}
    for row in rows:
        key = (norm(row["title"]), row["date"], norm(row["time"]), norm(row["venue"]), norm(row["city"]))
        if key in seen:
            exact_duplicates.append((seen[key], row))
        else:
            seen[key] = row

    counts = Counter(row["category"] or "✨ Другое" for row in rows)
    print("CATALOG_TOTAL", len(rows))
    print("CATEGORY_COUNTS", dict(counts))
    print("EXACT_DUPLICATES", len(exact_duplicates))
    for left, right in exact_duplicates[:80]:
        print(
            f"EXACT_DUPLICATE | {left['id']} | {left['date']} | "
            f"{left['category']} | {left['title']} | {left['venue']} || "
            f"{right['id']} | {right['category']} | {right['title']} | {right['venue']}"
        )

    print("POSSIBLE_DUPLICATES", len(candidates))
    for sim, left, right in candidates[:80]:
        print(
            f"DUP_CANDIDATE | {sim:.2f} | {left['date']} | "
            f"{left['category']} | {left['title']} | {left['venue']} || "
            f"{right['category']} | {right['title']} | {right['venue']}"
        )

    source_rows = conn.execute(
        "SELECT id, name, url, type, enabled FROM sources ORDER BY name"
    ).fetchall()
    print("SOURCE_DUPLICATES")
    source_seen = {}
    for source in source_rows:
        key = (norm(source["url"]), source["type"])
        if key in source_seen:
            previous = source_seen[key]
            print(
                f"SOURCE_DUPLICATE | {previous['id']} | {previous['name']} | {previous['url']} || "
                f"{source['id']} | {source['name']} | {source['url']}"
            )
        else:
            source_seen[key] = source

    print("CATEGORY_WITH_MULTIPLE_NAMES")
    category_titles = defaultdict(Counter)
    for row in rows:
        category_titles[row["category"] or "✨ Другое"][norm(row["title"])] += 1
    for category, titles in category_titles.items():
        variants = [title for title, count in titles.items() if count > 1]
        if variants:
            print(f"CATEGORY_REPEAT | {category} | {len(variants)} repeated normalized titles")

if __name__ == "__main__":
    main()
