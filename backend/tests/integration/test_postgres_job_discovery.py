"""PostgreSQL integration tests for job discovery persistence, constraints, triggers, and fencing."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from conftest import PostgresDatabase, upgrade
from backend.app.db.models import (
    DiscoveryCheckpoint,
    DiscoveryRun,
    EmployerSubscription,
    JobPosting,
    JobPostingSnapshot,
    JobSource,
)
from backend.app.domain.job_posting import (
    DiscoveryRunStatus,
    LeaseFencingError,
    NormalizedPosting,
    PostingLifecycleStatus,
    SourceCapabilityStatus,
)
from backend.app.adapters.job_sources import FixtureJobSourceAdapter
from backend.app.adapters.lever import LeverPostingsAdapter
from backend.app.services.job_discovery import (
    orchestrate_discovery_run,
    begin_discovery_run,
    complete_discovery_run,
    create_employer_subscription,
    fenced_page_commit,
    get_subscription_checkpoint,
    interrupt_discovery_run,
    renew_subscription_lease,
)


pytestmark = pytest.mark.postgres


def test_upgrade_from_0003_adds_job_discovery_schema_and_seeds_lever(
    postgres_database: PostgresDatabase,
) -> None:
    upgrade(postgres_database, "0003_candidate_evidence")
    with postgres_database.engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0003_candidate_evidence"

    upgrade(postgres_database)
    inspector = inspect(postgres_database.engine)
    names = set(inspector.get_table_names(schema=postgres_database.schema))
    assert {
        "job_sources",
        "employer_subscriptions",
        "discovery_checkpoints",
        "discovery_runs",
        "job_postings",
        "job_posting_snapshots",
    } <= names

    with postgres_database.engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0004_job_discovery_persistence"
        lever_row = connection.execute(
            text("SELECT source_name, display_name, capability_status, is_enabled FROM job_sources WHERE source_name = 'lever'")
        ).one()
        assert lever_row == ("lever", "Lever Postings API", "NEEDS_REVIEW", False)


def test_job_discovery_downgrade_drops_discovery_tables_and_preserves_foundation(
    postgres_database: PostgresDatabase,
) -> None:
    upgrade(postgres_database)
    with postgres_database.session_factory() as session:
        sub = create_employer_subscription(session, "lever", "acme-corp")
        session.commit()

    config = Config("backend/alembic.ini")
    with postgres_database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0003_candidate_evidence")
        table_names = set(inspect(connection).get_table_names(schema=postgres_database.schema))

    assert "job_posting_snapshots" not in table_names
    assert "job_postings" not in table_names
    assert "discovery_runs" not in table_names
    assert "employer_subscriptions" not in table_names
    assert "job_sources" not in table_names
    assert "candidate_documents" in table_names
    assert "compensation_preferences" in table_names


def test_job_sources_active_gate_constraint_enforces_approved_status(
    postgres_database: PostgresDatabase,
) -> None:
    upgrade(postgres_database)
    # Lever is in NEEDS_REVIEW. Setting is_enabled = TRUE must fail check constraint
    with pytest.raises(IntegrityError):
        with postgres_database.engine.begin() as connection:
            connection.execute(
                text("UPDATE job_sources SET is_enabled = TRUE WHERE source_name = 'lever'")
            )

    # Transitioning to VERIFIED_READ_ONLY allows is_enabled = TRUE
    with postgres_database.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE job_sources SET capability_status = 'VERIFIED_READ_ONLY', is_enabled = TRUE "
                "WHERE source_name = 'lever'"
            )
        )
        assert connection.scalar(
            text("SELECT is_enabled FROM job_sources WHERE source_name = 'lever'")
        ) is True


def test_job_posting_snapshots_trigger_enforces_strict_immutability(
    postgres_database: PostgresDatabase,
) -> None:
    upgrade(postgres_database)
    with postgres_database.session_factory() as session:
        # Enable lever for test
        lever = session.get(JobSource, "lever")
        lever.capability_status = SourceCapabilityStatus.VERIFIED_READ_ONLY.value
        lever.is_enabled = True
        lever.terms_reviewed_at = datetime.now(timezone.utc)
        lever.terms_review_reference = "ADR-0012"
        session.commit()

        sub = create_employer_subscription(session, "lever", "immutability-corp")
        session.commit()
        sub_id = sub.id

        run, token = begin_discovery_run(session, sub_id)
        session.commit()
        run_id = run.id

        posting = NormalizedPosting(
            source="lever",
            employer_handle="immutability-corp",
            posting_id="snap-test-1",
            title="Immutable Role",
            description_plain="Description text",
            source_raw_hash="d" * 64,
        )
        fenced_page_commit(session, sub_id, run_id, token, [posting], 0, 0, 10)
        session.commit()

        snapshot = session.scalar(
            select(JobPostingSnapshot).where(JobPostingSnapshot.source_raw_hash == "d" * 64)
        )
        assert snapshot is not None
        snapshot_id = snapshot.id

    # Test UPDATE is blocked by PostgreSQL trigger
    with postgres_database.engine.begin() as connection:
        with pytest.raises(DBAPIError, match="immutable and cannot be updated"):
            connection.execute(
                text(f"UPDATE job_posting_snapshots SET title = 'Mutated' WHERE id = '{snapshot_id}'")
            )

    # Test DELETE is blocked by PostgreSQL trigger
    with postgres_database.engine.begin() as connection:
        with pytest.raises(DBAPIError, match="immutable and cannot be updated"):
            connection.execute(
                text(f"DELETE FROM job_posting_snapshots WHERE id = '{snapshot_id}'")
            )


def test_composite_foreign_keys_reject_cross_subscription_linkage(
    postgres_database: PostgresDatabase,
) -> None:
    upgrade(postgres_database)
    with postgres_database.session_factory() as session:
        lever = session.get(JobSource, "lever")
        lever.capability_status = SourceCapabilityStatus.VERIFIED_READ_ONLY.value
        lever.is_enabled = True
        lever.terms_reviewed_at = datetime.now(timezone.utc)
        lever.terms_review_reference = "ADR-0012"
        session.commit()

        sub_a = create_employer_subscription(session, "lever", "corp-a")
        sub_b = create_employer_subscription(session, "lever", "corp-b")
        session.commit()

        sub_b_id = sub_b.id
        run_a, _ = begin_discovery_run(session, sub_a.id)
        run_b, _ = begin_discovery_run(session, sub_b_id)
        session.commit()
        run_a_id = run_a.id

    # Attempt to create JobPosting with subscription_id = sub_b, but last_seen_run_id = run_a
    # fk_job_postings_run_composite must reject cross-subscription linkage!
    with postgres_database.engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO job_postings (id, subscription_id, posting_id, current_raw_hash, "
                    "lifecycle_status, consecutive_misses_count, version, first_observed_at, "
                    "last_observed_at, last_seen_run_id) "
                    f"VALUES ('p-cross', '{sub_b_id}', 'post-x', 'e" + ("0" * 63) + "', "
                    f"'ACTIVE', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, '{run_a_id}')"
                )
            )


def test_postgres_wall_clock_fencing_and_concurrent_lease_acquisition(
    postgres_database: PostgresDatabase,
) -> None:
    upgrade(postgres_database)
    with postgres_database.session_factory() as session:
        lever = session.get(JobSource, "lever")
        lever.capability_status = SourceCapabilityStatus.VERIFIED_READ_ONLY.value
        lever.is_enabled = True
        lever.terms_reviewed_at = datetime.now(timezone.utc)
        lever.terms_review_reference = "ADR-0012"
        session.commit()

        sub = create_employer_subscription(session, "lever", "fencing-corp")
        session.commit()
        sub_id = sub.id

        # Runner 1 acquires lease
        run1, token1 = begin_discovery_run(session, sub_id, lease_duration_minutes=10)
        session.commit()
        run1_id = run1.id
        assert run1.status == DiscoveryRunStatus.RUNNING
        assert token1 is not None

        # Runner 2 attempts concurrent acquisition -> skipped
        run2, token2 = begin_discovery_run(session, sub_id)
        session.commit()
        assert token2 is None
        assert run2.status == DiscoveryRunStatus.SKIPPED_CONCURRENT_LEASE
        assert run2.error_code == "LEASE_ACTIVE"

    # Simulate runner 1 lease expiry using PostgreSQL clock_timestamp() arithmetic
    with postgres_database.engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE employer_subscriptions SET lease_expires_at = clock_timestamp() - INTERVAL '5 seconds' "
                f"WHERE id = '{sub_id}'"
            )
        )

    # Runner 1 attempts fenced page commit after expiry -> raises LeaseFencingError
    with postgres_database.session_factory() as session:
        posting = NormalizedPosting(
            source="lever",
            employer_handle="fencing-corp",
            posting_id="late-post",
            title="Late Job",
            description_plain="Plain text",
            source_raw_hash="f" * 64,
        )
        with pytest.raises(LeaseFencingError):
            fenced_page_commit(session, sub_id, run1_id, token1, [posting], 0, 0, 10)

    # Runner 3 can now acquire the expired lease atomically
    with postgres_database.session_factory() as session:
        run3, token3 = begin_discovery_run(session, sub_id, lease_duration_minutes=10)
        session.commit()
        assert run3.status == DiscoveryRunStatus.RUNNING
        assert token3 is not None
        assert token3 != token1


def test_postgres_atomic_rollback_on_snapshot_failure(
    postgres_database: PostgresDatabase,
) -> None:
    upgrade(postgres_database)
    with postgres_database.session_factory() as session:
        lever = session.get(JobSource, "lever")
        lever.capability_status = SourceCapabilityStatus.VERIFIED_READ_ONLY.value
        lever.is_enabled = True
        lever.terms_reviewed_at = datetime.now(timezone.utc)
        lever.terms_review_reference = "ADR-0012"
        session.commit()

        sub = create_employer_subscription(session, "lever", "atomic-pg")
        session.commit()
        sub_id = sub.id

        run, token = begin_discovery_run(session, sub_id)
        session.commit()
        run_id = run.id

        posting1 = NormalizedPosting(
            source="lever",
            employer_handle="atomic-pg",
            posting_id="post-atomic-pg",
            title="Initial Role",
            description_plain="Version 1",
            source_raw_hash="1" * 64,
        )
        fenced_page_commit(session, sub_id, run_id, token, [posting1], 0, 0, 10)
        session.commit()

        # Injected failure during update snapshot creation
        posting1_updated = NormalizedPosting(
            source="lever",
            employer_handle="atomic-pg",
            posting_id="post-atomic-pg",
            title="Updated Role",
            description_plain="Version 2",
            source_raw_hash="2" * 64,
        )

        with patch.object(JobPostingSnapshot, "__init__", side_effect=RuntimeError("Simulated snapshot DB failure")):
            with pytest.raises(RuntimeError, match="Simulated snapshot DB failure"):
                fenced_page_commit(session, sub_id, run_id, token, [posting1_updated], 1, 1, 10)

        # Confirm atomic rollback: posting is still at v1 with hash "1"*64
        session.expire_all()
        db_post = session.scalar(
            select(JobPosting).where(JobPosting.subscription_id == sub_id, JobPosting.posting_id == "post-atomic-pg")
        )
        assert db_post.version == 1
        assert db_post.current_raw_hash == "1" * 64

        snapshots = session.scalars(
            select(JobPostingSnapshot).where(JobPostingSnapshot.posting_id == db_post.id)
        ).all()
        assert len(snapshots) == 1
        assert snapshots[0].source_raw_hash == "1" * 64


def test_postgres_posting_lifecycle_staleness_and_interruption(
    postgres_database: PostgresDatabase,
) -> None:
    upgrade(postgres_database)
    with postgres_database.session_factory() as session:
        lever = session.get(JobSource, "lever")
        lever.capability_status = SourceCapabilityStatus.VERIFIED_READ_ONLY.value
        lever.is_enabled = True
        lever.terms_reviewed_at = datetime.now(timezone.utc)
        lever.terms_review_reference = "ADR-0012"
        session.commit()

        sub = create_employer_subscription(session, "lever", "lifecycle-pg")
        session.commit()
        sub_id = sub.id

        run1, token1 = begin_discovery_run(session, sub_id)
        session.commit()
        run1_id = run1.id

        posting = NormalizedPosting(
            source="lever",
            employer_handle="lifecycle-pg",
            posting_id="post-pg-vanish",
            title="Vanishing Role",
            description_plain="Will disappear",
            source_raw_hash="3" * 64,
        )
        fenced_page_commit(session, sub_id, run1_id, token1, [posting], 0, 0, 10)
        complete_discovery_run(session, sub_id, run1_id, token1, seen_posting_ids={"post-pg-vanish"})
        session.commit()

        db_post = session.scalar(
            select(JobPosting).where(JobPosting.subscription_id == sub_id, JobPosting.posting_id == "post-pg-vanish")
        )
        assert db_post.lifecycle_status == PostingLifecycleStatus.ACTIVE
        assert db_post.consecutive_misses_count == 0

        # Simulate 31 days elapsed
        now = datetime.now(timezone.utc)
        db_post.last_observed_at = now - timedelta(days=31)
        session.commit()

        # Run 2 omits the posting -> transitions to STALE because > 30 days
        run2, token2 = begin_discovery_run(session, sub_id)
        session.commit()
        complete_discovery_run(session, sub_id, run2.id, token2, seen_posting_ids=set())
        session.commit()

        session.refresh(db_post)
        assert db_post.lifecycle_status == PostingLifecycleStatus.STALE

        # Run 3 test interruption
        run3, token3 = begin_discovery_run(session, sub_id)
        session.commit()
        interrupted = interrupt_discovery_run(session, sub_id, run3.id, token3, reason="SIGINT_RECEIVED")
        session.commit()
        assert interrupted.status == DiscoveryRunStatus.INTERRUPTED
        assert interrupted.error_code == "SIGINT_RECEIVED"

        checkpoint = get_subscription_checkpoint(session, sub_id)
        assert checkpoint.consecutive_failure_count == 0
        assert checkpoint.circuit_breaker_tripped is False


def test_postgres_orchestrate_discovery_run_e2e(
    postgres_database: PostgresDatabase,
) -> None:
    upgrade(postgres_database)
    with postgres_database.session_factory() as session:
        # Create approved test source
        source = JobSource(
            source_name="fixture_pg_ats",
            display_name="Fixture PG ATS",
            capability_status=SourceCapabilityStatus.VERIFIED_READ_ONLY.value,
            is_enabled=True,
            terms_reviewed_at=datetime.now(timezone.utc),
            terms_review_reference="ADR-0012-fixture-pg",
            rate_limit_requests_per_minute=10,
            min_poll_interval_seconds=43200,
        )
        session.add(source)
        session.commit()

        sub = create_employer_subscription(session, "fixture_pg_ats", "postgres-corp")
        session.commit()
        sub_id = sub.id

        page_0 = [
            {
                "id": "lever-pg-001",
                "text": "Senior Staff Architect",
                "createdAt": 1700000000000,
                "description": "<p>Build high-scale distributed systems.</p>",
                "hostedUrl": "https://jobs.lever.co/postgres-corp/lever-pg-001",
            }
        ]

        adapter = FixtureJobSourceAdapter(
            source_name="fixture_pg_ats",
            pages=[page_0],
            delegate_adapter=LeverPostingsAdapter(source_name="fixture_pg_ats"),
        )

        result = orchestrate_discovery_run(
            session,
            subscription_or_id=sub_id,
            adapter=adapter,
            page_limit=10,
        )

        assert result.status == DiscoveryRunStatus.SUCCEEDED
        assert result.items_seen == 1
        assert result.items_new == 1
        assert result.pages_processed == 1

        # Verify DB records
        posting = session.scalar(
            select(JobPosting).where(
                JobPosting.subscription_id == sub_id,
                JobPosting.posting_id == "lever-pg-001",
            )
        )
        assert posting is not None
        assert posting.version == 1
        assert posting.lifecycle_status == PostingLifecycleStatus.ACTIVE

        snapshot = session.scalar(
            select(JobPostingSnapshot).where(
                JobPostingSnapshot.subscription_id == sub_id,
                JobPostingSnapshot.posting_id == posting.id,
            )
        )
        assert snapshot is not None
        assert snapshot.title == "Senior Staff Architect"
        assert snapshot.source_raw_hash == posting.current_raw_hash

        checkpoint = get_subscription_checkpoint(session, sub_id)
        assert checkpoint.last_successful_run_at is not None
        assert checkpoint.consecutive_failure_count == 0

        # Lease released on Postgres
        refreshed_sub = session.get(EmployerSubscription, sub_id)
        assert refreshed_sub.lease_token is None
        assert refreshed_sub.lease_expires_at is None


def test_postgres_stale_worker_fenced_out_without_checkpoint_corruption(
    postgres_database: PostgresDatabase,
) -> None:
    upgrade(postgres_database)
    with postgres_database.session_factory() as session:
        source = JobSource(
            source_name="fixture_stale_pg",
            display_name="Fixture Stale PG",
            capability_status=SourceCapabilityStatus.VERIFIED_READ_ONLY.value,
            is_enabled=True,
            terms_reviewed_at=datetime.now(timezone.utc),
            terms_review_reference="ADR-0012-fixture-stale-pg",
            rate_limit_requests_per_minute=10,
            min_poll_interval_seconds=43200,
        )
        session.add(source)
        session.commit()

        sub = create_employer_subscription(session, "fixture_stale_pg", "stale-pg-corp")
        session.commit()
        sub_id = sub.id

        class InvalidateLeaseOnFetchAdapter(FixtureJobSourceAdapter):
            def fetch_page(self, employer_handle: str, skip: int, limit: int):
                # Simulates runner 2 stealing the lease while runner 1 is fetching
                with postgres_database.session_factory() as s2:
                    sub_db = s2.get(EmployerSubscription, sub_id)
                    sub_db.lease_token = "runner-2-active-lease"
                    sub_db.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
                    s2.commit()
                return super().fetch_page(employer_handle, skip, limit)

        page_data = [
            {
                "id": "lever-stale-001",
                "text": "Stale Attempt Role",
                "createdAt": 1700000000000,
                "hostedUrl": "https://jobs.lever.co/stale-pg-corp/lever-stale-001",
            }
        ]
        adapter = InvalidateLeaseOnFetchAdapter(
            source_name="fixture_stale_pg",
            pages=[page_data],
            delegate_adapter=LeverPostingsAdapter(source_name="fixture_stale_pg"),
        )

        result = orchestrate_discovery_run(session, sub_id, adapter, page_limit=10)
        assert result.status == DiscoveryRunStatus.FAILED
        assert result.error_code == "LEASE_FENCING_FAILED"

        # Stale worker was rejected by Postgres row lock; zero postings written
        postings = session.scalars(select(JobPosting).where(JobPosting.subscription_id == sub_id)).all()
        assert len(postings) == 0

        # Runner 2's active lease on Postgres was NOT cleared
        refreshed_sub = session.get(EmployerSubscription, sub_id)
        assert refreshed_sub.lease_token == "runner-2-active-lease"

        # Checkpoint failure count on Postgres was NOT incremented by the stale worker
        checkpoint = get_subscription_checkpoint(session, sub_id)
        assert checkpoint.consecutive_failure_count == 0
