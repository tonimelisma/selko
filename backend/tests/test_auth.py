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

    client.assert_called_once()
    # The transport invariant this test exists for.
    assert client.call_args.kwargs["http2"] is False
    assert client.call_args.kwargs["timeout"] == 120
    options = create_client.call_args.kwargs["options"]
    assert options.httpx_client is http_client
    assert result is supabase_client


def test_service_client_meters_every_supabase_round_trip():
    """The egress hook must be attached to the one shared client.

    Every PostgREST query and RPC in the codebase goes through this client, so
    attaching the meter here is what makes the accounting impossible to bypass
    and impossible to forget on a new call site.
    """
    from selko.services.auth import _record_supabase_egress

    config = MagicMock(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-key",
    )

    with (
        patch("selko.services.auth.httpx.Client") as client,
        patch("selko.services.auth.create_client"),
    ):
        get_service_client(config)

    assert _record_supabase_egress in client.call_args.kwargs["event_hooks"]["response"]


def test_egress_accounting_never_breaks_a_database_call():
    """A meter that can raise would turn an accounting bug into an outage."""
    from selko.services.auth import _record_supabase_egress

    broken = MagicMock()
    # `.request` raising simulates any unexpected shape change in httpx.
    type(broken).request = property(lambda _self: (_ for _ in ()).throw(RuntimeError("boom")))

    _record_supabase_egress(broken)  # must not raise
