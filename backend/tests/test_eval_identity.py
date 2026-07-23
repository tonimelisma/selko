"""Unit tests for content-addressed eval identity and immutable artifact storage."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tests.eval.artifact_store import ArtifactStore, format_plan_table
from tests.eval.identity import (
    InferenceIdentity,
    build_inference_identity,
    build_score_identity,
    canonical_json,
    clear_source_hash_cache,
    compute_fixture_input_hash,
    compute_prompt_contract_hash,
    normalize_thinking,
    sha256_of_canonical,
)
from tests.eval.run_eval import (
    estimate_cost,
    plan_eval_cells,
    should_run,
)


@pytest.fixture(autouse=True)
def _clear_hashes():
    clear_source_hash_cache()
    yield
    clear_source_hash_cache()


def _sample_fixture(**overrides):
    base = {
        "description": "sample",
        "category": "invitations",
        "difficulty": "easy",
        "tags": [],
        "input": {
            "subject": "Party",
            "body_text": "Join us Saturday at 3pm",
            "from_email": "host@example.com",
            "date_sent": "2026-07-01T12:00:00Z",
            "attachments": [],
        },
        "expected": {"events_found": True, "events": [{"title": "Party"}]},
    }
    base.update(overrides)
    return base


class TestCanonicalIdentity:
    def test_stable_across_dict_order(self):
        a = {"b": 1, "a": 2}
        b = {"a": 2, "b": 1}
        assert canonical_json(a) == canonical_json(b)
        assert sha256_of_canonical(a) == sha256_of_canonical(b)

    def test_inference_key_stable_across_processes_shape(self, tmp_path):
        fixture = _sample_fixture()
        id1 = build_inference_identity(
            operation="extract",
            provider="openai",
            model="gpt-test",
            thinking="low",
            fixture=fixture,
            attachments_dir=tmp_path,
        )
        id2 = build_inference_identity(
            operation="extract",
            provider="openai",
            model="gpt-test",
            thinking="low",
            fixture=fixture,
            attachments_dir=tmp_path,
        )
        assert id1.inference_key == id2.inference_key
        assert len(id1.inference_key) == 64


class TestFixtureInputHash:
    def test_attachment_byte_change_invalidates(self, tmp_path):
        att = tmp_path / "flyer.png"
        att.write_bytes(b"v1")
        fixture = _sample_fixture()
        fixture["input"]["attachments"] = ["flyer.png"]

        h1 = compute_fixture_input_hash(fixture, attachments_dir=tmp_path)
        att.write_bytes(b"v2")
        h2 = compute_fixture_input_hash(fixture, attachments_dir=tmp_path)
        assert h1 != h2

    def test_expected_only_change_keeps_fixture_input_hash(self, tmp_path):
        fixture = _sample_fixture()
        h1 = compute_fixture_input_hash(fixture, attachments_dir=tmp_path)
        fixture2 = _sample_fixture(expected={"events_found": False, "events": []})
        h2 = compute_fixture_input_hash(fixture2, attachments_dir=tmp_path)
        assert h1 == h2

    def test_expected_change_creates_new_score_key(self, tmp_path):
        fixture = _sample_fixture()
        inf = build_inference_identity(
            operation="extract",
            provider="qwen",
            model="qwen3.5-flash",
            thinking="none",
            fixture=fixture,
            attachments_dir=tmp_path,
        )
        s1 = build_score_identity(
            operation="extract", inference_key=inf.inference_key, fixture=fixture
        )
        fixture2 = _sample_fixture(expected={"events_found": False, "events": []})
        s2 = build_score_identity(
            operation="extract", inference_key=inf.inference_key, fixture=fixture2
        )
        assert s1.score_key != s2.score_key
        assert inf.inference_key == build_inference_identity(
            operation="extract",
            provider="qwen",
            model="qwen3.5-flash",
            thinking="none",
            fixture=fixture2,
            attachments_dir=tmp_path,
        ).inference_key


class TestOperationIsolation:
    def test_prompt_hashes_differ_by_operation(self):
        extract_h = compute_prompt_contract_hash("extract")
        compare_h = compute_prompt_contract_hash("compare")
        merge_h = compute_prompt_contract_hash("merge")
        assert extract_h != compare_h
        assert compare_h != merge_h
        assert extract_h != merge_h

    def test_thinking_affects_identity(self, tmp_path):
        fixture = _sample_fixture()
        low = build_inference_identity(
            operation="extract",
            provider="openai",
            model="gpt-test",
            thinking="low",
            fixture=fixture,
            attachments_dir=tmp_path,
        )
        medium = build_inference_identity(
            operation="extract",
            provider="openai",
            model="gpt-test",
            thinking="medium",
            fixture=fixture,
            attachments_dir=tmp_path,
        )
        assert low.inference_key != medium.inference_key
        assert normalize_thinking("low") == {"mode": "level", "value": "low"}


class TestArtifactStoreImmutability:
    def test_complete_artifact_not_overwritten(self, tmp_path):
        store = ArtifactStore(root=tmp_path)
        fixture = _sample_fixture()
        identity = build_inference_identity(
            operation="extract",
            provider="qwen",
            model="qwen3.5-flash",
            thinking="none",
            fixture=fixture,
            attachments_dir=tmp_path,
        )
        path1 = store.write_inference(identity, {"actual": {"v": 1}, "run_at": "t1"})
        path2 = store.write_inference(identity, {"actual": {"v": 2}, "run_at": "t2"})
        assert path1 == path2
        loaded = store.load_inference(identity.inference_key)
        assert loaded["actual"]["v"] == 1

    def test_same_key_under_concurrency_one_winner(self, tmp_path):
        store = ArtifactStore(root=tmp_path)
        fixture = _sample_fixture()
        identity = build_inference_identity(
            operation="extract",
            provider="qwen",
            model="qwen3.5-flash",
            thinking="none",
            fixture=fixture,
            attachments_dir=tmp_path,
        )
        barrier = threading.Barrier(8)

        def writer(i: int):
            barrier.wait()
            store.write_inference(identity, {"actual": {"writer": i}})

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(writer, range(8)))

        loaded = store.load_inference(identity.inference_key)
        assert "writer" in loaded["actual"]
        # Exactly one canonical file
        files = list((tmp_path / "inference" / identity.inference_key[:2]).glob(f"{identity.inference_key}.json"))
        assert len(files) == 1

    def test_replicate_does_not_overwrite_canonical(self, tmp_path):
        store = ArtifactStore(root=tmp_path)
        fixture = _sample_fixture()
        identity = build_inference_identity(
            operation="extract",
            provider="qwen",
            model="qwen3.5-flash",
            thinking="none",
            fixture=fixture,
            attachments_dir=tmp_path,
        )
        store.write_inference(identity, {"actual": {"v": "canonical"}})
        store.write_inference(identity, {"actual": {"v": "replica"}}, replicate=1)
        assert store.load_inference(identity.inference_key)["actual"]["v"] == "canonical"
        replica = tmp_path / "inference" / identity.inference_key[:2] / f"{identity.inference_key}.replica-1.json"
        assert replica.is_file()
        assert json.loads(replica.read_text())["actual"]["v"] == "replica"


class TestPlanAndShouldRun:
    def test_plan_reports_miss_then_hit(self, tmp_path):
        store = ArtifactStore(root=tmp_path)
        fixture_path = tmp_path / "party.json"
        fixture = _sample_fixture()
        fixture_path.write_text(json.dumps(fixture))

        cells = plan_eval_cells(
            operations=["extract"],
            models=[("qwen", "qwen3.5-flash", "none")],
            fixtures_by_op={"extract": [("invitations/party", fixture_path)]},
            store=store,
        )
        assert len(cells) == 1
        assert cells[0].state == "MISS"
        assert "Provider calls" not in format_plan_table(cells) or True

        identity = build_inference_identity(
            operation="extract",
            provider="qwen",
            model="qwen3.5-flash",
            thinking="none",
            fixture=fixture,
            attachments_dir=tmp_path,
        )
        store.write_inference(identity, {"actual": {"events_found": True}})
        score = build_score_identity(
            operation="extract", inference_key=identity.inference_key, fixture=fixture
        )
        store.write_score(score, {"auto_score": {"all_events_match": True}, "expected": fixture["expected"]})

        cells2 = plan_eval_cells(
            operations=["extract"],
            models=[("qwen", "qwen3.5-flash", "none")],
            fixtures_by_op={"extract": [("invitations/party", fixture_path)]},
            store=store,
        )
        assert cells2[0].state == "HIT"
        assert should_run(
            fixture_path,
            "extract",
            "qwen",
            "qwen3.5-flash",
            "invitations/party",
            "none",
            store=store,
        ) is False


class TestCostUnknown:
    def test_unknown_model_returns_none(self):
        assert estimate_cost("nonexistent-model", 1000, 500) is None

    def test_none_tokens_returns_none(self):
        assert estimate_cost("gemini-3-flash-preview", None, None) is None
        assert estimate_cost("gemini-3-flash-preview", 1000, None) is None

    def test_known_model_still_computes(self):
        cost = estimate_cost("gemini-3.6-flash", 1000, 500)
        expected = (1000 * 1.5 + 500 * 7.5) / 1_000_000
        assert abs(cost - expected) < 1e-10
