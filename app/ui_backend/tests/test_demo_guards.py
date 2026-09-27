"""The demo account is shared by every visitor, so anything that ties it to a
person must refuse it. Google Drive is the sharpest case: a Drive linked to the
demo account would hand the next visitor a token for someone else's Drive.

No database here, so this pins the wiring: each route depends on
``forbid_demo`` (which returns 403 for the demo account).
"""

import pytest
from fastapi.routing import APIRoute

from accounts.auth import forbid_demo
from routes.drive import router as drive_router


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
