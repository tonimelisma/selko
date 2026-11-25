def test_factory_builds_rows(db, factory):
    user = factory.user()
    event = factory.event(user)
    source = factory.event_source(event, email_id=factory.email(user))
    assert factory.row("events", event)["user_id"] == user
    assert factory.row("event_sources", source)["extracted_data"] == {}
