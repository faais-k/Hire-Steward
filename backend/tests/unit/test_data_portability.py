"""Unit tests for Data Portability, export bundle integrity, preview, and restore (Stage 8)."""

from __future__ import annotations

from pathlib import Path
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.domain.data_portability import (
    EXPORT_FORMAT_VERSION,
    compute_bundle_checksum,
    sanitize_bundle_dictionary,
    validate_import_bundle_manifest,
)
from backend.app.main import create_app
from backend.app.services import answer_bank as answer_service
from backend.app.services import candidate_profile as profile_service


def local_headers() -> dict[str, str]:
    return {"host": "localhost", "origin": "http://localhost"}


def test_sanitize_bundle_dictionary_removes_secrets() -> None:
    raw = {
        "user_profile": {"name": "Alice", "api_key": "secret_12345", "token": "xyz"},
        "nested": [{"auth_token": "abc", "clean_field": "ok", "key": "sk-ant-api03-abcdefghijklmnop"}],
    }
    sanitized = sanitize_bundle_dictionary(raw)
    assert "api_key" not in sanitized["user_profile"]
    assert "token" not in sanitized["user_profile"]
    assert sanitized["user_profile"]["name"] == "Alice"
    assert "auth_token" not in sanitized["nested"][0]
    assert sanitized["nested"][0]["clean_field"] == "ok"


def test_export_preview_commit_roundtrip_api() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    config = Config("backend/alembic.ini")
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session: Session = factory()

    # Seed initial candidate profile & answer bank
    profile_service.update_profile(
        session,
        {
            "name": "Morgan Vance",
            "headline": "Lead Reliability Engineer",
            "summary": "Specialist in high-availability and fault-tolerant architectures.",
            "skills": [{"name": "Python"}, {"name": "Kubernetes"}],
        },
    )
    ans = answer_service.create_answer_item(
        session,
        question="What is your relocation preference?",
        answer="I am open to hybrid roles in Bengaluru or fully remote.",
        category="logistics",
    )
    session.commit()
    session.close()

    app = create_app(session_factory=factory)
    client = TestClient(app, base_url="http://localhost")

    # 1. Export Data
    export_resp = client.post("/api/v1/data/export", headers=local_headers())
    assert export_resp.status_code == 200
    bundle = export_resp.json()
    assert "manifest" in bundle
    assert bundle["manifest"]["format_version"] == EXPORT_FORMAT_VERSION
    assert bundle["candidate_profile"]["name"] == "Morgan Vance"
    assert len(bundle["answer_bank_items"]) >= 1

    # 2. Preview Import
    preview_resp = client.post("/api/v1/data/import/preview", json=bundle, headers=local_headers())
    assert preview_resp.status_code == 200
    preview_data = preview_resp.json()
    assert preview_data["is_valid"] is True
    assert preview_data["checksum_verified"] is True
    assert preview_data["collision_counts"]["candidate_profile"] == 1

    # 3. Modify bundle slightly and Commit to a new fresh engine
    engine2 = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine2.connect() as conn2:
        config.attributes["connection"] = conn2
        command.upgrade(config, "head")

    factory2 = sessionmaker(bind=engine2, expire_on_commit=False)
    app2 = create_app(session_factory=factory2)
    client2 = TestClient(app2, base_url="http://localhost")

    # Commit import into fresh app
    commit_resp = client2.post(
        "/api/v1/data/import/commit",
        json={"bundle": bundle, "overwrite_existing": True},
        headers=local_headers(),
    )
    assert commit_resp.status_code == 200
    commit_data = commit_resp.json()
    assert commit_data["status"] == "COMPLETED"
    assert commit_data["restored_counts"]["candidate_profile"] == 1
    assert commit_data["restored_counts"]["answer_bank_items"] >= 1

    # Verify restored data via GET profile and GET answers
    prof_check = client2.get("/api/v1/profile", headers=local_headers()).json()
    assert prof_check["profile"]["name"] == "Morgan Vance"

    ans_check = client2.get("/api/v1/answers", headers=local_headers()).json()
    assert len(ans_check) >= 1
    assert any("relocation preference" in a["question"].lower() for a in ans_check)


def test_compute_bundle_checksum_cross_language_numeric_normalization() -> None:
    """Verify that integer floats (e.g. 5.0) normalized to ints (5) by browser/JS parsers yield identical checksums."""
    py_payload = {
        "user_settings": {"ai_budget_limit_usd": 5.0, "daily_cap": 8},
        "candidate_profile": {"completeness_score": 0.25},
    }
    js_roundtrip_payload = {
        "user_settings": {"ai_budget_limit_usd": 5, "daily_cap": 8},
        "candidate_profile": {"completeness_score": 0.25},
    }

    py_checksum = compute_bundle_checksum(py_payload)
    js_checksum = compute_bundle_checksum(js_roundtrip_payload)

    assert py_checksum == js_checksum

