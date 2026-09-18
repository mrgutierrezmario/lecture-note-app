"""API smoke tests through FastAPI's TestClient (no database available).

They pin the *shape* of the app: which paths are public, what an unauthenticated
call gets, that the static pages serve, and that /health reports a broken
dependency as 503 rather than pretending to be fine.
"""

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture(scope="module")
def client():
    # raise_server_exceptions=False: /health must *report* failures, not raise.
    with TestClient(main.app, raise_server_exceptions=False) as c:
        yield c


def test_health_reports_degraded_without_database(client):
    r = client.get("/health")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["database"].startswith("error")


def test_health_accepts_head(client):
    assert client.head("/health").status_code in (200, 503)


def test_public_paths_need_no_login(client):
    assert client.get("/api/auth/status").status_code == 200
    assert client.get("/api/auth/status").json()["password_reset_available"] is False


def test_protected_paths_require_login(client):
    for path in ("/api/sessions", "/api/settings", "/api/drive", "/api/auth/me"):
        assert client.get(path).status_code == 401, path


def test_static_pages(client):
    r = client.get("/privacy")
    if r.status_code == 404:
        pytest.skip("frontend not built")
    assert r.status_code == 200 and "Privacy Policy" in r.text
    assert client.get("/guide").status_code == 200
    home = client.get("/")
    assert home.status_code == 200 and "no-cache" in home.headers.get("cache-control", "")
