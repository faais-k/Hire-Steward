"""Tests for operational hardening, secret redaction, and system observability (Stage 1)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from backend.app.logging_config import RedactingFormatter, correlation_id_ctx
from backend.app.main import create_app


def test_redacting_formatter_masks_secrets_and_pii() -> None:
    formatter = RedactingFormatter("%(message)s")
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="User john.doe@example.com with phone +1-555-123-4567 used key sk-ant-api03-abcdef123456789012345678 and Bearer secrettoken12345678901234567890.",
        args=(),
        exc_info=None,
    )

    formatted = formatter.format(record)

    assert "john.doe@example.com" not in formatted
    assert "[REDACTED_PII]" in formatted
    assert "sk-ant-api03" not in formatted
    assert "secrettoken1234567890" not in formatted
    assert "[REDACTED_SECRET]" in formatted


def test_redacting_formatter_correlation_id() -> None:
    formatter = RedactingFormatter("[%(correlation_id)s] %(message)s")
    token = correlation_id_ctx.set("corr-test-123")
    try:
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Operation performed successfully.",
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)
        assert "[corr-test-123]" in formatted
    finally:
        correlation_id_ctx.reset(token)


def test_correlation_id_middleware_and_system_endpoints() -> None:
    app = create_app()
    client = TestClient(app)

    # 1. Custom correlation ID passed in header
    custom_cid = "client-req-9999"
    resp = client.get("/api/v1/system/status", headers={"X-Correlation-ID": custom_cid})
    assert resp.status_code == 200
    assert resp.headers.get("X-Correlation-ID") == custom_cid

    data = resp.json()
    assert data["loopback_enforced"] is True
    assert "status" in data
    assert "database" in data
    assert "storage" in data
    assert "metrics" in data
    assert "ai_provider" in data
    # Ensure no secret values are exposed in ai_provider
    for key, val in data["ai_provider"].items():
        assert not str(val).startswith("sk-")

    # 2. Generated correlation ID when omitted
    resp2 = client.get("/api/v1/system/activity")
    assert resp2.status_code == 200
    assert "X-Correlation-ID" in resp2.headers
    assert isinstance(resp2.json(), list)
