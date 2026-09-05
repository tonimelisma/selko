"""Re-fetch stored Gmail messages whose saved body never carried the message.

Why this exists
---------------
Before PR #381 the Gmail sync path stored the `text/plain` MIME part verbatim
and discarded `text/html`. For a `multipart/alternative` whose plain part is a
placeholder -- or absent entirely -- that left `body_text` holding nothing the
extractor could use, and the LLM was asked to find events in ~200 characters of
provider snippet.

#381 fixes new mail. It cannot fix history, because `reprocess_email` re-runs
extraction on stored data and never re-fetches from the provider. Clicking
Reprocess on such a row therefore appears to do nothing, forever. That is what
this tool is for: it re-fetches the message, re-parses it with the current
code, and upserts the result so a later reprocess has something to work with.

Outlook is not affected. Graph is asked for
`Prefer: outlook.body-content-type="text"` and renders HTML server-side, so its
stored bodies were never starved.

Safety
------
Dry run is the default; `--apply` is required to write. The write goes through
`save_email_with_attachment_descriptors`, whose ON CONFLICT DO UPDATE is
restricted to content columns and does not touch `processing_status`,
`attempts`, `lock_generation`, `locked_by` or `processed_at`. Re-extraction
happens only with `--reprocess`, through the ordinary `reprocess_email` RPC.
"""

import sys
from typing import Any, Optional

import typer
from rich.console import Console
from rich.table import Table

sys.path.insert(0, str(__file__ + "/../.."))

from selko.config import load_config
from selko.services.auth import get_service_client
from selko.services.emails import parse_gmail_message
from selko.services.gmail import build_service, get_full_message
from selko.services.integrations import get_oauth_credentials

app = typer.Typer(help="Re-fetch Gmail messages whose stored body never carried the message")
console = Console()

# Content columns the save RPC will overwrite. Listed so --apply can state
# exactly what it touches rather than asking the operator to read SQL.
CONTENT_COLUMNS = (
    "thread_id, subject, from_email, from_name, to_emails, date_sent, snippet, "
    "provider_labels, has_attachments, body_text, is_calendar_invite, "
    "integration_id, provider_folder_ids, content_hash"
)


def is_starved(body_text: Optional[str], snippet: Optional[str]) -> bool:
    """Whether extraction saw less than the provider's own snippet.

    Covers both shapes the old sync path produced: no stored body at all, and a
    stored body that exists but says less than the snippet (the placeholder
    plain part). The comparison is against the snippet rather than a fixed
    length because a genuinely terse email is short and fine.
    """
    stored = (body_text or "").strip()
    preview = (snippet or "").strip()
    if not preview:
        return False
    return len(stored) < len(preview)


def describe_change(old_body: Optional[str], new_body: Optional[str]) -> tuple[bool, str]:
    """Whether a re-fetch is worth writing, and a one-line reason."""
    old_len = len((old_body or "").strip())
    new_len = len((new_body or "").strip())
    if new_len == 0:
        return False, "provider returned no usable body"
    if new_len <= old_len:
        return False, f"no improvement ({old_len} -> {new_len} chars)"
    return True, f"{old_len} -> {new_len} chars"


def _select_rows(client, user_id: str, email_id: Optional[str], limit: int) -> list[dict[str, Any]]:
    query = (
        client.table("emails")
        .select("id,provider_message_id,integration_id,subject,body_text,snippet,"
                "processing_outcome,email_provider")
        .eq("user_id", user_id)
        .eq("email_provider", "gmail")
    )
    if email_id:
        query = query.eq("id", email_id)
    result = query.order("date_sent", desc=True).limit(limit).execute()
    rows = result.data or []
    if email_id:
        # An explicitly named row is repaired on the operator's judgement, not
        # on the predicate -- they may know the body is stale for another reason.
        return rows
    return [r for r in rows if is_starved(r.get("body_text"), r.get("snippet"))]


@app.command()
def main(
    user_id: str = typer.Option(..., "--user-id", help="Owner of the emails to repair"),
    email_id: Optional[str] = typer.Option(None, "--email-id", help="Repair one specific email row"),
    limit: int = typer.Option(50, "--limit", help="Maximum rows to consider"),
    apply: bool = typer.Option(False, "--apply", help="Write the refreshed bodies (default: dry run)"),
    reprocess: bool = typer.Option(False, "--reprocess", help="Also requeue extraction for repaired rows"),
) -> None:
    config = load_config()
    client = get_service_client(config)

    console.print(f"[dim]environment: {getattr(config, 'environment', 'unknown')}[/dim]")
    rows = _select_rows(client, user_id, email_id, limit)
    if not rows:
        console.print("[green]Nothing to repair: no stored Gmail body is shorter than its snippet.[/green]")
        return

    creds = get_oauth_credentials(client, config, "gmail", user_id=user_id)
    if creds is None:
        console.print("[red]No Gmail credentials for this user.[/red]")
        raise typer.Exit(1)
    if creds.expired:
        console.print("[red]Gmail token is expired. Reauthorize before repairing.[/red]")
        raise typer.Exit(1)
    service = build_service(creds)

    table = Table(title=f"{len(rows)} candidate row(s)")
    table.add_column("subject", overflow="ellipsis", max_width=44)
    table.add_column("stored", justify="right")
    table.add_column("refetched", justify="right")
    table.add_column("action")

    repaired = 0
    for row in rows:
        subject = row.get("subject") or "(no subject)"
        try:
            parsed = parse_gmail_message(get_full_message(service, row["provider_message_id"]))
        except Exception as exc:  # message deleted, permission changed, transient
            table.add_row(subject, str(len(row.get("body_text") or "")), "-", f"[yellow]skipped: {exc}[/yellow]")
            continue

        worth_writing, reason = describe_change(row.get("body_text"), parsed.get("body_text"))
        stored_len = str(len((row.get("body_text") or "").strip()))
        new_len = str(len((parsed.get("body_text") or "").strip()))
        if not worth_writing:
            table.add_row(subject, stored_len, new_len, f"[dim]skip: {reason}[/dim]")
            continue
        if not apply:
            table.add_row(subject, stored_len, new_len, f"[cyan]would repair: {reason}[/cyan]")
            continue

        parsed["integration_id"] = row["integration_id"]
        components = parsed.pop("calendar_components", []) or []
        client.rpc("save_email_with_attachment_descriptors", {
            "p_user_id": user_id,
            "p_email": parsed,
            "p_descriptors": [],
            "p_calendar_components": components,
        }).execute()
        note = f"repaired: {reason}"
        if reprocess:
            client.rpc("reprocess_email", {"p_user_id": user_id, "p_email_id": row["id"]}).execute()
            note += ", requeued"
        repaired += 1
        table.add_row(subject, stored_len, new_len, f"[green]{note}[/green]")

    console.print(table)
    if apply:
        console.print(f"[green]Repaired {repaired} row(s).[/green] Columns written: {CONTENT_COLUMNS}")
        if not reprocess and repaired:
            console.print("[yellow]Bodies refreshed but not re-extracted. Pass --reprocess, or use Reprocess in the UI.[/yellow]")
    else:
        console.print("[cyan]Dry run. Pass --apply to write.[/cyan]")


if __name__ == "__main__":
    app()
