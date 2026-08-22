"""Static guards for the extraction decision envelope.

``commit_email_extraction`` refuses a decision without an intent, but that
refusal only fires once an email is actually processed against a real database.
These guards fail at unit-test speed the moment a new branch is added to
``save_extracted_events`` without saying what it intends, which is the shape of
mistake that produced the original defect: #332 removed the review marker from
one branch and nothing anywhere noticed.
"""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVENTS = ROOT / "backend/selko/services/events.py"
VALID_INTENTS = {"no_change", "apply", "review", "record_only"}


def _decision_dicts() -> list[ast.Dict]:
    """Every dict literal appended to the extraction decisions list."""
    tree = ast.parse(EVENTS.read_text(encoding="utf-8"))
    found: list[ast.Dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "append":
            continue
        if not isinstance(node.func.value, ast.Name) or node.func.value.id != "decisions":
            continue
        assert node.args and isinstance(node.args[0], ast.Dict), (
            f"decisions.append at line {node.lineno} must append a dict literal "
            "so this guard can read it"
        )
        found.append(node.args[0])
    return found


def _literal_keys(node: ast.Dict) -> dict[str, ast.expr]:
    return {
        key.value: value
        for key, value in zip(node.keys, node.values)
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def test_every_extraction_decision_states_an_intent() -> None:
    decisions = _decision_dicts()
    assert decisions, "expected save_extracted_events to build decisions"
    for decision in decisions:
        keys = _literal_keys(decision)
        assert "intent" in keys, (
            f"decision at line {decision.lineno} has no intent; the commit RPC "
            "has no default and will refuse it"
        )
        intent = keys["intent"]
        assert isinstance(intent, ast.Constant) and intent.value in VALID_INTENTS, (
            f"decision at line {decision.lineno} has a non-literal or unknown intent"
        )


def test_decisions_that_change_an_event_state_their_review_status() -> None:
    """Only record_only may omit review_status; nothing else has a default."""
    for decision in _decision_dicts():
        keys = _literal_keys(decision)
        intent = keys["intent"].value
        fields = keys.get("fields")
        if intent == "record_only":
            continue
        assert isinstance(fields, ast.Dict), (
            f"decision at line {decision.lineno} must build fields as a dict literal"
        )
        field_keys = {
            key.value for key in fields.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
        # A ** unpack may supply review_status (e.g. **match.baseline); those
        # branches name it explicitly alongside, so a literal key is required.
        assert "review_status" in field_keys, (
            f"decision at line {decision.lineno} (intent={intent}) must state "
            "review_status explicitly; the commit RPC will refuse it otherwise"
        )


def test_the_dead_replace_pending_proposal_flag_is_gone() -> None:
    """20260826000001 dropped the columns it drove; it had no reader since."""
    assert "replace_pending_proposal" not in EVENTS.read_text(encoding="utf-8")
