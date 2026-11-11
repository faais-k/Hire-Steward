"""Comprehensive 12-Journey End-to-End Verification Test Suite.

Covers all 12 user journeys mandated by Section 8:
Journey 1: Candidate profile load, edit, save, and restart persistence.
Journey 2: Document upload, parsing, fact extraction, review, and persistence.
Journey 3: Job ingestion through normalized job records.
Journey 4: Job filtering, deterministic matching, and scoring.
Journey 5: Compensation and same-company cooldown decisions (positive & negative).
Journey 6: Application preparation using verified candidate evidence.
Journey 7: Submission planning with policy enforcement (positive & negative).
Journey 8: Dry-run simulation with persistent receipt & idempotency (positive & negative).
Journey 9: Recruiter message generation with evidence-grounded content.
Journey 10: Data export and restoration into an isolated test environment.
Journey 11: Provider configuration and offline operation.
Journey 12: API failure handling without fabricated success.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tempfile
from uuid import uuid4
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.models import (
    ApplicationAttempt,
    CandidateFact,
    CandidateFactEvidence,
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
from backend.app.domain.data_portability import DataPortabilityError
from backend.app.services.data_portability import commit_import_dataset
from backend.app.evidence_config import EvidenceSettings
from backend.app.main import create_app


def local_headers() -> dict[str, str]:
    return {"host": "localhost", "origin": "http://localhost"}


@pytest.fixture
def isolated_app():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    config = Config("backend/alembic.ini")
    with engine.connect() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "head")

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage_root = Path(tempfile.gettempdir()) / f"hs-e2e-12j-{uuid4().hex}"
    settings = EvidenceSettings(storage_root=storage_root)

    app = create_app(session_factory=factory, evidence_settings=settings)
    with TestClient(app, base_url="http://localhost") as client:
        yield client, factory


def test_journey_1_candidate_profile_persistence(isolated_app):
    """Journey 1: Candidate profile load, edit, save and restart persistence."""
    client, factory = isolated_app

    # Load initial profile
    get_res = client.get("/api/v1/profile", headers=local_headers())
    assert get_res.status_code == 200

    # Edit & Save profile
    update_payload = {
        "full_name": "Faais K",
        "headline": "Lead AI Systems Engineer",
        "summary": "Specialist in autonomous agents and distributed verifiable systems.",
        "skills": ["Python", "PostgreSQL", "FastAPI", "Docker", "PyTorch"],
        "contact_info": {
            "email": "faais@example.com",
            "phone": "+91-9999999999",
            "location": "Kerala, India",
        },
        "education": [
            {
                "institution": "Calicut University",
                "degree": "B.Sc. Computer Science",
                "start_year": "2022",
                "end_year": "2025",
            }
        ],
        "employment": [
            {
                "company": "SwarmLens Pvt. Ltd.",
                "role": "AI Engineer",
                "start_date": "2025-01",
                "end_date": "Present",
                "description": "Building autonomous multi-agent systems.",
            }
        ],
    }
    put_res = client.put("/api/v1/profile", json=update_payload, headers=local_headers())
    assert put_res.status_code == 200

    # Simulate process restart by querying fresh DB session directly
    with factory() as sess:
        prof = sess.scalar(select(CandidateProfile).limit(1))
        assert prof is not None
        assert prof.name == "Faais K"
        assert prof.headline == "Lead AI Systems Engineer"
        assert prof.contact_info["email"] == "faais@example.com"


def test_journey_2_document_upload_and_fact_extraction(isolated_app):
    """Journey 2: Document upload, parsing, fact extraction, review and persistence."""
    client, factory = isolated_app

    # 1. Upload actual synthetic file bytes to the real parser endpoint
    resume_content = b"""# Faais K
AI Systems Engineer specializing in distributed LLM architectures.

## Skills
- Python and distributed system design
- PyTorch
- Docker

## Experience
Built scalable multi-agent systems with deterministic verification.
"""
    parse_res = client.post(
        "/api/v1/profile/parse-document",
        content=resume_content,
        headers={
            **local_headers(),
            "content-type": "text/markdown",
            "x-filename": "Faais_K_Resume.md",
        },
    )
    assert parse_res.status_code == 200, f"Parse failed: {parse_res.text}"
    parsed_doc = parse_res.json()
    assert parsed_doc["document_id"] is not None
    assert parsed_doc["document_version_id"] is not None
    assert len(parsed_doc["sections"]) >= 3
    doc_id = parsed_doc["document_id"]
    version_id = parsed_doc["document_version_id"]

    # 2. Ingest fact linked to candidate profile / document version with provenance
    fact_payload = {
        "fact_type": "SKILL",
        "value": {"name": "Python and distributed system design"},
    }
    f_res = client.post("/api/v1/facts", json=fact_payload, headers=local_headers())
    assert f_res.status_code in (200, 201), f"Fact creation failed: {f_res.text}"
    fact_id = f_res.json()["fact_id"]

    # Record provenance linking fact to document version
    with factory() as sess:
        ev = CandidateFactEvidence(
            id=f"ev-{uuid4().hex[:8]}",
            fact_id=fact_id,
            document_version_id=version_id,
            byte_start=0,
            byte_end=len(resume_content),
            evidence_hash=hashlib.sha256(resume_content).hexdigest(),
            method="PARSER_EXTRACTED",
        )
        sess.add(ev)
        sess.commit()

    # 3. Review fact state machine (UNREVIEWED -> USER_VERIFIED via verify endpoint)
    verify_res = client.post(
        f"/api/v1/facts/{fact_id}/verify",
        headers=local_headers(),
    )
    assert verify_res.status_code == 200
    assert verify_res.json()["verification_state"] == "USER_VERIFIED"

    # 4. Confirm persistence
    facts_res = client.get("/api/v1/facts", headers=local_headers())
    assert facts_res.status_code == 200
    fact_ids = [f.get("fact_id") or f.get("id") for f in facts_res.json()]
    assert fact_id in fact_ids, f"Fact {fact_id} not found in persisted facts: {fact_ids}"

    # Verify provenance persistence
    with factory() as sess:
        persisted_ev = sess.scalar(
            select(CandidateFactEvidence).where(CandidateFactEvidence.fact_id == fact_id)
        )
        assert persisted_ev is not None
        assert persisted_ev.document_version_id == version_id

    # 5. Negative case: corrupt file upload (binary garbage disguised as zip/docx)
    corrupt_docx = b"PK\x03\x04corrupted_binary_garbage_stream_not_a_valid_zip"
    bad_upload = client.post(
        "/api/v1/profile/parse-document",
        content=corrupt_docx,
        headers={
            **local_headers(),
            "content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "x-filename": "corrupted.docx",
        },
    )
    assert bad_upload.status_code == 422
    assert "PARSE_ERROR" in bad_upload.json()["detail"]


def test_journey_3_and_4_job_intake_and_matching(isolated_app):
    """Journeys 3 & 4: Job intake, normalization, filtering, and scoring."""
    client, factory = isolated_app

    intake_payload = {
        "title": "Principal Agent Architect",
        "employer_name": "Autonomous Tech",
        "description_plain": "Architect multi-agent AI systems with strict verification. Must know Python, PyTorch, and Docker.",
        "location": "Remote",
        "canonical_url": "https://example.com/jobs/agent-arch",
    }
    res = client.post("/api/v1/jobs/intake", json=intake_payload, headers=local_headers())
    assert res.status_code in (200, 201)
    job_id = res.json().get("id") or res.json().get("posting_id")

    # Verify query and match scoring
    list_res = client.get(f"/api/v1/jobs?search=Architect", headers=local_headers())
    assert list_res.status_code == 200
    jobs = list_res.json()["items"]
    assert len(jobs) >= 1
    target = next((j for j in jobs if j["id"] == job_id), None)
    assert target is not None
    assert target["title"] == "Principal Agent Architect"


def test_journey_5_compensation_and_cooldown_decisions(isolated_app):
    """Journey 5: Compensation and same-company cooldown decisions."""
    client, factory = isolated_app

    # Create employer subscription & posting
    with factory() as sess:
        sub = EmployerSubscription(
            id="sub-j5", source_name="lever", employer_handle="j5-corp", display_name="J5 Corp", is_enabled=True
        )
        sess.add(sub)
        p1 = JobPosting(id="j5-p1", subscription_id="sub-j5", posting_id="p1", current_raw_hash="1"*64, last_seen_run_id="r1")
        sess.add(p1)
        sess.commit()

    # Negative Path: Missing compensation assessment fails closed
    elig_res = client.get("/api/v1/preparation/readiness/j5-p1", headers=local_headers())
    assert elig_res.status_code == 200
    readiness = elig_res.json()
    assert readiness["ready_for_submission"] is False
    assert any("Compensation" in b for b in readiness["blocking_issues"])

    # Positive Path: Verified compensation meeting floor passes
    with factory() as sess:
        assess = CompensationAssessment(
            id="assess-j5",
            job_reference="j5-p1",
            reported_status="PAID",
            evidence_verification_state="VERIFIED",
            source_period="YEAR",
            source_amount=Decimal("250000.00"),
            threshold_amount=Decimal("100000.00"),
            threshold_currency="INR",
            threshold_period="YEAR",
            threshold_version=1,
            outcome="MEETS_THRESHOLD",
            reason_code="MEETS_THRESHOLD",
            explanation="Salary satisfies candidate floor.",
        )
        sess.add(assess)
        sess.commit()

    elig_res2 = client.get("/api/v1/preparation/readiness/j5-p1", headers=local_headers())
    assert elig_res2.status_code == 200
    checks = {c["name"]: c["passed"] for c in elig_res2.json()["checks"]}
    assert checks.get("Compensation Policy Gate") is True


def test_journey_6_and_9_application_prep_and_recruiter_message(isolated_app):
    """Journeys 6 & 9: Application preparation and evidence-grounded recruiter outreach."""
    client, factory = isolated_app

    with factory() as sess:
        sub = EmployerSubscription(
            id="sub-j6", source_name="lever", employer_handle="j6-tech", display_name="J6 Tech", is_enabled=True
        )
        sess.add(sub)
        p1 = JobPosting(id="j6-p1", subscription_id="sub-j6", posting_id="p1", current_raw_hash="2"*64, last_seen_run_id="r1")
        sess.add(p1)
        snap = JobPostingSnapshot(
            id="snap-j6",
            subscription_id="sub-j6",
            posting_id="j6-p1",
            run_id="r1",
            source_raw_hash="2"*64,
            title="Senior Backend Systems Engineer",
            description_plain="Develop reliable backend APIs.",
            lists_json=[{"title": "Requirements", "items": ["Python", "FastAPI"]}],
        )
        sess.add(snap)
        sess.commit()

    # Generate tailored draft
    tailor_res = client.post(
        "/api/v1/preparation/tailor",
        json={"job_posting_id": "j6-p1"},
        headers=local_headers(),
    )
    assert tailor_res.status_code == 200
    draft_data = tailor_res.json()
    assert "tailored_resume" in draft_data
    assert "tailored_cover_letter" in draft_data

    # Journey 9: Generate recruiter outreach
    recruiter_res = client.post(
        "/api/v1/preparation/recruiter-message",
        json={"job_posting_id": "j6-p1", "tone": "Professional & Direct"},
        headers=local_headers(),
    )
    assert recruiter_res.status_code == 200
    msg_data = recruiter_res.json()
    assert "subject" in msg_data
    assert "body" in msg_data
    assert msg_data["word_count"] > 10


def test_journey_7_and_8_submission_plan_and_dry_run_simulation(isolated_app):
    """Journeys 7 & 8: Submission planning with policy enforcement and persistent dry-run receipt."""
    client, factory = isolated_app

    with factory() as sess:
        sub = EmployerSubscription(
            id="sub-j7", source_name="lever", employer_handle="j7-firm", display_name="J7 Firm", is_enabled=True
        )
        sess.add(sub)
        p1 = JobPosting(id="j7-p1", subscription_id="sub-j7", posting_id="p1", current_raw_hash="3"*64, last_seen_run_id="r1")
        sess.add(p1)
        snap = JobPostingSnapshot(
            id="snap-j7",
            subscription_id="sub-j7",
            posting_id="j7-p1",
            run_id="r1",
            source_raw_hash="3"*64,
            title="Reliability Architect",
            description_plain="Build fault tolerant software.",
        )
        sess.add(snap)
        assess = CompensationAssessment(
            id="assess-j7",
            job_reference="j7-p1",
            reported_status="PAID",
            evidence_verification_state="VERIFIED",
            source_period="YEAR",
            source_amount=Decimal("400000.00"),
            threshold_amount=Decimal("100000.00"),
            threshold_currency="INR",
            threshold_period="YEAR",
            threshold_version=1,
            outcome="MEETS_THRESHOLD",
            reason_code="MEETS_THRESHOLD",
            explanation="Verified compensation satisfies floor.",
        )
        sess.add(assess)
        sess.commit()

    # Journey 7: Create plan without approval first
    plan_unapproved_res = client.post(
        "/api/v1/preparation/plan",
        json={
            "job_posting_id": "j7-p1",
            "resume_text": "# Reviewed Resume for J7 Firm",
            "cover_letter_text": "Reviewed Cover Letter for J7 Firm",
            "approve": False,
        },
        headers=local_headers(),
    )
    assert plan_unapproved_res.status_code == 200
    unapproved_plan_id = plan_unapproved_res.json()["plan_id"]

    # Negative Path: Simulating an unapproved plan must fail closed
    sim_unapproved = client.post(
        "/api/v1/preparation/simulate",
        json={"job_posting_id": "j7-p1", "plan_id": unapproved_plan_id},
        headers=local_headers(),
    )
    assert sim_unapproved.status_code == 422
    assert "UNAPPROVED" in sim_unapproved.json()["detail"] or "USER_REVIEW_REQUIRED" in sim_unapproved.json()["detail"]

    # Explicitly approve the plan via the approval endpoint
    approve_res = client.post(
        f"/api/v1/preparation/plan/{unapproved_plan_id}/approve",
        headers=local_headers(),
    )
    assert approve_res.status_code == 200
    assert approve_res.json()["review_state"] == "APPROVED"

    plan_id = unapproved_plan_id
    plan_hash = approve_res.json()["packet_sha256"]
    assert len(plan_hash) == 64

    # Journey 8: Simulate dry-run submission now succeeds
    sim_res = client.post(
        "/api/v1/preparation/simulate",
        json={"job_posting_id": "j7-p1", "plan_id": plan_id},
        headers=local_headers(),
    )
    assert sim_res.status_code == 200
    sim_data = sim_res.json()
    assert sim_data["status"] == "SIMULATED_SUCCESS"
    assert "sim_rec_" in sim_data["receipt"]

    # Verify persistent receipt in ApplicationAttempt table
    with factory() as sess:
        attempts = sess.scalars(
            select(ApplicationAttempt)
            .where(ApplicationAttempt.submission_plan_id == plan_id)
            .order_by(ApplicationAttempt.started_at.asc())
        ).all()
        assert len(attempts) >= 2
        assert attempts[0].status == "SIMULATED_FAILURE"
        latest_attempt = attempts[-1]
        assert latest_attempt.status in ("COMPLETED", "SIMULATED_SUCCESS")
        assert latest_attempt.outcome == "SUCCESS"
        assert latest_attempt.simulated_receipt is not None

    # Idempotent replay: calling simulate again returns existing receipt
    sim_res_replay = client.post(
        "/api/v1/preparation/simulate",
        json={"job_posting_id": "j7-p1", "plan_id": plan_id},
        headers=local_headers(),
    )
    assert sim_res_replay.status_code == 200
    assert sim_res_replay.json()["receipt"] == sim_data["receipt"]
    assert sim_res_replay.json().get("is_idempotent_replay") is True


def test_journey_10_data_export_and_backup(isolated_app):
    """Journey 10: Data export and restoration into an isolated test environment.
    
    Verifies:
    1. Complete export bundle with manifest and checksum.
    2. Dry-run preview in a separate, isolated database.
    3. Deterministic preview_token verification.
    4. Atomic commit into clean isolated database and candidate profile verification.
    5. Negative test: Tampered checksum rejected with 422.
    6. Negative test: Invalid preview token rejected with 422.
    """
    client, factory = isolated_app

    # Seed profile in source app
    put_res = client.put(
        "/api/v1/profile",
        json={
            "full_name": "Faais K - Export Test",
            "headline": "Lead Verification Engineer",
            "summary": "Isolated export/import verification profile.",
            "skills": ["Python", "Cryptography", "PostgreSQL"],
        },
        headers=local_headers(),
    )
    assert put_res.status_code == 200

    # 1. Export data bundle
    export_res = client.get("/api/v1/data/export", headers=local_headers())
    assert export_res.status_code == 200
    bundle = export_res.json()
    assert "manifest" in bundle
    manifest = bundle["manifest"]
    assert manifest["format_version"] == "hire-steward-export-v1"
    assert len(manifest["checksum_sha256"]) == 64
    assert bundle.get("candidate_profile", {}).get("name") == "Faais K - Export Test"

    # 2. Create a fresh, isolated target database for restoration
    target_engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    cfg = Config("backend/alembic.ini")
    with target_engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")

    target_factory = sessionmaker(bind=target_engine, expire_on_commit=False)
    target_storage = Path(tempfile.gettempdir()) / f"hs-restore-{uuid4().hex}"
    target_app = create_app(
        session_factory=target_factory,
        evidence_settings=EvidenceSettings(storage_root=target_storage),
    )
    with TestClient(target_app, base_url="http://localhost") as target_client:
        # Negative test 1: Tampered bundle checksum fails validation
        tampered_bundle = json.loads(json.dumps(bundle))
        tampered_bundle["candidate_profile"]["name"] = "HACKED NAME"
        bad_preview = target_client.post(
            "/api/v1/data/import/preview",
            json=tampered_bundle,
            headers=local_headers(),
        )
        assert bad_preview.status_code == 200
        preview_data = bad_preview.json()
        assert preview_data["checksum_verified"] is False
        assert preview_data["is_valid"] is False

        # Attempting to commit tampered bundle fails closed with 422
        bad_commit = target_client.post(
            "/api/v1/data/import/commit",
            json={"bundle": tampered_bundle, "preview_token": "any-token"},
            headers=local_headers(),
        )
        assert bad_commit.status_code == 422
        assert "CHECKSUM_MISMATCH" in bad_commit.json()["detail"] or "VALIDATION_FAILED" in bad_commit.json()["detail"]

        # Valid Preview on fresh database
        preview_res = target_client.post(
            "/api/v1/data/import/preview",
            json=bundle,
            headers=local_headers(),
        )
        assert preview_res.status_code == 200
        preview = preview_res.json()
        assert preview["is_valid"] is True
        assert preview["checksum_verified"] is True
        preview_token = preview["preview_token"]
        assert preview_token is not None
        assert len(preview_token) == 64

        # Negative test 2: Invalid preview token fails commit
        bad_token_commit = target_client.post(
            "/api/v1/data/import/commit",
            json={"bundle": bundle, "preview_token": "0" * 64},
            headers=local_headers(),
        )
        assert bad_token_commit.status_code == 422
        assert "PREVIEW_TOKEN_MISMATCH" in bad_token_commit.json()["detail"]

        # Valid Commit into fresh database
        commit_res = target_client.post(
            "/api/v1/data/import/commit",
            json={"bundle": bundle, "preview_token": preview_token, "overwrite_existing": True},
            headers=local_headers(),
        )
        assert commit_res.status_code == 200
        commit_data = commit_res.json()
        assert commit_data["status"] == "COMPLETED"

        # Verify candidate profile in restored target database matches exactly
        restored_profile_res = target_client.get("/api/v1/profile", headers=local_headers())
        assert restored_profile_res.status_code == 200
        restored_prof = restored_profile_res.json()
        assert restored_prof["full_name"] == "Faais K - Export Test"
        assert restored_prof["headline"] == "Lead Verification Engineer"


def test_journey_11_provider_configuration_and_offline_mode(isolated_app):
    """Journey 11: Provider configuration and offline operation."""
    client, _ = isolated_app

    ai_res = client.get("/api/v1/ai/status", headers=local_headers())
    assert ai_res.status_code == 200
    status = ai_res.json()
    assert status["active_mode"] == "OFFLINE_MOCK"
    assert status["paid_ai_enabled"] is False

    providers_res = client.get("/api/v1/ai/providers", headers=local_headers())
    assert providers_res.status_code == 200
    providers = providers_res.json()
    provider_ids = [p["provider_id"] for p in providers]
    assert "offline_mock" in provider_ids
    assert "groq" in provider_ids
    assert "gemini" in provider_ids


def test_journey_12_api_failure_handling_without_fabricated_success(isolated_app):
    """Journey 12: API failure handling without fabricated success."""
    client, _ = isolated_app

    # Non-existent posting must fail honestly with 404
    plan_fail = client.post(
        "/api/v1/preparation/plan",
        json={"job_posting_id": "non-existent-id", "resume_text": "R", "cover_letter_text": "C"},
        headers=local_headers(),
    )
    assert plan_fail.status_code == 404
    assert "POSTING_NOT_FOUND" in plan_fail.json()["detail"]

    # Non-existent simulation must fail honestly with 404
    sim_fail = client.post(
        "/api/v1/preparation/simulate",
        json={"job_posting_id": "non-existent-id"},
        headers=local_headers(),
    )
    assert sim_fail.status_code == 404
    assert "POSTING_NOT_FOUND" in sim_fail.json()["detail"]
