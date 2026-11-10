"""Unit tests for user settings, search policy, and source registry (Stage 3 & 4)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.models import (
    CandidateProfile,
    CompensationPreference,
    CompensationPreferenceAudit,
    JobSource,
    UserSettingsModel,
)
from backend.app.domain.user_settings import UserSettings
from backend.app.main import create_app
from backend.app.services import user_settings as settings_service


def local_headers() -> dict[str, str]:
    return {"host": "localhost", "origin": "http://localhost"}


def test_user_settings_domain_validation() -> None:
    settings = UserSettings()
    settings.validate()  # Default valid

    # Invalid cooldown
    settings.same_company_cooldown_days = -5
    with pytest.raises(ValueError, match="same_company_cooldown_days"):
        settings.validate()

    settings.same_company_cooldown_days = 90
    settings.daily_application_cap = 0
    with pytest.raises(ValueError, match="daily_application_cap"):
        settings.validate()

    settings.daily_application_cap = 5
    settings.sponsorship_requirement = "invalid_sponsorship"
    with pytest.raises(ValueError, match="sponsorship_requirement"):
        settings.validate()


def test_user_settings_service_and_api() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    CandidateProfile.__table__.create(engine)
    CompensationPreference.__table__.create(engine)
    CompensationPreferenceAudit.__table__.create(engine)
    UserSettingsModel.__table__.create(engine)
    session_factory = sessionmaker(bind=engine)
    session: Session = session_factory()

    # Seed compensation preference singleton
    pref = CompensationPreference(
        id=1,
        amount=150000.0,
        currency="INR",
        period="YEAR",
        version=1,
    )
    session.add(pref)
    session.commit()
    session.close()

    app = create_app(session_factory=session_factory)
    client = TestClient(app)

    # 1. GET /api/v1/settings
    resp = client.get("/api/v1/settings", headers=local_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert "target_roles" in data
    assert "same_company_cooldown_days" in data
    assert data["same_company_cooldown_days"] == 30
    assert data["minimum_compensation"]["currency"] == "INR"

    # 2. PUT /api/v1/settings
    update_payload = {
        "target_roles": ["Principal Architect", "Staff AI Engineer"],
        "same_company_cooldown_days": 60,
        "daily_application_cap": 8,
        "minimum_compensation": {"amount": "200000.00"},
    }
    put_resp = client.put("/api/v1/settings", json=update_payload, headers=local_headers())
    assert put_resp.status_code == 200
    res_data = put_resp.json()
    assert res_data["same_company_cooldown_days"] == 60
    assert res_data["daily_application_cap"] == 8
    assert "Principal Architect" in res_data["target_roles"]


def test_source_registry_endpoints() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    JobSource.__table__.create(engine)
    session_factory = sessionmaker(bind=engine)

    app = create_app(session_factory=session_factory)
    client = TestClient(app)

    # 1. GET /api/v1/sources
    resp = client.get("/api/v1/sources", headers=local_headers())
    assert resp.status_code == 200
    sources = resp.json()
    assert len(sources) >= 5
    source_names = [s["source_name"] for s in sources]
    assert "lever" in source_names
    assert "greenhouse" in source_names
    assert "manual" in source_names
    assert "fixtures" in source_names

    # Check that live fetching is disabled by default for all sources
    for s in sources:
        assert s["live_fetching_enabled"] is False
        assert s["is_read_only"] is True

    # 2. Attempting to enable lever without prior terms review must fail with 400
    fail_patch = client.patch(
        "/api/v1/sources/lever",
        json={"is_enabled": True},
        headers=local_headers(),
    )
    assert fail_patch.status_code == 400
    assert "TERMS_REVIEW_REQUIRED" in fail_patch.json()["detail"]

    # 3. Explicit terms review updates capability_status to VERIFIED_READ_ONLY first
    review_patch = client.patch(
        "/api/v1/sources/lever",
        json={"capability_status": "VERIFIED_READ_ONLY"},
        headers=local_headers(),
    )
    assert review_patch.status_code == 200

    # 4. Now enabling lever succeeds
    patch_resp = client.patch(
        "/api/v1/sources/lever",
        json={"is_enabled": True, "rate_limit_requests_per_minute": 15},
        headers=local_headers(),
    )
    assert patch_resp.status_code == 200
    patched = patch_resp.json()
    assert patched["is_enabled"] is True
    assert patched["capability_status"] == "VERIFIED_READ_ONLY"
    assert patched["rate_limit_requests_per_minute"] == 15
