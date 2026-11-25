"""Release every lease at startup (02-data-layer.md §7.3).

Selko is one process, so a lease present when it starts belongs to a run that
died. The lifespan calls `reset_leases_at_startup` before any worker starts,
so no worker can take a lease that the reset would then clear.

Generations (``lock_generation``, ``lease_generation``, ``generation``) are not
reset: monotonic generations keep every fence valid.
"""

from __future__ import annotations

from selko.db.connection import Database
from selko.db.emails import _unlock_emails


def reset_leases_at_startup(db: Database) -> dict[str, int]:
    """One transaction; returns the rows changed per table for the startup log."""
    with db.write() as tx:
        now = tx.now_text
        emails_retried, emails_failed = _unlock_emails(tx, expired_only=False)
        counts = {
            "emails": emails_retried,
            "emails_failed": emails_failed,
            # As claim-time recovery does: attempts unchanged.
            "calendar_work_items": tx.execute(
                "UPDATE calendar_work_items SET status = 'pending', locked_by = NULL,"
                " locked_until = NULL, updated_at = ? WHERE status = 'processing'",
                (now,),
            ).rowcount,
            "email_ingestion_items": tx.execute(
                "UPDATE email_ingestion_items SET acquisition_status = 'retry', lease_owner = NULL,"
                " lease_expires_at = NULL, updated_at = ? WHERE acquisition_status = 'processing'",
                (now,),
            ).rowcount,
            "attachments": tx.execute(
                "UPDATE attachments SET ingestion_status = 'retry', locked_by = NULL,"
                " locked_until = NULL WHERE ingestion_status = 'processing'",
            ).rowcount,
            "integration_recoveries": tx.execute(
                "UPDATE integration_recoveries SET status = 'pending', locked_by = NULL,"
                " locked_until = NULL, updated_at = ? WHERE status = 'processing'",
                (now,),
            ).rowcount,
            "email_sync_state": tx.execute(
                "UPDATE email_sync_state SET lease_owner = NULL, lease_expires_at = NULL, updated_at = ?"
                " WHERE lease_owner IS NOT NULL OR lease_expires_at IS NOT NULL",
                (now,),
            ).rowcount,
            "email_sync_runs": tx.execute(
                "UPDATE email_sync_runs SET status = 'abandoned', completed_at = ? WHERE status = 'running'",
                (now,),
            ).rowcount,
        }
    return counts


__all__ = ["reset_leases_at_startup"]
