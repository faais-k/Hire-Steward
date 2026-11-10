"""Unit tests for Data Portability checksum integrity and atomic restoration."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.models import (
    AnswerBankItem,
    CandidateFact,
    CandidateProfile,
    CompensationPreference,
    TrackedApplication,
    UserSettingsModel,
)
from backend.app.domain.data_portability import (
    DataPortabilityError,
    validate_import_bundle_manifest,
)
from backend.app.services.data_portability import (
    commit_import_dataset,
    export_dataset,
    preview_import_dataset,
)
from backend.app.services.answer_bank import create_answer_item
from backend.app.services.candidate_evidence import create_fact
from backend.app.services.candidate_profile import update_profile
from backend.app.services.user_settings import update_user_settings


@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    CandidateProfile.__table__.create(engine)
    CompensationPreference.__table__.create(engine)
    UserSettingsModel.__table__.create(engine)
    AnswerBankItem.__table__.create(engine)
    CandidateFact.__table__.create(engine)
    TrackedApplication.__table__.create(engine)

    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        session.add(
            CompensationPreference(
                id=1,
                amount=100000.0,
                currency="INR",
                period="YEAR",
                version=1,
            )
        )
        session.commit()
        yield session


def test_tampered_checksum_rejected(test_db: Session):
    bundle = export_dataset(test_db)
    assert bundle["manifest"]["checksum_sha256"] is not None

    # Tamper with the bundle content
    bundle["candidate_profile"]["name"] = "Tampered Identity"

    preview = preview_import_dataset(test_db, bundle)
    assert preview["is_valid"] is False
    assert preview["checksum_verified"] is False
    assert any("checksum" in w.lower() for w in preview["warnings"])

    # Attempting to commit tampered bundle must fail
    with pytest.raises(DataPortabilityError) as exc_info:
        commit_import_dataset(test_db, bundle)
    assert "IMPORT_VALIDATION_FAILED" in str(exc_info.value) or "CHECKSUM_MISMATCH" in str(exc_info.value)


def test_missing_checksum_rejected(test_db: Session):
    bundle = export_dataset(test_db)
    bundle["manifest"].pop("checksum_sha256", None)

    preview = preview_import_dataset(test_db, bundle)
    assert preview["is_valid"] is False
    assert preview["checksum_verified"] is False

    with pytest.raises(DataPortabilityError):
        commit_import_dataset(test_db, bundle)


def test_complete_roundtrip_restoration(test_db: Session):
    # Seed data across all supported entities
    update_profile(test_db, {"name": "Alice Candidate", "headline": "Senior Engineer"})
    update_user_settings(test_db, {"daily_application_cap": 7, "target_roles": ["Staff Engineer"]})
    create_answer_item(test_db, question="Q1", answer="A1", category="general", reuse_consent=False)
    create_fact(test_db, "SKILL", {"name": "Rust"})

    # Export
    bundle = export_dataset(test_db)
    assert bundle["manifest"]["record_counts"]["candidate_profile"] == 1
    assert bundle["manifest"]["record_counts"]["answer_bank_items"] == 1
    assert bundle["manifest"]["record_counts"]["candidate_facts"] == 1

    # Verify checksum
    preview = preview_import_dataset(test_db, bundle)
    assert preview["is_valid"] is True
    assert preview["checksum_verified"] is True
    assert preview["new_counts"]["candidate_facts"] == 1
    assert preview["collision_counts"]["candidate_profile"] == 1

    # Clear and restore in a clean DB
    engine2 = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    CandidateProfile.__table__.create(engine2)
    CompensationPreference.__table__.create(engine2)
    UserSettingsModel.__table__.create(engine2)
    AnswerBankItem.__table__.create(engine2)
    CandidateFact.__table__.create(engine2)
    TrackedApplication.__table__.create(engine2)

    session_factory2 = sessionmaker(bind=engine2)
    with session_factory2() as clean_db:
        clean_db.add(
            CompensationPreference(
                id=1,
                amount=100000.0,
                currency="INR",
                period="YEAR",
                version=1,
            )
        )
        clean_db.commit()
        result = commit_import_dataset(clean_db, bundle)
        assert result["status"] == "COMPLETED"
        assert result["restored_counts"]["candidate_profile"] == 1
        assert result["restored_counts"]["user_settings"] == 1
        assert result["restored_counts"]["candidate_facts"] == 1
        assert result["restored_counts"]["answer_bank_items"] == 1

        # Check restored content
        p = clean_db.get(CandidateProfile, "default")
        assert p.name == "Alice Candidate"
        s = clean_db.get(UserSettingsModel, "default")
        assert s.daily_application_cap == 7
        f = clean_db.query(CandidateFact).first()
        assert f.value_json["name"] == "Rust"
        a = clean_db.query(AnswerBankItem).first()
        assert a.question == "Q1"
        assert a.reuse_consent is False


def test_atomic_rollback_on_failure(test_db: Session):
    bundle = export_dataset(test_db)
    # Inject malformed data that fails during restore (e.g. invalid status on tracked application)
    bundle["tracked_applications"] = [
        {"id": "app-1", "job_posting_id": None, "status": "INVALID_STATUS"}
    ]
    # Recompute valid checksum for this payload so it passes preview but fails DB execution
    from backend.app.domain.data_portability import compute_bundle_checksum
    bundle["manifest"]["checksum_sha256"] = compute_bundle_checksum(bundle)

    with pytest.raises(DataPortabilityError) as exc_info:
        commit_import_dataset(test_db, bundle)
    assert "IMPORT_FAILED" in str(exc_info.value)
