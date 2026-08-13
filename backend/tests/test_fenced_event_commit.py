from unittest.mock import MagicMock

from selko.services.events import _commit_email_extraction


def test_fenced_write_is_logged_not_raised(caplog):
    client = MagicMock()
    client.rpc.return_value.execute.return_value.data = {
        "fenced": True,
        "applied": 0,
        "event_ids": [],
    }

    with caplog.at_level("WARNING"):
        result = _commit_email_extraction(
            client, "email-1", "worker-old", 7, [], "processed"
        )

    assert result["fenced"] is True
    assert "Extraction commit fenced for email email-1" in caplog.text
