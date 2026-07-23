"""LLM Provider abstraction for multi-backend support.

Provides a unified interface for multiple LLM providers:
- Google Gemini (native SDK)
- Anthropic Claude (native SDK)
- OpenAI, xAI, Z.AI/Zhipu, Alibaba/Qwen (OpenAI-compatible)
- Optional keys retained for Moonshot/DeepSeek/MiniMax (models deferred until IDs verified)

All providers implement the same LLMProvider interface, allowing transparent
switching between providers via environment variables.
"""

import base64
import io
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Optional

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
    finish_reason: Optional[str] = None


@dataclass(frozen=True)
class Pricing:
    """Per-1M-token USD pricing. Prefer None over zero when unknown."""

    input: float
    output: float
    estimated: bool = False


@dataclass(frozen=True)
class ThinkingConfig:
    """Explicit provider thinking/reasoning capability."""

    mode: Literal["effort", "level", "toggle", "budget", "provider_default"]
    value: str | int | bool


@dataclass(frozen=True)
class ModelSpec:
    """Curated model capability + pricing entry."""

    provider: str
    model: str
    vision: bool
    structured_output: Literal["json_schema", "json_object", "prompt_json"]
    preferred_thinking: ThinkingConfig
    supported_thinking: tuple[ThinkingConfig, ...]
    request_api: str
    pricing: Pricing | None
    pricing_as_of: date | None
    base_url: str | None = None


_QWEN_BASE = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
_OPENAI_BASE = "https://api.openai.com/v1"
_ZAI_BASE = "https://api.z.ai/api/paas/v4/"
_XAI_BASE = "https://api.x.ai/v1"

_EFFORT_NONE = ThinkingConfig("effort", "none")
_EFFORT_LOW = ThinkingConfig("effort", "low")
_EFFORT_MEDIUM = ThinkingConfig("effort", "medium")
_LEVEL_MINIMAL = ThinkingConfig("level", "minimal")
_LEVEL_LOW = ThinkingConfig("level", "low")
_LEVEL_MEDIUM = ThinkingConfig("level", "medium")
_BUDGET_LOW = ThinkingConfig("budget", 2048)
_BUDGET_OFF = ThinkingConfig("toggle", False)
_TOGGLE_ON = ThinkingConfig("toggle", True)
_TOGGLE_OFF = ThinkingConfig("toggle", False)
_ADAPTIVE_LOW = ThinkingConfig("effort", "low")

# Curated current candidates only (WS4). Unverified family IDs (Kimi K3,
# MiniMax M3, DeepSeek V4, Meta Spark, Inkling) are omitted until authenticated.
MODEL_SPECS: dict[str, ModelSpec] = {
    "gemini-3.5-flash-lite": ModelSpec(
        provider="gemini",
        model="gemini-3.5-flash-lite",
        vision=True,
        structured_output="json_schema",
        preferred_thinking=_LEVEL_MINIMAL,
        supported_thinking=(_LEVEL_MINIMAL, _LEVEL_LOW, _LEVEL_MEDIUM),
        request_api="gemini_native",
        pricing=Pricing(0.30, 2.50),
        pricing_as_of=date(2026, 7, 22),
    ),
    "gemini-3.6-flash": ModelSpec(
        provider="gemini",
        model="gemini-3.6-flash",
        vision=True,
        structured_output="json_schema",
        preferred_thinking=_LEVEL_MINIMAL,
        supported_thinking=(_LEVEL_MINIMAL, _LEVEL_LOW, _LEVEL_MEDIUM),
        request_api="gemini_native",
        pricing=Pricing(1.50, 7.50),
        pricing_as_of=date(2026, 7, 22),
    ),
    "gpt-5.6-luna": ModelSpec(
        provider="openai",
        model="gpt-5.6-luna",
        vision=True,
        structured_output="json_schema",
        preferred_thinking=_EFFORT_LOW,
        supported_thinking=(_EFFORT_NONE, _EFFORT_LOW, _EFFORT_MEDIUM),
        request_api="openai_compatible",
        pricing=Pricing(5.00, 30.00, estimated=True),
        pricing_as_of=date(2026, 7, 22),
        base_url=_OPENAI_BASE,
    ),
    "gpt-5.6-terra": ModelSpec(
        provider="openai",
        model="gpt-5.6-terra",
        vision=True,
        structured_output="json_schema",
        preferred_thinking=_EFFORT_LOW,
        supported_thinking=(_EFFORT_NONE, _EFFORT_LOW, _EFFORT_MEDIUM),
        request_api="openai_compatible",
        pricing=Pricing(5.00, 30.00, estimated=True),
        pricing_as_of=date(2026, 7, 22),
        base_url=_OPENAI_BASE,
    ),
    "qwen3.6-flash": ModelSpec(
        provider="qwen",
        model="qwen3.6-flash",
        vision=True,
        # DashScope docs list structured output; keep prompt_json until verified
        # under thinking+json_schema together.
        structured_output="prompt_json",
        preferred_thinking=_BUDGET_LOW,
        supported_thinking=(_BUDGET_OFF, _BUDGET_LOW),
        request_api="openai_compatible",
        pricing=Pricing(0.10, 0.40, estimated=True),
        pricing_as_of=date(2026, 7, 22),
        base_url=_QWEN_BASE,
    ),
    "qwen3.7-plus": ModelSpec(
        provider="qwen",
        model="qwen3.7-plus",
        vision=True,
        structured_output="prompt_json",
        preferred_thinking=_BUDGET_LOW,
        supported_thinking=(_BUDGET_OFF, _BUDGET_LOW),
        request_api="openai_compatible",
        pricing=Pricing(0.40, 1.60),
        pricing_as_of=date(2026, 7, 22),
        base_url=_QWEN_BASE,
    ),
    "glm-5.2": ModelSpec(
        provider="zai",
        model="glm-5.2",
        vision=True,
        structured_output="json_object",
        preferred_thinking=_TOGGLE_ON,
        supported_thinking=(_TOGGLE_OFF, _TOGGLE_ON),
        request_api="openai_compatible",
        pricing=Pricing(1.40, 4.40, estimated=True),
        pricing_as_of=date(2026, 7, 22),
        base_url=_ZAI_BASE,
    ),
    "grok-4.5": ModelSpec(
        provider="xai",
        model="grok-4.5",
        vision=True,
        structured_output="json_schema",
        preferred_thinking=_EFFORT_LOW,
        supported_thinking=(_EFFORT_LOW, _EFFORT_MEDIUM),
        request_api="openai_compatible",
        pricing=Pricing(2.00, 6.00),
        pricing_as_of=date(2026, 7, 22),
        base_url=_XAI_BASE,
    ),
    "claude-sonnet-5": ModelSpec(
        provider="anthropic",
        model="claude-sonnet-5",
        vision=True,
        structured_output="prompt_json",
        preferred_thinking=_ADAPTIVE_LOW,
        supported_thinking=(_EFFORT_NONE, _ADAPTIVE_LOW, _EFFORT_MEDIUM),
        request_api="anthropic_native",
        pricing=Pricing(2.00, 10.00),
        pricing_as_of=date(2026, 7, 22),
    ),
}


def _spec_to_registry_entry(spec: ModelSpec) -> dict[str, Any]:
    """Dict view used by estimate_cost / create_provider / legacy callers."""
    entry: dict[str, Any] = {
        "provider": spec.provider,
        "vision": spec.vision,
        "json_schema": spec.structured_output == "json_schema",
        "structured_output": spec.structured_output,
        "preferred_thinking": spec.preferred_thinking,
        "supported_thinking": spec.supported_thinking,
        "request_api": spec.request_api,
        "pricing_as_of": (
            spec.pricing_as_of.isoformat() if spec.pricing_as_of else None
        ),
    }
    if spec.pricing is not None:
        entry["pricing"] = {"input": spec.pricing.input, "output": spec.pricing.output}
        if spec.pricing.estimated:
            entry["pricing_estimated"] = True
    else:
        entry["pricing"] = None
    if spec.base_url:
        entry["base_url"] = spec.base_url
    if spec.preferred_thinking.mode == "effort" and spec.provider in ("openai", "xai"):
        entry["reasoning"] = True
    if spec.preferred_thinking.mode in ("budget", "toggle") and spec.provider == "qwen":
        entry["qwen_thinking"] = True
    if spec.provider == "anthropic":
        entry["adaptive_thinking"] = True
    return entry


# Pricing / capability lookup dict (kept for estimate_cost and older callers)
MODEL_REGISTRY: dict[str, dict[str, Any]] = {
    name: _spec_to_registry_entry(spec) for name, spec in MODEL_SPECS.items()
}

# Map provider name → Config attribute name for API key
PROVIDER_API_KEY_MAP = {
    "gemini": "gemini_api_key",
    "moonshot": "moonshot_api_key",
    "zai": "zai_api_key",
    "qwen": "alibaba_api_key",
    "deepseek": "deepseek_api_key",
    "minimax": "minimax_api_key",
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
    "xai": "xai_api_key",
}

# Default model per provider with a curated registry entry
PROVIDER_DEFAULT_MODEL = {
    "gemini": "gemini-3.5-flash-lite",
    "zai": "glm-5.2",
    "qwen": "qwen3.6-flash",
    "openai": "gpt-5.6-luna",
    "anthropic": "claude-sonnet-5",
    "xai": "grok-4.5",
}


def _resize_image_if_needed(
    data: bytes, mime_type: str, max_dimension: int = 2048
) -> Optional[bytes]:
    """Resize image if either dimension exceeds max_dimension.

    Filters out degenerate images (tracking pixels, spacers) that are
    too small for LLM providers to process.

    Args:
        data: Raw image bytes.
        mime_type: MIME type of the image.
        max_dimension: Maximum allowed dimension in pixels.

    Returns:
        Original or resized image bytes, or None for degenerate images.
    """
    if not mime_type.startswith("image/"):
        return data

    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        w, h = img.size

        # Skip degenerate images (tracking pixels, spacers)
        MIN_DIMENSION = 10
        if w < MIN_DIMENSION or h < MIN_DIMENSION:
            logger.debug(f"Skipping degenerate image ({w}x{h})")
            return None

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


_MARKDOWN_JSON_RE = re.compile(
    r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL
)

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_THINK_OPEN_RE = re.compile(r"</think>")


def _strip_markdown_json(text: str) -> str:
    """Strip markdown code-block wrapping and think blocks from JSON responses.

    Handles:
    - Markdown code blocks: ```json ... ```
    - Think blocks: <think>...</think> and stray </think> tags
    - Extra text before/after the JSON object

    Falls back to finding the last top-level {...} JSON object when
    the response contains multiple JSON objects or surrounding text.
    """
    # First try the simple markdown match
    m = _MARKDOWN_JSON_RE.match(text)
    if m:
        return m.group(1).strip()

    # Strip think blocks (some models like ZAI produce these)
    cleaned = _THINK_BLOCK_RE.sub("", text)
    cleaned = _THINK_OPEN_RE.sub("", cleaned)
    cleaned = cleaned.strip()

    # Try to parse as-is first — if it works, no extraction needed
    if cleaned.startswith("{") and cleaned.endswith("}"):
        import json

        try:
            json.loads(cleaned)
            return cleaned
        except json.JSONDecodeError:
            pass

    # Find the last top-level JSON object (skip echoed schemas, extra text, etc.)
    brace_depth = 0
    end_pos = None
    start_pos = None
    for i in range(len(cleaned) - 1, -1, -1):
        ch = cleaned[i]
        if ch == "}":
            if brace_depth == 0:
                end_pos = i
            brace_depth += 1
        elif ch == "{":
            brace_depth -= 1
            if brace_depth == 0 and end_pos is not None:
                start_pos = i
                break

    if start_pos is not None and end_pos is not None:
        return cleaned[start_pos : end_pos + 1]

    return text


# Public alias for validators / callers outside this module.
strip_markdown_json = _strip_markdown_json


def _sanitize_schema_for_strict(schema: dict) -> dict:
    """Sanitize a Pydantic-generated JSON schema for strict-mode OpenAI-compatible APIs.

    Strict mode (used by Moonshot, Z.AI, etc.) requires:
    - No $ref/$defs — all definitions must be inlined
    - No 'default' alongside 'anyOf' (Moonshot rejects this combination)
    - No 'title' on nested properties
    - All objects must have 'additionalProperties': false
    - All properties must be listed in 'required'
    """
    import copy

    schema = copy.deepcopy(schema)
    defs = schema.pop("$defs", {})

    # Track recursion to avoid infinite loops with circular $ref
    _resolving: set[str] = set()

    def _resolve(node: Any) -> Any:
        if isinstance(node, dict):
            # Resolve $ref
            if "$ref" in node:
                ref_path = node["$ref"]  # e.g. "#/$defs/CalendarEvent"
                ref_name = ref_path.split("/")[-1]
                if ref_name in defs and ref_name not in _resolving:
                    _resolving.add(ref_name)
                    resolved = _resolve(copy.deepcopy(defs[ref_name]))
                    _resolving.discard(ref_name)
                    return resolved
                # Unresolvable ref — strip it and return empty object
                return {"type": "object"}

            resolved = {}
            for key, value in node.items():
                resolved[key] = _resolve(value)

            # Remove 'default' when 'anyOf' is present (strict mode incompatibility)
            if "anyOf" in resolved and "default" in resolved:
                del resolved["default"]

            # Strip 'format' from anyOf items (Moonshot rejects format inside anyOf)
            if "anyOf" in resolved and isinstance(resolved["anyOf"], list):
                for item in resolved["anyOf"]:
                    if isinstance(item, dict):
                        item.pop("format", None)

            # Remove 'title' from property-level nodes (not root)
            if "title" in resolved and "type" in resolved:
                del resolved["title"]
            if "title" in resolved and "anyOf" in resolved:
                del resolved["title"]

            # Ensure objects have additionalProperties: false and all props in required
            if resolved.get("type") == "object" and "properties" in resolved:
                resolved["additionalProperties"] = False
                resolved["required"] = list(resolved["properties"].keys())

            # Handle items in arrays
            if resolved.get("type") == "array" and "items" in resolved:
                resolved["items"] = _resolve(resolved["items"])
                # Remove title from array-level too
                if "title" in resolved:
                    del resolved["title"]

            return resolved
        elif isinstance(node, list):
            return [_resolve(item) for item in node]
        return node

    result = _resolve(schema)

    # Final validation: assert no $ref or $defs remain in the output
    def _assert_no_refs(node: Any, path: str = "") -> None:
        if isinstance(node, dict):
            if "$ref" in node:
                logger.warning(f"Unresolved $ref at {path}: {node['$ref']}")
            if "$defs" in node:
                logger.warning(f"Remaining $defs at {path}")
            for key, value in node.items():
                _assert_no_refs(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                _assert_no_refs(item, f"{path}[{i}]")

    _assert_no_refs(result)

    return result


def _sanitize_schema_for_gemini(schema: dict) -> dict:
    """Sanitize a JSON schema for Gemini SDK compatibility.

    The Gemini SDK's Schema class doesn't accept anyOf patterns.
    Converts anyOf: [{"type": "string"}, {"type": "null"}] to
    {"type": "string", "nullable": true} which Gemini accepts.

    Also resolves $ref/$defs and removes unsupported keywords.
    """
    import copy

    schema = copy.deepcopy(schema)
    defs = schema.pop("$defs", {})

    _resolving: set[str] = set()

    def _resolve(node: Any) -> Any:
        if isinstance(node, dict):
            # Resolve $ref
            if "$ref" in node:
                ref_path = node["$ref"]
                ref_name = ref_path.split("/")[-1]
                if ref_name in defs and ref_name not in _resolving:
                    _resolving.add(ref_name)
                    resolved = _resolve(copy.deepcopy(defs[ref_name]))
                    _resolving.discard(ref_name)
                    return resolved
                return {"type": "STRING"}

            # Don't recurse into "properties" or "items" generically —
            # they're handled specially below.  Processing the properties
            # container through _resolve would confuse property *names*
            # (e.g. "title", "description") with schema *keywords*.
            resolved = {}
            for key, value in node.items():
                if key in ("properties", "items"):
                    resolved[key] = value  # handled below
                else:
                    resolved[key] = _resolve(value)

            # Convert anyOf with null to nullable
            if "anyOf" in resolved:
                any_of = resolved["anyOf"]
                non_null = [s for s in any_of if s.get("type") != "null"]
                has_null = any(s.get("type") == "null" for s in any_of)
                if has_null and len(non_null) == 1:
                    # Replace anyOf with the non-null type + nullable
                    merged = dict(non_null[0])
                    merged["nullable"] = True
                    # Preserve other keys from resolved (except anyOf)
                    del resolved["anyOf"]
                    resolved.update(merged)
                elif len(non_null) == 1 and not has_null:
                    # Single non-null anyOf — just unwrap
                    del resolved["anyOf"]
                    resolved.update(non_null[0])

            # Remove unsupported Gemini keywords (safe here because
            # _resolve only processes actual schema nodes, never the
            # properties container dict directly).
            for key in ("title", "default", "$defs", "additionalProperties"):
                resolved.pop(key, None)

            # Recurse into properties values individually
            if "properties" in resolved:
                resolved["properties"] = {
                    k: _resolve(v) for k, v in resolved["properties"].items()
                }

            # Recurse into array items
            if "items" in resolved:
                resolved["items"] = _resolve(resolved["items"])

            return resolved
        elif isinstance(node, list):
            return [_resolve(item) for item in node]
        return node

    return _resolve(schema)


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

    def __init__(self, api_key: str, model: str, thinking: str = "low"):
        from google import genai

        self.provider_name = "gemini"
        self.model = model
        self.supports_vision = True
        self.supports_json_schema = True
        self.thinking = thinking
        self.client = genai.Client(api_key=api_key)
        self._last_sanitized_schema: Optional[dict] = None
        logger.debug(f"Initialized Gemini provider with model {model}, thinking={thinking}")

    def generate(
        self,
        contents: list[ContentPart],
        json_schema: Optional[dict] = None,
    ) -> LLMResponse:
        from google.genai import types

        from selko.services.format_conversion import (
            PROVIDER_ACCEPTED_FORMATS,
            prepare_content_for_provider,
        )

        # Convert ContentPart list to Gemini format
        gemini_parts: list[Any] = []
        for part in contents:
            if isinstance(part, str):
                gemini_parts.append(part)
            elif isinstance(part, ImageContent):
                # Run through format conversion gate
                converted_list = prepare_content_for_provider(
                    part.data, part.mime_type, self.provider_name,
                )
                for converted in converted_list:
                    resized = _resize_image_if_needed(
                        converted.data, converted.mime_type
                    )
                    if resized is None:
                        continue
                    gemini_parts.append({
                        "inline_data": {
                            "mime_type": converted.mime_type,
                            "data": base64.b64encode(resized).decode("utf-8"),
                        }
                    })

        # Build generation config
        config_kwargs: dict[str, Any] = {}
        if json_schema is not None:
            config_kwargs["response_mime_type"] = "application/json"
            sanitized = _sanitize_schema_for_gemini(json_schema)
            self._last_sanitized_schema = sanitized
            config_kwargs["response_schema"] = sanitized
        # Gemini 3.x cannot fully disable thinking; omit ≠ none. Map none→minimal
        # and always send an explicit thinking_level.
        thinking_level = (
            "minimal" if self.thinking in (None, "", "none") else self.thinking
        )
        config_kwargs["thinking_config"] = types.ThinkingConfig(
            thinking_level=thinking_level
        )
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

        # Extract finish reason
        finish_reason = None
        if hasattr(response, "candidates") and response.candidates:
            fr = getattr(response.candidates[0], "finish_reason", None)
            if fr is not None:
                finish_reason = str(fr)

        return LLMResponse(
            text=response.text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason=finish_reason,
        )


class OpenAICompatibleProvider(LLMProvider):
    """Provider for OpenAI-compatible APIs (Moonshot, Z.AI, Qwen, DeepSeek, MiniMax, OpenAI)."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        provider_name: str,
        supports_vision: bool = False,
        supports_json_schema: bool = True,
        reasoning_model: bool = False,
        qwen_thinking: bool = False,
        thinking: str = "low",
    ):
        from openai import OpenAI

        self.provider_name = provider_name
        self.model = model
        self.supports_vision = supports_vision
        self.supports_json_schema = supports_json_schema
        self.reasoning_model = reasoning_model
        self.qwen_thinking = qwen_thinking
        self.thinking = thinking
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self._last_sanitized_schema: Optional[dict] = None
        logger.debug(
            f"Initialized {provider_name} provider with model {model} "
            f"at {base_url}, thinking={thinking}"
        )

    def generate(
        self,
        contents: list[ContentPart],
        json_schema: Optional[dict] = None,
    ) -> LLMResponse:
        from selko.services.format_conversion import prepare_content_for_provider

        # Build message content parts
        message_content: list[dict[str, Any]] = []
        for part in contents:
            if isinstance(part, str):
                message_content.append({"type": "text", "text": part})
            elif isinstance(part, ImageContent):
                # Run through format conversion gate
                converted_list = prepare_content_for_provider(
                    part.data, part.mime_type, self.provider_name,
                )
                for converted in converted_list:
                    resized = _resize_image_if_needed(
                        converted.data, converted.mime_type
                    )
                    if resized is None:
                        continue
                    b64 = base64.b64encode(resized).decode("utf-8")
                    data_url = f"data:{converted.mime_type};base64,{b64}"
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

        # OpenAI/xAI reasoning: always send reasoning_effort explicitly.
        # Omitting defaults to medium on GPT-5.6 — never treat omit as "none"/"low".
        if self.reasoning_model:
            kwargs["reasoning_effort"] = self.thinking or "low"

        # Qwen thinking mode (enable_thinking + thinking_budget via extra_body)
        if self.qwen_thinking:
            if self.thinking != "none":
                thinking_budgets = {"low": 2048, "medium": 8192, "minimal": 1024}
                budget = (
                    self.thinking
                    if isinstance(self.thinking, int)
                    else thinking_budgets.get(self.thinking, 2048)
                )
                kwargs["extra_body"] = {
                    "enable_thinking": True,
                    "thinking_budget": budget,
                }
            else:
                kwargs["extra_body"] = {"enable_thinking": False}

        # Handle structured output
        if json_schema is not None:
            if self.supports_json_schema:
                sanitized = _sanitize_schema_for_strict(json_schema)
                self._last_sanitized_schema = sanitized
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "response",
                        "strict": True,
                        "schema": sanitized,
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
        text = _strip_markdown_json(text)

        # Extract token counts
        prompt_tokens = None
        completion_tokens = None
        if response.usage:
            prompt_tokens = response.usage.prompt_tokens
            completion_tokens = response.usage.completion_tokens

        # Extract finish reason
        finish_reason = getattr(choice, "finish_reason", None)

        return LLMResponse(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason=finish_reason,
        )


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider using native anthropic SDK."""

    def __init__(
        self, api_key: str, model: str, thinking: str = "low",
        adaptive_thinking: bool = False,
    ):
        import anthropic

        self.provider_name = "anthropic"
        self.model = model
        self.supports_vision = True
        self.supports_json_schema = False
        self.thinking = thinking
        self.adaptive_thinking = adaptive_thinking
        self.client = anthropic.Anthropic(api_key=api_key)
        self._last_sanitized_schema: Optional[dict] = None
        logger.debug(f"Initialized Anthropic provider with model {model}")

    def generate(
        self,
        contents: list[ContentPart],
        json_schema: Optional[dict] = None,
    ) -> LLMResponse:
        from selko.services.format_conversion import prepare_content_for_provider

        # Build message content parts
        message_content: list[dict[str, Any]] = []
        for part in contents:
            if isinstance(part, str):
                message_content.append({"type": "text", "text": part})
            elif isinstance(part, ImageContent):
                converted_list = prepare_content_for_provider(
                    part.data, part.mime_type, self.provider_name,
                )
                for converted in converted_list:
                    if converted.mime_type == "application/pdf":
                        # Anthropic uses "document" type for PDFs
                        b64 = base64.b64encode(converted.data).decode("utf-8")
                        message_content.append({
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": b64,
                            },
                        })
                    else:
                        resized = _resize_image_if_needed(
                            converted.data, converted.mime_type
                        )
                        if resized is None:
                            continue
                        b64 = base64.b64encode(resized).decode("utf-8")
                        message_content.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": converted.mime_type,
                                "data": b64,
                            },
                        })

        # Handle JSON schema via prompt instruction (no native schema mode)
        if json_schema is not None:
            self._last_sanitized_schema = json_schema  # No sanitization for Anthropic
            json_instruction = (
                "\n\nYou MUST respond with valid JSON matching this schema:\n"
                f"{json_schema}\n"
                "Return ONLY the JSON, no other text."
            )
            for item in reversed(message_content):
                if item["type"] == "text":
                    item["text"] += json_instruction
                    break

        # Build API kwargs
        api_kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": message_content}],
        }

        # Adaptive thinking for Sonnet 4.6+ (thinking=none skips entirely)
        if self.adaptive_thinking and self.thinking != "none":
            api_kwargs["thinking"] = {"type": "adaptive"}
            api_kwargs["output_config"] = {"effort": self.thinking}
            # Adaptive thinking needs higher max_tokens to include thinking tokens
            api_kwargs["max_tokens"] = 16000

        response = self.client.messages.create(**api_kwargs)

        # Extract response text (strip markdown code blocks if present)
        text = ""
        for block in response.content:
            if block.type == "text":
                text += block.text
        text = _strip_markdown_json(text)

        # Extract token counts
        prompt_tokens = None
        completion_tokens = None
        if response.usage:
            prompt_tokens = response.usage.input_tokens
            completion_tokens = response.usage.output_tokens

        # Extract finish reason
        finish_reason = getattr(response, "stop_reason", None)

        return LLMResponse(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason=finish_reason,
        )


class LLMProviderError(Exception):
    """Raised when provider creation or configuration fails."""

    pass


def create_provider(
    config: Any,
    thinking: str = "low",
    *,
    provider_name: Optional[str] = None,
    model_name: Optional[str] = None,
) -> LLMProvider:
    """Create an LLM provider from configuration.

    Uses LLM_PROVIDER to select the API key and LLM_MODEL to select
    the model from the registry. Falls back to Qwen with default model.

    Args:
        config: Config object with provider settings and API keys.
        thinking: Thinking/reasoning level ("none", "low", "medium").
            Gemini maps to thinking_level, OpenAI GPT-5 maps to reasoning_effort.
            Providers without thinking support ignore this parameter.
        provider_name: Optional override (e.g. fallback route provider).
        model_name: Optional override (e.g. fallback route model).

    Returns:
        Configured LLMProvider instance.

    Raises:
        LLMProviderError: If API key is missing or model is invalid.
    """
    if provider_name is None:
        provider_name = getattr(config, "llm_provider", "qwen")
    if model_name is None:
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
        return GeminiProvider(api_key=api_key, model=model_name, thinking=thinking)
    elif provider_name == "anthropic":
        return AnthropicProvider(
            api_key=api_key, model=model_name, thinking=thinking,
            adaptive_thinking=registry_entry.get("adaptive_thinking", False),
        )
    else:
        # OpenAI-compatible (openai, xai, zai, qwen, and deferred providers)
        base_url = registry_entry.get("base_url")
        if not base_url:
            raise LLMProviderError(
                f"No base_url configured for model '{model_name}'"
            )
        supports_json_schema = registry_entry.get("json_schema", True)
        if registry_entry.get("structured_output") == "json_object":
            supports_json_schema = False
        return OpenAICompatibleProvider(
            api_key=api_key,
            model=model_name,
            base_url=base_url,
            provider_name=provider_name,
            supports_vision=registry_entry.get("vision", False),
            supports_json_schema=supports_json_schema,
            reasoning_model=registry_entry.get("reasoning", False),
            qwen_thinking=registry_entry.get("qwen_thinking", False),
            thinking=thinking,
        )
