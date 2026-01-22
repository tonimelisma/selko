"""Tests for configuration loading."""

import pytest

from selko.config import get_environment


class TestGetEnvironment:
    """Test environment detection."""

    def test_default_development(self, monkeypatch):
        """Default to development if not specified."""
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        assert get_environment(None) == "development"

    def test_override_from_arg(self, monkeypatch):
        """CLI arg overrides env var."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        assert get_environment("staging") == "staging"

    def test_from_env_var(self, monkeypatch):
        """Read from ENVIRONMENT var."""
        monkeypatch.setenv("ENVIRONMENT", "staging")
        assert get_environment(None) == "staging"

    def test_production_environment(self, monkeypatch):
        """Test production environment."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        assert get_environment(None) == "production"

    def test_invalid_environment(self):
        """Reject invalid environment names."""
        with pytest.raises(ValueError) as exc_info:
            get_environment("invalid")
        assert "Invalid environment" in str(exc_info.value)
        assert "invalid" in str(exc_info.value)

    def test_invalid_env_lists_valid(self):
        """Error message includes valid environments."""
        with pytest.raises(ValueError) as exc_info:
            get_environment("bogus")
        error_msg = str(exc_info.value)
        assert "development" in error_msg
        assert "staging" in error_msg
        assert "production" in error_msg
