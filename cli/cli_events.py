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

app = typer.Typer(help="Manage calendar events")
console = Console()


@app.command()
def new():
    """List events pending approval (New view)."""
    config = load_config()
    client = get_authenticated_client(config)

    result = client.table("events").select("*").eq(
        "status", "pending_review"
    ).order("created_at", desc=True).execute()

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

    result = client.table("events").select("*").in_(
        "status", ["approved", "synced"]
    ).order("start_datetime", desc=False).execute()

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
            event["status"],
        )

    console.print(table)


@app.command()
def updates():
    """List change log (Updates view)."""
    config = load_config()
    client = get_authenticated_client(config)

    # Get event sources with related events and emails
    result = client.table("event_sources").select(
        "*, events(*), emails(*)"
    ).order("created_at", desc=True).limit(20).execute()

    updates_data = result.data

    if not updates_data:
        console.print("[yellow]No updates[/yellow]")
        return

    console.print("[bold]Event Updates & Changes[/bold]\n")

    for update in updates_data:
        event = update.get("events") or {}
        email = update.get("emails") or {}

        source_type = update.get("source_type", "unknown")
        created_at = update.get("created_at", "")

        console.print(f"[cyan]{source_type.upper()}[/cyan] - {created_at}")
        console.print(f"  Event: {event.get('title', 'Unknown')}")
        console.print(f"  From: {email.get('from_name', 'Unknown')}")
        console.print("")


@app.command()
def approve(event_id: str):
    """Approve an event for calendar sync."""
    config = load_config()
    client = get_authenticated_client(config)

    # Find the event (handle partial ID)
    if len(event_id) < 36:
        result = client.table("events").select("id").ilike(
            "id", f"{event_id}%"
        ).execute()
        if not result.data:
            console.print(f"[red]Event not found: {event_id}[/red]")
            raise typer.Exit(1)
        if len(result.data) > 1:
            console.print(f"[red]Ambiguous ID, matches multiple events: {event_id}[/red]")
            raise typer.Exit(1)
        event_id = result.data[0]["id"]

    # Update status
    client.table("events").update({
        "status": "approved"
    }).eq("id", event_id).execute()

    console.print(f"[green]Approved event {event_id[:8]}[/green]")
    console.print("[dim]Run 'sync' command to sync to calendar.[/dim]")


@app.command()
def reject(event_id: str):
    """Reject an event."""
    config = load_config()
    client = get_authenticated_client(config)

    # Find the event (handle partial ID)
    if len(event_id) < 36:
        result = client.table("events").select("id").ilike(
            "id", f"{event_id}%"
        ).execute()
        if not result.data:
            console.print(f"[red]Event not found: {event_id}[/red]")
            raise typer.Exit(1)
        if len(result.data) > 1:
            console.print(f"[red]Ambiguous ID, matches multiple events: {event_id}[/red]")
            raise typer.Exit(1)
        event_id = result.data[0]["id"]

    # Update status
    client.table("events").update({
        "status": "rejected"
    }).eq("id", event_id).execute()

    console.print(f"[yellow]Rejected event {event_id[:8]}[/yellow]")


@app.command()
def restore(event_id: str):
    """Restore a rejected event to New."""
    config = load_config()
    client = get_authenticated_client(config)

    # Find the event (handle partial ID)
    if len(event_id) < 36:
        result = client.table("events").select("id").ilike(
            "id", f"{event_id}%"
        ).execute()
        if not result.data:
            console.print(f"[red]Event not found: {event_id}[/red]")
            raise typer.Exit(1)
        if len(result.data) > 1:
            console.print(f"[red]Ambiguous ID, matches multiple events: {event_id}[/red]")
            raise typer.Exit(1)
        event_id = result.data[0]["id"]

    # Update status
    client.table("events").update({
        "status": "pending_review"
    }).eq("id", event_id).execute()

    console.print(f"[green]Restored event {event_id[:8]} to pending review[/green]")


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

    config = load_config()
    client = get_authenticated_client(config)

    # Delete the event source
    client.table("event_sources").delete().eq(
        "id", source_id
    ).eq("event_id", event_id).execute()

    console.print(f"[green]Undid source {source_id[:8]}[/green]")


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
    user_id = get_current_user_id(client)

    # Determine if it's domain or email
    if "@" in sender:
        data = {"user_id": user_id, "sender_email": sender, "action": "ignore"}
    else:
        data = {"user_id": user_id, "sender_domain": sender, "action": "ignore"}

    client.table("sender_rules").upsert(data).execute()

    console.print(f"[yellow]Ignoring events from {sender}[/yellow]")
    console.print("[dim]Note: Only ignores their email contributions, not entire events.[/dim]")


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
    config = load_config()
    client = get_authenticated_client(config)
    user_id = get_current_user_id(client)

    # Find the event (handle partial ID)
    if len(event_id) < 36:
        result = client.table("events").select("id, status").ilike(
            "id", f"{event_id}%"
        ).execute()
        if not result.data:
            console.print(f"[red]Event not found: {event_id}[/red]")
            raise typer.Exit(1)
        if len(result.data) > 1:
            console.print(f"[red]Ambiguous ID, matches multiple events: {event_id}[/red]")
            raise typer.Exit(1)
        event_data = result.data[0]
        event_id = event_data["id"]
    else:
        result = client.table("events").select("id, status").eq(
            "id", event_id
        ).single().execute()
        event_data = result.data

    # Check status
    status = event_data.get("status")
    if status not in ("approved", "synced", "sync_failed"):
        console.print(f"[red]Event must be approved before syncing (current status: {status})[/red]")
        raise typer.Exit(1)

    try:
        gcal_id = calendars.sync_event_to_calendar(client, user_id, event_id)
        console.print(f"[green]Synced event {event_id[:8]} to Google Calendar[/green]")
        console.print(f"[dim]Calendar event ID: {gcal_id}[/dim]")
    except calendars.CalendarsError as e:
        console.print(f"[red]Sync failed: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def sync_all():
    """Sync all approved events to Google Calendar."""
    config = load_config()
    client = get_authenticated_client(config)
    user_id = get_current_user_id(client)

    # Find all approved events
    result = client.table("events").select("id, title").eq(
        "status", "approved"
    ).execute()

    events = result.data

    if not events:
        console.print("[yellow]No approved events to sync[/yellow]")
        return

    console.print(f"[bold]Syncing {len(events)} events to Google Calendar...[/bold]\n")

    success_count = 0
    fail_count = 0

    for event in events:
        event_id = event["id"]
        title = event["title"]

        try:
            gcal_id = calendars.sync_event_to_calendar(client, user_id, event_id)
            console.print(f"[green]  {title[:40]}[/green]")
            success_count += 1
        except calendars.CalendarsError as e:
            console.print(f"[red]  {title[:40]} - FAILED: {e}[/red]")
            fail_count += 1

    console.print(f"\n[bold]Results: {success_count} synced, {fail_count} failed[/bold]")


if __name__ == "__main__":
    app()
