"""Regression tests for durable email ingestion and user-facing history state."""

from unittest.mock import MagicMock

from selko.services.email_folders import (
    gmail_label_is_permanently_excluded,
    outlook_folder_is_permanently_excluded,
)
from selko.services.folder_classification import (
    FolderClassification,
    classify_email_folder,
)
from selko.services.gmail import build_initial_sync_query, fetch_history_message_ids
from selko.services.emails import complete_email_processing
from selko.services.outlook import normalize_mail_folders


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
