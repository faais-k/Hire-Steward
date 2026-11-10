"""Unit tests for Candidate Evidence verification and user review workflow."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from backend.app.db.models import (
    CandidateFact,
    CandidateFactEvidence,
    CandidateProfile,
    CompensationPreference,
    UserSettingsModel,
)
from backend.app.services.candidate_evidence import (
    create_fact,
    get_fact,
    verify_fact,
    reject_fact,
)
from backend.app.main import create_app
from backend.app.api.dependencies import get_session


@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    CandidateFact.__table__.create(engine)
    CandidateProfile.__table__.create(engine)
    CompensationPreference.__table__.create(engine)
    UserSettingsModel.__table__.create(engine)

    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        yield session


def test_fact_verification_and_rejection_workflow(test_db: Session):
    fact = create_fact(test_db, "SKILL", {"name": "PostgreSQL", "proficiency": "expert"})
    assert fact.verification_state == "UNREVIEWED"

    # User verifies fact
    verified = verify_fact(test_db, fact.id)
    assert verified.verification_state == "USER_VERIFIED"
    assert get_fact(test_db, fact.id).verification_state == "USER_VERIFIED"

    # User can also reject fact if inaccurate
    rejected = reject_fact(test_db, fact.id)
    assert rejected.verification_state == "REJECTED"
    assert get_fact(test_db, fact.id).verification_state == "REJECTED"


def test_fact_verification_api_endpoints(test_db: Session):
    fact = create_fact(test_db, "EMPLOYMENT", {"company": "Acme", "role": "Senior Engineer"})

    app = create_app()

    def override():
        yield test_db

    app.dependency_overrides[get_session] = override
    try:
        client = TestClient(app)

        # POST /facts/{id}/verify
        res_v = client.post(
            f"/api/v1/facts/{fact.id}/verify",
            headers={"host": "localhost", "origin": "http://localhost"},
        )
        assert res_v.status_code == 200
        assert res_v.json()["verification_state"] == "USER_VERIFIED"

        # POST /facts/{id}/reject
        res_r = client.post(
            f"/api/v1/facts/{fact.id}/reject",
            headers={"host": "localhost", "origin": "http://localhost"},
        )
        assert res_r.status_code == 200
        assert res_r.json()["verification_state"] == "REJECTED"
    finally:
        app.dependency_overrides.pop(get_session, None)
