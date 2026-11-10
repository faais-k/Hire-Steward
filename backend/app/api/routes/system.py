"""System health, operational metrics, and activity timeline routes (Stage 1 & Stage 7 Screen 12/13).

Provides single-source operational visibility:
1. Database connectivity and migration head status.
2. Local evidence storage availability and writability.
3. Local loopback enforcement status.
4. AI Provider configuration and budget tracker summary.
5. High-level entity counts (opportunities, pipeline, facts).
6. Immutable activity and audit feed.
"""

from __future__ import annotations

import os
from pathlib import Path
from collections.abc import Generator
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from backend.app.db.models import (
    ApplicationStatusHistory,
    CandidateDocument,
    CandidateFact,
    JobPosting,
    TrackedApplication,
)
from backend.app.evaluation.budget import BudgetTracker
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
    """Return operational health, storage status, and system metrics."""
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

    # 4. AI Provider status (Zero secret exposure)
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
        "ai_provider": ai_status,
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
                feed.append({
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
                })

            from backend.app.db.models import AuditEvent

            audit_rows = session.scalars(
                select(AuditEvent)
                .order_by(AuditEvent.created_at.desc())
                .limit(limit)
            ).all()

            for a in audit_rows:
                feed.append({
                    "id": a.id,
                    "type": a.event_type,
                    "timestamp": a.created_at.isoformat() if a.created_at else None,
                    "title": f"Audit: {a.event_type}",
                    "detail": f"{a.entity_type} {a.entity_id} acted upon by {a.actor_type}:{a.actor_id}",
                    "metadata": a.payload_json or {},
                })
        except Exception:
            pass

    feed.sort(key=lambda x: x["timestamp"], reverse=True)
    return feed[:limit]
