"""Quota service for rate limiting.

Tracks and enforces per-user daily usage quotas for LLM calls,
email syncs, and calendar syncs.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal, Optional

from supabase import Client

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


@dataclass
class UserUsage:
    """User's current usage for all quota types."""

    llm_calls_count: int
    llm_calls_limit: int
    llm_calls_remaining: int
    email_syncs_count: int
    email_syncs_limit: int
    email_syncs_remaining: int
    calendar_syncs_count: int
    calendar_syncs_limit: int
    calendar_syncs_remaining: int


class QuotaService:
    """Service for tracking and enforcing per-user daily usage quotas.

    Uses Supabase RPC functions for atomic check-and-increment operations
    to prevent race conditions in concurrent requests.
    """

    def __init__(self, client: Client):
        """Initialize QuotaService.

        Args:
            client: Supabase client (service role recommended for writes).
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
            # Call the atomic RPC function
            result = self.client.rpc(
                "check_and_increment_quota",
                {
                    "p_user_id": user_id,
                    "p_quota_type": quota_type,
                    "p_increment": increment,
                },
            ).execute()

            if not result.data or len(result.data) == 0:
                # No data returned, assume allowed with defaults
                logger.warning(f"No quota data returned for user {user_id}, allowing request")
                return QuotaCheckResult(
                    allowed=True,
                    current_count=increment,
                    limit=100,
                    remaining=99,
                )

            row = result.data[0]
            return QuotaCheckResult(
                allowed=row["allowed"],
                current_count=row["current_count"],
                limit=row["quota_limit"],
                remaining=row["remaining"],
            )

        except Exception as e:
            # On error, log but allow the request (fail-open for availability)
            logger.error(f"Quota check failed for user {user_id}: {e}")
            return QuotaCheckResult(
                allowed=True,
                current_count=0,
                limit=100,
                remaining=100,
            )

    def get_usage(
        self,
        user_id: str,
        for_date: Optional[date] = None,
    ) -> UserUsage:
        """Get user's current usage for all quota types.

        Args:
            user_id: User UUID.
            for_date: Date to get usage for (defaults to today).

        Returns:
            UserUsage with counts and limits for all quota types.
        """
        try:
            params = {"p_user_id": user_id}
            if for_date:
                params["p_date"] = for_date.isoformat()

            result = self.client.rpc("get_user_quota_usage", params).execute()

            if not result.data or len(result.data) == 0:
                # No usage data, return defaults
                return UserUsage(
                    llm_calls_count=0,
                    llm_calls_limit=100,
                    llm_calls_remaining=100,
                    email_syncs_count=0,
                    email_syncs_limit=50,
                    email_syncs_remaining=50,
                    calendar_syncs_count=0,
                    calendar_syncs_limit=100,
                    calendar_syncs_remaining=100,
                )

            row = result.data[0]
            return UserUsage(
                llm_calls_count=row["llm_calls_count"],
                llm_calls_limit=row["llm_calls_limit"],
                llm_calls_remaining=row["llm_calls_remaining"],
                email_syncs_count=row["email_syncs_count"],
                email_syncs_limit=row["email_syncs_limit"],
                email_syncs_remaining=row["email_syncs_remaining"],
                calendar_syncs_count=row["calendar_syncs_count"],
                calendar_syncs_limit=row["calendar_syncs_limit"],
                calendar_syncs_remaining=row["calendar_syncs_remaining"],
            )

        except Exception as e:
            logger.error(f"Failed to get usage for user {user_id}: {e}")
            # Return defaults on error
            return UserUsage(
                llm_calls_count=0,
                llm_calls_limit=100,
                llm_calls_remaining=100,
                email_syncs_count=0,
                email_syncs_limit=50,
                email_syncs_remaining=50,
                calendar_syncs_count=0,
                calendar_syncs_limit=100,
                calendar_syncs_remaining=100,
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
            max_result = (
                self.client.table("global_limits")
                .select("max_allowed")
                .eq("limit_type", f"{quota_type}_daily")
                .single()
                .execute()
            )
            max_allowed = max_result.data.get("max_allowed", 1000)
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

        # Upsert today's quota row with new limit
        today = date.today().isoformat()
        try:
            self.client.table("usage_quotas").upsert(
                {
                    "user_id": user_id,
                    "date": today,
                    limit_col: new_limit,
                },
                on_conflict="user_id,date",
            ).execute()
            logger.info(f"Set {quota_type} limit to {new_limit} for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to set limit: {e}")
            raise


def get_quota_service(client: Client) -> QuotaService:
    """Factory function to create QuotaService.

    Args:
        client: Supabase client.

    Returns:
        Configured QuotaService instance.
    """
    return QuotaService(client)
