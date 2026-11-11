"""Tests for Application Preparation & Readiness API (Area G / Screen 4).

Verifies:
1. Tailored materials generation grounded in candidate evidence.
2. Submission plan creation and cryptographic content hashing.
3. Offline dry-run ATS simulation receipts.
4. Personalized recruiter outreach generation.
5. Submission readiness audit across compensation floor, cooldown rules, and fact verification states.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import tempfile
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.models import (
    CandidateFact,
    CandidateProfile,
    CompensationPreference,
    EmployerSubscription,
    JobPosting,
    JobPostingSnapshot,
    SubmissionPlanModel,
    TrackedApplication,
    UserSettingsModel,
)
from backend.app.evidence_config import EvidenceSettings
from backend.app.main import create_app


def local_headers() -> dict[str, str]:
    return {"host": "localhost", "origin": "http://localhost"}


@pytest.fixture
def prep_client():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    config = Config("backend/alembic.ini")
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage_root = Path(tempfile.gettempdir()) / "hire-steward-prep-tests" / uuid4().hex
    settings = EvidenceSettings(storage_root=storage_root)

    session: Session = session_factory()

    # Seed Employer & Posting
    sub = EmployerSubscription(
        id="sub_test_01",
        source_name="lever",
        employer_handle="acme-corp",
        display_name="Acme Corporation",
        is_enabled=True,
    )
    session.add(sub)

    posting = JobPosting(
        id="post_test_01",
        subscription_id=sub.id,
        posting_id="acme_sr_py_01",
        current_raw_hash="1" * 64,
        lifecycle_status="ACTIVE",
        last_seen_run_id=str(uuid4()),
    )
    session.add(posting)

    snapshot = JobPostingSnapshot(
        id="snap_test_01",
        subscription_id=sub.id,
        posting_id=posting.id,
        run_id=posting.last_seen_run_id,
        source_raw_hash="1" * 64,
        title="Senior Python Backend Engineer",
        location="Remote",
        description_plain="Build scalable data APIs using Python, FastAPI, and PostgreSQL.",
        lists_json=[
            {
                "title": "Required Skills",
                "items": ["Python", "PostgreSQL", "FastAPI"],
            }
        ],
    )
    session.add(snapshot)

    from decimal import Decimal
    from backend.app.db.models import CompensationAssessment

    # Seed verified compensation assessment to satisfy deterministic policy gate
    comp_assess = CompensationAssessment(
        id="assess_test_01",
        job_reference=posting.id,
        reported_status="PAID",
        evidence_verification_state="VERIFIED",
        source_period="YEAR",
        source_amount=Decimal("200000.00"),
        threshold_amount=Decimal("100000.00"),
        threshold_currency="INR",
        threshold_period="YEAR",
        threshold_version=1,
        outcome="MEETS_THRESHOLD",
        reason_code="MEETS_THRESHOLD",
        explanation="Verified compensation satisfies floor.",
    )
    session.add(comp_assess)

    # Seed Candidate Profile
    profile = CandidateProfile(
        id="default",
        name="Alex Mercer",
        headline="Staff Platform Engineer",
        contact_info={"email": "alex@example.com", "phone": "+15551234567"},
        skills=[{"name": "Python"}, {"name": "PostgreSQL"}, {"name": "FastAPI"}],
    )
    session.add(profile)

    # Seed Candidate Facts
    fact1 = CandidateFact(
        id="fact_py_01",
        fact_type="SKILL",
        value_json={"name": "Python", "years_experience": 6},
        value_hash=hashlib.sha256(b'{"name": "Python", "years_experience": 6}').hexdigest(),
        verification_state="USER_VERIFIED",
    )
    fact2 = CandidateFact(
        id="fact_exp_01",
        fact_type="EMPLOYMENT",
        value_json={"company": "CloudTech", "role": "Senior Engineer", "years": 4},
        value_hash=hashlib.sha256(b'{"company": "CloudTech", "role": "Senior Engineer", "years": 4}').hexdigest(),
        verification_state="USER_VERIFIED",
    )
    session.add_all([fact1, fact2])

    comp = session.get(CompensationPreference, 1)
    if comp:
        comp.amount = 1200000
    else:
        session.add(
            CompensationPreference(
                id=1,
                amount=1200000,
                currency="INR",
                period="YEAR",
                version=1,
            )
        )

    session.commit()
    session.close()

    app = create_app(session_factory=session_factory, evidence_settings=settings)
    with TestClient(app, base_url="http://localhost") as client:
        yield client

    engine.dispose()
    shutil.rmtree(storage_root, ignore_errors=True)


def test_preparation_tailor_flow(prep_client: TestClient) -> None:
    resp = prep_client.post(
        "/api/v1/preparation/tailor",
        json={"job_posting_id": "post_test_01"},
        headers=local_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "tailored_resume" in data
    assert "tailored_cover_letter" in data
    assert data["has_sufficient_evidence"] is True
    assert len(data["addressed_requirements"]) > 0


def test_preparation_plan_flow(prep_client: TestClient) -> None:
    resp = prep_client.post(
        "/api/v1/preparation/plan",
        json={
            "job_posting_id": "post_test_01",
            "resume_text": "Reviewed Resume Markdown",
            "cover_letter_text": "Reviewed Cover Letter Markdown",
        },
        headers=local_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "plan_id" in data
    assert "plan_hash" in data
    assert len(data["plan_hash"]) == 64  # SHA-256


def test_preparation_simulate_flow(prep_client: TestClient) -> None:
    # 1. Create plan first to freeze materials and hashes
    plan_resp = prep_client.post(
        "/api/v1/preparation/plan",
        json={
            "job_posting_id": "post_test_01",
            "resume_text": "Reviewed Resume Markdown",
            "cover_letter_text": "Reviewed Cover Letter Markdown",
        },
        headers=local_headers(),
    )
    assert plan_resp.status_code == 200
    plan_id = plan_resp.json()["plan_id"]

    # 2. Simulate submission with frozen plan
    resp = prep_client.post(
        "/api/v1/preparation/simulate",
        json={"job_posting_id": "post_test_01", "plan_id": plan_id},
        headers=local_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["dry_run"] is True
    assert "receipt" in data
    assert "Simulated ATS Submission Receipt" in data["receipt"]


def test_preparation_recruiter_message_flow(prep_client: TestClient) -> None:
    resp = prep_client.post(
        "/api/v1/preparation/recruiter-message",
        json={"job_posting_id": "post_test_01"},
        headers=local_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "subject" in data
    assert "Alex Mercer" in data["subject"]
    assert "acme-corp" in data["body"]
    assert data["word_count"] > 20


def test_preparation_readiness_flow(prep_client: TestClient) -> None:
    resp = prep_client.get(
        "/api/v1/preparation/readiness/post_test_01",
        headers=local_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready_for_submission"] is True
    assert len(data["blocking_issues"]) == 0
    check_names = [c["name"] for c in data["checks"]]
    assert "Compensation Policy Gate" in check_names
    assert "Employer Cooldown Gate" in check_names
    assert "Evidence Truthfulness Check" in check_names
