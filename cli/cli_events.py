"""CLI tool for event management via REST API.

This CLI calls the REST API server (must be running).
"""

import sys
from typing import Optional

import httpx
import typer
from rich import print
from rich.console import Console
from rich.table import Table

sys.path.insert(0, str(__file__ + "/../.."))

from selko.config import load_config
from selko.services.auth import get_authenticated_client

app = typer.Typer(help="Manage calendar events")
console = Console()


def get_api_client() -> tuple[httpx.Client, str]:
    """Get authenticated HTTP client for API calls.
    
    Returns:
        Tuple of (HTTP client, base URL).
    """
    config = load_config()
    
    # Get JWT token via Supabase auth
    supabase_client = get_authenticated_client(config)
    token = supabase_client.auth.get_session().access_token
    
    # API base URL (default to localhost:8000)
    base_url = config.api_base_url if hasattr(config, 'api_base_url') else "http://localhost:8000"
    
    client = httpx.Client(
        base_url=base_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )
    
    return client, base_url


@app.command()
def new():
    """List events pending approval (New view)."""
    try:
        client, base_url = get_api_client()
        response = client.get("/events/new")
        response.raise_for_status()
        
        events = response.json()
        
        if not events:
            console.print("[yellow]No pending events[/yellow]")
            return
        
        # Group by sender
        by_sender = {}
        for event in events:
            sender = event["primary_sender"]
            if sender not in by_sender:
                by_sender[sender] = []
            by_sender[sender].append(event)
        
        # Print grouped by sender
        for sender, sender_events in by_sender.items():
            console.print(f"\n[bold cyan]{sender}[/bold cyan]:")
            for event in sender_events:
                event_id = event["id"][:8]
                title = event["title"]
                start = event.get("start_datetime", "No date")
                console.print(f"  [green][{event_id}][/green] {title} - {start}")
        
        console.print(f"\n[dim]Total: {len(events)} pending events[/dim]")
        
    except httpx.HTTPError as e:
        console.print(f"[red]API error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def approved():
    """List approved/synced events (Approved view)."""
    try:
        client, base_url = get_api_client()
        response = client.get("/events/approved")
        response.raise_for_status()
        
        events = response.json()
        
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
                event.get("start_datetime", "No date"),
                event["status"],
            )
        
        console.print(table)
        
    except httpx.HTTPError as e:
        console.print(f"[red]API error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def updates():
    """List change log (Updates view)."""
    try:
        client, base_url = get_api_client()
        response = client.get("/events/updates")
        response.raise_for_status()
        
        updates_data = response.json()
        
        if not updates_data:
            console.print("[yellow]No updates[/yellow]")
            return
        
        console.print(f"[bold]Event Updates & Changes[/bold]\n")
        
        for update in updates_data:
            event = update.get("events", {})
            email = update.get("emails", {})
            
            source_type = update["source_type"]
            created_at = update["created_at"]
            
            console.print(f"[cyan]{source_type.upper()}[/cyan] - {created_at}")
            console.print(f"  Event: {event.get('title', 'Unknown')}")
            console.print(f"  From: {email.get('from_name', 'Unknown')}")
            console.print("")
        
    except httpx.HTTPError as e:
        console.print(f"[red]API error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def approve(event_id: str):
    """Approve an event for calendar sync."""
    try:
        client, base_url = get_api_client()
        response = client.post(f"/events/{event_id}/approve")
        response.raise_for_status()
        
        console.print(f"[green]✓ Approved event {event_id}[/green]")
        console.print("[dim]Event will sync to calendar shortly.[/dim]")
        
    except httpx.HTTPError as e:
        console.print(f"[red]API error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def reject(event_id: str):
    """Reject an event."""
    try:
        client, base_url = get_api_client()
        response = client.post(f"/events/{event_id}/reject")
        response.raise_for_status()
        
        console.print(f"[yellow]Rejected event {event_id}[/yellow]")
        
    except httpx.HTTPError as e:
        console.print(f"[red]API error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def restore(event_id: str):
    """Restore a rejected event to New."""
    try:
        client, base_url = get_api_client()
        response = client.post(f"/events/{event_id}/restore")
        response.raise_for_status()
        
        console.print(f"[green]Restored event {event_id} to New[/green]")
        
    except httpx.HTTPError as e:
        console.print(f"[red]API error: {e}[/red]")
        raise typer.Exit(1)


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
    
    try:
        client, base_url = get_api_client()
        response = client.post(f"/events/{event_id}/sources/{source_id}/undo")
        response.raise_for_status()
        
        console.print(f"[green]✓ Undid source {source_id}[/green]")
        
    except httpx.HTTPError as e:
        console.print(f"[red]API error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def approve_sender(sender: str):
    """Auto-approve all events from a sender (domain or email).
    
    Args:
        sender: Email address or domain (e.g., "school.edu" or "calendar@school.edu")
    """
    try:
        client, base_url = get_api_client()
        
        # Determine if it's domain or email
        if "@" in sender:
            payload = {"sender_email": sender, "action": "auto_approve"}
        else:
            payload = {"sender_domain": sender, "action": "auto_approve"}
        
        response = client.post("/sender-rules", json=payload)
        response.raise_for_status()
        
        console.print(f"[green]✓ Auto-approving events from {sender}[/green]")
        
    except httpx.HTTPError as e:
        console.print(f"[red]API error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def ignore_sender(sender: str):
    """Ignore all events from a sender (domain or email).
    
    Note: This only ignores their email data contributions,
    not entire events (which may have multiple senders).
    
    Args:
        sender: Email address or domain (e.g., "school.edu" or "newsletter@school.edu")
    """
    try:
        client, base_url = get_api_client()
        
        # Determine if it's domain or email
        if "@" in sender:
            payload = {"sender_email": sender, "action": "ignore"}
        else:
            payload = {"sender_domain": sender, "action": "ignore"}
        
        response = client.post("/sender-rules", json=payload)
        response.raise_for_status()
        
        console.print(f"[yellow]Ignoring events from {sender}[/yellow]")
        console.print("[dim]Note: Only ignores their email contributions, not entire events.[/dim]")
        
    except httpx.HTTPError as e:
        console.print(f"[red]API error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def list_rules():
    """List all sender rules."""
    try:
        client, base_url = get_api_client()
        response = client.get("/sender-rules")
        response.raise_for_status()
        
        rules = response.json()
        
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
        
    except httpx.HTTPError as e:
        console.print(f"[red]API error: {e}[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
