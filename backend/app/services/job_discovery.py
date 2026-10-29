"""Service and repository operations for job discovery persistence and execution."""

from collections.abc import Sequence
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from backend.app.db.models import (
    DiscoveryCheckpoint,
    DiscoveryRun,
    EmployerSubscription,
    JobPosting,
    JobPostingSnapshot,
    JobSource,
)
from backend.app.adapters.job_sources import JobSourceAdapter
from backend.app.domain.job_posting import (
    PaginationLoopError,
    CircuitBreakerTrippedError,
    ClosedPostingReappearedError,
    DiscoveryRunStatus,
    DuplicateJobPostingError,
    InvalidJobIntakeError,
    InvalidPaginationBoundsError,
    InvalidPostingPayloadError,
    LeaseFencingError,
    NormalizedPosting,
    PostingLifecycleStatus,
    PublicationDateStatus,
    SourceCapabilityStatus,
    SourceGloballyDisabledError,
    SourceNotApprovedError,
    SourceTermsReviewStaleError,
    SubscriptionDisabledError,
    UserJobIntake,
    extract_sections_from_plain_text,
    validate_reference_url,
)


# Hire-Steward internal policy: source terms reviews must be reassessed within 365 days.
# This is an internal freshness discipline, not a statutory or third-party requirement.
TERMS_REVIEW_MAX_AGE_DAYS: int = 365
TERMS_REVIEW_MAX_AGE_SECONDS: int = TERMS_REVIEW_MAX_AGE_DAYS * 86400


@dataclass(frozen=True, slots=True)
class PageCommitResult:
    """Summary of posting mutations committed in a single discovery page."""

    page_index: int
    items_seen: int
    items_new: int
    items_updated: int
    items_duplicate: int


@dataclass(frozen=True, slots=True)
class DiscoveryRunResult:
    """Outcome and metric summary of an orchestrated discovery execution."""

    run_id: str
    status: DiscoveryRunStatus
    items_seen: int = 0
    items_new: int = 0
    items_updated: int = 0
    items_duplicate: int = 0
    pages_processed: int = 0
    error_code: str | None = None
    error_message: str | None = None


def _get_db_wall_clock(session: Session) -> datetime:
    """Retrieve current wall-clock time from the database.

    In PostgreSQL, clock_timestamp() advances in real time, unlike NOW()
    which is frozen at transaction start.
    """
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        now = session.scalar(select(func.clock_timestamp()))
    else:
        now = datetime.now(timezone.utc)
    if now is not None and now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now


def verify_source_authorization_gate(
    session: Session,
    source_name: str,
    subscription_id: str | None = None,
) -> tuple[JobSource, EmployerSubscription | None]:
    """Verify the multi-layer source authorization gate before any discovery activity.

    Enforces:
    1. Source capability status must be VERIFIED_READ_ONLY.
    2. Source must be globally enabled.
    3. Source terms review must be present, documented, non-future, and not older
       than TERMS_REVIEW_MAX_AGE_DAYS (365 days; Hire-Steward internal policy).
    4. If subscription_id is provided: subscription must be enabled.
    5. If subscription_id is provided: circuit breaker must not be tripped.

    Note: A valid, fresh review timestamp is a required gate condition but does
    NOT itself authorize access. Live discovery additionally requires explicit source
    activation and verified read-only capability status.
    """
    source = session.get(JobSource, source_name)
    if source is None or source.capability_status != SourceCapabilityStatus.VERIFIED_READ_ONLY:
        status_label = source.capability_status if source else "NOT_FOUND"
        raise SourceNotApprovedError(
            f"Source '{source_name}' is not approved for discovery (status: {status_label})"
        )

    if not source.is_enabled:
        raise SourceGloballyDisabledError(
            f"Source '{source_name}' is globally disabled"
        )

    now = _get_db_wall_clock(session)
    terms_reviewed_at = source.terms_reviewed_at
    if terms_reviewed_at is not None and terms_reviewed_at.tzinfo is None:
        terms_reviewed_at = terms_reviewed_at.replace(tzinfo=timezone.utc)

    if (
        terms_reviewed_at is None
        or not source.terms_review_reference
        or terms_reviewed_at > now
        or (now - terms_reviewed_at).total_seconds() > TERMS_REVIEW_MAX_AGE_SECONDS
    ):
        raise SourceTermsReviewStaleError(
            f"Source '{source_name}' has stale, future, or missing terms review"
        )

    subscription: EmployerSubscription | None = None
    if subscription_id is not None:
        subscription = session.get(EmployerSubscription, subscription_id)
        if subscription is None:
            raise SubscriptionDisabledError(
                f"Employer subscription '{subscription_id}' does not exist"
            )
        if not subscription.is_enabled:
            raise SubscriptionDisabledError(
                f"Employer subscription '{subscription_id}' is disabled by candidate"
            )

        checkpoint = session.get(DiscoveryCheckpoint, subscription_id)
        if checkpoint is not None and checkpoint.circuit_breaker_tripped:
            raise CircuitBreakerTrippedError(
                f"Circuit breaker tripped for subscription '{subscription_id}': {checkpoint.circuit_breaker_reason}"
            )

    return source, subscription


def create_employer_subscription(
    session: Session,
    source_name: str,
    employer_handle: str,
    display_name: str | None = None,
) -> EmployerSubscription:
    """Create a candidate employer subscription and initialize its checkpoint."""
    sub_id = str(uuid4())
    subscription = EmployerSubscription(
        id=sub_id,
        source_name=source_name,
        employer_handle=employer_handle,
        display_name=display_name,
        is_enabled=True,
    )
    checkpoint = DiscoveryCheckpoint(
        subscription_id=sub_id,
        consecutive_failure_count=0,
        circuit_breaker_tripped=False,
    )
    with session.begin_nested() if session.in_transaction() else session.begin():
        session.add(subscription)
        session.flush()
        session.add(checkpoint)
        session.flush()
    return subscription


def set_employer_subscription_enabled(
    session: Session,
    subscription_id: str,
    is_enabled: bool,
) -> EmployerSubscription:
    """Update candidate-managed enabled status and record user configuration timestamp."""
    subscription = session.get(EmployerSubscription, subscription_id)
    if subscription is None:
        raise SubscriptionDisabledError(f"Subscription '{subscription_id}' not found")
    with session.begin_nested() if session.in_transaction() else session.begin():
        subscription.is_enabled = is_enabled
        subscription.updated_at = _get_db_wall_clock(session)
        session.flush()
    return subscription


def get_subscription_checkpoint(
    session: Session,
    subscription_id: str,
) -> DiscoveryCheckpoint | None:
    """Retrieve durable discovery progress and circuit-breaker status."""
    return session.get(DiscoveryCheckpoint, subscription_id)


def begin_discovery_run(
    session: Session,
    subscription_id: str,
    page_limit: int = 100,
    lease_duration_minutes: int = 10,
) -> tuple[DiscoveryRun, str | None]:
    """Initiate a discovery run attempt with atomic lease acquisition and fencing.

    If another runner holds an active, unexpired lease:
    - Persists an audit run record with status SKIPPED_CONCURRENT_LEASE.
    - Performs zero network requests and zero posting/checkpoint mutations.
    - Returns (run, None) to signal skip.

    If lease is acquired:
    - Advances run status to RUNNING.
    - Returns (run, lease_token).
    """
    subscription = session.get(EmployerSubscription, subscription_id)
    if subscription is None:
        raise SubscriptionDisabledError(f"Subscription '{subscription_id}' not found")

    verify_source_authorization_gate(
        session,
        source_name=subscription.source_name,
        subscription_id=subscription_id,
    )

    if page_limit < 1 or page_limit > 100:
        raise InvalidPaginationBoundsError(
            f"page_limit must be between 1 and 100, got {page_limit}",
            "PAGE_LIMIT_OUT_OF_BOUNDS",
        )

    run_id = str(uuid4())
    new_token = str(uuid4())
    bind = session.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    with session.begin_nested() if session.in_transaction() else session.begin():
        run = DiscoveryRun(
            id=run_id,
            subscription_id=subscription_id,
            status=DiscoveryRunStatus.PENDING,
            page_limit=page_limit,
        )
        session.add(run)
        session.flush()

        if is_sqlite:
            acquire_stmt = text(
                """
                UPDATE employer_subscriptions
                SET lease_token = :new_token,
                    lease_expires_at = datetime('now', '+' || :duration || ' minutes')
                WHERE id = :subscription_id
                  AND (
                    (lease_token IS NULL AND lease_expires_at IS NULL)
                    OR lease_expires_at <= datetime('now')
                  )
                """
            )
        else:
            acquire_stmt = text(
                """
                UPDATE employer_subscriptions
                SET lease_token = :new_token,
                    lease_expires_at = clock_timestamp() + (:duration * INTERVAL '1 minute')
                WHERE id = :subscription_id
                  AND (
                    (lease_token IS NULL AND lease_expires_at IS NULL)
                    OR lease_expires_at <= clock_timestamp()
                  )
                """
            )

        result = session.execute(
            acquire_stmt,
            {
                "new_token": new_token,
                "duration": lease_duration_minutes,
                "subscription_id": subscription_id,
            },
        )

        session.expire(subscription)

        if result.rowcount == 0:
            now = _get_db_wall_clock(session)
            run.status = DiscoveryRunStatus.SKIPPED_CONCURRENT_LEASE
            run.finished_at = now
            run.error_code = "LEASE_ACTIVE"
            session.flush()
            return run, None

        run.status = DiscoveryRunStatus.RUNNING
        session.flush()

    return run, new_token


def renew_subscription_lease(
    session: Session,
    subscription_id: str,
    lease_token: str,
    duration_minutes: int = 10,
) -> bool:
    """Extend runner lease expiry without mutating user configuration timestamps.

    Returns True if lease was successfully renewed; False if ownership was lost.
    """
    bind = session.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    if is_sqlite:
        renew_stmt = text(
            """
            UPDATE employer_subscriptions
            SET lease_expires_at = datetime('now', '+' || :duration || ' minutes')
            WHERE id = :subscription_id
              AND lease_token = :token
              AND lease_expires_at > datetime('now')
            """
        )
    else:
        renew_stmt = text(
            """
            UPDATE employer_subscriptions
            SET lease_expires_at = clock_timestamp() + (:duration * INTERVAL '1 minute')
            WHERE id = :subscription_id
              AND lease_token = :token
              AND lease_expires_at > clock_timestamp()
            """
        )

    with session.begin_nested() if session.in_transaction() else session.begin():
        result = session.execute(
            renew_stmt,
            {
                "token": lease_token,
                "duration": duration_minutes,
                "subscription_id": subscription_id,
            },
        )
        sub = session.get(EmployerSubscription, subscription_id)
        if sub is not None:
            session.expire(sub)
        return result.rowcount > 0


def fenced_page_commit(
    session: Session,
    subscription_id: str,
    run_id: str,
    lease_token: str,
    postings: Sequence[NormalizedPosting],
    page_index: int,
    skip: int,
    page_limit: int,
) -> PageCommitResult:
    """Atomically commit a page of discovered postings with strict lease fencing.

    Invariants:
    1. Locks subscription row with FOR UPDATE.
    2. Validates lease token matches and expiry is in the future using wall-clock time.
    3. Persists new JobPostingSnapshot rows for newly discovered or updated hashes.
    4. Updates JobPosting rows with composite referential integrity.
    5. Advances DiscoveryRun cursor and item counters.
    6. Rejects silent resurrection of CLOSED_CONFIRMED postings.
    """
    with session.begin_nested() if session.in_transaction() else session.begin():
        sub_stmt = (
            select(EmployerSubscription)
            .where(EmployerSubscription.id == subscription_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        sub = session.scalar(sub_stmt)
        if sub is None:
            raise LeaseFencingError("Employer subscription not found during page commit")

        now = _get_db_wall_clock(session)
        sub_lease_expires = sub.lease_expires_at
        if sub_lease_expires is not None and sub_lease_expires.tzinfo is None:
            sub_lease_expires = sub_lease_expires.replace(tzinfo=timezone.utc)

        if sub.lease_token != lease_token or sub_lease_expires is None or sub_lease_expires <= now:
            raise LeaseFencingError(
                "Lease fencing validation failed: runner does not hold active unexpired lease"
            )

        run = session.get(DiscoveryRun, run_id)
        if run is None or run.subscription_id != subscription_id:
            raise LeaseFencingError(
                f"Discovery run '{run_id}' does not belong to subscription '{subscription_id}'"
            )

        items_seen = len(postings)
        items_new = 0
        items_updated = 0
        items_duplicate = 0

        for posting in postings:
            if posting.employer_handle != sub.employer_handle or posting.source != sub.source_name:
                raise InvalidPostingPayloadError(
                    f"Posting origin mismatch: expected {sub.source_name}/{sub.employer_handle}, "
                    f"got {posting.source}/{posting.employer_handle}",
                    "POSTING_SUBSCRIPTION_MISMATCH",
                )

            existing_stmt = select(JobPosting).where(
                JobPosting.subscription_id == subscription_id,
                JobPosting.posting_id == posting.posting_id,
            )
            existing = session.scalar(existing_stmt)

            if existing is None:
                new_posting_id = str(uuid4())
                snapshot_id = str(uuid4())

                new_posting = JobPosting(
                    id=new_posting_id,
                    subscription_id=subscription_id,
                    posting_id=posting.posting_id,
                    current_raw_hash=posting.source_raw_hash,
                    lifecycle_status=PostingLifecycleStatus.ACTIVE,
                    consecutive_misses_count=0,
                    version=1,
                    first_observed_at=now,
                    last_observed_at=now,
                    last_seen_run_id=run_id,
                )
                session.add(new_posting)
                session.flush()

                lists_payload = [section.model_dump() for section in posting.lists]
                snapshot = JobPostingSnapshot(
                    id=snapshot_id,
                    subscription_id=subscription_id,
                    posting_id=new_posting_id,
                    run_id=run_id,
                    source_raw_hash=posting.source_raw_hash,
                    title=posting.title,
                    location=posting.location,
                    commitment=posting.commitment,
                    team=posting.team,
                    department=posting.department,
                    level=posting.level,
                    workplace_type=posting.workplace_type,
                    published_at=posting.published_at,
                    publication_date_status=posting.publication_date_status.value,
                    raw_created_at_ms=posting.raw_created_at_ms,
                    canonical_url=posting.canonical_url,
                    apply_url=posting.apply_url,
                    description_plain=posting.description_plain,
                    description_html=posting.description_html,
                    lists_json=lists_payload,
                    additional_plain=posting.additional_plain,
                    captured_at=now,
                )
                session.add(snapshot)
                items_new += 1

            else:
                if existing.lifecycle_status == PostingLifecycleStatus.CLOSED_CONFIRMED:
                    raise ClosedPostingReappearedError(
                        f"Posting '{posting.posting_id}' is marked CLOSED_CONFIRMED and cannot "
                        f"be silently reactivated without candidate confirmation"
                    )

                if existing.current_raw_hash != posting.source_raw_hash:
                    existing.current_raw_hash = posting.source_raw_hash
                    existing.version += 1
                    existing.last_observed_at = now
                    existing.last_seen_run_id = run_id
                    existing.consecutive_misses_count = 0
                    if existing.lifecycle_status in (
                        PostingLifecycleStatus.REMOVED,
                        PostingLifecycleStatus.STALE,
                    ):
                        existing.lifecycle_status = PostingLifecycleStatus.ACTIVE

                    snapshot_id = str(uuid4())
                    lists_payload = [section.model_dump() for section in posting.lists]
                    snapshot = JobPostingSnapshot(
                        id=snapshot_id,
                        subscription_id=subscription_id,
                        posting_id=existing.id,
                        run_id=run_id,
                        source_raw_hash=posting.source_raw_hash,
                        title=posting.title,
                        location=posting.location,
                        commitment=posting.commitment,
                        team=posting.team,
                        department=posting.department,
                        level=posting.level,
                        workplace_type=posting.workplace_type,
                        published_at=posting.published_at,
                        publication_date_status=posting.publication_date_status.value,
                        raw_created_at_ms=posting.raw_created_at_ms,
                        canonical_url=posting.canonical_url,
                        apply_url=posting.apply_url,
                        description_plain=posting.description_plain,
                        description_html=posting.description_html,
                        lists_json=lists_payload,
                        additional_plain=posting.additional_plain,
                        captured_at=now,
                    )
                    session.add(snapshot)
                    items_updated += 1

                else:
                    existing.last_observed_at = now
                    existing.last_seen_run_id = run_id
                    existing.consecutive_misses_count = 0
                    if existing.lifecycle_status in (
                        PostingLifecycleStatus.REMOVED,
                        PostingLifecycleStatus.STALE,
                    ):
                        existing.lifecycle_status = PostingLifecycleStatus.ACTIVE
                    items_duplicate += 1

        run.current_skip = skip
        run.current_page_index = page_index
        run.page_limit = page_limit
        run.items_seen_count += items_seen
        run.items_new_count += items_new
        run.items_updated_count += items_updated
        run.items_duplicate_count += items_duplicate
        session.flush()

    return PageCommitResult(
        page_index=page_index,
        items_seen=items_seen,
        items_new=items_new,
        items_updated=items_updated,
        items_duplicate=items_duplicate,
    )


def complete_discovery_run(
    session: Session,
    subscription_id: str,
    run_id: str,
    lease_token: str,
    seen_posting_ids: set[str],
) -> DiscoveryRun:
    """Finalize a successful discovery run, handle absence detection, and release lease.

    Absence Threshold Rules:
    - Active postings omitted from this run increment consecutive_misses_count.
    - If consecutive_misses_count >= 2, transition lifecycle_status to REMOVED.
    - Checkpoint consecutive_failure_count is reset to 0.
    """
    with session.begin_nested() if session.in_transaction() else session.begin():
        sub_stmt = (
            select(EmployerSubscription)
            .where(EmployerSubscription.id == subscription_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        sub = session.scalar(sub_stmt)
        if sub is None:
            raise LeaseFencingError("Employer subscription not found during run completion")

        now = _get_db_wall_clock(session)
        sub_lease_expires = sub.lease_expires_at
        if sub_lease_expires is not None and sub_lease_expires.tzinfo is None:
            sub_lease_expires = sub_lease_expires.replace(tzinfo=timezone.utc)

        if sub.lease_token != lease_token or sub_lease_expires is None or sub_lease_expires <= now:
            raise LeaseFencingError(
                "Lease fencing validation failed during discovery run completion"
            )

        run = session.get(DiscoveryRun, run_id)
        if run is None or run.subscription_id != subscription_id:
            raise LeaseFencingError(
                f"Discovery run '{run_id}' does not match subscription '{subscription_id}'"
            )

        # Absence and staleness evaluation for non-CLOSED_CONFIRMED postings
        eval_postings = session.scalars(
            select(JobPosting).where(
                JobPosting.subscription_id == subscription_id,
                JobPosting.lifecycle_status.in_([
                    PostingLifecycleStatus.ACTIVE,
                    PostingLifecycleStatus.REMOVED,
                ]),
            )
        ).all()

        for p in eval_postings:
            if p.lifecycle_status == PostingLifecycleStatus.ACTIVE:
                if p.posting_id not in seen_posting_ids:
                    p.consecutive_misses_count += 1
                    if p.consecutive_misses_count >= 2:
                        p.lifecycle_status = PostingLifecycleStatus.REMOVED

            # Staleness: unobserved for > 30 days transitions ACTIVE/REMOVED to STALE
            p_last = p.last_observed_at
            if p_last is not None:
                if p_last.tzinfo is None:
                    p_last = p_last.replace(tzinfo=timezone.utc)
                if (now - p_last).total_seconds() > 30 * 86400:
                    p.lifecycle_status = PostingLifecycleStatus.STALE

        run.status = DiscoveryRunStatus.SUCCEEDED
        run.finished_at = now

        checkpoint = session.get(DiscoveryCheckpoint, subscription_id)
        if checkpoint is None:
            checkpoint = DiscoveryCheckpoint(
                subscription_id=subscription_id,
                last_successful_run_at=now,
                consecutive_failure_count=0,
                circuit_breaker_tripped=False,
                updated_at=now,
            )
            session.add(checkpoint)
        else:
            checkpoint.last_successful_run_at = now
            checkpoint.consecutive_failure_count = 0
            checkpoint.circuit_breaker_tripped = False
            checkpoint.circuit_breaker_reason = None
            checkpoint.circuit_breaker_tripped_at = None
            checkpoint.updated_at = now

        # Release lease atomically (preserves employer_subscriptions.updated_at)
        sub.lease_token = None
        sub.lease_expires_at = None
        session.flush()

    return run


def fail_discovery_run(
    session: Session,
    subscription_id: str,
    run_id: str,
    lease_token: str | None,
    error_code: str,
    error_message: str | None = None,
    mutate_checkpoint: bool = True,
) -> DiscoveryRun:
    """Record discovery run failure, advance circuit breaker, and release held lease."""
    now = _get_db_wall_clock(session)
    with session.begin_nested() if session.in_transaction() else session.begin():
        run = session.get(DiscoveryRun, run_id)
        if run is not None and run.subscription_id == subscription_id:
            run.status = DiscoveryRunStatus.FAILED
            run.finished_at = now
            run.error_code = error_code
            run.error_message_redacted = error_message

        if mutate_checkpoint:
            checkpoint = session.get(DiscoveryCheckpoint, subscription_id)
            if checkpoint is None:
                checkpoint = DiscoveryCheckpoint(
                    subscription_id=subscription_id,
                    consecutive_failure_count=1,
                    circuit_breaker_tripped=False,
                    updated_at=now,
                )
                session.add(checkpoint)
            else:
                checkpoint.consecutive_failure_count += 1
                checkpoint.updated_at = now
                if checkpoint.consecutive_failure_count >= 3:
                    checkpoint.circuit_breaker_tripped = True
                    checkpoint.circuit_breaker_reason = error_code
                    checkpoint.circuit_breaker_tripped_at = now

        if lease_token is not None:
            sub = session.get(
                EmployerSubscription,
                subscription_id,
                execution_options={"populate_existing": True},
            )
            if sub is not None and sub.lease_token == lease_token:
                sub.lease_token = None
                sub.lease_expires_at = None

        session.flush()

    return run


def interrupt_discovery_run(
    session: Session,
    subscription_id: str,
    run_id: str,
    lease_token: str | None,
    reason: str = "RUNNER_INTERRUPTED",
) -> DiscoveryRun | None:
    """Record discovery run interruption (e.g. graceful shutdown) and release held lease.

    Does not advance circuit breaker failure counter or mutate discovery checkpoints.
    """
    now = _get_db_wall_clock(session)
    with session.begin_nested() if session.in_transaction() else session.begin():
        run = session.get(DiscoveryRun, run_id)
        if run is not None and run.subscription_id == subscription_id:
            run.status = DiscoveryRunStatus.INTERRUPTED
            run.finished_at = now
            run.error_code = reason

        if lease_token is not None:
            sub = session.get(
                EmployerSubscription,
                subscription_id,
                execution_options={"populate_existing": True},
            )
            if sub is not None and sub.lease_token == lease_token:
                sub.lease_token = None
                sub.lease_expires_at = None

        session.flush()

    return run


def orchestrate_discovery_run(
    session: Session,
    subscription_or_id: str | EmployerSubscription,
    adapter: JobSourceAdapter,
    page_limit: int = 100,
    lease_duration_minutes: int = 10,
    max_pages: int = 50,
) -> DiscoveryRunResult:
    """Orchestrate an end-to-end job discovery run for an employer subscription.

    Transaction Ownership Contract:
    - Discovery orchestration operates across multiple discrete transactions:
      1. Commit 1: Lease acquisition and run initiation (releases lock before network/adapter fetch).
      2. Commits 2..N+1: Per-page atomic writes (each page committed independently with row-level fencing).
      3. Final Commit: Run completion and lease release, or failure audit recording.
    - Entry Precondition:
      Callers MUST provide a session with no active transaction (session.in_transaction() is False)
      and no pending uncommitted changes (session.dirty, session.new, session.deleted are empty).
      If either condition is violated, raises ValueError before performing any database operations
      or adapter fetches, preventing orchestration from accidentally committing or rolling back
      unrelated caller transactions or mutations.
    - Internal Transactions:
      Orchestration internally manages its own transaction boundaries across lease acquisition,
      page commits, and finalization. The entry precondition applies solely to the state of the session
      when passed in by the caller.
    - Exceptions roll back any in-flight uncommitted page mutations before recording run failure.

    Coordinates:
    1. Entry precondition check (no active transaction and no pending changes).
    2. Multi-layer source authorization gate verification.
    3. Atomic discovery run creation and lease acquisition.
    4. Deterministic page fetching and listing parsing via adapter.
    5. Pagination cycle / loop detection across pages.
    6. Fenced page-by-page transaction commits.
    7. Absence and staleness evaluation upon completion.
    8. Checkpoint advancement only after all pages succeed.
    9. Lease release and graceful failure/interruption handling.
    """
    if session.dirty or session.new or session.deleted:
        raise ValueError(
            "orchestrate_discovery_run requires a clean session with no pending changes "
            "(session.new, session.dirty, or session.deleted). Discovery orchestration "
            "manages discrete transaction boundaries for lease acquisition, page persistence, "
            "and run finalization."
        )

    if session.in_transaction():
        raise ValueError(
            "orchestrate_discovery_run requires a session with no active transaction "
            "(session.in_transaction() must be False). Callers must commit or roll back "
            "any prior transaction before invoking discovery orchestration, which manages "
            "its own discrete transaction boundaries."
        )

    if isinstance(subscription_or_id, EmployerSubscription):
        subscription = subscription_or_id
        subscription_id = subscription.id
    else:
        subscription_id = str(subscription_or_id)
        subscription = session.get(EmployerSubscription, subscription_id)
        if subscription is None:
            raise SubscriptionDisabledError(
                f"Employer subscription '{subscription_id}' does not exist"
            )

    if adapter.source_name != subscription.source_name:
        raise InvalidPostingPayloadError(
            f"Adapter source '{adapter.source_name}' does not match subscription source '{subscription.source_name}'",
            "SOURCE_MISMATCH",
        )

    # Authorization gate (fail-closed if source or subscription is unapproved/disabled/stale)
    verify_source_authorization_gate(
        session,
        source_name=subscription.source_name,
        subscription_id=subscription_id,
    )

    employer_handle = subscription.employer_handle

    # Begin run with atomic lease fencing
    run, lease_token = begin_discovery_run(
        session,
        subscription_id=subscription_id,
        page_limit=page_limit,
        lease_duration_minutes=lease_duration_minutes,
    )
    session.commit()

    if lease_token is None:
        # Concurrent lease collision; run audit record was created with SKIPPED_CONCURRENT_LEASE
        return DiscoveryRunResult(
            run_id=run.id,
            status=run.status,
            items_seen=0,
            items_new=0,
            items_updated=0,
            items_duplicate=0,
            pages_processed=0,
            error_code=run.error_code,
            error_message=run.error_message_redacted,
        )

    seen_posting_ids: set[str] = set()
    seen_page_signatures: set[tuple[str, ...]] = set()
    total_seen = 0
    total_new = 0
    total_updated = 0
    total_duplicate = 0
    pages_processed = 0

    try:
        terminated_early = False

        for page_idx in range(max_pages):
            skip = page_idx * page_limit
            raw_page = adapter.fetch_page(employer_handle, skip=skip, limit=page_limit)

            if raw_page is None:
                # End of available pages
                break

            postings = adapter.parse_listing_page(
                employer_handle,
                raw_page,
                skip=skip,
                limit=page_limit,
            )

            if terminated_early and postings:
                raise InvalidPaginationBoundsError(
                    f"Received non-empty page at index {page_idx} after previous page signaled termination",
                    "UNEXPECTED_PAGE_AFTER_TERMINATION",
                )

            if not postings:
                # Empty page ends pagination
                break

            page_signature = tuple(p.posting_id for p in postings)
            if page_signature in seen_page_signatures:
                raise PaginationLoopError(
                    f"Detected cycle in pagination: page {page_idx} repeated a previously seen page signature",
                    "PAGINATION_CYCLE_DETECTED",
                )
            seen_page_signatures.add(page_signature)

            new_ids_on_page = {p.posting_id for p in postings} - seen_posting_ids
            if page_idx > 0 and not new_ids_on_page:
                raise PaginationLoopError(
                    f"Detected cycle in pagination: page {page_idx} produced zero new postings",
                    "PAGINATION_CYCLE_DETECTED",
                )

            for posting in postings:
                seen_posting_ids.add(posting.posting_id)

            commit_result = fenced_page_commit(
                session=session,
                subscription_id=subscription_id,
                run_id=run.id,
                lease_token=lease_token,
                postings=postings,
                page_index=page_idx,
                skip=skip,
                page_limit=page_limit,
            )
            session.commit()

            total_seen += commit_result.items_seen
            total_new += commit_result.items_new
            total_updated += commit_result.items_updated
            total_duplicate += commit_result.items_duplicate
            pages_processed += 1

            if len(raw_page) < page_limit:
                terminated_early = True
                break
        else:
            # Check if there were additional pages beyond max_pages
            next_page = adapter.fetch_page(
                employer_handle, skip=max_pages * page_limit, limit=page_limit
            )
            if next_page:
                raise InvalidPaginationBoundsError(
                    f"Exceeded maximum page count of {max_pages}",
                    "MAX_PAGES_EXCEEDED",
                )

        completed_run = complete_discovery_run(
            session=session,
            subscription_id=subscription_id,
            run_id=run.id,
            lease_token=lease_token,
            seen_posting_ids=seen_posting_ids,
        )
        session.commit()
        return DiscoveryRunResult(
            run_id=completed_run.id,
            status=completed_run.status,
            items_seen=completed_run.items_seen_count,
            items_new=completed_run.items_new_count,
            items_updated=completed_run.items_updated_count,
            items_duplicate=completed_run.items_duplicate_count,
            pages_processed=pages_processed,
        )

    except KeyboardInterrupt:
        try:
            session.rollback()
            interrupt_discovery_run(
                session=session,
                subscription_id=subscription_id,
                run_id=run.id,
                lease_token=lease_token,
                reason="RUNNER_INTERRUPTED",
            )
            session.commit()
        except Exception:
            session.rollback()
        return DiscoveryRunResult(
            run_id=run.id,
            status=DiscoveryRunStatus.INTERRUPTED,
            items_seen=total_seen,
            items_new=total_new,
            items_updated=total_updated,
            items_duplicate=total_duplicate,
            pages_processed=pages_processed,
            error_code="RUNNER_INTERRUPTED",
            error_message="Execution interrupted by runner signal",
        )

    except LeaseFencingError as exc:
        try:
            session.rollback()
            fail_discovery_run(
                session=session,
                subscription_id=subscription_id,
                run_id=run.id,
                lease_token=lease_token,
                error_code="LEASE_FENCING_FAILED",
                error_message=str(exc),
                mutate_checkpoint=False,
            )
            session.commit()
        except Exception:
            session.rollback()
        return DiscoveryRunResult(
            run_id=run.id,
            status=DiscoveryRunStatus.FAILED,
            items_seen=total_seen,
            items_new=total_new,
            items_updated=total_updated,
            items_duplicate=total_duplicate,
            pages_processed=pages_processed,
            error_code="LEASE_FENCING_FAILED",
            error_message=str(exc),
        )

    except Exception as exc:
        error_code = getattr(exc, "code", type(exc).__name__)
        try:
            session.rollback()
            fail_discovery_run(
                session=session,
                subscription_id=subscription_id,
                run_id=run.id,
                lease_token=lease_token,
                error_code=error_code,
                error_message=str(exc),
                mutate_checkpoint=True,
            )
            session.commit()
        except Exception:
            session.rollback()
        return DiscoveryRunResult(
            run_id=run.id,
            status=DiscoveryRunStatus.FAILED,
            items_seen=total_seen,
            items_new=total_new,
            items_updated=total_updated,
            items_duplicate=total_duplicate,
            pages_processed=pages_processed,
            error_code=error_code,
            error_message=str(exc),
        )


def create_user_job_intake(
    session: Session,
    intake: UserJobIntake,
) -> tuple[JobPosting, JobPostingSnapshot]:
    """Create a user-controlled job intake record without live source access.

    Enforces:
    1. Input validation & boundaries (title 1-500 chars, description 20-50,000 chars, safe URL).
    2. Idempotent source record under capability_status='MANUAL_ONLY' and is_enabled=False.
    3. Normalization of employer handle matching ^[a-z0-9][a-z0-9_-]{0,127}$.
    4. Deterministic content hash and duplicate detection.
    5. Pure offline storage with provenance explicitly marked 'User-entered job intake; unverified by external source.'
    """
    clean_title = intake.title.strip()
    clean_desc = intake.description_plain.strip()
    clean_employer = (intake.employer_name or "user-provided").strip()

    # Generate valid employer handle conforming to ^[a-z0-9][a-z0-9_-]{0,127}$
    raw_handle = re.sub(r"[^a-z0-9_-]+", "-", clean_employer.lower()).strip("-_")
    if not raw_handle or not raw_handle[0].isalnum() or raw_handle in {".", ".."}:
        employer_handle = "user-provided"
    else:
        employer_handle = raw_handle[:128].rstrip("-_")
        if not employer_handle or not employer_handle[0].isalnum():
            employer_handle = "user-provided"

    # Deterministic content hash
    canonical_str = f"manual_intake\n{employer_handle}\n{clean_title}\n{clean_desc}"
    raw_hash = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    # Check for duplicate posting
    existing_posting = session.scalar(
        select(JobPosting)
        .join(EmployerSubscription, JobPosting.subscription_id == EmployerSubscription.id)
        .where(
            EmployerSubscription.source_name == "manual_intake",
            JobPosting.current_raw_hash == raw_hash,
        )
        .limit(1)
    )
    if existing_posting is not None:
        raise DuplicateJobPostingError(
            f"Job posting already exists with ID '{existing_posting.id}'",
            code="DUPLICATE_JOB_POSTING",
            posting_id=existing_posting.id,
        )

    now = datetime.now(timezone.utc)

    # Ensure JobSource: manual_intake in MANUAL_ONLY status (globally disabled)
    source = session.get(JobSource, "manual_intake")
    if source is None:
        source = JobSource(
            source_name="manual_intake",
            display_name="User Job Intake",
            capability_status=SourceCapabilityStatus.MANUAL_ONLY.value,
            is_enabled=False,
            terms_reviewed_at=None,
            terms_review_reference="User-entered job intake; unverified by external source.",
            rate_limit_requests_per_minute=10,
            min_poll_interval_seconds=43200,
        )
        session.add(source)
        session.flush()

    # Ensure EmployerSubscription
    sub = session.scalar(
        select(EmployerSubscription).where(
            EmployerSubscription.source_name == "manual_intake",
            EmployerSubscription.employer_handle == employer_handle,
        ).limit(1)
    )
    if sub is None:
        sub = EmployerSubscription(
            id=str(uuid4()),
            source_name="manual_intake",
            employer_handle=employer_handle,
            is_enabled=False,
        )
        session.add(sub)
        session.flush()

        checkpoint = DiscoveryCheckpoint(
            subscription_id=sub.id,
            last_successful_run_at=now,
            consecutive_failure_count=0,
            circuit_breaker_tripped=False,
        )
        session.add(checkpoint)
        session.flush()

    # Ensure a DiscoveryRun record for foreign key constraints
    run = session.scalar(
        select(DiscoveryRun).where(
            DiscoveryRun.subscription_id == sub.id,
            DiscoveryRun.status == "SUCCEEDED",
        ).order_by(DiscoveryRun.started_at.desc()).limit(1)
    )
    if run is None:
        run = DiscoveryRun(
            id=str(uuid4()),
            subscription_id=sub.id,
            status="SUCCEEDED",
            started_at=now,
            finished_at=now,
            items_seen_count=1,
            items_new_count=1,
            page_limit=50,
        )
        session.add(run)
        session.flush()

    # Create JobPosting
    posting_id_slug = f"user_{raw_hash[:16]}"
    posting = JobPosting(
        id=str(uuid4()),
        subscription_id=sub.id,
        posting_id=posting_id_slug,
        current_raw_hash=raw_hash,
        lifecycle_status="ACTIVE",
        last_seen_run_id=run.id,
        first_observed_at=now,
        last_observed_at=now,
    )
    session.add(posting)
    session.flush()

    # Create JobPostingSnapshot
    lists_json = intake.lists_json
    if not lists_json:
        lists_json = extract_sections_from_plain_text(clean_desc)

    clean_url = validate_reference_url(intake.canonical_url)

    snapshot = JobPostingSnapshot(
        id=str(uuid4()),
        subscription_id=sub.id,
        posting_id=posting.id,
        run_id=run.id,
        source_raw_hash=raw_hash,
        title=clean_title,
        location=intake.location.strip() if intake.location else None,
        workplace_type=intake.workplace_type.strip().lower() if intake.workplace_type else None,
        commitment=intake.commitment.strip() if intake.commitment else None,
        team=intake.team.strip() if intake.team else None,
        department=intake.department.strip() if intake.department else None,
        level=intake.level.strip() if intake.level else None,
        published_at=None,
        publication_date_status="UNKNOWN",
        canonical_url=clean_url,
        apply_url=clean_url,
        description_plain=clean_desc,
        description_html=None,
        lists_json=lists_json,
        additional_plain="User-entered job intake; unverified by external source.",
        captured_at=now,
    )
    session.add(snapshot)
    session.flush()

    return posting, snapshot
