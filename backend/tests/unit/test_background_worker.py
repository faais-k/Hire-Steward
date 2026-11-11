"""Unit tests for BackgroundWorker engine.

Covers:
1. Enqueue with idempotency deduplication.
2. Dialect-aware atomic claiming.
3. Strict lease fencing on completion and failure.
4. Bounded exponential retries with jitter and permanent failure AuditEvent.
5. Zombie reaper recovering expired leases.
6. Thread-safe lifecycle controls (start, pause, resume, stop, run_once).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.base import Base
from backend.app.db.models import (
    AuditEvent,
    BackgroundTask,
    BackgroundTaskRun,
    BackgroundWorker as BackgroundWorkerModel,
)
from backend.app.services.background_worker import (
    BackgroundWorker,
    LeaseFencingError,
    TaskHandlerNotFoundError,
    TaskRunStatus,
    TaskStatus,
    WorkerStatus,
    claim_next_task,
    complete_task,
    enqueue_task,
    fail_task,
    reap_zombies,
    renew_task_lease,
)


from alembic import command
from alembic.config import Config


@pytest.fixture
def session_factory():
    """Isolated in-memory SQLite database migrated to Alembic head."""
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    config = Config("backend/alembic.ini")
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


def test_enqueue_task_creates_new_row(session_factory):
    with session_factory() as session:
        task, created = enqueue_task(
            session=session,
            task_type="DOC_PARSE",
            payload={"doc_id": "doc-123"},
            priority=150,
        )
        session.commit()

        assert created is True
        assert task.id is not None
        assert task.task_type == "DOC_PARSE"
        assert task.status == TaskStatus.PENDING.value
        assert task.priority == 150
        assert task.payload_json == {"doc_id": "doc-123"}
        assert task.attempts_count == 0


def test_enqueue_task_idempotency_deduplication(session_factory):
    with session_factory() as session:
        task1, created1 = enqueue_task(
            session=session,
            task_type="DOC_PARSE",
            payload={"doc_id": "doc-1"},
            idempotency_key="doc-parse-key-1",
        )
        session.commit()
        assert created1 is True

        # Second enqueue with identical idempotency key returns existing row
        task2, created2 = enqueue_task(
            session=session,
            task_type="DOC_PARSE",
            payload={"doc_id": "doc-1"},
            idempotency_key="doc-parse-key-1",
        )
        session.commit()
        assert created2 is False
        assert task2.id == task1.id

        # Even after completion, re-enqueue deduplicates cleanly
        task1.status = TaskStatus.COMPLETED.value
        session.commit()

        task3, created3 = enqueue_task(
            session=session,
            task_type="DOC_PARSE",
            payload={"doc_id": "doc-1"},
            idempotency_key="doc-parse-key-1",
        )
        session.commit()
        assert created3 is False
        assert task3.id == task1.id


def test_claim_next_task_priority_ordering(session_factory):
    with session_factory() as session:
        # Enqueue low priority task first, then high priority task
        t_low, _ = enqueue_task(
            session=session,
            task_type="DOC_PARSE",
            payload={"priority": "low"},
            priority=10,
        )
        t_high, _ = enqueue_task(
            session=session,
            task_type="MATCH_EVAL",
            payload={"priority": "high"},
            priority=200,
        )
        session.commit()

        # Worker claims next task -> must claim high priority first
        claimed, token = claim_next_task(session, worker_id="worker-test-1", lease_duration_seconds=30)
        session.commit()

        assert claimed is not None
        assert token is not None
        assert claimed.id == t_high.id
        assert claimed.status == TaskStatus.RUNNING.value
        assert claimed.lease_token == token
        assert claimed.worker_id == "worker-test-1"
        assert claimed.attempts_count == 1

        # Second claim gets low priority task
        claimed2, token2 = claim_next_task(session, worker_id="worker-test-1", lease_duration_seconds=30)
        session.commit()
        assert claimed2 is not None
        assert claimed2.id == t_low.id

        # Third claim returns None (no pending tasks)
        claimed3, token3 = claim_next_task(session, worker_id="worker-test-1")
        assert claimed3 is None
        assert token3 is None


def test_renew_task_lease_extends_expiry(session_factory):
    with session_factory() as session:
        task, _ = enqueue_task(session=session, task_type="DOC_PARSE")
        session.commit()

        claimed, token = claim_next_task(session, worker_id="worker-test-1", lease_duration_seconds=20)
        session.commit()

        # Renew lease with valid token
        renewed = renew_task_lease(session, claimed.id, token, duration_seconds=60)
        session.commit()
        assert renewed is True

        # Renew lease with bogus token fails (fencing rejection)
        bogus_renewed = renew_task_lease(session, claimed.id, "bogus-token", duration_seconds=60)
        assert bogus_renewed is False


def test_complete_task_with_lease_fencing(session_factory):
    with session_factory() as session:
        task, _ = enqueue_task(session=session, task_type="DOC_PARSE")
        session.commit()

        claimed, token = claim_next_task(session, worker_id="worker-1", lease_duration_seconds=60)
        session.commit()

        # Completing with incorrect token raises LeaseFencingError and logs FENCED_OUT run
        with pytest.raises(LeaseFencingError):
            complete_task(
                session,
                task_id=claimed.id,
                lease_token="invalid-token",
                worker_id="worker-1",
                result_payload={"data": "test"},
            )
        session.commit()

        fenced_run = session.scalar(
            select(BackgroundTaskRun).where(
                BackgroundTaskRun.task_id == claimed.id,
                BackgroundTaskRun.status == TaskRunStatus.FENCED_OUT.value,
            )
        )
        assert fenced_run is not None

        # Completing with valid token succeeds and logs SUCCEEDED run
        completed = complete_task(
            session,
            task_id=claimed.id,
            lease_token=token,
            worker_id="worker-1",
            result_payload={"parsed_sections": 5},
            duration_ms=45,
        )
        session.commit()
        assert completed is True

        refreshed = session.get(BackgroundTask, claimed.id)
        assert refreshed.status == TaskStatus.COMPLETED.value
        assert refreshed.result_json == {"parsed_sections": 5}
        assert refreshed.lease_token is None

        succeeded_run = session.scalar(
            select(BackgroundTaskRun).where(
                BackgroundTaskRun.task_id == claimed.id,
                BackgroundTaskRun.status == TaskRunStatus.SUCCEEDED.value,
            )
        )
        assert succeeded_run is not None
        assert succeeded_run.duration_ms == 45


def test_fail_task_retries_and_permanent_failure(session_factory):
    with session_factory() as session:
        task, _ = enqueue_task(
            session=session,
            task_type="DOC_PARSE",
            max_attempts=2,
            backoff_base_seconds=1,
        )
        session.commit()

        # Attempt 1: Claim and fail
        claimed1, token1 = claim_next_task(session, worker_id="worker-1")
        session.commit()
        assert claimed1.attempts_count == 1

        fail_task(
            session,
            task_id=claimed1.id,
            lease_token=token1,
            worker_id="worker-1",
            error="Transient disk timeout",
        )
        session.commit()

        # Should be reset to PENDING for retry because attempts (1) < max_attempts (2)
        refreshed1 = session.get(BackgroundTask, claimed1.id)
        assert refreshed1.status == TaskStatus.PENDING.value
        assert refreshed1.last_error == "Transient disk timeout"
        assert refreshed1.scheduled_at > datetime.now(timezone.utc) - timedelta(seconds=1)

        # Force scheduled_at into the past so it can be claimed for attempt 2
        refreshed1.scheduled_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        session.commit()

        # Attempt 2: Claim and fail again
        claimed2, token2 = claim_next_task(session, worker_id="worker-1")
        session.commit()
        assert claimed2.attempts_count == 2

        fail_task(
            session,
            task_id=claimed2.id,
            lease_token=token2,
            worker_id="worker-1",
            error="Permanent corruption",
        )
        session.commit()

        # Attempts exhausted (2 >= 2) -> status must be FAILED and AuditEvent emitted
        refreshed2 = session.get(BackgroundTask, claimed2.id)
        assert refreshed2.status == TaskStatus.FAILED.value
        assert refreshed2.last_error == "Permanent corruption"

        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.event_type == "TASK_PERMANENT_FAILURE",
                AuditEvent.entity_id == claimed2.id,
            )
        )
        assert audit is not None
        assert audit.payload_json["attempts"] == 2
        assert audit.payload_json["max_attempts"] == 2


def test_reap_zombies_recovers_expired_running_tasks(session_factory):
    with session_factory() as session:
        task, _ = enqueue_task(session=session, task_type="DOC_PARSE", max_attempts=3)
        session.commit()

        claimed, token = claim_next_task(session, worker_id="worker-dead", lease_duration_seconds=10)
        session.commit()

        # Simulate expired lease by moving lease_expires_at into the past
        claimed.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=60)
        session.commit()

        # Run zombie reaper
        reaped = reap_zombies(session)
        session.commit()
        assert reaped == 1

        refreshed = session.get(BackgroundTask, claimed.id)
        assert refreshed.status == TaskStatus.PENDING.value
        assert refreshed.last_error == "REAPED_ZOMBIE_LEASE_EXPIRED"
        assert refreshed.lease_token is None

        interrupted_run = session.scalar(
            select(BackgroundTaskRun).where(
                BackgroundTaskRun.task_id == claimed.id,
                BackgroundTaskRun.status == TaskRunStatus.INTERRUPTED.value,
            )
        )
        assert interrupted_run is not None


def test_background_worker_run_once_execution(session_factory):
    worker = BackgroundWorker(session_factory=session_factory, worker_id="worker-unit-test")

    # Define custom handler
    handled_payloads = []

    def custom_handler(payload: dict, session: Session) -> dict:
        handled_payloads.append(payload)
        return {"processed": True, "count": 42}

    worker.register_handler("TEST_JOB", custom_handler)

    # 1. run_once when queue is empty returns False
    assert worker.run_once() is False

    # 2. Enqueue task and execute via run_once
    with session_factory() as session:
        task, _ = enqueue_task(session=session, task_type="TEST_JOB", payload={"val": 100})
        session.commit()

    did_run = worker.run_once()
    assert did_run is True
    assert len(handled_payloads) == 1
    assert handled_payloads[0] == {"val": 100}

    with session_factory() as session:
        t_row = session.get(BackgroundTask, task.id)
        assert t_row.status == TaskStatus.COMPLETED.value
        assert t_row.result_json == {"processed": True, "count": 42}


def test_background_worker_lifecycle_controls(session_factory):
    worker = BackgroundWorker(
        session_factory=session_factory,
        worker_id="worker-lifecycle-test",
        poll_interval_seconds=0.1,
    )
    assert worker.status == WorkerStatus.STOPPED

    worker.start()
    assert worker.status == WorkerStatus.ACTIVE

    worker.pause()
    assert worker.status == WorkerStatus.PAUSED

    worker.resume()
    assert worker.status == WorkerStatus.ACTIVE

    worker.stop(drain_timeout_seconds=2.0)
    assert worker.status == WorkerStatus.STOPPED
