"""OAuth integration storage over a real SQLite database.

Credentials are written as the callback writes them (``save_oauth_credentials``
on the process database) and read back through the services. The four
column-grant tests of the Postgres era are replaced: there are no database
roles, and the API is the only door, so the property they protected becomes
"no client response carries a token column" (``TestNoTokenLeavesTheApi``;
docs/specs/sqlite-single-process/05-verification.md §A.2 row 31). The staging
test went with staging.
"""

import pytest

from selko.services.integrations import (
    delete_integration,
    get_oauth_credentials,
    get_provider_integration,
    save_oauth_credentials,
    update_integration_status,
    update_oauth_credentials,
)

TOKEN_COLUMNS = {"access_token", "refresh_token", "code_verifier"}


@pytest.fixture
def sample_oauth_credentials():
    from google.oauth2.credentials import Credentials

    return Credentials(
        token="test_access_token_12345",
        refresh_token="test_refresh_token_67890",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="test_client_id",
        client_secret="test_client_secret",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )


def _credentials(token: str, sample, **overrides):
    """Build a Credentials object that differs from `sample` only by token."""
    from google.oauth2.credentials import Credentials

    fields = {
        "token": token,
        "refresh_token": sample.refresh_token,
        "token_uri": sample.token_uri,
        "client_id": sample.client_id,
        "client_secret": sample.client_secret,
        "scopes": sample.scopes,
    }
    fields.update(overrides)
    return Credentials(**fields)


class TestOAuthIntegrations:
    def test_save_oauth_credentials(self, db, factory, mock_config, sample_oauth_credentials):
        user_id = factory.user()
        save_oauth_credentials(db, user_id, "gmail", sample_oauth_credentials,
                               provider_email="test@gmail.com")

        creds = get_oauth_credentials(db, mock_config, "gmail", user_id=user_id)
        assert creds is not None
        assert creds.token == sample_oauth_credentials.token
        assert creds.refresh_token == sample_oauth_credentials.refresh_token

    def test_get_oauth_credentials_not_found(self, db, factory, mock_config):
        assert get_oauth_credentials(db, mock_config, "google_calendar", user_id=factory.user()) is None

    def test_save_credentials_upsert(self, db, factory, mock_config, sample_oauth_credentials):
        user_id = factory.user()
        save_oauth_credentials(db, user_id, "gmail", sample_oauth_credentials)
        save_oauth_credentials(db, user_id, "gmail", _credentials("updated_token_xyz", sample_oauth_credentials))

        creds = get_oauth_credentials(db, mock_config, "gmail", user_id=user_id)
        assert creds.token == "updated_token_xyz"
        rows = db.query("SELECT id FROM integrations WHERE user_id = ? AND provider = 'gmail'", (user_id,))
        assert len(rows) == 1, "upsert must not create a second row"

    def test_update_integration_status(self, db, factory, mock_config, sample_oauth_credentials):
        """A non-active status hides credentials from callers."""
        user_id = factory.user()
        save_oauth_credentials(db, user_id, "gmail", sample_oauth_credentials)

        update_integration_status(db, "gmail", "expired", user_id=user_id)

        assert get_oauth_credentials(db, mock_config, "gmail", user_id=user_id) is None

    def test_update_oauth_credentials(self, db, factory, mock_config, sample_oauth_credentials):
        user_id = factory.user()
        save_oauth_credentials(db, user_id, "gmail", sample_oauth_credentials)

        update_oauth_credentials(
            db, "gmail", _credentials("refreshed_token_abc", sample_oauth_credentials), user_id=user_id
        )

        assert get_oauth_credentials(db, mock_config, "gmail", user_id=user_id).token == "refreshed_token_abc"

    def test_scopes_stored_as_array(self, db, factory, mock_config, sample_oauth_credentials):
        user_id = factory.user()
        save_oauth_credentials(db, user_id, "gmail", sample_oauth_credentials)

        creds = get_oauth_credentials(db, mock_config, "gmail", user_id=user_id)
        assert creds.scopes == list(sample_oauth_credentials.scopes)

    def test_provider_email_stored(self, db, factory, sample_oauth_credentials):
        user_id = factory.user()
        save_oauth_credentials(db, user_id, "gmail", sample_oauth_credentials,
                               provider_email="myemail@gmail.com")

        assert get_provider_integration(db, "gmail", user_id=user_id)["provider_email"] == "myemail@gmail.com"

    def test_multiple_providers(self, db, factory, mock_config, sample_oauth_credentials):
        user_id = factory.user()
        save_oauth_credentials(db, user_id, "gmail", sample_oauth_credentials)
        save_oauth_credentials(
            db, user_id, "google_calendar",
            _credentials("calendar_token", sample_oauth_credentials, refresh_token="calendar_refresh",
                         scopes=["https://www.googleapis.com/auth/calendar"]),
        )

        gmail = get_oauth_credentials(db, mock_config, "gmail", user_id=user_id)
        calendar = get_oauth_credentials(db, mock_config, "google_calendar", user_id=user_id)
        assert gmail.token != calendar.token

    def test_disconnect_removes_the_row_and_its_sync_state(self, db, factory, sample_oauth_credentials):
        user_id = factory.user()
        save_oauth_credentials(db, user_id, "gmail", sample_oauth_credentials)
        integration_id = get_provider_integration(db, "gmail", user_id=user_id)["id"]

        delete_integration(db, "gmail", user_id=user_id)

        assert get_provider_integration(db, "gmail", user_id=user_id) is None
        assert db.query_one(
            "SELECT 1 FROM email_sync_state WHERE integration_id = ?", (integration_id,)
        ) is None, "foreign keys cascade (PRAGMA foreign_keys=ON)"


class TestNoTokenLeavesTheApi:
    """The integration responses a client can receive never name a token column."""

    def test_integration_response_models_have_no_token_fields(self):
        from selko.api.schemas import integrations as schemas

        for model in (schemas.IntegrationResponse, schemas.EmailFolderPreferenceResponse):
            assert not (set(model.model_fields) & TOKEN_COLUMNS), model.__name__

    def test_no_integrations_route_returns_a_raw_row(self):
        """Every JSON integrations route declares a response model (or redirects)."""
        from selko.api.routes import integrations as routes

        for route in routes.router.routes:
            if "GET" in route.methods and route.path.endswith("/folders"):
                assert route.response_model is not None, route.path
            if "PATCH" in route.methods:
                assert route.response_model is not None, route.path
