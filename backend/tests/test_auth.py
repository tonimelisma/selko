"""Unit tests for authentication client construction."""

from unittest.mock import MagicMock, patch

from selko.services.auth import get_service_client


def test_service_client_disables_http2_for_concurrent_workers():
    """Production service clients avoid the failing shared HTTP/2 transport."""
    config = MagicMock(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-key",
    )
    http_client = MagicMock(name="http_client")
    supabase_client = MagicMock(name="supabase_client")

    with (
        patch("selko.services.auth.httpx.Client", return_value=http_client) as client,
        patch(
            "selko.services.auth.create_client",
            return_value=supabase_client,
        ) as create_client,
    ):
        result = get_service_client(config)

    client.assert_called_once_with(http2=False, timeout=120)
    options = create_client.call_args.kwargs["options"]
    assert options.httpx_client is http_client
    assert result is supabase_client
