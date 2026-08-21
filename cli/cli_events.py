"""CLI tool for event management.

Uses direct Supabase queries and service calls (no REST API server required).
"""

import sys
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

sys.path.insert(0, str(__file__ + "/../.."))

from selko.config import load_config
from selko.services.auth import get_authenticated_client, get_current_user_id
from selko.services import calendars
from selko.services.events import derive_delivery_status

app = typer.Typer(help="Manage calendar events")
console = Console()


@app.command()
def new():
    """List events pending approval (New view)."""
    config = load_config()
    client = get_authenticated_client(config)

    result = client.table("events").select(
        "*, calendar_work_items(status, action, generation, failure_code)"
    ).eq("review_status", "pending_review").order("created_at", desc=True).execute()

    events = result.data

    if not events:
        console.print("[yellow]No pending events[/yellow]")
        return

    # Group by sender (using first event source's sender)
    # For simplicity, we'll just list them without grouping for now
    table = Table(title="Pending Events")
    table.add_column("ID", style="cyan")
    table.add_column("Title", style="green")
    table.add_column("Start", style="yellow")
    table.add_column("Location", style="dim")

    for event in events:
        table.add_row(
            event["id"][:8],
            event["title"],
            event.get("start_datetime", "No date") or "No date",
            (event.get("location") or "")[:30],
        )

    console.print(table)
    console.print(f"\n[dim]Total: {len(events)} pending events[/dim]")


@app.command()
def approved():
    """List approved/synced events (Approved view)."""
    config = load_config()
    client = get_authenticated_client(config)

    result = client.table("events").select(
        "*, calendar_work_items(status, action, generation, failure_code)"
    ).eq("review_status", "active").order("start_datetime", desc=False).execute()

    events = result.data

    if not events:
        console.print("[yellow]No approved events[/yellow]")
        return

    table = Table(title="Approved Events")
    table.add_column("ID", style="cyan")
    table.add_column("Title", style="green")
    table.add_column("Start", style="yellow")
    table.add_column("Status", style="magenta")

    for event in events:
        table.add_row(
            event["id"][:8],
            event["title"],
            event.get("start_datetime", "No date") or "No date",
            derive_delivery_status(event),
        )

    console.print(table)


@app.command()
def updates():
    """List change log (Updates view)."""
    config = load_config()
    client = get_authenticated_client(config)

    result = client.table("event_change_proposals").select(
        "*, events(*), event_sources(*, emails(*))"
    ).order("created_at", desc=True).limit(20).execute()

    updates_data = result.data

    if not updates_data:
        console.print("[yellow]No updates[/yellow]")
        return

    console.print("[bold]Event Updates & Changes[/bold]\n")

    for update in updates_data:
        event = update.get("events") or {}
        source = update.get("event_sources") or {}
        email = source.get("emails") or {}

        source_type = update.get("kind", "unknown")
        created_at = update.get("created_at", "")

        console.print(f"[cyan]{source_type.upper()}[/cyan] - {created_at}")
        console.print(f"  Event: {event.get('title', 'Unknown')}")
        console.print(f"  From: {email.get('from_name', 'Unknown')}")
        console.print("")


@app.command()
def approve(event_id: str):
    """Approve an event for calendar sync."""
    console.print("[yellow]Direct CLI approval was retired with S5. Use the web/API event action so calendar work is enqueued and fenced.[/yellow]")
    raise typer.Exit(2)


@app.command()
def reject(event_id: str):
    """Reject an event."""
    console.print("[yellow]Direct CLI rejection was retired with S5. Use the web/API event action so proposals are resolved atomically.[/yellow]")
    raise typer.Exit(2)


@app.command()
def restore(event_id: str):
    """Restore a rejected event to New."""
    console.print("[yellow]Direct CLI restore was retired with S5. Use the web/API history action so proposals and calendar work stay consistent.[/yellow]")
    raise typer.Exit(2)


@app.command()
def undo(source_id: str, event_id: Optional[str] = None):
    """Undo a specific email's contribution to an event.

    Args:
        source_id: Event source ID to undo.
        event_id: Optional event ID (if known).
    """
    if not event_id:
        console.print("[red]Error: event_id is required[/red]")
        console.print("[dim]Usage: uv run python -m cli.cli_events undo <source-id> --event-id <event-id>[/dim]")
        raise typer.Exit(1)

    console.print("[yellow]Direct source undo was retired with S5. Use the History/API action so the authoritative proposal is reopened.[/yellow]")
    raise typer.Exit(2)


@app.command()
def approve_sender(sender: str):
    """Auto-approve all events from a sender (domain or email).

    Args:
        sender: Email address or domain (e.g., "school.edu" or "calendar@school.edu")
    """
    config = load_config()
    client = get_authenticated_client(config)
    user_id = get_current_user_id(client)

    # Determine if it's domain or email
    if "@" in sender:
        data = {"user_id": user_id, "sender_email": sender, "action": "auto_approve"}
    else:
        data = {"user_id": user_id, "sender_domain": sender, "action": "auto_approve"}

    client.table("sender_rules").upsert(data).execute()

    console.print(f"[green]Auto-approving events from {sender}[/green]")


@app.command()
def ignore_sender(sender: str):
    """Ignore all events from a sender (domain or email).

    Note: This only ignores their email data contributions,
    not entire events (which may have multiple senders).

    Args:
        sender: Email address or domain (e.g., "school.edu" or "newsletter@school.edu")
    """
    config = load_config()
    client = get_authenticated_client(config)

    params = {"p_sender_email": sender if "@" in sender else None,
              "p_sender_domain": None if "@" in sender else sender}
    result = client.rpc("ignore_sender_and_reject_pending", params).execute()
    console.print(f"[yellow]Ignoring events from {sender}: {result.data}[/yellow]")


@app.command()
def list_rules():
    """List all sender rules."""
    config = load_config()
    client = get_authenticated_client(config)

    result = client.table("sender_rules").select("*").execute()
    rules = result.data

    if not rules:
        console.print("[yellow]No sender rules configured[/yellow]")
        return

    table = Table(title="Sender Rules")
    table.add_column("ID", style="cyan")
    table.add_column("Sender", style="green")
    table.add_column("Action", style="yellow")

    for rule in rules:
        rule_id = rule["id"][:8]
        sender = rule.get("sender_email") or rule.get("sender_domain", "Unknown")
        action = rule["action"]

        table.add_row(rule_id, sender, action)

    console.print(table)


@app.command()
def sync(event_id: str):
    """Sync an approved event to Google Calendar.

    Args:
        event_id: Event ID (or partial ID) to sync.
    """
    console.print("[yellow]Direct CLI calendar writes were retired with S5. Use the web/API sync action so calendar_work_items remain the sole provider-write owner.[/yellow]")
    raise typer.Exit(2)


@app.command()
def sync_all():
    """Sync all approved events to Google Calendar."""
    console.print("[yellow]Direct CLI calendar writes were retired with S5. Use the web/API sync action so calendar_work_items remain the sole provider-write owner.[/yellow]")
    raise typer.Exit(2)


if __name__ == "__main__":
    app()
