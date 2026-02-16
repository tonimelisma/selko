"""LLM Provider abstraction for multi-backend support.

Provides a unified interface for multiple LLM providers:
- Google Gemini (native SDK)
- Moonshot/Kimi, Z.AI/Zhipu, Alibaba/Qwen, DeepSeek, MiniMax (OpenAI-compatible)

All providers implement the same LLMProvider interface, allowing transparent
switching between providers via environment variables.
"""

import base64
import io
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class ImageContent:
    """Binary image/document content for multimodal LLM calls."""

    data: bytes
    mime_type: str  # "image/png", "image/jpeg", "application/pdf", etc.


# A content part is either text or binary image content
ContentPart = str | ImageContent


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""

    text: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None


# Model registry: every supported model with provider, capabilities, and pricing
# Pricing is per 1M tokens in USD
MODEL_REGISTRY: dict[str, dict[str, Any]] = {
    # --- Gemini (1 model) ---
    "gemini-3-flash-preview": {
        "provider": "gemini",
        "vision": True,
        "json_schema": True,
        "pricing": {"input": 0.15, "output": 0.60},
    },
    # --- Moonshot/Kimi (4 models) ---
    "kimi-k2.5": {
        "provider": "moonshot",
        "vision": True,
        "json_schema": True,
        "base_url": "https://api.moonshot.ai/v1",
        "pricing": {"input": 0.60, "output": 3.00},
    },
    "moonshot-v1-8k-vision-preview": {
        "provider": "moonshot",
        "vision": True,
        "json_schema": True,
        "base_url": "https://api.moonshot.ai/v1",
        "pricing": {"input": 0.20, "output": 2.00},
    },
    "moonshot-v1-32k-vision-preview": {
        "provider": "moonshot",
        "vision": True,
        "json_schema": True,
        "base_url": "https://api.moonshot.ai/v1",
        "pricing": {"input": 1.00, "output": 3.00},
    },
    "moonshot-v1-128k-vision-preview": {
        "provider": "moonshot",
        "vision": True,
        "json_schema": True,
        "base_url": "https://api.moonshot.ai/v1",
        "pricing": {"input": 2.00, "output": 5.00},
    },
    # --- Z.AI / Zhipu (6 models) ---
    "glm-5": {
        "provider": "zai",
        "vision": False,
        "json_schema": True,
        "base_url": "https://api.z.ai/api/paas/v4/",
        "pricing": {"input": 1.00, "output": 3.20},
    },
    "glm-4.6v": {
        "provider": "zai",
        "vision": True,
        "json_schema": True,
        "base_url": "https://api.z.ai/api/paas/v4/",
        "pricing": {"input": 0.30, "output": 0.90},
    },
    "glm-4.6v-flashx": {
        "provider": "zai",
        "vision": True,
        "json_schema": True,
        "base_url": "https://api.z.ai/api/paas/v4/",
        "pricing": {"input": 0.04, "output": 0.40},
    },
    "glm-4.6v-flash": {
        "provider": "zai",
        "vision": True,
        "json_schema": True,
        "base_url": "https://api.z.ai/api/paas/v4/",
        "pricing": {"input": 0.00, "output": 0.00},
    },
    "glm-4.5v": {
        "provider": "zai",
        "vision": True,
        "json_schema": True,
        "base_url": "https://api.z.ai/api/paas/v4/",
        "pricing": {"input": 0.60, "output": 1.80},
    },
    "glm-4.7-flash": {
        "provider": "zai",
        "vision": False,
        "json_schema": True,
        "base_url": "https://api.z.ai/api/paas/v4/",
        "pricing": {"input": 0.00, "output": 0.00},
    },
    # --- Alibaba / Qwen (6 models) ---
    "qwen3-vl-plus": {
        "provider": "qwen",
        "vision": True,
        "json_schema": False,
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "pricing": {"input": 0.40, "output": 3.20},
    },
    "qwen3-vl-flash": {
        "provider": "qwen",
        "vision": True,
        "json_schema": False,
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "pricing": {"input": 0.08, "output": 0.68},
    },
    "qwen-vl-max": {
        "provider": "qwen",
        "vision": True,
        "json_schema": False,
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "pricing": {"input": 0.80, "output": 3.20},
    },
    "qwen-vl-plus": {
        "provider": "qwen",
        "vision": True,
        "json_schema": False,
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "pricing": {"input": 0.21, "output": 0.63},
    },
    "qwen-plus": {
        "provider": "qwen",
        "vision": False,
        "json_schema": True,
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "pricing": {"input": 0.80, "output": 8.00},
    },
    "qwen-turbo": {
        "provider": "qwen",
        "vision": False,
        "json_schema": True,
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "pricing": {"input": 0.05, "output": 0.35},
    },
    # --- DeepSeek (2 models, text-only) ---
    "deepseek-chat": {
        "provider": "deepseek",
        "vision": False,
        "json_schema": True,
        "base_url": "https://api.deepseek.com/v1",
        "pricing": {"input": 0.27, "output": 1.10},
    },
    "deepseek-reasoner": {
        "provider": "deepseek",
        "vision": False,
        "json_schema": True,
        "base_url": "https://api.deepseek.com/v1",
        "pricing": {"input": 0.55, "output": 2.19},
    },
    # --- MiniMax (2 models, text-only) ---
    "MiniMax-M2.5": {
        "provider": "minimax",
        "vision": False,
        "json_schema": True,
        "base_url": "https://api.minimax.io/v1",
        "pricing": {"input": 0.30, "output": 1.20},
    },
    "MiniMax-01": {
        "provider": "minimax",
        "vision": False,
        "json_schema": True,
        "base_url": "https://api.minimax.io/v1",
        "pricing": {"input": 0.20, "output": 1.10},
    },
}

# Map provider name → Config attribute name for API key
PROVIDER_API_KEY_MAP = {
    "gemini": "gemini_api_key",
    "moonshot": "moonshot_api_key",
    "zai": "zai_api_key",
    "qwen": "alibaba_api_key",
    "deepseek": "deepseek_api_key",
    "minimax": "minimax_api_key",
}

# Default model per provider (first listed model)
PROVIDER_DEFAULT_MODEL = {
    "gemini": "gemini-3-flash-preview",
    "moonshot": "kimi-k2.5",
    "zai": "glm-4.6v-flash",
    "qwen": "qwen3-vl-flash",
    "deepseek": "deepseek-chat",
    "minimax": "MiniMax-M2.5",
}


def _resize_image_if_needed(
    data: bytes, mime_type: str, max_dimension: int = 2048
) -> bytes:
    """Resize image if either dimension exceeds max_dimension.

    Args:
        data: Raw image bytes.
        mime_type: MIME type of the image.
        max_dimension: Maximum allowed dimension in pixels.

    Returns:
        Original or resized image bytes.
    """
    if not mime_type.startswith("image/"):
        return data

    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        w, h = img.size

        if w <= max_dimension and h <= max_dimension:
            return data

        # Calculate new size preserving aspect ratio
        if w > h:
            new_w = max_dimension
            new_h = int(h * (max_dimension / w))
        else:
            new_h = max_dimension
            new_w = int(w * (max_dimension / h))

        img = img.resize((new_w, new_h), Image.LANCZOS)

        # Save to bytes in original format
        output = io.BytesIO()
        fmt_map = {
            "image/jpeg": "JPEG",
            "image/png": "PNG",
            "image/gif": "GIF",
            "image/webp": "WEBP",
        }
        fmt = fmt_map.get(mime_type, "PNG")
        img.save(output, format=fmt)
        resized = output.getvalue()

        logger.debug(
            f"Resized image from {w}x{h} to {new_w}x{new_h} "
            f"({len(data)} → {len(resized)} bytes)"
        )
        return resized

    except Exception as e:
        logger.warning(f"Failed to resize image: {e}")
        return data


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    provider_name: str
    model: str
    supports_vision: bool
    supports_json_schema: bool

    @abstractmethod
    def generate(
        self,
        contents: list[ContentPart],
        json_schema: Optional[dict] = None,
    ) -> LLMResponse:
        """Generate a response from the LLM.

        Args:
            contents: List of text and/or image content parts.
            json_schema: Optional JSON schema for structured output.

        Returns:
            LLMResponse with text and token counts.
        """
        ...


class GeminiProvider(LLMProvider):
    """Google Gemini provider using native google-genai SDK."""

    def __init__(self, api_key: str, model: str):
        from google import genai

        self.provider_name = "gemini"
        self.model = model
        self.supports_vision = True
        self.supports_json_schema = True
        self.client = genai.Client(api_key=api_key)
        logger.debug(f"Initialized Gemini provider with model {model}")

    def generate(
        self,
        contents: list[ContentPart],
        json_schema: Optional[dict] = None,
    ) -> LLMResponse:
        from google.genai import types

        # Convert ContentPart list to Gemini format
        gemini_parts: list[Any] = []
        for part in contents:
            if isinstance(part, str):
                gemini_parts.append(part)
            elif isinstance(part, ImageContent):
                resized = _resize_image_if_needed(part.data, part.mime_type)
                gemini_parts.append({
                    "inline_data": {
                        "mime_type": part.mime_type,
                        "data": base64.b64encode(resized).decode("utf-8"),
                    }
                })

        # Build generation config
        config_kwargs: dict[str, Any] = {}
        if json_schema is not None:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = json_schema
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level="low")
        config = types.GenerateContentConfig(**config_kwargs)

        response = self.client.models.generate_content(
            model=self.model,
            contents=gemini_parts,
            config=config,
        )

        # Extract token counts
        prompt_tokens = None
        completion_tokens = None
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            prompt_tokens = getattr(
                response.usage_metadata, "prompt_token_count", None
            )
            completion_tokens = getattr(
                response.usage_metadata, "candidates_token_count", None
            )

        return LLMResponse(
            text=response.text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )


class OpenAICompatibleProvider(LLMProvider):
    """Provider for OpenAI-compatible APIs (Moonshot, Z.AI, Qwen, DeepSeek, MiniMax)."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        provider_name: str,
        supports_vision: bool = False,
        supports_json_schema: bool = True,
    ):
        from openai import OpenAI

        self.provider_name = provider_name
        self.model = model
        self.supports_vision = supports_vision
        self.supports_json_schema = supports_json_schema
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        logger.debug(
            f"Initialized {provider_name} provider with model {model} "
            f"at {base_url}"
        )

    def generate(
        self,
        contents: list[ContentPart],
        json_schema: Optional[dict] = None,
    ) -> LLMResponse:
        # Build message content parts
        message_content: list[dict[str, Any]] = []
        for part in contents:
            if isinstance(part, str):
                message_content.append({"type": "text", "text": part})
            elif isinstance(part, ImageContent):
                if not self.supports_vision:
                    logger.warning(
                        f"Skipping image for text-only provider {self.provider_name}"
                    )
                    continue
                resized = _resize_image_if_needed(part.data, part.mime_type)
                b64 = base64.b64encode(resized).decode("utf-8")
                data_url = f"data:{part.mime_type};base64,{b64}"
                message_content.append({
                    "type": "image_url",
                    "image_url": {"url": data_url},
                })

        messages = [{"role": "user", "content": message_content}]

        # Build kwargs
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }

        # Handle structured output
        if json_schema is not None:
            if self.supports_json_schema:
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "response",
                        "strict": True,
                        "schema": json_schema,
                    },
                }
            else:
                # Fallback: instruct via prompt to return JSON
                json_instruction = (
                    "\n\nYou MUST respond with valid JSON matching this schema:\n"
                    f"{json_schema}\n"
                    "Return ONLY the JSON, no other text."
                )
                # Append instruction to the last text part
                for item in reversed(message_content):
                    if item["type"] == "text":
                        item["text"] += json_instruction
                        break
                kwargs["response_format"] = {"type": "json_object"}

        response = self.client.chat.completions.create(**kwargs)

        # Extract response
        choice = response.choices[0]
        text = choice.message.content or ""

        # Extract token counts
        prompt_tokens = None
        completion_tokens = None
        if response.usage:
            prompt_tokens = response.usage.prompt_tokens
            completion_tokens = response.usage.completion_tokens

        return LLMResponse(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )


class LLMProviderError(Exception):
    """Raised when provider creation or configuration fails."""

    pass


def create_provider(config: Any) -> LLMProvider:
    """Create an LLM provider from configuration.

    Uses LLM_PROVIDER to select the API key and LLM_MODEL to select
    the model from the registry. Falls back to Gemini with default model.

    Args:
        config: Config object with provider settings and API keys.

    Returns:
        Configured LLMProvider instance.

    Raises:
        LLMProviderError: If API key is missing or model is invalid.
    """
    provider_name = getattr(config, "llm_provider", "gemini")
    model_name = getattr(config, "llm_model", None)

    # Determine model
    if model_name is None:
        model_name = PROVIDER_DEFAULT_MODEL.get(provider_name)
    if model_name is None:
        raise LLMProviderError(
            f"No model specified and no default for provider '{provider_name}'"
        )

    # Validate model exists in registry
    registry_entry = MODEL_REGISTRY.get(model_name)
    if registry_entry is None:
        raise LLMProviderError(
            f"Unknown model '{model_name}'. "
            f"Available models: {', '.join(sorted(MODEL_REGISTRY.keys()))}"
        )

    # Get API key
    api_key_attr = PROVIDER_API_KEY_MAP.get(provider_name)
    if api_key_attr is None:
        raise LLMProviderError(f"Unknown provider '{provider_name}'")

    api_key = getattr(config, api_key_attr, None)
    if not api_key:
        env_var = api_key_attr.upper()
        raise LLMProviderError(
            f"API key not configured for provider '{provider_name}'. "
            f"Set {env_var} in your .env file."
        )

    # Create provider
    if provider_name == "gemini":
        return GeminiProvider(api_key=api_key, model=model_name)
    else:
        base_url = registry_entry.get("base_url")
        if not base_url:
            raise LLMProviderError(
                f"No base_url configured for model '{model_name}'"
            )
        return OpenAICompatibleProvider(
            api_key=api_key,
            model=model_name,
            base_url=base_url,
            provider_name=provider_name,
            supports_vision=registry_entry.get("vision", False),
            supports_json_schema=registry_entry.get("json_schema", True),
        )
