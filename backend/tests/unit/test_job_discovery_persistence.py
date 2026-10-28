"""Unit tests for job discovery persistence models, migrations, domain errors, and service operations."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.models import (
    DiscoveryCheckpoint,
    DiscoveryRun,
    EmployerSubscription,
    JobPosting,
    JobPostingSnapshot,
    JobSource,
)
from backend.app.domain.job_posting import (
    CircuitBreakerTrippedError,
    ClosedPostingReappearedError,
    DiscoveryRunStatus,
    InvalidPaginationBoundsError,
    JobDiscoveryError,
    LeaseFencingError,
    NormalizedPosting,
    PostingLifecycleStatus,
    PublicationDateStatus,
    SourceCapabilityStatus,
    SourceGloballyDisabledError,
    SourceNotApprovedError,
    SourceTermsReviewStaleError,
    SubscriptionDisabledError,
)
from backend.app.services.job_discovery import (
    begin_discovery_run,
    complete_discovery_run,
    create_employer_subscription,
    fail_discovery_run,
    fenced_page_commit,
    get_subscription_checkpoint,
    interrupt_discovery_run,
    renew_subscription_lease,
    set_employer_subscription_enabled,
    verify_source_authorization_gate,
)


def test_migration_0004_metadata_fits_constraints() -> None:
    script = ScriptDirectory.from_config(Config("backend/alembic.ini"))
    rev = script.get_revision("0004_job_discovery_persistence")
    assert rev is not None
    assert rev.revision == "0004_job_discovery_persistence"
    assert len(rev.revision) <= 32
    assert rev.down_revision == "0003_candidate_evidence"


def test_models_declare_required_constraints_and_composite_keys() -> None:
    source_constraints = {c.name for c in JobSource.__table__.constraints if c.name}
    assert {
        "pk_job_sources",
        "ck_job_sources_status",
        "ck_job_sources_active_gate",
        "ck_job_sources_rate_positive",
    } <= source_constraints

    sub_constraints = {c.name for c in EmployerSubscription.__table__.constraints if c.name}
    assert {
        "pk_employer_subscriptions",
        "fk_subscriptions_source",
        "uq_employer_subscriptions_identity",
        "ck_subscriptions_handle_format",
        "ck_subscriptions_lease_pair",
    } <= sub_constraints
    assert "ix_subscriptions_pollable" in {i.name for i in EmployerSubscription.__table__.indexes}

    run_constraints = {c.name for c in DiscoveryRun.__table__.constraints if c.name}
    assert {
        "pk_discovery_runs",
        "fk_discovery_runs_subscription",
        "uq_discovery_runs_id_subscription",
        "ck_discovery_runs_status",
        "ck_discovery_runs_page_limit",
        "ck_discovery_runs_skip_nonneg",
        "ck_discovery_runs_counts_nonneg",
        "ck_discovery_runs_termination",
    } <= run_constraints

    posting_constraints = {c.name for c in JobPosting.__table__.constraints if c.name}
    assert {
        "pk_job_postings",
        "fk_job_postings_subscription",
        "uq_job_postings_identity",
        "uq_job_postings_id_subscription",
        "fk_job_postings_run_composite",
        "ck_job_postings_posting_id",
        "ck_job_postings_hash_format",
        "ck_job_postings_lifecycle",
        "ck_job_postings_misses_nonneg",
        "ck_job_postings_version_positive",
    } <= posting_constraints

    snapshot_constraints = {c.name for c in JobPostingSnapshot.__table__.constraints if c.name}
    assert {
        "pk_job_posting_snapshots",
        "fk_snapshots_posting_composite",
        "fk_snapshots_run_composite",
        "uq_snapshots_posting_hash",
        "ck_snapshots_title_nonempty",
        "ck_snapshots_hash_format",
        "ck_snapshots_pub_status",
        "ck_snapshots_pub_exact",
    } <= snapshot_constraints


def test_domain_errors_inherit_from_job_discovery_error() -> None:
    errors = [
        SourceNotApprovedError("not approved"),
        SourceGloballyDisabledError("disabled"),
        SourceTermsReviewStaleError("stale terms"),
        SubscriptionDisabledError("subscription disabled"),
        CircuitBreakerTrippedError("circuit breaker tripped"),
        LeaseFencingError("lease fencing failed"),
        ClosedPostingReappearedError("closed posting reappeared"),
    ]
    for error in errors:
        assert isinstance(error, JobDiscoveryError)
        assert error.code is not None


@pytest.fixture
def sqlite_session():
    """Provides an isolated in-memory SQLite database upgraded via Alembic migrations."""
    from alembic import command

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    config = Config("backend/alembic.ini")
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _setup_approved_source(session: Session, source_name: str = "approved_ats") -> JobSource:
    source = JobSource(
        source_name=source_name,
        display_name="Approved ATS",
        capability_status=SourceCapabilityStatus.VERIFIED_READ_ONLY.value,
        is_enabled=True,
        terms_reviewed_at=datetime.now(timezone.utc),
        terms_review_reference="ADR-0012-approved",
        rate_limit_requests_per_minute=10,
        min_poll_interval_seconds=43200,
    )
    session.add(source)
    session.commit()
    return source


def test_source_authorization_gate_enforcement(sqlite_session: Session) -> None:
    # 1. Lever is seeded as NEEDS_REVIEW and disabled
    with pytest.raises(SourceNotApprovedError):
        verify_source_authorization_gate(sqlite_session, "lever")

    # 2. Add approved source
    _setup_approved_source(sqlite_session, "test_source")
    source, sub = verify_source_authorization_gate(sqlite_session, "test_source")
    assert source.source_name == "test_source"
    assert sub is None

    # 3. Create subscription and test candidate toggle
    subscription = create_employer_subscription(sqlite_session, "test_source", "acme-corp")
    sqlite_session.commit()
    _, sub = verify_source_authorization_gate(sqlite_session, "test_source", subscription.id)
    assert sub is not None
    assert sub.is_enabled is True

    # 4. Disable subscription
    set_employer_subscription_enabled(sqlite_session, subscription.id, is_enabled=False)
    sqlite_session.commit()
    with pytest.raises(SubscriptionDisabledError):
        verify_source_authorization_gate(sqlite_session, "test_source", subscription.id)

    # 5. Tripped circuit breaker
    set_employer_subscription_enabled(sqlite_session, subscription.id, is_enabled=True)
    checkpoint = get_subscription_checkpoint(sqlite_session, subscription.id)
    checkpoint.circuit_breaker_tripped = True
    checkpoint.circuit_breaker_reason = "RATE_LIMIT_429"
    checkpoint.circuit_breaker_tripped_at = datetime.now(timezone.utc)
    sqlite_session.commit()
    with pytest.raises(CircuitBreakerTrippedError):
        verify_source_authorization_gate(sqlite_session, "test_source", subscription.id)


def test_discovery_run_lifecycle_and_concurrent_lease_skip(sqlite_session: Session) -> None:
    _setup_approved_source(sqlite_session, "test_source")
    sub = create_employer_subscription(sqlite_session, "test_source", "sample-corp")
    sqlite_session.commit()

    # Invalid page bounds
    with pytest.raises(InvalidPaginationBoundsError):
        begin_discovery_run(sqlite_session, sub.id, page_limit=0)
    with pytest.raises(InvalidPaginationBoundsError):
        begin_discovery_run(sqlite_session, sub.id, page_limit=101)

    # First runner acquires lease
    run1, token1 = begin_discovery_run(sqlite_session, sub.id, page_limit=50)
    sqlite_session.commit()
    assert run1.status == DiscoveryRunStatus.RUNNING
    assert token1 is not None

    # Check updated_at was NOT modified during initial acquisition
    sub_row = sqlite_session.get(EmployerSubscription, sub.id)
    initial_updated_at = sub_row.updated_at
    assert sub_row.lease_token == token1

    # Second concurrent runner attempts while lease is active
    run2, token2 = begin_discovery_run(sqlite_session, sub.id, page_limit=50)
    sqlite_session.commit()
    assert token2 is None
    assert run2.status == DiscoveryRunStatus.SKIPPED_CONCURRENT_LEASE
    assert run2.error_code == "LEASE_ACTIVE"
    assert run2.finished_at is not None

    # Lease renewal
    renewed = renew_subscription_lease(sqlite_session, sub.id, token1, duration_minutes=15)
    sqlite_session.commit()
    assert renewed is True
    sqlite_session.refresh(sub_row)
    assert sub_row.updated_at == initial_updated_at  # updated_at preserved!

    # Attempt renewal with invalid token fails
    invalid_renew = renew_subscription_lease(sqlite_session, sub.id, "wrong-token")
    assert invalid_renew is False


def test_fenced_page_commit_and_snapshot_creation(sqlite_session: Session) -> None:
    _setup_approved_source(sqlite_session, "test_source")
    sub = create_employer_subscription(sqlite_session, "test_source", "test-employer")
    sqlite_session.commit()
    run, token = begin_discovery_run(sqlite_session, sub.id, page_limit=10)
    sqlite_session.commit()

    posting1 = NormalizedPosting(
        source="lever",
        employer_handle="test-employer",
        posting_id="post-101",
        title="Software Engineer",
        description_plain="Build great software.",
        source_raw_hash="a" * 64,
    )

    # Override source on sub to match domain posting model
    sub.source_name = "lever"
    sub_source = sqlite_session.get(JobSource, "lever")
    sub_source.capability_status = SourceCapabilityStatus.VERIFIED_READ_ONLY.value
    sub_source.is_enabled = True
    sub_source.terms_reviewed_at = datetime.now(timezone.utc)
    sub_source.terms_review_reference = "ADR-0012"
    sqlite_session.commit()

    # Fenced commit with valid lease
    result = fenced_page_commit(
        sqlite_session,
        subscription_id=sub.id,
        run_id=run.id,
        lease_token=token,
        postings=[posting1],
        page_index=0,
        skip=0,
        page_limit=10,
    )
    sqlite_session.commit()
    assert result.items_new == 1
    assert result.items_duplicate == 0

    # Verify JobPosting and JobPostingSnapshot persisted
    db_posting = sqlite_session.scalar(
        select(JobPosting).where(JobPosting.subscription_id == sub.id, JobPosting.posting_id == "post-101")
    )
    assert db_posting is not None
    assert db_posting.current_raw_hash == "a" * 64
    assert db_posting.version == 1

    snapshots = sqlite_session.scalars(
        select(JobPostingSnapshot).where(JobPostingSnapshot.posting_id == db_posting.id)
    ).all()
    assert len(snapshots) == 1
    assert snapshots[0].source_raw_hash == "a" * 64

    # Second commit with same posting (duplicate hash): no new snapshot created
    result_dup = fenced_page_commit(
        sqlite_session,
        subscription_id=sub.id,
        run_id=run.id,
        lease_token=token,
        postings=[posting1],
        page_index=1,
        skip=1,
        page_limit=10,
    )
    sqlite_session.commit()
    assert result_dup.items_new == 0
    assert result_dup.items_duplicate == 1
    snapshots_after_dup = sqlite_session.scalars(
        select(JobPostingSnapshot).where(JobPostingSnapshot.posting_id == db_posting.id)
    ).all()
    assert len(snapshots_after_dup) == 1  # Unchanged!

    # Third commit with updated payload hash: version increments, new snapshot created
    posting1_updated = NormalizedPosting(
        source="lever",
        employer_handle="test-employer",
        posting_id="post-101",
        title="Software Engineer II",
        description_plain="Build even better software.",
        source_raw_hash="b" * 64,
    )
    result_upd = fenced_page_commit(
        sqlite_session,
        subscription_id=sub.id,
        run_id=run.id,
        lease_token=token,
        postings=[posting1_updated],
        page_index=2,
        skip=2,
        page_limit=10,
    )
    sqlite_session.commit()
    assert result_upd.items_updated == 1
    sqlite_session.refresh(db_posting)
    assert db_posting.version == 2
    assert db_posting.current_raw_hash == "b" * 64
    snapshots_after_upd = sqlite_session.scalars(
        select(JobPostingSnapshot).where(JobPostingSnapshot.posting_id == db_posting.id)
    ).all()
    assert len(snapshots_after_upd) == 2

    # Commit with invalid lease token raises LeaseFencingError
    with pytest.raises(LeaseFencingError):
        fenced_page_commit(
            sqlite_session,
            subscription_id=sub.id,
            run_id=run.id,
            lease_token="invalid-token",
            postings=[posting1],
            page_index=3,
            skip=3,
            page_limit=10,
        )


def test_absence_detection_and_run_completion(sqlite_session: Session) -> None:
    _setup_approved_source(sqlite_session, "test_source")
    sub = create_employer_subscription(sqlite_session, "test_source", "absence-corp")
    sub.source_name = "lever"
    sub_source = sqlite_session.get(JobSource, "lever")
    sub_source.capability_status = SourceCapabilityStatus.VERIFIED_READ_ONLY.value
    sub_source.is_enabled = True
    sub_source.terms_reviewed_at = datetime.now(timezone.utc)
    sub_source.terms_review_reference = "ADR-0012"
    sqlite_session.commit()

    run, token = begin_discovery_run(sqlite_session, sub.id)
    sqlite_session.commit()

    posting = NormalizedPosting(
        source="lever",
        employer_handle="absence-corp",
        posting_id="post-vanish",
        title="Disappearing Role",
        description_plain="Role soon to be missing.",
        source_raw_hash="c" * 64,
    )
    fenced_page_commit(sqlite_session, sub.id, run.id, token, [posting], 0, 0, 10)
    sqlite_session.commit()

    # First run completes seeing the posting
    complete_discovery_run(sqlite_session, sub.id, run.id, token, seen_posting_ids={"post-vanish"})
    sqlite_session.commit()
    db_post = sqlite_session.scalar(
        select(JobPosting).where(JobPosting.subscription_id == sub.id, JobPosting.posting_id == "post-vanish")
    )
    assert db_post.consecutive_misses_count == 0
    assert db_post.lifecycle_status == PostingLifecycleStatus.ACTIVE

    # Second run completes omitting the posting: consecutive misses reaches 1 (still ACTIVE)
    run2, token2 = begin_discovery_run(sqlite_session, sub.id)
    sqlite_session.commit()
    complete_discovery_run(sqlite_session, sub.id, run2.id, token2, seen_posting_ids=set())
    sqlite_session.commit()
    sqlite_session.refresh(db_post)
    assert db_post.consecutive_misses_count == 1
    assert db_post.lifecycle_status == PostingLifecycleStatus.ACTIVE

    # Third run completes omitting the posting: consecutive misses reaches 2 -> transitions to REMOVED
    run3, token3 = begin_discovery_run(sqlite_session, sub.id)
    sqlite_session.commit()
    complete_discovery_run(sqlite_session, sub.id, run3.id, token3, seen_posting_ids=set())
    sqlite_session.commit()
    sqlite_session.refresh(db_post)
    assert db_post.consecutive_misses_count == 2
    assert db_post.lifecycle_status == PostingLifecycleStatus.REMOVED


def test_failure_handling_and_circuit_breaker(sqlite_session: Session) -> None:
    _setup_approved_source(sqlite_session, "test_source")
    sub = create_employer_subscription(sqlite_session, "test_source", "fail-corp")
    sqlite_session.commit()
    run, token = begin_discovery_run(sqlite_session, sub.id)
    sqlite_session.commit()

    fail_discovery_run(sqlite_session, sub.id, run.id, token, "HTTP_500", "Internal Server Error")
    sqlite_session.commit()
    checkpoint = get_subscription_checkpoint(sqlite_session, sub.id)
    assert checkpoint.consecutive_failure_count == 1
    assert checkpoint.circuit_breaker_tripped is False

    # Lease is released on failure
    sub_row = sqlite_session.get(EmployerSubscription, sub.id)
    assert sub_row.lease_token is None

    # Second failure
    run2, token2 = begin_discovery_run(sqlite_session, sub.id)
    sqlite_session.commit()
    fail_discovery_run(sqlite_session, sub.id, run2.id, token2, "HTTP_500")
    sqlite_session.commit()
    sqlite_session.refresh(checkpoint)
    assert checkpoint.consecutive_failure_count == 2
    assert checkpoint.circuit_breaker_tripped is False

    # Third failure trips circuit breaker
    run3, token3 = begin_discovery_run(sqlite_session, sub.id)
    sqlite_session.commit()
    fail_discovery_run(sqlite_session, sub.id, run3.id, token3, "HTTP_500")
    sqlite_session.commit()
    sqlite_session.refresh(checkpoint)
    assert checkpoint.consecutive_failure_count == 3
    assert checkpoint.circuit_breaker_tripped is True
    assert checkpoint.circuit_breaker_reason == "HTTP_500"
    assert checkpoint.circuit_breaker_tripped_at is not None

    # Subsequent run attempt is blocked by circuit breaker
    with pytest.raises(CircuitBreakerTrippedError):
        begin_discovery_run(sqlite_session, sub.id)


def test_atomic_rollback_on_snapshot_failure(sqlite_session: Session) -> None:
    _setup_approved_source(sqlite_session, "test_source")
    sub = create_employer_subscription(sqlite_session, "test_source", "atomic-corp")
    sub.source_name = "lever"
    sub_source = sqlite_session.get(JobSource, "lever")
    sub_source.capability_status = SourceCapabilityStatus.VERIFIED_READ_ONLY.value
    sub_source.is_enabled = True
    sub_source.terms_reviewed_at = datetime.now(timezone.utc)
    sub_source.terms_review_reference = "ADR-0012"
    sqlite_session.commit()

    run, token = begin_discovery_run(sqlite_session, sub.id)
    sqlite_session.commit()

    posting1 = NormalizedPosting(
        source="lever",
        employer_handle="atomic-corp",
        posting_id="post-atomic-1",
        title="Atomic Engineer",
        description_plain="Transactional integrity required.",
        source_raw_hash="1" * 64,
    )

    # 1. First successfully commit version 1
    result = fenced_page_commit(sqlite_session, sub.id, run.id, token, [posting1], 0, 0, 10)
    sqlite_session.commit()
    assert result.items_new == 1

    db_posting = sqlite_session.scalar(
        select(JobPosting).where(JobPosting.subscription_id == sub.id, JobPosting.posting_id == "post-atomic-1")
    )
    assert db_posting is not None
    assert db_posting.version == 1
    assert db_posting.current_raw_hash == "1" * 64

    # 2. Update attempt with injected failure during snapshot creation
    posting1_updated = NormalizedPosting(
        source="lever",
        employer_handle="atomic-corp",
        posting_id="post-atomic-1",
        title="Updated Atomic Engineer",
        description_plain="Failure injected on snapshot.",
        source_raw_hash="2" * 64,
    )

    with patch.object(
        JobPostingSnapshot,
        "__init__",
        side_effect=RuntimeError("Simulated DB snapshot insertion failure"),
    ):
        with pytest.raises(RuntimeError, match="Simulated DB snapshot insertion failure"):
            fenced_page_commit(
                sqlite_session,
                subscription_id=sub.id,
                run_id=run.id,
                lease_token=token,
                postings=[posting1_updated],
                page_index=1,
                skip=1,
                page_limit=10,
            )

    # Verify atomic rollback: neither posting version/hash nor snapshot partially committed
    sqlite_session.expire_all()
    rolled_back_posting = sqlite_session.scalar(
        select(JobPosting).where(JobPosting.subscription_id == sub.id, JobPosting.posting_id == "post-atomic-1")
    )
    assert rolled_back_posting.version == 1
    assert rolled_back_posting.current_raw_hash == "1" * 64

    snapshots = sqlite_session.scalars(
        select(JobPostingSnapshot).where(JobPostingSnapshot.posting_id == rolled_back_posting.id)
    ).all()
    assert len(snapshots) == 1
    assert snapshots[0].source_raw_hash == "1" * 64


def test_unobserved_posting_transitions_to_stale(sqlite_session: Session) -> None:
    _setup_approved_source(sqlite_session, "test_source")
    sub = create_employer_subscription(sqlite_session, "test_source", "stale-corp")
    sub.source_name = "lever"
    sub_source = sqlite_session.get(JobSource, "lever")
    sub_source.capability_status = SourceCapabilityStatus.VERIFIED_READ_ONLY.value
    sub_source.is_enabled = True
    sub_source.terms_reviewed_at = datetime.now(timezone.utc)
    sub_source.terms_review_reference = "ADR-0012"
    sqlite_session.commit()

    run, token = begin_discovery_run(sqlite_session, sub.id)
    sqlite_session.commit()

    posting = NormalizedPosting(
        source="lever",
        employer_handle="stale-corp",
        posting_id="post-stale-test",
        title="Ancient Role",
        description_plain="Posted long ago.",
        source_raw_hash="9" * 64,
    )
    fenced_page_commit(sqlite_session, sub.id, run.id, token, [posting], 0, 0, 10)
    complete_discovery_run(sqlite_session, sub.id, run.id, token, seen_posting_ids={"post-stale-test"})
    sqlite_session.commit()

    db_post = sqlite_session.scalar(
        select(JobPosting).where(JobPosting.subscription_id == sub.id, JobPosting.posting_id == "post-stale-test")
    )
    assert db_post.lifecycle_status == PostingLifecycleStatus.ACTIVE

    # Simulate that 31 days have passed since last observation
    now = datetime.now(timezone.utc)
    db_post.last_observed_at = now - timedelta(days=31)
    sqlite_session.commit()

    # Next run omits the posting
    run2, token2 = begin_discovery_run(sqlite_session, sub.id)
    sqlite_session.commit()
    complete_discovery_run(sqlite_session, sub.id, run2.id, token2, seen_posting_ids=set())
    sqlite_session.commit()

    sqlite_session.refresh(db_post)
    # Transitions to STALE because unobserved for > 30 days
    assert db_post.lifecycle_status == PostingLifecycleStatus.STALE


def test_interrupt_discovery_run_lifecycle(sqlite_session: Session) -> None:
    _setup_approved_source(sqlite_session, "test_source")
    sub = create_employer_subscription(sqlite_session, "test_source", "interrupt-corp")
    sqlite_session.commit()

    run, token = begin_discovery_run(sqlite_session, sub.id)
    sqlite_session.commit()
    assert run.status == DiscoveryRunStatus.RUNNING

    # Runner receives cancellation signal or interruption
    interrupted_run = interrupt_discovery_run(sqlite_session, sub.id, run.id, token, reason="SIGINT_RECEIVED")
    sqlite_session.commit()

    assert interrupted_run is not None
    assert interrupted_run.status == DiscoveryRunStatus.INTERRUPTED
    assert interrupted_run.error_code == "SIGINT_RECEIVED"
    assert interrupted_run.finished_at is not None

    # Lease is released
    sub_row = sqlite_session.get(EmployerSubscription, sub.id)
    assert sub_row.lease_token is None
    assert sub_row.lease_expires_at is None

    # Checkpoint circuit breaker is NOT tripped or incremented
    checkpoint = get_subscription_checkpoint(sqlite_session, sub.id)
    assert checkpoint.consecutive_failure_count == 0
    assert checkpoint.circuit_breaker_tripped is False


def test_source_terms_review_staleness_and_boundary_checks(sqlite_session: Session) -> None:
    source = _setup_approved_source(sqlite_session, "boundary_ats")
    fixed_now = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)

    with patch("backend.app.services.job_discovery._get_db_wall_clock", return_value=fixed_now):
        # 1. Missing timestamp -> raises error
        source.terms_reviewed_at = None
        sqlite_session.commit()
        with pytest.raises(SourceTermsReviewStaleError, match="stale, future, or missing"):
            verify_source_authorization_gate(sqlite_session, "boundary_ats")

        # 2. Missing review reference -> raises error even with fresh timestamp
        source.terms_reviewed_at = fixed_now - timedelta(days=10)
        source.terms_review_reference = None
        sqlite_session.commit()
        with pytest.raises(SourceTermsReviewStaleError, match="stale, future, or missing"):
            verify_source_authorization_gate(sqlite_session, "boundary_ats")

        source.terms_review_reference = "ADR-0012-approved"

        # 3. Timestamp in the future (+1 second and +5 days) -> raises error
        source.terms_reviewed_at = fixed_now + timedelta(seconds=1)
        sqlite_session.commit()
        with pytest.raises(SourceTermsReviewStaleError, match="stale, future, or missing"):
            verify_source_authorization_gate(sqlite_session, "boundary_ats")

        source.terms_reviewed_at = fixed_now + timedelta(days=5)
        sqlite_session.commit()
        with pytest.raises(SourceTermsReviewStaleError, match="stale, future, or missing"):
            verify_source_authorization_gate(sqlite_session, "boundary_ats")

        # 4. Timestamp exactly 365 days old -> boundary passes
        source.terms_reviewed_at = fixed_now - timedelta(days=365)
        sqlite_session.commit()
        verified_src, _ = verify_source_authorization_gate(sqlite_session, "boundary_ats")
        assert verified_src.source_name == "boundary_ats"

        # 5. Timestamp just older than 365 days (+1 second) -> boundary raises error
        source.terms_reviewed_at = fixed_now - timedelta(days=365, seconds=1)
        sqlite_session.commit()
        with pytest.raises(SourceTermsReviewStaleError, match="stale, future, or missing"):
            verify_source_authorization_gate(sqlite_session, "boundary_ats")

        # 6. Fresh valid timestamp (30 days old) -> passes
        source.terms_reviewed_at = fixed_now - timedelta(days=30)
        sqlite_session.commit()
        verified_fresh, _ = verify_source_authorization_gate(sqlite_session, "boundary_ats")
        assert verified_fresh.source_name == "boundary_ats"

        # 7. Source not approved (NEEDS_REVIEW and disabled) with fresh timestamp -> raises SourceNotApprovedError
        source.is_enabled = False
        source.capability_status = SourceCapabilityStatus.NEEDS_REVIEW.value
        sqlite_session.commit()
        with pytest.raises(SourceNotApprovedError):
            verify_source_authorization_gate(sqlite_session, "boundary_ats")

        # 8. Source globally disabled with fresh timestamp -> raises SourceGloballyDisabledError
        source.capability_status = SourceCapabilityStatus.VERIFIED_READ_ONLY.value
        source.is_enabled = False
        sqlite_session.commit()
        with pytest.raises(SourceGloballyDisabledError):
            verify_source_authorization_gate(sqlite_session, "boundary_ats")
