from pathlib import Path
import shutil
import tempfile
from dataclasses import replace
from datetime import datetime, timedelta, timezone
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
from backend.app.api.routes import candidate_evidence
from backend.app.services import candidate_evidence as candidate_service


def local_headers() -> dict[str, str]:
    return {"host": "localhost", "origin": "http://localhost"}


@pytest.fixture
def candidate_client(tmp_path: Path):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    config = Config("backend/alembic.ini")
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage_root = Path(tempfile.gettempdir()) / "hire-steward-evidence-tests" / uuid4().hex
    settings = EvidenceSettings(storage_root=storage_root)
    with TestClient(create_app(session_factory=factory, evidence_settings=settings)) as client:
        yield client
    engine.dispose()
    shutil.rmtree(storage_root, ignore_errors=True)


def test_document_upload_is_bounded_and_metadata_only(candidate_client: TestClient) -> None:
    created = candidate_client.post(
        "/api/v1/documents",
        headers=local_headers(),
        json={"display_name": "Resume"},
    )
    assert created.status_code == 201, created.text

    uploaded = candidate_client.post(
        f"/api/v1/documents/{created.json()['document_id']}/versions",
        headers={
            **local_headers(),
            "content-type": "text/plain; charset=utf-8",
            "x-original-filename": "resume.txt",
        },
        content=b"Python engineering experience\n",
    )
    assert uploaded.status_code == 201, uploaded.text
    result = uploaded.json()
    assert result["filename"] == "resume.txt"
    assert result["byte_size"] == len(b"Python engineering experience\n")
    assert "storage_key" not in result
    assert "Python engineering" not in uploaded.text

    listed = candidate_client.get(
        f"/api/v1/documents/{created.json()['document_id']}/versions",
        headers={"host": "localhost"},
    )
    assert listed.status_code == 200, listed.text
    assert listed.json() == [
        {
            **result,
            "media_type": "text/plain",
        }
    ]


def test_public_fact_and_provenance_remain_unreviewed(candidate_client: TestClient) -> None:
    document = candidate_client.post(
        "/api/v1/documents", headers=local_headers(), json={"display_name": "Resume"}
    ).json()
    version = candidate_client.post(
        f"/api/v1/documents/{document['document_id']}/versions",
        headers={
            **local_headers(),
            "content-type": "text/plain",
            "x-original-filename": "resume.txt",
        },
        content=b"Python\n",
    ).json()
    fact = candidate_client.post(
        "/api/v1/facts",
        headers=local_headers(),
        json={"fact_type": "SKILL", "value": {"name": "Python"}},
    )
    assert fact.status_code == 201, fact.text
    assert fact.json()["verification_state"] == "UNREVIEWED"

    linked = candidate_client.post(
        f"/api/v1/facts/{fact.json()['fact_id']}/provenance",
        headers=local_headers(),
        json={
            "document_version_id": version["document_version_id"],
            "byte_start": 0,
            "byte_end": 6,
            "excerpt": "Python",
        },
    )
    assert linked.status_code == 201, linked.text
    assert linked.json()["verification_state"] == "UNREVIEWED"
    assert "excerpt" not in linked.json()


@pytest.mark.parametrize(
    "body, expected_status, code",
    [
        (b"", 422, "INVALID_DOCUMENT_CONTENT"),
        (b"\xff", 422, "INVALID_DOCUMENT_CONTENT"),
        (b"safe\x00text", 422, "INVALID_DOCUMENT_CONTENT"),
    ],
)
def test_invalid_document_body_is_rejected(candidate_client: TestClient, body: bytes, expected_status: int, code: str) -> None:
    document = candidate_client.post(
        "/api/v1/documents", headers=local_headers(), json={"display_name": "Resume"}
    ).json()
    response = candidate_client.post(
        f"/api/v1/documents/{document['document_id']}/versions",
        headers={
            **local_headers(),
            "content-type": "text/plain",
            "x-original-filename": "resume.txt",
        },
        content=body,
    )
    assert response.status_code == expected_status
    assert response.json() == {"detail": code}


def test_public_request_cannot_supply_trusted_fact_state(candidate_client: TestClient) -> None:
    response = candidate_client.post(
        "/api/v1/facts",
        headers=local_headers(),
        json={
            "fact_type": "SKILL",
            "value": {"name": "Python"},
            "verification_state": "USER_VERIFIED",
        },
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "INVALID_REQUEST"}


def test_employment_dates_require_extended_iso_format(candidate_client: TestClient) -> None:
    response = candidate_client.post(
        "/api/v1/facts",
        headers=local_headers(),
        json={
            "fact_type": "EMPLOYMENT",
            "value": {"employer": "Example", "title": "Engineer", "start_date": "20260101"},
        },
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "INVALID_REQUEST"}


def test_ready_fails_closed_when_candidate_schema_is_missing(candidate_client: TestClient) -> None:
    # The isolated SQLite fixture applies the Foundation 3 head. Dropping one
    # required table must make readiness fail even while Alembic remains at head.
    factory = candidate_client.app.state.session_factory
    assert factory is not None
    with factory() as session:
        session.connection().exec_driver_sql("DROP TABLE candidate_facts")
        session.commit()
    response = candidate_client.get("/ready", headers={"host": "localhost"})
    assert response.status_code == 503
    assert response.json() == {"detail": "DATABASE_NOT_READY"}


def test_upload_rejects_untrusted_content_type_and_unsafe_filename(
    candidate_client: TestClient,
) -> None:
    document = candidate_client.post(
        "/api/v1/documents", headers=local_headers(), json={"display_name": "Resume"}
    ).json()
    wrong_type = candidate_client.post(
        f"/api/v1/documents/{document['document_id']}/versions",
        headers={**local_headers(), "content-type": "application/pdf", "x-original-filename": "resume.pdf"},
        content=b"not a PDF",
    )
    assert wrong_type.status_code == 415
    assert wrong_type.json() == {"detail": "UNSUPPORTED_MEDIA_TYPE"}
    traversal = candidate_client.post(
        f"/api/v1/documents/{document['document_id']}/versions",
        headers={**local_headers(), "content-type": "text/plain", "x-original-filename": "../resume.txt"},
        content=b"safe text",
    )
    assert traversal.status_code == 422
    assert traversal.json() == {"detail": "INVALID_DOCUMENT_CONTENT"}


def test_unexpected_post_staging_failure_releases_upload_slot(
    candidate_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A durable reservation may remain, but process-local admission cannot leak."""
    document = candidate_client.post(
        "/api/v1/documents", headers=local_headers(), json={"display_name": "Resume"}
    ).json()

    def raise_unexpected(*_args, **_kwargs):
        raise RuntimeError("synthetic database failure")

    monkeypatch.setattr(candidate_evidence.service, "mark_reservation_ready", raise_unexpected)
    with TestClient(candidate_client.app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/api/v1/documents/{document['document_id']}/versions",
            headers={
                **local_headers(),
                "content-type": "text/plain",
                "x-original-filename": "resume.txt",
            },
            content=b"candidate evidence",
        )
    assert response.status_code == 500
    assert "synthetic database failure" not in response.text

    storage = candidate_client.app.state.evidence_storage
    assert storage is not None
    first = storage.acquire_upload_slot()
    second = storage.acquire_upload_slot()
    if first:
        storage.release_upload_slot()
    if second:
        storage.release_upload_slot()
    assert first is True
    assert second is True


def test_reconciliation_keeps_failed_owned_cleanup_out_of_unexpected_report(
    candidate_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = candidate_client.post(
        "/api/v1/documents", headers=local_headers(), json={"display_name": "Resume"}
    ).json()
    storage = candidate_client.app.state.evidence_storage
    settings = candidate_client.app.state.evidence_settings
    factory = candidate_client.app.state.session_factory
    assert storage is not None and settings is not None and factory is not None
    with factory() as session:
        reservation = candidate_service.reserve_upload(
            session, document["document_id"], storage, settings
        )
        reservation.created_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    temp_path = storage._path(reservation.temp_key)
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.write_bytes(b"unremovable owned staging file")
    monkeypatch.setattr(storage, "remove", lambda _key: False)
    with factory() as session:
        result = candidate_service.reconcile_stale_reservations(
            session, storage, replace(settings, reconciliation_grace_seconds=0)
        )

    assert result["protected_reservations"] == 1
    assert result["unexpected_files"] == 0
