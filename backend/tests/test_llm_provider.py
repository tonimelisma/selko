"""Tests for LLM Provider abstraction."""

from unittest.mock import MagicMock, patch

import pytest

from selko.services.llm_provider import (
    MODEL_REGISTRY,
    PROVIDER_API_KEY_MAP,
    PROVIDER_DEFAULT_MODEL,
    AnthropicProvider,
    ContentPart,
    GeminiProvider,
    ImageContent,
    LLMProvider,
    LLMProviderError,
    LLMResponse,
    OpenAICompatibleProvider,
    _resize_image_if_needed,
    _strip_markdown_json,
    create_provider,
)


class TestModelRegistry:
    """Test the model registry."""

    def test_registry_has_27_models(self):
        """Test that all 27 models are in the registry."""
        assert len(MODEL_REGISTRY) == 27

    def test_all_models_have_required_fields(self):
        """Test that every model has required fields."""
        for model_name, entry in MODEL_REGISTRY.items():
            assert "provider" in entry, f"{model_name} missing 'provider'"
            assert "vision" in entry, f"{model_name} missing 'vision'"
            assert "json_schema" in entry, f"{model_name} missing 'json_schema'"
            assert "pricing" in entry, f"{model_name} missing 'pricing'"
            assert "input" in entry["pricing"], f"{model_name} missing pricing 'input'"
            assert "output" in entry["pricing"], f"{model_name} missing pricing 'output'"

    def test_non_native_sdk_models_have_base_url(self):
        """Test that non-native-SDK models have base_url."""
        native_sdk_providers = {"gemini", "anthropic"}
        for model_name, entry in MODEL_REGISTRY.items():
            if entry["provider"] not in native_sdk_providers:
                assert "base_url" in entry, f"{model_name} missing 'base_url'"

    def test_all_providers_have_default_model(self):
        """Test that every provider has a default model."""
        providers = set(entry["provider"] for entry in MODEL_REGISTRY.values())
        for provider in providers:
            assert provider in PROVIDER_DEFAULT_MODEL, f"No default model for {provider}"

    def test_all_providers_have_api_key_mapping(self):
        """Test that every provider has an API key mapping."""
        providers = set(entry["provider"] for entry in MODEL_REGISTRY.values())
        for provider in providers:
            assert provider in PROVIDER_API_KEY_MAP, f"No API key mapping for {provider}"

    def test_default_models_exist_in_registry(self):
        """Test that default models exist in the registry."""
        for provider, model in PROVIDER_DEFAULT_MODEL.items():
            assert model in MODEL_REGISTRY, f"Default model {model} for {provider} not in registry"


class TestCreateProvider:
    """Test provider factory function."""

    def test_create_gemini_provider(self):
        """Test creating a Gemini provider."""
        config = MagicMock()
        config.llm_provider = "gemini"
        config.llm_model = None
        config.gemini_api_key = "test-key"

        with patch("google.genai.Client"):
            provider = create_provider(config)

        assert isinstance(provider, GeminiProvider)
        assert provider.model == "gemini-3-flash-preview"
        assert provider.provider_name == "gemini"

    def test_create_openai_compatible_provider(self):
        """Test creating an OpenAI-compatible provider."""
        config = MagicMock()
        config.llm_provider = "moonshot"
        config.llm_model = "kimi-k2.5"
        config.moonshot_api_key = "test-key"

        with patch("openai.OpenAI"):
            provider = create_provider(config)

        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.model == "kimi-k2.5"
        assert provider.provider_name == "moonshot"
        assert provider.supports_vision is True

    def test_missing_api_key_raises_error(self):
        """Test that missing API key raises LLMProviderError."""
        config = MagicMock()
        config.llm_provider = "moonshot"
        config.llm_model = "kimi-k2.5"
        config.moonshot_api_key = None

        with pytest.raises(LLMProviderError, match="API key not configured"):
            create_provider(config)

    def test_unknown_model_raises_error(self):
        """Test that unknown model raises LLMProviderError."""
        config = MagicMock()
        config.llm_provider = "gemini"
        config.llm_model = "nonexistent-model"

        with pytest.raises(LLMProviderError, match="Unknown model"):
            create_provider(config)

    def test_unknown_provider_raises_error(self):
        """Test that unknown provider raises LLMProviderError."""
        config = MagicMock()
        config.llm_provider = "unknown_provider"
        config.llm_model = None

        with pytest.raises(LLMProviderError):
            create_provider(config)

    def test_default_model_selection(self):
        """Test that default model is selected when none specified."""
        config = MagicMock()
        config.llm_provider = "deepseek"
        config.llm_model = None
        config.deepseek_api_key = "test-key"

        with patch("openai.OpenAI"):
            provider = create_provider(config)

        assert provider.model == "deepseek-chat"

    def test_create_anthropic_provider(self):
        """Test creating an Anthropic provider."""
        config = MagicMock()
        config.llm_provider = "anthropic"
        config.llm_model = "claude-haiku-4-5-20251001"
        config.anthropic_api_key = "test-key"

        with patch("anthropic.Anthropic"):
            provider = create_provider(config)

        assert isinstance(provider, AnthropicProvider)
        assert provider.model == "claude-haiku-4-5-20251001"
        assert provider.provider_name == "anthropic"

    def test_create_openai_provider(self):
        """Test creating an OpenAI provider (uses OpenAI-compatible path)."""
        config = MagicMock()
        config.llm_provider = "openai"
        config.llm_model = "gpt-5-nano"
        config.openai_api_key = "test-key"

        with patch("openai.OpenAI"):
            provider = create_provider(config)

        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.model == "gpt-5-nano"
        assert provider.provider_name == "openai"
        assert provider.supports_vision is True


class TestImageContent:
    """Test ImageContent dataclass."""

    def test_creation(self):
        """Test creating ImageContent."""
        img = ImageContent(data=b"test", mime_type="image/png")
        assert img.data == b"test"
        assert img.mime_type == "image/png"

    def test_content_part_union(self):
        """Test ContentPart type accepts both str and ImageContent."""
        parts: list[ContentPart] = [
            "hello",
            ImageContent(data=b"img", mime_type="image/jpeg"),
        ]
        assert isinstance(parts[0], str)
        assert isinstance(parts[1], ImageContent)


class TestLLMResponse:
    """Test LLMResponse dataclass."""

    def test_creation_with_tokens(self):
        """Test creating LLMResponse with tokens."""
        resp = LLMResponse(text="hello", prompt_tokens=10, completion_tokens=5)
        assert resp.text == "hello"
        assert resp.prompt_tokens == 10
        assert resp.completion_tokens == 5

    def test_creation_without_tokens(self):
        """Test creating LLMResponse without tokens."""
        resp = LLMResponse(text="hello")
        assert resp.text == "hello"
        assert resp.prompt_tokens is None
        assert resp.completion_tokens is None


class TestResizeImage:
    """Test image resizing."""

    def test_non_image_returns_unchanged(self):
        """Test that non-image data is returned unchanged."""
        data = b"pdf content"
        result = _resize_image_if_needed(data, "application/pdf")
        assert result == data

    def test_small_image_returns_unchanged(self):
        """Test that small images are returned unchanged."""
        # Create a small 10x10 image
        from PIL import Image
        import io

        img = Image.new("RGB", (10, 10), color="red")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data = buf.getvalue()

        result = _resize_image_if_needed(data, "image/png", max_dimension=2048)
        assert result == data

    def test_large_image_is_resized(self):
        """Test that oversized images are resized."""
        from PIL import Image
        import io

        img = Image.new("RGB", (4000, 3000), color="blue")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data = buf.getvalue()

        result = _resize_image_if_needed(data, "image/png", max_dimension=2048)

        # Verify it was resized
        resized_img = Image.open(io.BytesIO(result))
        assert resized_img.size[0] <= 2048
        assert resized_img.size[1] <= 2048

    def test_invalid_image_returns_unchanged(self):
        """Test that invalid image data is returned unchanged."""
        data = b"not an image"
        result = _resize_image_if_needed(data, "image/png")
        assert result == data


class TestStripMarkdownJson:
    """Test markdown code-block stripping from JSON responses."""

    def test_strips_json_code_block(self):
        """Test that ```json ... ``` wrapping is removed."""
        text = '```json\n{"greeting": "hello"}\n```'
        assert _strip_markdown_json(text) == '{"greeting": "hello"}'

    def test_strips_plain_code_block(self):
        """Test that ``` ... ``` wrapping without language tag is removed."""
        text = '```\n{"greeting": "hello"}\n```'
        assert _strip_markdown_json(text) == '{"greeting": "hello"}'

    def test_plain_json_unchanged(self):
        """Test that plain JSON without markdown is returned unchanged."""
        text = '{"greeting": "hello"}'
        assert _strip_markdown_json(text) == '{"greeting": "hello"}'

    def test_multiline_json(self):
        """Test with multiline JSON inside code block."""
        text = '```json\n{\n  "events_found": true,\n  "events": []\n}\n```'
        result = _strip_markdown_json(text)
        assert '"events_found": true' in result
        assert result.startswith("{")
        assert result.endswith("}")

    def test_empty_string(self):
        """Test that empty string is returned unchanged."""
        assert _strip_markdown_json("") == ""
