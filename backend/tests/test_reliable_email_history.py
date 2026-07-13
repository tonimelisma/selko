"""Regression tests for durable email ingestion and user-facing history state."""

from unittest.mock import MagicMock, patch

import pytest

from selko.services.email_folders import (
    gmail_label_is_permanently_excluded,
    outlook_folder_is_permanently_excluded,
    set_folder_preference,
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
from selko.services.outlook import fetch_mail_folders, normalize_mail_folders
from selko.workers.email_fetch import _process_gmail_reliable


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


def test_upsert_does_not_classify_eligible_system_folders_and_preserves_scan_metadata():
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    client.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[])
    gateway = MagicMock()

    upsert_discovered_folders(
        client,
        user_id="user-1",
        integration_id="integration-1",
        provider="outlook",
        folders=[{
            "id": "inbox-id",
            "name": "Boîte de réception",
            "full_path": "Boîte de réception",
            "kind": "folder",
            "is_system": True,
            "is_scannable": True,
            "system_kind": "inbox",
        }],
        gateway=gateway,
    )

    row = client.table.return_value.upsert.call_args.args[0][0]
    assert row["is_system"] is True
    assert row["is_scannable"] is True
    assert row["is_included"] is True
    gateway.for_user.assert_not_called()


def test_folder_preference_uses_restricted_rpc_instead_of_table_update():
    client = MagicMock()
    client.rpc.return_value.execute.return_value = MagicMock(data=[{"id": "folder-1", "is_included": False}])

    result = set_folder_preference(
        client,
        user_id="user-1",
        folder_id="folder-1",
        is_included=False,
    )

    assert result["id"] == "folder-1"
    client.rpc.assert_called_once_with(
        "set_email_folder_preference",
        {"p_folder_id": "folder-1", "p_is_included": False},
    )
    client.table.return_value.update.assert_not_called()


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


def test_successful_completion_clears_stale_processing_error_atomically():
    client = MagicMock()

    complete_email_processing(client, "email-1")

    update = client.table.return_value.update.call_args.args[0]
    assert update["processing_status"] == "processed"
    assert update["processing_error"] is None
    assert update["locked_by"] is None
    assert update["locked_until"] is None


def test_gmail_expired_cursor_is_replaced_before_overlap_search():
    client = MagicMock()
    order = []

    def replacement_profile(_service):
        order.append("profile")
        return {"historyId": "replacement-cursor"}

    def overlap_search(_service, **_kwargs):
        order.append("search")
        return []

    with (
        patch("selko.workers.email_fetch.get_credentials", return_value=MagicMock()),
        patch("selko.workers.email_fetch.build_service", return_value=MagicMock()),
        patch("selko.workers.email_fetch.list_labels", return_value=[]),
        patch("selko.workers.email_fetch.upsert_discovered_folders"),
        patch("selko.workers.email_fetch._folder_classifier_gateway", return_value=None),
        patch("selko.workers.email_fetch._gmail_excluded_user_labels", return_value=(set(), [])),
        patch("selko.workers.email_fetch.fetch_history_message_ids", side_effect=lambda *_args: (order.append("history") or (_ for _ in ()).throw(GmailHistoryExpiredError("expired")))),
        patch("selko.workers.email_fetch.get_user_profile", side_effect=replacement_profile),
        patch("selko.workers.email_fetch.list_message_ids", side_effect=overlap_search),
        patch("selko.workers.email_fetch._save_sync_cursor") as save_cursor,
    ):
        _process_gmail_reliable(
            client,
            MagicMock(),
            {"user_id": "user-1"},
            {"id": "integration-1", "sync_cursor": "expired-cursor"},
        )

    assert order == ["history", "profile", "search"]
    save_cursor.assert_called_once_with(
        client,
        "user-1",
        "gmail",
        "replacement-cursor",
        include_last_sync=True,
    )


def test_gmail_attachment_failure_leaves_previous_cursor_unchanged():
    client = MagicMock()
    message = {"id": "message-1", "labelIds": ["INBOX"]}

    with (
        patch("selko.workers.email_fetch.get_credentials", return_value=MagicMock()),
        patch("selko.workers.email_fetch.build_service", return_value=MagicMock()),
        patch("selko.workers.email_fetch.list_labels", return_value=[]),
        patch("selko.workers.email_fetch.upsert_discovered_folders"),
        patch("selko.workers.email_fetch._folder_classifier_gateway", return_value=None),
        patch("selko.workers.email_fetch._gmail_excluded_user_labels", return_value=(set(), [])),
        patch("selko.workers.email_fetch.fetch_history_message_ids", return_value=(["message-1"], "next-cursor")),
        patch("selko.workers.email_fetch.get_message_metadata", return_value=message),
        patch("selko.workers.email_fetch.get_gmail_full_message", return_value=message),
        patch("selko.workers.email_fetch.parse_gmail_message", return_value={
            "email_provider": "gmail",
            "provider_message_id": "message-1",
        }),
        patch("selko.workers.email_fetch._store_email_record", return_value=[{"id": "email-1"}]),
        patch("selko.workers.email_fetch.store_gmail_message_attachments", side_effect=AttachmentError("download failed")),
        patch("selko.workers.email_fetch._save_sync_cursor") as save_cursor,
    ):
        with pytest.raises(AttachmentError, match="download failed"):
            _process_gmail_reliable(
                client,
                MagicMock(),
                {"user_id": "user-1"},
                {"id": "integration-1", "sync_cursor": "cursor-1"},
            )

    save_cursor.assert_not_called()
