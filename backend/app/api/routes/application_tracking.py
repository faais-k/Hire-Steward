"""API endpoints for application tracking and pipeline lifecycle management."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from sqlalchemy import func, select

from backend.app.api.dependencies import get_session, require_local_same_origin
from backend.app.adapters.simulated_ats import SimulatedAtsAdapter
from backend.app.domain.application_preparation import ApplicationPreparationError
from backend.app.domain.submission_plan import SubmissionPlan
from backend.app.services.answer_bank import list_answer_items
from backend.app.services.application_preparation import prepare_application_draft
from backend.app.services.candidate_profile import get_or_create_profile
from backend.app.services.simulation_service import (
    SimulationIntegrityError,
    SimulationMaterialsError,
    SimulationMismatchError,
    SimulationNotFoundError,
    SimulationPolicyError,
    execute_simulation,
)
from backend.app.services.user_settings import get_user_settings
from backend.app.db.models import (
    ApplicationAttempt,
    AuditEvent,
    CompensationAssessment,
    EmployerSubscription,
    JobPosting,
    JobPostingSnapshot,
    SubmissionPlanModel,
    TrackedApplication,
)
from backend.app.domain.application_tracking import (
    AlreadySubmittedError,
    ApplicationNotFoundError,
    ApplicationStatus,
    ApplicationTrackingError,
    ApplicationUpdateRequest,
    ConcurrencyConflictError,
    DirectAppliedTransitionNotAllowedError,
    DuplicateApplicationTrackingError,
    InvalidStateTransitionError,
    MarkReviewedRequest,
    StatusTransitionRequest,
    SubmissionConfirmRequest,
    TrackedApplicationDetailView,
    TrackedApplicationView,
    TrackJobRequest,
)
from backend.app.services.application_tracking import (
    build_application_detail_view,
    confirm_application_submission,
    get_tracked_application,
    get_tracked_application_by_posting,
    list_tracked_applications,
    mark_application_reviewed,
    save_or_track_job,
    transition_application_status,
    update_application_details,
)


router = APIRouter(prefix="/api/v1")

VALID_SORT_BY = {"updated_at", "created_at", "last_status_change_at"}


@router.post("/applications/track", status_code=status.HTTP_201_CREATED)
@router.post("/applications", status_code=status.HTTP_201_CREATED)
def track_job(
    request: TrackJobRequest,
    session: Session = Depends(get_session),
) -> TrackedApplicationDetailView:
    """Track a job posting in the user's application pipeline."""
    try:
        app = save_or_track_job(session, request)
    except DirectAppliedTransitionNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code)
    except DuplicateApplicationTrackingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.code)
    except ApplicationTrackingError as exc:
        if exc.code == "POSTING_NOT_FOUND":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.code)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code)

    return build_application_detail_view(session, app)


@router.get("/applications")
def get_applications(
    status_filter: str | None = Query(None, alias="status"),
    include_archived: bool = Query(False),
    sort_by: str = Query("updated_at"),
    session: Session = Depends(get_session),
) -> list[TrackedApplicationView]:
    """List tracked applications in the user's pipeline with filtering and sorting."""
    app_status: ApplicationStatus | None = None
    if status_filter:
        try:
            app_status = ApplicationStatus(status_filter.upper())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="INVALID_STATUS_FILTER",
            )

    if sort_by not in VALID_SORT_BY:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="INVALID_SORT_BY",
        )

    return list_tracked_applications(
        session,
        status=app_status,
        include_archived=include_archived,
        sort_by=sort_by,
    )


@router.get("/applications/{application_id}")
def get_application(
    application_id: str,
    session: Session = Depends(get_session),
) -> TrackedApplicationDetailView:
    """Retrieve full application details, including status transition history."""
    try:
        app = get_tracked_application(session, application_id)
    except ApplicationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.code)

    return build_application_detail_view(session, app)


@router.get("/jobs/{posting_id}/tracking")
def get_job_tracking_status(
    posting_id: str,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Check if a job posting is tracked and return its details if present."""
    app = get_tracked_application_by_posting(session, posting_id)
    if app is None:
        return {"tracked": False, "application": None}

    detail = build_application_detail_view(session, app)
    return {"tracked": True, "application": detail.model_dump()}


@router.patch("/applications/{application_id}/status")
def change_application_status(
    application_id: str,
    request: StatusTransitionRequest,
    session: Session = Depends(get_session),
) -> TrackedApplicationDetailView:
    """Transition application status following valid state-machine rules."""
    try:
        app = transition_application_status(session, application_id, request)
    except ApplicationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.code)
    except (InvalidStateTransitionError, DirectAppliedTransitionNotAllowedError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code)
    except ConcurrencyConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.code)

    return build_application_detail_view(session, app)


@router.post("/applications/{application_id}/confirm-submission")
def confirm_submission(
    application_id: str,
    request: SubmissionConfirmRequest,
    session: Session = Depends(get_session),
) -> TrackedApplicationDetailView:
    """Confirm external application submission, freezing submitted material snapshots."""
    try:
        app = confirm_application_submission(session, application_id, request)
    except ApplicationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.code)
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code)
    except AlreadySubmittedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.code)
    except ConcurrencyConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.code)

    return build_application_detail_view(session, app)


@router.post("/applications/{application_id}/mark-reviewed")
def mark_reviewed(
    application_id: str,
    request: MarkReviewedRequest,
    session: Session = Depends(get_session),
) -> TrackedApplicationDetailView:
    """Mark application materials reviewed and transition to READY_FOR_REVIEW."""
    try:
        app = mark_application_reviewed(session, application_id, request)
    except ApplicationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.code)
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code)
    except ConcurrencyConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.code)

    return build_application_detail_view(session, app)


@router.patch("/applications/{application_id}")
def update_details(
    application_id: str,
    request: ApplicationUpdateRequest,
    session: Session = Depends(get_session),
) -> TrackedApplicationDetailView:
    """Update notes, deadlines, or upcoming interview dates."""
    try:
        app = update_application_details(session, application_id, request)
    except ApplicationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.code)
    except ConcurrencyConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.code)

    return build_application_detail_view(session, app)


@router.post("/applications/{application_id}/archive")
def archive_app(
    application_id: str,
    request: StatusTransitionRequest | None = None,
    session: Session = Depends(get_session),
) -> TrackedApplicationDetailView:
    """Archive an application."""
    req = request or StatusTransitionRequest(
        target_status=ApplicationStatus.ARCHIVED,
        reason="Archived by user",
    )
    req.target_status = ApplicationStatus.ARCHIVED
    try:
        app = transition_application_status(session, application_id, req)
    except ApplicationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.code)
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code)
    except ConcurrencyConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.code)

    return build_application_detail_view(session, app)


@router.post("/applications/{application_id}/submission-plan")
def create_submission_plan(
    application_id: str,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, Any]:
    """Generate and freeze an immutable submission plan packet for this application."""
    app = get_tracked_application(session, application_id)
    posting = session.get(JobPosting, app.job_posting_id)
    if posting is None:
        raise HTTPException(status_code=404, detail="POSTING_NOT_FOUND")

    sub = session.get(EmployerSubscription, posting.subscription_id)
    employer_handle = sub.employer_handle if sub else "unknown"

    snapshot = session.scalar(
        select(JobPostingSnapshot)
        .where(JobPostingSnapshot.posting_id == posting.id)
        .order_by(JobPostingSnapshot.captured_at.desc())
        .limit(1)
    )
    job_title = snapshot.title if snapshot else "Target Role"

    # Load tailored materials or prepare fresh draft
    resume = app.reviewed_resume_markdown or app.submitted_resume_snapshot
    cover_letter = app.reviewed_cover_letter_markdown or app.submitted_cover_letter_snapshot
    if not resume or not cover_letter:
        try:
            draft = prepare_application_draft(session, posting.id)
            resume = resume or draft.resume_markdown
            cover_letter = cover_letter or draft.cover_letter_markdown
        except ApplicationPreparationError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"APPLICATION_MATERIALS_INCOMPLETE: Cannot prepare application draft: {exc.message}",
            )
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=f"APPLICATION_MATERIALS_INCOMPLETE: Draft preparation failed: {exc}",
            )

    if not resume or not cover_letter:
        raise HTTPException(
            status_code=422,
            detail="APPLICATION_MATERIALS_INCOMPLETE: Tailored resume and cover letter are required.",
        )

    # Load pre-approved answers with explicit consent
    answers_db = list_answer_items(session, include_revoked=False, consent_only=True)
    answers = [
        {
            "question": a.question,
            "answer": a.answer,
            "category": a.category,
            "reuse_consent": a.reuse_consent,
        }
        for a in answers_db
    ]

    # Evaluate compensation and cooldown policy via authoritative service (fail closed)
    from backend.app.services.submission_eligibility import evaluate_submission_eligibility
    eligibility = evaluate_submission_eligibility(
        session,
        posting.id,
        current_application_id=app.id,
    )
    is_compensation_eligible = eligibility.is_compensation_eligible
    is_cooldown_clear = eligibility.is_cooldown_clear

    import uuid
    plan_id = str(uuid.uuid4())
    # Creating a plan must never imply user approval; all new plans remain UNREVIEWED
    review_state = "UNREVIEWED"

    plan = SubmissionPlan.create(
        plan_id=plan_id,
        application_id=app.id,
        job_posting_id=posting.id,
        employer_handle=employer_handle,
        target_role=job_title,
        resume_markdown=resume,
        cover_letter_markdown=cover_letter,
        answers=answers,
        is_compensation_eligible=is_compensation_eligible,
        is_cooldown_clear=is_cooldown_clear,
        compensation_threshold_version=1,
        review_state=review_state,
    )

    # Persist immutable submission plan record
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

    now = datetime.now(timezone.utc)
    if not app.reviewed_resume_markdown:
        app.reviewed_resume_markdown = resume
    if not app.reviewed_cover_letter_markdown:
        app.reviewed_cover_letter_markdown = cover_letter

    # Do not overwrite a previous approval with a new approval when creating or editing a plan.
    # A newly created plan must require a new approval, even when the user previously approved another plan.
    # Therefore, creating a new plan does NOT approve this plan.
    if not app.approved_submission_plan_id:
        app.review_approval_state = "REVIEW_REQUIRED"

    session.commit()

    return plan.to_dict()


@router.post("/applications/{application_id}/plans/{plan_id}/approve")
def approve_application_plan(
    application_id: str,
    plan_id: str,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, Any]:
    """Explicitly review and approve a frozen submission plan for this application."""
    from backend.app.services.simulation_service import (
        approve_submission_plan_and_application,
        SimulationNotFoundError,
        SimulationIntegrityError,
        SimulationMaterialsError,
        SimulationMismatchError,
    )
    try:
        return approve_submission_plan_and_application(
            session,
            plan_id=plan_id,
            application_id=application_id,
        )
    except SimulationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.code)
    except (SimulationIntegrityError, SimulationMaterialsError, SimulationMismatchError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{exc.code}: {exc.message}")


class SimulateSubmissionRequest(BaseModel):
    mode: str = "SUCCESS"
    plan_id: str | None = None
    idempotency_key: str | None = None


@router.post("/applications/{application_id}/simulate-submission")
def simulate_submission(
    application_id: str,
    payload: SimulateSubmissionRequest | None = None,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, Any]:
    """Simulate ATS dispatch and dry-run application submission via unified simulation service."""
    app = get_tracked_application(session, application_id)

    mode = payload.mode if payload and payload.mode else "SUCCESS"
    from backend.app.adapters.simulated_ats import VALID_SIMULATION_MODES
    if mode not in VALID_SIMULATION_MODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid simulation mode '{mode}'. Valid modes: {sorted(VALID_SIMULATION_MODES)}",
        )
    idempotency_key = payload.idempotency_key if payload and payload.idempotency_key else None

    # Resolve or create plan
    plan_id = payload.plan_id if payload else None
    if not plan_id:
        existing_plan = session.scalar(
            select(SubmissionPlanModel)
            .where(SubmissionPlanModel.application_id == application_id)
            .order_by(SubmissionPlanModel.created_at.desc())
            .limit(1)
        )
        if existing_plan:
            plan_id = existing_plan.id
        else:
            plan_dict = create_submission_plan(application_id, session)
            plan_id = plan_dict["plan_id"]

    try:
        res = execute_simulation(
            session,
            plan_id=plan_id,
            application_id=application_id,
            mode=mode,
            idempotency_key=idempotency_key,
            raise_on_policy_failure=False,
        )
    except SimulationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.code)
    except (SimulationIntegrityError, SimulationMaterialsError, SimulationMismatchError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{exc.code}: {exc.message}")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    return {
        "attempt_id": res.simulation_id,
        "application_id": res.application_id,
        "submission_plan_id": res.submission_plan_id,
        "attempt_number": res.attempt_number,
        "idempotency_key": res.idempotency_key,
        "status": res.status,
        "outcome": res.outcome,
        "success": res.success,
        "mode_used": mode,
        "is_simulation": True,
        "receipt_id": res.receipt,
        "error_code": res.error_code,
        "error_message": res.error_message,
        "duration_ms": res.duration_ms,
        "plan_sha256": res.plan_sha256,
        "is_idempotent_replay": res.is_idempotent_replay,
        "started_at": res.started_at.isoformat() if res.started_at else None,
        "completed_at": res.completed_at.isoformat() if res.completed_at else None,
        "application_status": res.application_status,
    }


@router.get("/applications/{application_id}/attempts")
def list_application_attempts(
    application_id: str,
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    """List all persisted execution attempts for a tracked application."""
    get_tracked_application(session, application_id)
    attempts = list(
        session.scalars(
            select(ApplicationAttempt)
            .where(ApplicationAttempt.application_id == application_id)
            .order_by(ApplicationAttempt.attempt_number.asc())
        ).all()
    )
    return [
        {
            "id": att.id,
            "application_id": att.application_id,
            "submission_plan_id": att.submission_plan_id,
            "attempt_number": att.attempt_number,
            "idempotency_key": att.idempotency_key,
            "simulation_mode": att.simulation_mode,
            "plan_sha256": att.plan_sha256,
            "status": att.status,
            "outcome": att.outcome,
            "error_code": att.error_code,
            "error_message": att.error_message,
            "simulated_receipt": att.simulated_receipt,
            "metadata": att.metadata_json,
            "started_at": att.started_at.isoformat() if att.started_at else None,
            "completed_at": att.completed_at.isoformat() if att.completed_at else None,
        }
        for att in attempts
    ]



@router.get("/applications/{application_id}/handoff")
def get_manual_handoff_packet(
    application_id: str,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Assemble manual submission packet for external employer portal application."""
    app = get_tracked_application(session, application_id)
    posting = session.get(JobPosting, app.job_posting_id)
    if posting is None:
        raise HTTPException(status_code=404, detail="POSTING_NOT_FOUND")

    sub = session.get(EmployerSubscription, posting.subscription_id)
    employer_handle = sub.employer_handle if sub else "unknown"

    snapshot = session.scalar(
        select(JobPostingSnapshot)
        .where(JobPostingSnapshot.posting_id == posting.id)
        .order_by(JobPostingSnapshot.captured_at.desc())
        .limit(1)
    )
    job_title = snapshot.title if snapshot else "Target Role"
    destination_url = snapshot.canonical_url if snapshot else None

    # Load tailored materials or prepare fresh draft
    resume = app.reviewed_resume_markdown or app.submitted_resume_snapshot
    cover_letter = app.reviewed_cover_letter_markdown or app.submitted_cover_letter_snapshot
    if not resume or not cover_letter:
        try:
            draft = prepare_application_draft(session, posting.id)
            resume = resume or draft.resume_markdown
            cover_letter = cover_letter or draft.cover_letter_markdown
        except ApplicationPreparationError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"APPLICATION_MATERIALS_INCOMPLETE: Cannot prepare application draft: {exc.message}",
            )
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=f"APPLICATION_MATERIALS_INCOMPLETE: Draft preparation failed: {exc}",
            )

    if not resume or not cover_letter:
        raise HTTPException(
            status_code=422,
            detail="APPLICATION_MATERIALS_INCOMPLETE: Tailored resume and cover letter are required.",
        )

    # Evaluate unresolved safety gates
    unresolved_gates: list[str] = []

    # 1. Compensation check
    comp_assess = session.scalar(
        select(CompensationAssessment)
        .where(CompensationAssessment.job_reference == posting.id)
        .order_by(CompensationAssessment.created_at.desc())
        .limit(1)
    )
    is_compensation_eligible = False
    if comp_assess is not None:
        if (
            comp_assess.reported_status == "PAID"
            and comp_assess.evidence_verification_state == "VERIFIED"
            and comp_assess.outcome == "MEETS_THRESHOLD"
        ):
            is_compensation_eligible = True
    if not is_compensation_eligible:
        unresolved_gates.append("COMPENSATION_VERIFICATION_REQUIRED")

    # 2. Cooldown check
    is_cooldown_clear = False
    if employer_handle and employer_handle.strip() and employer_handle != "unknown":
        settings_dict = get_user_settings(session)
        cooldown_days = int(settings_dict.get("same_company_cooldown_days", 30))
        cutoff = datetime.now(timezone.utc) - timedelta(days=cooldown_days)
        matching_sub_ids = list(session.scalars(
            select(EmployerSubscription.id).where(EmployerSubscription.employer_handle == employer_handle)
        ).all())
        if matching_sub_ids:
            matching_posting_ids = list(session.scalars(
                select(JobPosting.id).where(JobPosting.subscription_id.in_(matching_sub_ids))
            ).all())
            if matching_posting_ids:
                prior_app = session.scalar(
                    select(TrackedApplication)
                    .where(
                        TrackedApplication.job_posting_id.in_(matching_posting_ids),
                        TrackedApplication.id != app.id,
                        TrackedApplication.status.in_([
                            ApplicationStatus.APPLIED.value,
                            ApplicationStatus.INTERVIEWING.value,
                            ApplicationStatus.OFFER_RECEIVED.value,
                        ]),
                        TrackedApplication.created_at >= cutoff,
                    )
                    .limit(1)
                )
                is_cooldown_clear = (prior_app is None)
            else:
                is_cooldown_clear = True
        else:
            is_cooldown_clear = True
    if not is_cooldown_clear:
        unresolved_gates.append("COOLDOWN_ACTIVE")

    # 3. Materials review check
    materials_reviewed = bool(app.reviewed_resume_markdown and app.reviewed_cover_letter_markdown)
    if not materials_reviewed:
        unresolved_gates.append("CANDIDATE_MATERIAL_REVIEW_REQUIRED")

    answers_db = list_answer_items(session, include_revoked=False, consent_only=True)
    answers = [
        {"question": a.question, "answer": a.answer, "category": a.category}
        for a in answers_db
    ]

    material_status = "VERIFIED_APPROVED" if materials_reviewed else "GENERATED_UNREVIEWED"
    instructions = (
        "Review all application materials thoroughly before submitting. Unreviewed AI drafts must be verified by candidate."
        if unresolved_gates
        else "Materials reviewed and safety gates satisfied. Copy and paste verified materials into the employer portal, then click 'Confirm Submission' to record the application."
    )

    return {
        "application_id": app.id,
        "job_title": job_title,
        "employer_handle": employer_handle,
        "destination_url": destination_url,
        "resume_markdown": resume,
        "cover_letter_markdown": cover_letter,
        "answers": answers,
        "material_status": material_status,
        "review_required": len(unresolved_gates) > 0,
        "unresolved_gates": unresolved_gates,
        "instructions": instructions,
    }
