"""Sender rules: matching, "ignore sender", and deleting a rule.

- `matching` is ``services/events.py:check_sender_rules``' two queries.
- `ignore_sender_and_reject_pending` ports the Postgres function of that name
  (docs/specs/sqlite-single-process/02-data-layer.md §2.5 #41, §5.6). The
  Postgres version is broken whenever the sender has a pending change: it calls
  ``reject_event_change_proposal`` with a 14th argument (a restore status) the
  13-argument function no longer takes. This port implements the evident
  intent -- record the rule, reject the sender's New-lane events, discard their
  pending changes restoring the snapshot -- in one transaction, without the
  obsolete argument (a pending proposal's event is ``active``, and rejecting the
  proposal does not change that decision).
- `delete_rule` carries the ``BEFORE DELETE`` trigger
  ``reset_skipped_emails_for_sender_rule`` (§2.10 #58) as Python: removing an
  ignore rule requeues the sender's mail skipped in the last 30 days, unless an
  equivalent ignore rule remains.

``LIKE '%@' || domain`` keeps Postgres semantics (case-sensitive, ``%``/``_``
wildcards) via `events.pg_like`; SQLite's ``LIKE`` folds ASCII case.
"""

from __future__ import annotations

import logging
from typing import Any

from selko.db import codec, errors
from selko.db.connection import Database
from selko.db.events import jtext, pg_bool, pg_like, pg_timestamp, reject_pending_in_tx
from selko.db.proposals import reject_event_change_proposal_in_tx

logger = logging.getLogger(__name__)

UNIGNORE_WINDOW_SECONDS = 30 * 86400


def _sender_matches(from_email: str | None, sender_email: str | None, sender_domain: str | None) -> bool:
    return ((sender_email is not None and from_email == sender_email)
            or (sender_domain is not None and pg_like(from_email, "%@" + sender_domain)))


def matching(db: Database, user_id: str, sender_email: str) -> dict[str, Any] | None:
    """The rule for an exact sender address, else for its domain, else None."""
    user_id = codec.to_id(user_id)  # type: ignore[assignment]
    row = db.query_one("SELECT * FROM sender_rules WHERE user_id = ? AND sender_email = ? LIMIT 1",
                       (user_id, sender_email))
    if row is not None:
        return dict(row)
    domain = sender_email.split("@")[-1] if "@" in sender_email else ""
    if domain:
        row = db.query_one("SELECT * FROM sender_rules WHERE user_id = ? AND sender_domain = ? LIMIT 1",
                           (user_id, domain))
        if row is not None:
            return dict(row)
    return None


def ignore_sender_and_reject_pending(
    db: Database, user_id: str | None, sender_email: str | None = None, sender_domain: str | None = None
) -> dict[str, int]:
    """Ignore a sender (address, or domain when no address) and clear what it put in review.

    Returns ``{"rejected_new": n, "discarded_changes": m}``.
    """
    if user_id is None:
        raise errors.NotOwned("not authenticated")
    if sender_email is None and sender_domain is None:
        raise errors.InvalidArgument("sender_email or sender_domain required")
    user_id = codec.to_id(user_id)  # type: ignore[assignment]
    with db.write() as tx:
        if sender_email is not None:
            tx.execute(
                "INSERT INTO sender_rules (id, user_id, sender_email, action, created_at, updated_at) "
                "VALUES (?, ?, ?, 'ignore', ?, ?) "
                "ON CONFLICT (user_id, sender_email) WHERE sender_email IS NOT NULL "
                "DO UPDATE SET action = 'ignore', updated_at = excluded.updated_at",
                (codec.new_id(), user_id, sender_email, tx.now_text, tx.now_text),
            )
        else:
            tx.execute(
                "INSERT INTO sender_rules (id, user_id, sender_domain, action, created_at, updated_at) "
                "VALUES (?, ?, ?, 'ignore', ?, ?) "
                "ON CONFLICT (user_id, sender_domain) WHERE sender_domain IS NOT NULL "
                "DO UPDATE SET action = 'ignore', updated_at = excluded.updated_at",
                (codec.new_id(), user_id, sender_domain, tx.now_text, tx.now_text),
            )

        # The New lane: every pending event with a source email from the sender.
        candidates = tx.execute(
            "SELECT DISTINCT s.event_id, m.from_email FROM event_sources s "
            "JOIN emails m ON m.id = s.email_id JOIN events e ON e.id = s.event_id "
            "WHERE m.user_id = ? AND e.user_id = ? AND e.review_status = 'pending_review'",
            (user_id, user_id),
        ).fetchall()
        new_ids = sorted({r["event_id"] for r in candidates
                          if _sender_matches(r["from_email"], sender_email, sender_domain)})
        rejected_new = 0
        for event_id in new_ids:
            rejected_new += reject_pending_in_tx(tx, user_id, event_id)

        # The Changes lane: discard each pending change from the sender,
        # restoring the event to the proposal's snapshot.
        rows = tx.execute(
            "SELECT p.id, p.event_id, p.event_snapshot_before, m.from_email, e.title, "
            "e.start_datetime, e.end_datetime, e.all_day, e.location, e.description, e.importance "
            "FROM event_change_proposals p JOIN events e ON e.id = p.event_id "
            "JOIN event_sources s ON s.id = p.source_id JOIN emails m ON m.id = s.email_id "
            "WHERE p.user_id = ? AND p.status = 'pending' AND e.review_status = 'active' "
            "ORDER BY p.created_at, p.id",
            (user_id,),
        ).fetchall()
        discarded = 0
        for row in rows:
            if not _sender_matches(row["from_email"], sender_email, sender_domain):
                continue
            snap = tx.schema.decode("event_change_proposals",
                                    {"event_snapshot_before": row["event_snapshot_before"]})["event_snapshot_before"]
            present = snap if isinstance(snap, dict) else {}
            start, end = jtext(snap, "start_datetime"), jtext(snap, "end_datetime")
            all_day = pg_bool(jtext(snap, "all_day"))
            reject_event_change_proposal_in_tx(
                tx, user_id, row["event_id"], row["id"], None, False,
                jtext(snap, "title") if jtext(snap, "title") is not None else row["title"],
                pg_timestamp(start) if start not in (None, "") else row["start_datetime"],
                pg_timestamp(end) if end not in (None, "") else row["end_datetime"],
                all_day if all_day is not None else (None if row["all_day"] is None else bool(row["all_day"])),
                jtext(snap, "location") if "location" in present else row["location"],
                jtext(snap, "description") if "description" in present else row["description"],
                jtext(snap, "importance") if jtext(snap, "importance") is not None else row["importance"],
                "repair_operator",
            )
            discarded += 1
    return {"rejected_new": rejected_new, "discarded_changes": discarded}


def delete_rule(db: Database, user_id: str, rule_id: str) -> bool:
    """Delete one of the user's rules; an ignore rule's recent skipped mail is requeued first.

    Returns False when the user has no such rule.
    """
    user_id = codec.to_id(user_id)  # type: ignore[assignment]
    with db.write() as tx:
        rule = tx.execute("SELECT * FROM sender_rules WHERE id = ? AND user_id = ?",
                          (codec.to_id(rule_id), user_id)).fetchone()
        if rule is None:
            return False
        if rule["action"] == "ignore":
            equivalent = tx.execute(
                "SELECT 1 FROM sender_rules WHERE user_id = ? AND action = 'ignore' AND id <> ? "
                "AND ((? IS NOT NULL AND sender_email = ?) OR (? IS NOT NULL AND sender_domain = ?)) LIMIT 1",
                (user_id, rule["id"], rule["sender_email"], rule["sender_email"],
                 rule["sender_domain"], rule["sender_domain"]),
            ).fetchone()
            if equivalent is None:
                since = tx.ts(-UNIGNORE_WINDOW_SECONDS)
                reset = ("UPDATE emails SET processing_status = 'pending', attempts = 0, "
                         "processing_error = NULL, locked_by = NULL, locked_until = NULL WHERE id = ?")
                count = 0
                if rule["sender_email"] is not None:
                    count += tx.execute(
                        "UPDATE emails SET processing_status = 'pending', attempts = 0, "
                        "processing_error = NULL, locked_by = NULL, locked_until = NULL "
                        "WHERE from_email = ? AND user_id = ? AND processing_status = 'skipped' "
                        "AND date_sent >= ?",
                        (rule["sender_email"], user_id, since),
                    ).rowcount
                if rule["sender_domain"] is not None:
                    skipped = tx.execute(
                        "SELECT id, from_email FROM emails WHERE user_id = ? AND processing_status = 'skipped' "
                        "AND date_sent >= ?", (user_id, since),
                    ).fetchall()
                    for email in skipped:
                        if pg_like(email["from_email"], "%@" + rule["sender_domain"]):
                            count += tx.execute(reset, (email["id"],)).rowcount
                if count > 0:
                    logger.info("Un-ignore: reset %s skipped emails for rule %s", count, rule["id"])
        tx.execute("DELETE FROM sender_rules WHERE id = ?", (rule["id"],))
    return True


__all__ = ["delete_rule", "ignore_sender_and_reject_pending", "matching"]
