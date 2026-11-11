"""Durable database-backed background worker engine with atomic claiming, lease fencing, and heartbeats.

Conforms to Hire-Steward specification R3:
- Dialect-aware atomic claiming:
  - PostgreSQL: SELECT ... FOR UPDATE SKIP LOCKED
  - SQLite: single-writer serialized transaction claiming
- Background heartbeat daemon renewing lease_expires_at and worker liveness
- Strict lease fencing on task completion and failure
- Idempotency deduplication at enqueue and execution time
- Bounded retries with exponential backoff and jitter
- Periodic zombie task reaper
- Thread-safe lifecycle controls (start, pause, resume, stop)
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from enum import Enum
import logging
import os
import random
import socket
import threading
import time
from typing import Any
from uuid import uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.db.models import (
    AuditEvent,
    BackgroundTask,
    BackgroundTaskRun,
    BackgroundWorker as BackgroundWorkerModel,
)

logger = logging.getLogger("hire_steward.background_worker")


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    PAUSED = "PAUSED"


class WorkerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    DRAINING = "DRAINING"


class TaskRunStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    FENCED_OUT = "FENCED_OUT"
    CANCELLED = "CANCELLED"


class WorkerEngineError(Exception):
    """Base class for background worker engine errors."""


class LeaseFencingError(WorkerEngineError):
    """Raised when lease token is invalid, expired, or superseded by another worker."""


class TaskHandlerNotFoundError(WorkerEngineError):
    """Raised when no handler is registered for a task type."""


TaskHandler = Callable[[dict[str, Any], Session], dict[str, Any] | None]


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
    return now or datetime.now(timezone.utc)


def enqueue_task(
    session: Session,
    task_type: str,
    payload: dict[str, Any] | None = None,
    priority: int = 100,
    scheduled_at: datetime | None = None,
    idempotency_key: str | None = None,
    max_attempts: int = 3,
    backoff_base_seconds: int = 10,
) -> tuple[BackgroundTask, bool]:
    """Enqueue a new background task with idempotency deduplication.

    Returns (task, created):
    - created=True: A new task row was inserted.
    - created=False: An existing task was returned due to idempotency deduplication.
    """
    now = _get_db_wall_clock(session)
    effective_scheduled_at = scheduled_at or now

    if idempotency_key:
        existing = session.scalar(
            select(BackgroundTask).where(BackgroundTask.idempotency_key == idempotency_key)
        )
        if existing is not None:
            if existing.status in (
                TaskStatus.COMPLETED.value,
                TaskStatus.PENDING.value,
                TaskStatus.RUNNING.value,
            ):
                return existing, False

            # If failed or cancelled, re-enqueue existing task
            existing.status = TaskStatus.PENDING.value
            existing.payload_json = payload or {}
            existing.priority = priority
            existing.scheduled_at = effective_scheduled_at
            existing.attempts_count = 0
            existing.last_error = None
            existing.lease_token = None
            existing.lease_expires_at = None
            existing.result_json = None
            existing.updated_at = now
            session.flush()
            return existing, False

    task = BackgroundTask(
        id=str(uuid4()),
        task_type=task_type,
        payload_json=payload or {},
        priority=priority,
        status=TaskStatus.PENDING.value,
        idempotency_key=idempotency_key,
        scheduled_at=effective_scheduled_at,
        attempts_count=0,
        max_attempts=max_attempts,
        backoff_base_seconds=backoff_base_seconds,
        created_at=now,
        updated_at=now,
    )
    if idempotency_key:
        try:
            session.add(task)
            session.flush()
        except IntegrityError:
            # Handle concurrent race condition on duplicate idempotency_key enqueue
            session.rollback()
            existing = session.scalar(
                select(BackgroundTask).where(BackgroundTask.idempotency_key == idempotency_key)
            )
            if existing is not None:
                return existing, False
            raise
    else:
        session.add(task)
        session.flush()
    return task, True


def claim_next_task(
    session: Session,
    worker_id: str,
    lease_duration_seconds: int = 60,
    max_claim_attempts: int = 5,
) -> tuple[BackgroundTask | None, str | None]:
    """Atomically claim the next eligible PENDING task using dialect-aware locking.

    Returns (task, lease_token) or (None, None).
    """
    bind = session.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    lease_token = str(uuid4())
    now = _get_db_wall_clock(session)
    new_lease = now + timedelta(seconds=lease_duration_seconds)

    for _ in range(max_claim_attempts if is_sqlite else 1):
        stmt = (
            select(BackgroundTask)
            .where(
                BackgroundTask.status == TaskStatus.PENDING.value,
                or_(
                    BackgroundTask.scheduled_at.is_(None),
                    BackgroundTask.scheduled_at <= now,
                ),
            )
            .order_by(BackgroundTask.priority.desc(), BackgroundTask.scheduled_at.asc())
            .limit(1)
        )
        if not is_sqlite:
            stmt = stmt.with_for_update(skip_locked=True)

        task = session.scalar(stmt)
        if task is None:
            return None, None

        if is_sqlite:
            # Atomic conditional update on SQLite to prevent race condition double claims
            updated_rows = session.execute(
                update(BackgroundTask)
                .where(
                    BackgroundTask.id == task.id,
                    BackgroundTask.status == TaskStatus.PENDING.value,
                )
                .values(
                    status=TaskStatus.RUNNING.value,
                    lease_token=lease_token,
                    worker_id=worker_id,
                    started_at=now,
                    lease_expires_at=new_lease,
                    attempts_count=BackgroundTask.attempts_count + 1,
                    updated_at=now,
                )
            ).rowcount
            if updated_rows > 0:
                session.refresh(task)
                return task, lease_token
            # Contention: another worker claimed this task, try next candidate
            continue

        task.status = TaskStatus.RUNNING.value
        task.lease_token = lease_token
        task.worker_id = worker_id
        task.started_at = now
        task.lease_expires_at = new_lease
        task.attempts_count += 1
        task.updated_at = now
        session.flush()
        return task, lease_token

    return None, None


def renew_task_lease(
    session: Session,
    task_id: str,
    lease_token: str,
    duration_seconds: int = 60,
) -> bool:
    """Extend runner lease expiry for active task. Returns True if lease renewed, False if fenced out."""
    now = _get_db_wall_clock(session)
    task = session.get(BackgroundTask, task_id)
    if (
        task is None
        or task.lease_token != lease_token
        or task.status != TaskStatus.RUNNING.value
    ):
        return False
    task.lease_expires_at = now + timedelta(seconds=duration_seconds)
    task.updated_at = now
    session.flush()
    return True


def complete_task(
    session: Session,
    task_id: str,
    lease_token: str,
    worker_id: str,
    result_payload: dict[str, Any] | None = None,
    duration_ms: int = 0,
) -> bool:
    """Atomically complete a background task with strict lease fencing."""
    now = _get_db_wall_clock(session)
    task = session.get(BackgroundTask, task_id)
    attempts = task.attempts_count if task else 1
    started = task.started_at if task and task.started_at else now

    if (
        task is None
        or task.lease_token != lease_token
        or task.status != TaskStatus.RUNNING.value
    ):
        # Fenced out
        run_record = BackgroundTaskRun(
            id=str(uuid4()),
            task_id=task_id,
            attempt_number=attempts,
            worker_id=worker_id,
            started_at=started,
            finished_at=now,
            status=TaskRunStatus.FENCED_OUT.value,
            duration_ms=duration_ms,
            error_message="Lease fencing violation: worker token mismatch or expired lease",
        )
        session.add(run_record)
        session.flush()
        raise LeaseFencingError(
            f"Lease fencing error: Worker '{worker_id}' lost lease on task '{task_id}'"
        )

    task.status = TaskStatus.COMPLETED.value
    task.result_json = result_payload or {}
    task.finished_at = now
    task.lease_token = None
    task.lease_expires_at = None
    task.updated_at = now

    run_record = BackgroundTaskRun(
        id=str(uuid4()),
        task_id=task_id,
        attempt_number=attempts,
        worker_id=worker_id,
        started_at=started,
        finished_at=now,
        status=TaskRunStatus.SUCCEEDED.value,
        duration_ms=duration_ms,
        error_message=None,
    )
    session.add(run_record)
    session.flush()
    return True


def fail_task(
    session: Session,
    task_id: str,
    lease_token: str,
    worker_id: str,
    error: Exception | str,
    duration_ms: int = 0,
) -> bool:
    """Record task failure with lease fencing, bounded exponential backoff retry, or permanent failure."""
    now = _get_db_wall_clock(session)
    error_msg = str(error) if isinstance(error, Exception) else error

    task = session.get(BackgroundTask, task_id)
    if task is None:
        return False

    attempts = task.attempts_count
    max_attempts = task.max_attempts
    started = task.started_at or now

    # Lease fencing check
    if task.lease_token != lease_token or task.status != TaskStatus.RUNNING.value:
        run_record = BackgroundTaskRun(
            id=str(uuid4()),
            task_id=task_id,
            attempt_number=attempts,
            worker_id=worker_id,
            started_at=started,
            finished_at=now,
            status=TaskRunStatus.FENCED_OUT.value,
            duration_ms=duration_ms,
            error_message=f"Fenced out on failure: {error_msg}",
        )
        session.add(run_record)
        session.flush()
        raise LeaseFencingError(
            f"Lease fencing error: Worker '{worker_id}' lost lease on task '{task_id}'"
        )

    run_record = BackgroundTaskRun(
        id=str(uuid4()),
        task_id=task_id,
        attempt_number=attempts,
        worker_id=worker_id,
        started_at=started,
        finished_at=now,
        status=TaskRunStatus.FAILED.value,
        duration_ms=duration_ms,
        error_message=error_msg,
    )
    session.add(run_record)

    if attempts < max_attempts:
        # Exponential backoff with jitter
        delay = task.backoff_base_seconds * (2 ** (attempts - 1)) + random.uniform(0.1, 1.5)
        task.status = TaskStatus.PENDING.value
        task.scheduled_at = now + timedelta(seconds=delay)
        task.last_error = error_msg
        task.lease_token = None
        task.lease_expires_at = None
        task.updated_at = now
    else:
        # Permanent failure
        task.status = TaskStatus.FAILED.value
        task.finished_at = now
        task.last_error = error_msg
        task.lease_token = None
        task.lease_expires_at = None
        task.updated_at = now

        audit = AuditEvent(
            id=str(uuid4()),
            event_type="TASK_PERMANENT_FAILURE",
            entity_type="BACKGROUND_TASK",
            entity_id=task_id,
            actor_type="WORKER",
            actor_id=worker_id,
            payload_json={
                "task_type": task.task_type,
                "attempts": attempts,
                "max_attempts": max_attempts,
                "error": error_msg,
            },
            created_at=now,
        )
        session.add(audit)

    session.flush()
    return True


def reap_zombies(session: Session, stale_threshold_seconds: int = 60) -> int:
    """Recover tasks abandoned by dead or partitioned workers whose lease has expired."""
    now = _get_db_wall_clock(session)

    stale_tasks = session.scalars(
        select(BackgroundTask).where(
            BackgroundTask.status == TaskStatus.RUNNING.value,
            BackgroundTask.lease_expires_at <= now,
        )
    ).all()

    reaped_count = 0
    for task in stale_tasks:
        reaped_count += 1
        run_record = BackgroundTaskRun(
            id=str(uuid4()),
            task_id=task.id,
            attempt_number=task.attempts_count,
            worker_id=task.worker_id or "unknown",
            started_at=task.started_at or now,
            finished_at=now,
            status=TaskRunStatus.INTERRUPTED.value,
            duration_ms=0,
            error_message="Worker lease expired; reclaimed by zombie reaper",
        )
        session.add(run_record)

        if task.attempts_count < task.max_attempts:
            delay = task.backoff_base_seconds * (2 ** task.attempts_count) + random.uniform(0.5, 2.0)
            task.status = TaskStatus.PENDING.value
            task.scheduled_at = now + timedelta(seconds=delay)
            task.lease_token = None
            task.lease_expires_at = None
            task.last_error = "REAPED_ZOMBIE_LEASE_EXPIRED"
            task.updated_at = now
        else:
            task.status = TaskStatus.FAILED.value
            task.finished_at = now
            task.lease_token = None
            task.lease_expires_at = None
            task.last_error = "REAPED_ZOMBIE_MAX_ATTEMPTS_EXCEEDED"
            task.updated_at = now

            audit = AuditEvent(
                id=str(uuid4()),
                event_type="TASK_PERMANENT_FAILURE",
                entity_type="BACKGROUND_TASK",
                entity_id=task.id,
                actor_type="WORKER",
                actor_id=task.worker_id or "unknown",
                payload_json={
                    "task_type": task.task_type,
                    "attempts": task.attempts_count,
                    "max_attempts": task.max_attempts,
                    "error": "REAPED_ZOMBIE_MAX_ATTEMPTS_EXCEEDED",
                },
                created_at=now,
            )
            session.add(audit)

    # Reclaim stale active workers whose heartbeat has lapsed
    stale_cutoff = now - timedelta(seconds=stale_threshold_seconds)
    stale_workers = session.scalars(
        select(BackgroundWorkerModel).where(
            BackgroundWorkerModel.status == WorkerStatus.ACTIVE.value,
            BackgroundWorkerModel.last_heartbeat_at <= stale_cutoff,
        )
    ).all()
    for w in stale_workers:
        w.status = WorkerStatus.STOPPED.value
        w.current_task_id = None

    session.flush()
    return reaped_count


class BackgroundWorker:
    """Durable background worker engine executing local tasks."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        worker_id: str | None = None,
        lease_duration_seconds: int = 60,
        heartbeat_interval_seconds: float = 15.0,
        poll_interval_seconds: float = 1.0,
        zombie_reap_interval_seconds: float = 60.0,
    ) -> None:
        self.session_factory = session_factory
        self.worker_id = (
            worker_id or f"worker-{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:8]}"
        )
        self.lease_duration_seconds = lease_duration_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.zombie_reap_interval_seconds = zombie_reap_interval_seconds

        self._status = WorkerStatus.STOPPED
        self._handlers: dict[str, TaskHandler] = {}
        self._current_task_id: str | None = None
        self._current_lease_token: str | None = None

        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._state_lock = threading.Lock()

        self._worker_thread: threading.Thread | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._last_zombie_reap = 0.0

        self._register_default_handlers()

    @property
    def status(self) -> WorkerStatus:
        with self._state_lock:
            return self._status

    def _register_default_handlers(self) -> None:
        """Register safe built-in local offline mock handlers."""
        def default_discovery_handler(payload: dict[str, Any], session: Session) -> dict[str, Any]:
            return {"source": payload.get("source", "local_fixtures"), "dry_run": True, "status": "completed"}

        def default_maintenance_checkpoint(payload: dict[str, Any], session: Session) -> dict[str, Any]:
            return {"action": payload.get("action", "checkpoint"), "status": "reconciled"}

        def default_maintenance_runs(payload: dict[str, Any], session: Session) -> dict[str, Any]:
            return {"pruned_count": 0, "status": "runs_cleaned"}

        self._handlers["DISCOVERY_POLL"] = default_discovery_handler
        self._handlers["MAINTENANCE_CHECKPOINT"] = default_maintenance_checkpoint
        self._handlers["MAINTENANCE_RUNS"] = default_maintenance_runs

    def register_handler(self, task_type: str, handler: TaskHandler) -> None:
        """Register a callable handler for a specific task type."""
        self._handlers[task_type] = handler

    def start(self) -> None:
        """Initialize worker registration and start background execution and heartbeat threads."""
        with self._state_lock:
            if self._status != WorkerStatus.STOPPED:
                return
            self._status = WorkerStatus.ACTIVE
            self._stop_event.clear()
            self._pause_event.set()

        self._register_worker_row()

        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"worker-heartbeat-{self.worker_id}",
            daemon=True,
        )
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name=f"worker-loop-{self.worker_id}",
            daemon=True,
        )
        self._heartbeat_thread.start()
        self._worker_thread.start()
        logger.info("BackgroundWorker '%s' started.", self.worker_id)

    def pause(self) -> None:
        """Pause worker task claiming; active task runs to completion."""
        with self._state_lock:
            if self._status != WorkerStatus.ACTIVE:
                return
            self._status = WorkerStatus.PAUSED
            self._pause_event.clear()

        self._update_worker_row_status(WorkerStatus.PAUSED.value)
        logger.info("BackgroundWorker '%s' paused.", self.worker_id)

    def resume(self) -> None:
        """Resume worker task claiming from paused state."""
        with self._state_lock:
            if self._status != WorkerStatus.PAUSED:
                return
            self._status = WorkerStatus.ACTIVE
            self._pause_event.set()

        self._update_worker_row_status(WorkerStatus.ACTIVE.value)
        logger.info("BackgroundWorker '%s' resumed.", self.worker_id)

    def stop(self, drain_timeout_seconds: float = 5.0) -> None:
        """Gracefully drain active task and terminate background threads."""
        with self._state_lock:
            if self._status == WorkerStatus.STOPPED:
                return
            self._status = WorkerStatus.DRAINING

        self._update_worker_row_status(WorkerStatus.DRAINING.value)
        self._stop_event.set()
        self._pause_event.set()  # Unblock if paused

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=drain_timeout_seconds)

        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=2.0)

        with self._state_lock:
            self._status = WorkerStatus.STOPPED

        self._update_worker_row_status(WorkerStatus.STOPPED.value)
        logger.info("BackgroundWorker '%s' stopped.", self.worker_id)

    def run_once(self) -> bool:
        """Synchronously claim and execute at most one pending task.

        Returns True if a task was processed; False if no task was available.
        Ideal for deterministic test execution without background threads.
        """
        task_id: str | None = None
        task_type: str | None = None
        payload_json: dict[str, Any] = {}
        lease_token: str | None = None

        with self.session_factory() as session:
            task, lease_token = claim_next_task(
                session, self.worker_id, self.lease_duration_seconds
            )
            if task is None or lease_token is None:
                return False

            task_id = task.id
            task_type = task.task_type
            payload_json = dict(task.payload_json or {})
            self._current_task_id = task_id
            self._current_lease_token = lease_token
            session.commit()

        start_time = time.perf_counter()
        duration_ms = 0

        with self.session_factory() as session:
            try:
                handler = self._handlers.get(task_type)
                if handler is None:
                    raise TaskHandlerNotFoundError(
                        f"No handler registered for task type '{task_type}'"
                    )

                result = handler(payload_json, session)
                duration_ms = int((time.perf_counter() - start_time) * 1000)

                complete_task(
                    session,
                    task_id=task_id,
                    lease_token=lease_token,
                    worker_id=self.worker_id,
                    result_payload=result,
                    duration_ms=duration_ms,
                )
                session.commit()
            except Exception as exc:
                duration_ms = int((time.perf_counter() - start_time) * 1000)
                try:
                    fail_task(
                        session,
                        task_id=task_id,
                        lease_token=lease_token,
                        worker_id=self.worker_id,
                        error=exc,
                        duration_ms=duration_ms,
                    )
                    session.commit()
                except Exception as fail_exc:
                    session.rollback()
                    logger.warning("Error recording task failure: %s", fail_exc)
            finally:
                self._current_task_id = None
                self._current_lease_token = None

        return True

    def get_status(self) -> dict[str, Any]:
        """Return diagnostic status dictionary for system telemetry."""
        return {
            "status": self.status.value,
            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
            "active_tasks": 1 if self._current_task_id else 0,
            "worker_id": self.worker_id,
        }

    def _worker_loop(self) -> None:
        """Continuous execution loop."""
        while not self._stop_event.is_set():
            self._pause_event.wait()
            if self._stop_event.is_set():
                break

            now_mono = time.monotonic()
            if now_mono - self._last_zombie_reap >= self.zombie_reap_interval_seconds:
                self._last_zombie_reap = now_mono
                try:
                    with self.session_factory() as session:
                        reap_zombies(session)
                        session.commit()
                except Exception as exc:
                    logger.debug("Zombie reap exception: %s", exc)

            try:
                did_work = self.run_once()
                if not did_work:
                    self._stop_event.wait(timeout=self.poll_interval_seconds)
            except Exception as exc:
                logger.debug("Exception in worker loop: %s", exc)
                self._stop_event.wait(timeout=self.poll_interval_seconds)

    def _heartbeat_loop(self) -> None:
        """Periodic heartbeat pulse renewing worker record and active task lease."""
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self.heartbeat_interval_seconds)
            if self._stop_event.is_set():
                break

            try:
                with self.session_factory() as session:
                    now = _get_db_wall_clock(session)
                    w_row = session.get(BackgroundWorkerModel, self.worker_id)
                    if w_row:
                        w_row.last_heartbeat_at = now
                        w_row.status = self.status.value
                        w_row.current_task_id = self._current_task_id
                        session.flush()

                    if self._current_task_id and self._current_lease_token:
                        renew_task_lease(
                            session,
                            self._current_task_id,
                            self._current_lease_token,
                            self.lease_duration_seconds,
                        )
                    session.commit()
            except Exception as exc:
                logger.debug("Heartbeat loop exception: %s", exc)

    def _register_worker_row(self) -> None:
        """Insert or refresh worker registration in background_workers table."""
        try:
            with self.session_factory() as session:
                now = _get_db_wall_clock(session)
                w_row = session.get(BackgroundWorkerModel, self.worker_id)
                if w_row is None:
                    w_row = BackgroundWorkerModel(
                        worker_id=self.worker_id,
                        hostname=socket.gethostname(),
                        pid=os.getpid(),
                        status=WorkerStatus.ACTIVE.value,
                        started_at=now,
                        last_heartbeat_at=now,
                    )
                    session.add(w_row)
                else:
                    w_row.status = WorkerStatus.ACTIVE.value
                    w_row.last_heartbeat_at = now
                session.commit()
        except Exception as exc:
            logger.warning("Could not register worker row: %s", exc)

    def _update_worker_row_status(self, status: str) -> None:
        """Update worker state in background_workers table."""
        try:
            with self.session_factory() as session:
                now = _get_db_wall_clock(session)
                w_row = session.get(BackgroundWorkerModel, self.worker_id)
                if w_row:
                    w_row.status = status
                    w_row.last_heartbeat_at = now
                    session.commit()
        except Exception as exc:
            logger.debug("Could not update worker row status: %s", exc)
