#!/usr/bin/env python3
"""One-off cleanup for the 2026-07-13 review-incident production data.

The #183 deploy-window scan ingested 84 Outlook emails from Sent Items /
Deleted Items before the #184/#185 well-known-folder hardening landed. Their
provider_folder_ids point to folder rows that were later deleted by the
reconcile, so the emails (and the pending Selko events sourced only from
them) keep polluting the review list. Around the same window, the whole
mailbox was re-ingested when message IDs switched from mutable to immutable
format, producing duplicate pending events from the same underlying email.

For every user with an Outlook integration, this script:
  1. Finds "orphaned" Outlook emails — provider_folder_ids non-empty, but
     every entry is missing from the user's current email_folders.
  2. Rejects pending_review events whose non-undone email sources are ALL
     orphaned, and discards pending_change proposals whose active proposal's
     email source is orphaned (via selko.services.events.reject_pending_change,
     reusing the real undo/restore logic rather than reimplementing it).
  3. Neutralizes the orphaned emails (processing_status='skipped') so nothing
     reprocesses them.
  4. Rejects duplicate pending_review events (same title + start_datetime),
     keeping the oldest created_at row per group.
  5. Prints a per-user summary table.

Dry-run by default; pass --apply to write. Explicitly out of scope: deleting
the stale mutable-ID email rows, and touching integrations.sync_cursor.

Usage:
    ENVIRONMENT=staging uv run python scripts/cleanup_review_incident_20260713.py
    ENVIRONMENT=staging uv run python scripts/cleanup_review_incident_20260713.py --apply
    ENVIRONMENT=production uv run python scripts/cleanup_review_incident_20260713.py --apply
"""

import argparse
import sys
from collections import defaultdict
from typing import Any, Optional

from rich.console import Console
from rich.table import Table

from selko.config import load_config
from selko.services.auth import get_service_client
from selko.services.events import reject_pending_change

console = Console()


def find_orphaned_outlook_email_ids(
    emails: list[dict[str, Any]], known_folder_ids: set[str]
) -> list[str]:
    """An Outlook email is orphaned when it has provider_folder_ids and every
    one of them is missing from the user's current email_folders."""
    orphaned = []
    for email in emails:
        folder_ids = email.get("provider_folder_ids") or []
        if not folder_ids:
            continue
        if all(fid not in known_folder_ids for fid in folder_ids):
            orphaned.append(email["id"])
    return orphaned


def group_duplicate_pending_events(
    events: list[dict[str, Any]],
) -> list[tuple[str, list[str]]]:
    """Group pending_review events by (title, start_datetime).

    Returns (keep_id, [reject_ids]) for each group with more than one row,
    keeping the row with the oldest created_at.
    """
    groups: dict[tuple[Any, Any], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        key = (event.get("title"), event.get("start_datetime"))
        groups[key].append(event)

    duplicates = []
    for rows in groups.values():
        if len(rows) <= 1:
            continue
        rows_sorted = sorted(rows, key=lambda r: r.get("created_at") or "")
        keep_id = rows_sorted[0]["id"]
        reject_ids = [r["id"] for r in rows_sorted[1:]]
        duplicates.append((keep_id, reject_ids))
    return duplicates


def cleanup_user(client, user_id: str, apply: bool) -> dict[str, int]:
    summary = {
        "orphaned_emails": 0,
        "rejected_new_events": 0,
        "discarded_pending_changes": 0,
        "duplicate_groups": 0,
        "duplicate_events_rejected": 0,
    }

    folders_result = (
        client.table("email_folders")
        .select("provider_folder_id")
        .eq("user_id", user_id)
        .eq("provider", "outlook")
        .execute()
    )
    known_folder_ids = {
        row["provider_folder_id"]
        for row in (folders_result.data or [])
        if row.get("provider_folder_id")
    }

    emails_result = (
        client.table("emails")
        .select("id, provider_folder_ids")
        .eq("user_id", user_id)
        .eq("email_provider", "outlook")
        .execute()
    )
    orphaned_email_ids = find_orphaned_outlook_email_ids(
        emails_result.data or [], known_folder_ids
    )
    summary["orphaned_emails"] = len(orphaned_email_ids)
    orphaned_set = set(orphaned_email_ids)

    if orphaned_email_ids:
        events_result = (
            client.table("events")
            .select("id, status")
            .eq("user_id", user_id)
            .in_("status", ["pending_review", "pending_change"])
            .execute()
        )
        for event in events_result.data or []:
            sources_result = (
                client.table("event_sources")
                .select("email_id, source_type, created_at")
                .eq("event_id", event["id"])
                .eq("is_undone", False)
                .execute()
            )
            sources = sources_result.data or []
            email_sources = [s for s in sources if s.get("email_id")]

            if event["status"] == "pending_review":
                if email_sources and all(
                    s["email_id"] in orphaned_set for s in email_sources
                ):
                    summary["rejected_new_events"] += 1
                    if apply:
                        client.table("events").update({"status": "rejected"}).eq(
                            "id", event["id"]
                        ).execute()
            else:  # pending_change
                update_sources = [
                    s for s in sources if s.get("source_type") in ("update", "cancellation")
                ]
                if not update_sources:
                    continue
                latest = max(update_sources, key=lambda s: s.get("created_at") or "")
                if latest.get("email_id") in orphaned_set:
                    summary["discarded_pending_changes"] += 1
                    if apply:
                        reject_pending_change(client, event["id"])

        if apply:
            client.table("emails").update(
                {
                    "processing_status": "skipped",
                    "processing_explanation": (
                        "Ingested from an excluded folder (Sent/Deleted Items) "
                        "during the 2026-07-13 migration window"
                    ),
                }
            ).in_("id", orphaned_email_ids).execute()

    pending_review_result = (
        client.table("events")
        .select("id, title, start_datetime, created_at")
        .eq("user_id", user_id)
        .eq("status", "pending_review")
        .execute()
    )
    duplicates = group_duplicate_pending_events(pending_review_result.data or [])
    summary["duplicate_groups"] = len(duplicates)
    for _keep_id, reject_ids in duplicates:
        summary["duplicate_events_rejected"] += len(reject_ids)
        if apply:
            client.table("events").update({"status": "rejected"}).in_(
                "id", reject_ids
            ).execute()

    return summary


def print_summary(user_id: str, summary: dict[str, int], apply: bool) -> None:
    table = Table(title=f"User {user_id[:8]} ({'APPLIED' if apply else 'DRY RUN'})")
    table.add_column("Step", style="cyan")
    table.add_column("Count", style="yellow", justify="right")
    table.add_row("Orphaned Outlook emails found", str(summary["orphaned_emails"]))
    table.add_row("New-lane events rejected", str(summary["rejected_new_events"]))
    table.add_row("Pending changes discarded", str(summary["discarded_pending_changes"]))
    table.add_row("Duplicate groups found", str(summary["duplicate_groups"]))
    table.add_row("Duplicate events rejected", str(summary["duplicate_events_rejected"]))
    console.print(table)


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Write changes (default: dry run)"
    )
    args = parser.parse_args(argv)

    config = load_config()
    console.print(
        f"[bold]Environment:[/bold] {config.environment}  "
        f"[bold]Mode:[/bold] {'APPLY' if args.apply else 'DRY RUN'}"
    )

    if args.apply and config.environment == "production":
        if not input(
            "About to APPLY changes to PRODUCTION. Type 'yes' to continue: "
        ) == "yes":
            console.print("[yellow]Aborted.[/yellow]")
            sys.exit(0)

    client = get_service_client(config)

    integrations_result = (
        client.table("integrations").select("user_id").eq("provider", "outlook").execute()
    )
    user_ids = sorted({row["user_id"] for row in (integrations_result.data or [])})

    if not user_ids:
        console.print("[dim]No users with an Outlook integration found.[/dim]")
        return

    for user_id in user_ids:
        summary = cleanup_user(client, user_id, apply=args.apply)
        print_summary(user_id, summary, apply=args.apply)


if __name__ == "__main__":
    main()
