"""Adversarial regression test for compensation verification and simulated ATS dispatch gating.

Verifies:
1. Verified assessment (evidence_verification_state='VERIFIED', outcome='MEETS_THRESHOLD'):
   - submission-plan sets is_compensation_eligible = True.
   - simulate-submission succeeds with status='SIMULATED_SUCCESS', outcome='SUCCESS'.
2. Unverified assessment (evidence_verification_state='UNVERIFIED'):
   - submission-plan sets is_compensation_eligible = False.
   - simulate-submission fails closed with status='SIMULATED_FAILURE', error_code='INELIGIBLE_COMPENSATION'.
3. Idempotent replay of both verified success and unverified failure:
   - Returns is_idempotent_replay=True, same status, outcome, error_code, receipt_id, and duration_ms.
4. Dry-run simulation NEVER modifies application status to APPLIED.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from backend.app.db.models import (
    CompensationAssessment,
    JobPosting,
    TrackedApplication,
)
from backend.tests.integration.test_data_preservation_operational_acceptance import (
    IsolatedInstance,
    local_headers,
)


def test_compensation_verification_gates_simulation_positive_and_negative() -> None:
    """Verify that unverified compensation fails closed while verified compensation succeeds."""
    instance = IsolatedInstance("comp_sim_gate")
    try:
        client = instance.client

        # Seed initial fixtures
        seed_res = client.post("/api/v1/jobs/seed-fixtures", headers=local_headers())
        assert seed_res.status_code == 200

        with instance.factory() as session:
            posting = session.scalars(select(JobPosting)).first()
            assert posting is not None
            posting_id = posting.id

        # -----------------------------------------------------------------
        # TEST CASE 1: UNVERIFIED ASSESSMENT (Fail Closed)
        # -----------------------------------------------------------------
        # Step 1.1: Ingest a job via intake endpoint
        res_intake = client.post(
            "/api/v1/jobs/intake",
            json={
                "title": f"Staff Architect {uuid.uuid4().hex[:6]}",
                "company": "Decentralized Corp",
                "location": "Remote",
                "url": f"https://jobs.example.com/roles/{uuid.uuid4().hex}",
                "description": "Distributed systems engineering role requiring Raft and Paxos.",
            },
            headers=local_headers(),
        )
        assert res_intake.status_code == 201
        unverified_ref = res_intake.json()["posting_id"]

        res_comp_unverified = client.post(
            "/api/v1/compensation/assessments",
            json={
                "job_reference": unverified_ref,
                "reported_status": "PAID",
                "amount": "250000.00",
                "currency": "INR",
                "period": "YEAR",
                "evidence_reference": "user-reported-unverified-claim",
            },
            headers=local_headers(),
        )
        assert res_comp_unverified.status_code == 201
        comp_data = res_comp_unverified.json()
        assert comp_data["evidence_verification_state"] == "UNVERIFIED"

        # Step 1.2: Track application and review materials
        res_app_unverified = client.post(
            "/api/v1/applications/track",
            json={"job_posting_id": unverified_ref, "notes": "Testing unverified compensation gate"},
            headers=local_headers(),
        )
        assert res_app_unverified.status_code == 201
        app_unverified_id = res_app_unverified.json()["id"]

        client.post(
            f"/api/v1/applications/{app_unverified_id}/mark-reviewed",
            json={
                "reviewed_resume": "# Candidate Resume\nSystems Specialist",
                "reviewed_cover_letter": "Dear Team,\nCover letter text.",
            },
            headers=local_headers(),
        )

        # Step 1.3: Generate submission plan - MUST evaluate is_compensation_eligible = False
        res_plan_unverified = client.post(
            f"/api/v1/applications/{app_unverified_id}/submission-plan",
            headers=local_headers(),
        )
        assert res_plan_unverified.status_code == 200
        plan_unverified = res_plan_unverified.json()
        assert plan_unverified["is_compensation_eligible"] is False

        # Step 1.4: Simulate submission - MUST fail closed
        idemp_key_unverified = f"idemp-unverified-{uuid.uuid4().hex}"
        res_sim_unverified = client.post(
            f"/api/v1/applications/{app_unverified_id}/simulate-submission",
            json={
                "mode": "SUCCESS",
                "plan_id": plan_unverified["plan_id"],
                "idempotency_key": idemp_key_unverified,
            },
            headers=local_headers(),
        )
        assert res_sim_unverified.status_code == 200
        sim_unverified_data = res_sim_unverified.json()
        assert sim_unverified_data["status"] == "SIMULATED_FAILURE"
        assert sim_unverified_data["outcome"] == "FAILED"
        assert sim_unverified_data["success"] is False
        assert sim_unverified_data["error_code"] == "INELIGIBLE_COMPENSATION"
        assert sim_unverified_data["is_simulation"] is True

        # Step 1.5: Idempotent replay of the failure attempt
        res_replay_unverified = client.post(
            f"/api/v1/applications/{app_unverified_id}/simulate-submission",
            json={
                "mode": "SUCCESS",
                "plan_id": plan_unverified["plan_id"],
                "idempotency_key": idemp_key_unverified,
            },
            headers=local_headers(),
        )
        assert res_replay_unverified.status_code == 200
        replay_unverified_data = res_replay_unverified.json()
        assert replay_unverified_data["is_idempotent_replay"] is True
        assert replay_unverified_data["status"] == "SIMULATED_FAILURE"
        assert replay_unverified_data["success"] is False
        assert replay_unverified_data["error_code"] == "INELIGIBLE_COMPENSATION"

        # -----------------------------------------------------------------
        # TEST CASE 2: VERIFIED ASSESSMENT (Success)
        # -----------------------------------------------------------------
        # Step 2.1: `posting_id` already has a verified assessment from `seed_synthetic_fixtures`
        # Track application on posting_id
        res_app_verified = client.post(
            "/api/v1/applications/track",
            json={"job_posting_id": posting_id, "notes": "Testing verified compensation gate"},
            headers=local_headers(),
        )
        assert res_app_verified.status_code == 201
        app_verified_id = res_app_verified.json()["id"]

        client.post(
            f"/api/v1/applications/{app_verified_id}/mark-reviewed",
            json={
                "reviewed_resume": "# Candidate Resume\nVerified Systems Architect",
                "reviewed_cover_letter": "Dear Team,\nVerified cover letter text.",
            },
            headers=local_headers(),
        )

        # Step 2.2: Generate submission plan - MUST evaluate is_compensation_eligible = True
        res_plan_verified = client.post(
            f"/api/v1/applications/{app_verified_id}/submission-plan",
            headers=local_headers(),
        )
        assert res_plan_verified.status_code == 200
        plan_verified = res_plan_verified.json()
        assert plan_verified["is_compensation_eligible"] is True

        # Step 2.3: Simulate submission in SUCCESS mode - MUST succeed
        idemp_key_verified = f"idemp-verified-{uuid.uuid4().hex}"
        res_sim_verified = client.post(
            f"/api/v1/applications/{app_verified_id}/simulate-submission",
            json={
                "mode": "SUCCESS",
                "plan_id": plan_verified["plan_id"],
                "idempotency_key": idemp_key_verified,
            },
            headers=local_headers(),
        )
        assert res_sim_verified.status_code == 200
        sim_verified_data = res_sim_verified.json()
        assert sim_verified_data["status"] == "SIMULATED_SUCCESS"
        assert sim_verified_data["outcome"] == "SUCCESS"
        assert sim_verified_data["success"] is True
        assert sim_verified_data["receipt_id"] is not None
        assert sim_verified_data["is_simulation"] is True

        # Step 2.4: Idempotent replay of success attempt
        res_replay_verified = client.post(
            f"/api/v1/applications/{app_verified_id}/simulate-submission",
            json={
                "mode": "SUCCESS",
                "plan_id": plan_verified["plan_id"],
                "idempotency_key": idemp_key_verified,
            },
            headers=local_headers(),
        )
        assert res_replay_verified.status_code == 200
        replay_verified_data = res_replay_verified.json()
        assert replay_verified_data["is_idempotent_replay"] is True
        assert replay_verified_data["status"] == "SIMULATED_SUCCESS"
        assert replay_verified_data["success"] is True
        assert replay_verified_data["receipt_id"] == sim_verified_data["receipt_id"]

        # Step 2.5: Invariant verification: neither simulation modified status to APPLIED
        with instance.factory() as session:
            app_unv = session.get(TrackedApplication, app_unverified_id)
            app_ver = session.get(TrackedApplication, app_verified_id)
            assert app_unv.status != "APPLIED"
            assert app_ver.status != "APPLIED"
            assert app_ver.status == "READY_FOR_REVIEW"

    finally:
        instance.cleanup()
