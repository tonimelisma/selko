"""Regression tests for durable email ingestion and user-facing history state."""

from unittest.mock import MagicMock, patch

import pytest

from selko.services.email_folders import (
    gmail_label_is_permanently_excluded,
    outlook_folder_is_permanently_excluded,
    upsert_discovered_folders,
)
from selko.services.attachments import AttachmentError
from selko.services.folder_classification import (
    FolderClassification,
    classify_email_folder,
)
from selko.services.gmail import (
    GmailHistoryExpiredError,
    build_initial_sync_query,
    fetch_history_message_ids,
)
from selko.services.emails import complete_email_processing
from selko.services.outlook import (
    GraphHttpError,
    fetch_mail_folders,
    normalize_mail_folders,
)


def test_initial_gmail_query_is_bounded_and_excludes_arbitrary_user_labels():
    query = build_initial_sync_query(["Lists/Promotions", 'Deals "VIP"'])

    assert "after:" in query
    assert "-in:spam" in query
    assert '-label:"Lists/Promotions"' in query
    assert '-label:"Deals \\"VIP\\""' in query


def test_gmail_history_drains_every_page_and_deduplicates_message_ids():
    client = MagicMock()
    history = client.users.return_value.history.return_value
    history.list.return_value.execute.side_effect = [
        {
            "history": [
                {"id": "11", "messagesAdded": [{"message": {"id": "m1"}}]},
                {"id": "12", "labelsAdded": [{"message": {"id": "m2"}}]},
            ],
            "historyId": "12",
            "nextPageToken": "page-2",
        },
        {
            "history": [
                {"id": "13", "labelsRemoved": [{"message": {"id": "m1"}}]},
                {"id": "14", "messagesDeleted": [{"message": {"id": "m3"}}]},
            ],
            "historyId": "14",
        },
    ]

    message_ids, cursor = fetch_history_message_ids(client, "10")

    assert message_ids == ["m1", "m2", "m3"]
    assert cursor == "14"
    assert history.list.call_count == 2


def test_provider_system_folders_are_never_user_configurable():
    assert gmail_label_is_permanently_excluded({"id": "CATEGORY_PROMOTIONS"})
    assert gmail_label_is_permanently_excluded({"id": "TRASH"})
    assert outlook_folder_is_permanently_excluded({"wellKnownName": "deleteditems"})
    assert outlook_folder_is_permanently_excluded({"wellKnownName": "junkemail"})
    assert not outlook_folder_is_permanently_excluded({"wellKnownName": "inbox"})


def test_outlook_folder_paths_include_nested_parent_context():
    folders = normalize_mail_folders([
        {"id": "root", "displayName": "Projects"},
        {"id": "child", "displayName": "School", "parentFolderId": "root"},
    ])

    assert next(folder for folder in folders if folder["id"] == "child")["full_path"] == "Projects/School"


def test_outlook_folder_discovery_uses_immutable_ids_and_does_not_traverse_forbidden_trees():
    aliases = {
        "inbox": "immutable-inbox",
        "junkemail": "immutable-junk",
        "sentitems": "immutable-sent",
        "searchfolders": "immutable-search",
    }
    child_requests = []

    def graph_get(_token, url, **_kwargs):
        if url.endswith("/mailFolders"):
            return {
                "value": [
                    {"id": "immutable-inbox", "displayName": "Boîte de réception"},
                    {"id": "immutable-junk", "displayName": "Courrier indésirable"},
                    {"id": "immutable-sent", "displayName": "Gesendet"},
                    {"id": "immutable-search", "displayName": "Search folders"},
                    {"id": "custom", "displayName": "Projects"},
                ]
            }
        if "/childFolders" in url:
            child_requests.append(url)
            return {"value": []}
        alias = url.rsplit("/", 1)[-1]
        if alias in aliases:
            return {"id": aliases[alias]}
        return {"value": []}

    with patch("selko.services.outlook._graph_get", side_effect=graph_get):
        folders = fetch_mail_folders("token", resolved_well_known_ids=aliases)

    ids = {folder["id"] for folder in folders}
    assert ids == {"immutable-inbox", "custom"}
    assert all("immutable-junk" not in request for request in child_requests)
    assert all("immutable-sent" not in request for request in child_requests)
    assert all("immutable-search" not in request for request in child_requests)
    assert next(folder for folder in folders if folder["id"] == "immutable-inbox")["wellKnownName"] == "inbox"


def test_outlook_conversation_history_is_never_discovered_or_traversed():
    aliases = {"conversationhistory": "conversation-history-id"}
    child_requests = []

    def graph_get(_token, url, **_kwargs):
        if url.endswith("/mailFolders"):
            return {
                "value": [
                    {
                        "id": "conversation-history-id",
                        "displayName": "Conversation History",
                    },
                    {"id": "custom", "displayName": "Newsletters"},
                ]
            }
        if "/childFolders" in url:
            child_requests.append(url)
        return {"value": []}

    with patch("selko.services.outlook._graph_get", side_effect=graph_get):
        folders = fetch_mail_folders("token", resolved_well_known_ids=aliases)

    assert [folder["id"] for folder in folders] == ["custom"]
    assert all("conversation-history-id" not in request for request in child_requests)


def _folder_integration(factory, provider: str = "outlook") -> tuple[str, str]:
    user = factory.user()
    return user, factory.integration(user, provider=provider)


def _inbox() -> dict:
    return {
        "id": "inbox-id",
        "name": "Boîte de réception",
        "full_path": "Boîte de réception",
        "kind": "folder",
        "is_system": True,
        "is_scannable": True,
        "system_kind": "inbox",
    }


def test_upsert_does_not_classify_eligible_system_folders_and_preserves_scan_metadata(db, factory):
    user, integration_id = _folder_integration(factory)
    gateway = MagicMock()

    [row] = upsert_discovered_folders(
        db,
        user_id=user,
        integration_id=integration_id,
        provider="outlook",
        folders=[_inbox()],
        gateway=gateway,
    )

    assert row["is_system"] is True
    assert row["is_scannable"] is True
    assert row["is_included"] is True
    assert row["system_kind"] == "inbox"
    assert row["user_id"] == user
    gateway.for_user.assert_not_called()


def test_upsert_normalizes_stale_system_folder_exclusion(db, factory):
    user, integration_id = _folder_integration(factory)
    # A row saved before system-folder recognition: excluded by a user override.
    upsert_discovered_folders(db, user_id=user, integration_id=integration_id, provider="outlook",
                              folders=[{**_inbox(), "is_system": False}])
    from selko.db import email_sync

    [stale] = email_sync.folders_for_integration(db, integration_id)
    with db.write() as tx:
        tx.execute("UPDATE email_folders SET is_included = 0, user_override = 1 WHERE id = ?", (stale["id"],))

    [row] = upsert_discovered_folders(db, user_id=user, integration_id=integration_id, provider="outlook",
                                      folders=[_inbox()])

    assert row["id"] == stale["id"]
    assert row["is_included"] is True
    assert row["user_override"] is False


def test_a_rediscovered_folder_keeps_its_cursor_and_user_override(db, factory):
    user, integration_id = _folder_integration(factory)
    label = {"id": "label-1", "name": "School", "full_path": "School", "kind": "folder"}
    [first] = upsert_discovered_folders(db, user_id=user, integration_id=integration_id,
                                        provider="outlook", folders=[label])
    from selko.db.email_sync import set_email_folder_preference

    set_email_folder_preference(db, user, first["id"], False)
    with db.write() as tx:
        tx.execute("UPDATE email_folders SET sync_cursor = 'delta-1' WHERE id = ?", (first["id"],))

    [again] = upsert_discovered_folders(db, user_id=user, integration_id=integration_id,
                                        provider="outlook", folders=[label])

    assert again["id"] == first["id"]
    assert again["is_included"] is False
    assert again["user_override"] is True
    assert again["sync_cursor"] == "delta-1"


def test_folder_classifier_uses_only_folder_metadata_and_preserves_structured_reason():
    gateway = MagicMock()
    gateway.for_user.return_value = gateway
    gateway.call.return_value.text = '{"decision":"exclude","reason":"Clearly commercial promotions."}'

    result = classify_email_folder(
        gateway,
        user_id="user-1",
        provider="outlook",
        name="Boletines",
        full_path="Archive/Boletines",
    )

    assert result == FolderClassification(
        decision="exclude",
        reason="Clearly commercial promotions.",
    )
    prompt = gateway.call.call_args.kwargs["contents"][0]
    assert "Archive/Boletines" in prompt
    assert "Email Body" not in prompt


def test_successful_completion_clears_stale_processing_error_atomically(db, factory):
    import asyncio

    email_id = factory.email(
        factory.user(), processing_status="processing", processing_error="earlier failure",
        locked_by="worker-1", locked_until="2999-01-01T00:00:00.000000Z", attempts=1,
    )

    asyncio.run(complete_email_processing(db, email_id))

    row = factory.row("emails", email_id)
    assert row["processing_status"] == "processed"
    assert row["processing_error"] is None
    assert row["locked_by"] is None
    assert row["locked_until"] is None
    assert row["processed_at"] is not None
