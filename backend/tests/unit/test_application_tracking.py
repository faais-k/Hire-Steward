"""Unit tests for application tracking domain and service layers.

Verifies:
1. Valid lifecycle state transitions.
2. Discontinuous or illegal status transitions are rejected.
3. Immutable snapshot hashes (SHA-256) at application submission.
4. Concurrency conflict detection using optimistic locking (version token).
5. Duplicate tracking prevention for the same job posting.
6. Non-destructive retention of application history for stale/closed postings.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from alembic import command
from alembic.config import Config

from backend.app.db.models import (
    ApplicationStatusHistory,
    DiscoveryCheckpoint,
    DiscoveryRun,
    EmployerSubscription,
    JobPosting,
    JobPostingSnapshot,
    JobSource,
    TrackedApplication,
)
from backend.app.domain.application_tracking import (
    AlreadySubmittedError,
    ApplicationNotFoundError,
    ApplicationStatus,
    ConcurrencyConflictError,
    DirectAppliedTransitionNotAllowedError,
    DuplicateApplicationTrackingError,
    InvalidStateTransitionError,
    StatusTransitionRequest,
    SubmissionConfirmRequest,
    TrackJobRequest,
    compute_content_sha256,
    validate_status_transition,
    verify_snapshot_hashes,
)
from backend.app.services.application_tracking import (
    build_application_detail_view,
    confirm_application_submission,
    get_tracked_application,
    list_tracked_applications,
    save_or_track_job,
    transition_application_status,
)


@pytest.fixture
def sqlite_session() -> Session:
    """In-memory SQLite session with full schema upgraded via Alembic migrations."""
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    config = Config("backend/alembic.ini")
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    session = Session(engine)
    try:
        yield session
    finally:
        session.close()


def _seed_test_job(session: Session, posting_id: str = "job_test_001") -> JobPosting:
    now = datetime.now(timezone.utc)
    source = session.get(JobSource, "test_src")
    if source is None:
        source = JobSource(
            source_name="test_src",
            display_name="Test Source",
            capability_status="VERIFIED_READ_ONLY",
            is_enabled=True,
        )
        session.add(source)
        session.flush()

    sub = session.scalar(
        select(EmployerSubscription).where(
            EmployerSubscription.source_name == "test_src",
            EmployerSubscription.employer_handle == "test_employer",
        )
    )
    if sub is None:
        sub = EmployerSubscription(
            id=str(uuid4()),
            source_name="test_src",
            employer_handle="test_employer",
            display_name="Test Employer",
            is_enabled=True,
        )
        session.add(sub)
        session.flush()

    run = DiscoveryRun(
        id=str(uuid4()),
        subscription_id=sub.id,
        status="SUCCEEDED",
        finished_at=now,
    )
    session.add(run)
    session.flush()

    raw_hash = hashlib.sha256(posting_id.encode("utf-8")).hexdigest()
    posting = JobPosting(
        id=str(uuid4()),
        subscription_id=sub.id,
        posting_id=posting_id,
        current_raw_hash=raw_hash,
        lifecycle_status="ACTIVE",
        last_seen_run_id=run.id,
        first_observed_at=now,
        last_observed_at=now,
    )
    session.add(posting)
    session.flush()

    snapshot = JobPostingSnapshot(
        id=str(uuid4()),
        subscription_id=sub.id,
        posting_id=posting.id,
        run_id=run.id,
        source_raw_hash=raw_hash,
        title="Test Senior Backend Engineer",
        location="Remote",
        description_plain="Build scalable systems.",
        lists_json=[],
        published_at=now,
        publication_date_status="EXACT",
    )
    session.add(snapshot)
    session.commit()
    session.refresh(posting)
    return posting


# 1. State Machine Transition Tests


def test_valid_status_transitions():
    """Verify expected valid transitions pass without error."""
    # SAVED transitions
    validate_status_transition(ApplicationStatus.SAVED, ApplicationStatus.PREPARING)
    validate_status_transition(ApplicationStatus.SAVED, ApplicationStatus.APPLIED)
    validate_status_transition(ApplicationStatus.SAVED, ApplicationStatus.ARCHIVED)

    # PREPARING transitions
    validate_status_transition(ApplicationStatus.PREPARING, ApplicationStatus.READY_FOR_REVIEW)
    validate_status_transition(ApplicationStatus.PREPARING, ApplicationStatus.APPLIED)
    validate_status_transition(ApplicationStatus.PREPARING, ApplicationStatus.SAVED)
    validate_status_transition(ApplicationStatus.PREPARING, ApplicationStatus.ARCHIVED)

    # READY_FOR_REVIEW transitions
    validate_status_transition(ApplicationStatus.READY_FOR_REVIEW, ApplicationStatus.APPLIED)
    validate_status_transition(ApplicationStatus.READY_FOR_REVIEW, ApplicationStatus.PREPARING)
    validate_status_transition(ApplicationStatus.READY_FOR_REVIEW, ApplicationStatus.ARCHIVED)

    # APPLIED transitions
    validate_status_transition(ApplicationStatus.APPLIED, ApplicationStatus.INTERVIEWING)
    validate_status_transition(ApplicationStatus.APPLIED, ApplicationStatus.REJECTED)
    validate_status_transition(ApplicationStatus.APPLIED, ApplicationStatus.WITHDRAWN)
    validate_status_transition(ApplicationStatus.APPLIED, ApplicationStatus.ARCHIVED)

    # INTERVIEWING transitions
    validate_status_transition(ApplicationStatus.INTERVIEWING, ApplicationStatus.OFFER_RECEIVED)
    validate_status_transition(ApplicationStatus.INTERVIEWING, ApplicationStatus.REJECTED)
    validate_status_transition(ApplicationStatus.INTERVIEWING, ApplicationStatus.WITHDRAWN)
    validate_status_transition(ApplicationStatus.INTERVIEWING, ApplicationStatus.ARCHIVED)

    # OFFER_RECEIVED transitions
    validate_status_transition(ApplicationStatus.OFFER_RECEIVED, ApplicationStatus.WITHDRAWN)
    validate_status_transition(ApplicationStatus.OFFER_RECEIVED, ApplicationStatus.ARCHIVED)

    # ARCHIVED transitions (revival back to SAVED)
    validate_status_transition(ApplicationStatus.ARCHIVED, ApplicationStatus.SAVED)

    # Self transitions
    validate_status_transition(ApplicationStatus.SAVED, ApplicationStatus.SAVED)
    validate_status_transition(ApplicationStatus.APPLIED, ApplicationStatus.APPLIED)


def test_invalid_status_transitions():
    """Verify illegal jumps across non-adjacent lifecycle phases are rejected."""
    # Cannot jump from SAVED directly to OFFER_RECEIVED or INTERVIEWING
    with pytest.raises(InvalidStateTransitionError):
        validate_status_transition(ApplicationStatus.SAVED, ApplicationStatus.OFFER_RECEIVED)
    with pytest.raises(InvalidStateTransitionError):
        validate_status_transition(ApplicationStatus.SAVED, ApplicationStatus.INTERVIEWING)

    # Cannot jump from PREPARING directly to OFFER_RECEIVED
    with pytest.raises(InvalidStateTransitionError):
        validate_status_transition(ApplicationStatus.PREPARING, ApplicationStatus.OFFER_RECEIVED)

    # Cannot unapply back to SAVED or PREPARING once APPLIED
    with pytest.raises(InvalidStateTransitionError):
        validate_status_transition(ApplicationStatus.APPLIED, ApplicationStatus.SAVED)
    with pytest.raises(InvalidStateTransitionError):
        validate_status_transition(ApplicationStatus.APPLIED, ApplicationStatus.PREPARING)

    # Cannot jump from REJECTED or WITHDRAWN to OFFER_RECEIVED
    with pytest.raises(InvalidStateTransitionError):
        validate_status_transition(ApplicationStatus.REJECTED, ApplicationStatus.OFFER_RECEIVED)
    with pytest.raises(InvalidStateTransitionError):
        validate_status_transition(ApplicationStatus.WITHDRAWN, ApplicationStatus.OFFER_RECEIVED)


# 2. Content Hash Verification


def test_compute_content_sha256():
    """Verify deterministic hash computation and null handling."""
    assert compute_content_sha256(None) is None
    sample = "# Candidate Resume\n\nExperience: 5 years Python"
    expected = hashlib.sha256(sample.encode("utf-8")).hexdigest()
    assert compute_content_sha256(sample) == expected


# 3. Service Layer and Persistence Tests


def test_save_or_track_job_lifecycle(sqlite_session: Session):
    """Verify tracking a job creates initial record, history, and version token."""
    posting = _seed_test_job(sqlite_session, "posting_001")
    req = TrackJobRequest(job_posting_id=posting.id, notes="Interested in core platform role")
    app = save_or_track_job(sqlite_session, req)

    assert app.id is not None
    assert app.job_posting_id == posting.id
    assert app.status == ApplicationStatus.SAVED.value
    assert app.version == 1
    assert app.notes == "Interested in core platform role"

    # History record created
    history = sqlite_session.scalars(
        select(ApplicationStatusHistory).where(ApplicationStatusHistory.application_id == app.id)
    ).all()
    assert len(history) == 1
    assert history[0].from_status is None
    assert history[0].to_status == ApplicationStatus.SAVED.value


def test_duplicate_tracking_prevention(sqlite_session: Session):
    """Verify attempting to track the same job posting twice fails."""
    posting = _seed_test_job(sqlite_session, "posting_duplicate")
    req = TrackJobRequest(job_posting_id=posting.id)
    save_or_track_job(sqlite_session, req)

    with pytest.raises(DuplicateApplicationTrackingError):
        save_or_track_job(sqlite_session, req)


def test_concurrency_conflict_token(sqlite_session: Session):
    """Verify stale expected_version triggers ConcurrencyConflictError."""
    posting = _seed_test_job(sqlite_session, "posting_concurrency")
    app = save_or_track_job(sqlite_session, TrackJobRequest(job_posting_id=posting.id))
    assert app.version == 1

    # Transition with correct expected version
    transition_application_status(
        sqlite_session,
        app.id,
        StatusTransitionRequest(target_status=ApplicationStatus.PREPARING, expected_version=1),
    )
    sqlite_session.refresh(app)
    assert app.version == 2
    assert app.status == ApplicationStatus.PREPARING.value

    # Attempting mutation with outdated version 1 fails
    with pytest.raises(ConcurrencyConflictError):
        transition_application_status(
            sqlite_session,
            app.id,
            StatusTransitionRequest(target_status=ApplicationStatus.READY_FOR_REVIEW, expected_version=1),
        )


def test_submission_confirmation_freezes_snapshot(sqlite_session: Session):
    """Verify confirming application freezes submitted materials with SHA-256 hashes."""
    posting = _seed_test_job(sqlite_session, "posting_submission")
    app = save_or_track_job(sqlite_session, TrackJobRequest(job_posting_id=posting.id))

    resume_content = "# Tailored Resume\n\nSenior Backend Engineer"
    cover_letter_content = "# Cover Letter\n\nDear Hiring Team"
    resume_sha = hashlib.sha256(resume_content.encode("utf-8")).hexdigest()
    cover_sha = hashlib.sha256(cover_letter_content.encode("utf-8")).hexdigest()

    app = confirm_application_submission(
        sqlite_session,
        app.id,
        SubmissionConfirmRequest(
            resume_markdown=resume_content,
            cover_letter_markdown=cover_letter_content,
            notes="Applied through company portal directly",
        ),
    )

    assert app.status == ApplicationStatus.APPLIED.value
    assert app.applied_at is not None
    assert app.submitted_resume_snapshot == resume_content
    assert app.submitted_cover_letter_snapshot == cover_letter_content
    assert app.submitted_resume_sha256 == resume_sha
    assert app.submitted_cover_letter_sha256 == cover_sha

    # Status history records APPLIED
    history = sqlite_session.scalars(
        select(ApplicationStatusHistory)
        .where(ApplicationStatusHistory.application_id == app.id)
        .order_by(ApplicationStatusHistory.created_at.asc())
    ).all()
    assert len(history) == 2
    assert history[1].from_status == ApplicationStatus.SAVED.value
    assert history[1].to_status == ApplicationStatus.APPLIED.value


def test_stale_or_closed_job_preserves_application_history(sqlite_session: Session):
    """Verify tracked application history is preserved when job posting becomes STALE or REMOVED."""
    posting = _seed_test_job(sqlite_session, "posting_stale")
    app = save_or_track_job(sqlite_session, TrackJobRequest(job_posting_id=posting.id))

    # Mark posting STALE
    posting.lifecycle_status = "STALE"
    sqlite_session.commit()

    # Tracked application is still accessible and reflects current lifecycle status
    detail = build_application_detail_view(sqlite_session, app)
    assert detail.job_lifecycle_status == "STALE"
    assert detail.status == ApplicationStatus.SAVED.value



def test_direct_applied_transition_disallowed(sqlite_session: Session):
    """Verify that transitioning to APPLIED via transition_application_status is blocked."""
    posting = _seed_test_job(sqlite_session, "posting_no_direct_applied")
    app = save_or_track_job(sqlite_session, TrackJobRequest(job_posting_id=posting.id))

    with pytest.raises(DirectAppliedTransitionNotAllowedError):
        transition_application_status(
            sqlite_session,
            app.id,
            StatusTransitionRequest(target_status=ApplicationStatus.APPLIED),
        )


def test_initial_applied_status_rejected(sqlite_session: Session):
    """Verify that creating a tracked application directly with APPLIED is rejected."""
    posting = _seed_test_job(sqlite_session, "posting_no_initial_applied")
    with pytest.raises(Exception):
        save_or_track_job(
            sqlite_session,
            TrackJobRequest.model_validate({"job_posting_id": posting.id, "initial_status": "APPLIED"}),
        )


def test_repeated_submission_confirmation_rejected(sqlite_session: Session):
    """Verify that repeated submission confirmation fails and does not alter snapshot."""
    posting = _seed_test_job(sqlite_session, "posting_repeat_submit")
    app = save_or_track_job(sqlite_session, TrackJobRequest(job_posting_id=posting.id))

    resume_original = "# Original Resume"
    cover_original = "# Original Cover Letter"
    confirm_application_submission(
        sqlite_session,
        app.id,
        SubmissionConfirmRequest(
            resume_markdown=resume_original,
            cover_letter_markdown=cover_original,
        ),
    )

    with pytest.raises(AlreadySubmittedError):
        confirm_application_submission(
            sqlite_session,
            app.id,
            SubmissionConfirmRequest(
                resume_markdown="# Mutated Resume",
                cover_letter_markdown="# Mutated Cover Letter",
            ),
        )

    sqlite_session.refresh(app)
    assert app.submitted_resume_snapshot == resume_original
    assert app.submitted_cover_letter_snapshot == cover_original


def test_cannot_unapply_previously_submitted_application(sqlite_session: Session):
    """Verify that once submitted, an application cannot revert to SAVED or PREPARING."""
    posting = _seed_test_job(sqlite_session, "posting_no_unapply")
    app = save_or_track_job(sqlite_session, TrackJobRequest(job_posting_id=posting.id))
    confirm_application_submission(
        sqlite_session,
        app.id,
        SubmissionConfirmRequest(resume_markdown="# Resume"),
    )

    # Archive it
    transition_application_status(
        sqlite_session,
        app.id,
        StatusTransitionRequest(target_status=ApplicationStatus.ARCHIVED),
    )

    # Attempt to restore to SAVED must fail
    with pytest.raises(InvalidStateTransitionError):
        transition_application_status(
            sqlite_session,
            app.id,
            StatusTransitionRequest(target_status=ApplicationStatus.SAVED),
        )


def test_verify_snapshot_hashes_integrity():
    """Verify that hash verification detects matching and tampered snapshot content."""
    sample = "# My Resume"
    valid_sha = hashlib.sha256(sample.encode("utf-8")).hexdigest()
    assert verify_snapshot_hashes(sample, valid_sha, None, None) is True
    assert verify_snapshot_hashes(sample, "tampered_hash_0123456789abcdef", None, None) is False


def test_archiving_rejecting_withdrawing_preserves_status_history(sqlite_session: Session):
    """Verify that archiving, rejecting, withdrawing, and concluding preserve full status history."""
    posting1 = _seed_test_job(sqlite_session, "posting_lifecycle_1")
    app1 = save_or_track_job(sqlite_session, TrackJobRequest(job_posting_id=posting1.id))

    # SAVED -> PREPARING
    transition_application_status(
        sqlite_session,
        app1.id,
        StatusTransitionRequest(target_status=ApplicationStatus.PREPARING, reason="Drafting resume"),
    )
    # PREPARING -> READY_FOR_REVIEW
    transition_application_status(
        sqlite_session,
        app1.id,
        StatusTransitionRequest(target_status=ApplicationStatus.READY_FOR_REVIEW, reason="Reviewed drafts"),
    )
    # READY_FOR_REVIEW -> APPLIED
    confirm_application_submission(
        sqlite_session,
        app1.id,
        SubmissionConfirmRequest(resume_markdown="# Resume", notes="Submitted on company website"),
    )
    # APPLIED -> INTERVIEWING
    transition_application_status(
        sqlite_session,
        app1.id,
        StatusTransitionRequest(target_status=ApplicationStatus.INTERVIEWING, reason="Phone screen scheduled"),
    )
    # INTERVIEWING -> OFFER_RECEIVED
    transition_application_status(
        sqlite_session,
        app1.id,
        StatusTransitionRequest(target_status=ApplicationStatus.OFFER_RECEIVED, reason="Received offer letter"),
    )
    # OFFER_RECEIVED -> WITHDRAWN
    transition_application_status(
        sqlite_session,
        app1.id,
        StatusTransitionRequest(target_status=ApplicationStatus.WITHDRAWN, reason="Accepted alternate offer"),
    )
    # WITHDRAWN -> ARCHIVED
    transition_application_status(
        sqlite_session,
        app1.id,
        StatusTransitionRequest(target_status=ApplicationStatus.ARCHIVED, reason="Concluded application search"),
    )

    detail1 = build_application_detail_view(sqlite_session, app1)
    assert detail1.status == "ARCHIVED"
    assert len(detail1.status_history) == 8
    expected_transitions = [
        (None, "SAVED"),
        ("SAVED", "PREPARING"),
        ("PREPARING", "READY_FOR_REVIEW"),
        ("READY_FOR_REVIEW", "APPLIED"),
        ("APPLIED", "INTERVIEWING"),
        ("INTERVIEWING", "OFFER_RECEIVED"),
        ("OFFER_RECEIVED", "WITHDRAWN"),
        ("WITHDRAWN", "ARCHIVED"),
    ]
    actual_transitions = [(h.from_status, h.to_status) for h in detail1.status_history]
    assert actual_transitions == expected_transitions

    # Test rejecting path: SAVED -> APPLIED -> REJECTED -> ARCHIVED
    posting2 = _seed_test_job(sqlite_session, "posting_lifecycle_2")
    app2 = save_or_track_job(sqlite_session, TrackJobRequest(job_posting_id=posting2.id))
    confirm_application_submission(
        sqlite_session,
        app2.id,
        SubmissionConfirmRequest(resume_markdown="# Resume 2"),
    )
    transition_application_status(
        sqlite_session,
        app2.id,
        StatusTransitionRequest(target_status=ApplicationStatus.REJECTED, reason="Position filled"),
    )
    transition_application_status(
        sqlite_session,
        app2.id,
        StatusTransitionRequest(target_status=ApplicationStatus.ARCHIVED, reason="Archived rejection"),
    )

    detail2 = build_application_detail_view(sqlite_session, app2)
    assert detail2.status == "ARCHIVED"
    assert len(detail2.status_history) == 4
    actual_transitions2 = [(h.from_status, h.to_status) for h in detail2.status_history]
    assert actual_transitions2 == [
        (None, "SAVED"),
        ("SAVED", "APPLIED"),
        ("APPLIED", "REJECTED"),
        ("REJECTED", "ARCHIVED"),
    ]
