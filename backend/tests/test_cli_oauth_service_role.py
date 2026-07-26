"""Regression tests for CLI OAuth token persistence."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cli import cli_auth_gcal, cli_auth_gmail, cli_auth_outlook


def _prepare_cli(monkeypatch, module):
    config = MagicMock()
    authenticated_client = MagicMock(name="authenticated_client")
    service_client = MagicMock(name="service_client")
    monkeypatch.setattr(module.sys, "argv", [module.__name__])
    monkeypatch.setattr(module, "setup_logging", MagicMock())
    monkeypatch.setattr(module, "load_config", MagicMock(return_value=config))
    monkeypatch.setattr(
        module,
        "get_authenticated_client",
        MagicMock(return_value=authenticated_client),
    )
    monkeypatch.setattr(
        module,
        "get_current_user_id",
        MagicMock(return_value="user-123"),
    )
    monkeypatch.setattr(
        module,
        "get_service_client",
        MagicMock(return_value=service_client),
    )
    return config, authenticated_client, service_client


def test_gmail_cli_saves_tokens_with_service_role(monkeypatch):
    config, _, service_client = _prepare_cli(monkeypatch, cli_auth_gmail)
    credentials = MagicMock(name="credentials")
    monkeypatch.setattr(
        cli_auth_gmail,
        "run_oauth_flow",
        MagicMock(return_value=credentials),
    )
    monkeypatch.setattr(cli_auth_gmail, "build_service", MagicMock())
    monkeypatch.setattr(
        cli_auth_gmail,
        "get_user_profile",
        MagicMock(return_value={"emailAddress": "burner@example.com"}),
    )
    save = MagicMock()
    monkeypatch.setattr(cli_auth_gmail, "save_oauth_credentials", save)

    cli_auth_gmail.main()

    cli_auth_gmail.get_service_client.assert_called_once_with(config)
    save.assert_called_once_with(
        service_client,
        "user-123",
        "gmail",
        credentials,
        "burner@example.com",
    )


def test_google_calendar_cli_saves_tokens_with_service_role(monkeypatch):
    config, _, service_client = _prepare_cli(monkeypatch, cli_auth_gcal)
    credentials = MagicMock(name="credentials")
    monkeypatch.setattr(
        cli_auth_gcal,
        "run_calendar_oauth_flow",
        MagicMock(return_value=credentials),
    )
    save = MagicMock()
    monkeypatch.setattr(cli_auth_gcal, "save_oauth_credentials", save)

    cli_auth_gcal.main()

    cli_auth_gcal.get_service_client.assert_called_once_with(config)
    save.assert_called_once_with(
        service_client,
        "user-123",
        "google_calendar",
        credentials,
        None,
    )


def test_outlook_cli_saves_tokens_with_service_role(monkeypatch):
    config, _, service_client = _prepare_cli(monkeypatch, cli_auth_outlook)
    monkeypatch.setattr(
        cli_auth_outlook,
        "initiate_oauth_flow",
        MagicMock(return_value={"auth_url": "https://login.example", "state": "state"}),
    )
    monkeypatch.setattr(
        cli_auth_outlook,
        "_capture_callback",
        MagicMock(return_value={"code": "code", "state": "state"}),
    )
    token_result = {"access_token": "token", "refresh_token": "refresh"}
    monkeypatch.setattr(
        cli_auth_outlook,
        "complete_oauth_flow",
        MagicMock(return_value=(token_result, "user-123", "outlook")),
    )
    monkeypatch.setattr(
        cli_auth_outlook,
        "get_user_profile",
        MagicMock(return_value={"mail": "burner@example.com"}),
    )
    save = MagicMock()
    monkeypatch.setattr(cli_auth_outlook, "save_provider_tokens", save)

    cli_auth_outlook.main()

    cli_auth_outlook.get_service_client.assert_called_once_with(config)
    save.assert_called_once_with(
        service_client,
        "user-123",
        "outlook",
        token_result,
        "burner@example.com",
    )
