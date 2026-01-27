"""CLI tool for calendar management.

Uses direct Supabase queries and service calls (no REST API server required).
"""

import sys

import typer
from rich.console import Console
from rich.table import Table

sys.path.insert(0, str(__file__ + "/../.."))

from selko.config import load_config
from selko.services.auth import get_authenticated_client, get_current_user_id
from selko.services import calendars

app = typer.Typer(help="Manage Google Calendar integration")
console = Console()


@app.command()
def list():
    """List all available Google Calendars."""
    config = load_config()
    client = get_authenticated_client(config)
    user_id = get_current_user_id(client)

    try:
        calendar_list = calendars.list_calendars(client, user_id)
    except calendars.CalendarsError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    if not calendar_list:
        console.print("[yellow]No calendars found[/yellow]")
        return

    table = Table(title="Google Calendars")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Type", style="yellow")
    table.add_column("Selected", style="magenta")

    for cal in calendar_list:
        cal_type = "Primary" if cal["is_primary"] else "Secondary"
        selected = "Y" if cal["is_selected"] else ""

        table.add_row(
            cal["id"][:30] + "..." if len(cal["id"]) > 30 else cal["id"],
            cal["name"],
            cal_type,
            selected,
        )

    console.print(table)

    # Show current settings
    try:
        settings = calendars.get_calendar_settings(client, user_id)

        if settings.get("target_calendar_id"):
            console.print(f"\n[dim]Target calendar: {settings.get('target_calendar_name')}[/dim]")
        else:
            console.print("\n[dim]Using primary calendar (default)[/dim]")

        if settings.get("default_invitees"):
            console.print(f"[dim]Default invitees: {settings.get('default_invitees')}[/dim]")
    except Exception:
        pass  # Ignore settings errors


@app.command("set")
def set_calendar(calendar_id: str):
    """Set target calendar for event sync.

    Args:
        calendar_id: Google Calendar ID (use 'primary' for primary calendar).
    """
    config = load_config()
    client = get_authenticated_client(config)
    user_id = get_current_user_id(client)

    # Set to None if primary requested
    target_id = None if calendar_id.lower() == "primary" else calendar_id

    try:
        calendars.update_calendar_settings(
            client, user_id,
            target_calendar_id=target_id
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    if target_id:
        console.print(f"[green]Set target calendar to {calendar_id}[/green]")
    else:
        console.print("[green]Set target calendar to primary[/green]")


@app.command()
def invitees(emails: str):
    """Set default invitees (comma-separated emails).

    Args:
        emails: Comma-separated email addresses (e.g., "spouse@gmail.com,friend@example.com").
    """
    config = load_config()
    client = get_authenticated_client(config)
    user_id = get_current_user_id(client)

    try:
        calendars.update_calendar_settings(
            client, user_id,
            default_invitees=emails
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Set default invitees to: {emails}[/green]")
    console.print("[dim]These emails will be added to all new calendar events.[/dim]")


@app.command()
def settings():
    """Show current calendar settings."""
    config = load_config()
    client = get_authenticated_client(config)
    user_id = get_current_user_id(client)

    try:
        settings_data = calendars.get_calendar_settings(client, user_id)
    except calendars.CalendarsError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    console.print("[bold]Calendar Settings[/bold]\n")

    if settings_data.get("target_calendar_id"):
        console.print(f"Target Calendar: [green]{settings_data.get('target_calendar_name')}[/green]")
        console.print(f"  ID: [dim]{settings_data.get('target_calendar_id')}[/dim]")
    else:
        console.print("Target Calendar: [green]Primary (default)[/green]")

    if settings_data.get("default_invitees"):
        console.print(f"\nDefault Invitees: [cyan]{settings_data.get('default_invitees')}[/cyan]")
    else:
        console.print("\nDefault Invitees: [dim](none)[/dim]")


if __name__ == "__main__":
    app()
