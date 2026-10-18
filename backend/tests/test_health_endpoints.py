

def test_health_publishes_an_absolute_process_start_time():
    """A duration cannot identify which process answered; an instant can.

    Production once returned uptimes 3.19 days apart within fifteen minutes
    while Render reported a single instance. With only `uptime_seconds` there
    was no way to tell a second process from a broken counter, and the question
    stayed open. `started_at` settles it: identical value means identical
    process, and it can be compared against the deploy time directly.
    """
    from datetime import datetime

    from selko.services.resolution_metrics import resolution_metrics

    started = resolution_metrics.started_at
    assert started.tzinfo is not None, "started_at must be timezone-aware"
    # Round-trips as ISO-8601 so a probe can parse it without guessing a format.
    assert datetime.fromisoformat(started.isoformat()) == started


def test_health_reports_server_error_rate():
    """/health must publish what the API has been answering, not just internals.

    Production returned 500 to every /events/{id}/apply-change for eight days
    while every health invariant stayed green: the workers were alive, the
    queues were clean, the listener was connected. Nothing measured responses.
    """
    from selko.services.request_metrics import RequestMetrics

    metrics = RequestMetrics()
    metrics.record(status_code=200, route="/events/{event_id}/apply-change")
    metrics.record(status_code=500, route="/events/{event_id}/apply-change")
    metrics.record(status_code=404, route="/events/{event_id}")

    snapshot = metrics.snapshot()
    assert snapshot["requests_per_hour"] == 3
    assert snapshot["server_errors_per_hour"] == 1, snapshot
    # 4xx is a client problem, not a service failure.
    assert snapshot["server_error_routes"] == {"/events/{event_id}/apply-change": 1}


def test_request_metrics_records_route_templates_not_paths():
    """Content-free by construction: no identifiers may enter the counters."""
    from selko.services.request_metrics import RequestMetrics

    metrics = RequestMetrics()
    metrics.record(status_code=500, route="/events/{event_id}/apply-change")

    routes = metrics.snapshot()["server_error_routes"]
    assert list(routes) == ["/events/{event_id}/apply-change"]
    assert all("{" in route for route in routes), "a concrete path would leak an id"


def test_transport_probe_reports_unavailable_for_a_pool_that_cannot_answer():
    """assert-health.sh asserts `transport == "asyncpg"` to prove the worker
    transport is live. That assertion used to read `pool is not None`, which is
    equally true of a pool whose every connection is wedged -- so the gate
    could not fail for the one reason worth gating on.

    A hung `pool.acquire()` (asyncpg has no default acquire timeout) inside an
    unbounded executor is how acquisition stalled for 19 days.
    """
    import asyncio
    from unittest.mock import AsyncMock

    from selko.api.routes.health import _pg_transport_state

    working = AsyncMock()
    working.fetchval = AsyncMock(return_value=1)
    assert asyncio.run(_pg_transport_state(working)) == "asyncpg"

    broken = AsyncMock()
    broken.fetchval = AsyncMock(side_effect=OSError("connection reset"))
    assert asyncio.run(_pg_transport_state(broken)) == "unavailable"

    assert asyncio.run(_pg_transport_state(None)) == "none"


def test_transport_probe_cannot_hang_the_health_route():
    """The probe is bounded, or a wedged pool takes the health check with it."""
    import asyncio
    from unittest.mock import AsyncMock

    from selko.api.routes.health import _pg_transport_state

    async def scenario():
        never_returns = asyncio.Event()
        pool = AsyncMock()

        async def hang(*_args):
            await never_returns.wait()

        pool.fetchval = hang
        # Well inside the probe's own 5s bound, so a pass here means the bound
        # fired rather than the test merely being patient.
        return await asyncio.wait_for(_pg_transport_state(pool), timeout=20)

    assert asyncio.run(scenario()) == "unavailable"
