"""Strict format whitelisting and conversion for LLM providers.

Implements a two-tier whitelist approach:
1. INGESTIBLE_FORMATS: formats our system knows how to handle
2. PROVIDER_ACCEPTED_FORMATS: formats each LLM API is documented to accept

Attachments outside the ingestible list are discarded. Those within the list
but not accepted by the target provider are converted (PDF → page images,
HEIC/BMP/TIFF → PNG).
"""

import io
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Whitelist 1: Formats our system can ingest (we know how to handle these)
# ---------------------------------------------------------------------------

INGESTIBLE_FORMATS = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/bmp",
    "image/tiff",
    "image/heic",
    "application/pdf",
}

# Formats that always need conversion (never sent directly to any LLM)
ALWAYS_CONVERT = {"image/bmp", "image/tiff", "image/heic"}


# ---------------------------------------------------------------------------
# Whitelist 2: Formats each LLM API is documented to accept
# ---------------------------------------------------------------------------

PROVIDER_ACCEPTED_FORMATS: dict[str, set[str]] = {
    "gemini": {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"},
    "moonshot": {"image/png", "image/jpeg", "image/gif", "image/webp"},
    "zai": {"image/png", "image/jpeg", "image/gif", "image/webp"},
    "qwen": {"image/png", "image/jpeg", "image/gif", "image/webp"},
    "deepseek": set(),   # text-only
    "minimax": set(),    # text-only
    "openai": {"image/png", "image/jpeg", "image/gif", "image/webp"},
    "anthropic": {"image/png", "image/jpeg", "image/gif", "image/webp"},
}


@dataclass
class ConvertedContent:
    """A single piece of converted content ready for LLM."""
    data: bytes
    mime_type: str


# ---------------------------------------------------------------------------
# PDF handling
# ---------------------------------------------------------------------------

def get_pdf_page_count(data: bytes) -> int:
    """Get the number of pages in a PDF without rendering.

    Args:
        data: Raw PDF bytes.

    Returns:
        Number of pages, or 0 if the PDF can't be read.
    """
    try:
        import fitz  # pymupdf

        doc = fitz.open(stream=data, filetype="pdf")
        count = len(doc)
        doc.close()
        return count
    except Exception as e:
        logger.warning(f"Failed to count PDF pages: {e}")
        return 0


def pdf_to_images(
    data: bytes,
    max_pages: int = 10,
    dpi: int = 150,
) -> list[ConvertedContent]:
    """Render PDF pages as PNG images.

    Args:
        data: Raw PDF bytes.
        max_pages: Maximum pages to render (0 = all).
        dpi: Resolution for rendering.

    Returns:
        List of ConvertedContent with PNG data for each page.
    """
    try:
        import fitz  # pymupdf

        doc = fitz.open(stream=data, filetype="pdf")
        total_pages = len(doc)
        pages_to_render = min(total_pages, max_pages) if max_pages > 0 else total_pages
        results = []

        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)

        for page_num in range(pages_to_render):
            page = doc[page_num]
            pix = page.get_pixmap(matrix=matrix)
            png_data = pix.tobytes("png")
            results.append(ConvertedContent(data=png_data, mime_type="image/png"))
            logger.debug(
                f"Rendered PDF page {page_num + 1}/{pages_to_render} "
                f"({len(png_data)} bytes)"
            )

        doc.close()

        if total_pages > pages_to_render:
            logger.info(
                f"PDF has {total_pages} pages, rendered first {pages_to_render}"
            )

        return results

    except Exception as e:
        logger.warning(f"Failed to render PDF to images: {e}")
        return []


# ---------------------------------------------------------------------------
# Image conversion
# ---------------------------------------------------------------------------

def convert_image_to_png(data: bytes) -> Optional[ConvertedContent]:
    """Convert any Pillow-readable image to PNG.

    Handles HEIC (via pillow-heif), BMP, TIFF, and other formats.

    Args:
        data: Raw image bytes.

    Returns:
        ConvertedContent with PNG data, or None on failure.
    """
    try:
        from PIL import Image

        # Register HEIF/HEIC support if available
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            pass  # pillow-heif not installed, HEIC won't work

        img = Image.open(io.BytesIO(data))

        # Convert to RGB if needed (e.g., CMYK, palette modes)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")

        output = io.BytesIO()
        img.save(output, format="PNG")
        png_data = output.getvalue()

        logger.debug(
            f"Converted image ({img.size[0]}x{img.size[1]}) to PNG "
            f"({len(png_data)} bytes)"
        )
        return ConvertedContent(data=png_data, mime_type="image/png")

    except Exception as e:
        logger.warning(f"Failed to convert image to PNG: {e}")
        return None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def prepare_content_for_provider(
    data: bytes,
    mime_type: str,
    provider_name: str,
    max_pdf_pages: int = 10,
) -> list[ConvertedContent]:
    """Prepare attachment content for a specific LLM provider.

    Implements the decision flow:
    1. Is the mime type ingestible? NO → discard
    2. Is this a text-only provider? YES → discard
    3. Is the format already accepted? YES → pass through
    4. Can we convert? YES → convert; NO → discard

    Args:
        data: Raw attachment bytes.
        mime_type: MIME type of the attachment.
        provider_name: LLM provider name (e.g., "gemini", "moonshot").
        max_pdf_pages: Maximum PDF pages to render.

    Returns:
        List of ConvertedContent (0 = discarded, >1 for multi-page PDF).
    """
    # Step 1: Is the mime type in our ingestible whitelist?
    if mime_type not in INGESTIBLE_FORMATS:
        logger.warning(
            f"Unknown format {mime_type}, skipping (not in ingestible whitelist)"
        )
        return []

    # Step 2: Is this a text-only LLM?
    accepted = PROVIDER_ACCEPTED_FORMATS.get(provider_name, set())
    if not accepted:
        logger.info(
            f"Visual content skipped for text-only provider {provider_name}"
        )
        return []

    # Step 3: Is the format already accepted AND not in always-convert?
    if mime_type in accepted and mime_type not in ALWAYS_CONVERT:
        return [ConvertedContent(data=data, mime_type=mime_type)]

    # Step 4: Convert
    if mime_type == "application/pdf":
        # For PDFs: check page count, then render to images
        page_count = get_pdf_page_count(data)
        if page_count == 0:
            logger.warning("PDF appears empty or unreadable, skipping")
            return []
        if max_pdf_pages > 0 and page_count > max_pdf_pages:
            logger.warning(
                f"PDF has {page_count} pages (limit: {max_pdf_pages}), "
                f"rendering first {max_pdf_pages} only"
            )
        return pdf_to_images(data, max_pages=max_pdf_pages)

    elif mime_type in {"image/heic", "image/bmp", "image/tiff"}:
        result = convert_image_to_png(data)
        return [result] if result else []

    elif mime_type in {"image/gif", "image/webp"}:
        # These are in INGESTIBLE but might not be accepted by the provider
        if mime_type not in accepted:
            result = convert_image_to_png(data)
            return [result] if result else []
        return [ConvertedContent(data=data, mime_type=mime_type)]

    # Shouldn't reach here, but safety fallback
    logger.warning(f"Cannot convert {mime_type} to accepted format, skipping")
    return []
