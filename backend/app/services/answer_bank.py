"""Service layer for Answer Bank item lifecycle, versioning, and consent management (Stage 2 & 5)."""

from __future__ import annotations

import uuid
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import AnswerBankItem
from backend.app.domain.answer_bank import AnswerBankEntry, AnswerBankError


def create_answer_item(
    session: Session,
    question: str,
    answer: str,
    category: str = "general",
    fact_ids: list[str] | None = None,
    reuse_consent: bool = False,
) -> AnswerBankItem:
    """Create and validate a new answer bank record."""
    item_id = str(uuid.uuid4())
    entry = AnswerBankEntry(
        id=item_id,
        question=question,
        answer=answer,
        category=category,
        fact_ids=fact_ids or [],
        reuse_consent=reuse_consent,
    )
    entry.validate()

    db_item = AnswerBankItem(
        id=item_id,
        question=entry.question,
        answer=entry.answer,
        category=entry.category,
        fact_ids=entry.fact_ids,
        reuse_consent=entry.reuse_consent,
        version=1,
        is_revoked=False,
    )
    session.add(db_item)
    session.flush()
    return db_item


def get_answer_item(session: Session, answer_id: str) -> AnswerBankItem | None:
    return session.get(AnswerBankItem, answer_id)


def list_answer_items(
    session: Session,
    category: str | None = None,
    include_revoked: bool = False,
    consent_only: bool = False,
) -> list[AnswerBankItem]:
    stmt = select(AnswerBankItem)
    if not include_revoked:
        stmt = stmt.where(AnswerBankItem.is_revoked.is_(False))
    if consent_only:
        stmt = stmt.where(AnswerBankItem.reuse_consent.is_(True))
    if category:
        stmt = stmt.where(AnswerBankItem.category == category)
    stmt = stmt.order_by(AnswerBankItem.created_at.desc())
    return list(session.scalars(stmt).all())


def update_answer_item(
    session: Session,
    answer_id: str,
    question: str | None = None,
    answer: str | None = None,
    category: str | None = None,
    fact_ids: list[str] | None = None,
    reuse_consent: bool | None = None,
    is_revoked: bool | None = None,
) -> AnswerBankItem:
    item = session.get(AnswerBankItem, answer_id)
    if item is None:
        raise AnswerBankError(f"Answer with id {answer_id} not found", code="ANSWER_NOT_FOUND")

    if question is not None:
        item.question = question
    if answer is not None:
        item.answer = answer
    if category is not None:
        item.category = category
    if fact_ids is not None:
        item.fact_ids = fact_ids
    old_consent = item.reuse_consent
    if reuse_consent is not None:
        item.reuse_consent = reuse_consent
    if is_revoked is not None:
        item.is_revoked = is_revoked
        if is_revoked and reuse_consent is None:
            item.reuse_consent = False

    # Validate updated state
    entry = AnswerBankEntry(
        id=item.id,
        question=item.question,
        answer=item.answer,
        category=item.category,
        fact_ids=item.fact_ids,
        reuse_consent=item.reuse_consent,
        is_revoked=item.is_revoked,
    )
    entry.validate()

    if reuse_consent is not None and reuse_consent != old_consent:
        from backend.app.services.audit import record_audit_event

        record_audit_event(
            session,
            event_type="ANSWER_CONSENT_MODIFIED",
            entity_type="ANSWER_BANK_ITEM",
            entity_id=item.id,
            payload_json={
                "previous_consent": old_consent,
                "new_consent": reuse_consent,
            },
        )

    item.version += 1
    session.flush()
    return item


def revoke_answer_item(session: Session, answer_id: str) -> AnswerBankItem:
    return update_answer_item(session, answer_id, is_revoked=True, reuse_consent=False)
