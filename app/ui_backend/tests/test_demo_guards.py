"""The demo account is shared by every visitor, so anything that ties it to a
person must refuse it. Google Drive is the sharpest case: a Drive linked to the
demo account would hand the next visitor a token for someone else's Drive.

No database here, so this pins the wiring: each route depends on
``forbid_demo`` (which returns 403 for the demo account).
"""

import uuid

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from accounts import auth
from accounts.auth import CurrentUser, forbid_demo, forbid_read_only_demo
from core.config import get_settings
from routes.drive import router as drive_router
from routes.history import router as history_router


def _calls(dependant):
    yield dependant.call
    for sub in dependant.dependencies:
        yield from _calls(sub)


def _route(method, path):
    for r in drive_router.routes:
        if isinstance(r, APIRoute) and r.path == path and method in r.methods:
            return r
    raise AssertionError(f"no route {method} {path}")


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/drive/connect"),
        ("GET", "/api/drive/callback"),
        ("GET", "/api/drive/picker-token"),
        ("PATCH", "/api/drive"),
        ("DELETE", "/api/drive"),
    ],
)
def test_drive_refuses_the_demo_account(method, path):
    assert forbid_demo in set(_calls(_route(method, path).dependant))


def test_drive_status_stays_readable_for_the_demo_account():
    # The History panel reads it to decide what to show; it holds no token.
    assert forbid_demo not in set(_calls(_route("GET", "/api/drive").dependant))


# ── Full access through the tunnel ────────────────────────────────────────────

DEMO = CurrentUser(id=uuid.uuid4(), username="demo", is_admin=False, is_demo=True)
DEMO_FULL = CurrentUser(id=DEMO.id, username="demo", is_admin=False, is_demo=True, demo_full=True)
PERSON = CurrentUser(id=uuid.uuid4(), username="someone", is_admin=False)


def _history_route(method, path):
    for r in history_router.routes:
        if isinstance(r, APIRoute) and r.path == path and method in r.methods:
            return r
    raise AssertionError(f"no route {method} {path}")


def test_demo_never_shares_or_locks_even_with_full_access():
    for method, path in [
        ("PUT", "/api/sessions/{session_id}/shares"),
        ("PUT", "/api/sessions/{session_id}/lock"),
    ]:
        assert forbid_demo in set(_calls(_history_route(method, path).dependant))
    with pytest.raises(HTTPException):
        forbid_demo(DEMO_FULL)


def test_full_access_opens_rename_and_delete():
    for method, path in [
        ("PATCH", "/api/sessions/{session_id}"),
        ("DELETE", "/api/sessions/{session_id}"),
        ("DELETE", "/api/sessions/{session_id}/audio"),
    ]:
        deps = set(_calls(_history_route(method, path).dependant))
        assert forbid_read_only_demo in deps and forbid_demo not in deps


def test_read_only_demo_is_refused_full_demo_and_people_are_not():
    with pytest.raises(HTTPException) as e:
        forbid_read_only_demo(DEMO)
    assert e.value.status_code == 403
    assert forbid_read_only_demo(DEMO_FULL) is DEMO_FULL
    assert forbid_read_only_demo(PERSON) is PERSON


@pytest.fixture
def tunnel_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "demo_full_access_via_tunnel", True)
    monkeypatch.setattr(auth, "_own_address", lambda: "172.20.0.5")


def _scope(client, xff=None, proto=None):
    headers = []
    if xff:
        headers.append((b"x-forwarded-for", xff.encode()))
    if proto:
        headers.append((b"x-forwarded-proto", proto.encode()))
    return {"type": "http", "client": (client, 51000), "scheme": "http", "headers": headers}


def test_tunnel_request_gets_visitor_ip_and_https(tunnel_on):
    scope = _scope("172.20.0.5", xff="203.0.113.7", proto="https")
    assert auth._mark_tunnel_request(scope)
    assert scope["client"][0] == "203.0.113.7"
    assert scope["scheme"] == "https"


def test_funnel_and_lan_requests_are_not_the_tunnel(tunnel_on):
    # Funnel connects over loopback; the LAN port arrives from the Docker gateway.
    for peer in ("127.0.0.1", "172.20.0.1"):
        scope = _scope(peer, xff="172.20.0.5", proto="https")
        assert not auth._mark_tunnel_request(scope)
        assert scope["client"][0] == peer


def test_tunnel_full_access_is_off_by_default(monkeypatch):
    monkeypatch.setattr(get_settings(), "demo_full_access_via_tunnel", False)
    monkeypatch.setattr(auth, "_own_address", lambda: "172.20.0.5")
    assert not auth._mark_tunnel_request(_scope("172.20.0.5", xff="203.0.113.7"))
