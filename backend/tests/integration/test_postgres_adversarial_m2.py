"""PostgreSQL Integration Adversarial Stress-Tests for Milestone 2.

Executed by Milestone 2 Challenger 2 on PostgreSQL:
1. True PostgreSQL lease fencing with concurrent hung worker and active replacement
2. PostgreSQL task run audit ledger validation under lease fencing failure
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from backend.app.db.models import (
    AuditEvent,
    BackgroundTask,
    BackgroundTaskRun,
    BackgroundWorker as BackgroundWorkerModel,
)
from backend.app.services.background_worker import (
    LeaseFencingError,
    TaskRunStatus,
    TaskStatus,
    WorkerStatus,
    claim_next_task,
    complete_task,
    enqueue_task,
    fail_task,
    reap_zombies,
)
from backend.tests.integration.conftest import upgrade

pytestmark = pytest.mark.postgres


def test_postgres_adversarial_lease_fencing_hung_worker_and_stale_rejection(postgres_database):
    """PostgreSQL Adversarial Test:
    - Worker 1 claims task T with lease_duration_seconds=5 on PostgreSQL.
    - Worker 1 hangs; lease expires without renewal.
    - Reaper reclaims task back to PENDING.
    - Worker 2 claims task T with new lease token.
    - Worker 1 wakes up and attempts complete_task and fail_task -> LeaseFencingError.
    - Worker 2 successfully completes task T.
    - Verify Postgres DB state: task is COMPLETED with Worker 2's payload, stale writes rejected.
    """
    upgrade(postgres_database)
    factory = postgres_database.session_factory

    with factory() as session:
        task, created = enqueue_task(
            session=session,
            task_type="POSTGRES_HEAVY",
            payload={"action": "calculate", "version": 1},
            priority=200,
            max_attempts=3,
            backoff_base_seconds=1,
        )
        session.commit()
        task_id = task.id
        assert created is True

    # 1. Worker 1 claims task
    with factory() as session:
        t_w1, token_1 = claim_next_task(session, worker_id="pg-worker-1", lease_duration_seconds=5)
        session.commit()
        assert t_w1 is not None
        assert token_1 is not None
        assert t_w1.worker_id == "pg-worker-1"
        assert t_w1.status == TaskStatus.RUNNING.value

    # 2. Simulate hung worker: lease expires
    with factory() as session:
        t = session.get(BackgroundTask, task_id)
        t.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=15)
        session.commit()

    # 3. Zombie reaper runs on PostgreSQL
    with factory() as session:
        reaped = reap_zombies(session)
        session.commit()
        assert reaped == 1

        t_reaped = session.get(BackgroundTask, task_id)
        assert t_reaped.status == TaskStatus.PENDING.value
        assert t_reaped.lease_token is None
        # Make immediately claimable
        t_reaped.scheduled_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()

    # 4. Worker 2 claims task on PostgreSQL
    with factory() as session:
        t_w2, token_2 = claim_next_task(session, worker_id="pg-worker-2", lease_duration_seconds=60)
        session.commit()
        assert t_w2 is not None
        assert token_2 is not None
        assert token_2 != token_1
        assert t_w2.worker_id == "pg-worker-2"
        assert t_w2.status == TaskStatus.RUNNING.value

    # 5. Worker 1 attempts complete_task -> MUST raise LeaseFencingError
    with factory() as session:
        with pytest.raises(LeaseFencingError) as exc_info:
            complete_task(
                session=session,
                task_id=task_id,
                lease_token=token_1,
                worker_id="pg-worker-1",
                result_payload={"corrupted": True},
            )
        session.commit()
        assert "lost lease" in str(exc_info.value)

    # 6. Worker 1 attempts fail_task -> MUST raise LeaseFencingError
    with factory() as session:
        with pytest.raises(LeaseFencingError) as exc_info:
            fail_task(
                session=session,
                task_id=task_id,
                lease_token=token_1,
                worker_id="pg-worker-1",
                error="Late crash from worker 1",
            )
        session.commit()
        assert "lost lease" in str(exc_info.value)

    # 7. Worker 2 completes task
    with factory() as session:
        ok = complete_task(
            session=session,
            task_id=task_id,
            lease_token=token_2,
            worker_id="pg-worker-2",
            result_payload={"winner": "pg-worker-2", "records_processed": 500},
            duration_ms=250,
        )
        session.commit()
        assert ok is True

    # 8. Verify database state
    with factory() as session:
        final_task = session.get(BackgroundTask, task_id)
        assert final_task.status == TaskStatus.COMPLETED.value
        assert final_task.result_json == {"winner": "pg-worker-2", "records_processed": 500}
        assert final_task.lease_token is None

        # Verify task run records
        runs = session.scalars(
            select(BackgroundTaskRun)
            .where(BackgroundTaskRun.task_id == task_id)
            .order_by(BackgroundTaskRun.started_at.asc())
        ).all()

        statuses = [r.status for r in runs]
        assert TaskRunStatus.INTERRUPTED.value in statuses
        assert TaskRunStatus.FENCED_OUT.value in statuses
        assert TaskRunStatus.SUCCEEDED.value in statuses
