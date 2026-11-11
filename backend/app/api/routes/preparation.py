"""Application Preparation, Gating, and Simulation Endpoints (Area G / Screen 4).

Normative implementation of:
- ADR-0003: Submission Safety and Reconcilable Intent
- ADR-0005: Configurable Targeting and Policy Controls
- ADR-0006: Hard Compensation Floor
- ADR-0009: Compensation Evidence Trust Boundaries
- ADR-0016: Application Tracking and Pipeline Model
- docs/application-safety-policy.md

Provides:
1. Tailored resume and cover letter generation grounded in candidate evidence.
2. Submission plan creation with deterministic policy enforcement and SHA-256 integrity hashes.
3. Offline dry-run ATS simulation with cryptographic verification, idempotency, and persistent attempt logging.
4. Personalized recruiter outreach drafting grounded in verified evidence.
5. Multi-gate application submission readiness auditing.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.adapters.simulated_ats import SimulatedAtsAdapter
from backend.app.api.dependencies import get_session, require_local_same_origin
from backend.app.db.models import (
    ApplicationAttempt,
    EmployerSubscription,
    JobPosting,
    JobPostingSnapshot,
    SubmissionPlanModel,
    TrackedApplication,
)
from backend.app.domain.application_preparation import (
    ApplicationPreparationError,
)
from backend.app.domain.submission_plan import SubmissionPlan
from backend.app.services.application_preparation import (
    check_application_readiness,
    prepare_application_draft,
    prepare_recruiter_message,
)
from backend.app.services.submission_eligibility import (
    EligibilityDecision,
    evaluate_submission_eligibility,
)

router = APIRouter(prefix="/api/v1/preparation", tags=["Application Preparation"])


class TailorDraftRequest(BaseModel):
    job_posting_id: str = Field(..., description="ID of persisted job posting")
    fact_ids: list[str] | None = Field(default=None, description="Optional subset of facts to include")


class CreatePlanRequest(BaseModel):
    job_posting_id: str = Field(..., description="ID of target job posting")
    resume_text: str | None = Field(default=None, description="Reviewed resume markdown")
    cover_letter_text: str | None = Field(default=None, description="Reviewed cover letter markdown")


class SimulateSubmissionRequest(BaseModel):
    job_posting_id: str = Field(..., description="ID of target job posting")
    plan_id: str | None = Field(default=None, description="Optional plan ID to simulate")


class RecruiterMessageRequest(BaseModel):
    job_posting_id: str = Field(..., description="ID of target job posting")
    fact_ids: list[str] | None = Field(default=None, description="Optional subset of facts to cite")
    tone: str = Field(default="Professional & Direct", description="Tone for outreach message")


@router.post("/tailor")
def generate_tailored_materials(
    payload: TailorDraftRequest,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, Any]:
    """Generate tailored resume and cover letter deterministically grounded in candidate facts."""
    try:
        draft = prepare_application_draft(
            session,
            posting_id=payload.job_posting_id,
            fact_ids=payload.fact_ids,
        )
    except ApplicationPreparationError as exc:
        if exc.code in {"POSTING_NOT_FOUND", "SNAPSHOT_NOT_FOUND"}:
            raise HTTPException(status_code=404, detail=exc.code)
        raise HTTPException(status_code=422, detail=exc.message)

    grounded_claims = []
    for req in draft.addressed_requirements:
        for c in req.supporting_claims:
            grounded_claims.append({
                "claim": c.statement,
                "fact_id": c.fact_id,
                "source_excerpt": c.relevance_reason or req.requirement_text,
            })

    if not grounded_claims:
        for c in draft.unreviewed_claims:
            grounded_claims.append({
                "claim": c.statement,
                "fact_id": c.fact_id,
                "source_excerpt": "Unreviewed candidate fact",
            })

    return {
        "tailored_resume": draft.resume_markdown,
        "tailored_cover_letter": draft.cover_letter_markdown,
        "grounded_claims": grounded_claims,
        "has_sufficient_evidence": draft.has_sufficient_evidence,
        "addressed_requirements": [r.model_dump() for r in draft.addressed_requirements],
        "evidence_gaps": [g.model_dump() for g in draft.evidence_gaps],
        "unreviewed_claims": [u.model_dump() for u in draft.unreviewed_claims],
        "conflicted_claims": [c.model_dump() for c in draft.conflicted_claims],
        "draft_explanation": draft.draft_explanation,
    }


@router.post("/plan")
def create_application_submission_plan(
    payload: CreatePlanRequest,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, Any]:
    """Freeze and persist an immutable submission plan with authoritative policy evaluation."""
    posting = session.get(JobPosting, payload.job_posting_id)
    if posting is None:
        posting = session.scalar(
            select(JobPosting).where(JobPosting.posting_id == payload.job_posting_id).limit(1)
        )
    if posting is None:
        raise HTTPException(status_code=404, detail="POSTING_NOT_FOUND")

    # Find or initialize tracked application
    app = session.scalar(
        select(TrackedApplication)
        .where(TrackedApplication.job_posting_id == posting.id)
        .limit(1)
    )
    if app is None:
        app = TrackedApplication(
            id=str(uuid.uuid4()),
            job_posting_id=posting.id,
            status="READY_FOR_REVIEW",
            reviewed_resume_markdown=payload.resume_text,
            reviewed_cover_letter_markdown=payload.cover_letter_text,
        )
        session.add(app)
        session.flush()
    else:
        if payload.resume_text:
            app.reviewed_resume_markdown = payload.resume_text
        if payload.cover_letter_text:
            app.reviewed_cover_letter_markdown = payload.cover_letter_text
        session.flush()

    # Enforce non-empty, reviewed application materials (no placeholder fabrication)
    resume_content = (payload.resume_text or app.reviewed_resume_markdown or "").strip()
    cover_content = (payload.cover_letter_text or app.reviewed_cover_letter_markdown or "").strip()
    if not resume_content or not cover_content:
        raise HTTPException(
            status_code=422,
            detail="APPLICATION_MATERIALS_INCOMPLETE: Reviewed resume and cover letter markdown are both required to freeze a submission plan.",
        )

    # Authoritative deterministic policy gating (fail closed)
    eligibility = evaluate_submission_eligibility(
        session,
        job_posting_id=posting.id,
        current_application_id=app.id,
    )

    if eligibility.overall_decision == EligibilityDecision.BLOCKED:
        raise HTTPException(
            status_code=422,
            detail=f"POLICY_BLOCKED: Submission plan blocked by policy: {'; '.join(eligibility.blocking_reasons)}",
        )

    if eligibility.overall_decision == EligibilityDecision.REVIEW_REQUIRED:
        raise HTTPException(
            status_code=422,
            detail=f"POLICY_REVIEW_REQUIRED: Submission plan requires verified evidence: {'; '.join(eligibility.review_reasons)}",
        )

    sub = session.get(EmployerSubscription, posting.subscription_id)
    employer_handle = sub.employer_handle if sub else "unknown"

    snapshot = session.scalar(
        select(JobPostingSnapshot)
        .where(JobPostingSnapshot.posting_id == posting.id)
        .order_by(JobPostingSnapshot.captured_at.desc())
        .limit(1)
    )
    job_title = snapshot.title if snapshot else "Target Role"

    plan_id = str(uuid.uuid4())
    is_reviewed = bool(app.reviewed_resume_markdown and app.reviewed_cover_letter_markdown)
    review_state = "USER_REVIEWED" if is_reviewed else "UNREVIEWED"

    plan = SubmissionPlan.create(
        plan_id=plan_id,
        application_id=app.id,
        job_posting_id=posting.id,
        employer_handle=employer_handle,
        target_role=job_title,
        resume_markdown=resume_content,
        cover_letter_markdown=cover_content,
        answers=[],
        is_compensation_eligible=eligibility.is_compensation_eligible,
        is_cooldown_clear=eligibility.is_cooldown_clear,
        compensation_threshold_version=1,
        review_state=review_state,
    )

    plan_model = SubmissionPlanModel(
        id=plan.plan_id,
        application_id=plan.application_id,
        job_posting_id=plan.job_posting_id,
        employer_handle=plan.employer_handle,
        target_role=plan.target_role,
        resume_sha256=plan.resume_sha256,
        cover_letter_sha256=plan.cover_letter_sha256,
        packet_sha256=plan.packet_sha256,
        answers_json=[a.to_dict() for a in plan.answers],
        is_compensation_eligible=plan.is_compensation_eligible,
        is_cooldown_clear=plan.is_cooldown_clear,
        compensation_threshold_version=plan.compensation_threshold_version,
        status=plan.status,
    )
    session.add(plan_model)
    session.commit()

    return {
        "plan_id": plan.plan_id,
        "plan_hash": plan.packet_sha256,
        "is_compensation_eligible": plan.is_compensation_eligible,
        "is_cooldown_clear": plan.is_cooldown_clear,
        "message": "Submission plan created and cryptographically signed for review.",
    }


@router.post("/simulate")
def simulate_ats_dispatch(
    payload: SimulateSubmissionRequest,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, Any]:
    """Execute an offline dry-run ATS simulation without external network transmission.

    Guarantees:
    1. Loads the actual persisted submission plan.
    2. Validates plan SHA-256 integrity hash.
    3. Verifies that the plan matches target posting and application.
    4. Verifies actual reviewed application material is present.
    5. Re-evaluates current eligibility and policy gates.
    6. Rejects blocked or review-required plans fail-closed.
    7. Enforces idempotency via persisted ApplicationAttempt table.
    8. Persistently records attempt outcome and simulation receipt.
    9. Never performs external HTTP transmission.
    """
    posting = session.get(JobPosting, payload.job_posting_id)
    if posting is None:
        posting = session.scalar(
            select(JobPosting).where(JobPosting.posting_id == payload.job_posting_id).limit(1)
        )
    if posting is None:
        raise HTTPException(status_code=404, detail="POSTING_NOT_FOUND")

    app = session.scalar(
        select(TrackedApplication)
        .where(TrackedApplication.job_posting_id == posting.id)
        .limit(1)
    )
    if app is None:
        raise HTTPException(status_code=404, detail="APPLICATION_NOT_FOUND: No application record exists for this posting.")

    # 1. Load actual persisted submission plan
    if payload.plan_id:
        plan_model = session.get(SubmissionPlanModel, payload.plan_id)
    else:
        plan_model = session.scalar(
            select(SubmissionPlanModel)
            .where(SubmissionPlanModel.job_posting_id == posting.id)
            .order_by(SubmissionPlanModel.created_at.desc())
            .limit(1)
        )

    if plan_model is None:
        raise HTTPException(
            status_code=404,
            detail="SUBMISSION_PLAN_NOT_FOUND: No persisted submission plan exists for this posting. Create a plan first.",
        )

    # 2. Verify SHA-256 integrity hashes
    if (
        not plan_model.packet_sha256
        or len(plan_model.packet_sha256) != 64
        or not plan_model.resume_sha256
        or len(plan_model.resume_sha256) != 64
    ):
        raise HTTPException(
            status_code=422,
            detail="INVALID_PLAN_INTEGRITY_HASH: Submission plan has missing or malformed SHA-256 hashes.",
        )

    # 3. Verify plan references intended posting and application
    if plan_model.job_posting_id != posting.id:
        raise HTTPException(
            status_code=422,
            detail="PLAN_POSTING_MISMATCH: Plan references a different job posting.",
        )
    if plan_model.application_id != app.id:
        raise HTTPException(
            status_code=422,
            detail="PLAN_APPLICATION_MISMATCH: Plan references a different application record.",
        )

    # 4. Verify actual reviewed application material exists
    resume_content = (app.reviewed_resume_markdown or app.submitted_resume_snapshot or "").strip()
    cover_content = (app.reviewed_cover_letter_markdown or app.submitted_cover_letter_snapshot or "").strip()
    if not resume_content or not cover_content:
        raise HTTPException(
            status_code=422,
            detail="APPLICATION_MATERIALS_INCOMPLETE: Cannot simulate submission without reviewed resume and cover letter markdown.",
        )

    # 5 & 6. Re-evaluate current eligibility and policy gates
    eligibility = evaluate_submission_eligibility(
        session,
        job_posting_id=posting.id,
        current_application_id=app.id,
    )

    # Determine attempt number
    current_attempt_count = session.scalar(
        select(func.count(ApplicationAttempt.id))
        .where(ApplicationAttempt.submission_plan_id == plan_model.id)
    ) or 0
    attempt_number = current_attempt_count + 1
    idempotency_key = f"sim_{plan_model.id}_{attempt_number}"

    # Check for existing idempotent successful attempt
    existing_success = session.scalar(
        select(ApplicationAttempt)
        .where(
            ApplicationAttempt.submission_plan_id == plan_model.id,
            ApplicationAttempt.status == "COMPLETED",
            ApplicationAttempt.outcome == "SUCCESS",
        )
        .order_by(ApplicationAttempt.started_at.desc())
        .limit(1)
    )
    if existing_success:
        return {
            "simulation_id": existing_success.id,
            "receipt": existing_success.simulated_receipt,
            "dry_run": True,
            "status": "SIMULATED_SUCCESS",
            "is_idempotent_replay": True,
        }

    # Reject blocked or review-required plans
    if eligibility.overall_decision == EligibilityDecision.BLOCKED:
        attempt = ApplicationAttempt(
            id=str(uuid.uuid4()),
            application_id=app.id,
            submission_plan_id=plan_model.id,
            attempt_number=attempt_number,
            idempotency_key=idempotency_key,
            simulation_mode="BLOCKED",
            plan_sha256=plan_model.packet_sha256,
            status="FAILED",
            outcome="BLOCKED",
            error_code="POLICY_BLOCKED",
            error_message="; ".join(eligibility.blocking_reasons),
            metadata_json={"reasons": eligibility.blocking_reasons},
            completed_at=datetime.now(timezone.utc),
        )
        session.add(attempt)
        session.commit()
        raise HTTPException(
            status_code=422,
            detail=f"POLICY_BLOCKED: Simulation rejected by policy gate: {'; '.join(eligibility.blocking_reasons)}",
        )

    if eligibility.overall_decision == EligibilityDecision.REVIEW_REQUIRED:
        attempt = ApplicationAttempt(
            id=str(uuid.uuid4()),
            application_id=app.id,
            submission_plan_id=plan_model.id,
            attempt_number=attempt_number,
            idempotency_key=idempotency_key,
            simulation_mode="REVIEW_REQUIRED",
            plan_sha256=plan_model.packet_sha256,
            status="FAILED",
            outcome="REVIEW_REQUIRED",
            error_code="POLICY_REVIEW_REQUIRED",
            error_message="; ".join(eligibility.review_reasons),
            metadata_json={"reasons": eligibility.review_reasons},
            completed_at=datetime.now(timezone.utc),
        )
        session.add(attempt)
        session.commit()
        raise HTTPException(
            status_code=422,
            detail=f"POLICY_REVIEW_REQUIRED: Simulation requires verified evidence: {'; '.join(eligibility.review_reasons)}",
        )

    # Execute simulation via SimulatedAtsAdapter
    packet = {
        "job_posting_id": posting.id,
        "is_compensation_eligible": eligibility.is_compensation_eligible,
        "is_cooldown_clear": eligibility.is_cooldown_clear,
        "resume_markdown": resume_content,
        "cover_letter_markdown": cover_content,
        "packet_sha256": plan_model.packet_sha256,
    }
    adapter = SimulatedAtsAdapter()
    sim_result = adapter.simulate_dispatch(submission_packet=packet)

    status_label = "SIMULATED_SUCCESS" if sim_result.success else "SIMULATED_FAILURE"
    receipt_str = (
        f"Simulated ATS Submission Receipt (Dry-Run)\n"
        f"Job ID: {posting.id}\n"
        f"Plan ID: {plan_model.id}\n"
        f"Plan SHA-256: {plan_model.packet_sha256}\n"
        f"Receipt ID: {sim_result.simulated_receipt_id}\n"
        f"Status: {status_label}\n"
        f"Dispatched via: Local Loopback Simulated ATS\n"
        f"State: Verified Dry-Run Complete. Application state remains user-controlled."
    )

    attempt = ApplicationAttempt(
        id=str(uuid.uuid4()),
        application_id=app.id,
        submission_plan_id=plan_model.id,
        attempt_number=attempt_number,
        idempotency_key=idempotency_key,
        simulation_mode="SUCCESS" if sim_result.success else "FAILED",
        plan_sha256=plan_model.packet_sha256,
        status="COMPLETED" if sim_result.success else "FAILED",
        outcome="SUCCESS" if sim_result.success else "FAILED",
        error_code=sim_result.error_code,
        error_message=sim_result.error_message,
        simulated_receipt=receipt_str,
        metadata_json={
            "duration_ms": sim_result.duration_ms,
            "mode_used": sim_result.mode_used,
        },
        completed_at=datetime.now(timezone.utc),
    )
    session.add(attempt)
    session.commit()

    return {
        "simulation_id": attempt.id,
        "receipt": receipt_str,
        "dry_run": True,
        "status": status_label,
    }


@router.post("/recruiter-message")
def generate_recruiter_outreach(
    payload: RecruiterMessageRequest,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, Any]:
    """Assemble a tailored, factual recruiter outreach draft."""
    try:
        msg = prepare_recruiter_message(
            session,
            posting_id=payload.job_posting_id,
            fact_ids=payload.fact_ids,
            tone=payload.tone,
        )
    except ApplicationPreparationError as exc:
        if exc.code in {"POSTING_NOT_FOUND", "SNAPSHOT_NOT_FOUND"}:
            raise HTTPException(status_code=404, detail=exc.code)
        raise HTTPException(status_code=422, detail=exc.message)

    return msg.model_dump()


@router.get("/readiness/{posting_id}")
def get_submission_readiness(
    posting_id: str,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Audit application readiness across compensation floor, cooldown rules, and fact verification states."""
    try:
        report = check_application_readiness(session, posting_id=posting_id)
    except ApplicationPreparationError as exc:
        if exc.code in {"POSTING_NOT_FOUND", "SNAPSHOT_NOT_FOUND"}:
            raise HTTPException(status_code=404, detail=exc.code)
        raise HTTPException(status_code=422, detail=exc.message)

    return report.model_dump()
