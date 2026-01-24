"""Development server entry point.

Run with: uv run python -m selko.api
"""

import uvicorn

from selko.logging import setup_logging

if __name__ == "__main__":
    # Set up logging for development
    setup_logging(level="INFO")

    # Run uvicorn with auto-reload for development
    uvicorn.run(
        "selko.api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
