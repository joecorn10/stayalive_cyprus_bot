"""Event synchronization entry point."""

from app.sync import sync_all


def main() -> None:
    added = sync_all()
    print(f"Event sync complete: {added} new events.")


if __name__ == "__main__":
    main()
