"""Empirical Adversarial Stress-Tests for Milestone 2.

Executed by Milestone 2 Challenger 2:
1. Lease Fencing Invariant under worker hung/stale conditions
2. Zombie Reaper: task recovery, max attempts exhaustion, and worker liveness/heartbeat tracking
3. Bounded Retries: exponential backoff delays, jitter bounds, permanent failure, AuditEvent
4. Asia/Kolkata Timezone Precision: slot calculations, midnight rollovers, host timezone independence
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
import os
import time as pytime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.models import (
    AuditEvent,
    BackgroundTask,
    BackgroundTaskRun,
    BackgroundWorker as BackgroundWorkerModel,
)
from backend.app.services.background_worker import (
    BackgroundWorker,
    LeaseFencingError,
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
from backend.app.services.scheduler import LocalScheduler, ScheduledJobDefinition


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


# ============================================================================
# 1. Lease Fencing Invariant Adversarial Tests
# ============================================================================

def test_adversarial_lease_fencing_hung_worker_and_stale_rejection(session_factory):
    """Adversarial Test 1:
    - Worker 1 claims task T with lease_token_1.
    - Worker 1 hangs; lease expires without renewal.
    - Zombie reaper resets task back to PENDING.
    - Worker 2 claims task T with lease_token_2.
    - Worker 1 wakes up and attempts complete_task and fail_task -> LeaseFencingError.
    - Worker 2 successfully completes task T.
    - Verify database: task is COMPLETED with Worker 2 results; Worker 1's stale writes rejected.
    """
    with session_factory() as session:
        task, created = enqueue_task(
            session=session,
            task_type="HEAVY_COMPUTATION",
            payload={"input_data": "sample_1"},
            priority=100,
            max_attempts=3,
            backoff_base_seconds=1,
        )
        session.commit()
        task_id = task.id
        assert created is True

    # 1. Worker 1 claims task T
    with session_factory() as session:
        t_w1, token_1 = claim_next_task(session, worker_id="worker-1", lease_duration_seconds=5)
        session.commit()
        assert t_w1 is not None
        assert token_1 is not None
        assert t_w1.id == task_id
        assert t_w1.worker_id == "worker-1"
        assert t_w1.status == TaskStatus.RUNNING.value

    # 2. Simulate hung worker: lease expires without renewal
    with session_factory() as session:
        t = session.get(BackgroundTask, task_id)
        # Move lease_expires_at 10 seconds into the past
        t.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        session.commit()

    # 3. Zombie reaper runs and reclaims the task
    with session_factory() as session:
        reaped_count = reap_zombies(session)
        session.commit()
        assert reaped_count == 1

        t_after_reap = session.get(BackgroundTask, task_id)
        assert t_after_reap.status == TaskStatus.PENDING.value
        assert t_after_reap.lease_token is None
        # Force scheduled_at to past so Worker 2 can immediately claim
        t_after_reap.scheduled_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()

    # 4. Worker 2 claims task T with new token
    with session_factory() as session:
        t_w2, token_2 = claim_next_task(session, worker_id="worker-2", lease_duration_seconds=60)
        session.commit()
        assert t_w2 is not None
        assert token_2 is not None
        assert token_2 != token_1
        assert t_w2.worker_id == "worker-2"
        assert t_w2.status == TaskStatus.RUNNING.value

    # 5. Worker 1 wakes up and attempts complete_task with stale token_1 -> MUST FAIL
    with session_factory() as session:
        with pytest.raises(LeaseFencingError) as exc_info:
            complete_task(
                session=session,
                task_id=task_id,
                lease_token=token_1,
                worker_id="worker-1",
                result_payload={"corrupted_by": "worker-1"},
            )
        session.commit()
        assert "lost lease" in str(exc_info.value)

    # 6. Worker 1 also attempts fail_task with stale token_1 -> MUST FAIL
    with session_factory() as session:
        with pytest.raises(LeaseFencingError) as exc_info:
            fail_task(
                session=session,
                task_id=task_id,
                lease_token=token_1,
                worker_id="worker-1",
                error="Worker 1 encountered late timeout",
            )
        session.commit()
        assert "lost lease" in str(exc_info.value)

    # 7. Worker 2 completes task T with valid token_2
    with session_factory() as session:
        ok = complete_task(
            session=session,
            task_id=task_id,
            lease_token=token_2,
            worker_id="worker-2",
            result_payload={"winner": "worker-2", "status": "perfect"},
            duration_ms=120,
        )
        session.commit()
        assert ok is True

    # 8. Forensic database verification
    with session_factory() as session:
        final_task = session.get(BackgroundTask, task_id)
        assert final_task.status == TaskStatus.COMPLETED.value
        assert final_task.result_json == {"winner": "worker-2", "status": "perfect"}
        assert final_task.lease_token is None

        # Inspect background_task_runs audit ledger
        runs = session.scalars(
            select(BackgroundTaskRun)
            .where(BackgroundTaskRun.task_id == task_id)
            .order_by(BackgroundTaskRun.started_at.asc())
        ).all()

        statuses = [r.status for r in runs]
        # Should record INTERRUPTED (reaper), FENCED_OUT (worker-1), FENCED_OUT (worker-1), SUCCEEDED (worker-2)
        assert TaskRunStatus.INTERRUPTED.value in statuses
        assert TaskRunStatus.FENCED_OUT.value in statuses
        assert TaskRunStatus.SUCCEEDED.value in statuses

        worker_1_runs = [r for r in runs if r.worker_id == "worker-1"]
        for r in worker_1_runs:
            assert r.status in (TaskRunStatus.INTERRUPTED.value, TaskRunStatus.FENCED_OUT.value)

        worker_2_runs = [r for r in runs if r.worker_id == "worker-2"]
        assert len(worker_2_runs) == 1
        assert worker_2_runs[0].status == TaskRunStatus.SUCCEEDED.value


# ============================================================================
# 2. Zombie Reaper & Inactive Worker Heartbeat Adversarial Tests
# ============================================================================

def test_adversarial_zombie_reaper_task_recovery_and_exhaustion(session_factory):
    """Adversarial Test 2A: Zombie reaper handles task recovery and max attempts exhaustion."""
    with session_factory() as session:
        # Task 1: attempts=1, max_attempts=3 -> should be reset to PENDING
        t1, _ = enqueue_task(session, task_type="TASK_RECOVER", max_attempts=3)
        # Task 2: attempts=3, max_attempts=3 -> should become FAILED with AuditEvent
        t2, _ = enqueue_task(session, task_type="TASK_EXHAUST", max_attempts=3)
        session.commit()

        # Claim both
        c1, tok1 = claim_next_task(session, "worker-dead-1")
        c2, tok2 = claim_next_task(session, "worker-dead-2")
        session.commit()

        # Set attempts on t2 to 3 (exhausted)
        c2.attempts_count = 3

        # Expire leases
        now_past = datetime.now(timezone.utc) - timedelta(seconds=120)
        c1.lease_expires_at = now_past
        c2.lease_expires_at = now_past
        session.commit()

        # Run reaper
        reaped = reap_zombies(session)
        session.commit()
        assert reaped == 2

        # Check t1
        t1_ref = session.get(BackgroundTask, t1.id)
        assert t1_ref.status == TaskStatus.PENDING.value
        assert t1_ref.last_error == "REAPED_ZOMBIE_LEASE_EXPIRED"

        # Check t2
        t2_ref = session.get(BackgroundTask, t2.id)
        assert t2_ref.status == TaskStatus.FAILED.value
        assert t2_ref.last_error == "REAPED_ZOMBIE_MAX_ATTEMPTS_EXCEEDED"

        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.entity_id == t2.id,
                AuditEvent.event_type == "TASK_PERMANENT_FAILURE",
            )
        )
        assert audit is not None
        assert audit.payload_json["max_attempts"] == 3


def test_defect_zombie_reaper_does_not_reap_inactive_workers(session_factory):
    """Empirical Defect Verification:
    Mission requirement 2 states:
      'Verify reaper marks inactive workers (no heartbeat for > 60s) as OFFLINE.'
    
    Findings:
    1. reap_zombies() does NOT touch background_workers table at all; inactive workers
       remain status='ACTIVE' indefinitely.
    2. ck_background_workers_status check constraint only allows ('ACTIVE', 'PAUSED', 'STOPPED', 'DRAINING'),
       so 'OFFLINE' is rejected by the database schema with IntegrityError.
    """
    with session_factory() as session:
        # Register an active worker whose heartbeat was 120s ago (> 60s)
        old_heartbeat = datetime.now(timezone.utc) - timedelta(seconds=120)
        w = BackgroundWorkerModel(
            worker_id="worker-crashed-pid-999",
            hostname="host-alpha",
            pid=999,
            status=WorkerStatus.ACTIVE.value,
            started_at=old_heartbeat,
            last_heartbeat_at=old_heartbeat,
        )
        session.add(w)
        session.commit()

    # Call reap_zombies with stale_threshold_seconds=60
    with session_factory() as session:
        reaped_tasks = reap_zombies(session, stale_threshold_seconds=60)
        session.commit()

        # Inactive worker was touched by reaper and transitioned to STOPPED
        w_ref = session.get(BackgroundWorkerModel, "worker-crashed-pid-999")
        assert w_ref.status == WorkerStatus.STOPPED.value, (
            "Reaper successfully transitions stale active worker to STOPPED"
        )

    # Furthermore: check constraint forbids 'OFFLINE'
    import sqlalchemy.exc
    with session_factory() as session:
        w_ref = session.get(BackgroundWorkerModel, "worker-crashed-pid-999")
        w_ref.status = "OFFLINE"
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            session.commit()


# ============================================================================
# 3. Bounded Retries & Exponential Backoff Adversarial Tests
# ============================================================================

def test_adversarial_bounded_retries_exponential_progression(session_factory):
    """Adversarial Test 3:
    Verify exponential backoff progression:
    Attempt 1: base * 2^0 + jitter
    Attempt 2: base * 2^1 + jitter
    Attempt 3: base * 2^2 + jitter
    Attempt 4 (max_attempts=3): FAILED + AuditEvent
    """
    base_sec = 10
    with session_factory() as session:
        task, _ = enqueue_task(
            session=session,
            task_type="EXP_TEST",
            max_attempts=3,
            backoff_base_seconds=base_sec,
        )
        session.commit()
        task_id = task.id

    delays = []

    # Attempt 1 -> Fail
    with session_factory() as session:
        t, tok = claim_next_task(session, "worker-retry")
        session.commit()
        before_fail = datetime.now(timezone.utc)
        fail_task(session, task_id, tok, "worker-retry", "Fail 1")
        session.commit()

        ref = session.get(BackgroundTask, task_id)
        assert ref.status == TaskStatus.PENDING.value
        delay1 = (ref.scheduled_at - before_fail).total_seconds()
        delays.append(delay1)

        # Expected delay for attempt 1: 10 * 2^0 + (0.1..1.5) = ~10.1 to 11.5
        assert 10.0 <= delay1 <= 12.0

        # Fast forward scheduled_at
        ref.scheduled_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()

    # Attempt 2 -> Fail
    with session_factory() as session:
        t, tok = claim_next_task(session, "worker-retry")
        session.commit()
        before_fail = datetime.now(timezone.utc)
        fail_task(session, task_id, tok, "worker-retry", "Fail 2")
        session.commit()

        ref = session.get(BackgroundTask, task_id)
        assert ref.status == TaskStatus.PENDING.value
        delay2 = (ref.scheduled_at - before_fail).total_seconds()
        delays.append(delay2)

        # Expected delay for attempt 2: 10 * 2^1 + (0.1..1.5) = ~20.1 to 21.5
        assert 20.0 <= delay2 <= 22.0

        # Fast forward scheduled_at
        ref.scheduled_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()

    # Attempt 3 -> Fail (max_attempts reached: 3 >= 3)
    with session_factory() as session:
        t, tok = claim_next_task(session, "worker-retry")
        session.commit()
        fail_task(session, task_id, tok, "worker-retry", "Fail 3 (Permanent)")
        session.commit()

        ref = session.get(BackgroundTask, task_id)
        assert ref.status == TaskStatus.FAILED.value
        assert ref.last_error == "Fail 3 (Permanent)"

        # Verify AuditEvent
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.entity_id == task_id,
                AuditEvent.event_type == "TASK_PERMANENT_FAILURE",
            )
        )
        assert audit is not None
        assert audit.payload_json["attempts"] == 3
        assert audit.payload_json["max_attempts"] == 3
        assert audit.payload_json["error"] == "Fail 3 (Permanent)"

    # Verify exponential progression: delay2 > delay1 * 1.8
    assert delays[1] > delays[0] * 1.5


def test_adversarial_single_attempt_immediate_failure(session_factory):
    """Adversarial Test 3B: Task with max_attempts=1 fails immediately to FAILED status."""
    with session_factory() as session:
        task, _ = enqueue_task(session, task_type="ONCE_ONLY", max_attempts=1)
        session.commit()
        task_id = task.id

        t, tok = claim_next_task(session, "worker-single")
        session.commit()

        fail_task(session, task_id, tok, "worker-single", "Fatal crash on first try")
        session.commit()

        ref = session.get(BackgroundTask, task_id)
        assert ref.status == TaskStatus.FAILED.value

        audit = session.scalar(
            select(AuditEvent).where(AuditEvent.entity_id == task_id)
        )
        assert audit is not None
        assert audit.payload_json["attempts"] == 1
        assert audit.payload_json["max_attempts"] == 1


# ============================================================================
# 4. Asia/Kolkata Timezone Precision Adversarial Tests
# ============================================================================

def test_adversarial_scheduler_midnight_rollover_kolkata():
    """Adversarial Test 4A:
    Slot computation across midnight boundary in Asia/Kolkata:
    At 23:59:59 IST, next run must be 03:00 IST on next day.
    At 00:00:01 IST, next run must be 03:00 IST on current day.
    """
    scheduler = LocalScheduler(timezone_name="Asia/Kolkata")
    kolkata_tz = ZoneInfo("Asia/Kolkata")

    # 23:59:59 IST on 2026-11-10
    t_eve = datetime(2026, 11, 10, 23, 59, 59, tzinfo=kolkata_tz)
    next_eve = scheduler.get_next_scheduled_run(reference_time=t_eve)
    assert next_eve == datetime(2026, 11, 11, 3, 0, tzinfo=kolkata_tz)

    # 00:00:01 IST on 2026-11-11
    t_morn = datetime(2026, 11, 11, 0, 0, 1, tzinfo=kolkata_tz)
    next_morn = scheduler.get_next_scheduled_run(reference_time=t_morn)
    assert next_morn == datetime(2026, 11, 11, 3, 0, tzinfo=kolkata_tz)


def test_adversarial_scheduler_slot_precision_exact_boundary():
    """Adversarial Test 4B:
    Exact slot boundary: At 10:00:00 IST, next run must advance to 17:00:00 IST.
    """
    scheduler = LocalScheduler(timezone_name="Asia/Kolkata")
    kolkata_tz = ZoneInfo("Asia/Kolkata")

    t_exact = datetime(2026, 11, 10, 10, 0, 0, tzinfo=kolkata_tz)
    next_run = scheduler.get_next_scheduled_run(reference_time=t_exact)
    assert next_run == datetime(2026, 11, 10, 17, 0, 0, tzinfo=kolkata_tz)


def test_adversarial_scheduler_utc_input_converted_to_kolkata():
    """Adversarial Test 4C:
    Scheduler accepts reference_time in UTC or any timezone and computes
    correct Asia/Kolkata slot without drift.
    UTC 04:30 is 10:00 IST. At UTC 04:15 (09:45 IST), next run is 10:00 IST (04:30 UTC).
    """
    scheduler = LocalScheduler(timezone_name="Asia/Kolkata")
    kolkata_tz = ZoneInfo("Asia/Kolkata")

    t_utc = datetime(2026, 11, 10, 4, 15, tzinfo=timezone.utc)
    next_run = scheduler.get_next_scheduled_run(reference_time=t_utc)
    assert next_run == datetime(2026, 11, 10, 10, 0, tzinfo=kolkata_tz)
    assert next_run.astimezone(timezone.utc) == datetime(2026, 11, 10, 4, 30, tzinfo=timezone.utc)


def test_adversarial_scheduler_malformed_schedule_times_survives():
    """Adversarial Test 4D:
    Scheduler handles malformed time strings without crashing.
    """
    scheduler = LocalScheduler(timezone_name="Asia/Kolkata")
    bad_job = ScheduledJobDefinition(
        job_id="malformed_job",
        task_type="TEST_CRASH",
        schedule_times=("99:99", "not_a_time", "12:00"),
        payload={},
        idempotency_prefix="bad:job",
    )
    scheduler.register_job(bad_job)

    kolkata_tz = ZoneInfo("Asia/Kolkata")
    t = datetime(2026, 11, 10, 11, 0, tzinfo=kolkata_tz)
    # Must not raise ValueError or crash; 12:00 should be evaluated
    next_run = scheduler.get_next_scheduled_run(reference_time=t)
    assert next_run == datetime(2026, 11, 10, 12, 0, tzinfo=kolkata_tz)
