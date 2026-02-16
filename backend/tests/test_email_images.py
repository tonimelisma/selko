"""Tests for email HTML image extraction (linked and data URI)."""

import base64
from unittest.mock import MagicMock, patch

import pytest

from selko.services.email_images import (
    _ImageSrcParser,
    _is_tracking_url,
    extract_data_uri_images,
    extract_linked_images,
)
from selko.services.llm_provider import ImageContent


class TestImageSrcParser:
    """Test HTML image URL extraction."""

    def test_extracts_simple_img_src(self):
        """Test extracting src from simple img tags."""
        parser = _ImageSrcParser()
        parser.feed('<html><body><img src="https://example.com/photo.jpg"></body></html>')

        assert len(parser.image_urls) == 1
        assert parser.image_urls[0] == "https://example.com/photo.jpg"

    def test_extracts_multiple_images(self):
        """Test extracting from multiple img tags."""
        parser = _ImageSrcParser()
        parser.feed("""
            <img src="https://example.com/a.jpg">
            <img src="https://example.com/b.png">
        """)

        assert len(parser.image_urls) == 2

    def test_skips_data_uris(self):
        """Test that data: URIs are skipped."""
        parser = _ImageSrcParser()
        parser.feed('<img src="data:image/png;base64,abc123">')

        assert len(parser.image_urls) == 0

    def test_skips_cid_refs(self):
        """Test that cid: references are skipped."""
        parser = _ImageSrcParser()
        parser.feed('<img src="cid:image001.png@01D6B7">')

        assert len(parser.image_urls) == 0

    def test_skips_empty_src(self):
        """Test that empty src is skipped."""
        parser = _ImageSrcParser()
        parser.feed('<img src="">')

        assert len(parser.image_urls) == 0

    def test_skips_tracking_pixels_by_size(self):
        """Test that 1x1 images are skipped."""
        parser = _ImageSrcParser()
        parser.feed('<img src="https://track.example.com/pixel.gif" width="1" height="1">')

        assert len(parser.image_urls) == 0


class TestIsTrackingUrl:
    """Test tracking URL detection."""

    def test_tracking_domains(self):
        """Test detection of tracking pixel domains."""
        assert _is_tracking_url("https://open.tracking.example.com/pixel.gif")
        assert _is_tracking_url("https://pixel.example.com/t.gif")
        assert _is_tracking_url("https://beacon.example.com/b.png")

    def test_normal_urls(self):
        """Test that normal URLs are not flagged as tracking."""
        assert not _is_tracking_url("https://example.com/photo.jpg")
        assert not _is_tracking_url("https://cdn.example.com/image.png")


class TestExtractLinkedImages:
    """Test full linked image extraction pipeline."""

    def test_empty_html_returns_empty(self):
        """Test empty HTML returns no images."""
        result = extract_linked_images("")
        assert result == []

    def test_no_images_returns_empty(self):
        """Test HTML without images returns empty."""
        result = extract_linked_images("<html><body><p>No images here</p></body></html>")
        assert result == []

    def test_skips_relative_urls(self):
        """Test that relative URLs are skipped."""
        result = extract_linked_images('<img src="/images/photo.jpg">')
        assert result == []

    @patch("selko.services.email_images.httpx.Client")
    def test_downloads_valid_images(self, mock_client_class):
        """Test that valid images are downloaded."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "image/jpeg"}
        mock_response.content = b"x" * 1000  # Fake image data
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = extract_linked_images('<img src="https://example.com/photo.jpg">')

        assert len(result) == 1
        assert isinstance(result[0], ImageContent)
        assert result[0].mime_type == "image/jpeg"

    @patch("selko.services.email_images.httpx.Client")
    def test_skips_non_image_content(self, mock_client_class):
        """Test that non-image responses are skipped."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.content = b"<html>not an image</html>"
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = extract_linked_images('<img src="https://example.com/redirect">')

        assert len(result) == 0

    @patch("selko.services.email_images.httpx.Client")
    def test_skips_oversized_images(self, mock_client_class):
        """Test that oversized images are skipped."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "image/jpeg"}
        mock_response.content = b"x" * (6 * 1024 * 1024)  # 6MB
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = extract_linked_images(
            '<img src="https://example.com/huge.jpg">',
            max_size=5 * 1024 * 1024,
        )

        assert len(result) == 0

    @patch("selko.services.email_images.httpx.Client")
    def test_skips_tiny_images(self, mock_client_class):
        """Test that tiny images (tracking pixels) are skipped."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "image/gif"}
        mock_response.content = b"GIF89a"  # 6 bytes — too tiny
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = extract_linked_images('<img src="https://example.com/tiny.gif">')

        assert len(result) == 0

    @patch("selko.services.email_images.httpx.Client")
    def test_max_images_limit(self, mock_client_class):
        """Test that max_images limit is respected."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "image/jpeg"}
        mock_response.content = b"x" * 1000
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        html = "".join(
            f'<img src="https://example.com/img{i}.jpg">' for i in range(20)
        )

        result = extract_linked_images(html, max_images=3)

        assert len(result) == 3

    @patch("selko.services.email_images.httpx.Client")
    def test_deduplicates_urls(self, mock_client_class):
        """Test that duplicate URLs are deduplicated."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "image/jpeg"}
        mock_response.content = b"x" * 1000
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        html = """
            <img src="https://example.com/same.jpg">
            <img src="https://example.com/same.jpg">
            <img src="https://example.com/same.jpg">
        """

        result = extract_linked_images(html)

        # Should only download once
        assert mock_client.get.call_count == 1
        assert len(result) == 1

    @patch("selko.services.email_images.httpx.Client")
    def test_handles_download_errors_gracefully(self, mock_client_class):
        """Test that download errors don't crash the extraction."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = Exception("Connection failed")
        mock_client_class.return_value = mock_client

        result = extract_linked_images('<img src="https://example.com/photo.jpg">')

        assert len(result) == 0


class TestExtractDataUriImages:
    """Test data URI image extraction from HTML."""

    def test_extracts_basic_data_uri(self):
        """Extract a base64 data URI image from HTML."""
        # Create a real base64 image (at least 100 bytes decoded)
        fake_image = b"x" * 200
        b64 = base64.b64encode(fake_image).decode()
        html = f'<img src="data:image/png;base64,{b64}">'

        result = extract_data_uri_images(html)

        assert len(result) == 1
        assert isinstance(result[0], ImageContent)
        assert result[0].mime_type == "image/png"
        assert result[0].data == fake_image

    def test_extracts_multiple_data_uris(self):
        """Extract multiple data URI images."""
        fake_image = b"y" * 200
        b64 = base64.b64encode(fake_image).decode()
        html = (
            f'<img src="data:image/jpeg;base64,{b64}">'
            f'<img src="data:image/png;base64,{b64}">'
        )

        result = extract_data_uri_images(html)

        assert len(result) == 2

    def test_skips_tiny_data_uri(self):
        """Skip data URIs that decode to fewer than 100 bytes."""
        tiny_data = b"tiny"
        b64 = base64.b64encode(tiny_data).decode()
        html = f'<img src="data:image/gif;base64,{b64}">'

        result = extract_data_uri_images(html)

        assert len(result) == 0

    def test_skips_non_image_data_uri(self):
        """Skip data URIs with non-image MIME types."""
        fake_data = b"x" * 200
        b64 = base64.b64encode(fake_data).decode()
        html = f'<img src="data:text/plain;base64,{b64}">'

        result = extract_data_uri_images(html)

        assert len(result) == 0

    def test_empty_html_returns_empty(self):
        """Empty HTML returns no images."""
        result = extract_data_uri_images("")

        assert result == []

    def test_no_data_uris_returns_empty(self):
        """HTML without data URIs returns empty."""
        result = extract_data_uri_images('<img src="https://example.com/photo.jpg">')

        assert result == []

    def test_max_images_limit(self):
        """Respects max_images parameter."""
        fake_image = b"z" * 200
        b64 = base64.b64encode(fake_image).decode()
        html = "".join(
            f'<img src="data:image/png;base64,{b64}">' for _ in range(5)
        )

        result = extract_data_uri_images(html, max_images=2)

        assert len(result) == 2

    def test_handles_single_quoted_src(self):
        """Handle single-quoted src attributes."""
        fake_image = b"x" * 200
        b64 = base64.b64encode(fake_image).decode()
        html = f"<img src='data:image/jpeg;base64,{b64}'>"

        result = extract_data_uri_images(html)

        assert len(result) == 1
