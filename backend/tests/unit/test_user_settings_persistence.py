"""Unit tests for User Settings persistence decoupling and rollback safety."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.models import (
    CandidateProfile,
    CompensationPreference,
    UserSettingsModel,
)
from backend.app.services.candidate_profile import (
    get_or_create_profile,
    update_profile,
)
from backend.app.services.user_settings import (
    get_user_settings,
    update_user_settings,
)


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
    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        yield session


def test_user_settings_survives_profile_contact_info_update(test_db: Session):
    # 1. Update user settings
    update_user_settings(
        test_db,
        {
            "daily_application_cap": 25,
            "same_company_cooldown_days": 45,
            "target_roles": ["Lead Architect"],
        },
    )

    settings_before = get_user_settings(test_db)
    assert settings_before["daily_application_cap"] == 25
    assert settings_before["same_company_cooldown_days"] == 45
    assert settings_before["target_roles"] == ["Lead Architect"]

    # 2. Update candidate profile contact info (simulating PUT /api/v1/profile)
    update_profile(
        test_db,
        {
            "contact_info": {
                "email": "user@example.com",
                "phone": "+1-555-0100",
                "location": "San Francisco, CA",
            }
        },
    )
    test_db.commit()

    # 3. Verify settings remain intact and unchanged
    settings_after = get_user_settings(test_db)
    assert settings_after["daily_application_cap"] == 25
    assert settings_after["same_company_cooldown_days"] == 45
    assert settings_after["target_roles"] == ["Lead Architect"]

    # 4. Verify profile contact info remains clean without _user_settings pollution
    profile = get_or_create_profile(test_db)
    assert profile.contact_info["email"] == "user@example.com"
    assert "_user_settings" not in profile.contact_info


def test_user_settings_auto_commit_false_rollback(test_db: Session):
    # Set initial value
    update_user_settings(test_db, {"daily_application_cap": 10}, auto_commit=True)
    assert get_user_settings(test_db)["daily_application_cap"] == 10

    # Start a transaction, update with auto_commit=False, then roll back
    try:
        update_user_settings(test_db, {"daily_application_cap": 50}, auto_commit=False)
        raise RuntimeError("Simulated crash before commit")
    except RuntimeError:
        test_db.rollback()

    # Verify daily_application_cap was rolled back to 10
    assert get_user_settings(test_db)["daily_application_cap"] == 10


def test_user_settings_missing_row_falls_back_to_defaults(test_db: Session):
    """Missing compensation row (e.g. unseeded DB) safely falls back to standard INR 100k preference."""
    settings = get_user_settings(test_db)
    assert settings["minimum_compensation"]["amount"] == "100000.00"
    assert settings["minimum_compensation"]["currency"] == "INR"


def test_user_settings_database_failure_raises_exception_not_defaults(test_db: Session):
    """Genuine database errors raise UserSettingsError and NEVER silently become default settings."""
    from unittest.mock import MagicMock
    from backend.app.domain.user_settings import UserSettingsError
    from sqlalchemy.exc import OperationalError

    # 1. Database failure on settings record load
    broken_session = MagicMock(spec=Session)
    broken_session.get.side_effect = OperationalError("SELECT 1", {}, Exception("connection closed unexpectedly"))

    with pytest.raises(UserSettingsError) as exc_info:
        get_user_settings(broken_session)
    assert "FAILED_TO_LOAD_SETTINGS" in str(exc_info.value)

    # 2. Database failure on compensation query
    settings_ok_session = MagicMock(spec=Session)
    mock_record = UserSettingsModel(id="default")
    settings_ok_session.get.return_value = mock_record
    settings_ok_session.scalar.side_effect = OperationalError("SELECT comp", {}, Exception("database disk image is malformed"))

    with pytest.raises(UserSettingsError) as exc_info2:
        get_user_settings(settings_ok_session)
    assert "FAILED_TO_LOAD_COMPENSATION_PREFERENCE" in str(exc_info2.value)

