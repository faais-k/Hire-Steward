"""Unit tests for Answer Bank consent enforcement remediation."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from backend.app.db.models import AnswerBankItem, CandidateProfile
from backend.app.domain.answer_bank import AnswerBankEntry
from backend.app.services.answer_bank import (
    create_answer_item,
    get_answer_item,
    list_answer_items,
    revoke_answer_item,
)
from backend.app.main import create_app
from backend.app.api.dependencies import get_session
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AnswerBankItem.__table__.create(engine)
    CandidateProfile.__table__.create(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        yield session


def test_answer_bank_entry_default_consent_false():
    entry = AnswerBankEntry(
        id="test-1",
        question="Why Hire-Steward?",
        answer="Because it is transparent.",
    )
    assert entry.reuse_consent is False


def test_create_answer_item_defaults_to_no_consent(test_db: Session):
    item = create_answer_item(
        test_db,
        question="What is your greatest strength?",
        answer="Attention to detail and code quality.",
        category="behavioral",
    )
    assert item.reuse_consent is False
    assert item.is_revoked is False

    # Listed without consent_only
    all_items = list_answer_items(test_db, consent_only=False)
    assert len(all_items) == 1

    # Listed with consent_only
    consented_items = list_answer_items(test_db, consent_only=True)
    assert len(consented_items) == 0


def test_consent_only_filtering(test_db: Session):
    # Item 1: No consent
    create_answer_item(
        test_db,
        question="Q1",
        answer="A1",
        category="technical",
        reuse_consent=False,
    )
    # Item 2: Explicit consent granted
    create_answer_item(
        test_db,
        question="Q2",
        answer="A2",
        category="technical",
        reuse_consent=True,
    )

    consented = list_answer_items(test_db, consent_only=True)
    assert len(consented) == 1
    assert consented[0].question == "Q2"


def test_revocation_clears_consent_and_blocks_selection(test_db: Session):
    item = create_answer_item(
        test_db,
        question="Q_revoke",
        answer="A_revoke",
        category="general",
        reuse_consent=True,
    )
    assert item.reuse_consent is True

    # Revoke it
    revoked = revoke_answer_item(test_db, item.id)
    assert revoked.is_revoked is True
    assert revoked.reuse_consent is False

    # Should not appear in consent_only list
    consented = list_answer_items(test_db, consent_only=True)
    assert len(consented) == 0

    # Should not appear in standard list either (include_revoked=False)
    standard = list_answer_items(test_db, include_revoked=False)
    assert len(standard) == 0


def test_ai_answer_question_ignores_unconsented_answers(test_db: Session):
    # Create an answer with consent=False
    create_answer_item(
        test_db,
        question="Tell me about your Python experience",
        answer="5 years of Python development.",
        category="technical",
        reuse_consent=False,
    )

    app = create_app()

    def override_get_session():
        yield test_db

    app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(app)
        res = client.post(
            "/api/v1/ai/answer-question",
            json={"question": "Tell me about your Python experience", "category": "technical"},
            headers={"host": "localhost", "origin": "http://localhost"},
        )
        assert res.status_code == 200
        data = res.json()
        # Should NOT match unconsented answer from answer bank
        assert data["source"] != "ANSWER_BANK"
        assert data["is_pre_approved"] is False
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_database_migration_resets_historical_consent_raw_sql(tmp_path):
    """Verify at the database SQL level that migration 0008 resets historical consent and sets default to false."""
    from alembic.config import Config
    from alembic import command
    import sqlite3

    db_path = str(tmp_path / "migration_test.db")
    cfg = Config("backend/alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    # Upgrade to 0006 where reuse_consent default was true
    command.upgrade(cfg, "0006_candidate_profile")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    # Insert legacy item with default (which was true in 0006)
    cur.execute(
        "INSERT INTO answer_bank_items (id, question, answer, category, fact_ids, version, is_revoked, created_at, updated_at) "
        "VALUES ('legacy-default', 'Q default', 'A default', 'general', '[]', 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )
    # Insert legacy item with explicit true
    cur.execute(
        "INSERT INTO answer_bank_items (id, question, answer, category, fact_ids, reuse_consent, version, is_revoked, created_at, updated_at) "
        "VALUES ('legacy-explicit-true', 'Q explicit', 'A explicit', 'general', '[]', 1, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )
    conn.commit()

    # Verify both were 1 (true)
    cur.execute("SELECT id, reuse_consent FROM answer_bank_items ORDER BY id")
    rows = cur.fetchall()
    assert rows == [("legacy-default", 1), ("legacy-explicit-true", 1)]
    conn.close()

    # Upgrade to 0008
    command.upgrade(cfg, "0008_consent_cooldown_plans")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    # Verify migration 0008 reset all historical items to 0 (false)
    cur.execute("SELECT id, reuse_consent FROM answer_bank_items ORDER BY id")
    rows_after = cur.fetchall()
    assert rows_after == [("legacy-default", 0), ("legacy-explicit-true", 0)]

    # Insert new record without reuse_consent, verify new default is 0 (false)
    cur.execute(
        "INSERT INTO answer_bank_items (id, question, answer, category, fact_ids, version, is_revoked, created_at, updated_at) "
        "VALUES ('new-post-0008', 'Q new', 'A new', 'general', '[]', 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )
    conn.commit()
    cur.execute("SELECT reuse_consent FROM answer_bank_items WHERE id = 'new-post-0008'")
    new_val = cur.fetchone()[0]
    assert new_val == 0
    conn.close()

