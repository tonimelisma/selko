#!/usr/bin/env python3
"""Re-parse ICS attachments on emails that predate calendar-component capture.

I5 of docs/specs/event-identity-reach.md.

Component capture reached production in the 2026-08-22 cutover. Every ICS-bearing
email ingested after it produced a component; the 18 ingested before it produced
none and were never backfilled. Their iCalendar UIDs are therefore absent from
the identity index, which is the one signal that resolves "the user already has
this" without asking an LLM.

Dry run is the default and prints a content-free plan: counts, ids, and which
emails would gain a component. `--apply` requires `--environment` to be stated
explicitly, so pointing this at production is a deliberate act rather than a
default.

This only ever adds components for emails that have none. It never edits an
existing component, never touches events, and never writes to a calendar
provider -- an empty parse leaves the email exactly as it was, which is the rule
`save_email_with_attachment_descriptors` already enforces for live acquisition.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from selko.config import load_config  # noqa: E402
from selko.services.ics_parser import parse_calendar_components  # noqa: E402
from selko.services.auth import get_service_client  # noqa: E402


def find_candidates(client) -> list[dict]:
    """Emails holding an .ics attachment but carrying no parsed component."""
    attachments = (
        client.table("attachments")
        .select("id,email_id,filename,mime_type,storage_path")
        .execute()
        .data
        or []
    )
    ics = [
        row
        for row in attachments
        if (row.get("filename") or "").lower().endswith(".ics")
        or "calendar" in (row.get("mime_type") or "").lower()
    ]
    if not ics:
        return []

    email_ids = sorted({row["email_id"] for row in ics if row.get("email_id")})
    existing = (
        client.table("email_calendar_components")
        .select("email_id")
        .in_("email_id", email_ids)
        .execute()
        .data
        or []
    )
    already = {row["email_id"] for row in existing}
    return [row for row in ics if row.get("email_id") not in already]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write components. Without this the run only reports.",
    )
    parser.add_argument(
        "--environment",
        choices=["development", "staging", "production"],
        help="required with --apply, so production is never a default",
    )
    args = parser.parse_args()

    if args.apply and not args.environment:
        parser.error("--apply requires --environment to be stated explicitly")

    config = load_config()
    client = get_service_client(config)

    candidates = find_candidates(client)
    print(f"emails with an .ics attachment and no component: {len(candidates)}")
    for row in candidates:
        # Content-free: ids and the fact of an attachment, never its contents.
        print(f"  email={row['email_id']} attachment={row['id']}")

    if not args.apply:
        print("\ndry run: nothing written. Re-run with --apply --environment <env>.")
        return 0

    print(f"\napplying to {args.environment}...")
    written = 0
    skipped = 0
    for row in candidates:
        payload = _download(client, row)
        if payload is None:
            skipped += 1
            continue
        components = parse_calendar_components([payload])
        if not components:
            # An empty parse must leave the email untouched: a malformed
            # attachment is not evidence that the email has no invite.
            skipped += 1
            continue
        for index, component in enumerate(components):
            client.table("email_calendar_components").insert({
                "email_id": row["email_id"],
                "component_index": index,
                **component,
            }).execute()
        written += 1

    print(json.dumps({"written": written, "skipped": skipped}, indent=2))
    return 0


def _download(client, attachment: dict) -> bytes | None:
    """Fetch stored attachment bytes, or None when they are unavailable."""
    path = attachment.get("storage_path")
    if not path:
        return None
    try:
        return client.storage.from_("attachments").download(path)
    except Exception as exc:  # pragma: no cover - network/storage shape
        print(f"  could not read attachment {attachment['id']}: {type(exc).__name__}")
        return None


if __name__ == "__main__":
    raise SystemExit(main())
