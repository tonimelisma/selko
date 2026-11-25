"""The API process serves the built web app (SELKO_WEB_DIR)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    web = tmp_path / "web"
    (web / "_app" / "immutable").mkdir(parents=True)
    (web / "index.html").write_text("<html>SPA</html>")
    (web / "_app" / "immutable" / "a.js").write_text("js")
    (tmp_path / "secret.txt").write_text("secret")
    monkeypatch.setenv("SELKO_WEB_DIR", str(web))
    from selko.api.app import create_app

    return TestClient(create_app())


@pytest.mark.parametrize("path", ["/", "/login", "/register", "/privacy", "/app", "/app/events/123"])
def test_page_paths_get_the_app_shell_uncached(client, path):
    response = client.get(path)
    assert response.status_code == 200 and response.text == "<html>SPA</html>"
    assert response.headers["cache-control"] == "no-cache"


def test_hashed_assets_are_cached_for_good(client):
    response = client.get("/_app/immutable/a.js")
    assert response.text == "js" and "immutable" in response.headers["cache-control"]


@pytest.mark.parametrize("path", ["/_app/../../secret.txt", "/app/%2e%2e/%2e%2e/secret.txt", "/_app/..%2f..%2fsecret.txt"])
def test_nothing_outside_the_web_folder_is_served(client, path):
    assert "secret" not in client.get(path).text


def test_api_paths_are_not_swallowed(client):
    assert client.get("/events/review").status_code == 401  # the API answers, not the shell
