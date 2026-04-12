"""Base classes for notification plugins."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class MatchResult:
    """Result of matching new listings against a saved search."""

    saved_search_id: int
    search_name: str
    user_id: int
    new_listing_ids: list[int]
    new_listing_titles: list[str]
    total_new: int


class NotificationPlugin(ABC):
    """Base class for notification delivery plugins."""

    @abstractmethod
    async def is_configured(self) -> bool:
        """Return True if this plugin has all required config to send."""
        ...

    @abstractmethod
    async def send(self, match: MatchResult) -> bool:
        """Send a notification for a match result. Return True on success."""
        ...
