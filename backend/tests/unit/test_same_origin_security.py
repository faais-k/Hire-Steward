"""Regression tests for same-origin security and loopback protection.

Verifies:
1. require_local_same_origin dependency:
   - Legitimate same-origin mutations succeed.
   - Cross-origin requests (evil.com) fail with 403.
   - Port mismatches fail with 403.
   - Missing origin on protected endpoints fails with 403.
   - Null origin (sandboxed iframe / opaque origin) fails with 403.
   - Malformed origins with userinfo, path, query, or fragment fail with 403.
2. LocalClientOnlyMiddleware:
   - Non-loopback client IPs are blocked with 403.
   - Untrusted external origins are blocked with 403.
   - Allowed loopback client hosts succeed.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from backend.app.api.dependencies import require_local_same_origin
from backend.app.main import LocalClientOnlyMiddleware


def _create_guarded_test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(LocalClientOnlyMiddleware)

    @app.post("/test-mutation", dependencies=[Depends(require_local_same_origin)])
    def test_mutation() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/test-protected-get", dependencies=[Depends(require_local_same_origin)])
    def test_protected_get() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/test-query")
    def test_query() -> dict[str, str]:
        return {"status": "ok"}

    return app


def test_legitimate_same_origin_mutation_succeeds() -> None:
    app = _create_guarded_test_app()
    client = TestClient(app, base_url="http://127.0.0.1:8000")

    resp = client.post(
        "/test-mutation",
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://127.0.0.1:8000",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_cross_origin_write_fails() -> None:
    app = _create_guarded_test_app()
    client = TestClient(app, base_url="http://127.0.0.1:8000")

    resp = client.post(
        "/test-mutation",
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://evil.com",
        },
    )
    assert resp.status_code == 403


def test_port_mismatch_cross_origin_fails() -> None:
    app = _create_guarded_test_app()
    client = TestClient(app, base_url="http://127.0.0.1:8000")

    resp = client.post(
        "/test-mutation",
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://127.0.0.1:3000",
        },
    )
    assert resp.status_code == 403
    assert resp.json() == {"detail": "LOCAL_SAME_ORIGIN_REQUIRED"}


def test_missing_origin_on_protected_endpoint_fails() -> None:
    app = _create_guarded_test_app()
    client = TestClient(app, base_url="http://127.0.0.1:8000")

    # In Starlette TestClient, omitting Origin header
    resp = client.post(
        "/test-mutation",
        headers={
            "Host": "127.0.0.1:8000",
        },
    )
    assert resp.status_code == 403
    assert resp.json() == {"detail": "LOCAL_SAME_ORIGIN_REQUIRED"}


def test_null_origin_fails() -> None:
    app = _create_guarded_test_app()
    client = TestClient(app, base_url="http://127.0.0.1:8000")

    resp = client.post(
        "/test-mutation",
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "null",
        },
    )
    assert resp.status_code == 403


def test_malformed_origin_fails() -> None:
    app = _create_guarded_test_app()
    client = TestClient(app, base_url="http://127.0.0.1:8000")

    # Origin with credentials or paths or queries
    for bad_origin in [
        "http://user:pass@127.0.0.1:8000",
        "http://127.0.0.1:8000/some/path",
        "http://127.0.0.1:8000?query=1",
        "javascript:alert(1)",
        "file:///etc/passwd",
    ]:
        resp = client.post(
            "/test-mutation",
            headers={
                "Host": "127.0.0.1:8000",
                "Origin": bad_origin,
            },
        )
        assert resp.status_code == 403


def test_non_loopback_client_ip_blocked() -> None:
    app = _create_guarded_test_app()
    # Starlette TestClient uses 'testclient' which is in ALLOWED_CLIENT_HOSTS.
    # We can test LocalClientOnlyMiddleware directly via an ASGI scope.
    import asyncio

    received_status = None

    async def fake_send(msg: dict) -> None:
        nonlocal received_status
        if msg["type"] == "http.response.start":
            received_status = msg["status"]

    scope = {
        "type": "http",
        "client": ("192.168.1.100", 54321),
        "headers": [(b"host", b"127.0.0.1:8000")],
    }

    middleware = LocalClientOnlyMiddleware(app)
    asyncio.run(middleware(scope, None, fake_send))
    assert received_status == 403


def test_protected_get_with_same_origin_referer_succeeds() -> None:
    app = _create_guarded_test_app()
    client = TestClient(app, base_url="http://127.0.0.1:8000")

    # Browser GET without Origin, but with valid same-origin Referer
    resp = client.get(
        "/test-protected-get",
        headers={
            "Host": "127.0.0.1:8000",
            "Referer": "http://127.0.0.1:8000/workbench",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_protected_get_with_cross_origin_referer_fails() -> None:
    app = _create_guarded_test_app()
    client = TestClient(app, base_url="http://127.0.0.1:8000")

    # Browser GET with malicious Referer
    resp = client.get(
        "/test-protected-get",
        headers={
            "Host": "127.0.0.1:8000",
            "Referer": "http://evil.com/phishing",
        },
    )
    assert resp.status_code == 403
    assert resp.json() == {"detail": "LOCAL_SAME_ORIGIN_REQUIRED"}

