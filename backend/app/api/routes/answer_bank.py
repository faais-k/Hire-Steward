"""Answer Bank API endpoints for reusable interview responses and consent (Stage 2 & 5)."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_session, require_local_same_origin
from backend.app.domain.answer_bank import AnswerBankError
from backend.app.services import answer_bank as service

router = APIRouter(prefix="/api/v1/answers", tags=["Answer Bank"])


class AnswerCreateRequest(BaseModel):
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    category: str = Field(default="general")
    fact_ids: list[str] = Field(default_factory=list)
    reuse_consent: bool = False


class AnswerUpdateRequest(BaseModel):
    question: str | None = None
    answer: str | None = None
    category: str | None = None
    fact_ids: list[str] | None = None
    reuse_consent: bool | None = None
    is_revoked: bool | None = None


def _item_to_dict(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "question": item.question,
        "answer": item.answer,
        "category": item.category,
        "fact_ids": item.fact_ids,
        "reuse_consent": item.reuse_consent,
        "version": item.version,
        "is_revoked": item.is_revoked,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


@router.get("")
def list_answers(
    category: str | None = Query(default=None),
    include_revoked: bool = Query(default=False),
    consent_only: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    items = service.list_answer_items(
        session,
        category=category,
        include_revoked=include_revoked,
        consent_only=consent_only,
    )
    return [_item_to_dict(i) for i in items]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_answer(
    payload: AnswerCreateRequest,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, Any]:
    try:
        with session.begin():
            item = service.create_answer_item(
                session,
                question=payload.question,
                answer=payload.answer,
                category=payload.category,
                fact_ids=payload.fact_ids,
                reuse_consent=payload.reuse_consent,
            )
        return _item_to_dict(item)
    except AnswerBankError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc


@router.get("/{answer_id}")
def get_answer(
    answer_id: str,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    item = service.get_answer_item(session, answer_id)
    if item is None:
        raise HTTPException(status_code=404, detail="ANSWER_NOT_FOUND")
    return _item_to_dict(item)


@router.patch("/{answer_id}")
def update_answer(
    answer_id: str,
    payload: AnswerUpdateRequest,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, Any]:
    try:
        with session.begin():
            item = service.update_answer_item(
                session,
                answer_id=answer_id,
                question=payload.question,
                answer=payload.answer,
                category=payload.category,
                fact_ids=payload.fact_ids,
                reuse_consent=payload.reuse_consent,
                is_revoked=payload.is_revoked,
            )
        return _item_to_dict(item)
    except AnswerBankError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc


@router.delete("/{answer_id}")
def revoke_answer(
    answer_id: str,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, Any]:
    try:
        with session.begin():
            item = service.revoke_answer_item(session, answer_id)
        return _item_to_dict(item)
    except AnswerBankError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
