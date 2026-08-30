

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
