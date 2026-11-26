"""Selko's own INFO logs reach the container log, and carry no email content."""

from __future__ import annotations

import ast
import logging
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "selko"

# Names that hold what users wrote or received. A log line may name an id,
# never these: the container log lives outside the database and its retention.
CONTENT_NAMES = {"subject", "title", "sender_email", "from_email", "snippet", "body", "body_text", "description", "location"}


def test_importing_the_app_sends_selko_info_to_the_log():
    """The image runs `uvicorn selko.api.app:app`; uvicorn configures only its own
    loggers, so before this every selko.* INFO line was dropped in production."""
    script = (
        "import logging, selko.api.app\n"
        "logging.getLogger('selko.services.memory_monitor').info('probe-line')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True,
        env={"SELKO_JWT_SECRET": "k" * 64, "LLM_FALLBACK_PROVIDER": "none", "PATH": "/usr/bin:/bin"},
    )
    assert "probe-line" in result.stderr, result.stderr[-500:]


def test_setup_logging_is_info_by_default():
    from selko.logging import setup_logging

    setup_logging()
    assert logging.getLogger("selko.anything").getEffectiveLevel() == logging.INFO


def _content_in_log_calls(path: Path) -> list[str]:
    found = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"debug", "info", "warning", "error", "exception"}
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "logger"):
            continue
        for arg in node.args:
            for inner in ast.walk(arg):
                name = inner.id if isinstance(inner, ast.Name) else None
                if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute) and inner.func.attr == "get" \
                        and inner.args and isinstance(inner.args[0], ast.Constant):
                    name = inner.args[0].value
                if name in CONTENT_NAMES:
                    found.append(f"{path.relative_to(PACKAGE)}:{node.lineno} logs {name}")
    return found


def test_no_info_or_debug_line_logs_email_content():
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        found += [f for f in _content_in_log_calls(path)]
    assert not found, found


def test_the_content_check_sees_an_interpolated_subject(tmp_path):
    module = tmp_path / "selko" / "m.py"
    module.parent.mkdir()
    module.write_text("def f(email):\n    logger.info(f\"x {email.get('subject')}\")\n    subject = 1\n    logger.info('%s', subject)\n")
    import tests.test_logging as me

    original = me.PACKAGE
    me.PACKAGE = module.parent
    try:
        assert len(_content_in_log_calls(module)) == 2
    finally:
        me.PACKAGE = original
