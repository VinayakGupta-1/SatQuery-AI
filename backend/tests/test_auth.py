"""Sign-in: only verified Supabase users reach the analysis endpoints.

Tokens are minted here with a locally generated ES256 key -- the algorithm a
Supabase project signs with -- and the verifier is handed that key in place
of the project's published key set, so nothing reaches the network. The
history service is replaced the same way.
"""

from __future__ import annotations

import io
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.api import history
from app.api.store import task_store
from app.auth import AuthenticationError, reset_verifier
from app.auth.supabase import SupabaseVerifier
from app.config.settings import reset_settings
from app.main import create_app

PROJECT = "https://example-project.supabase.co"
KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())


def token(
    sub: str = "user-a",
    key=KEY,
    issuer: str = f"{PROJECT}/auth/v1",
    audience: str = "authenticated",
    role: str = "authenticated",
    expires_in: int = 3600,
) -> str:
    now = int(time.time())
    claims = {
        "sub": sub, "email": f"{sub}@example.org", "aud": audience, "role": role,
        "iss": issuer, "iat": now, "exp": now + expires_in,
    }
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": "test-key"})


class _Key:
    key = KEY.public_key()


@pytest.fixture
def signed_in(monkeypatch, tmp_path):
    """Sign-in on, the project's key replaced by ours, history in memory."""
    monkeypatch.setenv("SATQUERY_SUPABASE_URL", PROJECT)
    monkeypatch.setenv("SATQUERY_SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")
    monkeypatch.setenv("SATQUERY_STORAGE_ROOT", str(tmp_path / "storage"))
    reset_settings()
    reset_verifier()
    monkeypatch.setattr(
        jwt.PyJWKClient, "get_signing_key_from_jwt", lambda self, raw: _Key()
    )

    stored: dict[str, dict] = {}

    def save(user, response, settings=None):
        stored[response["task_id"]] = {"owner": user.id, "response": response}
        return True

    def fetch(user, task_id, settings=None):
        row = stored.get(task_id)
        return row["response"] if row and row["owner"] == user.id else None

    def recent(user, limit, settings=None):
        return [
            {k: row["response"][k] for k in ("query", "status", "outcome", "answer")}
            | {"id": task_id}
            for task_id, row in stored.items()
            if row["owner"] == user.id
        ][:limit]

    monkeypatch.setattr(history, "save", save)
    monkeypatch.setattr(history, "fetch", fetch)
    monkeypatch.setattr(history, "recent", recent)
    task_store.clear()
    with TestClient(create_app()) as client:
        yield client, stored
    task_store.clear()
    reset_settings()
    reset_verifier()


def bearer(raw: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw}"}


def upload(path: str):
    with open(path, "rb") as handle:
        return [("files", ("scene.tif", io.BytesIO(handle.read()), "image/tiff"))]


# ============================================================
# THE VERIFIER
# ============================================================
@pytest.mark.parametrize(
    "bad, message",
    [
        (lambda: token(key=OTHER_KEY), "not valid"),
        (lambda: token(expires_in=-60), "expired"),
        (lambda: token(issuer="https://another-project.supabase.co/auth/v1"), "not valid"),
        (lambda: token(audience="anon"), "not valid"),
        (lambda: token(role="anon", audience="authenticated"), "does not belong to a user"),
        (lambda: "not-a-jwt", "not valid"),
    ],
)
def test_the_verifier_refuses_anything_but_a_user_token_from_this_project(monkeypatch, bad, message):
    monkeypatch.setattr(jwt.PyJWKClient, "get_signing_key_from_jwt", lambda self, raw: _Key())
    verifier = SupabaseVerifier(PROJECT)
    with pytest.raises(AuthenticationError, match=message):
        verifier.verify(bad())


def test_the_verifier_accepts_a_user_token_from_this_project(monkeypatch):
    monkeypatch.setattr(jwt.PyJWKClient, "get_signing_key_from_jwt", lambda self, raw: _Key())
    user = SupabaseVerifier(PROJECT).verify(token("user-a"))
    assert (user.id, user.email) == ("user-a", "user-a@example.org")


# ============================================================
# THE API
# ============================================================
def test_capabilities_tell_the_workspace_how_to_sign_in(signed_in):
    client, _ = signed_in
    body = client.get("/api/capabilities").json()
    assert body["auth"] == {
        "provider": "supabase",
        "url": PROJECT,
        "publishable_key": "sb_publishable_test",
        "email_verification": True,
    }
    assert client.get("/api/health").status_code == 200  # public


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Basic abc"}, bearer("garbage")])
def test_analysis_needs_a_signed_in_user(signed_in, headers):
    client, _ = signed_in
    response = client.post("/api/tasks", data={"query": "NDVI"}, headers=headers)
    assert response.status_code == 401
    assert client.get("/api/tasks", headers=headers).status_code == 401


def test_a_users_results_are_theirs_alone(signed_in, sentinel2_scene):
    client, stored = signed_in
    response = client.post(
        "/api/tasks", data={"query": "Calculate NDVI"},
        files=upload(sentinel2_scene), headers=bearer(token("user-a")),
    )
    assert response.status_code == 200
    task_id = response.json()["task_id"]
    assert stored[task_id]["owner"] == "user-a"

    mine = client.get(f"/api/tasks/{task_id}", headers=bearer(token("user-a")))
    assert mine.status_code == 200
    # Another user cannot tell the task exists.
    theirs = client.get(f"/api/tasks/{task_id}", headers=bearer(token("user-b")))
    assert theirs.status_code == 404

    listed = client.get("/api/tasks", headers=bearer(token("user-a"))).json()
    assert [entry["task_id"] for entry in listed] == [task_id]
    assert client.get("/api/tasks", headers=bearer(token("user-b"))).json() == []


def test_a_result_outlives_a_restart_through_the_stored_history(signed_in, sentinel2_scene):
    client, _ = signed_in
    task_id = client.post(
        "/api/tasks", data={"query": "Calculate NDVI"},
        files=upload(sentinel2_scene), headers=bearer(token("user-a")),
    ).json()["task_id"]
    task_store.clear()  # what a restart does to the in-memory store

    again = client.get(f"/api/tasks/{task_id}", headers=bearer(token("user-a")))
    assert again.status_code == 200
    assert again.json()["task_id"] == task_id
    assert again.json()["status"] == "success"


def test_progress_is_reported_to_the_user_who_started_the_run(signed_in, sentinel2_scene):
    client, _ = signed_in
    client.post(
        "/api/tasks", data={"query": "Calculate NDVI", "client_ref": "ref-12345678"},
        files=upload(sentinel2_scene), headers=bearer(token("user-a")),
    )
    progress = client.get("/api/progress/ref-12345678", headers=bearer(token("user-a")))
    assert progress.status_code == 200
    assert progress.json()["done"] is True
    other = client.get("/api/progress/ref-12345678", headers=bearer(token("user-b")))
    assert other.status_code == 404


def test_without_supabase_the_api_stays_open(tmp_path, monkeypatch, sentinel2_scene):
    monkeypatch.setenv("SATQUERY_STORAGE_ROOT", str(tmp_path / "storage"))
    reset_settings()
    with TestClient(create_app()) as client:
        assert client.get("/api/capabilities").json()["auth"] is None
        response = client.post(
            "/api/tasks", data={"query": "Calculate NDVI"}, files=upload(sentinel2_scene)
        )
    assert response.status_code == 200
    reset_settings()
