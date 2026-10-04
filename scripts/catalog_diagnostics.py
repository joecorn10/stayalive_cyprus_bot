"""Catalog quality diagnostics for event duplicates and category/title anomalies."""
import re
import sqlite3
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
    semantic_seen = {}
    for source in source_rows:
        url = str(source["url"] or "").strip()
        source_type = str(source["type"] or "").strip()
        key = (norm(url), source_type)
        if key in source_seen:
            previous = source_seen[key]
            print(
                f"SOURCE_DUPLICATE | {previous['id']} | {previous['name']} | {previous['url']} || "
                f"{source['id']} | {source['name']} | {source['url']}"
            )
        else:
            source_seen[key] = source

        semantic_key = None
        if source_type.casefold() == "instagram":
            match = re.search(r"instagram\.com/([^/?#]+)", url, re.I)
            if match:
                semantic_key = ("instagram", match.group(1).casefold())
        elif source_type.casefold() in {"telegram", "telegrampinned"}:
            match = re.search(r"t\.me/([^/?#]+)", url, re.I)
            if match:
                semantic_key = ("telegram", match.group(1).casefold())
        else:
            semantic_key = (source_type.casefold(), norm(source["name"]))

        if semantic_key in semantic_seen:
            previous = semantic_seen[semantic_key]
            print(
                f"SOURCE_SEMANTIC_DUPLICATE | {previous['id']} | {previous['name']} | {previous['url']} || "
                f"{source['id']} | {source['name']} | {source['url']}"
            )
        else:
            semantic_seen[semantic_key] = source

    print("CATEGORY_WITH_MULTIPLE_NAMES")
    category_titles = defaultdict(Counter)
    for row in rows:
        category_titles[row["category"] or "✨ Другое"][norm(row["title"])] += 1
    for category, titles in category_titles.items():
        variants = [title for title, count in titles.items() if count > 1]
        if variants:
            print(f"CATEGORY_REPEAT | {category} | {len(variants)} repeated normalized titles")
            for variant in variants[:30]:
                matches = [row for row in rows if (row["category"] or "✨ Другое") == category and norm(row["title"]) == variant]
                for row in matches:
                    print(
                        f"CATEGORY_REPEAT_ITEM | {category} | {variant} | "
                        f"id={row['id']} | {row['date']} | {norm(row['time'])} | "
                        f"{norm(row['venue'])} | {norm(row['city'])} | {row['title']}"
                    )

    # Compare stored categories with a fresh classifier pass for TODAY only.
    # This tells us whether the bot's "Nightlife · 2" is a real catalogue
    # count or a missed-classification problem.
    from datetime import date
    from app.sync import classify_event, _event_categories

    today = date.today().isoformat()
    today_rows = [
        row for row in rows
        if str(row["date"]) <= today <= str(row["end_date"] or row["date"])
    ]
    today_counts = Counter(
        category
        for row in today_rows
        for category in _event_categories(row)
    )
    print("TODAY_EVENT_COUNT", len(today_rows))
    print("TODAY_CATEGORY_COUNTS", dict(today_counts))
    print("TODAY_CLASSIFIER_MISSES")
    misses = 0
    for row in today_rows:
        predicted = classify_event(dict(row))
        stored = set(_event_categories(row))
        if "🪩 Nightlife" in predicted and "🪩 Nightlife" not in stored:
            misses += 1
            print(
                f"TODAY_NIGHTLIFE_MISS | id={row['id']} | "
                f"stored={','.join(sorted(stored))} | "
                f"predicted={','.join(predicted)} | "
                f"source={row['source_url']} | title={row['title']} | "
                f"description={row['description']} | venue={row['venue']}"
            )
    print("TODAY_CLASSIFIER_MISS_COUNT", misses)

    identity_groups = defaultdict(list)
    for row in rows:
        identity = str(row["identity_key"] or "").strip()
        if identity:
            identity_groups[identity].append(row)
    identity_duplicates = [items for items in identity_groups.values() if len(items) > 1]
    print("IDENTITY_KEY_DUPLICATES", len(identity_duplicates))
    for items in identity_duplicates[:50]:
        print(
            "IDENTITY_DUPLICATE | " +
            " || ".join(
                f"id={row['id']} | {row['date']} | {row['category']} | {row['title']} | {row['venue']} | {row['city']}"
                for row in items
            )
        )

if __name__ == "__main__":
    main()
