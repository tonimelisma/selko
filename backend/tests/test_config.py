"""Tests for configuration loading."""

import os

import pytest

from selko.config import get_environment, _parse_allowed_origins, Config


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


class TestParseAllowedOrigins:
    """Test CORS allowed origins parsing."""

    def test_defaults_when_env_not_set(self, monkeypatch):
        """Returns localhost defaults when ALLOWED_ORIGINS not set."""
        monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
        origins = _parse_allowed_origins()

        assert "http://localhost:3000" in origins
        assert "http://localhost:5173" in origins
        assert "http://127.0.0.1:3000" in origins
        assert "http://127.0.0.1:5173" in origins
        assert len(origins) == 4

    def test_defaults_when_env_empty(self, monkeypatch):
        """Returns defaults when ALLOWED_ORIGINS is empty string."""
        monkeypatch.setenv("ALLOWED_ORIGINS", "")
        origins = _parse_allowed_origins()

        assert len(origins) == 4
        assert "http://localhost:3000" in origins

    def test_single_origin(self, monkeypatch):
        """Parses single origin correctly."""
        monkeypatch.setenv("ALLOWED_ORIGINS", "https://example.com")
        origins = _parse_allowed_origins()

        assert origins == ["https://example.com"]

    def test_multiple_origins(self, monkeypatch):
        """Parses comma-separated origins."""
        monkeypatch.setenv(
            "ALLOWED_ORIGINS",
            "https://staging.example.com,https://prod.example.com"
        )
        origins = _parse_allowed_origins()

        assert len(origins) == 2
        assert "https://staging.example.com" in origins
        assert "https://prod.example.com" in origins

    def test_trims_whitespace(self, monkeypatch):
        """Trims whitespace around origins."""
        monkeypatch.setenv(
            "ALLOWED_ORIGINS",
            "  https://a.com  ,  https://b.com  ,  https://c.com  "
        )
        origins = _parse_allowed_origins()

        assert origins == ["https://a.com", "https://b.com", "https://c.com"]

    def test_ignores_empty_entries(self, monkeypatch):
        """Ignores empty entries from extra commas."""
        monkeypatch.setenv("ALLOWED_ORIGINS", "https://a.com,,https://b.com,")
        origins = _parse_allowed_origins()

        assert origins == ["https://a.com", "https://b.com"]

    def test_render_staging_url(self, monkeypatch):
        """Correctly parses Render staging URL."""
        monkeypatch.setenv(
            "ALLOWED_ORIGINS",
            "https://selko-web-staging.onrender.com"
        )
        origins = _parse_allowed_origins()

        assert origins == ["https://selko-web-staging.onrender.com"]

    def test_custom_production_url(self, monkeypatch):
        """Correctly parses the custom production URL."""
        monkeypatch.setenv("ALLOWED_ORIGINS", "https://selkoapp.com")
        origins = _parse_allowed_origins()

        assert origins == ["https://selkoapp.com"]

    def test_mixed_localhost_and_production(self, monkeypatch):
        """Parses mix of localhost and production origins."""
        monkeypatch.setenv(
            "ALLOWED_ORIGINS",
            "http://localhost:3000,https://selkoapp.com"
        )
        origins = _parse_allowed_origins()

        assert len(origins) == 2
        assert "http://localhost:3000" in origins
        assert "https://selkoapp.com" in origins


class TestConfigAllowedOrigins:
    """Test Config dataclass allowed_origins field."""

    def test_default_allowed_origins(self):
        """Config has default allowed_origins for localhost."""
        config = Config(
            environment="development",
            supabase_url="http://localhost:54321",
            supabase_key="test-key",
        )

        assert len(config.allowed_origins) == 4
        assert "http://localhost:3000" in config.allowed_origins
        assert "http://localhost:5173" in config.allowed_origins

    def test_custom_allowed_origins(self):
        """Config accepts custom allowed_origins."""
        custom_origins = ["https://example.com", "https://staging.example.com"]
        config = Config(
            environment="production",
            supabase_url="https://example.supabase.co",
            supabase_key="prod-key",
            allowed_origins=custom_origins,
        )

        assert config.allowed_origins == custom_origins

    def test_empty_allowed_origins(self):
        """Config accepts empty allowed_origins list."""
        config = Config(
            environment="production",
            supabase_url="https://example.supabase.co",
            supabase_key="prod-key",
            allowed_origins=[],
        )

        assert config.allowed_origins == []


class TestLoadConfigAllowedOrigins:
    """Test load_config() integration with allowed_origins."""

    def test_load_config_uses_env_var(self, monkeypatch, tmp_path):
        """load_config() uses ALLOWED_ORIGINS from environment."""
        from selko.config import load_config

        # Create a minimal .env file
        env_file = tmp_path / ".env"
        env_file.write_text(
            "SUPABASE_URL=http://localhost:54321\n"
            "SUPABASE_PUBLISHABLE_KEY=test-key\n"
        )

        # Set environment to use our temp .env
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("SUPABASE_URL", "http://localhost:54321")
        monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-key")
        monkeypatch.setenv(
            "ALLOWED_ORIGINS",
            "https://selko-web-staging.onrender.com,https://selkoapp.com"
        )

        config = load_config()

        assert len(config.allowed_origins) == 2
        assert "https://selko-web-staging.onrender.com" in config.allowed_origins
        assert "https://selkoapp.com" in config.allowed_origins

    def test_load_config_defaults_without_env_var(self, monkeypatch):
        """load_config() uses defaults when ALLOWED_ORIGINS not set."""
        from selko.config import load_config

        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("SUPABASE_URL", "http://localhost:54321")
        monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-key")
        monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)

        config = load_config()

        assert len(config.allowed_origins) == 4
        assert "http://localhost:3000" in config.allowed_origins
        assert "http://localhost:5173" in config.allowed_origins


class TestBackgroundProcessingDefaults:
    """Test safe environment-specific worker defaults."""

    @pytest.mark.parametrize(
        ("environment", "expected"),
        [
            ("development", False),
            ("staging", False),
            ("production", True),
        ],
    )
    def test_defaults_by_environment(
        self, monkeypatch, tmp_path, environment, expected
    ):
        """Production processes work unless explicitly disabled."""
        from selko import config as config_module

        monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path)
        monkeypatch.setenv("ENVIRONMENT", environment)
        monkeypatch.setenv("SUPABASE_URL", "http://localhost:54321")
        monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-key")
        monkeypatch.delenv("ENABLE_BACKGROUND_PROCESSING", raising=False)

        config = config_module.load_config()

        assert config.enable_background_processing is expected

    def test_explicit_false_disables_production_workers(self, monkeypatch, tmp_path):
        """The environment flag remains an emergency production kill switch."""
        from selko import config as config_module

        monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path)
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("SUPABASE_URL", "http://localhost:54321")
        monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-key")
        monkeypatch.setenv("ENABLE_BACKGROUND_PROCESSING", "false")

        config = config_module.load_config()

        assert config.enable_background_processing is False

    def test_platform_env_overrides_dotenv_file(self, monkeypatch, tmp_path):
        """A Render setting must not be replaced by a checked-out env file."""
        from selko import config as config_module

        (tmp_path / ".env.production").write_text(
            "ENABLE_BACKGROUND_PROCESSING=false\n"
        )
        monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path)
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("SUPABASE_URL", "http://localhost:54321")
        monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-key")
        monkeypatch.setenv("ENABLE_BACKGROUND_PROCESSING", "true")

        config = config_module.load_config()

        assert config.enable_background_processing is True

    def test_selected_dotenv_does_not_contaminate_later_load(
        self, monkeypatch, tmp_path
    ):
        """Sequential explicit loads use their own file values."""
        from selko import config as config_module

        (tmp_path / ".env.test").write_text(
            "SUPABASE_URL=https://staging.example\n"
            "SUPABASE_PUBLISHABLE_KEY=staging-key\n"
        )
        (tmp_path / ".env").write_text(
            "SUPABASE_URL=http://localhost:54321\n"
            "SUPABASE_PUBLISHABLE_KEY=development-key\n"
        )
        monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path)
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_PUBLISHABLE_KEY", raising=False)

        staging = config_module.load_config(env_override="staging")
        development = config_module.load_config(env_override="development")

        assert staging.supabase_url == "https://staging.example"
        assert development.supabase_url == "http://localhost:54321"
        assert "SUPABASE_URL" not in os.environ


class TestAttachmentLimitsDefaults:
    """Test per-type attachment size limit defaults."""

    def test_defaults(self):
        """Verify default values for per-type attachment limits."""
        config = Config(
            environment="development",
            supabase_url="http://localhost:54321",
            supabase_key="test-key",
        )

        assert config.max_pdf_pages_for_llm == 10
        assert config.max_image_size_for_llm == 10 * 1024 * 1024
        assert config.max_other_size_for_llm == 20 * 1024 * 1024

    def test_custom_values(self):
        """Verify custom values can be set."""
        config = Config(
            environment="development",
            supabase_url="http://localhost:54321",
            supabase_key="test-key",
            max_pdf_pages_for_llm=5,
            max_image_size_for_llm=2048,
            max_other_size_for_llm=4096,
        )

        assert config.max_pdf_pages_for_llm == 5
        assert config.max_image_size_for_llm == 2048
        assert config.max_other_size_for_llm == 4096


class TestAttachmentLimitsFromEnv:
    """Test per-type attachment limits loaded from environment variables."""

    def test_from_env(self, monkeypatch):
        """Verify env override for attachment limits."""
        from selko.config import load_config

        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("SUPABASE_URL", "http://localhost:54321")
        monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-key")
        monkeypatch.setenv("MAX_PDF_PAGES_FOR_LLM", "20")
        monkeypatch.setenv("MAX_IMAGE_SIZE_FOR_LLM", "2000000")
        monkeypatch.setenv("MAX_OTHER_SIZE_FOR_LLM", "3000000")

        config = load_config()

        assert config.max_pdf_pages_for_llm == 20
        assert config.max_image_size_for_llm == 2000000
        assert config.max_other_size_for_llm == 3000000

    def test_defaults_without_env(self, monkeypatch):
        """Verify defaults when env vars not set."""
        from selko.config import load_config

        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("SUPABASE_URL", "http://localhost:54321")
        monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-key")
        monkeypatch.delenv("MAX_PDF_PAGES_FOR_LLM", raising=False)
        monkeypatch.delenv("MAX_IMAGE_SIZE_FOR_LLM", raising=False)
        monkeypatch.delenv("MAX_OTHER_SIZE_FOR_LLM", raising=False)

        config = load_config()

        assert config.max_pdf_pages_for_llm == 10
        assert config.max_image_size_for_llm == 10 * 1024 * 1024
        assert config.max_other_size_for_llm == 20 * 1024 * 1024


class TestMemoryMonitorConfig:
    """Test memory monitor configuration parsing."""

    def test_env_overrides(self, monkeypatch):
        """MEMORY_LOG_INTERVAL_SECONDS and MEMORY_TRACEMALLOC are parsed."""
        from selko.config import load_config

        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("SUPABASE_URL", "http://localhost:54321")
        monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-key")
        monkeypatch.setenv("MEMORY_LOG_INTERVAL_SECONDS", "300")
        monkeypatch.setenv("MEMORY_TRACEMALLOC", "true")

        config = load_config()

        assert config.memory_log_interval_seconds == 300.0
        assert config.memory_tracemalloc is True

    def test_defaults_without_env(self, monkeypatch):
        """Monitor defaults to 60s interval with tracemalloc off."""
        from selko.config import load_config

        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("SUPABASE_URL", "http://localhost:54321")
        monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-key")
        monkeypatch.delenv("MEMORY_LOG_INTERVAL_SECONDS", raising=False)
        monkeypatch.delenv("MEMORY_TRACEMALLOC", raising=False)

        config = load_config()

        assert config.memory_log_interval_seconds == 60.0
        assert config.memory_tracemalloc is False


class TestLlmDefaultsAndFallback:
    """Production LLM pairing defaults and provisional fallback fill-in."""

    def test_resolve_provisional_gemini_to_qwen_flash(self):
        from selko.config import _resolve_provisional_fallback

        provider, model = _resolve_provisional_fallback("gemini", None, None)
        assert provider == "qwen"
        assert model == "qwen3.7-flash"

    def test_resolve_provisional_qwen_to_gemini_lite(self):
        from selko.config import _resolve_provisional_fallback

        provider, model = _resolve_provisional_fallback("qwen", None, None)
        assert provider == "gemini"
        assert model == "gemini-3.5-flash-lite"

    def test_resolve_provisional_respects_explicit(self):
        from selko.config import _resolve_provisional_fallback

        provider, model = _resolve_provisional_fallback(
            "gemini", "anthropic", "claude-sonnet-5"
        )
        assert provider == "anthropic"
        assert model == "claude-sonnet-5"

    def test_resolve_provisional_deepseek_to_vision_fallback(self):
        from selko.config import _resolve_provisional_fallback

        provider, model = _resolve_provisional_fallback("deepseek", None, None)
        assert provider == "gemini"
        assert model == "gemini-3.5-flash-lite"

    def test_resolve_provisional_zai_to_vision_fallback(self):
        from selko.config import _resolve_provisional_fallback

        provider, model = _resolve_provisional_fallback("zai", None, None)
        assert provider == "gemini"
        assert model == "gemini-3.5-flash-lite"


class TestVisionFallback:
    """Ensure text-only primaries never silently drop attachments."""

    def test_ensure_vision_fallback_for_deepseek(self, monkeypatch):
        from selko.config import _ensure_vision_fallback

        monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
        provider, model = _ensure_vision_fallback(
            "deepseek", "deepseek-v4-flash", None, None
        )
        assert provider == "gemini"
        assert model == "gemini-3.5-flash-lite"

    def test_ensure_vision_fallback_for_glm_text_only(self, monkeypatch):
        from selko.config import _ensure_vision_fallback

        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        provider, model = _ensure_vision_fallback("zai", "glm-5.2", None, None)
        assert provider == "gemini"
        assert model == "gemini-3.5-flash-lite"

    def test_ensure_vision_fallback_respects_vision_primary(self):
        from selko.config import _ensure_vision_fallback

        provider, model = _ensure_vision_fallback(
            "gemini", "gemini-3.5-flash-lite", "qwen", "qwen3.7-flash"
        )
        assert provider == "qwen"
        assert model == "qwen3.7-flash"

    def test_ensure_vision_fallback_respects_existing_vision_fallback(self, monkeypatch):
        from selko.config import _ensure_vision_fallback

        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        provider, model = _ensure_vision_fallback(
            "deepseek", "deepseek-v4-pro", "qwen", "qwen3.7-flash"
        )
        # Already vision — keep it, don't force gemini
        assert provider == "qwen"
        assert model == "qwen3.7-flash"

    def test_is_vision_model(self):
        from selko.config import _is_vision_model

        assert _is_vision_model("gemini-3.5-flash-lite") is True
        assert _is_vision_model("deepseek-v4-flash") is False
        assert _is_vision_model("glm-5.2") is False
        assert _is_vision_model("glm-4.6v") is True
        assert _is_vision_model(None) is False
        assert _is_vision_model("unknown-model-xyz") is False

    def test_load_config_default_pairing(self, monkeypatch):
        from selko.config import load_config

        monkeypatch.setattr("selko.config.dotenv_values", lambda *a, **k: {})
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("SUPABASE_URL", "http://localhost:54321")
        monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-key")
        for key in (
            "LLM_PROVIDER",
            "LLM_MODEL",
            "LLM_THINKING",
            "LLM_FALLBACK_PROVIDER",
            "LLM_FALLBACK_MODEL",
            "LLM_FALLBACK_THINKING",
        ):
            monkeypatch.delenv(key, raising=False)

        config = load_config()

        assert config.llm_provider == "gemini"
        assert config.llm_model is None  # resolved via PROVIDER_DEFAULT_MODEL
        assert config.llm_thinking == "minimal"
        assert config.llm_fallback_provider == "qwen"
        assert config.llm_fallback_model == "qwen3.7-flash"
