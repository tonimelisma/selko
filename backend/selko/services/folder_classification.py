"""Shared classification contract for user-created mail folders and labels."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from selko.services.llm_gateway import LLMGateway
from selko.services.llm_logging import LLMOperationType

logger = logging.getLogger(__name__)


class FolderClassification(BaseModel):
    """The persisted, provider-independent folder recommendation."""

    decision: str = Field(description="include, exclude, or uncertain")
    reason: str = Field(description="A short user-facing explanation")


CLASSIFICATION_PROMPT = """You classify a user's email folder or label for an assistant that finds calendar events.

Classify only from the provider, folder name, and full parent path below. Never ask for
or infer anything from message subjects, senders, bodies, attachments, or message counts.

Use a narrow exclusion threshold. Return exclude only when the folder is clearly dedicated
to marketing, promotions, advertising, commercial offers, sales, coupons, or equivalent
unwanted bulk mail. Include personal, work, school, community, transactional, financial,
travel, receipts, alerts, general-purpose, and ambiguous folders. In particular, include
"Newsletters" by default because newsletters can contain relevant community or school events.
Use uncertain when the purpose is unclear; the application treats uncertain as included.

Return JSON with exactly:
{{"decision":"include|exclude|uncertain","reason":"short user-facing reason"}}

Provider: {provider}
Folder name: {name}
Full parent path: {full_path}
"""


def _normalize_decision(value: Any) -> str:
    decision = str(value or "uncertain").strip().lower()
    if decision not in {"include", "exclude", "uncertain"}:
        return "uncertain"
    return decision


def classify_email_folder(
    gateway: LLMGateway,
    *,
    user_id: str,
    provider: str,
    name: str,
    full_path: str,
) -> FolderClassification:
    """Classify a folder without exposing any message content to the model."""

    prompt = CLASSIFICATION_PROMPT.format(
        provider=provider,
        name=name,
        full_path=full_path,
    )
    try:
        response = gateway.for_user(user_id).call(
            operation=LLMOperationType.CLASSIFY_EMAIL_FOLDER,
            contents=[prompt],
            json_schema=FolderClassification.model_json_schema(),
            max_retries=2,
        )
        parsed = json.loads(response.text, strict=False)
        classification = FolderClassification.model_validate(parsed)
        classification.decision = _normalize_decision(classification.decision)
        classification.reason = (classification.reason or "").strip()[:240]
        if not classification.reason:
            classification.reason = "Folder purpose is unclear, so it is included by default."
        return classification
    except Exception as exc:
        # A classifier outage must never silently remove mail from the source set.
        logger.warning(
            "Folder classification failed for %s/%s (%s): %s",
            provider,
            full_path,
            name,
            exc,
        )
        return FolderClassification(
            decision="uncertain",
            reason="Folder classification was inconclusive, so it is included by default.",
        )


def effective_inclusion(decision: str, user_override: bool, is_included: bool | None = None) -> bool:
    """Return the effective source-set decision.

    User overrides are already persisted as ``is_included``. For a new
    classification, every decision except an explicit exclusion is included.
    """

    if user_override and is_included is not None:
        return bool(is_included)
    return _normalize_decision(decision) != "exclude"
