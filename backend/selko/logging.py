"""Centralized logging configuration for Selko."""

import logging
import sys


def setup_logging(verbose: bool = False, quiet: bool = False) -> None:
    """Configure logging for the application.

    Args:
        verbose: Show DEBUG level messages.
        quiet: Only show WARNING and above.
    """
    if quiet:
        level = logging.WARNING
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    # The image starts uvicorn directly, which configures only its own loggers.
    # Without this, Python's last-resort handler shows WARNING and above, and
    # every selko.* INFO line (the memory monitor included) was silently
    # dropped in production. force=True: the same level whoever ran first.
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,  # Keep stdout clean for data output
        force=True,
    )

    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.WARNING)
