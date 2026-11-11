"""Local timezone-aware scheduler service for Hire-Steward background processing.

Operates strictly offline/locally with zero external network access.
Uses standard library zoneinfo.ZoneInfo("Asia/Kolkata") for all scheduling evaluations.
Enqueues tasks into the durable `background_tasks` queue with deterministic idempotency keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
import logging
import threading
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.db.models import BackgroundTask
from backend.app.services.background_worker import enqueue_task

logger = logging.getLogger("hire_steward.scheduler")

DEFAULT_TIMEZONE_NAME = "Asia/Kolkata"
DEFAULT_DISCOVERY_TIMES = ("10:00", "17:00", "22:00")


@dataclass(frozen=True, slots=True)
class ScheduledJobDefinition:
    """Specification of a recurring background job rule."""

    job_id: str
    task_type: str
    schedule_times: tuple[str, ...]  # Format: "HH:MM" in local timezone
    payload: dict[str, Any]
    idempotency_prefix: str
    priority: int = 100
    max_attempts: int = 3
    backoff_base_seconds: int = 10
    enabled: bool = True


class LocalScheduler:
    """Timezone-aware background task scheduler for local execution.

    Responsibilities:
    1. Timezone Management: Evaluates schedules according to Asia/Kolkata (UTC+05:30).
    2. Deterministic Idempotency: Generates unique keys e.g. 'discovery:daily:2026-11-10:10:00'.
    3. Periodic Evaluation: Regularly checks if pending scheduled jobs are due and enqueues them.
    4. Lifecycle Controls: Thread-safe start(), pause(), resume(), and stop().
    5. Local / Offline Invariant: Restricts tasks strictly to local operations.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session] | None = None,
        timezone_name: str = DEFAULT_TIMEZONE_NAME,
        tick_interval_seconds: float = 15.0,
    ) -> None:
        self._session_factory = session_factory
        try:
            self._timezone = ZoneInfo(timezone_name)
        except Exception:
            logger.warning("Invalid timezone '%s', falling back to UTC", timezone_name)
            self._timezone = ZoneInfo("UTC")

        self._tick_interval = tick_interval_seconds
        self._jobs: dict[str, ScheduledJobDefinition] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._paused = False
        self._stopped = True

        self._register_default_jobs()

    @property
    def timezone(self) -> ZoneInfo:
        return self._timezone

    @property
    def is_active(self) -> bool:
        return not self._stopped and not self._paused

    @property
    def is_paused(self) -> bool:
        return self._paused

    def _register_default_jobs(self) -> None:
        """Register agreed default scheduled jobs."""
        # 1. Daily discovery polling (10:00, 17:00, 22:00 IST)
        self.register_job(
            ScheduledJobDefinition(
                job_id="daily_discovery",
                task_type="DISCOVERY_POLL",
                schedule_times=DEFAULT_DISCOVERY_TIMES,
                payload={"source": "local_fixtures", "dry_run": True},
                idempotency_prefix="discovery:daily",
                priority=100,
                max_attempts=3,
                backoff_base_seconds=10,
            )
        )
        # 2. Daily checkpoint maintenance (03:00 IST)
        self.register_job(
            ScheduledJobDefinition(
                job_id="checkpoint_maintenance",
                task_type="MAINTENANCE_CHECKPOINT",
                schedule_times=("03:00",),
                payload={"action": "reconcile_checkpoints_and_purge_orphans"},
                idempotency_prefix="maintenance:checkpoint",
                priority=50,
                max_attempts=3,
                backoff_base_seconds=30,
            )
        )
        # 3. Daily task run history cleanup (04:00 IST)
        self.register_job(
            ScheduledJobDefinition(
                job_id="task_run_cleanup",
                task_type="MAINTENANCE_RUNS",
                schedule_times=("04:00",),
                payload={"retention_days": 30},
                idempotency_prefix="maintenance:runs",
                priority=30,
                max_attempts=2,
                backoff_base_seconds=60,
            )
        )

    def register_job(self, job: ScheduledJobDefinition) -> None:
        """Register or update a scheduled job definition."""
        with self._lock:
            self._jobs[job.job_id] = job
            logger.debug("Registered scheduled job '%s'", job.job_id)

    def unregister_job(self, job_id: str) -> bool:
        """Remove a scheduled job definition."""
        with self._lock:
            removed = self._jobs.pop(job_id, None)
            return removed is not None

    def get_next_scheduled_run(self, reference_time: datetime | None = None) -> datetime | None:
        """Calculate the earliest upcoming scheduled run across all jobs in local timezone."""
        now_local = (
            reference_time.astimezone(self._timezone)
            if reference_time is not None
            else datetime.now(self._timezone)
        )
        candidates: list[datetime] = []

        with self._lock:
            active_jobs = [j for j in self._jobs.values() if j.enabled]

        for day_offset in (0, 1):
            target_date = (now_local + timedelta(days=day_offset)).date()
            for job in active_jobs:
                for time_str in job.schedule_times:
                    try:
                        hour, minute = map(int, time_str.split(":"))
                        slot_dt = datetime.combine(
                            target_date, time(hour, minute), tzinfo=self._timezone
                        )
                        if slot_dt > now_local:
                            candidates.append(slot_dt)
                    except ValueError:
                        continue

        return min(candidates) if candidates else None

    def tick(self, session: Session, reference_time: datetime | None = None) -> list[str]:
        """Evaluate scheduled jobs against current time and enqueue due tasks.

        Uses deterministic idempotency keys. Deduplicates against existing tasks.
        Returns list of newly enqueued task IDs.
        """
        if self._paused:
            return []

        now_local = (
            reference_time.astimezone(self._timezone)
            if reference_time is not None
            else datetime.now(self._timezone)
        )
        enqueued_ids: list[str] = []

        with self._lock:
            active_jobs = [j for j in self._jobs.values() if j.enabled]

        for job in active_jobs:
            for time_str in job.schedule_times:
                try:
                    hour, minute = map(int, time_str.split(":"))
                    slot_today = datetime.combine(
                        now_local.date(), time(hour, minute), tzinfo=self._timezone
                    )
                except ValueError:
                    continue

                # Has the slot arrived or elapsed today?
                if now_local >= slot_today:
                    date_str = slot_today.strftime("%Y-%m-%d")
                    idempotency_key = f"{job.idempotency_prefix}:{date_str}:{time_str}"

                    # Check if already enqueued in background_tasks
                    existing = session.scalar(
                        select(BackgroundTask.id).where(
                            BackgroundTask.idempotency_key == idempotency_key
                        )
                    )
                    if existing is not None:
                        continue

                    scheduled_at_utc = slot_today.astimezone(timezone.utc)
                    task, created = enqueue_task(
                        session=session,
                        task_type=job.task_type,
                        payload=dict(job.payload),
                        priority=job.priority,
                        scheduled_at=scheduled_at_utc,
                        idempotency_key=idempotency_key,
                        max_attempts=job.max_attempts,
                        backoff_base_seconds=job.backoff_base_seconds,
                    )
                    if created:
                        enqueued_ids.append(task.id)

        if enqueued_ids:
            try:
                session.commit()
                logger.info(
                    "Scheduler enqueued %d due tasks (IDs: %s)",
                    len(enqueued_ids),
                    enqueued_ids,
                )
            except Exception as exc:
                session.rollback()
                logger.warning("Failed to commit enqueued scheduled tasks: %s", exc)
                return []

        return enqueued_ids

    def _run_loop(self) -> None:
        """Background daemon thread ticker loop."""
        logger.info("LocalScheduler thread started (Timezone: %s)", self._timezone)
        while not self._stop_event.is_set():
            try:
                if not self._paused and self._session_factory is not None:
                    session = self._session_factory()
                    try:
                        self.tick(session)
                    finally:
                        session.close()
            except Exception as exc:
                logger.error("Unhandled exception in scheduler tick loop: %s", exc)

            self._stop_event.wait(timeout=self._tick_interval)
        logger.info("LocalScheduler thread terminated.")

    def start(self) -> None:
        """Start the background scheduler thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._stopped = False
            self._paused = False
            self._thread = threading.Thread(
                target=self._run_loop,
                daemon=True,
                name="HireSteward-LocalScheduler",
            )
            self._thread.start()
            logger.info("LocalScheduler started.")

    def pause(self) -> None:
        """Pause the scheduler (halts task enqueuing)."""
        with self._lock:
            self._paused = True
            logger.info("LocalScheduler paused.")

    def resume(self) -> None:
        """Resume the scheduler."""
        with self._lock:
            self._paused = False
            logger.info("LocalScheduler resumed.")

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the background scheduler thread gracefully."""
        with self._lock:
            self._stopped = True
            self._stop_event.set()
            thread = self._thread
            self._thread = None

        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
            logger.info("LocalScheduler stopped.")

    def get_status(self) -> dict[str, Any]:
        """Return operational diagnostics for API status endpoints."""
        next_run = self.get_next_scheduled_run()
        next_run_iso = next_run.isoformat() if next_run is not None else None

        if self._paused:
            status_str = "PAUSED"
        elif self._stopped:
            status_str = "STOPPED"
        else:
            status_str = "ACTIVE"

        tz_name = (
            self._timezone.key
            if hasattr(self._timezone, "key")
            else DEFAULT_TIMEZONE_NAME
        )

        with self._lock:
            schedules = [
                {
                    "job_id": job.job_id,
                    "task_type": job.task_type,
                    "schedule_times": list(job.schedule_times),
                    "enabled": job.enabled,
                }
                for job in self._jobs.values()
            ]

        return {
            "status": status_str,
            "timezone": tz_name,
            "next_scheduled_run": next_run_iso,
            "next_run": next_run_iso,
            "jobs_count": len(schedules),
            "schedules": schedules,
        }
