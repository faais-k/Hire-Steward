import tempfile
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from conftest import PostgresDatabase, local_headers, upgrade
from backend.app.adapters.storage import EvidenceStorage
from backend.app.domain.candidate_evidence import CandidateEvidenceError
from backend.app.evidence_config import EvidenceSettings
from backend.app.main import create_app
from backend.app.services import candidate_evidence as service


pytestmark = pytest.mark.postgres


def _settings() -> EvidenceSettings:
    return EvidenceSettings(storage_root=Path(tempfile.gettempdir()) / "hire-steward-postgres-evidence")


def test_upgrade_from_0002_adds_candidate_evidence_schema(postgres_database: PostgresDatabase) -> None:
    upgrade(postgres_database, "0002_comp_evidence_trust")
    with postgres_database.engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0002_comp_evidence_trust"
    upgrade(postgres_database)
    inspector = inspect(postgres_database.engine)
    names = set(inspector.get_table_names(schema=postgres_database.schema))
    assert {
        "candidate_document_blobs",
        "candidate_evidence_storage_usage",
        "candidate_evidence_storage_reservations",
        "candidate_documents",
        "candidate_document_versions",
        "candidate_facts",
        "candidate_fact_evidence",
    } <= names
    with postgres_database.engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0003_candidate_evidence"
        assert connection.execute(
            text("SELECT committed_bytes, reserved_bytes, version FROM candidate_evidence_storage_usage")
        ).one() == (0, 0, 1)


def test_candidate_evidence_downgrade_is_destructive_for_synthetic_data(
    postgres_database: PostgresDatabase,
) -> None:
    upgrade(postgres_database)
    with postgres_database.engine.begin() as connection:
        connection.execute(text("INSERT INTO candidate_documents (id, display_name, state) VALUES ('synthetic', 'Synthetic', 'ACTIVE')"))
    config = Config("backend/alembic.ini")
    with postgres_database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0002_comp_evidence_trust")
        table_names = set(inspect(connection).get_table_names())
    assert "candidate_documents" not in table_names
    assert "compensation_preferences" in table_names


def test_postgres_candidate_route_stays_unreviewed_and_ready_detects_missing_table(
    postgres_database: PostgresDatabase,
) -> None:
    upgrade(postgres_database)
    settings = _settings()
    try:
        with TestClient(
            create_app(session_factory=postgres_database.session_factory, evidence_settings=settings)
        ) as client:
            created = client.post(
                "/api/v1/facts",
                headers=local_headers(),
                json={"fact_type": "SKILL", "value": {"name": "PostgreSQL"}},
            )
            assert created.status_code == 201, created.text
            assert created.json()["verification_state"] == "UNREVIEWED"
            with postgres_database.engine.begin() as connection:
                connection.exec_driver_sql("DROP TABLE candidate_fact_evidence")
            response = client.get("/ready", headers={"host": "localhost"})
            assert response.status_code == 503
            assert response.json() == {"detail": "DATABASE_NOT_READY"}
    finally:
        import shutil

        shutil.rmtree(settings.storage_root, ignore_errors=True)


def test_postgres_reservation_blocks_second_full_cap_upload(postgres_database: PostgresDatabase) -> None:
    upgrade(postgres_database)
    settings = EvidenceSettings(
        storage_root=Path(tempfile.gettempdir()) / "hire-steward-postgres-reservation",
        max_version_bytes=10,
        max_total_bytes=10,
    )
    storage = EvidenceStorage(settings)
    try:
        with postgres_database.session_factory() as session:
            first_document = service.create_document(session, "First")
        with postgres_database.session_factory() as session:
            second_document = service.create_document(session, "Second")
        with postgres_database.session_factory() as session:
            first = service.reserve_upload(session, first_document.id, storage, settings)
        with postgres_database.session_factory() as session:
            with pytest.raises(CandidateEvidenceError) as failure:
                service.reserve_upload(session, second_document.id, storage, settings)
        assert getattr(failure.value, "code", None) == "EVIDENCE_STORAGE_UNAVAILABLE"
        with postgres_database.session_factory() as session:
            service.release_failed_reservation(session, first.id, storage)
    finally:
        import shutil

        shutil.rmtree(settings.storage_root, ignore_errors=True)
