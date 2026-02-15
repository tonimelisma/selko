"""Extract linked images from email HTML bodies.

Parses HTML for <img> tags, filters out tracking pixels and non-image
content, and downloads the images for LLM processing.
"""

import logging
from html.parser import HTMLParser
from typing import Optional

import httpx

from selko.services.llm_provider import ImageContent

logger = logging.getLogger(__name__)

# Image MIME types we'll download
_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/bmp",
    "image/tiff",
}

# Common tracking pixel domains to skip
_TRACKING_DOMAINS = {
    "open.tracking",
    "pixel.",
    "beacon.",
    "track.",
    "analytics.",
    "mailchimp.com/track",
    "list-manage.com/track",
}


class _ImageSrcParser(HTMLParser):
    """Extract src attributes from <img> tags."""

    def __init__(self):
        super().__init__()
        self.image_urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]):
        if tag != "img":
            return
        attrs_dict = dict(attrs)
        src = attrs_dict.get("src", "")
        if not src:
            return

        # Skip data: URIs and cid: references
        if src.startswith("data:") or src.startswith("cid:"):
            return

        # Skip tiny images (tracking pixels) based on width/height attributes
        width = attrs_dict.get("width", "")
        height = attrs_dict.get("height", "")
        try:
            if width and height and int(width) <= 2 and int(height) <= 2:
                return
        except ValueError:
            pass

        self.image_urls.append(src)


def _is_tracking_url(url: str) -> bool:
    """Check if URL is likely a tracking pixel."""
    url_lower = url.lower()
    return any(domain in url_lower for domain in _TRACKING_DOMAINS)


def extract_linked_images(
    html_body: str,
    max_images: int = 10,
    max_size: int = 5 * 1024 * 1024,
    timeout: float = 10.0,
) -> list[ImageContent]:
    """Extract and download linked images from HTML email body.

    Args:
        html_body: HTML content of the email.
        max_images: Maximum number of images to download.
        max_size: Maximum size per image in bytes.
        timeout: HTTP request timeout in seconds.

    Returns:
        List of ImageContent objects with downloaded image data.
    """
    # Parse HTML for image URLs
    parser = _ImageSrcParser()
    try:
        parser.feed(html_body)
    except Exception as e:
        logger.warning(f"Failed to parse HTML for images: {e}")
        return []

    urls = parser.image_urls
    if not urls:
        return []

    # Deduplicate and filter
    seen: set[str] = set()
    filtered_urls: list[str] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)

        if _is_tracking_url(url):
            logger.debug(f"Skipping tracking pixel: {url[:80]}")
            continue

        # Ensure absolute URL
        if not url.startswith(("http://", "https://")):
            continue

        filtered_urls.append(url)

    if not filtered_urls:
        return []

    # Download images
    results: list[ImageContent] = []
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for url in filtered_urls[:max_images]:
            try:
                response = client.get(url)
                response.raise_for_status()

                content_type = response.headers.get("content-type", "").split(";")[0].strip()

                # Check it's actually an image
                if content_type not in _IMAGE_MIME_TYPES:
                    logger.debug(f"Skipping non-image content: {content_type} from {url[:80]}")
                    continue

                data = response.content

                # Skip if too large
                if len(data) > max_size:
                    logger.debug(f"Skipping oversized image: {len(data)} bytes from {url[:80]}")
                    continue

                # Skip tiny images (likely tracking pixels)
                if len(data) < 100:
                    logger.debug(f"Skipping tiny image: {len(data)} bytes from {url[:80]}")
                    continue

                results.append(ImageContent(data=data, mime_type=content_type))
                logger.debug(f"Downloaded linked image: {content_type}, {len(data)} bytes")

            except Exception as e:
                logger.debug(f"Failed to download image from {url[:80]}: {e}")
                continue

    if results:
        logger.info(f"Extracted {len(results)} linked images from HTML body")

    return results
