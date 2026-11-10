"""Unified user settings and search policy API routes (Stage 3 & Stage 7 Screen 7)."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_session, require_local_same_origin
from backend.app.domain.user_settings import UserSettingsError
from backend.app.services import user_settings as service

router = APIRouter(prefix="/api/v1/settings", tags=["Settings"])


class UserSettingsUpdateRequest(BaseModel):
    target_roles: list[str] | None = None
    target_locations: list[str] | None = None
    workplace_arrangements: list[str] | None = None
    sponsorship_requirement: str | None = None
    same_company_cooldown_days: int | None = None
    daily_application_cap: int | None = None
    auto_tailor_resume: bool | None = None
    dry_run_simulation_mode: bool | None = None
    ai_provider_mode: str | None = None
    ai_budget_limit_usd: float | None = None
    minimum_compensation: dict[str, Any] | None = None


@router.get("")
def read_settings(
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        return service.get_user_settings(session)
    except UserSettingsError as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc


@router.put("")
def update_settings(
    payload: UserSettingsUpdateRequest,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, Any]:
    try:
        updates = {k: v for k, v in payload.model_dump().items() if v is not None}
        return service.update_user_settings(session, updates)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except UserSettingsError as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc
