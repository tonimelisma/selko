"""Safety checks for the Tier 2 staging verifier."""

import subprocess
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts" / "verify.sh"


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
