"""Notification plugin registry — module-level singleton."""

import logging

from app.notifications.base import MatchResult, NotificationPlugin

logger = logging.getLogger(__name__)


class NotificationRegistry:
    """Registry of active notification plugins. Singleton — import from here."""

    def __init__(self) -> None:
        self._plugins: list[NotificationPlugin] = []

    def register(self, plugin: NotificationPlugin) -> None:
        """Add a plugin to the registry."""
        self._plugins.append(plugin)

    async def dispatch(self, match: MatchResult) -> None:
        """Send match result to all configured plugins."""
        for plugin in self._plugins:
            if await plugin.is_configured():
                try:
                    await plugin.send(match)
                except Exception:
                    logger.exception(
                        "Plugin %s failed for search %s",
                        plugin.__class__.__name__,
                        match.search_name,
                    )


# Module-level singleton — import this, not from main.py
notification_registry = NotificationRegistry()
