"""The service wrapper around the fenced extraction commit, on a real database."""

from selko.services.events import _commit_email_extraction


def test_fenced_write_is_logged_not_raised(db, factory, caplog):
    user = factory.user()
    # The lease moved on: another worker holds generation 8.
    email = factory.email(user, processing_status="processing", locked_by="worker-new",
                          locked_until="2099-01-01T00:00:00.000000Z", lock_generation=8)

    with caplog.at_level("WARNING"):
        result = _commit_email_extraction(db, email, "worker-old", 7, [], "processed")

    assert result == {"fenced": True, "applied": 0}
    assert f"Extraction commit fenced for email {email}" in caplog.text
    # Nothing was written: the email is still the new worker's.
    row = factory.row("emails", email)
    assert (row["processing_status"], row["locked_by"]) == ("processing", "worker-new")
