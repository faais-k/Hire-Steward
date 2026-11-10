"""Job Source Registry API routes (Stage 4 & Stage 7 Screen 9).

Manages read-only job discovery sources, terms review status, rate limits, and offline safety.
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_session, require_local_same_origin
from backend.app.db.models import JobSource

router = APIRouter(prefix="/api/v1/sources", tags=["Source Registry"])

STATIC_SOURCE_CATALOG = {
    "lever": {
        "display_name": "Lever Postings API",
        "default_status": "NEEDS_REVIEW",
        "rate_limit": 10,
        "poll_interval": 43200,
        "notes": "Public read-only posting endpoint for Lever-hosted employers.",
    },
    "greenhouse": {
        "display_name": "Greenhouse Job Board API",
        "default_status": "NEEDS_REVIEW",
        "rate_limit": 10,
        "poll_interval": 43200,
        "notes": "Public read-only board API for Greenhouse-hosted employers.",
    },
    "ashby": {
        "display_name": "Ashby Job Board API",
        "default_status": "NEEDS_REVIEW",
        "rate_limit": 10,
        "poll_interval": 43200,
        "notes": "Public read-only board API for Ashby-hosted employers.",
    },
    "manual": {
        "display_name": "Direct Candidate Intake",
        "default_status": "MANUAL_ONLY",
        "rate_limit": 60,
        "poll_interval": 60,
        "notes": "Manual posting ingestion via web UI or API payload.",
    },
    "fixtures": {
        "display_name": "Offline Benchmark Fixtures",
        "default_status": "VERIFIED_READ_ONLY",
        "rate_limit": 120,
        "poll_interval": 60,
        "notes": "Synthetic and offline calibration test job postings.",
    },
}


class SourcePatchRequest(BaseModel):
    is_enabled: bool | None = None
    capability_status: str | None = None
    rate_limit_requests_per_minute: int | None = None


@router.get("")
def list_sources(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    """List all available job sources with real database status and local safety flags."""
    db_sources = {s.source_name: s for s in session.scalars(select(JobSource)).all()}

    results = []
    for s_name, meta in STATIC_SOURCE_CATALOG.items():
        db_s = db_sources.get(s_name)
        if db_s is not None:
            results.append({
                "source_name": db_s.source_name,
                "display_name": db_s.display_name,
                "capability_status": db_s.capability_status,
                "is_enabled": db_s.is_enabled,
                "is_read_only": True,
                "rate_limit_requests_per_minute": db_s.rate_limit_requests_per_minute,
                "min_poll_interval_seconds": db_s.min_poll_interval_seconds,
                "terms_reviewed_at": db_s.terms_reviewed_at.isoformat() if db_s.terms_reviewed_at else None,
                "terms_review_reference": db_s.terms_review_reference,
                "live_fetching_enabled": False,  # Strict offline local-first default
                "notes": meta["notes"],
            })
        else:
            results.append({
                "source_name": s_name,
                "display_name": meta["display_name"],
                "capability_status": meta["default_status"],
                "is_enabled": s_name in ("manual", "fixtures"),
                "is_read_only": True,
                "rate_limit_requests_per_minute": meta["rate_limit"],
                "min_poll_interval_seconds": meta["poll_interval"],
                "terms_reviewed_at": None,
                "terms_review_reference": None,
                "live_fetching_enabled": False,
                "notes": meta["notes"],
            })

    return results


@router.patch("/{source_name}")
def update_source(
    source_name: str,
    payload: SourcePatchRequest,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, Any]:
    """Update source capability status and rate limit in database."""
    source = session.get(JobSource, source_name)
    if source is None:
        if source_name not in STATIC_SOURCE_CATALOG:
            raise HTTPException(status_code=404, detail="SOURCE_NOT_FOUND")
        # Initialize record in DB
        meta = STATIC_SOURCE_CATALOG[source_name]
        source = JobSource(
            source_name=source_name,
            display_name=meta["display_name"],
            capability_status=meta["default_status"],
            is_enabled=False,
            rate_limit_requests_per_minute=meta["rate_limit"],
            min_poll_interval_seconds=meta["poll_interval"],
        )
        session.add(source)

    if payload.capability_status is not None:
        source.capability_status = payload.capability_status
    if payload.rate_limit_requests_per_minute is not None:
        if payload.rate_limit_requests_per_minute <= 0:
            raise HTTPException(status_code=422, detail="Rate limit must be positive")
        source.rate_limit_requests_per_minute = payload.rate_limit_requests_per_minute
    if payload.is_enabled is not None:
        if payload.is_enabled:
            # Enforce gate: cannot enable unless terms review has verified it
            if source.capability_status != "VERIFIED_READ_ONLY":
                raise HTTPException(
                    status_code=400,
                    detail="TERMS_REVIEW_REQUIRED: Cannot enable source without prior VERIFIED_READ_ONLY terms review.",
                )
            source.is_enabled = True
        else:
            source.is_enabled = False

    session.commit()

    return {
        "source_name": source.source_name,
        "display_name": source.display_name,
        "capability_status": source.capability_status,
        "is_enabled": source.is_enabled,
        "is_read_only": True,
        "rate_limit_requests_per_minute": source.rate_limit_requests_per_minute,
        "min_poll_interval_seconds": source.min_poll_interval_seconds,
        "live_fetching_enabled": False,
    }
