"""API endpoints for application tracking and pipeline lifecycle management."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_session
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
