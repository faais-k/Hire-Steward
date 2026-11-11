"""System health, operational metrics, task queue management, and activity timeline routes."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from backend.app.db.models import (
    ApplicationStatusHistory,
    AuditEvent,
    BackgroundTask,
    BackgroundTaskRun,
    BackgroundWorker,
    CandidateDocument,
    CandidateFact,
    JobPosting,
    TrackedApplication,
)
from backend.app.evaluation.credentials import load_provider_credentials

router = APIRouter(prefix="/api/v1/system", tags=["System"])


def get_optional_session(request: Request) -> Generator[Session | None, None, None]:
    """Provide database session if configured, or None if in offline mock mode."""
    factory = getattr(request.app.state, "session_factory", None)
    if not factory:
        yield None
        return
    session = factory()
    try:
        yield session
    finally:
        session.close()


@router.get("/status")
def get_system_status(
    request: Request,
    session: Session | None = Depends(get_optional_session),
) -> dict[str, Any]:
    """Return operational health, storage status, worker, scheduler, and system metrics."""
    # 1. Database check
    db_ok = False
    db_error = None
    if session is not None:
        try:
            session.execute(text("SELECT 1"))
            db_ok = True
        except Exception as exc:
            db_ok = False
            db_error = str(exc)
    else:
        db_error = "DATABASE_NOT_CONFIGURED"

    # 2. Storage check
    storage = getattr(request.app.state, "evidence_storage", None)
    storage_path = None
    storage_writable = False
    if storage:
        if hasattr(storage, "settings") and hasattr(storage.settings, "storage_root"):
            storage_path = str(storage.settings.storage_root)
        elif hasattr(storage, "base_dir"):
            storage_path = str(storage.base_dir)
        if storage_path:
            p = Path(storage_path)
            p.mkdir(parents=True, exist_ok=True)
            storage_writable = os.access(str(p), os.W_OK)

    # 3. Counts
    total_jobs = 0
    total_apps = 0
    total_facts = 0
    total_docs = 0
    if db_ok and session is not None:
        try:
            total_jobs = session.scalar(select(func.count(JobPosting.id))) or 0
            total_apps = session.scalar(select(func.count(TrackedApplication.id))) or 0
            total_facts = session.scalar(select(func.count(CandidateFact.id))) or 0
            total_docs = session.scalar(select(func.count(CandidateDocument.id))) or 0
        except Exception:
            pass

    # 4. Background Worker status
    worker_obj = getattr(request.app.state, "background_worker", None)
    if worker_obj is not None:
        worker_info = worker_obj.get_status()
    elif db_ok and session is not None:
        try:
            active_worker = session.scalar(
                select(BackgroundWorker)
                .order_by(BackgroundWorker.last_heartbeat_at.desc())
                .limit(1)
            )
            active_tasks = (
                session.scalar(
                    select(func.count(BackgroundTask.id)).where(
                        BackgroundTask.status == "RUNNING"
                    )
                )
                or 0
            )
            if active_worker:
                now_utc = datetime.now(timezone.utc)
                is_stale = False
                if active_worker.last_heartbeat_at:
                    hb = active_worker.last_heartbeat_at
                    if hb.tzinfo is None:
                        hb = hb.replace(tzinfo=timezone.utc)
                    if (now_utc - hb).total_seconds() > 60:
                        is_stale = True

                status_str = active_worker.status
                if is_stale and status_str == "ACTIVE":
                    status_str = "STOPPED"

                worker_info = {
                    "status": status_str,
                    "last_heartbeat": (
                        active_worker.last_heartbeat_at.isoformat()
                        if active_worker.last_heartbeat_at
                        else None
                    ),
                    "active_tasks": active_tasks,
                    "worker_id": active_worker.worker_id,
                }
            else:
                worker_info = {
                    "status": "UNAVAILABLE",
                    "last_heartbeat": None,
                    "active_tasks": 0,
                    "worker_id": None,
                }
        except Exception:
            worker_info = {
                "status": "UNAVAILABLE",
                "last_heartbeat": None,
                "active_tasks": 0,
                "worker_id": None,
            }
    else:
        worker_info = {
            "status": "UNAVAILABLE",
            "last_heartbeat": None,
            "active_tasks": 0,
            "worker_id": None,
        }

    # 5. Local Scheduler status
    scheduler_obj = getattr(request.app.state, "local_scheduler", None)
    if scheduler_obj is not None:
        scheduler_info = scheduler_obj.get_status()
    else:
        scheduler_info = {
            "status": "UNAVAILABLE",
            "timezone": "Asia/Kolkata",
            "next_scheduled_run": None,
            "next_run": None,
        }

    # 6. Task Queue Backlog
    queue_info = {
        "pending_tasks": 0,
        "running_tasks": 0,
        "completed_tasks": 0,
        "failed_tasks": 0,
        "pending": 0,
        "failed": 0,
    }
    if db_ok and session is not None:
        try:
            rows = session.execute(
                select(BackgroundTask.status, func.count(BackgroundTask.id)).group_by(
                    BackgroundTask.status
                )
            ).all()
            counts = {status: count for status, count in rows}
            queue_info = {
                "pending_tasks": counts.get("PENDING", 0),
                "running_tasks": counts.get("RUNNING", 0),
                "completed_tasks": counts.get("COMPLETED", 0),
                "failed_tasks": counts.get("FAILED", 0),
                "pending": counts.get("PENDING", 0),
                "failed": counts.get("FAILED", 0),
            }
        except Exception:
            pass

    # 7. AI Provider status (Zero secret exposure)
    creds = load_provider_credentials()
    ai_status = {
        "anthropic_configured": creds.has_anthropic,
        "openai_configured": creds.has_openai,
        "paid_ai_enabled": False,  # Strict default: disabled
        "budget_cap_usd": 5.0,
        "committed_spend_usd": 0.0,
    }

    return {
        "status": "healthy" if db_ok and storage_writable else "degraded",
        "loopback_enforced": True,
        "database": {
            "connected": db_ok,
            "error": db_error,
        },
        "storage": {
            "path": storage_path,
            "writable": storage_writable,
        },
        "metrics": {
            "total_opportunities": total_jobs,
            "active_applications": total_apps,
            "candidate_facts": total_facts,
            "documents": total_docs,
        },
        "worker": worker_info,
        "scheduler": scheduler_info,
        "queue": queue_info,
        "ai_provider": ai_status,
    }


# =========================================================================
# Worker Lifecycle Management Routes
# =========================================================================


@router.post("/worker/pause")
def pause_worker(
    request: Request,
    session: Session | None = Depends(get_optional_session),
) -> dict[str, Any]:
    """Pause background worker task consumption."""
    worker = getattr(request.app.state, "background_worker", None)
    if worker is not None:
        worker.pause()
        st = worker.get_status()
        return {
            "status": "PAUSED",
            "worker_id": st.get("worker_id"),
            "message": "Background worker paused successfully.",
        }
    if session is not None:
        try:
            active_worker = session.scalar(
                select(BackgroundWorker)
                .order_by(BackgroundWorker.last_heartbeat_at.desc())
                .limit(1)
            )
            if active_worker:
                active_worker.status = "PAUSED"
                session.commit()
                return {
                    "status": "PAUSED",
                    "worker_id": active_worker.worker_id,
                    "message": "Background worker status marked PAUSED in database.",
                }
        except Exception:
            pass
    return {
        "status": "PAUSED",
        "worker_id": None,
        "message": "Worker paused (in-process worker not registered).",
    }


@router.post("/worker/resume")
def resume_worker(
    request: Request,
    session: Session | None = Depends(get_optional_session),
) -> dict[str, Any]:
    """Resume background worker task consumption."""
    worker = getattr(request.app.state, "background_worker", None)
    if worker is not None:
        worker.resume()
        st = worker.get_status()
        return {
            "status": "ACTIVE",
            "worker_id": st.get("worker_id"),
            "message": "Background worker resumed successfully.",
        }
    if session is not None:
        try:
            active_worker = session.scalar(
                select(BackgroundWorker)
                .order_by(BackgroundWorker.last_heartbeat_at.desc())
                .limit(1)
            )
            if active_worker:
                active_worker.status = "ACTIVE"
                session.commit()
                return {
                    "status": "ACTIVE",
                    "worker_id": active_worker.worker_id,
                    "message": "Background worker status marked ACTIVE in database.",
                }
        except Exception:
            pass
    return {
        "status": "ACTIVE",
        "worker_id": None,
        "message": "Worker resumed (in-process worker not registered).",
    }


# =========================================================================
# Task Queue Management Routes
# =========================================================================


@router.get("/tasks")
def list_tasks(
    status: str | None = Query(None, description="Filter by task status"),
    task_type: str | None = Query(None, description="Filter by task type"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session | None = Depends(get_optional_session),
) -> dict[str, Any]:
    """List background tasks with filtering and pagination."""
    if session is None:
        return {"total": 0, "limit": limit, "offset": offset, "tasks": []}

    stmt = select(BackgroundTask)
    count_stmt = select(func.count(BackgroundTask.id))

    if status:
        stmt = stmt.where(BackgroundTask.status == status.upper())
        count_stmt = count_stmt.where(BackgroundTask.status == status.upper())
    if task_type:
        stmt = stmt.where(BackgroundTask.task_type == task_type)
        count_stmt = count_stmt.where(BackgroundTask.task_type == task_type)

    total = session.scalar(count_stmt) or 0
    stmt = stmt.order_by(BackgroundTask.created_at.desc()).limit(limit).offset(offset)
    tasks = session.scalars(stmt).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "tasks": [
            {
                "id": t.id,
                "task_type": t.task_type,
                "payload_json": t.payload_json,
                "priority": t.priority,
                "status": t.status,
                "idempotency_key": t.idempotency_key,
                "scheduled_at": t.scheduled_at.isoformat() if t.scheduled_at else None,
                "started_at": t.started_at.isoformat() if t.started_at else None,
                "finished_at": t.finished_at.isoformat() if t.finished_at else None,
                "attempts_count": t.attempts_count,
                "max_attempts": t.max_attempts,
                "backoff_base_seconds": t.backoff_base_seconds,
                "last_error": t.last_error,
                "worker_id": t.worker_id,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            }
            for t in tasks
        ],
    }


@router.get("/tasks/{task_id}")
def get_task_detail(
    task_id: str,
    session: Session | None = Depends(get_optional_session),
) -> dict[str, Any]:
    """Retrieve detailed task record including all execution attempt runs."""
    if session is None:
        raise HTTPException(status_code=503, detail="DATABASE_NOT_CONFIGURED")

    task = session.get(BackgroundTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="TASK_NOT_FOUND")

    runs = session.scalars(
        select(BackgroundTaskRun)
        .where(BackgroundTaskRun.task_id == task_id)
        .order_by(BackgroundTaskRun.attempt_number.asc())
    ).all()

    return {
        "id": task.id,
        "task_type": task.task_type,
        "payload_json": task.payload_json,
        "priority": task.priority,
        "status": task.status,
        "idempotency_key": task.idempotency_key,
        "scheduled_at": task.scheduled_at.isoformat() if task.scheduled_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "attempts_count": task.attempts_count,
        "max_attempts": task.max_attempts,
        "backoff_base_seconds": task.backoff_base_seconds,
        "last_error": task.last_error,
        "worker_id": task.worker_id,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "runs": [
            {
                "id": r.id,
                "attempt_number": r.attempt_number,
                "worker_id": r.worker_id,
                "status": r.status,
                "duration_ms": r.duration_ms,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "error_message": r.error_message,
            }
            for r in runs
        ],
    }


@router.post("/tasks/{task_id}/retry")
def retry_task(
    task_id: str,
    session: Session | None = Depends(get_optional_session),
) -> dict[str, Any]:
    """Requeue a FAILED or CANCELLED background task for immediate retry."""
    if session is None:
        raise HTTPException(status_code=503, detail="DATABASE_NOT_CONFIGURED")

    task = session.get(BackgroundTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="TASK_NOT_FOUND")

    if task.status == "RUNNING":
        raise HTTPException(status_code=409, detail="TASK_ALREADY_RUNNING")

    if task.status == "PENDING":
        return {
            "status": "PENDING",
            "task_id": task.id,
            "message": "Task is already pending execution.",
        }

    now_utc = datetime.now(timezone.utc)
    task.status = "PENDING"
    task.scheduled_at = now_utc
    task.started_at = None
    task.finished_at = None
    task.lease_token = None
    task.lease_expires_at = None
    task.worker_id = None
    task.attempts_count = 0
    task.last_error = None
    task.updated_at = now_utc

    session.commit()

    return {
        "status": "PENDING",
        "task_id": task.id,
        "message": "Task successfully requeued for execution.",
    }


@router.post("/tasks/{task_id}/cancel")
def cancel_task(
    task_id: str,
    session: Session | None = Depends(get_optional_session),
) -> dict[str, Any]:
    """Cancel a PENDING background task."""
    if session is None:
        raise HTTPException(status_code=503, detail="DATABASE_NOT_CONFIGURED")

    task = session.get(BackgroundTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="TASK_NOT_FOUND")

    if task.status == "RUNNING":
        raise HTTPException(status_code=409, detail="CANNOT_CANCEL_RUNNING_TASK")

    if task.status in ("COMPLETED", "FAILED", "CANCELLED"):
        return {
            "status": task.status,
            "task_id": task.id,
            "message": f"Task already in terminal state '{task.status}'.",
        }

    now_utc = datetime.now(timezone.utc)
    task.status = "CANCELLED"
    task.finished_at = now_utc
    task.lease_token = None
    task.lease_expires_at = None
    task.updated_at = now_utc

    session.commit()

    return {
        "status": "CANCELLED",
        "task_id": task.id,
        "message": "Task successfully cancelled.",
    }


@router.get("/activity")
def get_activity_feed(
    limit: int = 20,
    session: Session | None = Depends(get_optional_session),
) -> list[dict[str, Any]]:
    """Return recent immutable activity timeline from application tracking and documents."""
    feed: list[dict[str, Any]] = []

    if session is not None:
        try:
            history_rows = session.scalars(
                select(ApplicationStatusHistory)
                .order_by(ApplicationStatusHistory.created_at.desc())
                .limit(limit)
            ).all()

            for h in history_rows:
                feed.append(
                    {
                        "id": h.id,
                        "type": "APPLICATION_STATUS_CHANGE",
                        "timestamp": h.created_at.isoformat() if h.created_at else None,
                        "title": f"Application status updated to {h.to_status}",
                        "detail": f"Application {h.application_id} transitioned from {h.from_status} to {h.to_status}. Notes: {h.transition_reason or 'None'}",
                        "metadata": {
                            "application_id": h.application_id,
                            "from_status": h.from_status,
                            "to_status": h.to_status,
                        },
                    }
                )

            audit_rows = session.scalars(
                select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)
            ).all()

            for a in audit_rows:
                feed.append(
                    {
                        "id": a.id,
                        "type": a.event_type,
                        "timestamp": a.created_at.isoformat() if a.created_at else None,
                        "title": f"Audit: {a.event_type}",
                        "detail": f"{a.entity_type} {a.entity_id} acted upon by {a.actor_type}:{a.actor_id}",
                        "metadata": a.payload_json or {},
                    }
                )
        except Exception:
            pass

    feed.sort(key=lambda x: x["timestamp"] or "", reverse=True)
    return feed[:limit]
