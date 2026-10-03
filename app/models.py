"""Data helpers for source records."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    source_type: str
    comment: str = ""
    category: str = ""
    city: str = ""
    enabled: bool = True
