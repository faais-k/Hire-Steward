"""Application tracking and job-search pipeline domain models and lifecycle engine.

Manages application tracking states, valid transitions, concurrency tokens,
and immutable submission snapshot hashes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, field_validator


class ApplicationStatus(str, Enum):
    SAVED = "SAVED"
    PREPARING = "PREPARING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPLIED = "APPLIED"
    INTERVIEWING = "INTERVIEWING"
    OFFER_RECEIVED = "OFFER_RECEIVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    ARCHIVED = "ARCHIVED"


VALID_TRANSITIONS: dict[ApplicationStatus, set[ApplicationStatus]] = {
    ApplicationStatus.SAVED: {
        ApplicationStatus.PREPARING,
        ApplicationStatus.READY_FOR_REVIEW,
        ApplicationStatus.APPLIED,
        ApplicationStatus.ARCHIVED,
    },
    ApplicationStatus.PREPARING: {
        ApplicationStatus.READY_FOR_REVIEW,
        ApplicationStatus.APPLIED,
        ApplicationStatus.SAVED,
        ApplicationStatus.ARCHIVED,
    },
    ApplicationStatus.READY_FOR_REVIEW: {
        ApplicationStatus.PREPARING,
        ApplicationStatus.APPLIED,
        ApplicationStatus.SAVED,
        ApplicationStatus.ARCHIVED,
    },
    ApplicationStatus.APPLIED: {
        ApplicationStatus.INTERVIEWING,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
        ApplicationStatus.ARCHIVED,
    },
    ApplicationStatus.INTERVIEWING: {
        ApplicationStatus.OFFER_RECEIVED,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
        ApplicationStatus.ARCHIVED,
    },
    ApplicationStatus.OFFER_RECEIVED: {
        ApplicationStatus.WITHDRAWN,
        ApplicationStatus.ARCHIVED,
    },
    ApplicationStatus.REJECTED: {
        ApplicationStatus.ARCHIVED,
    },
    ApplicationStatus.WITHDRAWN: {
        ApplicationStatus.ARCHIVED,
    },
    ApplicationStatus.ARCHIVED: {
        ApplicationStatus.SAVED,
    },
}


class ApplicationTrackingError(Exception):
    """Base domain error for application tracking."""

    def __init__(self, message: str, code: str) -> None:
        self.message = message
        self.code = code
        super().__init__(message)


class InvalidStateTransitionError(ApplicationTrackingError):
    def __init__(self, from_status: str, to_status: str) -> None:
        super().__init__(
            f"Cannot transition application from '{from_status}' to '{to_status}'.",
            "INVALID_STATUS_TRANSITION",
        )
        self.from_status = from_status
        self.to_status = to_status


class ApplicationNotFoundError(ApplicationTrackingError):
    def __init__(self, identifier: str) -> None:
        super().__init__(
            f"Tracked application '{identifier}' was not found.",
            "APPLICATION_NOT_FOUND",
        )
        self.identifier = identifier


class DuplicateApplicationTrackingError(ApplicationTrackingError):
    def __init__(self, job_posting_id: str) -> None:
        super().__init__(
            f"A tracking record already exists for job posting '{job_posting_id}'.",
            "DUPLICATE_APPLICATION_TRACKING",
        )
        self.job_posting_id = job_posting_id


class ConcurrencyConflictError(ApplicationTrackingError):
    def __init__(self, expected_version: int, current_version: int) -> None:
        super().__init__(
            f"Concurrency conflict: expected version {expected_version}, but found version {current_version}.",
            "CONCURRENCY_CONFLICT",
        )
        self.expected_version = expected_version
        self.current_version = current_version


class DirectAppliedTransitionNotAllowedError(ApplicationTrackingError):
    def __init__(self, from_status: str) -> None:
        super().__init__(
            f"Cannot transition application from '{from_status}' directly to 'APPLIED' via generic status update. "
            "Explicit user confirmation with frozen material snapshots is required via /confirm-submission.",
            "DIRECT_APPLIED_TRANSITION_NOT_ALLOWED",
        )
        self.from_status = from_status


class AlreadySubmittedError(ApplicationTrackingError):
    def __init__(self, application_id: str) -> None:
        super().__init__(
            f"Application '{application_id}' has already been submitted and its snapshot is immutable.",
            "APPLICATION_ALREADY_SUBMITTED",
        )
        self.application_id = application_id


def validate_status_transition(
    from_status: ApplicationStatus | str,
    to_status: ApplicationStatus | str,
) -> None:
    """Validate that transition from from_status to to_status is permissible."""
    src = ApplicationStatus(from_status) if isinstance(from_status, str) else from_status
    dst = ApplicationStatus(to_status) if isinstance(to_status, str) else to_status

    if src == dst:
        return

    allowed = VALID_TRANSITIONS.get(src, set())
    if dst not in allowed:
        raise InvalidStateTransitionError(src.value, dst.value)


def compute_content_sha256(content: str | None) -> str | None:
    """Compute hex SHA-256 digest of content or return None if content is None."""
    if content is None:
        return None
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def verify_snapshot_hashes(
    resume: str | None,
    resume_sha: str | None,
    cover_letter: str | None,
    cover_letter_sha: str | None,
) -> bool:
    """Verify that stored SHA-256 hashes match stored snapshot text."""
    if resume_sha is not None:
        if compute_content_sha256(resume) != resume_sha:
            return False
    if cover_letter_sha is not None:
        if compute_content_sha256(cover_letter) != cover_letter_sha:
            return False
    return True


class TrackJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_posting_id: str = Field(..., min_length=1, max_length=64)
    initial_status: ApplicationStatus = Field(default=ApplicationStatus.SAVED)
    notes: str | None = Field(default=None, max_length=10000)
    follow_up_deadline: datetime | None = None

    @field_validator("initial_status")
    @classmethod
    def validate_initial_status(cls, v: ApplicationStatus) -> ApplicationStatus:
        if v == ApplicationStatus.APPLIED:
            raise ValueError(
                "Initial tracking status cannot be APPLIED. Applications require explicit submission confirmation."
            )
        return v


class StatusTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_status: ApplicationStatus
    reason: str | None = Field(default=None, max_length=1000)
    expected_version: int | None = Field(default=None, ge=1)


class SubmissionConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resume_markdown: str | None = Field(default=None, max_length=100000)
    cover_letter_markdown: str | None = Field(default=None, max_length=100000)
    applied_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=10000)
    expected_version: int | None = Field(default=None, ge=1)


class MarkReviewedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewed_resume: str | None = Field(default=None, max_length=100000)
    reviewed_cover_letter: str | None = Field(default=None, max_length=100000)
    expected_version: int | None = Field(default=None, ge=1)


class ApplicationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notes: str | None = Field(default=None, max_length=10000)
    follow_up_deadline: datetime | None = None
    next_interview_at: datetime | None = None
    expected_version: int | None = Field(default=None, ge=1)


class ApplicationStatusHistoryView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    application_id: str
    from_status: str | None
    to_status: str
    transition_reason: str | None
    created_at: datetime


class TrackedApplicationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    job_posting_id: str
    status: str
    notes: str | None
    follow_up_deadline: datetime | None
    next_interview_at: datetime | None
    applied_at: datetime | None
    last_status_change_at: datetime
    submitted_resume_snapshot: str | None
    submitted_cover_letter_snapshot: str | None
    submitted_resume_sha256: str | None
    submitted_cover_letter_sha256: str | None
    reviewed_resume_markdown: str | None
    reviewed_cover_letter_markdown: str | None
    reviewed_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime

    # Denormalized job details for pipeline list views
    job_title: str | None = None
    employer_name: str | None = None
    location: str | None = None
    apply_url: str | None = None
    job_lifecycle_status: str | None = None
    snapshot_hashes_verified: bool = True
    snapshot_hashes_verified: bool = True


class TrackedApplicationDetailView(TrackedApplicationView):
    status_history: list[ApplicationStatusHistoryView] = Field(default_factory=list)
