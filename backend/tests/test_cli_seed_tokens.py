"""Guardrails for the OAuth token seeding CLI.

This tool exists to seed burner test tokens between local development and
staging. Production holds real users' OAuth credentials and must never be
either end of a copy.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from cli_seed_tokens import (  # noqa: E402
    TokenSeedError,
    get_integration_by_provider,
    seed_tokens,
)


@pytest.mark.parametrize(
    "source_env,target_env",
    [
        ("production", "staging"),
        ("production", "development"),
        ("staging", "production"),
        ("development", "production"),
    ],
)
def test_production_is_refused_at_either_end(source_env, target_env):
    """Credentials must not flow out of, or into, production."""
    with pytest.raises(TokenSeedError, match="production"):
        seed_tokens(source_env, target_env, "gmail")


def test_production_is_not_offered_on_the_command_line():
    """argparse should not even present production as a choice."""
    import argparse
    import cli_seed_tokens

    parser_choices = []

    real_add_argument = argparse.ArgumentParser.add_argument

    def capture(self, *args, **kwargs):
        if kwargs.get("dest") in {"source_env", "target_env"}:
            parser_choices.append(kwargs.get("choices"))
        return real_add_argument(self, *args, **kwargs)

    argparse.ArgumentParser.add_argument = capture
    try:
        with pytest.raises(SystemExit):
            sys.argv = ["cli_seed_tokens", "--help"]
            cli_seed_tokens.main()
    finally:
        argparse.ArgumentParser.add_argument = real_add_argument

    assert parser_choices, "expected --from/--to to declare choices"
    for choices in parser_choices:
        assert "production" not in choices


def _client_returning(rows):
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
        data=rows
    )
    return client


def test_seeding_prefers_an_active_integration():
    """An unordered limit(1) could seed an expired account over a working one."""
    rows = [
        {"id": "expired-1", "provider": "gmail", "status": "expired"},
        {"id": "active-1", "provider": "gmail", "status": "active"},
    ]

    chosen = get_integration_by_provider(_client_returning(rows), "gmail")

    assert chosen["id"] == "active-1"


def test_seeding_falls_back_when_nothing_is_active():
    rows = [{"id": "expired-1", "provider": "gmail", "status": "expired"}]

    chosen = get_integration_by_provider(_client_returning(rows), "gmail")

    assert chosen["id"] == "expired-1"


def test_seeding_returns_none_without_any_integration():
    assert get_integration_by_provider(_client_returning([]), "gmail") is None

def test_is_integration_stale_cases():
    from cli_seed_tokens import is_integration_stale
    from datetime import datetime, timezone, timedelta
    # None -> stale
    assert is_integration_stale(None) is True
    # non-active -> stale
    assert is_integration_stale({"status": "expired", "token_expiry": (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(), "refresh_token": "r"}) is True
    # missing expiry -> stale
    assert is_integration_stale({"status": "active", "refresh_token": "r"}) is True
    # expired -> stale
    assert is_integration_stale({"status": "active", "token_expiry": (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(), "refresh_token": "r"}) is True
    # missing refresh_token -> stale
    future = (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
    assert is_integration_stale({"status": "active", "token_expiry": future}) is True
    # fresh -> not stale
    assert is_integration_stale({"status": "active", "token_expiry": future, "refresh_token": "r"}) is False


def test_sync_dev_staging_copies_working_to_stale(monkeypatch):
    from cli_seed_tokens import sync_dev_staging, is_integration_stale
    from datetime import datetime, timezone, timedelta
    future = (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
    past = (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
    fresh = {"status": "active", "token_expiry": future, "refresh_token": "r", "provider": "gmail"}
    stale = {"status": "expired", "token_expiry": past, "refresh_token": "r", "provider": "gmail"}

    # mock get_integration_by_provider to return fresh for dev, stale for staging
    import cli_seed_tokens as m
    calls = {}
    def fake_get(client, provider):
        # client is mock with _env attr we set
        return fresh if getattr(client, "_env", "") == "dev" else stale
    monkeypatch.setattr(m, "get_integration_by_provider", fake_get)
    # mock create_client to return tagged mocks
    def fake_create(url, key):
        mc = type("C", (), {})()
        mc._env = "dev" if "dev" in url or "localhost" in url else "staging"
        # heuristic: dev url contains localhost, staging contains supabase.co
        # Better: use call order
        return mc
    # Instead patch load_config_with_prefix to return configs with identifiable urls
    from unittest.mock import MagicMock
    def fake_load(env_name, prefix):
        cfg = MagicMock()
        cfg.supabase_url = "http://localhost:54321" if env_name=="development" else "https://staging.supabase.co"
        cfg.supabase_service_role_key = "key"
        return cfg
    monkeypatch.setattr(m, "load_config_with_prefix", fake_load)
    monkeypatch.setattr(m, "create_client", fake_create)
    seeded = {}
    def fake_seed(src, tgt, prov):
        seeded["args"]=(src,tgt,prov)
    monkeypatch.setattr(m, "seed_tokens", fake_seed)

    # dev fresh, staging stale -> should copy dev->staging
    direction = sync_dev_staging("gmail")
    assert direction == "development->staging"
    assert seeded["args"] == ("development", "staging", "gmail")

    # flip: staging fresh, dev stale
    def fake_get2(client, provider):
        return stale if getattr(client, "_env", "") == "dev" else fresh
    monkeypatch.setattr(m, "get_integration_by_provider", fake_get2)
    seeded.clear()
    direction = sync_dev_staging("gmail")
    assert direction == "staging->development"
    assert seeded["args"] == ("staging", "development", "gmail")

    # both fresh -> no-op
    def fake_get3(client, provider):
        return fresh
    monkeypatch.setattr(m, "get_integration_by_provider", fake_get3)
    seeded.clear()
    direction = sync_dev_staging("gmail")
    assert direction == "already in sync"
    assert seeded == {}

    # both stale -> error
    def fake_get4(client, provider):
        return stale
    monkeypatch.setattr(m, "get_integration_by_provider", fake_get4)
    import pytest as _pytest
    with _pytest.raises(m.TokenSeedError, match="Both dev and staging"):
        sync_dev_staging("gmail")


def test_sync_cli_requires_provider():
    import cli_seed_tokens, sys
    sys.argv = ["cli_seed_tokens", "--sync"]
    import pytest as _pytest
    with _pytest.raises(SystemExit):
        cli_seed_tokens.main()

