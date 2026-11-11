"""Unit tests for LocalScheduler service.

Covers:
1. Asia/Kolkata timezone awareness and independence from host OS timezone.
2. Deterministic idempotency key formatting.
3. Earliest upcoming slot computation across rolling 48-hour window.
4. Periodic tick evaluation and task deduplication against durable queue.
5. Thread-safe lifecycle controls (start, pause, resume, stop).
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.models import BackgroundTask
from backend.app.services.scheduler import LocalScheduler, ScheduledJobDefinition


@pytest.fixture
def session_factory():
    """Isolated SQLite database migrated to Alembic head."""
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


def test_scheduler_timezone_is_kolkata():
    scheduler = LocalScheduler()
    assert scheduler.timezone == ZoneInfo("Asia/Kolkata")
    st = scheduler.get_status()
    assert st["timezone"] == "Asia/Kolkata"


def test_scheduler_slot_computation_across_rolling_window():
    scheduler = LocalScheduler(timezone_name="Asia/Kolkata")
    kolkata_tz = ZoneInfo("Asia/Kolkata")

    # 1. At 08:30 IST, earliest discovery run is 10:00 IST today
    t1 = datetime(2026, 11, 10, 8, 30, tzinfo=kolkata_tz)
    next1 = scheduler.get_next_scheduled_run(reference_time=t1)
    assert next1 == datetime(2026, 11, 10, 10, 0, tzinfo=kolkata_tz)

    # 2. At 12:30 IST, next run is 17:00 IST today
    t2 = datetime(2026, 11, 10, 12, 30, tzinfo=kolkata_tz)
    next2 = scheduler.get_next_scheduled_run(reference_time=t2)
    assert next2 == datetime(2026, 11, 10, 17, 0, tzinfo=kolkata_tz)

    # 3. At 18:30 IST, next run is 22:00 IST today
    t3 = datetime(2026, 11, 10, 18, 30, tzinfo=kolkata_tz)
    next3 = scheduler.get_next_scheduled_run(reference_time=t3)
    assert next3 == datetime(2026, 11, 10, 22, 0, tzinfo=kolkata_tz)

    # 4. At 23:00 IST, today's runs are done. Next run is 03:00 IST tomorrow (checkpoint maintenance)
    t4 = datetime(2026, 11, 10, 23, 0, tzinfo=kolkata_tz)
    next4 = scheduler.get_next_scheduled_run(reference_time=t4)
    assert next4 == datetime(2026, 11, 11, 3, 0, tzinfo=kolkata_tz)


def test_scheduler_deterministic_idempotency_keys_and_tick(session_factory):
    scheduler = LocalScheduler(session_factory=session_factory, timezone_name="Asia/Kolkata")
    kolkata_tz = ZoneInfo("Asia/Kolkata")

    # Time: 2026-11-10 10:15 IST (past 03:00, 04:00, and 10:00 slots)
    ref_time = datetime(2026, 11, 10, 10, 15, tzinfo=kolkata_tz)

    with session_factory() as session:
        enqueued_ids = scheduler.tick(session, reference_time=ref_time)
        assert len(enqueued_ids) == 3  # 03:00 checkpoint, 04:00 runs cleanup, 10:00 daily discovery

        tasks = session.scalars(select(BackgroundTask).order_by(BackgroundTask.scheduled_at.asc())).all()
        keys = {t.idempotency_key for t in tasks}

        assert "maintenance:checkpoint:2026-11-10:03:00" in keys
        assert "maintenance:runs:2026-11-10:04:00" in keys
        assert "discovery:daily:2026-11-10:10:00" in keys

        # Verify offline mock invariant: discovery poll payload is local fixture
        disc_task = next(t for t in tasks if t.task_type == "DISCOVERY_POLL")
        assert disc_task.payload_json == {"source": "local_fixtures", "dry_run": True}

        # Second tick at 10:30 IST must deduplicate and return 0 new tasks
        ref_time_later = datetime(2026, 11, 10, 10, 30, tzinfo=kolkata_tz)
        second_enqueued = scheduler.tick(session, reference_time=ref_time_later)
        assert len(second_enqueued) == 0


def test_scheduler_pause_resume_and_lifecycle(session_factory):
    scheduler = LocalScheduler(session_factory=session_factory, timezone_name="Asia/Kolkata")
    kolkata_tz = ZoneInfo("Asia/Kolkata")
    ref_time = datetime(2026, 11, 10, 10, 15, tzinfo=kolkata_tz)

    scheduler.pause()
    assert scheduler.is_paused is True
    st_paused = scheduler.get_status()
    assert st_paused["status"] == "PAUSED"

    # Paused scheduler enqueues nothing on tick
    with session_factory() as session:
        enqueued = scheduler.tick(session, reference_time=ref_time)
        assert len(enqueued) == 0

    scheduler.resume()
    assert scheduler.is_paused is False
    st_resumed = scheduler.get_status()
    assert st_resumed["status"] == "STOPPED"  # Stopped because thread not started

    # Thread lifecycle
    scheduler.start()
    st_active = scheduler.get_status()
    assert st_active["status"] == "ACTIVE"

    scheduler.stop(timeout=2.0)
    st_stopped = scheduler.get_status()
    assert st_stopped["status"] == "STOPPED"
