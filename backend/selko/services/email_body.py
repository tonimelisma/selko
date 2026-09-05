"""Recover an email's readable text when the provider only supplies HTML.

Gmail returns raw MIME parts, so a `multipart/alternative` whose `text/plain`
part is a placeholder leaves the real message in the `text/html` part alone.
Outlook never hits this: `Prefer: outlook.body-content-type="text"` makes Graph
render the HTML server-side, which is why only Gmail starved the extractor.

The concrete failure: Ticketmaster's "You Got Tickets To Monster Jam" carried
the single `text/plain` word "Ticketmaster" (14 bytes) beside a full HTML
confirmation. `body_text` was stored as that stub, the LLM was handed 14
characters, and it correctly reported no event.

`href` targets are emitted as text on purpose. `body_text` is not only LLM
input -- `services/events.py` feeds it to `build_hints()`, whose
`extract_urls()` scans for URL-shaped whitespace-separated tokens to derive
join and management identity hints. A conversion that kept anchor text and
dropped the target would silently disable that matching.
"""

from html.parser import HTMLParser
import logging
import re


logger = logging.getLogger(__name__)

# Tags whose content is markup machinery rather than message text.
_SKIPPED_CONTENT_TAGS = frozenset({"script", "style", "head", "title", "noscript"})

# Tags that end the current line of prose.
_BREAKING_TAGS = frozenset(
    {
        "br", "p", "div", "tr", "li", "table", "thead", "tbody", "section",
        "article", "header", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
        "blockquote", "pre", "hr", "ul", "ol", "td", "th",
    }
)

_BLANK_RUN = re.compile(r"\n{3,}")
_SPACE_RUN = re.compile(r"[ \t\r\f\v]+")


class _TextExtractor(HTMLParser):
    """Collect visible text plus link targets, mirroring _ImageSrcParser."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_CONTENT_TAGS:
            self._skip_depth += 1
            return
        if tag in _BREAKING_TAGS:
            self._chunks.append("\n")
        if tag == "a":
            href = dict(attrs).get("href") or ""
            # cid:/data:/mailto: targets are not links a reader can follow and
            # are never event identity hints.
            if href.startswith(("http://", "https://")):
                self._chunks.append(f" {href} ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BREAKING_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_CONTENT_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag in _BREAKING_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data:
            self._chunks.append(data)

    @property
    def text(self) -> str:
        joined = "".join(self._chunks)
        lines = [_SPACE_RUN.sub(" ", line).strip() for line in joined.split("\n")]
        return _BLANK_RUN.sub("\n\n", "\n".join(lines)).strip()


def html_to_text(html: str | None) -> str:
    """Render an HTML email body to plain text, keeping http(s) link targets."""
    if not html:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # pragma: no cover - defensive, matches email_images
        logger.warning("Failed to parse HTML body for text: %s", exc)
        return ""
    return parser.text


def select_body_text(plain: str | None, html: str | None) -> str | None:
    """Pick whichever part actually carries the message.

    The comparison is between the two candidates rather than against a fixed
    minimum length, because there is no length that separates a placeholder
    from a genuinely terse email. "Lunch at 1?" is short and real; a
    single-word brand name beside a full HTML confirmation is short and not.
    Asking which of the two says more needs no such threshold, and when a
    message is sent as matching text and HTML alternatives either answer
    carries the same content.
    """
    plain_text = (plain or "").strip()
    rendered = html_to_text(html)
    if len(rendered) > len(plain_text):
        return rendered
    return plain if plain_text else None


def is_substantive(text: str | None, *, alternative: str | None = None) -> bool:
    """Whether `text` is worth sending to extraction in place of `alternative`.

    Used at extraction time as a second line of defence for rows already
    stored with a placeholder body: a stub is truthy, so `body_text or snippet`
    never reached the snippet.
    """
    stripped = (text or "").strip()
    if not stripped:
        return False
    other = (alternative or "").strip()
    return len(stripped) >= len(other)
