"""LogPlugin — logs match results to stdout. Default plugin, always configured."""

import logging

from app.notifications.base import MatchResult, NotificationPlugin

logger = logging.getLogger(__name__)


class LogPlugin(NotificationPlugin):
    """Logs match results to stdout. Default plugin, always configured."""

    async def is_configured(self) -> bool:
        return True

    async def send(self, match: MatchResult) -> bool:
        logger.info(
            "New matches for saved search '%s' (id=%d, user=%d): %d new listings: %s",
            match.search_name,
            match.saved_search_id,
            match.user_id,
            match.total_new,
            ", ".join(match.new_listing_titles[:5]),
        )
        return True
