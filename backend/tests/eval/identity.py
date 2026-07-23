"""Content-addressed inference and score identities for immutable eval caching.

An identical (operation, model, thinking, settings, prompt/adapter contract,
fixture input + attachments) invocation always maps to the same inference_key
and is never purchased twice. Scoring is a separate deterministic identity so
editing expected output or the scorer rescores without calling a model.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from .eval_config import ATTACHMENTS_DIR, EVENT_PROCESSING_PATH

IDENTITY_VERSION = 1
SCORING_VERSION = 1
PROMPT_RENDERER_VERSION = 1

OperationName = Literal["extract", "compare", "merge"]

_source_hash_cache: dict[str, str] = {}
_source_hash_lock = threading.Lock()


def canonical_json(value: Any) -> str:
    """Stable JSON for hashing: sorted keys, compact separators, no whitespace."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def sha256_of_canonical(value: Any) -> str:
    return sha256_hex(canonical_json(value))


def hash_file_bytes(path: Path) -> str:
    return sha256_hex(path.read_bytes())


def hash_source_object(obj: Any, *, label: str | None = None) -> str:
    """Hash Python source for a function/class. Cached by label or qualname."""
    cache_key = label or f"{getattr(obj, '__module__', '')}.{getattr(obj, '__qualname__', repr(obj))}"
    with _source_hash_lock:
        cached = _source_hash_cache.get(cache_key)
        if cached is not None:
            return cached
    try:
        source = inspect.getsource(obj)
    except (OSError, TypeError):
        source = repr(obj)
    digest = sha256_hex(source)
    with _source_hash_lock:
        _source_hash_cache[cache_key] = digest
    return digest


def clear_source_hash_cache() -> None:
    with _source_hash_lock:
        _source_hash_cache.clear()


@dataclass(frozen=True)
class InferenceIdentity:
    identity_version: int
    operation: str
    provider: str
    model: str
    thinking: dict[str, Any]
    request_settings: dict[str, Any]
    prompt_contract_hash: str
    adapter_contract_hash: str
    fixture_input_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def inference_key(self) -> str:
        return sha256_of_canonical(self.to_dict())


@dataclass(frozen=True)
class ScoreIdentity:
    scoring_version: int
    inference_key: str
    expected_output_hash: str
    scorer_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def score_key(self) -> str:
        return sha256_of_canonical(self.to_dict())


def normalize_thinking(thinking: str | dict[str, Any] | None) -> dict[str, Any]:
    """Normalize CLI / config thinking into an explicit effective config dict."""
    if thinking is None:
        return {"mode": "level", "value": "low"}
    if isinstance(thinking, dict):
        return dict(sorted((k, thinking[k]) for k in thinking))
    return {"mode": "level", "value": str(thinking)}


def default_request_settings(
    *,
    provider: str,
    model: str,
    thinking: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Effective serialized request settings used in the inference identity.

    Secrets and absolute URLs with credentials are never included. WS4 will
    enrich this with adapter-specific wire settings; until then the identity
    records the knobs the eval runner actually controls.
    """
    settings: dict[str, Any] = {
        "api_surface": f"{provider}/chat-completions-or-native",
        "model": model,
        "thinking": thinking,
        "temperature": None,
        "top_p": None,
        "max_output_tokens": None,
        "response_format": "operation_schema",
        "timeout_s": None,
    }
    if extra:
        settings.update(extra)
    return dict(sorted(settings.items()))


def fixture_input_payload(fixture: dict[str, Any]) -> dict[str, Any]:
    """Input-only fixture content (excludes handwritten expected output)."""
    return {
        "input": fixture.get("input", {}),
        "category": fixture.get("category"),
        "difficulty": fixture.get("difficulty"),
        "tags": fixture.get("tags", []),
        "description": fixture.get("description", ""),
    }


def compute_fixture_input_hash(
    fixture: dict[str, Any],
    *,
    attachments_dir: Path | None = None,
) -> str:
    """Hash fixture inputs plus referenced attachment bytes in stable order."""
    attachments_dir = attachments_dir or ATTACHMENTS_DIR
    input_data = fixture.get("input", {})
    attachment_refs = input_data.get("attachments", []) or []

    attachment_parts: list[dict[str, Any]] = []
    for ref in attachment_refs:
        if not isinstance(ref, str):
            attachment_parts.append({"name": canonical_json(ref), "bytes_sha256": None})
            continue
        path = attachments_dir / ref
        if path.exists():
            attachment_parts.append(
                {"name": ref, "bytes_sha256": hash_file_bytes(path)}
            )
        else:
            attachment_parts.append({"name": ref, "bytes_sha256": None, "missing": True})

    payload = {
        "fixture_input": fixture_input_payload(fixture),
        "attachments": attachment_parts,
    }
    return sha256_of_canonical(payload)


def compute_expected_output_hash(fixture: dict[str, Any]) -> str:
    return sha256_of_canonical(fixture.get("expected", {}))


def _schema_hash(cls: type) -> str:
    parts = [
        inspect.getsource(cls),
        canonical_json(cls.model_json_schema()),
    ]
    return sha256_hex("\n".join(parts))


def compute_prompt_contract_hash(operation: OperationName | str) -> str:
    """Operation-specific prompt/schema contract. Does not mix extract/compare/merge."""
    try:
        from selko.api.schemas.calendar import CalendarEvent, EventExtractionResponse
        from selko.services import event_processing
    except Exception:
        # Fall back to hashing the production file so tests still get a stable value
        # when imports fail in constrained environments.
        if EVENT_PROCESSING_PATH.resolve().exists():
            return hash_file_bytes(EVENT_PROCESSING_PATH.resolve())[:64]
        return "unknown"

    parts: list[str] = [f"renderer:{PROMPT_RENDERER_VERSION}", f"operation:{operation}"]

    if operation == "extract":
        parts.append(inspect.getsource(event_processing._build_prompt))
        parts.append(inspect.getsource(event_processing.extract_calendar_events))
        parts.append(_schema_hash(CalendarEvent))
        parts.append(_schema_hash(EventExtractionResponse))
    elif operation == "compare":
        parts.append(inspect.getsource(event_processing.compare_events))
        # Compare uses an inline JSON schema inside the function source above.
    elif operation == "merge":
        parts.append(inspect.getsource(event_processing.merge_event_data))
    else:
        raise ValueError(f"Unknown operation for prompt contract: {operation}")

    return sha256_hex("\n".join(parts))


def compute_adapter_contract_hash(provider: str) -> str:
    """Hash provider request/response adapter code relevant to wire serialization."""
    try:
        from selko.services import llm_gateway, llm_provider
    except Exception:
        return "unknown"

    parts = [
        f"provider:{provider}",
        hash_source_object(llm_provider.create_provider, label="create_provider"),
        hash_source_object(llm_gateway.LLMGateway.call, label="LLMGateway.call"),
        hash_source_object(llm_provider.LLMProvider, label="LLMProvider.abc"),
    ]

    # Include concrete provider class source when known.
    provider_classes = {
        "gemini": getattr(llm_provider, "GeminiProvider", None),
        "openai": getattr(llm_provider, "OpenAIProvider", None),
        "anthropic": getattr(llm_provider, "AnthropicProvider", None),
        "qwen": getattr(llm_provider, "OpenAICompatibleProvider", None),
        "moonshot": getattr(llm_provider, "OpenAICompatibleProvider", None),
        "zai": getattr(llm_provider, "OpenAICompatibleProvider", None),
        "deepseek": getattr(llm_provider, "OpenAICompatibleProvider", None),
        "minimax": getattr(llm_provider, "OpenAICompatibleProvider", None),
    }
    cls = provider_classes.get(provider)
    if cls is not None:
        parts.append(hash_source_object(cls, label=f"provider_class:{cls.__name__}"))

    # Structured-output / media helpers that affect the request body.
    for name in (
        "sanitize_schema_for_gemini",
        "sanitize_schema_for_openai",
        "_convert_heic_if_needed",
        "guess_mime_type",
    ):
        obj = getattr(llm_provider, name, None) or getattr(llm_gateway, name, None)
        if obj is not None:
            parts.append(hash_source_object(obj, label=f"helper:{name}"))

    return sha256_hex("\n".join(parts))


def compute_scorer_hash(operation: OperationName | str) -> str:
    """Hash deterministic scoring functions for the given operation."""
    from . import run_eval

    if operation == "extract":
        objs = [run_eval.auto_score_result, run_eval.auto_score_event]
    elif operation == "compare":
        objs = [run_eval.score_compare_result]
    elif operation == "merge":
        objs = [run_eval.score_merge_result]
    else:
        raise ValueError(f"Unknown operation for scorer hash: {operation}")

    parts = [f"scoring_version:{SCORING_VERSION}", f"operation:{operation}"]
    for obj in objs:
        parts.append(inspect.getsource(obj))
    # Thresholds affect scoring without changing function source.
    from . import eval_config

    if operation == "extract":
        parts.append(canonical_json(eval_config.AUTO_SCORE_THRESHOLDS))
    elif operation == "merge":
        parts.append(canonical_json(eval_config.MERGE_SCORE_THRESHOLDS))
    return sha256_hex("\n".join(parts))


def build_inference_identity(
    *,
    operation: OperationName | str,
    provider: str,
    model: str,
    thinking: str | dict[str, Any] | None,
    fixture: dict[str, Any],
    request_settings_extra: dict[str, Any] | None = None,
    attachments_dir: Path | None = None,
) -> InferenceIdentity:
    thinking_cfg = normalize_thinking(thinking)
    settings = default_request_settings(
        provider=provider,
        model=model,
        thinking=thinking_cfg,
        extra=request_settings_extra,
    )
    return InferenceIdentity(
        identity_version=IDENTITY_VERSION,
        operation=operation,
        provider=provider,
        model=model,
        thinking=thinking_cfg,
        request_settings=settings,
        prompt_contract_hash=compute_prompt_contract_hash(operation),
        adapter_contract_hash=compute_adapter_contract_hash(provider),
        fixture_input_hash=compute_fixture_input_hash(
            fixture, attachments_dir=attachments_dir
        ),
    )


def build_score_identity(
    *,
    operation: OperationName | str,
    inference_key: str,
    fixture: dict[str, Any],
) -> ScoreIdentity:
    return ScoreIdentity(
        scoring_version=SCORING_VERSION,
        inference_key=inference_key,
        expected_output_hash=compute_expected_output_hash(fixture),
        scorer_hash=compute_scorer_hash(operation),
    )


def code_provenance() -> dict[str, Any]:
    """Git commit + working-tree hashes for reports; not part of inference identity."""
    import subprocess

    commit = "unknown"
    try:
        commit = (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        )
    except Exception:
        pass

    event_processing_hash = "unknown"
    resolved = EVENT_PROCESSING_PATH.resolve()
    if resolved.exists():
        event_processing_hash = hash_file_bytes(resolved)

    return {
        "git_commit": commit,
        "event_processing_sha256": event_processing_hash,
    }
