"""Unit tests for SubmissionPlan, Simulated ATS adapter, and dry-run execution (Stage 6)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from decimal import Decimal
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.adapters.simulated_ats import SimulatedAtsAdapter
from backend.app.db.models import CompensationAssessment, JobPosting
from backend.app.domain.job_matching import CandidateEvidenceItem, FactType
from backend.app.domain.submission_plan import SubmissionPlan
from backend.app.main import create_app


def local_headers() -> dict[str, str]:
    return {"host": "localhost", "origin": "http://localhost"}


def test_submission_plan_deterministic_hash() -> None:
    plan1 = SubmissionPlan.create(
        plan_id="p1",
        application_id="app1",
        job_posting_id="job1",
        employer_handle="acme",
        target_role="Staff Engineer",
        resume_markdown="# Resume Content",
        cover_letter_markdown="Dear Hiring Team",
        answers=[{"question": "Notice?", "answer": "30 days"}],
    )

    plan2 = SubmissionPlan.create(
        plan_id="p2",
        application_id="app1",
        job_posting_id="job1",
        employer_handle="acme",
        target_role="Staff Engineer",
        resume_markdown="# Resume Content",
        cover_letter_markdown="Dear Hiring Team",
        answers=[{"question": "Notice?", "answer": "30 days"}],
    )

    # Hashes are deterministic and match
    assert plan1.resume_sha256 == plan2.resume_sha256
    assert plan1.cover_letter_sha256 == plan2.cover_letter_sha256
    assert plan1.packet_sha256 == plan2.packet_sha256
    assert plan1.status == "PREPARED"


def test_simulated_ats_adapter_modes() -> None:
    adapter = SimulatedAtsAdapter()
    dummy_packet = {
        "application_id": "app-test",
        "is_compensation_eligible": True,
        "is_cooldown_clear": True,
    }

    # 1. Success
    res_success = adapter.simulate_dispatch(dummy_packet, mode="SUCCESS")
    assert res_success.success is True
    assert res_success.simulated_receipt_id is not None
    assert res_success.simulated_receipt_id.startswith("sim_rec_")

    # 2. Pre-socket abort
    res_abort = adapter.simulate_dispatch(dummy_packet, mode="PRE_SOCKET_ABORT")
    assert res_abort.success is False
    assert res_abort.error_code == "CLIENT_SOCKET_ABORT"

    # 3. Timeout
    res_timeout = adapter.simulate_dispatch(dummy_packet, mode="TIMEOUT")
    assert res_timeout.success is False
    assert res_timeout.error_code == "GATEWAY_TIMEOUT"

    # 4. Duplicate
    res_dup = adapter.simulate_dispatch(dummy_packet, mode="DUPLICATE")
    assert res_dup.success is False
    assert res_dup.error_code == "DUPLICATE_APPLICATION"


def test_submission_plan_and_simulation_api() -> None:
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
    app = create_app(session_factory=factory)

    with TestClient(app, base_url="http://localhost") as client:
        # Seed jobs so postings are available
        seed_res = client.post("/api/v1/jobs/seed-fixtures", headers=local_headers())
        assert seed_res.status_code == 200

        # Track a job to get application_id
        track_res = client.post(
            "/api/v1/applications/track",
            json={"job_posting_id": "syn_py_backend_01", "notes": "Target role"},
            headers=local_headers(),
        )
        assert track_res.status_code == 201
        app_id = track_res.json()["id"]

        # Mark application reviewed with verified tailored materials
        rev_res = client.post(
            f"/api/v1/applications/{app_id}/mark-reviewed",
            json={
                "expected_version": 1,
                "reviewed_resume": "# Candidate\n\nVerified background in systems engineering.",
                "reviewed_cover_letter": "Dear Team,\n\nI am applying for Backend Engineer.",
            },
            headers=local_headers(),
        )
        assert rev_res.status_code == 200

        # Seed verified compensation assessment so policy is satisfied
        with factory() as session:
            posting = session.scalar(
                select(JobPosting).where(JobPosting.posting_id == "syn_py_backend_01").limit(1)
            )
            assess = CompensationAssessment(
                id="assess_test_01",
                job_reference=posting.id,
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
                explanation="Meets annual floor",
            )
            session.add(assess)
            session.commit()

        # 1. POST /applications/{id}/submission-plan
        plan_resp = client.post(
            f"/api/v1/applications/{app_id}/submission-plan",
            headers=local_headers(),
        )
        assert plan_resp.status_code == 200
        plan_data = plan_resp.json()
        assert plan_data["application_id"] == app_id
        assert "packet_sha256" in plan_data
        assert "resume_markdown" in plan_data
        plan_id = plan_data["plan_id"]

        # Explicit candidate approval of the frozen plan
        approve_resp = client.post(
            f"/api/v1/applications/{app_id}/plans/{plan_id}/approve",
            headers=local_headers(),
        )
        assert approve_resp.status_code == 200

        # 2. POST /applications/{id}/simulate-submission (Dry-Run Success)
        idemp_key = "idemp_unit_dryrun_success_01"
        sim_resp = client.post(
            f"/api/v1/applications/{app_id}/simulate-submission",
            json={"mode": "SUCCESS", "idempotency_key": idemp_key},
            headers=local_headers(),
        )
        assert sim_resp.status_code == 200
        sim_data = sim_resp.json()
        assert sim_data["success"] is True
        assert sim_data["is_simulation"] is True
        assert isinstance(sim_data["duration_ms"], int)
        assert sim_data["duration_ms"] >= 0
        assert sim_data["receipt_id"] is not None
        assert sim_data["application_status"] == "READY_FOR_REVIEW"

        # 2b. Idempotent replay: assert contract symmetry and data preservation
        replay_resp = client.post(
            f"/api/v1/applications/{app_id}/simulate-submission",
            json={"mode": "SUCCESS", "idempotency_key": idemp_key},
            headers=local_headers(),
        )
        assert replay_resp.status_code == 200
        replay_data = replay_resp.json()
        assert replay_data["is_idempotent_replay"] is True
        assert isinstance(replay_data["is_simulation"], bool)
        assert replay_data["is_simulation"] is True
        assert isinstance(replay_data["success"], bool)
        assert replay_data["success"] is True
        assert isinstance(replay_data["duration_ms"], int)
        assert replay_data["duration_ms"] >= 0
        assert replay_data["attempt_id"] == sim_data["attempt_id"]
        assert replay_data["receipt_id"] == sim_data["receipt_id"]
        assert replay_data["status"] == sim_data["status"]
        assert replay_data["outcome"] == sim_data["outcome"]
        assert replay_data["duration_ms"] == sim_data["duration_ms"]

        # 3. GET /applications/{id}/handoff
        handoff_resp = client.get(
            f"/api/v1/applications/{app_id}/handoff",
            headers=local_headers(),
        )
        assert handoff_resp.status_code == 200
        handoff_data = handoff_resp.json()
        assert "resume_markdown" in handoff_data
        assert "cover_letter_markdown" in handoff_data
        assert "instructions" in handoff_data


def test_simulate_submission_idempotent_replay() -> None:
    """Regression test asserting that idempotent replay preserves full contract symmetry:

    - 'is_simulation': strictly boolean True
    - 'success': boolean reflecting attempt outcome (True for SUCCESS, False for error modes)
    - 'duration_ms': integer >= 0, reflecting recorded dispatch duration
    - 'is_idempotent_replay': strictly True
    - Identity: attempt_id, receipt_id, plan_sha256 match initial attempt
    - Persistence: does not create duplicate attempt records
    """
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
    app = create_app(session_factory=factory)

    with TestClient(app, base_url="http://localhost") as client:
        # Seed jobs and track application
        client.post("/api/v1/jobs/seed-fixtures", headers=local_headers())
        track_res = client.post(
            "/api/v1/applications/track",
            json={"job_posting_id": "syn_py_backend_01", "notes": "Target role"},
            headers=local_headers(),
        )
        app_id = track_res.json()["id"]

        # Mark reviewed
        client.post(
            f"/api/v1/applications/{app_id}/mark-reviewed",
            json={
                "expected_version": 1,
                "reviewed_resume": "# Candidate\n\nVerified background in systems engineering.",
                "reviewed_cover_letter": "Dear Team,\n\nI am applying for Backend Engineer.",
            },
            headers=local_headers(),
        )

        # Seed compensation assessment
        with factory() as session:
            posting = session.scalar(
                select(JobPosting).where(JobPosting.posting_id == "syn_py_backend_01").limit(1)
            )
            assess = CompensationAssessment(
                id="assess_test_replay_spec",
                job_reference=posting.id,
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
                explanation="Meets annual floor",
            )
            session.add(assess)
            session.commit()

        # Create submission plan
        plan_resp = client.post(f"/api/v1/applications/{app_id}/submission-plan", headers=local_headers())
        assert plan_resp.status_code == 200
        plan_id = plan_resp.json()["plan_id"]

        # Explicit candidate approval of the frozen plan
        approve_resp = client.post(
            f"/api/v1/applications/{app_id}/plans/{plan_id}/approve",
            headers=local_headers(),
        )
        assert approve_resp.status_code == 200

        # -------------------------------------------------------------
        # Scenario 1: Replay of a SUCCESS attempt
        # -------------------------------------------------------------
        success_idemp_key = "idemp_test_replay_success_key"
        resp1 = client.post(
            f"/api/v1/applications/{app_id}/simulate-submission",
            json={"mode": "SUCCESS", "idempotency_key": success_idemp_key},
            headers=local_headers(),
        )
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["success"] is True
        assert data1["is_simulation"] is True
        assert isinstance(data1["duration_ms"], int)
        assert data1["duration_ms"] >= 0

        # First replay
        replay_succ = client.post(
            f"/api/v1/applications/{app_id}/simulate-submission",
            json={"mode": "SUCCESS", "idempotency_key": success_idemp_key},
            headers=local_headers(),
        )
        assert replay_succ.status_code == 200
        replay_succ_data = replay_succ.json()

        # Contract assertion: is_simulation: True, success: bool (True), duration_ms: int
        assert isinstance(replay_succ_data["is_simulation"], bool)
        assert replay_succ_data["is_simulation"] is True
        assert isinstance(replay_succ_data["success"], bool)
        assert replay_succ_data["success"] is True
        assert isinstance(replay_succ_data["duration_ms"], int)
        assert replay_succ_data["duration_ms"] >= 0
        assert replay_succ_data["is_idempotent_replay"] is True

        # Field equality with original attempt
        assert replay_succ_data["attempt_id"] == data1["attempt_id"]
        assert replay_succ_data["receipt_id"] == data1["receipt_id"]
        assert replay_succ_data["status"] == data1["status"]
        assert replay_succ_data["outcome"] == data1["outcome"]
        assert replay_succ_data["duration_ms"] == data1["duration_ms"]

        # -------------------------------------------------------------
        # Scenario 2: Replay of a FAILED attempt (e.g. PRE_SOCKET_ABORT)
        # -------------------------------------------------------------
        fail_idemp_key = "idemp_test_replay_failure_key"
        resp_fail = client.post(
            f"/api/v1/applications/{app_id}/simulate-submission",
            json={"mode": "PRE_SOCKET_ABORT", "idempotency_key": fail_idemp_key},
            headers=local_headers(),
        )
        assert resp_fail.status_code == 200
        data_fail = resp_fail.json()
        assert data_fail["success"] is False
        assert data_fail["is_simulation"] is True

        # Replay failure attempt
        replay_fail = client.post(
            f"/api/v1/applications/{app_id}/simulate-submission",
            json={"mode": "PRE_SOCKET_ABORT", "idempotency_key": fail_idemp_key},
            headers=local_headers(),
        )
        assert replay_fail.status_code == 200
        replay_fail_data = replay_fail.json()

        # Contract assertion: success MUST evaluate to False on replay of a failed attempt
        assert isinstance(replay_fail_data["is_simulation"], bool)
        assert replay_fail_data["is_simulation"] is True
        assert isinstance(replay_fail_data["success"], bool)
        assert replay_fail_data["success"] is False
        assert isinstance(replay_fail_data["duration_ms"], int)
        assert replay_fail_data["duration_ms"] >= 0
        assert replay_fail_data["is_idempotent_replay"] is True
        assert replay_fail_data["attempt_id"] == data_fail["attempt_id"]
        assert replay_fail_data["error_code"] == "CLIENT_SOCKET_ABORT"


def test_candidate_evidence_item_display_label_fallbacks() -> None:
    """Verify CandidateEvidenceItem.display_label handles all key fallbacks and edge cases gracefully."""
    cases = [
        # Skill fallbacks
        (FactType.SKILL.value, {"name": "Python"}, "Python"),
        (FactType.SKILL.value, {"text": "Python data pipelines"}, "Python data pipelines"),
        (FactType.SKILL.value, {"skill": "C++"}, "C++"),
        (FactType.SKILL.value, {"name": None, "text": "Python"}, "Python"),
        (FactType.SKILL.value, {"name": "", "text": "Python"}, "Python"),
        (FactType.SKILL.value, {"name": "   ", "text": "Python"}, "Python"),
        (FactType.SKILL.value, {}, "Skill"),
        (FactType.SKILL.value, {"name": None, "text": None, "skill": None}, "Skill"),
        (FactType.SKILL.value, None, "Skill"),
        # Project fallbacks
        (FactType.PROJECT.value, {"title": "Autonomous Agent"}, "Autonomous Agent"),
        (FactType.PROJECT.value, {"name": "Autonomous Agent"}, "Autonomous Agent"),
        (FactType.PROJECT.value, {"name": None, "title": "Autonomous Agent"}, "Autonomous Agent"),
        (FactType.PROJECT.value, {"name": "", "title": "Autonomous Agent"}, "Autonomous Agent"),
        (FactType.PROJECT.value, {"name": "   ", "title": "Autonomous Agent"}, "Autonomous Agent"),
        (FactType.PROJECT.value, {}, "Project"),
        (FactType.PROJECT.value, {"name": None, "title": None}, "Project"),
        (FactType.PROJECT.value, None, "Project"),
    ]

    for fact_type, val, expected in cases:
        item = CandidateEvidenceItem(
            fact_id=f"test_{fact_type}",
            fact_type=fact_type,
            value=val,  # type: ignore[arg-type]
            verification_state="USER_VERIFIED",
            is_active=True,
            is_conflicted=False,
        )
        assert item.display_label == expected, f"Failed for {fact_type} with value {val}: got {item.display_label}, expected {expected}"
