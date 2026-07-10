"""Tests for LLM Provider abstraction."""

import json
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
    _sanitize_schema_for_gemini,
    _sanitize_schema_for_strict,
    _strip_markdown_json,
    create_provider,
)


class TestModelRegistry:
    """Test the model registry."""

    def test_registry_has_37_models(self):
        """Test that all 37 models are in the registry."""
        assert len(MODEL_REGISTRY) == 37

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

    def test_gpt5_models_have_reasoning_flag(self):
        """Test that all GPT-5 models are marked as reasoning models."""
        gpt5_models = [m for m in MODEL_REGISTRY if m.startswith("gpt-5")]
        assert len(gpt5_models) == 7
        for model_name in gpt5_models:
            assert MODEL_REGISTRY[model_name].get("reasoning") is True, (
                f"{model_name} should have reasoning=True"
            )

    def test_sonnet_has_adaptive_thinking(self):
        """Test that Sonnet models have the adaptive_thinking flag."""
        assert MODEL_REGISTRY["claude-sonnet-5"].get("adaptive_thinking") is True
        assert MODEL_REGISTRY["claude-sonnet-4-6"].get("adaptive_thinking") is True

    def test_requested_frontier_models_are_registered(self):
        """The July 2026 frontier eval targets remain available by exact ID."""
        expected = {
            "glm-5.2",
            "kimi-k2.6",
            "kimi-k2.7-code",
            "gpt-5.6-sol",
            "gpt-5.6-terra",
            "gpt-5.6-luna",
            "claude-sonnet-5",
            "claude-opus-4-8",
        }
        assert expected <= MODEL_REGISTRY.keys()

    def test_frontier_provider_defaults(self):
        """Providers default to the requested frontier generation."""
        assert PROVIDER_DEFAULT_MODEL["moonshot"] == "kimi-k2.6"
        assert PROVIDER_DEFAULT_MODEL["zai"] == "glm-5.2"
        assert PROVIDER_DEFAULT_MODEL["openai"] == "gpt-5.6-sol"

    def test_opus_4_8_has_adaptive_thinking(self):
        """Claude Opus 4.8 uses Anthropic adaptive thinking."""
        assert MODEL_REGISTRY["claude-opus-4-8"].get("adaptive_thinking") is True

    def test_anthropic_default_is_sonnet_5(self):
        """Test that the Anthropic provider defaults to Claude Sonnet 5."""
        assert PROVIDER_DEFAULT_MODEL["anthropic"] == "claude-sonnet-5"
        assert "claude-sonnet-5" in MODEL_REGISTRY

    def test_haiku_has_no_adaptive_thinking(self):
        """Test that Haiku 4.5 does not have adaptive_thinking flag."""
        assert MODEL_REGISTRY["claude-haiku-4-5-20251001"].get("adaptive_thinking") is not True

    def test_qwen_thinking_models_have_flag(self):
        """Test that Qwen3-VL and Qwen3.5 models have qwen_thinking flag."""
        thinking_models = ["qwen3.5-plus", "qwen3.5-flash", "qwen3-vl-plus", "qwen3-vl-flash"]
        for model_name in thinking_models:
            assert MODEL_REGISTRY[model_name].get("qwen_thinking") is True, (
                f"{model_name} should have qwen_thinking=True"
            )

    def test_older_qwen_models_no_thinking(self):
        """Test that older Qwen models don't have qwen_thinking flag."""
        non_thinking = ["qwen-vl-max", "qwen-vl-plus", "qwen-plus", "qwen-turbo"]
        for model_name in non_thinking:
            assert MODEL_REGISTRY[model_name].get("qwen_thinking") is not True, (
                f"{model_name} should NOT have qwen_thinking"
            )


class TestCreateProvider:
    """Test provider factory function."""

    def test_create_default_qwen_provider(self):
        """Test creating the default Qwen provider."""
        config = MagicMock()
        config.llm_provider = "qwen"
        config.llm_model = None
        config.alibaba_api_key = "test-key"

        with patch("openai.OpenAI"):
            provider = create_provider(config)

        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.model == "qwen3.5-flash"
        assert provider.provider_name == "qwen"

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
        assert provider.reasoning_model is True

    def test_non_reasoning_model_has_no_reasoning_flag(self):
        """Test that non-reasoning models don't get reasoning_model=True."""
        config = MagicMock()
        config.llm_provider = "moonshot"
        config.llm_model = "kimi-k2.5"
        config.moonshot_api_key = "test-key"

        with patch("openai.OpenAI"):
            provider = create_provider(config)

        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.reasoning_model is False

    def test_create_provider_passes_thinking_to_gemini(self):
        """Test that thinking level is passed through to GeminiProvider."""
        config = MagicMock()
        config.llm_provider = "gemini"
        config.llm_model = None
        config.gemini_api_key = "test-key"

        with patch("google.genai.Client"):
            provider = create_provider(config, thinking="medium")

        assert isinstance(provider, GeminiProvider)
        assert provider.thinking == "medium"

    def test_create_provider_passes_thinking_to_openai(self):
        """Test that thinking level is passed through to OpenAICompatibleProvider."""
        config = MagicMock()
        config.llm_provider = "openai"
        config.llm_model = "gpt-5-nano"
        config.openai_api_key = "test-key"

        with patch("openai.OpenAI"):
            provider = create_provider(config, thinking="medium")

        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.thinking == "medium"

    def test_create_provider_passes_thinking_to_anthropic(self):
        """Test that thinking level is passed through to AnthropicProvider."""
        config = MagicMock()
        config.llm_provider = "anthropic"
        config.llm_model = "claude-haiku-4-5-20251001"
        config.anthropic_api_key = "test-key"

        with patch("anthropic.Anthropic"):
            provider = create_provider(config, thinking="none")

        assert isinstance(provider, AnthropicProvider)
        assert provider.thinking == "none"
        assert provider.adaptive_thinking is False

    def test_create_provider_sonnet_gets_adaptive_thinking(self):
        """Test that Sonnet 4.6 gets adaptive_thinking=True via create_provider."""
        config = MagicMock()
        config.llm_provider = "anthropic"
        config.llm_model = "claude-sonnet-4-6"
        config.anthropic_api_key = "test-key"

        with patch("anthropic.Anthropic"):
            provider = create_provider(config, thinking="medium")

        assert isinstance(provider, AnthropicProvider)
        assert provider.thinking == "medium"
        assert provider.adaptive_thinking is True

    def test_create_provider_qwen_thinking_model_gets_flag(self):
        """Test that Qwen3-VL-Plus gets qwen_thinking=True via create_provider."""
        config = MagicMock()
        config.llm_provider = "qwen"
        config.llm_model = "qwen3-vl-plus"
        config.alibaba_api_key = "test-key"

        with patch("openai.OpenAI"):
            provider = create_provider(config, thinking="low")

        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.qwen_thinking is True
        assert provider.thinking == "low"

    def test_create_provider_qwen_non_thinking_model_no_flag(self):
        """Test that older Qwen model gets qwen_thinking=False."""
        config = MagicMock()
        config.llm_provider = "qwen"
        config.llm_model = "qwen-vl-max"
        config.alibaba_api_key = "test-key"

        with patch("openai.OpenAI"):
            provider = create_provider(config, thinking="none")

        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.qwen_thinking is False


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

    def test_strips_think_blocks(self):
        """Test that <think>...</think> blocks are removed."""
        text = '<think>analyzing...</think>\n{"events_found": true}'
        result = _strip_markdown_json(text)
        assert json.loads(result) == {"events_found": True}

    def test_strips_stray_think_close_tags(self):
        """Test that stray </think> tags are removed (ZAI-style output)."""
        text = '{"schema": "echo"}\n</think>\ntext\n{"events_found": true}'
        result = _strip_markdown_json(text)
        assert json.loads(result) == {"events_found": True}

    def test_extracts_last_json_from_multi_object_response(self):
        """Test extraction of last JSON object when response contains multiple."""
        text = (
            '{"$defs": {"A": {"type": "object"}}}\n'
            'End the code block.\n'
            '{"events_found": true, "events": [{"title": "Test"}]}\n'
            'End the code block.'
        )
        result = _strip_markdown_json(text)
        parsed = json.loads(result)
        assert parsed["events_found"] is True
        assert parsed["events"][0]["title"] == "Test"

    def test_handles_think_blocks_with_schema_echo(self):
        """Test ZAI-style output: schema echo + think blocks + actual JSON."""
        schema_json = json.dumps({"$defs": {"Event": {"type": "object"}}})
        actual_json = json.dumps({"events_found": True, "events": []})
        text = (
            f"\n\n{schema_json}\n</think>\n"
            f"I'll extract events.\n\n{actual_json}\n"
            f"End block.\n</think>\n{actual_json}\nEnd block."
        )
        result = _strip_markdown_json(text)
        parsed = json.loads(result)
        assert parsed["events_found"] is True


class TestOpenAIReasoningEffort:
    """Test that reasoning models get reasoning_effort in API calls."""

    def test_reasoning_model_passes_reasoning_effort_low(self):
        """GPT-5 models with thinking='low' should pass reasoning_effort='low'."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content='{"events_found": false, "events": []}'))]
        mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
        mock_client.chat.completions.create.return_value = mock_response

        with patch("openai.OpenAI", return_value=mock_client):
            provider = OpenAICompatibleProvider(
                api_key="test-key",
                model="gpt-5-nano",
                base_url="https://api.openai.com/v1",
                provider_name="openai",
                supports_vision=True,
                reasoning_model=True,
                thinking="low",
            )

        provider.generate(["Hello"])

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs.get("reasoning_effort") == "low"

    def test_reasoning_model_passes_reasoning_effort_medium(self):
        """GPT-5 models with thinking='medium' should pass reasoning_effort='medium'."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content='{"events_found": false, "events": []}'))]
        mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
        mock_client.chat.completions.create.return_value = mock_response

        with patch("openai.OpenAI", return_value=mock_client):
            provider = OpenAICompatibleProvider(
                api_key="test-key",
                model="gpt-5-nano",
                base_url="https://api.openai.com/v1",
                provider_name="openai",
                supports_vision=True,
                reasoning_model=True,
                thinking="medium",
            )

        provider.generate(["Hello"])

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs.get("reasoning_effort") == "medium"

    def test_reasoning_model_with_thinking_none_omits_reasoning_effort(self):
        """Reasoning model with thinking='none' should NOT pass reasoning_effort."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content='{"events_found": false, "events": []}'))]
        mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
        mock_client.chat.completions.create.return_value = mock_response

        with patch("openai.OpenAI", return_value=mock_client):
            provider = OpenAICompatibleProvider(
                api_key="test-key",
                model="gpt-5-nano",
                base_url="https://api.openai.com/v1",
                provider_name="openai",
                supports_vision=True,
                reasoning_model=True,
                thinking="none",
            )

        provider.generate(["Hello"])

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert "reasoning_effort" not in call_kwargs

    def test_non_reasoning_model_omits_reasoning_effort(self):
        """Non-reasoning models should NOT pass reasoning_effort."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content='{"result": "ok"}'))]
        mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
        mock_client.chat.completions.create.return_value = mock_response

        with patch("openai.OpenAI", return_value=mock_client):
            provider = OpenAICompatibleProvider(
                api_key="test-key",
                model="kimi-k2.5",
                base_url="https://api.moonshot.ai/v1",
                provider_name="moonshot",
                supports_vision=True,
                reasoning_model=False,
            )

        provider.generate(["Hello"])

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert "reasoning_effort" not in call_kwargs


class TestAnthropicProviderPDFHandling:
    """Test that AnthropicProvider uses correct content types for PDFs vs images."""

    def test_pdf_uses_document_type(self):
        """Regression: PDFs must use 'type': 'document', not 'type': 'image'."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text='{"events_found": false, "events": []}')]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)
        mock_client.messages.create.return_value = mock_response

        with patch("anthropic.Anthropic", return_value=mock_client):
            provider = AnthropicProvider(api_key="test-key", model="claude-haiku-4-5-20251001")

        # Call generate with a PDF attachment
        contents = [
            "Analyze this PDF",
            ImageContent(data=b"%PDF-1.4 test pdf content", mime_type="application/pdf"),
        ]

        with patch("selko.services.format_conversion.prepare_content_for_provider") as mock_convert:
            from selko.services.format_conversion import ConvertedContent
            # Simulate format_conversion passing PDF through (Anthropic accepts PDFs)
            mock_convert.return_value = [
                ConvertedContent(data=b"%PDF-1.4 test pdf content", mime_type="application/pdf")
            ]
            provider.generate(contents)

        # Verify the API was called with "type": "document" for the PDF
        call_args = mock_client.messages.create.call_args
        message_content = call_args.kwargs["messages"][0]["content"]

        pdf_parts = [p for p in message_content if p.get("type") == "document"]
        image_parts = [p for p in message_content if p.get("type") == "image"]

        assert len(pdf_parts) == 1, "PDF should use 'type': 'document'"
        assert len(image_parts) == 0, "PDF should NOT use 'type': 'image'"
        assert pdf_parts[0]["source"]["media_type"] == "application/pdf"

    def test_image_uses_image_type(self):
        """Images should still use 'type': 'image'."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text='{"events_found": false, "events": []}')]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)
        mock_client.messages.create.return_value = mock_response

        with patch("anthropic.Anthropic", return_value=mock_client):
            provider = AnthropicProvider(api_key="test-key", model="claude-haiku-4-5-20251001")

        # Create a tiny valid PNG for the test
        from PIL import Image
        import io
        img = Image.new("RGB", (10, 10), color="red")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_data = buf.getvalue()

        contents = [
            "Analyze this image",
            ImageContent(data=png_data, mime_type="image/png"),
        ]

        with patch("selko.services.format_conversion.prepare_content_for_provider") as mock_convert:
            from selko.services.format_conversion import ConvertedContent
            mock_convert.return_value = [
                ConvertedContent(data=png_data, mime_type="image/png")
            ]
            provider.generate(contents)

        call_args = mock_client.messages.create.call_args
        message_content = call_args.kwargs["messages"][0]["content"]

        image_parts = [p for p in message_content if p.get("type") == "image"]
        document_parts = [p for p in message_content if p.get("type") == "document"]

        assert len(image_parts) == 1, "Image should use 'type': 'image'"
        assert len(document_parts) == 0, "Image should NOT use 'type': 'document'"
        assert image_parts[0]["source"]["media_type"] == "image/png"


class TestAnthropicAdaptiveThinking:
    """Test that Anthropic adaptive thinking is passed correctly."""

    def test_adaptive_thinking_low(self):
        """Sonnet 4.6 with thinking='low' should pass adaptive thinking + effort."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text='{"events_found": false, "events": []}')]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)
        mock_client.messages.create.return_value = mock_response

        with patch("anthropic.Anthropic", return_value=mock_client):
            provider = AnthropicProvider(
                api_key="test-key", model="claude-sonnet-4-6",
                thinking="low", adaptive_thinking=True,
            )

        provider.generate(["Hello"])

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["thinking"] == {"type": "adaptive"}
        assert call_kwargs["output_config"] == {"effort": "low"}
        assert call_kwargs["max_tokens"] == 16000

    def test_adaptive_thinking_medium(self):
        """Sonnet 4.6 with thinking='medium' should pass effort='medium'."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text='{"events_found": false, "events": []}')]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)
        mock_client.messages.create.return_value = mock_response

        with patch("anthropic.Anthropic", return_value=mock_client):
            provider = AnthropicProvider(
                api_key="test-key", model="claude-sonnet-4-6",
                thinking="medium", adaptive_thinking=True,
            )

        provider.generate(["Hello"])

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["thinking"] == {"type": "adaptive"}
        assert call_kwargs["output_config"] == {"effort": "medium"}

    def test_adaptive_thinking_none_omits_thinking(self):
        """Sonnet 4.6 with thinking='none' should NOT pass thinking params."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text='{"events_found": false, "events": []}')]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)
        mock_client.messages.create.return_value = mock_response

        with patch("anthropic.Anthropic", return_value=mock_client):
            provider = AnthropicProvider(
                api_key="test-key", model="claude-sonnet-4-6",
                thinking="none", adaptive_thinking=True,
            )

        provider.generate(["Hello"])

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "thinking" not in call_kwargs
        assert "output_config" not in call_kwargs
        assert call_kwargs["max_tokens"] == 4096

    def test_non_adaptive_model_omits_thinking(self):
        """Haiku (no adaptive_thinking) should NOT pass thinking params."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text='{"events_found": false, "events": []}')]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)
        mock_client.messages.create.return_value = mock_response

        with patch("anthropic.Anthropic", return_value=mock_client):
            provider = AnthropicProvider(
                api_key="test-key", model="claude-haiku-4-5-20251001",
                thinking="low", adaptive_thinking=False,
            )

        provider.generate(["Hello"])

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "thinking" not in call_kwargs
        assert "output_config" not in call_kwargs


class TestQwenThinking:
    """Test that Qwen thinking params are passed correctly via extra_body."""

    def _make_mock_client(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content='{"events_found": false, "events": []}'))]
        mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
        mock_client.chat.completions.create.return_value = mock_response
        return mock_client

    def test_qwen_thinking_low(self):
        """Qwen model with thinking='low' should pass enable_thinking + thinking_budget."""
        mock_client = self._make_mock_client()

        with patch("openai.OpenAI", return_value=mock_client):
            provider = OpenAICompatibleProvider(
                api_key="test-key", model="qwen3-vl-plus",
                base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                provider_name="qwen", qwen_thinking=True, thinking="low",
            )

        provider.generate(["Hello"])

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["extra_body"] == {
            "enable_thinking": True,
            "thinking_budget": 2048,
        }

    def test_qwen_thinking_medium(self):
        """Qwen model with thinking='medium' should pass higher thinking_budget."""
        mock_client = self._make_mock_client()

        with patch("openai.OpenAI", return_value=mock_client):
            provider = OpenAICompatibleProvider(
                api_key="test-key", model="qwen3.5-plus",
                base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                provider_name="qwen", qwen_thinking=True, thinking="medium",
            )

        provider.generate(["Hello"])

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["extra_body"] == {
            "enable_thinking": True,
            "thinking_budget": 8192,
        }

    def test_qwen_thinking_none_disables(self):
        """Qwen model with thinking='none' should explicitly disable thinking."""
        mock_client = self._make_mock_client()

        with patch("openai.OpenAI", return_value=mock_client):
            provider = OpenAICompatibleProvider(
                api_key="test-key", model="qwen3-vl-plus",
                base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                provider_name="qwen", qwen_thinking=True, thinking="none",
            )

        provider.generate(["Hello"])

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["extra_body"] == {"enable_thinking": False}

    def test_non_thinking_qwen_no_extra_body(self):
        """Older Qwen model (no qwen_thinking) should NOT pass extra_body."""
        mock_client = self._make_mock_client()

        with patch("openai.OpenAI", return_value=mock_client):
            provider = OpenAICompatibleProvider(
                api_key="test-key", model="qwen-vl-max",
                base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                provider_name="qwen", qwen_thinking=False, thinking="none",
            )

        provider.generate(["Hello"])

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert "extra_body" not in call_kwargs


class TestSanitizeSchemaForStrict:
    """Regression tests for _sanitize_schema_for_strict (Bug 1: Moonshot schema)."""

    def test_resolves_all_refs_and_removes_defs(self):
        """$ref and $defs must be fully resolved and removed."""
        schema = {
            "type": "object",
            "properties": {
                "event": {"$ref": "#/$defs/CalendarEvent"},
            },
            "$defs": {
                "CalendarEvent": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                    },
                },
            },
        }
        result = _sanitize_schema_for_strict(schema)

        # No $ref or $defs should remain
        result_str = str(result)
        assert "$ref" not in result_str
        assert "$defs" not in result_str
        # The reference should be inlined
        assert result["properties"]["event"]["properties"]["title"]["type"] == "string"

    def test_removes_default_alongside_anyof(self):
        """'default' must be removed when 'anyOf' is present (Moonshot requirement)."""
        schema = {
            "type": "object",
            "properties": {
                "end_datetime": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "default": None,
                    "title": "End Datetime",
                },
            },
        }
        result = _sanitize_schema_for_strict(schema)

        prop = result["properties"]["end_datetime"]
        assert "default" not in prop
        assert "anyOf" in prop

    def test_nested_ref_with_anyof_and_default(self):
        """Nested $ref with anyOf+default must be fully resolved and sanitized."""
        schema = {
            "type": "object",
            "properties": {
                "event": {"$ref": "#/$defs/CalendarEvent"},
            },
            "$defs": {
                "CalendarEvent": {
                    "type": "object",
                    "title": "CalendarEvent",
                    "properties": {
                        "start_datetime": {
                            "anyOf": [{"type": "string"}, {"type": "null"}],
                            "default": None,
                            "title": "Start Datetime",
                        },
                        "end_datetime": {
                            "anyOf": [{"type": "string"}, {"type": "null"}],
                            "default": None,
                            "title": "End Datetime",
                        },
                    },
                },
            },
        }
        result = _sanitize_schema_for_strict(schema)

        result_str = str(result)
        assert "$ref" not in result_str
        assert "$defs" not in result_str
        assert "default" not in result_str

        event = result["properties"]["event"]
        assert event["type"] == "object"
        assert "default" not in event["properties"]["start_datetime"]
        assert "default" not in event["properties"]["end_datetime"]

    def test_adds_additional_properties_false(self):
        """All objects must have additionalProperties: false for strict mode."""
        schema = {
            "type": "object",
            "properties": {
                "nested": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                    },
                },
            },
        }
        result = _sanitize_schema_for_strict(schema)

        assert result["additionalProperties"] is False
        assert result["properties"]["nested"]["additionalProperties"] is False

    def test_circular_ref_does_not_loop(self):
        """Circular $ref must not cause infinite recursion."""
        schema = {
            "type": "object",
            "properties": {
                "self_ref": {"$ref": "#/$defs/Node"},
            },
            "$defs": {
                "Node": {
                    "type": "object",
                    "properties": {
                        "child": {"$ref": "#/$defs/Node"},
                    },
                },
            },
        }
        # Should not raise RecursionError
        result = _sanitize_schema_for_strict(schema)
        assert "$ref" not in str(result)

    def test_strips_format_from_anyof_items(self):
        """'format' must be removed from anyOf items (Moonshot rejects it)."""
        schema = {
            "type": "object",
            "properties": {
                "start_datetime": {
                    "anyOf": [
                        {"format": "date-time", "type": "string"},
                        {"type": "null"},
                    ],
                    "default": None,
                },
            },
        }
        result = _sanitize_schema_for_strict(schema)

        prop = result["properties"]["start_datetime"]
        assert "anyOf" in prop
        for item in prop["anyOf"]:
            assert "format" not in item, (
                "format must be stripped from anyOf items for Moonshot compat"
            )


class TestSanitizeSchemaForGemini:
    """Regression tests for _sanitize_schema_for_gemini (Bug 3: Gemini anyOf)."""

    def test_converts_anyof_with_null_to_nullable(self):
        """anyOf: [type, null] must become {type, nullable: true}."""
        schema = {
            "type": "object",
            "properties": {
                "end_datetime": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "default": None,
                },
            },
        }
        result = _sanitize_schema_for_gemini(schema)

        prop = result["properties"]["end_datetime"]
        assert "anyOf" not in prop
        assert prop["type"] == "string"
        assert prop["nullable"] is True

    def test_removes_unsupported_keywords(self):
        """title, default, additionalProperties must be removed."""
        schema = {
            "type": "object",
            "title": "MySchema",
            "additionalProperties": False,
            "properties": {
                "field": {
                    "type": "string",
                    "title": "Field",
                    "default": "hello",
                },
            },
        }
        result = _sanitize_schema_for_gemini(schema)

        assert "title" not in result
        assert "additionalProperties" not in result
        assert "title" not in result["properties"]["field"]
        assert "default" not in result["properties"]["field"]

    def test_resolves_refs(self):
        """$ref/$defs must be resolved for Gemini."""
        schema = {
            "type": "object",
            "properties": {
                "event": {"$ref": "#/$defs/Event"},
            },
            "$defs": {
                "Event": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                    },
                },
            },
        }
        result = _sanitize_schema_for_gemini(schema)

        assert "$ref" not in str(result)
        assert "$defs" not in str(result)
        assert result["properties"]["event"]["properties"]["name"]["type"] == "string"

    def test_merge_schema_pattern(self):
        """Hand-built merge schema pattern should work after sanitization."""
        schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start_datetime": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                },
                "end_datetime": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                },
                "location": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                },
            },
        }
        result = _sanitize_schema_for_gemini(schema)

        for field in ("start_datetime", "end_datetime", "location"):
            prop = result["properties"][field]
            assert "anyOf" not in prop, f"{field} still has anyOf"
            assert prop["type"] == "string"
            assert prop["nullable"] is True

    def test_preserves_title_and_description_property_names(self):
        """Property names 'title' and 'description' must survive sanitization.

        Regression: _resolve() was processing the properties container dict
        through the generic path, where 'description' (a property NAME) was
        mistaken for the schema keyword, causing is_schema_node=True and
        then 'title' (also a property NAME) got stripped.
        """
        schema = {
            "type": "object",
            "$defs": {
                "CalendarEvent": {
                    "type": "object",
                    "title": "CalendarEvent",
                    "properties": {
                        "title": {
                            "type": "string",
                            "title": "Title",
                            "description": "Event title",
                        },
                        "description": {
                            "type": "string",
                            "title": "Description",
                            "description": "Event description",
                        },
                        "start_datetime": {
                            "anyOf": [{"type": "string"}, {"type": "null"}],
                            "title": "Start Datetime",
                            "default": None,
                        },
                    },
                    "required": ["title", "description"],
                },
            },
            "properties": {
                "events": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/CalendarEvent"},
                },
            },
        }
        result = _sanitize_schema_for_gemini(schema)

        event_props = result["properties"]["events"]["items"]["properties"]
        assert "title" in event_props, "Property 'title' was stripped"
        assert "description" in event_props, "Property 'description' was stripped"
        assert event_props["title"]["type"] == "string"
        assert event_props["description"]["type"] == "string"
        # Metadata 'title' keys should be stripped from property values
        assert "title" not in event_props["title"], "Metadata 'title' not stripped"
        assert "title" not in event_props["description"], "Metadata 'title' not stripped"
        # anyOf should be converted
        assert event_props["start_datetime"]["nullable"] is True

    def test_real_event_extraction_schema(self):
        """The actual EventExtractionResponse schema must preserve all fields."""
        from selko.services.event_processing import EventExtractionResponse

        schema = EventExtractionResponse.model_json_schema()
        result = _sanitize_schema_for_gemini(schema)

        # Navigate to CalendarEvent properties
        events_prop = result["properties"]["events"]
        cal_props = events_prop["items"]["properties"]

        expected_fields = [
            "title", "start_datetime", "end_datetime", "all_day",
            "location", "description", "importance",
        ]
        for field in expected_fields:
            assert field in cal_props, f"CalendarEvent.{field} was stripped"

        # No $defs/$ref/anyOf should remain
        import json
        schema_str = json.dumps(result)
        assert "$defs" not in schema_str
        assert "$ref" not in schema_str
        assert "anyOf" not in schema_str


class TestResizeImageDegenerateFiltering:
    """Regression tests for degenerate image filtering (Bug 5)."""

    def test_1x1_tracking_pixel_returns_none(self):
        """1x1 tracking pixel must be filtered out."""
        import io
        from PIL import Image

        img = Image.new("RGB", (1, 1), color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data = buf.getvalue()

        result = _resize_image_if_needed(data, "image/png")
        assert result is None

    def test_5x5_spacer_returns_none(self):
        """5x5 spacer image must be filtered out."""
        import io
        from PIL import Image

        img = Image.new("RGB", (5, 5), color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data = buf.getvalue()

        result = _resize_image_if_needed(data, "image/png")
        assert result is None

    def test_1x100_narrow_image_returns_none(self):
        """1-pixel-wide image must be filtered out."""
        import io
        from PIL import Image

        img = Image.new("RGB", (1, 100), color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data = buf.getvalue()

        result = _resize_image_if_needed(data, "image/png")
        assert result is None

    def test_10x10_minimum_passes(self):
        """10x10 image (at minimum threshold) should pass through."""
        import io
        from PIL import Image

        img = Image.new("RGB", (10, 10), color="red")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data = buf.getvalue()

        result = _resize_image_if_needed(data, "image/png")
        assert result is not None
        assert result == data
