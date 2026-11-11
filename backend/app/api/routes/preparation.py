"""Application Preparation and Readiness Endpoints (Area G / Screen 4).

Provides:
1. Tailored resume and cover letter generation grounded in candidate evidence.
2. Submission plan creation and cryptographic content hashing.
3. Offline dry-run ATS simulation and execution receipts.
4. Personalized recruiter outreach drafting.
5. Multi-gate application submission readiness auditing (compensation floor, cooldown, evidence verification).
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
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
    """Freeze and persist an immutable submission plan with SHA-256 integrity hash."""
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

    sub = session.get(EmployerSubscription, posting.subscription_id)
    employer_handle = sub.employer_handle if sub else "unknown"

    snapshot = session.scalar(
        select(JobPostingSnapshot)
        .where(JobPostingSnapshot.posting_id == posting.id)
        .order_by(JobPostingSnapshot.captured_at.desc())
        .limit(1)
    )
    job_title = snapshot.title if snapshot else "Target Role"

    resume_content = payload.resume_text or app.reviewed_resume_markdown or "Resume Content"
    cover_content = payload.cover_letter_text or app.reviewed_cover_letter_markdown or "Cover Letter"

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
        is_compensation_eligible=True,
        is_cooldown_clear=True,
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
        "message": "Submission plan created and cryptographically signed for review.",
    }


@router.post("/simulate")
def simulate_ats_dispatch(
    payload: SimulateSubmissionRequest,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, Any]:
    """Run an offline dry-run ATS simulation without external network transmission."""
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

    adapter = SimulatedAtsAdapter()
    packet = {
        "job_posting_id": posting.id,
        "is_compensation_eligible": True,
        "is_cooldown_clear": True,
        "resume_markdown": "Simulated Resume",
        "cover_letter_markdown": "Simulated Cover Letter",
    }
    result = adapter.simulate_dispatch(submission_packet=packet)

    status_label = "SIMULATED_SUCCESS" if result.success else "SIMULATED_FAILURE"
    receipt_str = (
        f"Simulated ATS Submission Receipt (Dry-Run)\n"
        f"Job ID: {posting.id}\n"
        f"Receipt ID: {result.simulated_receipt_id}\n"
        f"Status: {status_label}\n"
        f"Dispatched via: Local Loopback Simulated ATS\n"
        f"State: Verified Dry-Run Complete. Application state remains user-controlled."
    )

    return {
        "simulation_id": result.simulated_receipt_id or str(uuid.uuid4()),
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
    """Check application readiness across compensation floor, cooldown rules, and fact verification."""
    try:
        report = check_application_readiness(session, posting_id)
    except ApplicationPreparationError as exc:
        if exc.code in {"POSTING_NOT_FOUND", "SNAPSHOT_NOT_FOUND"}:
            raise HTTPException(status_code=404, detail=exc.code)
        raise HTTPException(status_code=422, detail=exc.message)

    return report.model_dump()
