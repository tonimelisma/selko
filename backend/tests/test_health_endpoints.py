

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
