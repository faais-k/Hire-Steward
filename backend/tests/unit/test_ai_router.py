"""Unit tests for Controlled AI Router, Budget Tracking, and Assistance (Stage 5)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.models import (
    AnswerBankItem,
    CandidateProfile,
    CompensationPreference,
    EmployerSubscription,
    JobPosting,
    JobPostingSnapshot,
    JobSource,
    UserSettingsModel,
)
from backend.app.main import create_app
from backend.app.services import answer_bank as answer_service


def local_headers() -> dict[str, str]:
    return {"host": "localhost", "origin": "http://localhost"}


def test_ai_status_and_question_answering() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    CandidateProfile.__table__.create(engine)
    CompensationPreference.__table__.create(engine)
    AnswerBankItem.__table__.create(engine)
    UserSettingsModel.__table__.create(engine)
    session_factory = sessionmaker(bind=engine)
    session: Session = session_factory()

    # Seed Answer Bank item with explicit reuse consent
    answer_service.create_answer_item(
        session,
        question="What is your notice period?",
        answer="I have an official notice period of 30 days, negotiable to 15 days.",
        category="logistics",
        reuse_consent=True,
    )

    # Seed Candidate Profile
    prof = CandidateProfile(
        id="default",
        name="Alex Mercer",
        headline="Staff Platform Architect",
        summary="Specialist in distributed consensus and local-first AI tooling.",
        skills=[{"name": "Python"}, {"name": "PostgreSQL"}, {"name": "FastAPI"}],
    )
    session.add(prof)
    session.commit()
    session.close()

    app = create_app(session_factory=session_factory)
    client = TestClient(app)

    # 1. GET /api/v1/ai/status
    status_resp = client.get("/api/v1/ai/status", headers=local_headers())
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["active_mode"] == "OFFLINE_MOCK"
    assert status_data["paid_ai_enabled"] is False
    assert status_data["budget_cap_usd"] == 5.0
    assert status_data["remaining_budget_usd"] == 5.0
    for key, val in status_data.items():
        assert not str(val).startswith("sk-")

    # 2. POST /api/v1/ai/answer-question - Match in Answer Bank
    ans_resp1 = client.post(
        "/api/v1/ai/answer-question",
        json={"question": "What is your notice period?"},
        headers=local_headers(),
    )
    assert ans_resp1.status_code == 200
    res1 = ans_resp1.json()
    assert res1["source"] == "ANSWER_BANK"
    assert res1["is_pre_approved"] is True
    assert "30 days" in res1["answer"]

    # 3. POST /api/v1/ai/answer-question - Unmatched, synthesizes grounded profile draft
    ans_resp2 = client.post(
        "/api/v1/ai/answer-question",
        json={"question": "What architectural frameworks have you led?"},
        headers=local_headers(),
    )
    assert ans_resp2.status_code == 200
    res2 = ans_resp2.json()
    assert res2["source"] in {"USER_ENTERED_PROFILE", "CANDIDATE_PROFILE_FACTS"}
    assert res2["is_pre_approved"] is False
    assert "verification_warning" in res2
    assert "Staff Platform Architect" in res2["answer"]


def test_ai_draft_disabled_guardrail() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    CandidateProfile.__table__.create(engine)
    CompensationPreference.__table__.create(engine)
    UserSettingsModel.__table__.create(engine)
    session_factory = sessionmaker(bind=engine)
    session: Session = session_factory()

    prof = CandidateProfile(id="default")
    session.add(prof)
    settings_rec = UserSettingsModel(id="default", ai_provider_mode="DISABLED")
    session.add(settings_rec)
    session.commit()
    session.close()

    app = create_app(session_factory=session_factory)
    client = TestClient(app)

    # When AI is explicitly DISABLED in settings, attempt to generate draft rejects immediately
    resp = client.post(
        "/api/v1/ai/generate-draft",
        json={"job_posting_id": "non_existent_posting"},
        headers=local_headers(),
    )
    assert resp.status_code == 400
    assert "AI_FEATURES_DISABLED" in resp.json()["detail"]
