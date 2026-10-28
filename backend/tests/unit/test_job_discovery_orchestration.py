"""Unit tests for offline end-to-end job discovery workflow orchestration and adversarial edge cases."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.adapters.job_sources import FixtureJobSourceAdapter
from backend.app.adapters.lever import LeverPostingsAdapter
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
    InvalidPostingPayloadError,
    PaginationLoopError,
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
    create_employer_subscription,
    orchestrate_discovery_run,
    verify_source_authorization_gate,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "lever"


def load_fixture(name: str):
    with open(FIXTURES_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def sqlite_session():
    """Provides an isolated in-memory SQLite database upgraded via Alembic migrations."""
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


def _setup_approved_source(session: Session, source_name: str = "fixture_ats") -> JobSource:
    source = JobSource(
        source_name=source_name,
        display_name="Fixture Approved ATS",
        capability_status=SourceCapabilityStatus.VERIFIED_READ_ONLY.value,
        is_enabled=True,
        terms_reviewed_at=datetime.now(timezone.utc),
        terms_review_reference="ADR-0012-fixture-approved",
        rate_limit_requests_per_minute=10,
        min_poll_interval_seconds=43200,
    )
    session.add(source)
    session.commit()
    return source


# -----------------------------------------------------------------------------
# 1. Successful Discovery Scenarios
# -----------------------------------------------------------------------------


def test_orchestrate_discovery_run_single_page_success(sqlite_session: Session) -> None:
    source = _setup_approved_source(sqlite_session, "fixture_lever")
    sub = create_employer_subscription(
        sqlite_session,
        source_name="fixture_lever",
        employer_handle="example-corp",
        display_name="Example Corp",
    )

    valid_listing = load_fixture("valid_listing.json")
    adapter = FixtureJobSourceAdapter(
        source_name="fixture_lever",
        pages=[valid_listing],
        delegate_adapter=LeverPostingsAdapter(source_name="fixture_lever"),
    )

    result = orchestrate_discovery_run(
        sqlite_session,
        subscription_or_id=sub.id,
        adapter=adapter,
        page_limit=10,
    )

    assert result.status == DiscoveryRunStatus.SUCCEEDED
    assert result.items_seen == 2
    assert result.items_new == 2
    assert result.items_updated == 0
    assert result.items_duplicate == 0
    assert result.pages_processed == 1
    assert result.error_code is None

    # Verify JobPosting persistence
    postings = sqlite_session.scalars(
        select(JobPosting).where(JobPosting.subscription_id == sub.id).order_by(JobPosting.posting_id)
    ).all()
    assert len(postings) == 2
    p1, p2 = postings[0], postings[1]

    assert p1.posting_id == "lever-job-001"
    assert p1.lifecycle_status == PostingLifecycleStatus.ACTIVE
    assert p1.version == 1
    assert p1.last_seen_run_id == result.run_id

    assert p2.posting_id == "lever-job-002"
    assert p2.lifecycle_status == PostingLifecycleStatus.ACTIVE
    assert p2.version == 1
    assert p2.last_seen_run_id == result.run_id

    # Verify JobPostingSnapshot persistence
    snapshots = sqlite_session.scalars(
        select(JobPostingSnapshot).where(JobPostingSnapshot.subscription_id == sub.id)
    ).all()
    assert len(snapshots) == 2
    s1 = next(s for s in snapshots if s.posting_id == p1.id)
    assert s1.title == "Senior Backend Engineer"
    assert s1.location == "Remote - India"
    assert s1.publication_date_status == PublicationDateStatus.EXACT.value
    assert s1.run_id == result.run_id
    assert s1.source_raw_hash == p1.current_raw_hash

    # Verify DiscoveryRun audit record
    run = sqlite_session.get(DiscoveryRun, result.run_id)
    assert run is not None
    assert run.status == DiscoveryRunStatus.SUCCEEDED
    assert run.items_seen_count == 2
    assert run.items_new_count == 2
    assert run.finished_at is not None

    # Verify Checkpoint state
    checkpoint = sqlite_session.get(DiscoveryCheckpoint, sub.id)
    assert checkpoint is not None
    assert checkpoint.last_successful_run_at is not None
    assert checkpoint.consecutive_failure_count == 0
    assert checkpoint.circuit_breaker_tripped is False

    # Verify lease released
    refreshed_sub = sqlite_session.get(EmployerSubscription, sub.id)
    assert refreshed_sub.lease_token is None
    assert refreshed_sub.lease_expires_at is None


def test_orchestrate_discovery_run_multi_page_success(sqlite_session: Session) -> None:
    source = _setup_approved_source(sqlite_session, "fixture_lever")
    sub = create_employer_subscription(sqlite_session, "fixture_lever", "example-corp")

    page_0 = [
        {
            "id": "lever-multipage-001",
            "text": "Frontend Engineer",
            "createdAt": 1700000000000,
            "description": "<p>Build UIs</p>",
            "hostedUrl": "https://jobs.lever.co/example-corp/lever-multipage-001",
        },
        {
            "id": "lever-multipage-002",
            "text": "Backend Engineer",
            "createdAt": 1700000000000,
            "description": "<p>Build APIs</p>",
            "hostedUrl": "https://jobs.lever.co/example-corp/lever-multipage-002",
        },
    ]
    page_1 = [
        {
            "id": "lever-multipage-003",
            "text": "DevOps Engineer",
            "createdAt": 1700000000000,
            "description": "<p>Build Infra</p>",
            "hostedUrl": "https://jobs.lever.co/example-corp/lever-multipage-003",
        }
    ]

    adapter = FixtureJobSourceAdapter(
        source_name="fixture_lever",
        pages=[page_0, page_1],
        delegate_adapter=LeverPostingsAdapter(source_name="fixture_lever"),
    )

    result = orchestrate_discovery_run(
        sqlite_session,
        subscription_or_id=sub.id,
        adapter=adapter,
        page_limit=2,
    )

    assert result.status == DiscoveryRunStatus.SUCCEEDED
    assert result.items_seen == 3
    assert result.items_new == 3
    assert result.pages_processed == 2

    postings = sqlite_session.scalars(
        select(JobPosting).where(JobPosting.subscription_id == sub.id)
    ).all()
    assert len(postings) == 3


# -----------------------------------------------------------------------------
# 2. Deduplication and Change Tracking
# -----------------------------------------------------------------------------


def test_orchestrate_discovery_run_deduplication_idempotent(sqlite_session: Session) -> None:
    _setup_approved_source(sqlite_session, "fixture_lever")
    sub = create_employer_subscription(sqlite_session, "fixture_lever", "example-corp")

    valid_listing = load_fixture("valid_listing.json")
    adapter = FixtureJobSourceAdapter(
        source_name="fixture_lever",
        pages=[valid_listing],
        delegate_adapter=LeverPostingsAdapter(source_name="fixture_lever"),
    )

    # First run
    r1 = orchestrate_discovery_run(sqlite_session, sub.id, adapter, page_limit=10)
    assert r1.status == DiscoveryRunStatus.SUCCEEDED
    assert r1.items_new == 2
    assert r1.items_duplicate == 0

    # Second run with identical fixture data
    r2 = orchestrate_discovery_run(sqlite_session, sub.id, adapter, page_limit=10)
    assert r2.status == DiscoveryRunStatus.SUCCEEDED
    assert r2.items_new == 0
    assert r2.items_updated == 0
    assert r2.items_duplicate == 2

    # Verify no new snapshots created
    snapshots = sqlite_session.scalars(
        select(JobPostingSnapshot).where(JobPostingSnapshot.subscription_id == sub.id)
    ).all()
    assert len(snapshots) == 2

    # Verify posting versions unchanged but last_seen_run_id updated to r2
    postings = sqlite_session.scalars(
        select(JobPosting).where(JobPosting.subscription_id == sub.id)
    ).all()
    for p in postings:
        assert p.version == 1
        assert p.last_seen_run_id == r2.run_id


def test_orchestrate_discovery_run_detects_changes_and_appends_snapshot(
    sqlite_session: Session,
) -> None:
    _setup_approved_source(sqlite_session, "fixture_lever")
    sub = create_employer_subscription(sqlite_session, "fixture_lever", "example-corp")
    sqlite_session.commit()
    sub_id = sub.id

    listing_initial = load_fixture("valid_listing.json")
    adapter1 = FixtureJobSourceAdapter(
        source_name="fixture_lever",
        pages=[listing_initial],
        delegate_adapter=LeverPostingsAdapter(source_name="fixture_lever"),
    )
    r1 = orchestrate_discovery_run(sqlite_session, sub_id, adapter1, page_limit=10)
    assert r1.status == DiscoveryRunStatus.SUCCEEDED

    # Modify item 1: change title and description
    modified_listing = json.loads(json.dumps(listing_initial))
    modified_listing[0]["text"] = "Lead Backend Architect"
    modified_listing[0]["descriptionPlain"] = "Lead high-scale architecture initiatives in Python."

    adapter2 = FixtureJobSourceAdapter(
        source_name="fixture_lever",
        pages=[modified_listing],
        delegate_adapter=LeverPostingsAdapter(source_name="fixture_lever"),
    )
    r2 = orchestrate_discovery_run(sqlite_session, sub_id, adapter2, page_limit=10)

    assert r2.status == DiscoveryRunStatus.SUCCEEDED
    assert r2.items_new == 0
    assert r2.items_updated == 1
    assert r2.items_duplicate == 1

    # Posting version incremented to 2
    p1 = sqlite_session.scalar(
        select(JobPosting).where(
            JobPosting.subscription_id == sub.id,
            JobPosting.posting_id == "lever-job-001",
        )
    )
    assert p1 is not None
    assert p1.version == 2
    assert p1.last_seen_run_id == r2.run_id

    # Item 1 now has two snapshots: historical and updated
    snapshots = sqlite_session.scalars(
        select(JobPostingSnapshot)
        .where(JobPostingSnapshot.posting_id == p1.id)
        .order_by(JobPostingSnapshot.captured_at)
    ).all()
    assert len(snapshots) == 2
    s_old, s_new = snapshots[0], snapshots[1]

    assert s_old.title == "Senior Backend Engineer"
    assert s_old.run_id == r1.run_id

    assert s_new.title == "Lead Backend Architect"
    assert s_new.run_id == r2.run_id
    assert s_new.source_raw_hash == p1.current_raw_hash


# -----------------------------------------------------------------------------
# 3. Absence, Lifecycle Transitions & Confirmed Closed Guard
# -----------------------------------------------------------------------------


def test_orchestrate_discovery_run_absence_transitions_to_removed(
    sqlite_session: Session,
) -> None:
    _setup_approved_source(sqlite_session, "fixture_lever")
    sub = create_employer_subscription(sqlite_session, "fixture_lever", "example-corp")
    sqlite_session.commit()
    sub_id = sub.id

    listing_initial = load_fixture("valid_listing.json")  # has lever-job-001 and lever-job-002
    adapter1 = FixtureJobSourceAdapter(
        "fixture_lever", [listing_initial], LeverPostingsAdapter(source_name="fixture_lever")
    )
    orchestrate_discovery_run(sqlite_session, sub_id, adapter1, page_limit=10)

    # Next run: lever-job-002 is omitted from feed
    feed_omitted = [listing_initial[0]]  # only lever-job-001
    adapter2 = FixtureJobSourceAdapter(
        "fixture_lever", [feed_omitted], LeverPostingsAdapter(source_name="fixture_lever")
    )

    # Miss 1: consecutive_misses_count becomes 1, still ACTIVE
    orchestrate_discovery_run(sqlite_session, sub_id, adapter2, page_limit=10)
    p2 = sqlite_session.scalar(
        select(JobPosting).where(
            JobPosting.subscription_id == sub_id,
            JobPosting.posting_id == "lever-job-002",
        )
    )
    assert p2.consecutive_misses_count == 1
    assert p2.lifecycle_status == PostingLifecycleStatus.ACTIVE
    sqlite_session.rollback()  # End caller inspection transaction before next run

    # Miss 2: consecutive_misses_count becomes 2, transitions to REMOVED
    orchestrate_discovery_run(sqlite_session, sub_id, adapter2, page_limit=10)
    sqlite_session.refresh(p2)
    assert p2.consecutive_misses_count == 2
    assert p2.lifecycle_status == PostingLifecycleStatus.REMOVED
    sqlite_session.rollback()  # End caller inspection transaction before next run

    # Re-observed on run 4: transitions back to ACTIVE and misses reset to 0
    orchestrate_discovery_run(sqlite_session, sub_id, adapter1, page_limit=10)
    sqlite_session.refresh(p2)
    assert p2.consecutive_misses_count == 0
    assert p2.lifecycle_status == PostingLifecycleStatus.ACTIVE


def test_orchestrate_discovery_run_closed_confirmed_guard(sqlite_session: Session) -> None:
    _setup_approved_source(sqlite_session, "fixture_lever")
    sub = create_employer_subscription(sqlite_session, "fixture_lever", "example-corp")

    listing_initial = load_fixture("valid_listing.json")
    adapter = FixtureJobSourceAdapter(
        "fixture_lever", [listing_initial], LeverPostingsAdapter(source_name="fixture_lever")
    )
    orchestrate_discovery_run(sqlite_session, sub.id, adapter, page_limit=10)

    p1 = sqlite_session.scalar(
        select(JobPosting).where(
            JobPosting.subscription_id == sub.id,
            JobPosting.posting_id == "lever-job-001",
        )
    )
    # Candidate manually confirms job is closed
    p1.lifecycle_status = PostingLifecycleStatus.CLOSED_CONFIRMED
    sqlite_session.commit()

    # Re-discovering the closed posting must fail and refuse silent resurrection
    result = orchestrate_discovery_run(sqlite_session, sub.id, adapter, page_limit=10)
    assert result.status == DiscoveryRunStatus.FAILED
    assert result.error_code == "CLOSED_POSTING_REAPPEARED"

    sqlite_session.refresh(p1)
    assert p1.lifecycle_status == PostingLifecycleStatus.CLOSED_CONFIRMED


# -----------------------------------------------------------------------------
# 4. Pagination Failure and Recovery
# -----------------------------------------------------------------------------


def test_orchestrate_discovery_run_page_failure_preserves_page1_and_checkpoint_intact(
    sqlite_session: Session,
) -> None:
    _setup_approved_source(sqlite_session, "fixture_lever")
    sub = create_employer_subscription(sqlite_session, "fixture_lever", "example-corp")
    sqlite_session.commit()
    sub_id = sub.id

    page_0 = [
        {
            "id": "lever-p0-001",
            "text": "Engineer 1",
            "createdAt": 1700000000000,
            "hostedUrl": "https://jobs.lever.co/example-corp/lever-p0-001",
        },
        {
            "id": "lever-p0-002",
            "text": "Engineer 2",
            "createdAt": 1700000000000,
            "hostedUrl": "https://jobs.lever.co/example-corp/lever-p0-002",
        },
    ]
    # Page 1 has invalid malformed payload item (non-dict)
    page_1_malformed = ["not-a-dict"]

    adapter_malformed = FixtureJobSourceAdapter(
        source_name="fixture_lever",
        pages=[page_0, page_1_malformed],
        delegate_adapter=LeverPostingsAdapter(source_name="fixture_lever"),
    )

    result = orchestrate_discovery_run(
        sqlite_session,
        subscription_or_id=sub_id,
        adapter=adapter_malformed,
        page_limit=2,
    )

    assert result.status == DiscoveryRunStatus.FAILED
    assert result.error_code == "INVALID_PAYLOAD_TYPE"
    assert result.pages_processed == 1

    # Page 0 postings WERE committed transactionally
    postings = sqlite_session.scalars(
        select(JobPosting).where(JobPosting.subscription_id == sub.id)
    ).all()
    assert len(postings) == 2

    # Checkpoint was NOT marked successful; failure counter incremented to 1
    checkpoint = sqlite_session.get(DiscoveryCheckpoint, sub.id)
    assert checkpoint.last_successful_run_at is None
    assert checkpoint.consecutive_failure_count == 1

    # Lease was released
    refreshed_sub = sqlite_session.get(EmployerSubscription, sub.id)
    assert refreshed_sub.lease_token is None
    sqlite_session.rollback()  # End caller inspection transaction before next run

    # Now recover with a valid page 1
    page_1_valid = [
        {
            "id": "lever-p1-003",
            "text": "Engineer 3",
            "createdAt": 1700000000000,
            "hostedUrl": "https://jobs.lever.co/example-corp/lever-p1-003",
        }
    ]
    adapter_recovered = FixtureJobSourceAdapter(
        source_name="fixture_lever",
        pages=[page_0, page_1_valid],
        delegate_adapter=LeverPostingsAdapter(source_name="fixture_lever"),
    )

    result_recovered = orchestrate_discovery_run(
        sqlite_session,
        subscription_or_id=sub_id,
        adapter=adapter_recovered,
        page_limit=2,
    )

    assert result_recovered.status == DiscoveryRunStatus.SUCCEEDED
    assert result_recovered.items_seen == 3
    assert result_recovered.items_duplicate == 2  # from page 0
    assert result_recovered.items_new == 1  # from page 1

    # Checkpoint now marked successful and failures reset to 0
    sqlite_session.refresh(checkpoint)
    assert checkpoint.last_successful_run_at is not None
    assert checkpoint.consecutive_failure_count == 0


def test_orchestrate_discovery_run_detects_pagination_cycle(sqlite_session: Session) -> None:
    _setup_approved_source(sqlite_session, "fixture_lever")
    sub = create_employer_subscription(sqlite_session, "fixture_lever", "example-corp")

    page_0 = [
        {
            "id": "lever-cycle-001",
            "text": "Engineer 1",
            "createdAt": 1700000000000,
            "hostedUrl": "https://jobs.lever.co/example-corp/lever-cycle-001",
        },
        {
            "id": "lever-cycle-002",
            "text": "Engineer 2",
            "createdAt": 1700000000000,
            "hostedUrl": "https://jobs.lever.co/example-corp/lever-cycle-002",
        },
    ]
    # Page 1 repeats identical items to page 0 (infinite loop simulation)
    page_1_repeating = page_0

    adapter = FixtureJobSourceAdapter(
        source_name="fixture_lever",
        pages=[page_0, page_1_repeating],
        delegate_adapter=LeverPostingsAdapter(source_name="fixture_lever"),
    )

    result = orchestrate_discovery_run(
        sqlite_session,
        subscription_or_id=sub.id,
        adapter=adapter,
        page_limit=2,
    )

    assert result.status == DiscoveryRunStatus.FAILED
    assert result.error_code == "PAGINATION_CYCLE_DETECTED"


# -----------------------------------------------------------------------------
# 5. Stale Worker & Concurrent Lease Fencing
# -----------------------------------------------------------------------------


def test_orchestrate_discovery_run_stale_worker_fenced_out(sqlite_session: Session) -> None:
    _setup_approved_source(sqlite_session, "fixture_lever")
    sub = create_employer_subscription(sqlite_session, "fixture_lever", "example-corp")

    class InvalidateLeaseDuringFetchAdapter(FixtureJobSourceAdapter):
        def fetch_page(self, employer_handle: str, skip: int, limit: int):
            # Simulate lease loss (e.g. lease expired and acquired by another runner)
            sub_to_invalidate = sqlite_session.get(EmployerSubscription, sub.id)
            sub_to_invalidate.lease_token = "stolen-lease-token"
            sqlite_session.commit()
            return super().fetch_page(employer_handle, skip, limit)

    valid_listing = load_fixture("valid_listing.json")
    adapter = InvalidateLeaseDuringFetchAdapter(
        source_name="fixture_lever",
        pages=[valid_listing],
        delegate_adapter=LeverPostingsAdapter(source_name="fixture_lever"),
    )

    result = orchestrate_discovery_run(
        sqlite_session,
        subscription_or_id=sub.id,
        adapter=adapter,
        page_limit=10,
    )

    assert result.status == DiscoveryRunStatus.FAILED
    assert result.error_code == "LEASE_FENCING_FAILED"

    # Stale worker was rejected; zero postings written
    postings = sqlite_session.scalars(
        select(JobPosting).where(JobPosting.subscription_id == sub.id)
    ).all()
    assert len(postings) == 0

    # Fenced out stale worker does NOT mutate checkpoint failure counter
    checkpoint = sqlite_session.get(DiscoveryCheckpoint, sub.id)
    assert checkpoint.consecutive_failure_count == 0


def test_orchestrate_discovery_run_concurrent_lease_skipped(sqlite_session: Session) -> None:
    _setup_approved_source(sqlite_session, "fixture_lever")
    sub = create_employer_subscription(sqlite_session, "fixture_lever", "example-corp")

    # Manually hold an active unexpired lease
    sub.lease_token = "active-runner-lease"
    sub.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    sqlite_session.commit()

    valid_listing = load_fixture("valid_listing.json")
    adapter = FixtureJobSourceAdapter(
        "fixture_lever", [valid_listing], LeverPostingsAdapter(source_name="fixture_lever")
    )

    result = orchestrate_discovery_run(sqlite_session, sub.id, adapter, page_limit=10)

    assert result.status == DiscoveryRunStatus.SKIPPED_CONCURRENT_LEASE
    assert result.error_code == "LEASE_ACTIVE"

    # Zero postings written and checkpoint untouched
    postings = sqlite_session.scalars(
        select(JobPosting).where(JobPosting.subscription_id == sub.id)
    ).all()
    assert len(postings) == 0


# -----------------------------------------------------------------------------
# 6. Security and Authorization Gates
# -----------------------------------------------------------------------------


def test_orchestrate_discovery_run_rejected_for_needs_review_source(
    sqlite_session: Session,
) -> None:
    # Lever is seeded as NEEDS_REVIEW and disabled in migration 0004
    sub = create_employer_subscription(sqlite_session, "lever", "example-corp")
    adapter = FixtureJobSourceAdapter("lever", [[]], LeverPostingsAdapter(source_name="lever"))

    with pytest.raises(SourceNotApprovedError):
        orchestrate_discovery_run(sqlite_session, sub.id, adapter)


def test_orchestrate_discovery_run_rejected_for_stale_terms_review(
    sqlite_session: Session,
) -> None:
    source = _setup_approved_source(sqlite_session, "stale_ats")
    source.terms_reviewed_at = datetime.now(timezone.utc) - timedelta(days=366)
    sqlite_session.commit()

    sub = create_employer_subscription(sqlite_session, "stale_ats", "example-corp")
    adapter = FixtureJobSourceAdapter("stale_ats", [[]], LeverPostingsAdapter(source_name="stale_ats"))

    with pytest.raises(SourceTermsReviewStaleError):
        orchestrate_discovery_run(sqlite_session, sub.id, adapter)


def test_orchestrate_discovery_run_rejected_for_tripped_circuit_breaker(
    sqlite_session: Session,
) -> None:
    _setup_approved_source(sqlite_session, "fixture_ats")
    sub = create_employer_subscription(sqlite_session, "fixture_ats", "example-corp")

    checkpoint = sqlite_session.get(DiscoveryCheckpoint, sub.id)
    checkpoint.circuit_breaker_tripped = True
    checkpoint.circuit_breaker_reason = "TRIPPED_TEST"
    checkpoint.circuit_breaker_tripped_at = datetime.now(timezone.utc)
    sqlite_session.commit()

    adapter = FixtureJobSourceAdapter("fixture_ats", [[]], LeverPostingsAdapter(source_name="fixture_ats"))

    with pytest.raises(CircuitBreakerTrippedError):
        orchestrate_discovery_run(sqlite_session, sub.id, adapter)


def test_orchestrate_discovery_run_sanitizes_hostile_content_in_snapshot(
    sqlite_session: Session,
) -> None:
    _setup_approved_source(sqlite_session, "fixture_hostile")
    sub = create_employer_subscription(sqlite_session, "fixture_hostile", "example-corp")

    hostile_fixture = load_fixture("hostile_content.json")
    adapter = FixtureJobSourceAdapter(
        source_name="fixture_hostile",
        pages=[[hostile_fixture]],
        delegate_adapter=LeverPostingsAdapter(source_name="fixture_hostile"),
    )

    result = orchestrate_discovery_run(sqlite_session, sub.id, adapter, page_limit=10)
    assert result.status == DiscoveryRunStatus.SUCCEEDED

    snapshot = sqlite_session.scalar(
        select(JobPostingSnapshot).where(JobPostingSnapshot.subscription_id == sub.id)
    )
    assert snapshot is not None
    assert "Security Analyst" in snapshot.title

    # Script and style tags stripped from plain text description
    assert "<script>" not in snapshot.description_plain
    assert "<style>" not in snapshot.description_plain
    assert "evilCode" not in snapshot.description_plain
    assert ".hidden" not in snapshot.description_plain
    assert "Legitimate job intro." in snapshot.description_plain

    # Prompt injection preserved as data rather than evaluated
    assert "SYSTEM PROMPT:" in snapshot.description_plain

    # Control characters and null bytes stripped
    assert snapshot.location == "Remote"


def test_lever_adapter_fetch_page_raises_not_implemented_offline_only() -> None:
    adapter = LeverPostingsAdapter()
    with pytest.raises(NotImplementedError, match="not authorized or implemented"):
        adapter.fetch_page("example-corp", skip=0, limit=100)


def test_orchestrate_discovery_run_handles_keyboard_interrupt(
    sqlite_session: Session,
) -> None:
    _setup_approved_source(sqlite_session, "fixture_lever")
    sub = create_employer_subscription(sqlite_session, "fixture_lever", "example-corp")

    class InterruptAdapter(FixtureJobSourceAdapter):
        def fetch_page(self, employer_handle: str, skip: int, limit: int):
            raise KeyboardInterrupt("Simulated user interrupt")

    adapter = InterruptAdapter("fixture_lever", [[]], LeverPostingsAdapter(source_name="fixture_lever"))

    result = orchestrate_discovery_run(sqlite_session, sub.id, adapter)
    assert result.status == DiscoveryRunStatus.INTERRUPTED
    assert result.error_code == "RUNNER_INTERRUPTED"

    run = sqlite_session.get(DiscoveryRun, result.run_id)
    assert run.status == DiscoveryRunStatus.INTERRUPTED

    # Lease is released
    sub_refreshed = sqlite_session.get(EmployerSubscription, sub.id)
    assert sub_refreshed.lease_token is None

    # Checkpoint failure counter NOT incremented on interrupt
    checkpoint = sqlite_session.get(DiscoveryCheckpoint, sub.id)
    assert checkpoint.consecutive_failure_count == 0


# -----------------------------------------------------------------------------
# 7. Adversarial Regression Tests: Contract, Pagination, Fencing & Boundaries
# -----------------------------------------------------------------------------


def test_fixture_adapter_rejects_mismatched_delegate_source_name() -> None:
    """Prohibits silent relabeling by rejecting mismatched delegate adapter sources on init."""
    with pytest.raises(ValueError, match="Silent source relabeling is prohibited"):
        FixtureJobSourceAdapter(
            source_name="injected_ats",
            pages=[[]],
            delegate_adapter=LeverPostingsAdapter(source_name="lever"),
        )


def test_fixture_adapter_rejects_parsed_posting_source_mismatch() -> None:
    """Rejects postings whose source does not match the adapter's declared source."""
    class FakeMismatchedDelegate:
        source_name = "custom_ats"
        def parse_posting_payload(self, employer_handle, payload):
            p = LeverPostingsAdapter(source_name="lever").parse_posting_payload(employer_handle, payload)
            return p  # source is "lever"
        def parse_listing_page(self, employer_handle, payload, skip, limit):
            return [self.parse_posting_payload(employer_handle, payload[0])]

    adapter = FixtureJobSourceAdapter(
        source_name="custom_ats",
        pages=[[[load_fixture("valid_detail.json")]]],
        delegate_adapter=FakeMismatchedDelegate(),
    )
    with pytest.raises(InvalidPostingPayloadError, match="does not match fixture adapter source"):
        adapter.parse_listing_page("example-corp", [load_fixture("valid_detail.json")], 0, 10)


def test_fixture_adapter_pagination_different_limits() -> None:
    """Verify that fetch_page respects different limit boundaries cleanly."""
    raw_listing = load_fixture("valid_listing.json")  # 2 items
    adapter = FixtureJobSourceAdapter("fixture_lever", pages=[raw_listing])

    # Caller requests page_limit=1
    page0 = adapter.fetch_page("example-corp", skip=0, limit=1)
    assert len(page0) == 1
    assert page0[0]["id"] == "lever-job-001"

    page1 = adapter.fetch_page("example-corp", skip=1, limit=1)
    assert len(page1) == 1
    assert page1[0]["id"] == "lever-job-002"

    page2 = adapter.fetch_page("example-corp", skip=2, limit=1)
    assert page2 == []


def test_fixture_adapter_pagination_nonzero_offsets() -> None:
    """Verify that fetch_page with non-multiple skip slices from flattened records properly."""
    raw_listing = load_fixture("valid_listing.json")  # 2 items
    adapter = FixtureJobSourceAdapter("fixture_lever", pages=[raw_listing])

    # Offset skip=1, limit=5
    page = adapter.fetch_page("example-corp", skip=1, limit=5)
    assert len(page) == 1
    assert page[0]["id"] == "lever-job-002"


def test_fixture_adapter_flat_records_mode() -> None:
    """Verify FixtureJobSourceAdapter supports flat continuous records cleanly."""
    records = [{"id": f"job-{i}", "text": f"Role {i}", "hostedUrl": f"https://example.com/{i}"} for i in range(5)]
    adapter = FixtureJobSourceAdapter("fixture_lever", records=records)

    p0 = adapter.fetch_page("example-corp", skip=0, limit=2)
    assert len(p0) == 2
    assert p0[0]["id"] == "job-0"

    p1 = adapter.fetch_page("example-corp", skip=2, limit=2)
    assert len(p1) == 2
    assert p1[0]["id"] == "job-2"

    p2 = adapter.fetch_page("example-corp", skip=4, limit=2)
    assert len(p2) == 1
    assert p2[0]["id"] == "job-4"

    p3 = adapter.fetch_page("example-corp", skip=6, limit=2)
    assert p3 == []


def test_fixture_adapter_invalid_json_fixture_fails_safely() -> None:
    """Verify corrupted JSON fixture file raises INVALID_FIXTURE_JSON."""
    with NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        f.write("{invalid json content")
        temp_path = Path(f.name)

    try:
        with pytest.raises(InvalidPostingPayloadError, match="Failed to parse fixture file"):
            FixtureJobSourceAdapter.from_json_files("test_src", [temp_path])
    finally:
        temp_path.unlink(missing_ok=True)


def test_orchestrate_discovery_run_malformed_record_midway_through_page_fails_atomically(
    sqlite_session: Session,
) -> None:
    """A malformed record midway through a page rolls back all page mutations."""
    _setup_approved_source(sqlite_session, "fixture_lever")
    sub = create_employer_subscription(sqlite_session, "fixture_lever", "example-corp")

    page_with_bad_item = [
        {
            "id": "lever-good-001",
            "text": "Good Engineer",
            "createdAt": 1700000000000,
            "hostedUrl": "https://jobs.lever.co/example-corp/lever-good-001",
        },
        {
            "id": "lever-bad-002",
            # missing "text" (required)
            "createdAt": 1700000000000,
            "hostedUrl": "https://jobs.lever.co/example-corp/lever-bad-002",
        },
    ]

    adapter = FixtureJobSourceAdapter(
        source_name="fixture_lever",
        pages=[page_with_bad_item],
        delegate_adapter=LeverPostingsAdapter(source_name="fixture_lever"),
    )

    result = orchestrate_discovery_run(sqlite_session, sub.id, adapter, page_limit=10)
    assert result.status == DiscoveryRunStatus.FAILED
    assert result.error_code == "MISSING_JOB_TITLE"

    # Zero postings committed (atomic page rollback)
    postings = sqlite_session.scalars(select(JobPosting).where(JobPosting.subscription_id == sub.id)).all()
    assert len(postings) == 0

    # Checkpoint failure counter incremented, last_successful_run_at remains None
    checkpoint = sqlite_session.get(DiscoveryCheckpoint, sub.id)
    assert checkpoint.last_successful_run_at is None
    assert checkpoint.consecutive_failure_count == 1


def test_orchestrate_discovery_run_failure_after_committed_page_prevents_false_removals(
    sqlite_session: Session,
) -> None:
    """A failure after one committed page must NOT advance checkpoint or falsely mark unobserved postings REMOVED."""
    _setup_approved_source(sqlite_session, "fixture_lever")
    sub = create_employer_subscription(sqlite_session, "fixture_lever", "example-corp")
    sqlite_session.commit()
    sub_id = sub.id

    # Initial successful discovery of job-A and job-B
    initial_listing = [
        {"id": "job-A", "text": "Role A", "createdAt": 1700000000000, "hostedUrl": "https://jobs.lever.co/example-corp/job-A"},
        {"id": "job-B", "text": "Role B", "createdAt": 1700000000000, "hostedUrl": "https://jobs.lever.co/example-corp/job-B"},
    ]
    adapter1 = FixtureJobSourceAdapter("fixture_lever", [initial_listing], LeverPostingsAdapter(source_name="fixture_lever"))
    r1 = orchestrate_discovery_run(sqlite_session, sub.id, adapter1, page_limit=10)
    assert r1.status == DiscoveryRunStatus.SUCCEEDED

    ckpt1 = sqlite_session.get(DiscoveryCheckpoint, sub.id)
    last_success_timestamp = ckpt1.last_successful_run_at
    assert last_success_timestamp is not None
    sqlite_session.rollback()  # End caller inspection transaction before next run

    # Next run: Page 0 has job-A. Page 1 fails with malformed payload
    page_0 = [initial_listing[0]]  # only job-A
    page_1_broken = ["not-a-dict"]

    adapter2 = FixtureJobSourceAdapter("fixture_lever", [page_0, page_1_broken], LeverPostingsAdapter(source_name="fixture_lever"))
    r2 = orchestrate_discovery_run(sqlite_session, sub_id, adapter2, page_limit=1)

    assert r2.status == DiscoveryRunStatus.FAILED

    # job-B was NOT in Page 0, but because run failed, job-B MUST NOT receive an absence miss!
    job_b = sqlite_session.scalar(select(JobPosting).where(JobPosting.subscription_id == sub.id, JobPosting.posting_id == "job-B"))
    assert job_b.consecutive_misses_count == 0
    assert job_b.lifecycle_status == PostingLifecycleStatus.ACTIVE

    # Checkpoint last_successful_run_at remains from Run 1
    sqlite_session.refresh(ckpt1)
    assert ckpt1.last_successful_run_at == last_success_timestamp
    assert ckpt1.consecutive_failure_count == 1


def test_orchestrate_discovery_run_fully_successful_empty_result(
    sqlite_session: Session,
) -> None:
    """An employer with zero open vacancies produces a successful empty run and increments misses."""
    _setup_approved_source(sqlite_session, "fixture_lever")
    sub = create_employer_subscription(sqlite_session, "fixture_lever", "example-corp")

    # Seed an active posting
    initial_listing = [
        {"id": "job-only", "text": "Sole Role", "createdAt": 1700000000000, "hostedUrl": "https://jobs.lever.co/example-corp/job-only"}
    ]
    adapter1 = FixtureJobSourceAdapter("fixture_lever", [initial_listing], LeverPostingsAdapter(source_name="fixture_lever"))
    orchestrate_discovery_run(sqlite_session, sub.id, adapter1, page_limit=10)

    # Run 2: empty feed (0 postings returned)
    adapter_empty = FixtureJobSourceAdapter("fixture_lever", [[]], LeverPostingsAdapter(source_name="fixture_lever"))
    r2 = orchestrate_discovery_run(sqlite_session, sub.id, adapter_empty, page_limit=10)

    assert r2.status == DiscoveryRunStatus.SUCCEEDED
    assert r2.items_seen == 0
    assert r2.items_new == 0

    # Checkpoint advances
    ckpt = sqlite_session.get(DiscoveryCheckpoint, sub.id)
    assert ckpt.last_successful_run_at is not None
    assert ckpt.consecutive_failure_count == 0

    # Job received 1 miss because run succeeded completely
    posting = sqlite_session.scalar(select(JobPosting).where(JobPosting.subscription_id == sub.id, JobPosting.posting_id == "job-only"))
    assert posting.consecutive_misses_count == 1
    assert posting.lifecycle_status == PostingLifecycleStatus.ACTIVE


def test_orchestrate_discovery_run_posting_reappears_after_one_miss_resets_misses(
    sqlite_session: Session,
) -> None:
    """A posting omitted for 1 run resets misses to 0 when rediscovered in a subsequent run."""
    _setup_approved_source(sqlite_session, "fixture_lever")
    sub = create_employer_subscription(sqlite_session, "fixture_lever", "example-corp")
    sqlite_session.commit()
    sub_id = sub.id

    listing = [
        {"id": "job-flip", "text": "Flipping Role", "createdAt": 1700000000000, "hostedUrl": "https://jobs.lever.co/example-corp/job-flip"}
    ]
    adapter_full = FixtureJobSourceAdapter("fixture_lever", [listing], LeverPostingsAdapter(source_name="fixture_lever"))
    adapter_empty = FixtureJobSourceAdapter("fixture_lever", [[]], LeverPostingsAdapter(source_name="fixture_lever"))

    # Run 1: discovered
    orchestrate_discovery_run(sqlite_session, sub_id, adapter_full, page_limit=10)
    p = sqlite_session.scalar(select(JobPosting).where(JobPosting.subscription_id == sub.id, JobPosting.posting_id == "job-flip"))
    assert p.consecutive_misses_count == 0
    sqlite_session.rollback()  # End caller inspection transaction before next run

    # Run 2: omitted
    orchestrate_discovery_run(sqlite_session, sub_id, adapter_empty, page_limit=10)
    sqlite_session.refresh(p)
    assert p.consecutive_misses_count == 1
    assert p.lifecycle_status == PostingLifecycleStatus.ACTIVE
    sqlite_session.rollback()  # End caller inspection transaction before next run

    # Run 3: reappeared
    orchestrate_discovery_run(sqlite_session, sub_id, adapter_full, page_limit=10)
    sqlite_session.refresh(p)
    assert p.consecutive_misses_count == 0
    assert p.lifecycle_status == PostingLifecycleStatus.ACTIVE


def test_orchestrate_discovery_run_duplicate_records_within_single_page(
    sqlite_session: Session,
) -> None:
    """Duplicate records within a single page are handled gracefully via items_duplicate."""
    _setup_approved_source(sqlite_session, "fixture_lever")
    sub = create_employer_subscription(sqlite_session, "fixture_lever", "example-corp")

    item = {"id": "job-dup", "text": "Duplicate Role", "createdAt": 1700000000000, "hostedUrl": "https://jobs.lever.co/example-corp/job-dup"}
    # Two identical records on the same page
    page_with_dups = [item, item]

    adapter = FixtureJobSourceAdapter("fixture_lever", [page_with_dups], LeverPostingsAdapter(source_name="fixture_lever"))
    result = orchestrate_discovery_run(sqlite_session, sub.id, adapter, page_limit=10)

    assert result.status == DiscoveryRunStatus.SUCCEEDED
    assert result.items_seen == 2
    assert result.items_new == 1
    assert result.items_duplicate == 1

    # Exactly 1 posting and 1 snapshot in DB
    postings = sqlite_session.scalars(select(JobPosting).where(JobPosting.subscription_id == sub.id)).all()
    assert len(postings) == 1
    assert postings[0].version == 1

    snapshots = sqlite_session.scalars(select(JobPostingSnapshot).where(JobPostingSnapshot.subscription_id == sub.id)).all()
    assert len(snapshots) == 1


def test_orchestrate_discovery_run_stale_worker_after_newer_worker_acquired_lease(
    sqlite_session: Session,
) -> None:
    """A stale worker cannot mutate checkpoint or clear newer worker lease."""
    _setup_approved_source(sqlite_session, "fixture_lever")
    sub = create_employer_subscription(sqlite_session, "fixture_lever", "example-corp")

    class NewerWorkerInterventionAdapter(FixtureJobSourceAdapter):
        def fetch_page(self, employer_handle: str, skip: int, limit: int):
            # Runner 2 intervenes and steals the lease
            s = sqlite_session.get(EmployerSubscription, sub.id)
            s.lease_token = "newer-runner-token"
            s.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
            sqlite_session.commit()
            return super().fetch_page(employer_handle, skip, limit)

    valid_listing = load_fixture("valid_listing.json")
    adapter = NewerWorkerInterventionAdapter(
        "fixture_lever", [valid_listing], LeverPostingsAdapter(source_name="fixture_lever")
    )

    result = orchestrate_discovery_run(sqlite_session, sub.id, adapter, page_limit=10)
    assert result.status == DiscoveryRunStatus.FAILED
    assert result.error_code == "LEASE_FENCING_FAILED"

    # Newer worker's lease is STILL active (not cleared by stale worker fail_discovery_run)
    refreshed_sub = sqlite_session.get(EmployerSubscription, sub.id)
    assert refreshed_sub.lease_token == "newer-runner-token"

    # Checkpoint failure counter is untouched (stale worker does not increment)
    checkpoint = sqlite_session.get(DiscoveryCheckpoint, sub.id)
    assert checkpoint.consecutive_failure_count == 0


def test_orchestrate_discovery_run_maximum_pages_termination(
    sqlite_session: Session,
) -> None:
    """A feed that exceeds max_pages terminates with MAX_PAGES_EXCEEDED without advancing checkpoint."""
    _setup_approved_source(sqlite_session, "fixture_lever")
    sub = create_employer_subscription(sqlite_session, "fixture_lever", "example-corp")

    # Feed has 3 pages, but max_pages is set to 2
    p0 = [{"id": "p0-1", "text": "R0", "createdAt": 1700000000000, "hostedUrl": "https://jobs.lever.co/example-corp/p0-1"}]
    p1 = [{"id": "p1-1", "text": "R1", "createdAt": 1700000000000, "hostedUrl": "https://jobs.lever.co/example-corp/p1-1"}]
    p2 = [{"id": "p2-1", "text": "R2", "createdAt": 1700000000000, "hostedUrl": "https://jobs.lever.co/example-corp/p2-1"}]

    adapter = FixtureJobSourceAdapter("fixture_lever", [p0, p1, p2], LeverPostingsAdapter(source_name="fixture_lever"))

    result = orchestrate_discovery_run(sqlite_session, sub.id, adapter, page_limit=1, max_pages=2)
    assert result.status == DiscoveryRunStatus.FAILED
    assert result.error_code == "MAX_PAGES_EXCEEDED"

    # Checkpoint last_successful_run_at does not advance
    checkpoint = sqlite_session.get(DiscoveryCheckpoint, sub.id)
    assert checkpoint.last_successful_run_at is None
    assert checkpoint.consecutive_failure_count == 1


def test_orchestrate_discovery_run_authorization_checked_before_fetch(
    sqlite_session: Session,
) -> None:
    """Verifies that authorization gate runs before any adapter fetch is attempted."""
    source = _setup_approved_source(sqlite_session, "disabled_ats")
    source.is_enabled = False
    source.capability_status = SourceCapabilityStatus.DISABLED_BY_USER.value
    sqlite_session.commit()

    sub = create_employer_subscription(sqlite_session, "disabled_ats", "example-corp")

    fetch_attempted = False

    class TrackingAdapter(FixtureJobSourceAdapter):
        def fetch_page(self, employer_handle, skip, limit):
            nonlocal fetch_attempted
            fetch_attempted = True
            return []

    adapter = TrackingAdapter("disabled_ats", [[]], LeverPostingsAdapter(source_name="disabled_ats"))

    with pytest.raises(SourceNotApprovedError):
        orchestrate_discovery_run(sqlite_session, sub.id, adapter)

    # Fetch was never called!
    assert fetch_attempted is False


def test_orchestrate_discovery_run_rejects_pending_changes_precondition(
    sqlite_session: Session,
) -> None:
    """Verifies that orchestrate_discovery_run rejects sessions with pending new, dirty, or deleted objects."""
    _setup_approved_source(sqlite_session, "clean_ats")
    sub = create_employer_subscription(sqlite_session, "clean_ats", "clean-corp")
    sqlite_session.commit()

    fetch_attempted = False

    class TrackingAdapter(FixtureJobSourceAdapter):
        def fetch_page(self, employer_handle, skip, limit):
            nonlocal fetch_attempted
            fetch_attempted = True
            return []

    adapter = TrackingAdapter("clean_ats", [[]], LeverPostingsAdapter(source_name="clean_ats"))

    # Case A: pending new object
    uncommitted_source = JobSource(
        source_name="unrelated_source",
        display_name="Unrelated",
        capability_status=SourceCapabilityStatus.NEEDS_REVIEW.value,
        is_enabled=False,
    )
    sqlite_session.add(uncommitted_source)
    assert uncommitted_source in sqlite_session.new

    with pytest.raises(ValueError, match="clean session with no pending changes"):
        orchestrate_discovery_run(sqlite_session, sub.id, adapter)

    assert fetch_attempted is False
    assert uncommitted_source in sqlite_session.new
    sqlite_session.rollback()

    # Case B: pending dirty object
    sub_dirty = sqlite_session.get(EmployerSubscription, sub.id)
    sub_dirty.display_name = "Mutated But Uncommitted"
    assert sub_dirty in sqlite_session.dirty

    with pytest.raises(ValueError, match="clean session with no pending changes"):
        orchestrate_discovery_run(sqlite_session, sub.id, adapter)

    assert fetch_attempted is False
    sqlite_session.rollback()

    # Verify zero discovery runs or postings were created
    runs = sqlite_session.scalars(select(DiscoveryRun).where(DiscoveryRun.subscription_id == sub.id)).all()
    assert len(runs) == 0


def test_orchestrate_discovery_run_rejects_active_transaction_precondition(
    sqlite_session: Session,
) -> None:
    """Verifies that orchestrate_discovery_run rejects clean sessions that have an active pre-existing transaction."""
    _setup_approved_source(sqlite_session, "tx_ats")
    sub = create_employer_subscription(sqlite_session, "tx_ats", "tx-corp")
    sqlite_session.commit()

    fetch_attempted = False

    class TrackingAdapter(FixtureJobSourceAdapter):
        def fetch_page(self, employer_handle, skip, limit):
            nonlocal fetch_attempted
            fetch_attempted = True
            return []

    adapter = TrackingAdapter("tx_ats", [[]], LeverPostingsAdapter(source_name="tx_ats"))

    # Caller explicitly starts a transaction context (clean, zero pending changes)
    sqlite_session.begin()
    assert sqlite_session.in_transaction() is True
    assert len(sqlite_session.new) == 0
    assert len(sqlite_session.dirty) == 0
    assert len(sqlite_session.deleted) == 0

    with pytest.raises(ValueError, match="session with no active transaction"):
        orchestrate_discovery_run(sqlite_session, sub.id, adapter)

    # Rejection happens before any fetch or database operation
    assert fetch_attempted is False

    # Close caller's transaction safely
    sqlite_session.rollback()
    assert sqlite_session.in_transaction() is False

    # Zero discovery mutations or runs were performed
    runs = sqlite_session.scalars(select(DiscoveryRun).where(DiscoveryRun.subscription_id == sub.id)).all()
    assert len(runs) == 0

    # Subscription lease remains untouched
    refreshed_sub = sqlite_session.get(EmployerSubscription, sub.id)
    assert refreshed_sub.lease_token is None


def test_orchestrate_discovery_run_leaves_session_usable_after_failure(
    sqlite_session: Session,
) -> None:
    """Verifies that discovery run failure leaves the session in a clean, usable transaction state."""
    _setup_approved_source(sqlite_session, "failing_ats")
    sub = create_employer_subscription(sqlite_session, "failing_ats", "fail-corp")
    sqlite_session.commit()

    class ExplodingAdapter(FixtureJobSourceAdapter):
        def fetch_page(self, employer_handle, skip, limit):
            raise RuntimeError("Network boom")

    adapter = ExplodingAdapter("failing_ats", [[]], LeverPostingsAdapter(source_name="failing_ats"))

    result = orchestrate_discovery_run(sqlite_session, sub.id, adapter)
    assert result.status == DiscoveryRunStatus.FAILED
    assert result.error_code == "RuntimeError"

    # Session is usable for immediate subsequent queries without aborted transaction errors
    refreshed_sub = sqlite_session.get(EmployerSubscription, sub.id)
    assert refreshed_sub is not None
    assert refreshed_sub.lease_token is None  # Lease released

    runs = sqlite_session.scalars(
        select(DiscoveryRun).where(DiscoveryRun.subscription_id == sub.id)
    ).all()
    assert len(runs) == 1
    assert runs[0].status == DiscoveryRunStatus.FAILED
