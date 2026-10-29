"""Service layer for application tracking and job-search pipeline management.

Coordinates persistence, state transitions, concurrency control,
and immutable submission snapshots.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.app.db.models import (
    ApplicationStatusHistory,
    EmployerSubscription,
    JobPosting,
    JobPostingSnapshot,
    TrackedApplication,
)
from backend.app.domain.application_tracking import (
    AlreadySubmittedError,
    ApplicationNotFoundError,
    ApplicationStatus,
    ApplicationStatusHistoryView,
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
    compute_content_sha256,
    validate_status_transition,
    verify_snapshot_hashes,
)


def _resolve_job_posting(session: Session, posting_identifier: str) -> JobPosting:
    """Resolve a JobPosting by either internal UUID or external posting_id."""
    posting = session.get(JobPosting, posting_identifier)
    if posting is None:
        posting = session.scalar(
            select(JobPosting).where(JobPosting.posting_id == posting_identifier).limit(1)
        )
    if posting is None:
        raise ApplicationTrackingError(
            f"Job posting '{posting_identifier}' was not found.",
            "POSTING_NOT_FOUND",
        )
    return posting


def save_or_track_job(
    session: Session,
    request: TrackJobRequest,
) -> TrackedApplication:
    """Track a job posting in the user's pipeline.

    Guarantees idempotency check: only one tracking record per job posting.
    """
    if request.initial_status == ApplicationStatus.APPLIED:
        raise DirectAppliedTransitionNotAllowedError("NONE")

    if request.initial_status == ApplicationStatus.APPLIED:
        raise DirectAppliedTransitionNotAllowedError("NONE")

    posting = _resolve_job_posting(session, request.job_posting_id)

    # Check for existing tracking record
    existing = session.scalar(
        select(TrackedApplication)
        .where(TrackedApplication.job_posting_id == posting.id)
        .limit(1)
    )
    if existing is not None:
        raise DuplicateApplicationTrackingError(posting.id)

    now = datetime.now(timezone.utc)
    app = TrackedApplication(
        id=str(uuid4()),
        job_posting_id=posting.id,
        status=request.initial_status.value,
        notes=request.notes,
        follow_up_deadline=request.follow_up_deadline,
        last_status_change_at=now,
        version=1,
    )
    session.add(app)
    session.flush()

    history = ApplicationStatusHistory(
        application_id=app.id,
        from_status=None,
        to_status=app.status,
        transition_reason="Initial job tracking",
        created_at=now,
    )
    session.add(history)
    session.commit()
    session.refresh(app)
    return app


def get_tracked_application(session: Session, application_id: str) -> TrackedApplication:
    """Get a tracked application by its ID."""
    app = session.get(TrackedApplication, application_id)
    if app is None:
        raise ApplicationNotFoundError(application_id)
    return app


def get_tracked_application_by_posting(
    session: Session, posting_identifier: str
) -> TrackedApplication | None:
    """Get a tracked application by job posting UUID or external posting_id."""
    posting = session.get(JobPosting, posting_identifier)
    if posting is None:
        posting = session.scalar(
            select(JobPosting).where(JobPosting.posting_id == posting_identifier).limit(1)
        )
    if posting is None:
        return None

    return session.scalar(
        select(TrackedApplication)
        .where(TrackedApplication.job_posting_id == posting.id)
        .limit(1)
    )


def list_tracked_applications(
    session: Session,
    status: ApplicationStatus | None = None,
    include_archived: bool = False,
    sort_by: str = "updated_at",
) -> list[TrackedApplicationView]:
    """List tracked applications with associated job details."""
    query = select(TrackedApplication)

    if status is not None:
        query = query.where(TrackedApplication.status == status.value)
    elif not include_archived:
        query = query.where(TrackedApplication.status != ApplicationStatus.ARCHIVED.value)

    if sort_by == "created_at":
        query = query.order_by(desc(TrackedApplication.created_at))
    elif sort_by == "last_status_change_at":
        query = query.order_by(desc(TrackedApplication.last_status_change_at))
    else:
        query = query.order_by(desc(TrackedApplication.updated_at))

    apps = session.scalars(query).all()
    views: list[TrackedApplicationView] = []
    for app in apps:
        views.append(build_application_view(session, app))
    return views


def transition_application_status(
    session: Session,
    application_id: str,
    request: StatusTransitionRequest,
) -> TrackedApplication:
    """Transition an application's status following allowed lifecycle rules."""
    app = get_tracked_application(session, application_id)

    if request.expected_version is not None and app.version != request.expected_version:
        raise ConcurrencyConflictError(request.expected_version, app.version)

    current_status = app.status
    target_status = request.target_status.value

    if current_status != target_status:
        if target_status == ApplicationStatus.APPLIED.value:
            raise DirectAppliedTransitionNotAllowedError(current_status)

        if target_status in (
            ApplicationStatus.SAVED.value,
            ApplicationStatus.PREPARING.value,
            ApplicationStatus.READY_FOR_REVIEW.value,
        ) and (app.applied_at is not None or app.submitted_resume_snapshot is not None):
            raise InvalidStateTransitionError(
                current_status,
                f"{target_status} (cannot unapply a previously submitted application)",
            )

        validate_status_transition(current_status, target_status)
        now = datetime.now(timezone.utc)
        app.status = target_status
        app.last_status_change_at = now
        app.version += 1

        history = ApplicationStatusHistory(
            application_id=app.id,
            from_status=current_status,
            to_status=target_status,
            transition_reason=request.reason,
            created_at=now,
        )
        session.add(history)
        session.commit()
        session.refresh(app)

    return app


def confirm_application_submission(
    session: Session,
    application_id: str,
    request: SubmissionConfirmRequest,
) -> TrackedApplication:
    """Confirm external job application submission.

    Transitions to APPLIED, freezes immutable snapshots of submitted materials,
    and records content SHA-256 digests.
    """
    app = get_tracked_application(session, application_id)

    if request.expected_version is not None and app.version != request.expected_version:
        raise ConcurrencyConflictError(request.expected_version, app.version)

    if (
        app.status == ApplicationStatus.APPLIED.value
        or app.submitted_resume_snapshot is not None
        or app.submitted_cover_letter_snapshot is not None
    ):
        raise AlreadySubmittedError(application_id)

    if app.status not in (
        ApplicationStatus.SAVED.value,
        ApplicationStatus.PREPARING.value,
        ApplicationStatus.READY_FOR_REVIEW.value,
    ):
        raise InvalidStateTransitionError(app.status, ApplicationStatus.APPLIED.value)

    if (
        app.status == ApplicationStatus.APPLIED.value
        or app.submitted_resume_snapshot is not None
        or app.submitted_cover_letter_snapshot is not None
    ):
        raise AlreadySubmittedError(application_id)

    if app.status not in (
        ApplicationStatus.SAVED.value,
        ApplicationStatus.PREPARING.value,
        ApplicationStatus.READY_FOR_REVIEW.value,
    ):
        raise InvalidStateTransitionError(app.status, ApplicationStatus.APPLIED.value)

    validate_status_transition(app.status, ApplicationStatus.APPLIED)

    now = datetime.now(timezone.utc)
    applied_time = request.applied_at or now

    current_status = app.status
    app.status = ApplicationStatus.APPLIED.value
    app.applied_at = applied_time
    app.last_status_change_at = now

    if request.resume_markdown is not None:
        app.submitted_resume_snapshot = request.resume_markdown
        app.submitted_resume_sha256 = compute_content_sha256(request.resume_markdown)

    if request.cover_letter_markdown is not None:
        app.submitted_cover_letter_snapshot = request.cover_letter_markdown
        app.submitted_cover_letter_sha256 = compute_content_sha256(request.cover_letter_markdown)

    if request.notes:
        if app.notes:
            app.notes = f"{app.notes}\n\n[Submission Note: {request.notes}]"
        else:
            app.notes = request.notes

    app.version += 1

    history = ApplicationStatusHistory(
        application_id=app.id,
        from_status=current_status,
        to_status=ApplicationStatus.APPLIED.value,
        transition_reason="Candidate confirmed application submission",
        created_at=now,
    )
    session.add(history)
    session.commit()
    session.refresh(app)
    return app


def mark_application_reviewed(
    session: Session,
    application_id: str,
    request: MarkReviewedRequest,
) -> TrackedApplication:
    """Mark application materials reviewed by candidate and transition to READY_FOR_REVIEW."""
    app = get_tracked_application(session, application_id)

    if request.expected_version is not None and app.version != request.expected_version:
        raise ConcurrencyConflictError(request.expected_version, app.version)

    now = datetime.now(timezone.utc)
    current_status = app.status

    if request.reviewed_resume is not None:
        app.reviewed_resume_markdown = request.reviewed_resume
    if request.reviewed_cover_letter is not None:
        app.reviewed_cover_letter_markdown = request.reviewed_cover_letter
    app.reviewed_at = now

    if current_status in (ApplicationStatus.SAVED.value, ApplicationStatus.PREPARING.value):
        validate_status_transition(current_status, ApplicationStatus.READY_FOR_REVIEW)
        app.status = ApplicationStatus.READY_FOR_REVIEW.value
        app.last_status_change_at = now
        history = ApplicationStatusHistory(
            application_id=app.id,
            from_status=current_status,
            to_status=ApplicationStatus.READY_FOR_REVIEW.value,
            transition_reason="Materials marked reviewed by candidate",
            created_at=now,
        )
        session.add(history)

    app.version += 1
    session.commit()
    session.refresh(app)
    return app


def update_application_details(
    session: Session,
    application_id: str,
    request: ApplicationUpdateRequest,
) -> TrackedApplication:
    """Update user notes, follow-up deadlines, or next interview schedule."""
    app = get_tracked_application(session, application_id)

    if request.expected_version is not None and app.version != request.expected_version:
        raise ConcurrencyConflictError(request.expected_version, app.version)

    changed = False
    if request.notes is not None:
        app.notes = request.notes
        changed = True
    if request.follow_up_deadline is not None:
        app.follow_up_deadline = request.follow_up_deadline
        changed = True
    if request.next_interview_at is not None:
        app.next_interview_at = request.next_interview_at
        changed = True

    if changed:
        app.version += 1
        session.commit()
        session.refresh(app)

    return app


def build_application_view(session: Session, app: TrackedApplication) -> TrackedApplicationView:
    """Enrich TrackedApplication with denormalized job posting and employer details."""
    posting = session.get(JobPosting, app.job_posting_id)
    job_title: str | None = None
    employer_name: str | None = None
    location: str | None = None
    apply_url: str | None = None
    job_lifecycle: str | None = None

    if posting:
        job_lifecycle = posting.lifecycle_status
        sub = session.get(EmployerSubscription, posting.subscription_id)
        if sub:
            employer_name = sub.display_name or sub.employer_handle

        snapshot = session.scalar(
            select(JobPostingSnapshot)
            .where(JobPostingSnapshot.posting_id == posting.id)
            .order_by(JobPostingSnapshot.captured_at.desc())
            .limit(1)
        )
        if snapshot:
            job_title = snapshot.title
            location = snapshot.location
            apply_url = snapshot.apply_url or snapshot.canonical_url

    return TrackedApplicationView(
        id=app.id,
        job_posting_id=app.job_posting_id,
        status=app.status,
        notes=app.notes,
        follow_up_deadline=app.follow_up_deadline,
        next_interview_at=app.next_interview_at,
        applied_at=app.applied_at,
        last_status_change_at=app.last_status_change_at,
        submitted_resume_snapshot=app.submitted_resume_snapshot,
        submitted_cover_letter_snapshot=app.submitted_cover_letter_snapshot,
        submitted_resume_sha256=app.submitted_resume_sha256,
        submitted_cover_letter_sha256=app.submitted_cover_letter_sha256,
        reviewed_resume_markdown=app.reviewed_resume_markdown,
        reviewed_cover_letter_markdown=app.reviewed_cover_letter_markdown,
        reviewed_at=app.reviewed_at,
        version=app.version,
        created_at=app.created_at,
        updated_at=app.updated_at,
        job_title=job_title,
        employer_name=employer_name,
        location=location,
        apply_url=apply_url,
        job_lifecycle_status=job_lifecycle,
        snapshot_hashes_verified=verify_snapshot_hashes(
            app.submitted_resume_snapshot,
            app.submitted_resume_sha256,
            app.submitted_cover_letter_snapshot,
            app.submitted_cover_letter_sha256,
        ),
    )


def build_application_detail_view(
    session: Session, app: TrackedApplication
) -> TrackedApplicationDetailView:
    """Enrich TrackedApplication with job details and full status transition history."""
    base_view = build_application_view(session, app)

    history_records = session.scalars(
        select(ApplicationStatusHistory)
        .where(ApplicationStatusHistory.application_id == app.id)
        .order_by(ApplicationStatusHistory.created_at.asc())
    ).all()

    history_views = [
        ApplicationStatusHistoryView.model_validate(rec) for rec in history_records
    ]

    return TrackedApplicationDetailView(
        **base_view.model_dump(),
        status_history=history_views,
    )
