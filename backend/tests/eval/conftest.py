"""Pytest configuration for LLM evaluation tests."""

import json
from pathlib import Path

import pytest

from .eval_config import EMAILS_DIR, ATTACHMENTS_DIR, THREADS_DIR, EMAIL_CATEGORIES


@pytest.fixture
def eval_fixtures_dir() -> Path:
    """Return the eval fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def eval_emails_dir() -> Path:
    """Return the eval emails directory."""
    return EMAILS_DIR


@pytest.fixture
def eval_attachments_dir() -> Path:
    """Return the eval attachments directory."""
    return ATTACHMENTS_DIR


@pytest.fixture
def eval_threads_dir() -> Path:
    """Return the eval threads directory."""
    return THREADS_DIR


@pytest.fixture
def all_email_categories() -> list[str]:
    """Return list of all email categories."""
    return EMAIL_CATEGORIES


def load_eval_fixture(fixture_path: Path) -> dict:
    """Load a fixture JSON file."""
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def load_fixture():
    """Fixture factory to load test fixtures."""
    return load_eval_fixture


def get_all_email_fixtures() -> list[tuple[str, Path]]:
    """Get all email fixtures for parametrization."""
    fixtures = []
    for category in EMAIL_CATEGORIES:
        category_dir = EMAILS_DIR / category
        if category_dir.exists():
            for fixture_file in sorted(category_dir.glob("*.json")):
                fixture_name = f"{category}/{fixture_file.stem}"
                fixtures.append((fixture_name, fixture_file))
    return fixtures


def get_fixtures_by_category(category: str) -> list[tuple[str, Path]]:
    """Get fixtures for a specific category."""
    fixtures = []
    category_dir = EMAILS_DIR / category
    if category_dir.exists():
        for fixture_file in sorted(category_dir.glob("*.json")):
            fixture_name = f"{category}/{fixture_file.stem}"
            fixtures.append((fixture_name, fixture_file))
    return fixtures


def get_thread_scenarios() -> list[tuple[str, Path]]:
    """Get all thread scenario files."""
    scenarios = []
    if THREADS_DIR.exists():
        for scenario_file in sorted(THREADS_DIR.glob("*.json")):
            scenarios.append((scenario_file.stem, scenario_file))
    return scenarios


# Parametrize helpers for pytest
def pytest_generate_tests(metafunc):
    """Generate test parameters based on fixtures."""
    if "email_fixture" in metafunc.fixturenames:
        fixtures = get_all_email_fixtures()
        metafunc.parametrize(
            "email_fixture",
            [f[1] for f in fixtures],
            ids=[f[0] for f in fixtures],
        )

    if "thread_scenario" in metafunc.fixturenames:
        scenarios = get_thread_scenarios()
        metafunc.parametrize(
            "thread_scenario",
            [s[1] for s in scenarios],
            ids=[s[0] for s in scenarios],
        )
