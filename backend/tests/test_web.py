"""Tests for serving the built workspace from the analysis service."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config.settings import reset_settings
from app.main import create_app

HTML = {"accept": "text/html,application/xhtml+xml,*/*;q=0.8"}


@pytest.fixture
def dist(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><div id=root></div>")
    (root / "assets" / "index-abc123.js").write_text("console.log(1)")
    (root / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("outside the build")
    return root


def make_client(tmp_path, monkeypatch, dist_dir):
    monkeypatch.setenv("SATQUERY_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("SATQUERY_FRONTEND_DIST", str(dist_dir))
    reset_settings()
    return TestClient(create_app())


@pytest.fixture
def client(tmp_path, monkeypatch, dist):
    with make_client(tmp_path, monkeypatch, dist) as test_client:
        yield test_client
    reset_settings()


def test_the_root_and_app_routes_load_the_workspace(client):
    for path in ("/", "/history", "/help", "/login"):
        response = client.get(path, headers=HTML)
        assert response.status_code == 200, path
        assert "id=root" in response.text
        assert response.headers["cache-control"] == "no-cache"


def test_pages_that_share_a_path_with_the_api_load_the_workspace(client):
    # A reload of /results/<id> or /capabilities must not show raw JSON.
    assert "id=root" in client.get("/results/abc", headers=HTML).text
    assert "id=root" in client.get("/capabilities", headers=HTML).text


def test_api_calls_still_get_json(client):
    assert client.get("/capabilities").headers["content-type"].startswith(
        "application/json"
    )
    response = client.get("/api/capabilities", headers=HTML)
    assert response.headers["content-type"].startswith("application/json")
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/results/missing").status_code == 404


def test_the_api_documentation_is_not_shadowed(client):
    assert "swagger" in client.get("/docs", headers=HTML).text.lower()
    assert client.get("/openapi.json", headers=HTML).json()["info"]["title"] == "SatQuery AI"


def test_build_files_are_served_and_assets_cached(client):
    asset = client.get("/assets/index-abc123.js")
    assert asset.text == "console.log(1)"
    assert "immutable" in asset.headers["cache-control"]
    assert client.get("/favicon.svg").text == "<svg/>"


def test_nothing_outside_the_build_is_served(client):
    response = client.get("/..%2Fsecret.txt", headers=HTML)
    assert "outside the build" not in response.text


def test_without_a_build_only_the_api_is_served(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch, tmp_path / "missing") as test_client:
        assert test_client.get("/", headers=HTML).status_code == 404
        assert test_client.get("/api/health").json()["status"] == "ok"
    reset_settings()
