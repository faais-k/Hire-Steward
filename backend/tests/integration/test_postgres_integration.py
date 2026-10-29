from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from alembic import command
from alembic.config import Config
from conftest import PostgresDatabase, local_headers, upgrade

from backend.app.db.base import Base
from backend.app.db.models import CompensationPreference, CompensationPreferenceAudit
from backend.app.main import create_app
from backend.app.services.preferences import set_minimum_compensation


pytestmark = pytest.mark.postgres


def test_fresh_migration_matches_models_and_seeds_exact_default(postgres_database):
    upgrade(postgres_database)

    inspector = inspect(postgres_database.engine)
    table_names = set(inspector.get_table_names(schema=postgres_database.schema))
    assert table_names == set(Base.metadata.tables) | {"alembic_version"}
    for table in Base.metadata.sorted_tables:
        database_constraint_names = {
            constraint["name"]
            for constraint in (
                inspector.get_check_constraints(table.name, schema=postgres_database.schema)
                + inspector.get_foreign_keys(table.name, schema=postgres_database.schema)
                + inspector.get_unique_constraints(table.name, schema=postgres_database.schema)
            )
            if constraint.get("name")
        }
        primary_key_name = inspector.get_pk_constraint(
            table.name, schema=postgres_database.schema
        ).get("name")
        if primary_key_name:
            database_constraint_names.add(primary_key_name)
        expected_constraint_names = {
            constraint.name for constraint in table.constraints if constraint.name
        }
        assert expected_constraint_names <= database_constraint_names
        database_index_names = {
            index["name"]
            for index in inspector.get_indexes(table.name, schema=postgres_database.schema)
        }
        expected_index_names = {index.name for index in table.indexes if index.name}
        assert expected_index_names <= database_index_names

    preference_columns = {
        column["name"]: column for column in inspector.get_columns(
            "compensation_preferences", schema=postgres_database.schema
        )
    }
    assert preference_columns["amount"]["type"].precision == 18
    assert preference_columns["amount"]["type"].scale == 2

    assessment_columns = {
        column["name"]: column for column in inspector.get_columns(
            "compensation_assessments", schema=postgres_database.schema
        )
    }
    assert assessment_columns["evidence_verification_state"]["default"]
    assert "UNVERIFIED" in assessment_columns["evidence_verification_state"]["default"]

    with postgres_database.session_factory() as session:
        preference = session.get(CompensationPreference, 1)
        revision = session.scalar(text("SELECT version_num FROM alembic_version"))

    assert preference is not None
    assert preference.amount == Decimal("100000.00")
    assert preference.currency == "INR"
    assert preference.period == "YEAR"
    assert revision == "0005_application_tracking"


def test_readiness_fails_closed_when_required_table_is_dropped_after_migration(
    postgres_database,
):
    upgrade(postgres_database)
    with postgres_database.engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE compensation_assessments")
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0005_application_tracking"
        )
        assert connection.scalar(
            text("SELECT amount FROM compensation_preferences WHERE id = 1")
        ) == Decimal("100000.00")

    with TestClient(create_app(session_factory=postgres_database.session_factory)) as client:
        response = client.get("/ready", headers={"host": "localhost"})

    assert response.status_code == 503
    assert response.json() == {"detail": "DATABASE_NOT_READY"}


def test_legacy_assessment_migrates_to_unverified_and_api_fails_closed(postgres_database):
    upgrade(postgres_database, "0001_compensation_preference")
    with postgres_database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO compensation_assessments "
                "(id, job_reference, source_status, source_amount, source_currency, "
                "source_period, threshold_amount, threshold_currency, threshold_period, "
                "threshold_version, normalized_minimum_annual, normalized_maximum_annual, "
                "conversion_basis, outcome, reason_code, explanation) "
                "VALUES ('legacy-assessment', 'job-legacy', 'PAID', 200000, 'INR', 'YEAR', "
                "100000, 'INR', 'YEAR', 1, 200000, 200000, 'DIRECT_INR_ANNUAL', "
                "'MEETS_THRESHOLD', 'MEETS_MINIMUM', 'Historical assessment')"
            )
        )
    upgrade(postgres_database)

    with postgres_database.engine.connect() as connection:
        stored = connection.execute(
            text(
                "SELECT evidence_verification_state, outcome, reason_code "
                "FROM compensation_assessments WHERE id = 'legacy-assessment'"
            )
        ).one()

    assert stored == ("UNVERIFIED", "MEETS_THRESHOLD", "MEETS_MINIMUM")
    with TestClient(create_app(session_factory=postgres_database.session_factory)) as client:
        response = client.get(
            "/api/v1/compensation/assessments/legacy-assessment",
            headers={"host": "localhost"},
        )
    assert response.status_code == 200
    assert response.json()["outcome"] == "REVIEW_REQUIRED"
    assert response.json()["reason_code"] == "EVIDENCE_UNVERIFIED"
    assert response.json()["eligible_to_submit"] is False


def test_decimal_preference_update_round_trips_with_audit(postgres_database):
    upgrade(postgres_database)

    with postgres_database.session_factory() as session:
        result = set_minimum_compensation(session, Decimal("50000.25"))
        assert result.amount == Decimal("50000.25")

    with postgres_database.session_factory() as session:
        preference = session.get(CompensationPreference, 1)
        events = session.scalars(
            select(CompensationPreferenceAudit).order_by(
                CompensationPreferenceAudit.settings_version
            )
        ).all()

    assert preference is not None
    assert preference.amount == Decimal("50000.25")
    assert preference.version == 2
    assert len(events) == 1
    assert events[0].previous_amount == Decimal("100000.00")
    assert events[0].new_amount == Decimal("50000.25")
    assert events[0].settings_version == 2


def test_failed_audit_insert_rolls_back_preference_update(postgres_database):
    upgrade(postgres_database)

    def violate_audit_constraint(mapper, connection, target):
        target.new_amount = Decimal("-1.00")

    event.listen(CompensationPreferenceAudit, "before_insert", violate_audit_constraint)
    try:
        with postgres_database.session_factory() as session:
            with pytest.raises(IntegrityError):
                set_minimum_compensation(session, Decimal("50000.00"))
    finally:
        event.remove(CompensationPreferenceAudit, "before_insert", violate_audit_constraint)

    with postgres_database.session_factory() as session:
        preference = session.get(CompensationPreference, 1)
        events = session.scalars(select(CompensationPreferenceAudit)).all()

    assert preference is not None
    assert preference.amount == Decimal("100000.00")
    assert preference.version == 1
    assert events == []


def test_concurrent_preference_updates_are_serialized_and_audited(postgres_database):
    upgrade(postgres_database)

    barrier = Barrier(2)

    def update(amount: str) -> None:
        barrier.wait(timeout=5)
        with postgres_database.session_factory() as session:
            set_minimum_compensation(session, Decimal(amount))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(update, "50000.00"),
            executor.submit(update, "150000.00"),
        ]
        for future in futures:
            future.result(timeout=15)

    with postgres_database.session_factory() as session:
        preference = session.get(CompensationPreference, 1)
        events = session.scalars(
            select(CompensationPreferenceAudit).order_by(
                CompensationPreferenceAudit.settings_version
            )
        ).all()

    assert preference is not None
    assert preference.version == 3
    assert [event.settings_version for event in events] == [2, 3]
    assert events[0].previous_amount == Decimal("100000.00")
    assert events[1].previous_amount == events[0].new_amount
    assert preference.amount == events[1].new_amount


def test_singleton_check_constraint_rejects_second_preference(postgres_database):
    upgrade(postgres_database)

    with postgres_database.session_factory() as session:
        session.add(
            CompensationPreference(
                id=2,
                amount=Decimal("0.00"),
                currency="INR",
                period="YEAR",
                version=1,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_primary_key_rejects_duplicate_preference_row(postgres_database):
    upgrade(postgres_database)

    with postgres_database.session_factory() as session:
        session.add(
            CompensationPreference(
                id=1,
                amount=Decimal("50000.00"),
                currency="INR",
                period="YEAR",
                version=2,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_public_salary_report_stays_unverified_and_cannot_authorize_submission(
    postgres_database,
):
    upgrade(postgres_database)
    with TestClient(create_app(session_factory=postgres_database.session_factory)) as client:
        response = client.post(
            "/api/v1/compensation/assessments",
            headers=local_headers(),
            json={
                "job_reference": "pg-unverified-job",
                "reported_status": "PAID",
                "amount": "200000.00",
                "currency": "INR",
                "period": "YEAR",
                "evidence_reference": "claim:example.invalid:jobs:123",
            },
        )

    assert response.status_code == 201, response.text
    result = response.json()
    assert result["reported_status"] == "PAID"
    assert result["evidence_verification_state"] == "UNVERIFIED"
    assert result["outcome"] == "REVIEW_REQUIRED"
    assert result["reason_code"] == "EVIDENCE_UNVERIFIED"
    assert result["eligible_to_submit"] is False
    assert result["reported_evidence_reference"] == "claim:example.invalid:jobs:123"
    explanation = result["explanation"].lower()
    assert "unverified observation" in explanation
    assert "cannot authorize an action" in explanation
    assert "verified annualized compensation" not in explanation


def test_application_tracking_upgrade_and_downgrade_postgres(postgres_database):
    """Verify 0004 -> 0005 upgrade, constraint verification, and downgrade on PostgreSQL."""
    upgrade(postgres_database, "0004_job_discovery_persistence")
    inspector = inspect(postgres_database.engine)
    assert "tracked_applications" not in inspector.get_table_names(schema=postgres_database.schema)

    upgrade(postgres_database, "0005_application_tracking")
    inspector = inspect(postgres_database.engine)
    table_names = set(inspector.get_table_names(schema=postgres_database.schema))
    assert {"tracked_applications", "application_status_history"} <= table_names

    # Check constraints and foreign keys on tracked_applications
    fks = inspector.get_foreign_keys("tracked_applications", schema=postgres_database.schema)
    assert len(fks) == 1
    assert fks[0]["referred_table"] == "job_postings"
    assert fks[0]["options"]["ondelete"].upper() == "RESTRICT"

    uqs = inspector.get_unique_constraints("tracked_applications", schema=postgres_database.schema)
    uq_names = {u["name"] for u in uqs}
    assert "uq_tracked_applications_posting" in uq_names

    # Check foreign keys on application_status_history
    hist_fks = inspector.get_foreign_keys("application_status_history", schema=postgres_database.schema)
    assert len(hist_fks) == 1
    assert hist_fks[0]["referred_table"] == "tracked_applications"
    assert hist_fks[0]["options"]["ondelete"].upper() == "CASCADE"

    # Downgrade back to 0004_job_discovery_persistence
    config = Config("backend/alembic.ini")
    with postgres_database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0004_job_discovery_persistence")
        downgraded_tables = set(inspect(connection).get_table_names(schema=postgres_database.schema))

    assert "tracked_applications" not in downgraded_tables
    assert "application_status_history" not in downgraded_tables
    assert "job_postings" in downgraded_tables
