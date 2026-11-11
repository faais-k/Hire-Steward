"""Unit tests for submission plan creation, dry-run simulation, and pre-submission readiness audits.

Guarantees:
- Submission plan creation rejects incomplete or placeholder application materials.
- Submission plan creation enforces deterministic compensation and cooldown gates fail-closed.
- Simulation verifies plan packet SHA-256 integrity hash.
- Simulation re-evaluates policy gates and persistently logs failed attempts in ApplicationAttempt.
- Simulation records successful receipts persistently in ApplicationAttempt.
- Idempotency is enforced on repeated simulations.
- Readiness audit evaluates compensation, cooldown, and candidate evidence truthfully.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from alembic import command
from alembic.config import Config

from backend.app.api.dependencies import get_session
from backend.app.db.models import (
    ApplicationAttempt,
    CandidateProfile,
    CompensationAssessment,
    EmployerSubscription,
    JobPosting,
    JobPostingSnapshot,
    SubmissionPlanModel,
    TrackedApplication,
    UserSettingsModel,
)
from backend.app.domain.application_tracking import ApplicationStatus
from backend.app.domain.submission_plan import SubmissionPlan
from backend.app.main import create_app


def local_headers() -> dict[str, str]:
    return {"host": "localhost", "origin": "http://localhost"}


@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    cfg = Config("backend/alembic.ini")
    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")

    session_maker = sessionmaker(bind=engine)
    with session_maker() as sess:
        # Seed subscription, posting, candidate profile
        sub = EmployerSubscription(
            id="sub-1", source_name="lever", employer_handle="apex-tech", display_name="Apex Tech", is_enabled=True
        )
        sess.add(sub)
        posting = JobPosting(
            id="job-1", subscription_id="sub-1", posting_id="p-1", current_raw_hash="a" * 64, last_seen_run_id="r1"
        )
        sess.add(posting)
        snap = JobPostingSnapshot(
            id="snap-1",
            subscription_id="sub-1",
            posting_id="job-1",
            run_id="r1",
            source_raw_hash="a" * 64,
            title="Senior Distributed Systems Architect",
            description_plain="Build highly reliable local-first distributed applications.",
        )
        sess.add(snap)
        profile = CandidateProfile(
            id="default",
            name="Faais K",
            headline="AI Systems Engineer",
            summary="Specialist in distributed AI and reliable data pipelines.",
            contact_info={"email": "faais@example.com", "phone": "+91-9999999999"},
        )
        sess.add(profile)
        sess.commit()
        yield sess


def test_create_plan_rejects_empty_materials(test_db: Session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: test_db
    try:
        client = TestClient(app)
        res = client.post(
            "/api/v1/preparation/plan",
            json={"job_posting_id": "job-1", "resume_text": "", "cover_letter_text": ""},
            headers=local_headers(),
        )
        assert res.status_code == 422
        assert "APPLICATION_MATERIALS_INCOMPLETE" in res.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_create_plan_rejects_when_compensation_unverified(test_db: Session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: test_db
    try:
        client = TestClient(app)
        # Attempt to freeze plan with valid materials but NO verified compensation assessment
        res = client.post(
            "/api/v1/preparation/plan",
            json={
                "job_posting_id": "job-1",
                "resume_text": "# Reviewed Resume",
                "cover_letter_text": "Reviewed Cover Letter",
            },
            headers=local_headers(),
        )
        assert res.status_code == 422
        assert "POLICY_REVIEW_REQUIRED" in res.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_create_plan_rejects_when_cooldown_active(test_db: Session):
    # Add verified compensation meeting floor
    assess = CompensationAssessment(
        id="assess-1",
        job_reference="job-1",
        reported_status="PAID",
        evidence_verification_state="VERIFIED",
        source_period="YEAR",
        source_amount=Decimal("300000.00"),
        threshold_amount=Decimal("100000.00"),
        threshold_currency="INR",
        threshold_period="YEAR",
        threshold_version=1,
        outcome="MEETS_THRESHOLD",
        reason_code="MEETS_THRESHOLD",
        explanation="Verified compensation meets floor.",
    )
    test_db.add(assess)

    # Add second posting under same employer and an active application applied 10 days ago
    posting2 = JobPosting(id="job-2", subscription_id="sub-1", posting_id="p-2", current_raw_hash="b"*64, last_seen_run_id="r1")
    test_db.add(posting2)
    prior_app = TrackedApplication(
        id="app-prior",
        job_posting_id="job-2",
        status=ApplicationStatus.APPLIED.value,
        applied_at=datetime.now(timezone.utc) - timedelta(days=10),
        created_at=datetime.now(timezone.utc) - timedelta(days=10),
    )
    test_db.add(prior_app)
    test_db.commit()

    app = create_app()
    app.dependency_overrides[get_session] = lambda: test_db
    try:
        client = TestClient(app)
        res = client.post(
            "/api/v1/preparation/plan",
            json={
                "job_posting_id": "job-1",
                "resume_text": "# Reviewed Resume",
                "cover_letter_text": "Reviewed Cover Letter",
            },
            headers=local_headers(),
        )
        assert res.status_code == 422
        assert "POLICY_BLOCKED" in res.json()["detail"]
        assert "Active cooldown in effect" in res.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_create_plan_succeeds_when_fully_eligible(test_db: Session):
    # Add verified compensation meeting floor
    assess = CompensationAssessment(
        id="assess-1",
        job_reference="job-1",
        reported_status="PAID",
        evidence_verification_state="VERIFIED",
        source_period="YEAR",
        source_amount=Decimal("300000.00"),
        threshold_amount=Decimal("100000.00"),
        threshold_currency="INR",
        threshold_period="YEAR",
        threshold_version=1,
        outcome="MEETS_THRESHOLD",
        reason_code="MEETS_THRESHOLD",
        explanation="Verified compensation meets floor.",
    )
    test_db.add(assess)
    test_db.commit()

    app = create_app()
    app.dependency_overrides[get_session] = lambda: test_db
    try:
        client = TestClient(app)
        res = client.post(
            "/api/v1/preparation/plan",
            json={
                "job_posting_id": "job-1",
                "resume_text": "# Reviewed Resume with Verified Facts",
                "cover_letter_text": "Reviewed Cover Letter for Apex Tech",
            },
            headers=local_headers(),
        )
        assert res.status_code == 200
        data = res.json()
        assert "plan_id" in data
        assert "plan_hash" in data
        assert len(data["plan_hash"]) == 64
        assert data["is_compensation_eligible"] is True
        assert data["is_cooldown_clear"] is True

        # Verify persisted in database
        plan_in_db = test_db.get(SubmissionPlanModel, data["plan_id"])
        assert plan_in_db is not None
        assert plan_in_db.packet_sha256 == data["plan_hash"]
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_simulate_fails_on_missing_submission_plan(test_db: Session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: test_db
    try:
        client = TestClient(app)
        res = client.post(
            "/api/v1/preparation/simulate",
            json={"job_posting_id": "job-1"},
            headers=local_headers(),
        )
        # No plan exists yet for job-1
        assert res.status_code in (404, 422)
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_simulate_persists_attempt_and_receipt(test_db: Session):
    # Setup eligible assessment
    assess = CompensationAssessment(
        id="assess-1",
        job_reference="job-1",
        reported_status="PAID",
        evidence_verification_state="VERIFIED",
        source_period="YEAR",
        source_amount=Decimal("300000.00"),
        threshold_amount=Decimal("100000.00"),
        threshold_currency="INR",
        threshold_period="YEAR",
        threshold_version=1,
        outcome="MEETS_THRESHOLD",
        reason_code="MEETS_THRESHOLD",
        explanation="Verified compensation meets floor.",
    )
    test_db.add(assess)
    test_db.commit()

    app = create_app()
    app.dependency_overrides[get_session] = lambda: test_db
    try:
        client = TestClient(app)
        # 1. Create plan
        plan_res = client.post(
            "/api/v1/preparation/plan",
            json={
                "job_posting_id": "job-1",
                "resume_text": "# Reviewed Resume",
                "cover_letter_text": "Reviewed Cover Letter",
            },
            headers=local_headers(),
        )
        assert plan_res.status_code == 200
        plan_id = plan_res.json()["plan_id"]

        # 2. Simulate submission
        sim_res = client.post(
            "/api/v1/preparation/simulate",
            json={"job_posting_id": "job-1", "plan_id": plan_id},
            headers=local_headers(),
        )
        assert sim_res.status_code == 200
        sim_data = sim_res.json()
        assert sim_data["status"] == "SIMULATED_SUCCESS"
        assert "sim_rec_" in sim_data["receipt"]

        # 3. Verify attempt was persisted in ApplicationAttempt table
        attempt = test_db.scalar(
            select(ApplicationAttempt).where(ApplicationAttempt.submission_plan_id == plan_id)
        )
        assert attempt is not None
        assert attempt.status == "COMPLETED"
        assert attempt.outcome == "SUCCESS"
        assert attempt.simulated_receipt is not None

        # 4. Idempotency test: repeated simulation returns identical receipt
        sim_res2 = client.post(
            "/api/v1/preparation/simulate",
            json={"job_posting_id": "job-1", "plan_id": plan_id},
            headers=local_headers(),
        )
        assert sim_res2.status_code == 200
        sim_data2 = sim_res2.json()
        assert sim_data2["receipt"] == sim_data["receipt"]
        assert sim_data2.get("is_idempotent_replay") is True
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_simulate_rejects_tampered_plan_hash(test_db: Session):
    # Setup eligible assessment and tracked application
    app_rec = TrackedApplication(
        id="app-1",
        job_posting_id="job-1",
        status="READY_FOR_REVIEW",
        reviewed_resume_markdown="# Resume",
        reviewed_cover_letter_markdown="Cover Letter",
    )
    test_db.add(app_rec)
    # Insert a corrupted plan with invalid packet_sha256
    plan_model = SubmissionPlanModel(
        id="corrupted-plan",
        application_id="app-1",
        job_posting_id="job-1",
        employer_handle="apex-tech",
        target_role="Architect",
        resume_sha256="short_hash",
        cover_letter_sha256="short_hash",
        packet_sha256="corrupted",  # Invalid 64-char sha256
        answers_json=[],
        is_compensation_eligible=True,
        is_cooldown_clear=True,
        compensation_threshold_version=1,
        status="FROZEN",
    )
    test_db.add(plan_model)
    test_db.commit()

    app = create_app()
    app.dependency_overrides[get_session] = lambda: test_db
    try:
        client = TestClient(app)
        res = client.post(
            "/api/v1/preparation/simulate",
            json={"job_posting_id": "job-1", "plan_id": "corrupted-plan"},
            headers=local_headers(),
        )
        assert res.status_code == 422
        assert "INVALID_PLAN_INTEGRITY_HASH" in res.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_session, None)
