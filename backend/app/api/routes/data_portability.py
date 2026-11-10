"""Data Portability API routes for safe export, preview, and restore (Stage 8 & Stage 7 Screen 11)."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_session, require_local_same_origin
from backend.app.domain.data_portability import DataPortabilityError
from backend.app.services import data_portability as service

router = APIRouter(prefix="/api/v1/data", tags=["Data Portability"])


class ImportCommitRequest(BaseModel):
    bundle: dict[str, Any] = Field(..., description="Full export bundle including manifest")
    preview_token: str | None = Field(default=None, description="Deterministic token from preview verification")
    overwrite_existing: bool = Field(default=False, description="Whether to overwrite overlapping IDs (defaults to False)")


@router.get("/export")
@router.post("/export")
def export_data(
    request: Request,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, Any]:
    """Generate and download safe JSON backup bundle stripped of secrets."""
    storage_root = None
    settings = getattr(request.app.state, "evidence_settings", None)
    if settings and hasattr(settings, "storage_root"):
        storage_root = settings.storage_root
    bundle = service.export_dataset(session, storage_root=storage_root)
    from backend.app.services.audit import record_audit_event

    record_audit_event(
        session,
        event_type="DATA_PORTABILITY_EXPORT",
        entity_type="SYSTEM",
        entity_id="export",
        payload_json={"checksum_sha256": bundle.get("manifest", {}).get("checksum_sha256")},
    )
    session.commit()
    return bundle


@router.post("/import/preview")
def preview_import(
    bundle: dict[str, Any],
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, Any]:
    """Dry-run validation of import bundle without applying changes."""
    try:
        return service.preview_import_dataset(session, bundle)
    except DataPortabilityError as exc:
        raise HTTPException(status_code=422, detail=f"VALIDATION_ERROR: {exc.message}") from exc


@router.post("/import/commit")
def commit_import(
    payload: ImportCommitRequest,
    request: Request,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, Any]:
    """Atomically commit validated import bundle."""
    storage_root = None
    settings = getattr(request.app.state, "evidence_settings", None)
    if settings and hasattr(settings, "storage_root"):
        storage_root = settings.storage_root
    try:
        res = service.commit_import_dataset(
            session,
            payload.bundle,
            preview_token=payload.preview_token,
            overwrite_existing=payload.overwrite_existing,
            storage_root=storage_root,
        )
        from backend.app.services.audit import record_audit_event

        record_audit_event(
            session,
            event_type="DATA_PORTABILITY_RESTORE",
            entity_type="SYSTEM",
            entity_id="restore",
            payload_json={"restored_counts": res.get("restored_counts", {})},
        )
        session.commit()
        return res
    except DataPortabilityError as exc:
        raise HTTPException(status_code=422, detail=f"IMPORT_ERROR: {exc.message}") from exc
