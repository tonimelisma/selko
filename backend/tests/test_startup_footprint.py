"""What the server loads at startup is what every deployment pays for in memory.

The heavy client libraries load on first use instead: the Google stack
(~20 MiB), PyMuPDF (~27 MiB) and the LLM SDKs (anthropic ~18, openai ~22,
google-genai ~40 MiB). An Outlook-only deployment that has not yet seen a PDF
never pays for most of them. Measured in the image on 2026-11-26.
"""

from __future__ import annotations

import json
import subprocess
import sys

DEFERRED = (
    "google.oauth2.credentials",
    "google.auth.transport.requests",
    "googleapiclient.discovery",
    "google_auth_oauthlib.flow",
    "fitz",
    "pymupdf",
    "anthropic",
    "openai",
    "google.genai",
)


# Validates: SEL-631
def test_starting_the_app_loads_none_of_the_heavy_clients():
    script = (
        "import json, sys, selko.api.app\n"
        f"print(json.dumps([m for m in {DEFERRED!r} if m in sys.modules]))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True,
        env={"SELKO_JWT_SECRET": "k" * 64, "LLM_FALLBACK_PROVIDER": "none", "PATH": "/usr/bin:/bin"},
    )
    loaded = json.loads(result.stdout.strip().splitlines()[-1])
    assert loaded == [], f"imported at startup: {loaded}"


# Validates: SEL-631
def test_the_deferred_google_names_still_work():
    """The names tests patch stay in place, and calling them imports the real thing."""
    from selko.services import calendars, integrations

    assert callable(calendars.build)
    assert callable(integrations.Flow.from_client_config)
    from google_auth_oauthlib.flow import Flow

    flow = integrations.Flow.from_client_config(
        {"web": {"client_id": "x", "client_secret": "y", "auth_uri": "https://a.test/auth",
                 "token_uri": "https://a.test/token", "redirect_uris": ["https://a.test/cb"]}},
        scopes=["openid"], redirect_uri="https://a.test/cb",
    )
    assert isinstance(flow, Flow)
