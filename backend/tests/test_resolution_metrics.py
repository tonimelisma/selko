from selko.services.resolution_metrics import ResolutionMetrics


def test_resolution_metrics_snapshot_is_content_free():
    metrics = ResolutionMetrics()
    metrics.record_conflict()
    metrics.record_retries_per_email(1)
    metrics.record_retries_per_email(2)
    metrics.record_fenced_write()
    metrics.record_conflict_exhaustion()

    snapshot = metrics.snapshot()

    assert snapshot["conflicts_per_hour"] == 1
    assert snapshot["retries_per_email_histogram"] == {"1": 1, "2": 1}
    assert snapshot["fenced_writes_since_start"] == 1
    assert snapshot["conflict_exhaustion_count"] == 1
    assert "token" not in str(snapshot).lower()
