"""CLI tool for inspecting and managing dead-lettered items.

Dead-lettered items are emails, photos, or events that have permanently failed
processing after exhausting all retry attempts. This tool allows listing,
inspecting, and retrying such items.

Uses direct Supabase queries (no REST API server required).
"""

import sys
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

sys.path.insert(0, str(__file__ + "/../.."))

from selko.config import load_config
from selko.services.auth import get_authenticated_client

app = typer.Typer(help="Inspect and manage dead-lettered (permanently failed) items")
console = Console()

VALID_TYPES = {"emails", "photos", "events", "all"}
VALID_SINGULAR_TYPES = {"email", "photo", "event"}


def _resolve_partial_id(client, table: str, item_id: str) -> str:
    """Resolve a partial ID to a full UUID, or return the original if already full."""
    if len(item_id) >= 36:
        return item_id

    result = client.table(table).select("id").ilike("id", f"{item_id}%").execute()

    if not result.data:
        console.print(f"[red]No item found matching ID: {item_id}[/red]")
        raise typer.Exit(1)
    if len(result.data) > 1:
        console.print(f"[red]Ambiguous ID, matches {len(result.data)} items: {item_id}[/red]")
        for match in result.data:
            console.print(f"  [dim]{match['id']}[/dim]")
        raise typer.Exit(1)

    return result.data[0]["id"]


def _truncate(text: Optional[str], length: int = 40) -> str:
    """Truncate text to a maximum length with ellipsis."""
    if not text:
        return ""
    if len(text) <= length:
        return text
    return text[: length - 1] + "\u2026"


def _list_dead_emails(client) -> list:
    """Fetch dead-lettered emails."""
    result = (
        client.table("emails")
        .select(
            "id, from_email, subject, processing_error, dead_letter_reason, "
            "dead_letter_at, attempts, max_attempts"
        )
        .eq("processing_status", "failed")
        .not_.is_("dead_letter_at", "null")
        .order("dead_letter_at", desc=True)
        .limit(50)
        .execute()
    )
    return result.data


def _list_dead_photos(client) -> list:
    """Fetch dead-lettered photos."""
    result = (
        client.table("photos")
        .select(
            "id, filename, google_photo_id, processing_error, dead_letter_reason, "
            "dead_letter_at, attempts, max_attempts"
        )
        .eq("processing_status", "failed")
        .not_.is_("dead_letter_at", "null")
        .order("dead_letter_at", desc=True)
        .limit(50)
        .execute()
    )
    return result.data


def _list_dead_events(client) -> list:
    """Fetch dead-lettered events."""
    result = (
        client.table("events")
        .select(
            "id, title, status, sync_error, dead_letter_reason, "
            "dead_letter_at, sync_attempts, max_sync_attempts"
        )
        .eq("status", "sync_failed")
        .not_.is_("dead_letter_at", "null")
        .order("dead_letter_at", desc=True)
        .limit(50)
        .execute()
    )
    return result.data


def _display_emails_table(emails: list) -> None:
    """Display dead-lettered emails in a Rich table."""
    if not emails:
        console.print("[dim]No dead-lettered emails[/dim]")
        return

    table = Table(title="Dead-Lettered Emails")
    table.add_column("ID", style="cyan")
    table.add_column("From", style="green")
    table.add_column("Subject", style="white")
    table.add_column("Reason", style="red")
    table.add_column("Attempts", style="yellow", justify="center")
    table.add_column("Dead Letter At", style="dim")

    for email in emails:
        table.add_row(
            email["id"][:8],
            _truncate(email.get("from_email"), 25),
            _truncate(email.get("subject"), 35),
            _truncate(email.get("dead_letter_reason"), 30),
            f"{email.get('attempts', 0)}/{email.get('max_attempts', 3)}",
            (email.get("dead_letter_at") or "")[:19],
        )

    console.print(table)
    console.print(f"[dim]Total: {len(emails)} dead-lettered emails[/dim]")


def _display_photos_table(photos: list) -> None:
    """Display dead-lettered photos in a Rich table."""
    if not photos:
        console.print("[dim]No dead-lettered photos[/dim]")
        return

    table = Table(title="Dead-Lettered Photos")
    table.add_column("ID", style="cyan")
    table.add_column("Filename", style="green")
    table.add_column("Google ID", style="white")
    table.add_column("Reason", style="red")
    table.add_column("Attempts", style="yellow", justify="center")
    table.add_column("Dead Letter At", style="dim")

    for photo in photos:
        table.add_row(
            photo["id"][:8],
            _truncate(photo.get("filename"), 25),
            _truncate(photo.get("google_photo_id"), 20),
            _truncate(photo.get("dead_letter_reason"), 30),
            f"{photo.get('attempts', 0)}/{photo.get('max_attempts', 3)}",
            (photo.get("dead_letter_at") or "")[:19],
        )

    console.print(table)
    console.print(f"[dim]Total: {len(photos)} dead-lettered photos[/dim]")


def _display_events_table(events: list) -> None:
    """Display dead-lettered events in a Rich table."""
    if not events:
        console.print("[dim]No dead-lettered events[/dim]")
        return

    table = Table(title="Dead-Lettered Events")
    table.add_column("ID", style="cyan")
    table.add_column("Title", style="green")
    table.add_column("Reason", style="red")
    table.add_column("Attempts", style="yellow", justify="center")
    table.add_column("Dead Letter At", style="dim")

    for event in events:
        table.add_row(
            event["id"][:8],
            _truncate(event.get("title"), 35),
            _truncate(event.get("dead_letter_reason"), 30),
            f"{event.get('sync_attempts', 0)}/{event.get('max_sync_attempts', 3)}",
            (event.get("dead_letter_at") or "")[:19],
        )

    console.print(table)
    console.print(f"[dim]Total: {len(events)} dead-lettered events[/dim]")


@app.command("list")
def list_dead_letters(
    item_type: Optional[str] = typer.Argument(
        None, help="Filter by type: emails, photos, events, or all"
    ),
):
    """List dead-lettered items (permanently failed)."""
    if item_type is None:
        item_type = "all"

    item_type = item_type.lower()
    if item_type not in VALID_TYPES:
        console.print(
            f"[red]Invalid type: {item_type}. Must be one of: {', '.join(sorted(VALID_TYPES))}[/red]"
        )
        raise typer.Exit(1)

    config = load_config()
    client = get_authenticated_client(config)

    if item_type in ("emails", "all"):
        emails = _list_dead_emails(client)
        _display_emails_table(emails)
        if item_type == "all":
            console.print()

    if item_type in ("photos", "all"):
        photos = _list_dead_photos(client)
        _display_photos_table(photos)
        if item_type == "all":
            console.print()

    if item_type in ("events", "all"):
        events = _list_dead_events(client)
        _display_events_table(events)


@app.command()
def inspect(
    item_id: str = typer.Argument(help="ID (or partial ID) of the item"),
    item_type: str = typer.Argument(help="Type: email, photo, or event"),
):
    """Inspect a dead-lettered item in detail."""
    item_type = item_type.lower()
    if item_type not in VALID_SINGULAR_TYPES:
        console.print(
            f"[red]Invalid type: {item_type}. Must be one of: {', '.join(sorted(VALID_SINGULAR_TYPES))}[/red]"
        )
        raise typer.Exit(1)

    config = load_config()
    client = get_authenticated_client(config)

    # Map singular type to table name
    table_map = {"email": "emails", "photo": "photos", "event": "events"}
    table_name = table_map[item_type]

    # Resolve partial ID
    full_id = _resolve_partial_id(client, table_name, item_id)

    # Fetch full record
    result = client.table(table_name).select("*").eq("id", full_id).single().execute()
    record = result.data

    if not record:
        console.print(f"[red]Item not found: {full_id}[/red]")
        raise typer.Exit(1)

    # Display header
    if item_type == "email":
        title = f"Email: {record.get('subject', 'No subject')}"
    elif item_type == "photo":
        title = f"Photo: {record.get('filename', 'Unknown')}"
    else:
        title = f"Event: {record.get('title', 'Untitled')}"

    console.print(Panel(f"[bold]{title}[/bold]", subtitle=f"[dim]{full_id}[/dim]"))

    # Display all fields
    for key, value in record.items():
        if value is None:
            formatted_value = "[dim]null[/dim]"
        elif isinstance(value, str) and len(value) > 200:
            formatted_value = value[:200] + "\u2026"
        elif isinstance(value, (dict, list)):
            import json

            formatted_value = json.dumps(value, indent=2, default=str)
        else:
            formatted_value = str(value)

        console.print(f"  [cyan]{key}[/cyan]: {formatted_value}")


@app.command()
def retry(
    item_id: str = typer.Argument(help="ID (or partial ID) of the item"),
    item_type: str = typer.Argument(help="Type: email, photo, or event"),
):
    """Reset a dead-lettered item for reprocessing."""
    item_type = item_type.lower()
    if item_type not in VALID_SINGULAR_TYPES:
        console.print(
            f"[red]Invalid type: {item_type}. Must be one of: {', '.join(sorted(VALID_SINGULAR_TYPES))}[/red]"
        )
        raise typer.Exit(1)

    config = load_config()
    client = get_authenticated_client(config)

    # Map singular type to table name
    table_map = {"email": "emails", "photo": "photos", "event": "events"}
    table_name = table_map[item_type]

    # Resolve partial ID
    full_id = _resolve_partial_id(client, table_name, item_id)

    # Fetch the record to confirm it's dead-lettered
    if item_type == "event":
        result = (
            client.table(table_name)
            .select("id, title, status, dead_letter_at")
            .eq("id", full_id)
            .single()
            .execute()
        )
    elif item_type == "email":
        result = (
            client.table(table_name)
            .select("id, subject, processing_status, dead_letter_at")
            .eq("id", full_id)
            .single()
            .execute()
        )
    else:
        result = (
            client.table(table_name)
            .select("id, filename, processing_status, dead_letter_at")
            .eq("id", full_id)
            .single()
            .execute()
        )

    record = result.data
    if not record:
        console.print(f"[red]Item not found: {full_id}[/red]")
        raise typer.Exit(1)

    if not record.get("dead_letter_at"):
        console.print(f"[yellow]Item {full_id[:8]} is not dead-lettered[/yellow]")
        raise typer.Exit(1)

    # Display what we're about to retry
    if item_type == "email":
        label = record.get("subject", "No subject")
    elif item_type == "photo":
        label = record.get("filename", "Unknown")
    else:
        label = record.get("title", "Untitled")

    console.print(f"[bold]Retry {item_type}:[/bold] {label}")
    console.print(f"[dim]ID: {full_id}[/dim]")

    if not typer.confirm("Reset this item for reprocessing?"):
        console.print("[yellow]Cancelled[/yellow]")
        raise typer.Exit(0)

    # Perform the reset
    if item_type in ("email", "photo"):
        client.table(table_name).update(
            {
                "processing_status": "pending",
                "dead_letter_at": None,
                "dead_letter_reason": None,
                "processing_error": None,
                "locked_by": None,
                "locked_until": None,
                "next_retry_at": None,
                "attempts": 0,
            }
        ).eq("id", full_id).execute()
    elif item_type == "event":
        client.table(table_name).update(
            {
                "status": "approved",
                "dead_letter_at": None,
                "dead_letter_reason": None,
                "sync_error": None,
                "locked_by": None,
                "locked_until": None,
                "next_retry_at": None,
                "sync_attempts": 0,
            }
        ).eq("id", full_id).execute()

    console.print(f"[green]Reset {item_type} {full_id[:8]} for reprocessing[/green]")
    console.print("[dim]The item will be picked up by the next worker cycle.[/dim]")


if __name__ == "__main__":
    app()
