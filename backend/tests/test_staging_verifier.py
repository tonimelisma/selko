"""Safety checks for the Tier 2 staging verifier."""

import subprocess
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts" / "verify.sh"
STAGING_SCRIPT = SCRIPT.parent / "verify-staging.sh"


def test_staging_mode_refuses_without_explicit_staging_environment():
    result = subprocess.run(
        ["bash", str(SCRIPT), "staging"],
        capture_output=True,
        text=True,
        timeout=10,
        env={"PATH": "/usr/bin:/bin:/opt/homebrew/bin"},
    )

    assert result.returncode == 1
    assert "ENVIRONMENT=staging" in result.stderr


def test_staging_verifier_waits_for_exact_revision_and_requires_workers():
    source = STAGING_SCRIPT.read_text()
    assert "STAGING_EXPECTED_SHA" in source
    assert "build_sha == $expected_sha" in source
    assert 'STAGING_REQUIRE_WORKERS:-1' in source
    assert "state-ownership-acceptance-drill" in source
