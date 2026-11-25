"""Quota service for rate limiting.

Tracks and enforces per-user daily usage quotas for LLM calls,
email syncs, and calendar syncs.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal

from selko.db import quotas as db_quotas
from selko.db.connection import Database

Client = Database

logger = logging.getLogger(__name__)

QuotaType = Literal["llm_calls", "email_syncs", "calendar_syncs"]


class QuotaExceededError(Exception):
    """Raised when a user exceeds their usage quota."""

    def __init__(
        self,
        quota_type: str,
        current_count: int,
        limit: int,
        message: str = None,
    ):
        self.quota_type = quota_type
        self.current_count = current_count
        self.limit = limit
        self.message = message or f"Quota exceeded for {quota_type}: {current_count}/{limit}"
        super().__init__(self.message)


@dataclass
class QuotaCheckResult:
    """Result of a quota check operation."""

    allowed: bool
    current_count: int
    limit: int
    remaining: int

    @property
    def resets_at(self) -> str:
        """Return midnight UTC as ISO string for next quota reset."""
        # Next midnight UTC
        tomorrow = date.today()
        # Get tomorrow's date at midnight UTC
        from datetime import timedelta

        tomorrow_midnight = datetime.combine(
            tomorrow + timedelta(days=1),
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
        return tomorrow_midnight.isoformat()


class QuotaService:
    """Service for tracking and enforcing per-user daily usage quotas.

    Check-and-increment is one write transaction on the single writer, so
    concurrent requests cannot both spend the last unit of a quota.
    """

    def __init__(self, client: Client):
        """Initialize QuotaService.

        Args:
            client: The process database.
        """
        self.client = client

    def check_and_increment(
        self,
        user_id: str,
        quota_type: QuotaType,
        increment: int = 1,
    ) -> QuotaCheckResult:
        """Atomically check quota and increment if allowed.

        This is the primary method for enforcing rate limits. It checks if
        the user has remaining quota and atomically increments the count
        if allowed.

        Args:
            user_id: User UUID.
            quota_type: Type of quota ('llm_calls', 'email_syncs', 'calendar_syncs').
            increment: Amount to increment (default 1).

        Returns:
            QuotaCheckResult with allowed status and current counts.

        Example:
            result = quota_service.check_and_increment(user_id, "llm_calls")
            if not result.allowed:
                raise HTTPException(429, "Quota exceeded")
        """
        try:
            row = db_quotas.check_and_increment_quota(
                self.client, user_id, quota_type, increment
            )
            return QuotaCheckResult(
                allowed=row["allowed"],
                current_count=row["current_count"],
                limit=row["quota_limit"],
                remaining=row["remaining"],
            )

        except Exception as e:
            # Alarmed fail-open: allow the request for availability, but log
            # at ERROR with structured fields so monitoring can alert on it
            logger.error(
                "QUOTA_SERVICE_ERROR: Quota check failed, allowing request "
                "(fail-open for availability)",
                extra={
                    "error_code": "QUOTA_SERVICE_ERROR",
                    "user_id": user_id,
                    "quota_type": quota_type,
                    "error": str(e),
                },
            )
            return QuotaCheckResult(
                allowed=True,
                current_count=0,
                limit=100,
                remaining=100,
            )

    def set_user_limit(
        self,
        user_id: str,
        quota_type: QuotaType,
        new_limit: int,
    ) -> None:
        """Set a custom limit for a user (admin operation).

        This allows upgrading users to higher tiers or applying
        temporary limit increases.

        Args:
            user_id: User UUID.
            quota_type: Type of quota to update.
            new_limit: New limit value.

        Raises:
            ValueError: If limit exceeds global max_allowed.
        """
        # Map quota type to column name
        limit_col_map = {
            "llm_calls": "llm_calls_limit",
            "email_syncs": "email_syncs_limit",
            "calendar_syncs": "calendar_syncs_limit",
        }
        limit_col = limit_col_map.get(quota_type)
        if not limit_col:
            raise ValueError(f"Invalid quota type: {quota_type}")

        # Check against global max
        try:
            max_allowed = db_quotas.max_allowed(self.client, f"{quota_type}_daily")
            if max_allowed is None:
                raise LookupError(f"no global max for {quota_type}_daily")
            if new_limit > max_allowed:
                raise ValueError(
                    f"Limit {new_limit} exceeds maximum allowed {max_allowed}"
                )
        except ValueError:
            # Re-raise ValueError (limit exceeded) - don't suppress
            raise
        except Exception as e:
            logger.warning(f"Could not verify max limit: {e}")
            # Allow setting if we can't verify

        # Upsert today's (UTC, the quota day) row with the new limit
        try:
            db_quotas.set_user_limit(self.client, user_id, quota_type, new_limit)
            logger.info(f"Set {quota_type} limit to {new_limit} for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to set limit: {e}")
            raise


def get_quota_service(client: Client) -> QuotaService:
    """Factory function to create QuotaService.

    Args:
        client: The process database.

    Returns:
        Configured QuotaService instance.
    """
    return QuotaService(client)
