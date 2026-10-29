from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.models import CompensationPreference, CompensationPreferenceAudit
from backend.app.main import create_app
from backend.app.services.preferences import set_minimum_compensation


@pytest.fixture
def migrated_engine():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    config = Config("backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", "sqlite+pysqlite://")
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def migrated_factory(migrated_engine):
    return sessionmaker(bind=migrated_engine, expire_on_commit=False)


@pytest.fixture
def client(migrated_factory):
    app = create_app(session_factory=migrated_factory)
    with TestClient(app) as test_client:
        yield test_client


def local_headers():
    return {"host": "localhost", "origin": "http://localhost"}


def test_ready_reports_database_and_required_compensation_state(migrated_factory):
    with TestClient(create_app(session_factory=migrated_factory)) as client:
        response = client.get("/ready", headers={"host": "localhost"})

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_openapi_uses_hire_steward_product_metadata():
    with TestClient(create_app()) as client:
        response = client.get("/openapi.json", headers={"host": "localhost"})

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Hire-steward API"
    assert "Hire-steward" in response.json()["info"]["description"]


def test_liveness_stays_available_when_database_is_unavailable():
    app = create_app(
        database_url=(
            "postgresql+psycopg://jobpilot:invalid@127.0.0.1:1/jobpilot"
            "?connect_timeout=1"
        )
    )
    with TestClient(app) as client:
        health = client.get("/health", headers={"host": "localhost"})
        ready = client.get("/ready", headers={"host": "localhost"})

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert ready.status_code == 503
    assert ready.json() == {"detail": "DATABASE_NOT_READY"}
    assert "invalid" not in ready.text
    assert "connection refused" not in ready.text.lower()


def test_readiness_fails_when_database_is_not_configured(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(create_app()) as client:
        response = client.get("/ready", headers={"host": "localhost"})

    assert response.status_code == 503
    assert response.json() == {"detail": "DATABASE_NOT_CONFIGURED"}


def test_readiness_fails_when_required_schema_is_missing():
    engine = create_engine("sqlite+pysqlite://")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with TestClient(create_app(session_factory=factory)) as client:
            response = client.get("/ready", headers={"host": "localhost"})

        assert response.status_code == 503
        assert response.json() == {"detail": "DATABASE_NOT_READY"}
    finally:
        engine.dispose()


def test_readiness_fails_when_required_table_is_missing_after_migration(
    migrated_engine, migrated_factory
):
    with migrated_engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE compensation_assessments")
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0005_application_tracking"
        )
        assert connection.scalar(
            text("SELECT amount FROM compensation_preferences WHERE id = 1")
        ) == Decimal("100000.00")

    with TestClient(create_app(session_factory=migrated_factory)) as client:
        response = client.get("/ready", headers={"host": "localhost"})

    assert response.status_code == 503
    assert response.json() == {"detail": "DATABASE_NOT_READY"}
    assert "compensation_assessments" not in response.text


def test_readiness_fails_when_required_column_is_missing_after_migration(
    migrated_engine, migrated_factory
):
    with migrated_engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE compensation_assessments DROP COLUMN evidence_reference"
        )
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0005_application_tracking"
        )

    with TestClient(create_app(session_factory=migrated_factory)) as client:
        response = client.get("/ready", headers={"host": "localhost"})

    assert response.status_code == 503
    assert response.json() == {"detail": "DATABASE_NOT_READY"}


def test_readiness_fails_when_preference_row_is_missing(migrated_engine, migrated_factory):
    with migrated_engine.begin() as connection:
        connection.execute(text("DELETE FROM compensation_preferences WHERE id = 1"))

    with TestClient(create_app(session_factory=migrated_factory)) as client:
        response = client.get("/ready", headers={"host": "localhost"})

    assert response.status_code == 503
    assert response.json() == {"detail": "DATABASE_NOT_READY"}


def test_readiness_fails_when_preference_violates_backend_assumptions(
    migrated_engine, migrated_factory
):
    with migrated_engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            text("UPDATE compensation_preferences SET currency = 'USD' WHERE id = 1")
        )

    with TestClient(create_app(session_factory=migrated_factory)) as client:
        response = client.get("/ready", headers={"host": "localhost"})

    assert response.status_code == 503
    assert response.json() == {"detail": "DATABASE_NOT_READY"}


def test_readiness_fails_when_migrations_are_behind():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    config = Config("backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", "sqlite+pysqlite://")
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0001_compensation_preference")
    try:
        with TestClient(create_app(session_factory=factory)) as client:
            response = client.get("/ready", headers={"host": "localhost"})

        assert response.status_code == 503
        assert response.json() == {"detail": "DATABASE_NOT_READY"}
    finally:
        engine.dispose()


def test_migration_seeds_default_inr_annual_preference(client):
    response = client.get("/api/v1/settings/policies", headers={"host": "localhost"})

    assert response.status_code == 200
    assert response.json()["minimum_compensation"] == {
        "amount": "100000.00",
        "currency": "INR",
        "period": "YEAR",
        "version": 1,
    }


@pytest.mark.parametrize("amount", ["50000.00", "150000.00", "0"])
def test_user_can_update_minimum_and_audit_change(client, migrated_factory, amount):
    response = client.patch(
        "/api/v1/settings/policies",
        headers=local_headers(),
        json={
            "minimum_compensation": {
                "amount": amount,
                "currency": "INR",
                "period": "YEAR",
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["minimum_compensation"]["amount"] == Decimal(amount).quantize(
        Decimal("0.01")
    ).to_eng_string()
    with migrated_factory() as session:
        events = session.scalars(select(CompensationPreferenceAudit)).all()
    assert len(events) == 1
    assert events[0].previous_amount == Decimal("100000.00")
    assert events[0].new_amount == Decimal(amount)
    assert events[0].actor_type == "local_api"
    assert events[0].actor_id == "local"
    assert events[0].settings_version == 2
    assert events[0].changed_at is not None
    assert events[0].currency == "INR"
    assert events[0].period == "YEAR"


@pytest.mark.parametrize("amount", ["-1", "NaN", "Infinity", "-Infinity", "1.001", "1e3", "not-money", "99999999999999999.99"])
def test_invalid_amount_is_rejected_without_audit(client, migrated_factory, amount):
    response = client.patch(
        "/api/v1/settings/policies",
        headers=local_headers(),
        json={
            "minimum_compensation": {
                "amount": amount,
                "currency": "INR",
                "period": "YEAR",
            }
        },
    )

    assert response.status_code == 422
    with migrated_factory() as session:
        assert session.scalars(select(CompensationPreferenceAudit)).all() == []
        preference = session.get(CompensationPreference, 1)
    assert preference.amount == Decimal("100000.00")
    assert preference.version == 1


def test_numeric_json_input_is_rejected_to_avoid_float_policy_values(client):
    response = client.patch(
        "/api/v1/settings/policies",
        headers=local_headers(),
        json={
            "minimum_compensation": {
                "amount": 100000,
                "currency": "INR",
                "period": "YEAR",
            }
        },
    )

    assert response.status_code == 422


def test_update_requires_same_origin_for_local_browser_requests(client):
    response = client.patch(
        "/api/v1/settings/policies",
        headers={"host": "localhost", "origin": "https://attacker.example"},
        json={
            "minimum_compensation": {
                "amount": "50000",
                "currency": "INR",
                "period": "YEAR",
            }
        },
    )

    assert response.status_code == 403


def test_update_rejects_malformed_origin_port(client):
    response = client.patch(
        "/api/v1/settings/policies",
        headers={"host": "localhost", "origin": "http://localhost:invalid"},
        json={
            "minimum_compensation": {
                "amount": "50000",
                "currency": "INR",
                "period": "YEAR",
            }
        },
    )

    assert response.status_code == 403


def test_assessment_uses_persisted_threshold_and_rejects_client_override(client):
    updated = client.patch(
        "/api/v1/settings/policies",
        headers=local_headers(),
        json={
            "minimum_compensation": {
                "amount": "150000",
                "currency": "INR",
                "period": "YEAR",
            }
        },
    )
    assert updated.status_code == 200

    assessment = client.post(
        "/api/v1/compensation/assessments",
        headers=local_headers(),
        json={
            "job_reference": "job-120k",
            "reported_status": "PAID",
            "amount": "120000",
            "currency": "INR",
            "period": "YEAR",
            "evidence_reference": "source-observation-1",
            "minimum_compensation": {
                "amount": "0",
                "currency": "INR",
                "period": "YEAR",
            },
        },
    )

    assert assessment.status_code == 422

    valid = client.post(
        "/api/v1/compensation/assessments",
        headers=local_headers(),
        json={
            "job_reference": "job-120k",
            "reported_status": "PAID",
            "amount": "120000",
            "currency": "INR",
            "period": "YEAR",
            "evidence_reference": "source-observation-1",
        },
    )
    assert valid.status_code == 201
    assert valid.json()["outcome"] == "REVIEW_REQUIRED"
    assert valid.json()["reason_code"] == "EVIDENCE_UNVERIFIED"
    assert valid.json()["evidence_verification_state"] == "UNVERIFIED"
    assert valid.json()["reported_status"] == "PAID"
    assert valid.json()["minimum_compensation"]["amount"] == "150000.00"
    assert "verified annualized compensation" not in valid.json()["explanation"].lower()


def test_assessment_rejects_ai_decision_and_unknown_salary_is_review(client):
    bypass = client.post(
        "/api/v1/compensation/assessments",
        headers=local_headers(),
        json={
            "job_reference": "job-ai",
            "reported_status": "PAID",
            "amount": "1",
            "currency": "INR",
            "period": "YEAR",
            "ai_decision": "MEETS_THRESHOLD",
        },
    )
    assert bypass.status_code == 422

    unknown = client.post(
        "/api/v1/compensation/assessments",
        headers=local_headers(),
        json={"job_reference": "job-unknown", "reported_status": "UNKNOWN"},
    )
    assert unknown.status_code == 201
    assert unknown.json()["outcome"] == "REVIEW_REQUIRED"
    assert unknown.json()["reason_code"] == "EVIDENCE_UNVERIFIED"
    assert unknown.json()["evidence_verification_state"] == "UNVERIFIED"
    assert unknown.json()["reported_status"] == "UNKNOWN"
    assert unknown.json()["normalized_minimum_annual"] is None
    assert unknown.json()["created_at"].endswith("Z")
    assert "verified annualized compensation" not in unknown.json()["explanation"].lower()


def test_paid_salary_and_arbitrary_reference_remain_unverified(client):
    response = client.post(
        "/api/v1/compensation/assessments",
        headers=local_headers(),
        json={
            "job_reference": "job-reported-pay",
            "reported_status": "PAID",
            "amount": "250000",
            "currency": "INR",
            "period": "YEAR",
            "evidence_reference": "claim:verified-salary-source",
        },
    )

    assert response.status_code == 201
    result = response.json()
    assert result["outcome"] == "REVIEW_REQUIRED"
    assert result["reason_code"] == "EVIDENCE_UNVERIFIED"
    assert result["evidence_verification_state"] == "UNVERIFIED"
    assert result["reported_status"] == "PAID"
    assert result["reported_amount"] == "250000.00"
    assert result["normalized_minimum_annual"] is None
    assert "verified annualized compensation" not in result["explanation"].lower()
    assert result["eligible_to_submit"] is False
    assert "stored_outcome" not in result
    assert result["reported_evidence_reference"] == "claim:verified-salary-source"


def test_reported_unpaid_is_not_a_trusted_unpaid_decision(client):
    response = client.post(
        "/api/v1/compensation/assessments",
        headers=local_headers(),
        json={
            "job_reference": "job-reported-unpaid",
            "reported_status": "UNPAID",
        },
    )

    assert response.status_code == 201
    result = response.json()
    assert result["reported_status"] == "UNPAID"
    assert result["evidence_verification_state"] == "UNVERIFIED"
    assert result["outcome"] == "REVIEW_REQUIRED"
    assert result["reason_code"] == "EVIDENCE_UNVERIFIED"
    assert result["outcome"] != "BLOCKED"
    assert "reported" in result["explanation"].lower()
    assert "not a confirmed unpaid classification" in result["explanation"].lower()


@pytest.mark.parametrize(
    "claim",
    [
        {"verified": True},
        {"trusted": True},
        {"verification_state": "VERIFIED"},
        {"evidence_verification_state": "VERIFIED"},
        {"reported_status": "VERIFIED"},
        {"status": "PAID"},
        {"ai_status": "PAID"},
        {"ai_decision": "MEETS_THRESHOLD"},
        {"model_decision": "MEETS_THRESHOLD"},
    ],
)
def test_public_api_rejects_verification_and_decision_claims(client, claim):
    payload = {
        "job_reference": "job-trust-claim",
        "reported_status": "PAID",
        "amount": "250000",
        "currency": "INR",
        "period": "YEAR",
        "evidence_reference": "untrusted-reference",
    }
    payload.update(claim)

    response = client.post(
        "/api/v1/compensation/assessments",
        headers=local_headers(),
        json=payload,
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "INVALID_REQUEST"}
    assert "250000" not in response.text


def test_url_shaped_reference_is_not_accepted_as_proof(client):
    response = client.post(
        "/api/v1/compensation/assessments",
        headers=local_headers(),
        json={
            "job_reference": "job-url-reference",
            "reported_status": "PAID",
            "amount": "250000",
            "currency": "INR",
            "period": "YEAR",
            "evidence_reference": "https://example.invalid/jobs/123?verified=true",
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "INVALID_REQUEST"}
    assert "example.invalid" not in response.text


def test_assessment_history_keeps_threshold_after_setting_change(client):
    first = client.post(
        "/api/v1/compensation/assessments",
        headers=local_headers(),
        json={
            "job_reference": "job-history",
            "reported_status": "PAID",
            "amount": "80000",
            "currency": "INR",
            "period": "YEAR",
        },
    )
    assert first.status_code == 201
    assessment_id = first.json()["assessment_id"]

    changed = client.patch(
        "/api/v1/settings/policies",
        headers=local_headers(),
        json={
            "minimum_compensation": {
                "amount": "50000",
                "currency": "INR",
                "period": "YEAR",
            }
        },
    )
    assert changed.status_code == 200

    history = client.get(
        f"/api/v1/compensation/assessments/{assessment_id}",
        headers={"host": "localhost"},
    )
    assert history.status_code == 200
    assert history.json()["minimum_compensation"]["amount"] == "100000.00"
    assert history.json()["outcome"] == "REVIEW_REQUIRED"
    assert history.json()["reason_code"] == "EVIDENCE_UNVERIFIED"
    assert history.json()["evidence_verification_state"] == "UNVERIFIED"


def test_failed_audit_insert_rolls_back_preference_update(migrated_factory):
    def violate_audit_constraint(mapper, connection, target):
        target.new_amount = Decimal("-1.00")

    event.listen(CompensationPreferenceAudit, "before_insert", violate_audit_constraint)
    try:
        with migrated_factory() as session:
            with pytest.raises(IntegrityError):
                set_minimum_compensation(session, Decimal("50000.00"))
        with migrated_factory() as session:
            setting = session.get(CompensationPreference, 1)
        assert setting.amount == Decimal("100000.00")
        assert setting.version == 1
    finally:
        event.remove(CompensationPreferenceAudit, "before_insert", violate_audit_constraint)


def test_legacy_assessment_is_safely_reassessed_after_trust_migration():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    config = Config("backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", "sqlite+pysqlite://")

    try:
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0001_compensation_preference")
            connection.execute(
                text(
                    "INSERT INTO compensation_assessments "
                    "(id, job_reference, source_status, source_amount, source_currency, "
                    "source_period, threshold_amount, threshold_currency, threshold_period, "
                    "threshold_version, normalized_minimum_annual, normalized_maximum_annual, "
                    "conversion_basis, outcome, reason_code, explanation) "
                    "VALUES ('legacy-assessment', 'job-legacy', 'PAID', 200000, 'INR', 'YEAR', "
                    "100000, 'INR', 'YEAR', 1, 200000, 200000, 'DIRECT_INR_ANNUAL', "
                    "'MEETS_THRESHOLD', 'MEETS_MINIMUM', 'Verified annualized compensation meets threshold')"
                )
            )
            connection.commit()
            command.upgrade(config, "head")

        with factory() as session:
            legacy = session.execute(
                text(
                    "SELECT evidence_verification_state, outcome, reason_code "
                    "FROM compensation_assessments WHERE id = 'legacy-assessment'"
                )
            ).one()
        assert legacy == ("UNVERIFIED", "MEETS_THRESHOLD", "MEETS_MINIMUM")

        app = create_app(session_factory=factory)
        with TestClient(app) as test_client:
            response = test_client.get(
                "/api/v1/compensation/assessments/legacy-assessment",
                headers={"host": "localhost"},
            )

        assert response.status_code == 200
        result = response.json()
        assert result["outcome"] == "REVIEW_REQUIRED"
        assert result["reason_code"] == "EVIDENCE_UNVERIFIED"
        assert result["evidence_verification_state"] == "UNVERIFIED"
        assert result["eligible_to_submit"] is False
        assert result["normalized_minimum_annual"] is None
        assert "verified annualized compensation" not in result["explanation"].lower()

        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "0001_compensation_preference")
            legacy_columns = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(compensation_assessments)"
                )
            }
            assert "evidence_verification_state" not in legacy_columns
            preserved = connection.execute(
                text(
                    "SELECT outcome, reason_code FROM compensation_assessments "
                    "WHERE id = 'legacy-assessment'"
                )
            ).one()
        assert preserved == ("MEETS_THRESHOLD", "MEETS_MINIMUM")
    finally:
        engine.dispose()
