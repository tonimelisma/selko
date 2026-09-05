"""Tests for the body re-sync selection and write decisions.

The repair tool exists because #381 fixes new mail and cannot fix history:
`reprocess_email` re-runs extraction on stored data and never re-fetches, so a
row saved with a placeholder body stays broken however many times Reprocess is
clicked. Measured on production at the time of writing: 61 stored Gmail rows
had no body at all and were extracted from a ~200-character snippet.
"""

import pytest

from cli_resync_email_bodies import describe_change, is_starved


class TestIsStarved:
    def test_no_stored_body_is_starved(self):
        """The commonest shape: HTML-only mail with no text/plain part."""
        assert is_starved(None, "The countdown to your event starts now, 200 chars of preview") is True

    def test_placeholder_body_shorter_than_snippet_is_starved(self):
        """The Monster Jam shape: truthy, and still says less than the snippet."""
        assert is_starved("Ticketmaster\r\n", "You Got the Tickets Order # 73-17813 Monster Jam preview") is True

    def test_real_body_longer_than_snippet_is_not_starved(self):
        assert is_starved("A" * 4000, "short preview") is False

    def test_body_equal_to_snippet_is_not_starved(self):
        """Equal length means nothing was lost; do not churn the row."""
        assert is_starved("same text here", "same text here") is False

    def test_absent_snippet_cannot_prove_starvation(self):
        """With no preview to compare against there is no evidence of loss."""
        assert is_starved(None, None) is False
        assert is_starved("", "   ") is False

    def test_whitespace_only_body_is_starved(self):
        assert is_starved("  \r\n  ", "a real preview of the message") is True


class TestDescribeChange:
    def test_growth_is_worth_writing(self):
        worth, reason = describe_change("Ticketmaster", "A" * 8551)
        assert worth is True
        assert "8551" in reason

    def test_empty_refetch_is_never_written(self):
        """A provider returning nothing must not blank a stored body."""
        worth, reason = describe_change("existing body", "")
        assert worth is False
        assert "no usable body" in reason

    def test_no_improvement_is_skipped(self):
        worth, reason = describe_change("A" * 500, "A" * 500)
        assert worth is False
        assert "no improvement" in reason

    def test_shrinkage_is_skipped(self):
        """Never trade a longer stored body for a shorter re-fetch."""
        worth, _ = describe_change("A" * 900, "A" * 100)
        assert worth is False

    @pytest.mark.parametrize("old", [None, "", "   "])
    def test_growth_from_nothing_is_worth_writing(self, old):
        worth, _ = describe_change(old, "a recovered body with real content")
        assert worth is True
