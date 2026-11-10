"""Integration tests for AI question answering evidence provenance (Section 5 Remediation)."""

from pathlib import Path
import shutil
import tempfile
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.evidence_config import EvidenceSettings
from backend.app.main import create_app
from backend.app.services.answer_bank import create_answer_item, update_answer_item
from backend.app.services.candidate_evidence import (
    create_document,
    reserve_upload,
    mark_reservation_ready,
    finalize_document_version,
    create_fact,
    verify_fact,
    reject_fact,
    attach_provenance,
)
from backend.app.domain.candidate_evidence import FactVerificationState
from backend.app.db.models import CandidateFact


def local_headers() -> dict[str, str]:
    return {"host": "localhost", "origin": "http://localhost"}


@pytest.fixture
def app_env():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False, "autocommit": False},
        poolclass=StaticPool,
    )
    config = Config("backend/alembic.ini")
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage_root = Path(tempfile.gettempdir()) / "hire-steward-ai-tests" / uuid4().hex
    settings = EvidenceSettings(storage_root=storage_root)
    app = create_app(session_factory=factory, evidence_settings=settings)
    with TestClient(app) as client:
        yield client, factory, app.state.evidence_storage, settings
    engine.dispose()
    shutil.rmtree(storage_root, ignore_errors=True)


def test_empty_profile_returns_source_none_and_zero_confidence(app_env):
    client, _, _, _ = app_env
    resp = client.post(
        "/api/v1/ai/answer-question",
        headers=local_headers(),
        json={"question": "What is your experience with distributed systems?"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["source"] == "NONE"
    assert data["fact_ids"] == []
    assert data["confidence"] == 0.0
    assert data["is_pre_approved"] is False
    assert len(data["evidence_gaps"]) > 0


def test_user_entered_profile_without_facts_returns_user_entered_profile(app_env):
    client, _, _, _ = app_env
    # Populate candidate profile with unverified user text
    client.put(
        "/api/v1/profile",
        headers=local_headers(),
        json={
            "headline": "Lead Systems Architect",
            "summary": "10 years building high-throughput backend services.",
            "skills": [{"name": "Python"}, {"name": "Go"}],
        },
    )

    resp = client.post(
        "/api/v1/ai/answer-question",
        headers=local_headers(),
        json={"question": "Tell me about your technical background"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["source"] == "USER_ENTERED_PROFILE"
    assert data["fact_ids"] == []
    assert data["confidence"] == 0.5
    assert data["is_pre_approved"] is False
    assert "unverified user profile text" in data["verification_warning"]
    assert len(data["evidence_gaps"]) > 0


def test_unreviewed_candidate_fact_returns_unreviewed_evidence(app_env):
    client, factory, _, _ = app_env
    # Create an UNREVIEWED CandidateFact in the database
    with factory() as s:
        fact = create_fact(
            s,
            fact_type="SKILL",
            value={"skill": "Distributed Systems", "text": "Designed Kafka pipeline processing 1M eps"},
        )
        fact_id = fact.id

    resp = client.post(
        "/api/v1/ai/answer-question",
        headers=local_headers(),
        json={"question": "Do you have Kafka experience?"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["source"] == "UNREVIEWED_EVIDENCE"
    assert fact_id in data["fact_ids"]
    assert data["confidence"] == 0.5
    assert data["is_pre_approved"] is False
    assert "unreviewed candidate facts" in data["verification_warning"]
    assert len(data["evidence_gaps"]) > 0


def test_verified_fact_with_provenance_returns_verified_evidence(app_env):
    client, factory, storage, settings = app_env
    # Create document, version, fact, and attach provenance
    with factory() as s:
        doc = create_document(s, display_name="resume.txt")
        res = reserve_upload(s, doc.id, storage, settings)
        text_bytes = b"Skills:\nDesigned Kafka pipeline processing 1M eps"

        import asyncio

        async def _stream():
            yield text_bytes

        staged = asyncio.run(storage.stage_stream(res.temp_key, _stream()))
        mark_reservation_ready(s, res.id, staged)
        finalized = finalize_document_version(s, doc.id, res.id, staged, storage, "resume.txt")
        doc_ver_id = finalized.version.id

        fact = create_fact(
            s,
            fact_type="SKILL",
            value={"text": "Designed Kafka pipeline processing 1M eps"},
        )
        fact_id = fact.id

        # Attach provenance (byte span 8 to 49)
        attach_provenance(
            session=s,
            fact_id=fact_id,
            version_id=doc_ver_id,
            start=8,
            end=49,
            excerpt="Designed Kafka pipeline processing 1M eps",
            storage=storage,
        )
        # Verify the fact explicitly
        verify_fact(s, fact_id)

    resp = client.post(
        "/api/v1/ai/answer-question",
        headers=local_headers(),
        json={"question": "Tell me about your Kafka experience"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["source"] == "VERIFIED_EVIDENCE"
    assert data["fact_ids"] == [fact_id]
    assert data["confidence"] == 1.0
    assert data["is_pre_approved"] is False
    assert len(data["provenance"]) == 1
    assert data["provenance"][0]["fact_id"] == fact_id
    assert data["provenance"][0]["document_version_id"] == doc_ver_id
    assert data["evidence_gaps"] == []


def test_rejected_and_superseded_facts_are_excluded(app_env):
    client, factory, _, _ = app_env
    with factory() as s:
        # 1. Create a rejected fact
        fact1 = create_fact(s, fact_type="SKILL", value={"text": "Old Fortran skill"})
        reject_fact(s, fact1.id)

        # 2. Create a superseded fact
        fact2 = CandidateFact(
            id=str(uuid4()),
            fact_type="SKILL",
            value_json={"text": "Old Python 2.7"},
            value_hash="dummyhash",
            verification_state=FactVerificationState.SUPERSEDED.value,
        )
        s.add(fact2)
        s.commit()

    resp = client.post(
        "/api/v1/ai/answer-question",
        headers=local_headers(),
        json={"question": "What legacy languages do you know?"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Should not use the rejected or superseded facts
    assert data["source"] == "NONE"
    assert data["fact_ids"] == []


def test_answer_bank_requires_explicit_consent_and_non_revoked(app_env):
    client, factory, _, _ = app_env
    # Create Answer Bank item with reuse_consent=False
    with factory() as s:
        item_no_consent = create_answer_item(
            s,
            question="What is your greatest achievement?",
            answer="Built a petabyte data pipeline.",
            category="general",
            reuse_consent=False,
        )
        no_consent_id = item_no_consent.id
        s.commit()

    # Should not match because reuse_consent is False
    resp = client.post(
        "/api/v1/ai/answer-question",
        headers=local_headers(),
        json={"question": "What is your greatest achievement?"},
    )
    assert resp.status_code == 200
    assert resp.json()["source"] != "ANSWER_BANK"

    # Now update with reuse_consent=True
    with factory() as s:
        update_answer_item(s, no_consent_id, reuse_consent=True)
        s.commit()

    resp2 = client.post(
        "/api/v1/ai/answer-question",
        headers=local_headers(),
        json={"question": "What is your greatest achievement?"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["source"] == "ANSWER_BANK"
    assert resp2.json()["answer_id"] == no_consent_id
    assert resp2.json()["confidence"] == 1.0
    assert resp2.json()["is_pre_approved"] is True

    # Now revoke consent
    with factory() as s:
        update_answer_item(s, no_consent_id, is_revoked=True)
        s.commit()

    resp3 = client.post(
        "/api/v1/ai/answer-question",
        headers=local_headers(),
        json={"question": "What is your greatest achievement?"},
    )
    assert resp3.status_code == 200
    assert resp3.json()["source"] != "ANSWER_BANK"
