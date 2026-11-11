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
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_session, require_local_same_origin
from backend.app.domain.application_tracking import ApplicationStatus
from backend.app.db.models import (
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
from backend.app.services.simulation_service import (
    SimulationIntegrityError,
    SimulationMaterialsError,
    SimulationMismatchError,
    SimulationNotFoundError,
    SimulationPolicyError,
    execute_simulation,
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
    approve: bool = Field(default=False, description="Explicit candidate approval of frozen materials")


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

    # Compute material SHA-256 hashes
    r_hash = hashlib.sha256(resume_content.encode("utf-8")).hexdigest()
    cl_hash = hashlib.sha256(cover_content.encode("utf-8")).hexdigest()

    # Invalidate prior approval if candidate altered materials
    if (
        getattr(app, "reviewed_resume_sha256", None)
        and getattr(app, "reviewed_resume_sha256", None) != r_hash
    ) or (
        getattr(app, "reviewed_cover_letter_sha256", None)
        and getattr(app, "reviewed_cover_letter_sha256", None) != cl_hash
    ):
        app.review_approval_state = "INVALIDATED"
        app.approved_submission_plan_id = None

    # Creating a plan must never imply user approval; all new plans remain UNREVIEWED
    # until an explicit candidate approval action occurs via POST /plan/{plan_id}/approve
    review_state = "UNREVIEWED"
    if not app.approved_submission_plan_id:
        app.review_approval_state = "REVIEW_REQUIRED"

    plan_id = str(uuid.uuid4())
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
        resume_markdown=plan.resume_markdown,
        cover_letter_markdown=plan.cover_letter_markdown,
        review_state=plan.review_state,
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


@router.post("/plan/{plan_id}/approve")
def approve_submission_plan(
    plan_id: str,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, Any]:
    """Explicitly review and approve a frozen submission plan and its materials."""
    from backend.app.services.simulation_service import approve_submission_plan_and_application

    try:
        return approve_submission_plan_and_application(session, plan_id=plan_id)
    except SimulationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.code)
    except (SimulationIntegrityError, SimulationMaterialsError, SimulationMismatchError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{exc.code}: {exc.message}")

    return {
        "plan_id": plan.id,
        "application_id": app.id,
        "approval_state": "APPROVED",
        "review_state": "APPROVED",
        "reviewed_resume_hash": resume_hash,
        "reviewed_cover_letter_hash": cover_hash,
        "packet_sha256": plan.packet_sha256,
        "reviewed_at": now.isoformat(),
        "message": "Submission plan explicitly approved by candidate.",
    }


@router.post("/simulate")
def simulate_ats_dispatch(
    payload: SimulateSubmissionRequest,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, Any]:
    """Execute an offline dry-run ATS simulation via the shared simulation service.

    Guarantees (enforced by simulation_service.execute_simulation):
    1. Loads the actual persisted submission plan.
    2. Recomputes and verifies all SHA-256 hashes from frozen material.
    3. Verifies plan matches target posting and application.
    4. Verifies reviewed application material is present.
    5. Re-evaluates current eligibility and policy gates (fail closed).
    6. Rejects blocked or review-required plans.
    7. Enforces idempotency via persisted ApplicationAttempt table.
    8. Persistently records attempt outcome and simulation receipt.
    9. Never performs external HTTP transmission.
    """
    try:
        result = execute_simulation(
            session,
            plan_id=payload.plan_id,
            posting_id=payload.job_posting_id,
        )
    except SimulationNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"{exc.code}: {exc.message}",
        )
    except SimulationIntegrityError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"{exc.code}: {exc.message}",
        )
    except SimulationMismatchError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"{exc.code}: {exc.message}",
        )
    except SimulationMaterialsError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"{exc.code}: {exc.message}",
        )
    except SimulationPolicyError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"{exc.code}: {exc.message}",
        )

    return {
        "simulation_id": result.simulation_id,
        "receipt": result.receipt,
        "dry_run": result.dry_run,
        "status": result.status,
        "is_idempotent_replay": result.is_idempotent_replay,
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
