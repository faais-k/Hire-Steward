"""Unit tests for Answer Bank lifecycle, consent revocation, and API routes (Stage 2 & 5)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.models import AnswerBankItem
from backend.app.domain.answer_bank import AnswerBankError
from backend.app.main import create_app
from backend.app.services import answer_bank as service


def local_headers() -> dict[str, str]:
    return {"host": "localhost", "origin": "http://localhost"}


def test_answer_bank_domain_validation() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AnswerBankItem.__table__.create(engine)
    session_factory = sessionmaker(bind=engine)
    session: Session = session_factory()

    try:
        # Empty question should fail
        with pytest.raises(AnswerBankError) as exc1:
            service.create_answer_item(session, question="", answer="Some answer")
        assert exc1.value.code == "EMPTY_QUESTION"

        # Invalid category should fail
        with pytest.raises(AnswerBankError) as exc2:
            service.create_answer_item(session, question="Q?", answer="A", category="invalid_cat")
        assert exc2.value.code == "INVALID_CATEGORY"

        # "experience" category should succeed
        exp_item = service.create_answer_item(
            session, question="Describe your background.", answer="10 years in backend systems.", category="experience"
        )
        assert exp_item.category == "experience"
    finally:
        session.close()


def test_answer_bank_crud_and_revocation() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AnswerBankItem.__table__.create(engine)
    session_factory = sessionmaker(bind=engine)

    app = create_app(session_factory=session_factory)
    client = TestClient(app)

    # 1. Create item
    payload = {
        "question": "Tell me about a time you resolved a major production incident.",
        "answer": "Diagnosed root cause within 15 minutes, initiated rollback, and restored full SLA.",
        "category": "behavioral",
        "fact_ids": [],
        "reuse_consent": True,
    }
    create_resp = client.post("/api/v1/answers", json=payload, headers=local_headers())
    assert create_resp.status_code == 201
    item = create_resp.json()
    item_id = item["id"]
    assert item["category"] == "behavioral"
    assert item["reuse_consent"] is True
    assert item["version"] == 1

    # 2. List items
    list_resp = client.get("/api/v1/answers", headers=local_headers())
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    # 3. Filter by category
    cat_resp = client.get("/api/v1/answers?category=technical", headers=local_headers())
    assert cat_resp.status_code == 200
    assert len(cat_resp.json()) == 0

    # 4. Update item
    patch_resp = client.patch(
        f"/api/v1/answers/{item_id}",
        json={"answer": "Updated detailed resolution."},
        headers=local_headers(),
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["answer"] == "Updated detailed resolution."
    assert patch_resp.json()["version"] == 2

    # 5. Revoke / delete consent
    del_resp = client.delete(f"/api/v1/answers/{item_id}", headers=local_headers())
    assert del_resp.status_code == 200
    assert del_resp.json()["is_revoked"] is True
    assert del_resp.json()["reuse_consent"] is False

    # Default list excludes revoked
    list_after_revocation = client.get("/api/v1/answers", headers=local_headers()).json()
    assert len(list_after_revocation) == 0

    # List with include_revoked=true includes it
    list_all = client.get("/api/v1/answers?include_revoked=true", headers=local_headers()).json()
    assert len(list_all) == 1

    # 6. Attempting to grant reuse consent to revoked answer MUST fail with 422
    regrant_resp = client.patch(
        f"/api/v1/answers/{item_id}",
        json={"reuse_consent": True},
        headers=local_headers(),
    )
    assert regrant_resp.status_code == 422
    assert "Cannot grant reuse consent to a revoked answer" in regrant_resp.json()["detail"]


def test_answer_bank_experience_category_api() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AnswerBankItem.__table__.create(engine)
    session_factory = sessionmaker(bind=engine)

    app = create_app(session_factory=session_factory)
    client = TestClient(app)

    payload = {
        "question": "What is your relevant work experience?",
        "answer": "Over 8 years building resilient Python and cloud systems.",
        "category": "experience",
        "fact_ids": [],
        "reuse_consent": True,
    }
    resp = client.post("/api/v1/answers", json=payload, headers=local_headers())
    assert resp.status_code == 201
    data = resp.json()
    assert data["category"] == "experience"
    assert data["question"] == payload["question"]
