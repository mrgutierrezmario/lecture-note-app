"""Every HTTP response carries the browser security headers, and the content
policy forbids inline scripts, framing by other sites and plugins."""

from fastapi.testclient import TestClient

import main
from core.security_headers import CSP


def test_headers_on_pages_and_refusals():
    client = TestClient(main.app)
    for path in ("/health", "/api/sessions"):  # public, and refused without login
        r = client.get(path)
        assert r.headers["x-frame-options"] == "SAMEORIGIN"
        assert r.headers["x-content-type-options"] == "nosniff"
        assert "max-age=" in r.headers["strict-transport-security"]
        assert r.headers["content-security-policy"] == CSP
        assert "microphone=(self)" in r.headers["permissions-policy"]


def test_policy_is_strict_where_it_matters():
    script = next(d for d in CSP.split("; ") if d.startswith("script-src"))
    assert "'unsafe-inline'" not in script and "'unsafe-eval'" not in script
    assert "frame-ancestors 'self'" in CSP
    assert "object-src 'none'" in CSP
