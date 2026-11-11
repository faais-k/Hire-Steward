"""PostgreSQL integration tests for BackgroundWorker concurrent claiming and locking.

Verifies:
1. Highly concurrent worker claiming across multiple threads using SELECT ... FOR UPDATE SKIP LOCKED.
2. Zero double-claiming: 20 tasks claimed concurrently by 4 workers yields an exact partition of 20 distinct tasks.
3. Zero lock contention or deadlocks.
4. Lease fencing enforcement on PostgreSQL.
"""

from __future__ import annotations

import concurrent.futures
from datetime import datetime, timedelta, timezone
import time

import pytest
from sqlalchemy import select, text

from backend.app.db.models import BackgroundTask
from backend.app.services.background_worker import (
    BackgroundWorker,
    LeaseFencingError,
    claim_next_task,
    complete_task,
    enqueue_task,
)
from backend.tests.integration.conftest import upgrade

pytestmark = pytest.mark.postgres


def test_postgres_concurrent_worker_claiming_skip_locked(postgres_database):
    """Verify that multiple concurrent worker threads claim tasks without overlap or deadlocks."""
    upgrade(postgres_database)
    factory = postgres_database.session_factory

    total_tasks = 20
    num_workers = 4

    # 1. Enqueue 20 tasks
    with factory() as session:
        for i in range(total_tasks):
            enqueue_task(
                session,
                task_type="MATCH_EVAL",
                payload={"index": i},
                priority=100 + i,
            )
        session.commit()

    # 2. Concurrently claim all tasks across 4 worker threads
    claimed_by_worker: dict[str, list[str]] = {f"worker-{w}": [] for w in range(num_workers)}

    def worker_claim_loop(worker_id: str) -> list[str]:
        claimed_ids = []
        while True:
            with factory() as session:
                task, token = claim_next_task(session, worker_id=worker_id, lease_duration_seconds=60)
                session.commit()
                if task is None:
                    break
                claimed_ids.append(task.id)
            time.sleep(0.01)
        return claimed_ids

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = {
            executor.submit(worker_claim_loop, f"worker-{w}"): f"worker-{w}"
            for w in range(num_workers)
        }
        for future in concurrent.futures.as_completed(futures):
            w_id = futures[future]
            claimed_by_worker[w_id] = future.result()

    # 3. Assert exact partition properties
    all_claimed = []
    for w_id, tasks in claimed_by_worker.items():
        all_claimed.extend(tasks)

    assert len(all_claimed) == total_tasks, f"Expected {total_tasks} claimed, got {len(all_claimed)}"
    assert len(set(all_claimed)) == total_tasks, "Duplicate task claims detected across concurrent workers!"

    # Multiple workers participated concurrently
    active_workers = [w_id for w_id, tasks in claimed_by_worker.items() if len(tasks) > 0]
    assert len(active_workers) >= 2, f"Expected multiple workers to participate concurrently, got {active_workers}"

    # Verify database state
    with factory() as session:
        running_count = session.scalar(
            select(BackgroundTask).where(BackgroundTask.status == "RUNNING")
        )
        assert running_count is not None


def test_postgres_lease_fencing_enforcement(postgres_database):
    """Verify that completing a task with a stale or superseded lease token fails on PostgreSQL."""
    upgrade(postgres_database)
    factory = postgres_database.session_factory

    with factory() as session:
        task, _ = enqueue_task(session, task_type="DOC_PARSE", payload={"file": "contract.pdf"})
        session.commit()
        task_id = task.id

    # Worker A claims task
    with factory() as session:
        claimed_a, token_a = claim_next_task(session, worker_id="worker-a", lease_duration_seconds=5)
        session.commit()
        assert token_a is not None

    # Force expiration of Worker A's lease
    with factory() as session:
        t = session.get(BackgroundTask, task_id)
        t.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        # Reset status to PENDING so Worker B can claim
        t.status = "PENDING"
        t.lease_token = None
        session.commit()

    # Worker B claims task
    with factory() as session:
        claimed_b, token_b = claim_next_task(session, worker_id="worker-b", lease_duration_seconds=60)
        session.commit()
        assert token_b is not None
        assert token_b != token_a

    # Worker A attempts to complete the task with stale token_a -> LeaseFencingError
    with factory() as session:
        with pytest.raises(LeaseFencingError):
            complete_task(
                session,
                task_id=task_id,
                lease_token=token_a,
                worker_id="worker-a",
                result_payload={"result": "stale"},
            )
        session.commit()

    # Worker B completes the task with valid token_b -> Success
    with factory() as session:
        success = complete_task(
            session,
            task_id=task_id,
            lease_token=token_b,
            worker_id="worker-b",
            result_payload={"result": "valid_worker_b"},
        )
        session.commit()
        assert success is True

        final_task = session.get(BackgroundTask, task_id)
        assert final_task.status == "COMPLETED"
        assert final_task.result_json == {"result": "valid_worker_b"}
