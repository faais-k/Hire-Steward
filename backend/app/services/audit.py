"""Unified system, security, and policy audit service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid
from sqlalchemy.orm import Session

from backend.app.db.models import AuditEvent


def record_audit_event(
    session: Session,
    event_type: str,
    entity_type: str,
    entity_id: str,
    payload_json: dict[str, Any] | None = None,
    actor_type: str = "USER",
    actor_id: str = "default",
) -> AuditEvent | None:
    """Record an immutable audit event in the unified audit log if the table exists."""
    try:
        with session.no_autoflush:
            from backend.app.services.data_portability import _get_existing_tables

            tables = _get_existing_tables(session)
            if "audit_events" not in tables:
                return None
    except Exception:
        return None

    event = AuditEvent(
        id=uuid.uuid4().hex,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=str(entity_id),
        actor_type=actor_type,
        actor_id=actor_id,
        payload_json=payload_json or {},
        created_at=datetime.now(timezone.utc),
    )
    session.add(event)
    return event
