"""Unit tests for System Task Queue and Lifecycle APIs.

Covers:
1. GET /api/v1/system/status extended telemetry (worker, scheduler, queue backlog).
2. POST /api/v1/system/worker/pause and POST /api/v1/system/worker/resume.
3. GET /api/v1/system/tasks listing with pagination and filtering.
4. GET /api/v1/system/tasks/{task_id} detailed inspection with run history.
5. POST /api/v1/system/tasks/{task_id}/retry lifecycle transition.
6. POST /api/v1/system/tasks/{task_id}/cancel lifecycle transition.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil
import tempfile
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.models import BackgroundTask, BackgroundTaskRun
from backend.app.evidence_config import EvidenceSettings
from backend.app.main import create_app
from backend.app.services.background_worker import enqueue_task


def local_headers() -> dict[str, str]:
    return {"host": "localhost", "origin": "http://localhost"}


@pytest.fixture
def client_and_factory():
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
    storage_root = Path(tempfile.gettempdir()) / "system-api-tests" / uuid4().hex
    storage_root.mkdir(parents=True, exist_ok=True)
    settings = EvidenceSettings(storage_root=storage_root)

    app = create_app(
        session_factory=factory,
        evidence_settings=settings,
        enable_background_services=False,  # Keep threads stopped for synchronous API tests
    )
    with TestClient(app, base_url="http://localhost") as client:
        yield client, factory

    engine.dispose()
    shutil.rmtree(storage_root, ignore_errors=True)


def test_system_status_telemetry(client_and_factory):
    client, factory = client_and_factory
    resp = client.get("/api/v1/system/status", headers=local_headers())
    assert resp.status_code == 200
    data = resp.json()

    # Preserves baseline keys
    assert data["status"] == "healthy"
    assert data["loopback_enforced"] is True
    assert data["database"]["connected"] is True
    assert data["storage"]["writable"] is True
    assert "metrics" in data
    assert "ai_provider" in data

    # Extended telemetry blocks
    assert "worker" in data
    assert "scheduler" in data
    assert "queue" in data

    assert data["queue"]["pending_tasks"] == 0
    assert data["queue"]["running_tasks"] == 0
    assert data["queue"]["completed_tasks"] == 0
    assert data["queue"]["failed_tasks"] == 0

    # Add a pending task and verify queue counts reflect it
    with factory() as session:
        enqueue_task(session, task_type="DOC_PARSE", payload={"file": "resume.pdf"})
        session.commit()

    resp2 = client.get("/api/v1/system/status", headers=local_headers())
    data2 = resp2.json()
    assert data2["queue"]["pending_tasks"] == 1
    assert data2["queue"]["pending"] == 1


def test_worker_pause_and_resume_endpoints(client_and_factory):
    client, _ = client_and_factory

    # 1. Pause
    pause_resp = client.post("/api/v1/system/worker/pause", headers=local_headers())
    assert pause_resp.status_code == 200
    p_data = pause_resp.json()
    assert p_data["status"] == "PAUSED"
    assert "message" in p_data

    # 2. Resume
    resume_resp = client.post("/api/v1/system/worker/resume", headers=local_headers())
    assert resume_resp.status_code == 200
    r_data = resume_resp.json()
    assert r_data["status"] == "ACTIVE"
    assert "message" in r_data


def test_list_tasks_and_pagination(client_and_factory):
    client, factory = client_and_factory

    with factory() as session:
        for i in range(5):
            enqueue_task(session, task_type="DOC_PARSE", payload={"idx": i})
        for j in range(3):
            enqueue_task(session, task_type="MATCH_EVAL", payload={"idx": j})
        session.commit()

    # Total list
    all_resp = client.get("/api/v1/system/tasks", headers=local_headers())
    assert all_resp.status_code == 200
    all_data = all_resp.json()
    assert all_data["total"] == 8
    assert len(all_data["tasks"]) == 8

    # Filter by task_type
    filtered_resp = client.get(
        "/api/v1/system/tasks?task_type=DOC_PARSE", headers=local_headers()
    )
    assert filtered_resp.status_code == 200
    f_data = filtered_resp.json()
    assert f_data["total"] == 5
    assert all(t["task_type"] == "DOC_PARSE" for t in f_data["tasks"])

    # Pagination: limit=2, offset=0
    page_resp = client.get("/api/v1/system/tasks?limit=2&offset=0", headers=local_headers())
    assert page_resp.status_code == 200
    p_data = page_resp.json()
    assert p_data["total"] == 8
    assert len(p_data["tasks"]) == 2


def test_get_task_detail_with_runs(client_and_factory):
    client, factory = client_and_factory

    with factory() as session:
        task, _ = enqueue_task(session, task_type="DOC_PARSE", payload={"doc": "test.pdf"})
        session.flush()

        now = datetime.now(timezone.utc)
        run = BackgroundTaskRun(
            id=str(uuid4()),
            task_id=task.id,
            worker_id="worker-test-1",
            attempt_number=1,
            started_at=now,
            finished_at=now,
            duration_ms=120,
            status="SUCCEEDED",
            error_message=None,
        )
        session.add(run)
        session.commit()
        task_id = task.id

    # Detail query
    resp = client.get(f"/api/v1/system/tasks/{task_id}", headers=local_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == task_id
    assert data["task_type"] == "DOC_PARSE"
    assert len(data["runs"]) == 1
    assert data["runs"][0]["status"] == "SUCCEEDED"
    assert data["runs"][0]["duration_ms"] == 120

    # 404 for non-existent task
    not_found = client.get(f"/api/v1/system/tasks/{uuid4().hex}", headers=local_headers())
    assert not_found.status_code == 404


def test_task_retry_endpoint(client_and_factory):
    client, factory = client_and_factory

    with factory() as session:
        task, _ = enqueue_task(session, task_type="DOC_PARSE")
        task.status = "FAILED"
        task.last_error = "Network timeout"
        task.attempts_count = 3
        session.commit()
        task_id = task.id

    # Retry failed task -> transitions back to PENDING
    retry_resp = client.post(f"/api/v1/system/tasks/{task_id}/retry", headers=local_headers())
    assert retry_resp.status_code == 200
    r_data = retry_resp.json()
    assert r_data["status"] == "PENDING"
    assert r_data["task_id"] == task_id

    with factory() as session:
        t = session.get(BackgroundTask, task_id)
        assert t.status == "PENDING"
        assert t.attempts_count == 0
        assert t.last_error is None

    # Calling retry on RUNNING task raises 409 Conflict
    with factory() as session:
        t_running, _ = enqueue_task(session, task_type="MATCH_EVAL")
        t_running.status = "RUNNING"
        session.commit()
        running_id = t_running.id

    conflict_resp = client.post(f"/api/v1/system/tasks/{running_id}/retry", headers=local_headers())
    assert conflict_resp.status_code == 409


def test_task_cancel_endpoint(client_and_factory):
    client, factory = client_and_factory

    with factory() as session:
        task, _ = enqueue_task(session, task_type="DOC_PARSE")
        session.commit()
        task_id = task.id

    # Cancel pending task -> transitions to CANCELLED
    cancel_resp = client.post(f"/api/v1/system/tasks/{task_id}/cancel", headers=local_headers())
    assert cancel_resp.status_code == 200
    c_data = cancel_resp.json()
    assert c_data["status"] == "CANCELLED"

    with factory() as session:
        t = session.get(BackgroundTask, task_id)
        assert t.status == "CANCELLED"

    # Cancelling a RUNNING task raises 409 Conflict
    with factory() as session:
        t_running, _ = enqueue_task(session, task_type="MATCH_EVAL")
        t_running.status = "RUNNING"
        session.commit()
        running_id = t_running.id

    conflict_resp = client.post(f"/api/v1/system/tasks/{running_id}/cancel", headers=local_headers())
    assert conflict_resp.status_code == 409
