"""CLI tool for calendar management via REST API.

This CLI calls the REST API server (must be running).
"""

import sys

import httpx
import typer
from rich import print
from rich.console import Console
from rich.table import Table

sys.path.insert(0, str(__file__ + "/../.."))

from selko.config import load_config
from selko.services.auth import get_authenticated_client

app = typer.Typer(help="Manage Google Calendar integration")
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
def list():
    """List all available Google Calendars."""
    try:
        client, base_url = get_api_client()
        response = client.get("/calendars")
        response.raise_for_status()
        
        calendars = response.json()
        
        if not calendars:
            console.print("[yellow]No calendars found[/yellow]")
            return
        
        table = Table(title="Google Calendars")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Type", style="yellow")
        table.add_column("Selected", style="magenta")
        
        for cal in calendars:
            cal_type = "Primary" if cal["is_primary"] else "Secondary"
            selected = "✓" if cal["is_selected"] else ""
            
            table.add_row(
                cal["id"][:30] + "..." if len(cal["id"]) > 30 else cal["id"],
                cal["name"],
                cal_type,
                selected,
            )
        
        console.print(table)
        
        # Show current settings
        settings_response = client.get("/calendars/settings")
        settings_response.raise_for_status()
        settings = settings_response.json()
        
        if settings.get("target_calendar_id"):
            console.print(f"\n[dim]Target calendar: {settings.get('target_calendar_name')}[/dim]")
        else:
            console.print("\n[dim]Using primary calendar (default)[/dim]")
        
        if settings.get("default_invitees"):
            console.print(f"[dim]Default invitees: {settings.get('default_invitees')}[/dim]")
        
    except httpx.HTTPError as e:
        console.print(f"[red]API error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def set(calendar_id: str):
    """Set target calendar for event sync.
    
    Args:
        calendar_id: Google Calendar ID (use 'primary' for primary calendar).
    """
    try:
        client, base_url = get_api_client()
        
        # Set to None if primary requested
        target_id = None if calendar_id.lower() == "primary" else calendar_id
        
        response = client.put(
            "/calendars/settings",
            json={"target_calendar_id": target_id}
        )
        response.raise_for_status()
        
        if target_id:
            console.print(f"[green]✓ Set target calendar to {calendar_id}[/green]")
        else:
            console.print("[green]✓ Set target calendar to primary[/green]")
        
    except httpx.HTTPError as e:
        console.print(f"[red]API error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def invitees(emails: str):
    """Set default invitees (comma-separated emails).
    
    Args:
        emails: Comma-separated email addresses (e.g., "spouse@gmail.com,friend@example.com").
    """
    try:
        client, base_url = get_api_client()
        
        response = client.put(
            "/calendars/settings",
            json={"default_invitees": emails}
        )
        response.raise_for_status()
        
        console.print(f"[green]✓ Set default invitees to: {emails}[/green]")
        console.print("[dim]These emails will be added to all new calendar events.[/dim]")
        
    except httpx.HTTPError as e:
        console.print(f"[red]API error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def settings():
    """Show current calendar settings."""
    try:
        client, base_url = get_api_client()
        response = client.get("/calendars/settings")
        response.raise_for_status()
        
        settings = response.json()
        
        console.print("[bold]Calendar Settings[/bold]\n")
        
        if settings.get("target_calendar_id"):
            console.print(f"Target Calendar: [green]{settings.get('target_calendar_name')}[/green]")
            console.print(f"  ID: [dim]{settings.get('target_calendar_id')}[/dim]")
        else:
            console.print("Target Calendar: [green]Primary (default)[/green]")
        
        if settings.get("default_invitees"):
            console.print(f"\nDefault Invitees: [cyan]{settings.get('default_invitees')}[/cyan]")
        else:
            console.print("\nDefault Invitees: [dim](none)[/dim]")
        
    except httpx.HTTPError as e:
        console.print(f"[red]API error: {e}[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
