"""Base parser interface."""

from abc import ABC, abstractmethod


class EventParser(ABC):
    """Interface implemented by source-specific event parsers."""

    @abstractmethod
    def parse(self) -> list[dict]:
        """Return normalized event dictionaries."""
        raise NotImplementedError
