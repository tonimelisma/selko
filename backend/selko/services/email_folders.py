"""Provider-independent mail-folder discovery and preference persistence."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable

from supabase import Client

from selko.services.folder_classification import (
    FolderClassification,
    classify_email_folder,
    effective_inclusion,
)
from selko.services.llm_gateway import LLMGateway

logger = logging.getLogger(__name__)

PERMANENT_GMAIL_LABEL_IDS = {
    "SPAM",
    "TRASH",
    "SENT",
    "DRAFT",
    "OUTBOX",
    "CATEGORY_PROMOTIONS",
    "CATEGORY_SOCIAL",
    "CATEGORY_FORUMS",
}

PERMANENT_OUTLOOK_WELL_KNOWN_NAMES = {
    "junkemail": "junk",
    "deleteditems": "trash",
    "sentitems": "sent",
    "drafts": "drafts",
    "outbox": "outbox",
}
HIDDEN_OUTLOOK_WELL_KNOWN_NAMES = {
    "searchfolders",
    "syncissues",
    "conflicts",
    "localfailures",
    "serverfailures",
    "recoverableitemsroot",
    "recoverableitemsdeletions",
    "recoverableitemspurges",
    "recoverableitemsversions",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def gmail_label_is_permanently_excluded(label: dict[str, Any]) -> bool:
    """Return whether a Gmail system label is outside the source set."""

    return label.get("id") in PERMANENT_GMAIL_LABEL_IDS


def outlook_folder_is_permanently_excluded(folder: dict[str, Any]) -> bool:
    """Return whether an Outlook well-known system folder is outside the source set."""

    well_known = str(
        folder.get("wellKnownName")
        or folder.get("well_known_name")
        or ""
    ).lower()
    return (
        well_known in PERMANENT_OUTLOOK_WELL_KNOWN_NAMES
        or well_known in HIDDEN_OUTLOOK_WELL_KNOWN_NAMES
        or bool(
            folder.get("is_permanently_excluded")
        )
    )


def _fallback_classification() -> FolderClassification:
    return FolderClassification(
        decision="uncertain",
        reason="Folder purpose is unclear, so it is included by default.",
    )


def upsert_discovered_folders(
    client: Client,
    *,
    user_id: str,
    integration_id: str,
    provider: str,
    folders: Iterable[dict[str, Any]],
    gateway: LLMGateway | None = None,
) -> list[dict[str, Any]]:
    """Persist folder discovery and classify only new or renamed folders.

    The provider adapters pass normalized dictionaries containing ``id``, ``name``,
    ``full_path``, ``parent_id``, ``kind``, and optionally ``is_system``/``system_kind``.
    Existing user overrides survive a rename or path change.
    """

    existing_result = (
        client.table("email_folders")
        .select("*")
        .eq("integration_id", integration_id)
        .execute()
    )
    existing = {
        row.get("provider_folder_id"): row
        for row in (existing_result.data or [])
        if row.get("provider_folder_id")
    }

    rows: list[dict[str, Any]] = []
    for folder in folders:
        provider_folder_id = str(folder["id"])
        name = str(folder.get("name") or provider_folder_id)
        full_path = str(folder.get("full_path") or name)
        is_system = bool(folder.get("is_system", False))
        is_permanently_excluded = bool(
            folder.get("is_permanently_excluded", False)
            or (
                provider == "outlook"
                and outlook_folder_is_permanently_excluded(folder)
            )
        )
        is_scannable = bool(folder.get("is_scannable", not is_permanently_excluded))
        system_kind = folder.get("system_kind")
        prior = existing.get(provider_folder_id)
        changed = bool(
            prior
            and (prior.get("name") != name or prior.get("full_path") != full_path)
        )

        if is_permanently_excluded:
            classification = FolderClassification(
                decision="exclude",
                reason="This provider system folder is permanently excluded.",
            )
            is_included = False
            user_override = False
            is_scannable = False
        elif is_system:
            # Eligible provider-owned folders such as Inbox and Archive are
            # scanned automatically but remain hidden from Settings.
            classification = FolderClassification(
                decision="include",
                reason="This provider system folder is included automatically.",
            )
            # Normalize rows created before system-folder recognition. Eligible
            # system folders are mandatory sources and are hidden from Settings,
            # so preserving an old user exclusion would make it impossible to
            # correct there.
            is_included = True
            user_override = False
            is_scannable = True
        elif prior and prior.get("user_override"):
            classification = FolderClassification(
                decision=prior.get("classification_decision") or "uncertain",
                reason=prior.get("classification_reason") or "User preference",
            )
            is_included = bool(prior.get("is_included"))
            user_override = True
        elif prior and not changed:
            classification = FolderClassification(
                decision=prior.get("classification_decision") or "uncertain",
                reason=prior.get("classification_reason") or "",
            )
            is_included = bool(prior.get("is_included", True))
            user_override = False
        else:
            classification = (
                classify_email_folder(
                    gateway,
                    user_id=user_id,
                    provider=provider,
                    name=name,
                    full_path=full_path,
                )
                if gateway
                else _fallback_classification()
            )
            is_included = effective_inclusion(classification.decision, False)
            user_override = False

        row = {
            "user_id": user_id,
            "integration_id": integration_id,
            "provider": provider,
            "provider_folder_id": provider_folder_id,
            "parent_folder_id": folder.get("parent_id"),
            "name": name,
            "full_path": full_path,
            "folder_kind": folder.get("kind") or ("label" if provider == "gmail" else "folder"),
            "is_system": is_system,
            "is_scannable": is_scannable,
            "is_permanently_excluded": is_permanently_excluded,
            "system_kind": system_kind,
            "classification_decision": classification.decision,
            "classification_reason": classification.reason,
            "user_override": user_override,
            "is_included": is_included,
            "updated_at": _now(),
        }
        if prior and prior.get("sync_cursor"):
            row["sync_cursor"] = prior["sync_cursor"]
        rows.append(row)

    if not rows:
        return []

    result = (
        client.table("email_folders")
        .upsert(rows, on_conflict="integration_id,provider_folder_id")
        .execute()
    )
    return result.data or rows


def set_folder_preference(
    client: Client,
    *,
    user_id: str,
    folder_id: str,
    is_included: bool,
) -> dict[str, Any] | None:
    """Persist a durable user override and reset the cursor when enabling a folder."""

    # The authenticated client must use the SECURITY DEFINER RPC. The table
    # UPDATE privilege is intentionally revoked so callers cannot mutate
    # provider metadata or system-folder rows alongside the preference.
    result = client.rpc(
        "set_email_folder_preference",
        {
            "p_folder_id": folder_id,
            "p_is_included": bool(is_included),
        },
    ).execute()
    if not result or not result.data:
        return None
    if isinstance(result.data, list):
        return result.data[0] if result.data else None
    return result.data
