"""Regression tests for explicit public-schema Data API grants."""

import pytest
from postgrest import APIError
from supabase import create_client


@pytest.mark.integration
@pytest.mark.development
def test_profile_is_reachable_by_service_role_and_owner(
    admin_client, temp_user, temp_user_client
):
    """Service seeding and authenticated profile access work through PostgREST."""
    user_id, _, _ = temp_user

    admin_result = (
        admin_client.table("users")
        .update({"display_name": "Screenshot Admin"})
        .eq("id", user_id)
        .execute()
    )
    assert admin_result.data[0]["display_name"] == "Screenshot Admin"

    owner_result = (
        temp_user_client.table("users")
        .update({"display_name": "Profile Owner"})
        .eq("id", user_id)
        .execute()
    )
    assert owner_result.data[0]["display_name"] == "Profile Owner"

    profile = (
        temp_user_client.table("users")
        .select("id,display_name")
        .eq("id", user_id)
        .single()
        .execute()
    )
    assert profile.data == {"id": user_id, "display_name": "Profile Owner"}


@pytest.mark.integration
@pytest.mark.development
def test_authenticated_read_only_tables_are_reachable(temp_user_client):
    """Authenticated reads are granted where RLS intentionally permits them."""
    result = temp_user_client.table("global_limits").select("limit_type").execute()

    assert {row["limit_type"] for row in result.data} == {
        "calendar_syncs_daily",
        "email_syncs_daily",
        "llm_calls_daily",
    }

    with pytest.raises(APIError) as exc_info:
        temp_user_client.table("global_limits").update({"is_active": False}).eq(
            "limit_type", "llm_calls_daily"
        ).execute()
    assert exc_info.value.code == "42501"


@pytest.mark.integration
@pytest.mark.development
def test_authenticated_cannot_read_integration_token_columns(
    admin_client, temp_user, temp_user_client
):
    """OAuth token columns stay service-role-only; metadata stays readable."""
    user_id, _, _ = temp_user

    admin_client.table("integrations").insert(
        {
            "user_id": user_id,
            "provider": "gmail",
            "status": "active",
            "access_token": "secret-access-token",
            "refresh_token": "secret-refresh-token",
            "provider_email": "grants-test@example.com",
        }
    ).execute()

    metadata = (
        temp_user_client.table("integrations")
        .select("id,provider,status,provider_email")
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    assert metadata.data["provider_email"] == "grants-test@example.com"

    for column in ("access_token", "refresh_token", "token_expiry"):
        with pytest.raises(APIError) as exc_info:
            temp_user_client.table("integrations").select(column).eq(
                "user_id", user_id
            ).execute()
        assert exc_info.value.code == "42501", column

    # Disconnect (delete) must still work for the owner. The app clients all
    # delete with minimal returns; representation would RETURNING * and hit
    # the revoked token columns.
    temp_user_client.table("integrations").delete(returning="minimal").eq(
        "user_id", user_id
    ).execute()
    remaining = (
        admin_client.table("integrations").select("id").eq("user_id", user_id).execute()
    )
    assert remaining.data == []


@pytest.mark.integration
@pytest.mark.development
def test_anonymous_role_cannot_read_application_tables(config):
    """Public application tables are not exposed to anonymous Data API users."""
    anonymous_client = create_client(config.supabase_url, config.supabase_key)

    with pytest.raises(APIError) as exc_info:
        anonymous_client.table("global_limits").select("limit_type").execute()
    assert exc_info.value.code == "42501"
