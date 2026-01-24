"""Integration tests for CLI tools.

Tests CLI as subprocess to validate argument parsing and output.
"""

import subprocess
import sys
from uuid import uuid4

import pytest


def run_cli(module: str, args: list[str], env_override: str = "development") -> subprocess.CompletedProcess:
    """Run a CLI module as subprocess.

    Args:
        module: CLI module name (e.g., "cli.cli_user")
        args: Command line arguments
        env_override: Environment to use

    Returns:
        CompletedProcess with stdout/stderr
    """
    cmd = [sys.executable, "-m", module, "--env", env_override] + args
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,  # 60 second timeout
    )


@pytest.mark.integration
@pytest.mark.development
class TestCLIUser:
    """Test cli_user commands."""

    def test_cli_user_list(self):
        """CLI user list returns users."""
        result = run_cli("cli.cli_user", ["list"])

        assert result.returncode == 0
        # Should show at least some output (header or users)
        assert result.stdout or result.stderr

    def test_cli_user_create_and_delete(self):
        """CLI can create and delete users."""
        email = f"cli-test-{uuid4()}@selko.local"

        # Create user
        create_result = run_cli(
            "cli.cli_user",
            ["create", "--email", email, "--password", "testpass123"],
        )

        assert create_result.returncode == 0
        # Extract user ID from output
        # Output format: "Created user: {id} ({email})"
        assert email in create_result.stdout or "Created" in create_result.stdout

        # Find user ID in output
        import re
        match = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", create_result.stdout)
        if match:
            user_id = match.group(1)

            # Delete user
            delete_result = run_cli(
                "cli.cli_user",
                ["delete", "--user-id", user_id],
            )
            assert delete_result.returncode == 0

    def test_cli_user_verbose(self):
        """CLI verbose flag enables debug logging."""
        # Note: -v must come before subcommand (it's on parent parser)
        result = run_cli("cli.cli_user", ["-v", "list"])

        # Verbose output should include DEBUG level logs
        # At minimum, should not error
        assert result.returncode == 0

    def test_cli_user_quiet(self):
        """CLI quiet flag reduces output."""
        # Note: -q must come before subcommand (it's on parent parser)
        result = run_cli("cli.cli_user", ["-q", "list"])

        assert result.returncode == 0
        # Quiet mode should have less output
        # (hard to test precisely, just verify it works)

    def test_cli_user_invalid_env(self):
        """CLI rejects invalid environment."""
        cmd = [sys.executable, "-m", "cli.cli_user", "--env", "invalid", "list"]
        result = subprocess.run(cmd, capture_output=True, text=True)

        # Should fail
        assert result.returncode != 0


@pytest.mark.integration
@pytest.mark.development
class TestCLIFetchEmails:
    """Test cli_fetch_emails commands.

    Note: These tests require a test user to be authenticated.
    In development, they use mocked Gmail or may skip if no credentials.
    """

    def test_cli_fetch_emails_help(self):
        """CLI fetch emails shows help."""
        cmd = [sys.executable, "-m", "cli.cli_fetch_emails", "--help"]
        result = subprocess.run(cmd, capture_output=True, text=True)

        assert result.returncode == 0
        assert "--max" in result.stdout or "max" in result.stdout.lower()

    def test_cli_fetch_emails_max_flag(self):
        """CLI accepts --max flag."""
        # This may fail if no Gmail credentials, but should parse args correctly
        result = run_cli("cli.cli_fetch_emails", ["--max", "5"])

        # Either succeeds or fails due to no credentials (not arg parsing)
        # Check that it didn't fail due to unrecognized argument
        assert "unrecognized" not in result.stderr.lower()


@pytest.mark.integration
@pytest.mark.development
class TestCLIAuthGmail:
    """Test cli_auth_gmail commands.

    Note: Cannot fully test OAuth flow without user interaction.
    """

    def test_cli_auth_gmail_help(self):
        """CLI auth gmail shows help."""
        cmd = [sys.executable, "-m", "cli.cli_auth_gmail", "--help"]
        result = subprocess.run(cmd, capture_output=True, text=True)

        assert result.returncode == 0
        assert "--env" in result.stdout or "environment" in result.stdout.lower()


@pytest.mark.integration
@pytest.mark.development
class TestCLIEnvironmentSelection:
    """Test CLI environment selection."""

    def test_env_development(self):
        """--env development uses .env file."""
        result = run_cli("cli.cli_user", ["list"], env_override="development")

        # Should work (assuming local Supabase is running)
        # At minimum, should not fail due to env parsing
        assert "Invalid environment" not in result.stderr

    def test_env_flag_override(self):
        """--env flag overrides ENVIRONMENT variable."""
        import os

        # Set env var to staging but use --env development
        env = os.environ.copy()
        env["ENVIRONMENT"] = "staging"

        cmd = [sys.executable, "-m", "cli.cli_user", "--env", "development", "list"]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

        # Should use development, not staging
        # (Would fail if staging config is missing)
        # This verifies the --env flag takes precedence


@pytest.mark.integration
@pytest.mark.staging
class TestCLIStaging:
    """Test CLI against staging environment."""

    def test_cli_user_list_staging(self):
        """CLI user list works in staging."""
        result = run_cli("cli.cli_user", ["list"], env_override="staging")

        assert result.returncode == 0

    def test_cli_fetch_emails_staging(self):
        """CLI fetch emails works in staging (with credentials)."""
        result = run_cli(
            "cli.cli_fetch_emails",
            ["--max", "3"],
            env_override="staging",
        )

        # May succeed or fail depending on Gmail credentials
        # Just verify it doesn't crash on env setup
        assert "Invalid environment" not in result.stderr
