"""Unit tests for submission plan deterministic policy eligibility and zero-fabrication fallbacks."""

import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from backend.app.db.models import (
    AnswerBankItem,
    CandidateProfile,
    CompensationAssessment,
    CompensationPreference,
    EmployerSubscription,
    JobPosting,
    JobPostingSnapshot,
    TrackedApplication,
    UserSettingsModel,
)
from backend.app.adapters.simulated_ats import SimulatedAtsAdapter
from backend.app.main import create_app
from backend.app.api.dependencies import get_session


from alembic import command
from alembic.config import Config

@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    config = Config("backend/alembic.ini")
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        # Seed subscription and posting
        sub = EmployerSubscription(
            id="sub-1",
            source_name="lever",
            employer_handle="acme-corp",
            display_name="Acme Corp",
            is_enabled=True,
        )
        session.add(sub)
        posting = JobPosting(
            id="job-1",
            subscription_id="sub-1",
            posting_id="p-1",
            current_raw_hash="a" * 64,
            last_seen_run_id="run-1",
        )
        session.add(posting)
        snap = JobPostingSnapshot(
            id="snap-1",
            subscription_id="sub-1",
            posting_id="job-1",
            run_id="run-1",
            source_raw_hash="a" * 64,
            title="Backend Engineer",
            description_plain="Build scalable systems.",
        )
        session.add(snap)
        app_rec = TrackedApplication(
            id="app-1",
            job_posting_id="job-1",
            status="PREPARING",
            reviewed_resume_markdown="# Candidate Resume\n\nSkills: Python, Rust",
            reviewed_cover_letter_markdown="Dear Acme Team,\n\nI am applying for Backend Engineer.",
        )
        session.add(app_rec)
        session.commit()
        yield session


def test_submission_plan_unverified_compensation_is_ineligible(test_db: Session):
    app = create_app()

    def override():
        yield test_db

    app.dependency_overrides[get_session] = override
    try:
        client = TestClient(app)
        res = client.post(
            "/api/v1/applications/app-1/submission-plan",
            headers={"host": "localhost", "origin": "http://localhost"},
        )
        assert res.status_code == 200
        data = res.json()
        # No verified compensation assessment exists -> must fail closed
        assert data["is_compensation_eligible"] is False
        assert data["is_cooldown_clear"] is True
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_submission_plan_verified_compensation_meets_threshold(test_db: Session):
    # Add verified compensation meeting threshold
    assess = CompensationAssessment(
        id="assess-1",
        job_reference="job-1",
        reported_status="PAID",
        evidence_verification_state="VERIFIED",
        source_period="YEAR",
        source_amount=Decimal("150000.00"),
        threshold_amount=Decimal("100000.00"),
        threshold_currency="INR",
        threshold_period="YEAR",
        threshold_version=1,
        outcome="MEETS_THRESHOLD",
        reason_code="EXACT_AMOUNT_MEETS_THRESHOLD",
        explanation="Verified annual compensation meets minimum preference",
    )
    test_db.add(assess)
    test_db.commit()

    app = create_app()

    def override():
        yield test_db

    app.dependency_overrides[get_session] = override
    try:
        client = TestClient(app)
        res = client.post(
            "/api/v1/applications/app-1/submission-plan",
            headers={"host": "localhost", "origin": "http://localhost"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["is_compensation_eligible"] is True
        assert data["is_cooldown_clear"] is True
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_submission_plan_cooldown_blocked_by_recent_application(test_db: Session):
    # Add another job posting under Acme Corp
    posting2 = JobPosting(
        id="job-2",
        subscription_id="sub-1",
        posting_id="p-2",
        current_raw_hash="b" * 64,
        last_seen_run_id="run-1",
    )
    test_db.add(posting2)
    # Add an active application submitted 10 days ago (within 90 day cooldown)
    prior_app = TrackedApplication(
        id="app-prior",
        job_posting_id="job-2",
        status="APPLIED",
        applied_at=datetime.now(timezone.utc) - timedelta(days=10),
    )
    test_db.add(prior_app)
    test_db.commit()

    app = create_app()

    def override():
        yield test_db

    app.dependency_overrides[get_session] = override
    try:
        client = TestClient(app)
        res = client.post(
            "/api/v1/applications/app-1/submission-plan",
            headers={"host": "localhost", "origin": "http://localhost"},
        )
        assert res.status_code == 200
        data = res.json()
        # Cooldown must be flagged as NOT clear
        assert data["is_cooldown_clear"] is False
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_simulated_ats_adapter_blocks_ineligible_packet():
    adapter = SimulatedAtsAdapter()
    ineligible_packet = {
        "is_compensation_eligible": False,
        "is_cooldown_clear": True,
    }
    result = adapter.simulate_dispatch(ineligible_packet)
    assert result.success is False
    assert result.error_code == "INELIGIBLE_COMPENSATION"

    cooldown_packet = {
        "is_compensation_eligible": True,
        "is_cooldown_clear": False,
    }
    result2 = adapter.simulate_dispatch(cooldown_packet)
    assert result2.success is False
    assert result2.error_code == "ACTIVE_COOLDOWN"
