"""Atomic, content-addressed storage for eval inference and score artifacts."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .eval_config import RESULTS_DIR
from .identity import InferenceIdentity, ScoreIdentity, canonical_json

CellState = Literal["HIT", "MISS", "ERROR", "LEGACY_NON_CACHEABLE"]

INFERENCE_DIRNAME = "inference"
SCORES_DIRNAME = "scores"
MANIFESTS_DIRNAME = "manifests"
REPORTS_DIRNAME = "reports"
LEGACY_DIRNAME = "legacy"

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key_subdir(key: str) -> str:
    return key[:2]


def _get_lock(key: str) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock


@dataclass
class ArtifactStore:
    """Filesystem layout under results/:

    inference/<ab>/<inference_key>.json
    scores/<ab>/<score_key>.json
    manifests/<run_id>.json
    reports/<date>-<slug>.md
    legacy/  (imported historical results; never suppress new calls)
    """

    root: Path = field(default_factory=lambda: RESULTS_DIR)

    @property
    def inference_root(self) -> Path:
        return self.root / INFERENCE_DIRNAME

    @property
    def scores_root(self) -> Path:
        return self.root / SCORES_DIRNAME

    @property
    def manifests_root(self) -> Path:
        return self.root / MANIFESTS_DIRNAME

    @property
    def reports_root(self) -> Path:
        return self.root / REPORTS_DIRNAME

    @property
    def legacy_root(self) -> Path:
        return self.root / LEGACY_DIRNAME

    def inference_path(self, inference_key: str) -> Path:
        return self.inference_root / _key_subdir(inference_key) / f"{inference_key}.json"

    def score_path(self, score_key: str) -> Path:
        return self.scores_root / _key_subdir(score_key) / f"{score_key}.json"

    def manifest_path(self, run_id: str) -> Path:
        return self.manifests_root / f"{run_id}.json"

    def has_inference(self, inference_key: str) -> bool:
        return self.inference_path(inference_key).is_file()

    def has_score(self, score_key: str) -> bool:
        return self.score_path(score_key).is_file()

    def load_inference(self, inference_key: str) -> dict[str, Any] | None:
        path = self.inference_path(inference_key)
        if not path.is_file():
            return None
        return json.loads(path.read_text())

    def load_score(self, score_key: str) -> dict[str, Any] | None:
        path = self.score_path(score_key)
        if not path.is_file():
            return None
        return json.loads(path.read_text())

    def write_inference(
        self,
        identity: InferenceIdentity,
        artifact: dict[str, Any],
        *,
        replicate: int | None = None,
    ) -> Path:
        """Write an inference artifact. Complete keys are immutable.

        ``replicate`` writes a side artifact for intentional nondeterminism
        studies and never overwrites the canonical key.
        """
        key = identity.inference_key
        if replicate is not None:
            # Replica keys are separate files next to the canonical artifact.
            path = (
                self.inference_root
                / _key_subdir(key)
                / f"{key}.replica-{replicate}.json"
            )
            payload = {
                **artifact,
                "identity": identity.to_dict(),
                "inference_key": key,
                "replicate": replicate,
                "stored_at": _utc_now(),
            }
            return self._atomic_write(path, payload)

        path = self.inference_path(key)
        lock = _get_lock(f"inference:{key}")
        with lock:
            if path.is_file():
                # Immutable: existing complete artifact wins; never overwrite.
                return path
            payload = {
                **artifact,
                "identity": identity.to_dict(),
                "inference_key": key,
                "stored_at": _utc_now(),
            }
            return self._atomic_write(path, payload)

    def write_score(
        self,
        identity: ScoreIdentity,
        artifact: dict[str, Any],
    ) -> Path:
        key = identity.score_key
        path = self.score_path(key)
        lock = _get_lock(f"score:{key}")
        with lock:
            if path.is_file():
                return path
            payload = {
                **artifact,
                "identity": identity.to_dict(),
                "score_key": key,
                "stored_at": _utc_now(),
            }
            return self._atomic_write(path, payload)

    def write_manifest(self, run_id: str, manifest: dict[str, Any]) -> Path:
        path = self.manifest_path(run_id)
        payload = {**manifest, "run_id": run_id, "written_at": _utc_now()}
        return self._atomic_write(path, payload)

    def load_manifest(self, run_id: str) -> dict[str, Any] | None:
        path = self.manifest_path(run_id)
        if not path.is_file():
            return None
        return json.loads(path.read_text())

    def _atomic_write(self, path: Path, payload: dict[str, Any]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.stem}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                json.dump(payload, tmp, indent=2, default=str)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return path


@dataclass
class PlannedCell:
    operation: str
    provider: str
    model: str
    thinking: dict[str, Any]
    fixture_name: str
    inference_key: str
    score_key: str
    state: CellState
    reason: str


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def classify_legacy_result(result: dict[str, Any]) -> CellState:
    """Old results lack a full InferenceIdentity — never use them as cache hits."""
    if result.get("identity") and result.get("inference_key"):
        return "HIT"
    return "LEGACY_NON_CACHEABLE"


def build_combined_result(
    *,
    inference: dict[str, Any],
    score: dict[str, Any] | None,
    fixture_name: str,
    operation: str,
    provider: str,
    model: str,
    thinking: str | dict[str, Any],
) -> dict[str, Any]:
    """Merge inference + score into the shape run_eval reporting expects."""
    thinking_value = thinking
    if isinstance(thinking, dict):
        thinking_value = thinking.get("value", thinking)

    combined = {
        "fixture_name": fixture_name,
        "operation": operation,
        "provider": provider,
        "model": model,
        "thinking": thinking_value,
        "inference_key": inference.get("inference_key"),
        "score_key": score.get("score_key") if score else None,
        "identity": inference.get("identity"),
        "cached_inference": inference.get("from_cache", False),
        "run_at": inference.get("run_at") or inference.get("stored_at"),
        "duration_ms": inference.get("duration_ms", 0),
        "timing": inference.get("timing", {}),
        "tokens": inference.get("tokens", {}),
        "cost": inference.get("cost"),
        "actual": inference.get("actual"),
        "trace": inference.get("trace"),
        "expected": score.get("expected") if score else inference.get("expected"),
        "auto_score": score.get("auto_score") if score else None,
        "category": inference.get("category"),
        "description": inference.get("description"),
        "difficulty": inference.get("difficulty"),
        "tags": inference.get("tags", []),
        "input_summary": inference.get("input_summary", {}),
        "fixture_hash": inference.get("fixture_input_hash"),
        "prompt_hash": (inference.get("identity") or {}).get("prompt_contract_hash"),
        "code_hash": inference.get("code_provenance", {}).get(
            "event_processing_sha256", "unknown"
        )[:12]
        if isinstance(inference.get("code_provenance"), dict)
        else inference.get("code_hash", "unknown"),
    }
    return combined


def format_plan_table(cells: list[PlannedCell]) -> str:
    lines = [
        f"{'STATE':8} {'OP':8} {'PROVIDER':12} {'MODEL':28} {'FIXTURE':40} REASON",
        "-" * 120,
    ]
    for cell in cells:
        model = cell.model[:28]
        fixture = cell.fixture_name[:40]
        lines.append(
            f"{cell.state:8} {cell.operation:8} {cell.provider:12} {model:28} "
            f"{fixture:40} {cell.reason}"
        )
    hits = sum(1 for c in cells if c.state == "HIT")
    misses = sum(1 for c in cells if c.state == "MISS")
    errors = sum(1 for c in cells if c.state == "ERROR")
    lines.append("-" * 120)
    lines.append(f"Total {len(cells)}: {hits} HIT, {misses} MISS, {errors} ERROR")
    return "\n".join(lines)


def manifest_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    cells = manifest.get("cells", [])
    counts = {"HIT": 0, "MISS": 0, "ERROR": 0, "LEGACY_NON_CACHEABLE": 0}
    for cell in cells:
        state = cell.get("state", "ERROR")
        counts[state] = counts.get(state, 0) + 1
    return {
        "run_id": manifest.get("run_id"),
        "cell_count": len(cells),
        **counts,
        "provenance": manifest.get("provenance"),
        "matrix": manifest.get("matrix"),
    }


def dump_debug_identity(identity: InferenceIdentity | ScoreIdentity) -> str:
    return canonical_json(asdict(identity))
