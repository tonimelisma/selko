"""Canonical candidate-band fingerprinting for extraction resolution."""

from datetime import datetime, timezone
from hashlib import md5
from typing import Any, Iterable


def canonical_updated_at(value: Any) -> str:
    """Render a database timestamp exactly as the SQL CAS function does."""
    if isinstance(value, datetime):
        timestamp = value
    else:
        raw = str(value).replace("Z", "+00:00")
        timestamp = datetime.fromisoformat(raw)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def candidate_fingerprint(candidates: Iterable[dict[str, Any]]) -> str:
    """Hash ``id:updated_at`` rows in the exact SQL ordering."""
    parts = sorted(
        f"{row['id']}:{canonical_updated_at(row['updated_at'])}"
        for row in candidates
        if row.get("id") is not None and row.get("updated_at") is not None
    )
    return md5(",".join(parts).encode("utf-8"), usedforsecurity=False).hexdigest()
