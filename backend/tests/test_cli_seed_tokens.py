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
