"""Regression tests for HTML-only email bodies reaching extraction.

Production defect: Ticketmaster's "You Got Tickets To Monster Jam" is a
multipart/alternative whose text/plain part is the single word "Ticketmaster"
(14 bytes) while the whole confirmation lives in the text/html part. Selko
stored the stub as body_text, discarded the HTML, and handed the extractor 14
characters. It returned no_event, correctly, and the event never reached the
review queue.

Outlook never reproduced this because Graph is asked for
`Prefer: outlook.body-content-type="text"` and renders the HTML server-side.
"""

import base64

import pytest

from selko.services.email_body import html_to_text, is_substantive, select_body_text
from selko.services.emails import parse_gmail_message


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


# The shape of the message that failed in production, reduced to its essentials.
_MONSTER_JAM_HTML = """
<html><head><style>.x{color:red}</style><title>Ticketmaster</title></head>
<body>
  <div>You Got the Tickets</div>
  <p>Order # 73-17813/NCA</p>
  <table><tr><td>Monster Jam</td><td>Sat, Oct 11, 2026 at 7:00 PM</td></tr>
  <tr><td>Oracle Park, San Francisco, CA</td></tr></table>
  <a href="https://www.ticketmaster.com/event/1A006FC0/manage">Manage your order</a>
  <script>track('open')</script>
</body></html>
"""


def _gmail_message(*, plain: str | None, html: str | None) -> dict:
    parts = []
    if plain is not None:
        parts.append({"mimeType": "text/plain", "body": {"data": _b64(plain)}})
    if html is not None:
        parts.append({"mimeType": "text/html", "body": {"data": _b64(html)}})
    return {
        "id": "monster-jam-id",
        "threadId": "monster-jam-thread",
        "snippet": "The countdown to your event starts now.",
        "labelIds": ["INBOX", "CATEGORY_UPDATES"],
        "payload": {
            "headers": [
                {"name": "From", "value": "Ticketmaster <customer_support@email.ticketmaster.com>"},
                {"name": "Subject", "value": "You Got Tickets To Monster Jam"},
            ],
            "parts": parts,
        },
    }


class TestStubPlainPart:
    def test_html_body_replaces_a_placeholder_plain_part(self):
        """The exact production failure: a one-word plain part beside real HTML."""
        msg = _gmail_message(plain="Ticketmaster\r\n", html=_MONSTER_JAM_HTML)

        body = parse_gmail_message(msg)["body_text"]

        assert "Monster Jam" in body
        assert "Sat, Oct 11, 2026 at 7:00 PM" in body
        assert "Oracle Park" in body
        # The whole point: extraction is no longer handed 14 bytes.
        assert len(body) > 100

    def test_html_body_used_when_there_is_no_plain_part_at_all(self):
        msg = _gmail_message(plain=None, html=_MONSTER_JAM_HTML)

        assert "Monster Jam" in parse_gmail_message(msg)["body_text"]

    def test_real_plain_text_body_is_left_alone(self):
        """A genuine plain-text email must not be replaced by HTML chrome."""
        plain = (
            "Hi Toni,\n\nConfirming our meeting on Tuesday at 2pm in the "
            "Mission office. Bring the quarterly numbers.\n\nThanks,\nAlex\n"
        )
        msg = _gmail_message(plain=plain, html="<html><body><p>Hi Toni</p></body></html>")

        assert parse_gmail_message(msg)["body_text"] == plain

    def test_short_but_genuine_plain_body_survives(self):
        """Terse is not the same as placeholder; there is no length floor."""
        msg = _gmail_message(plain="Lunch at 1?", html=None)

        assert parse_gmail_message(msg)["body_text"] == "Lunch at 1?"


class TestLinkPreservation:
    def test_href_targets_survive_conversion(self):
        """body_text feeds build_hints(); dropping hrefs would disable
        join/management identity matching (PRs #374/#375)."""
        text = html_to_text('<a href="https://zoom.us/j/9911223344">Join</a>')

        assert "https://zoom.us/j/9911223344" in text

    def test_extract_urls_still_finds_links_in_converted_text(self):
        from selko.services.event_identity import extract_urls

        body = parse_gmail_message(
            _gmail_message(plain="Ticketmaster\r\n", html=_MONSTER_JAM_HTML)
        )["body_text"]

        assert any("ticketmaster.com/event/1A006FC0/manage" in u for u in extract_urls(body))

    def test_non_navigable_hrefs_are_not_emitted(self):
        text = html_to_text('<a href="mailto:x@y.com">Mail</a><a href="cid:img1">Img</a>')

        assert "mailto:" not in text
        assert "cid:" not in text


class TestHtmlToText:
    def test_script_and_style_content_is_dropped(self):
        text = html_to_text(
            "<style>.a{color:red}</style><script>alert(1)</script><p>Real text</p>"
        )

        assert "color:red" not in text
        assert "alert(1)" not in text
        assert "Real text" in text

    def test_entities_are_unescaped(self):
        assert "Tom & Jerry" in html_to_text("<p>Tom &amp; Jerry</p>")

    def test_block_tags_separate_lines(self):
        text = html_to_text("<div>First</div><div>Second</div>")

        assert "First" in text and "Second" in text
        assert "FirstSecond" not in text

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_empty_input_returns_empty_string(self, value):
        assert html_to_text(value) == ""


class TestSelectBodyText:
    def test_returns_none_when_neither_part_has_content(self):
        assert select_body_text(None, None) is None
        assert select_body_text("   ", None) is None


class TestIsSubstantive:
    def test_placeholder_body_loses_to_a_longer_snippet(self):
        """Second line of defence for rows stored before the sync-time fix."""
        assert is_substantive("Ticketmaster", alternative="The countdown to your event starts now, Monster Jam") is False

    def test_real_body_beats_the_snippet(self):
        assert is_substantive("A" * 500, alternative="short snippet") is True

    @pytest.mark.parametrize("value", [None, "", "  \r\n "])
    def test_empty_body_is_never_substantive(self, value):
        assert is_substantive(value, alternative="anything") is False


class TestOutlookHtmlFallback:
    """Graph normally honours Prefer: outlook.body-content-type="text". When it
    does not, the previous code stored no body at all and extraction fell back
    to the ~255-char bodyPreview."""

    @staticmethod
    def _graph_message(*, content_type: str, content: str) -> dict:
        return {
            "id": "graph-id",
            "conversationId": "graph-thread",
            "subject": "Your booking",
            "from": {"emailAddress": {"address": "noreply@example.com", "name": "Example"}},
            "toRecipients": [],
            "receivedDateTime": "2026-09-05T04:07:45Z",
            "bodyPreview": "Short preview",
            "hasAttachments": False,
            "body": {"contentType": content_type, "content": content},
        }

    def test_text_content_is_stored_verbatim(self):
        from selko.services.outlook import parse_outlook_message

        msg = self._graph_message(content_type="text", content="Booking confirmed for 3pm.")

        assert parse_outlook_message(msg)["body_text"] == "Booking confirmed for 3pm."

    def test_html_content_is_rendered_rather_than_dropped(self):
        from selko.services.outlook import parse_outlook_message

        msg = self._graph_message(
            content_type="html",
            content="<html><body><p>Booking confirmed for 3pm at "
                    '<a href="https://maps.example.com/venue">The Venue</a></p></body></html>',
        )

        body = parse_outlook_message(msg)["body_text"]

        assert "Booking confirmed for 3pm" in body
        assert "https://maps.example.com/venue" in body
