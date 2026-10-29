"""Integration tests for User-Controlled Job Intake without Live Source Activation API."""

from __future__ import annotations

from pathlib import Path
import shutil
import socket
import tempfile
from unittest.mock import patch
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


def local_headers() -> dict[str, str]:
    return {"host": "localhost", "origin": "http://localhost"}


@pytest.fixture
def api_client(tmp_path: Path):
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
    storage_root = Path(tempfile.gettempdir()) / "hire-steward-intake-tests" / uuid4().hex
    settings = EvidenceSettings(storage_root=storage_root)

    app = create_app(session_factory=factory, evidence_settings=settings)

    with TestClient(app, base_url="http://localhost") as client:
        yield client

    if storage_root.exists():
        shutil.rmtree(storage_root, ignore_errors=True)


def test_job_intake_api_success_and_downstream_interoperability(api_client: TestClient) -> None:
    """Verify that a user-entered job is created, listed with badges, detailed, drafted, and tracked."""
    # 1. POST /api/v1/jobs/intake
    payload = {
        "title": "Principal Python Systems Architect",
        "company": "NextGen Distributed Systems",
        "description": (
            "We are seeking a Principal Systems Architect to design distributed backend systems.\n\n"
            "Requirements:\n"
            "- 8+ years experience with Python and high-throughput microservices\n"
            "- Deep expertise in PostgreSQL and relational database design\n\n"
            "Nice to have:\n"
            "- Kubernetes and cloud-native observability"
        ),
        "location": "Remote - Worldwide",
        "workplace_type": "remote",
        "commitment": "Full-time",
        "url": "https://careers.nextgen.example.com/roles/arch-891",
    }

    create_res = api_client.post("/api/v1/jobs/intake", json=payload, headers=local_headers())
    assert create_res.status_code == 201, create_res.text
    data = create_res.json()

    assert data["status"] == "SUCCESS"
    assert data["title"] == "Principal Python Systems Architect"
    assert data["employer_handle"] == "nextgen-distributed-systems"
    assert data["source_type"] == "USER_INTAKE"
    assert data["source_verification_status"] == "UNVERIFIED_USER_SUPPLIED"
    assert data["is_user_entered"] is True
    assert data["is_synthetic_fixture"] is False
    assert data["canonical_url"] == "https://careers.nextgen.example.com/roles/arch-891"
    assert "assessment" in data
    assert data["assessment"]["fit_tier"] in {
        "INSUFFICIENT_DATA",
        "STRONG_MATCH",
        "PARTIAL_MATCH",
        "WEAK_MATCH",
    }

    posting_id = data["id"]
    assert posting_id is not None

    # 2. GET /api/v1/jobs (List view)
    list_res = api_client.get("/api/v1/jobs", headers=local_headers())
    assert list_res.status_code == 200
    list_data = list_res.json()
    items = list_data["items"]
    assert len(items) >= 1

    matched_item = next((item for item in items if item["id"] == posting_id), None)
    assert matched_item is not None
    assert matched_item["title"] == "Principal Python Systems Architect"
    assert matched_item["is_user_entered"] is True
    assert matched_item["source_type"] == "USER_INTAKE"
    assert matched_item["source_verification_status"] == "UNVERIFIED_USER_SUPPLIED"
    assert matched_item["is_reference_url_only"] is True

    # 3. GET /api/v1/jobs/{posting_id} (Detail view)
    detail_res = api_client.get(f"/api/v1/jobs/{posting_id}", headers=local_headers())
    assert detail_res.status_code == 200
    detail_data = detail_res.json()
    assert detail_data["posting"]["id"] == posting_id
    assert detail_data["posting"]["is_user_entered"] is True
    assert detail_data["posting"]["source_type"] == "USER_INTAKE"
    assert detail_data["posting"]["source_verification_status"] == "UNVERIFIED_USER_SUPPLIED"
    assert detail_data["snapshot"]["is_reference_url_only"] is True
    assert detail_data["snapshot"]["canonical_url"] == "https://careers.nextgen.example.com/roles/arch-891"

    # 4. GET /api/v1/jobs/{posting_id}/application-draft (Evidence-grounded drafting)
    draft_res = api_client.get(f"/api/v1/jobs/{posting_id}/application-draft", headers=local_headers())
    assert draft_res.status_code == 200
    draft_data = draft_res.json()
    assert "resume_markdown" in draft_data
    assert "cover_letter_markdown" in draft_data
    assert draft_data["job_title"] == "Principal Python Systems Architect"
    assert draft_data["job_posting_id"] == posting_id

    # 5. POST /api/v1/applications/track (Application tracker interoperability)
    track_res = api_client.post(
        "/api/v1/applications/track",
        json={"job_posting_id": posting_id, "initial_status": "SAVED"},
        headers=local_headers(),
    )
    assert track_res.status_code == 201, track_res.text
    track_data = track_res.json()
    assert track_data["status"] == "SAVED"
    assert track_data["job_posting_id"] == posting_id


def test_job_intake_duplicate_submission_rejected(api_client: TestClient) -> None:
    """Verify duplicate submission under same employer raises 409 Conflict."""
    payload = {
        "title": "Data Engineer",
        "company": "Data Analytics Co",
        "description": "Responsible for designing robust ETL pipelines using PySpark and SQL.",
    }

    res1 = api_client.post("/api/v1/jobs/intake", json=payload, headers=local_headers())
    assert res1.status_code == 201

    res2 = api_client.post("/api/v1/jobs/intake", json=payload, headers=local_headers())
    assert res2.status_code == 409
    assert "DUPLICATE_JOB_POSTING" in res2.json()["detail"]


def test_job_intake_csrf_and_origin_guard(api_client: TestClient) -> None:
    """Verify that requests without local origin or from external origin are forbidden."""
    payload = {
        "title": "Security Engineer",
        "description": "Testing same-origin enforcement on user job intake endpoint.",
    }

    # Missing origin and referer
    res_no_origin = api_client.post("/api/v1/jobs/intake", json=payload)
    assert res_no_origin.status_code == 403

    # Disallowed external origin
    res_bad_origin = api_client.post(
        "/api/v1/jobs/intake",
        json=payload,
        headers={"host": "localhost", "origin": "https://malicious-external-site.com"},
    )
    assert res_bad_origin.status_code == 403


def test_job_intake_validation_and_url_boundary_rejection(api_client: TestClient) -> None:
    """Verify input validation boundaries and rejection of dangerous URL schemes."""
    # 1. Missing / empty title
    res_empty_title = api_client.post(
        "/api/v1/jobs/intake",
        json={"title": "   ", "description": "Valid job description exceeding 20 chars."},
        headers=local_headers(),
    )
    assert res_empty_title.status_code == 422
    assert "MISSING_TITLE" in res_empty_title.text

    # 2. Too short description (< 20 chars)
    res_short_desc = api_client.post(
        "/api/v1/jobs/intake",
        json={"title": "Software Engineer", "description": "Too short"},
        headers=local_headers(),
    )
    assert res_short_desc.status_code == 422
    assert "MISSING_DESCRIPTION" in res_short_desc.text

    # 3. Disallowed URL scheme (javascript, data, ftp, file)
    for bad_url in [
        "javascript:alert(1)",
        "data:text/html;base64,PHNjcmlwdD4=",
        "file:///etc/passwd",
        "ftp://mirror.example.com",
    ]:
        res_bad_url = api_client.post(
            "/api/v1/jobs/intake",
            json={
                "title": "Software Engineer",
                "description": "Valid job description exceeding 20 chars.",
                "url": bad_url,
            },
            headers=local_headers(),
        )
        assert res_bad_url.status_code == 422, f"Expected 422 for scheme {bad_url}"
        assert "INVALID_URL_SCHEME" in res_bad_url.text

    # 4. Invalid workplace type
    res_bad_wp = api_client.post(
        "/api/v1/jobs/intake",
        json={
            "title": "Software Engineer",
            "description": "Valid job description exceeding 20 chars.",
            "workplace_type": "metaverse",
        },
        headers=local_headers(),
    )
    assert res_bad_wp.status_code == 422
    assert "INVALID_WORKPLACE_TYPE" in res_bad_wp.text


def test_job_intake_strictly_offline_zero_sockets(api_client: TestClient) -> None:
    """Verify that job intake, listing, viewing, and drafting never make external network calls."""
    real_getaddrinfo = socket.getaddrinfo

    def guarded_getaddrinfo(host, port, *args, **kwargs):
        if host not in ("127.0.0.1", "localhost", "::1", None):
            raise AssertionError(f"DNS lookup / external network call for host '{host}' attempted! Job intake must remain strictly offline.")
        return real_getaddrinfo(host, port, *args, **kwargs)

    with patch.object(socket, "getaddrinfo", side_effect=guarded_getaddrinfo):
        # 1. Intake
        res = api_client.post(
            "/api/v1/jobs/intake",
            json={
                "title": "Offline Security Specialist",
                "company": "AirGap Inc",
                "description": "Designing completely offline verifiable workflows and systems.",
                "url": "https://airgap.example.com/jobs/offline-01",
            },
            headers=local_headers(),
        )
        assert res.status_code == 201
        job_id = res.json()["id"]

        # 2. List
        list_res = api_client.get("/api/v1/jobs", headers=local_headers())
        assert list_res.status_code == 200

        # 3. Detail
        detail_res = api_client.get(f"/api/v1/jobs/{job_id}", headers=local_headers())
        assert detail_res.status_code == 200

        # 4. Draft
        draft_res = api_client.get(f"/api/v1/jobs/{job_id}/application-draft", headers=local_headers())
        assert draft_res.status_code == 200

def test_job_intake_adversarial_xss_and_injection_payloads(api_client: TestClient) -> None:
    """Verify that script tags, event handlers, and HTML payloads in intake fields are stored safely as literal strings."""
    payload = {
        "title": "<script>alert('xss')</script> Architect \" onfocus=\"alert(1)\"",
        "company": "<img src=x onerror=alert(1)> Corp",
        "location": "<iframe src=\"javascript:alert(1)\">",
        "description": "Full description exceeding 20 chars with <svg onload=alert(1)> and [xss](javascript:alert(1)) inside.\n\nRequirements:\n- Must know Python <script>",
        "url": "https://secure.example.com/careers/job-01",
    }

    res = api_client.post("/api/v1/jobs/intake", json=payload, headers=local_headers())
    assert res.status_code == 201
    data = res.json()
    assert data["title"] == payload["title"]
    posting_id = data["id"]

    # Detail view
    detail_res = api_client.get(f"/api/v1/jobs/{posting_id}", headers=local_headers())
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["snapshot"]["title"] == payload["title"]
    assert detail["snapshot"]["description_plain"] == payload["description"]
    assert detail["snapshot"].get("description_html") is None

    # Application draft view executes safely without template or code execution
    draft_res = api_client.get(f"/api/v1/jobs/{posting_id}/application-draft", headers=local_headers())
    assert draft_res.status_code == 200
    draft = draft_res.json()
    assert payload["title"] in draft["job_title"]


def test_job_intake_null_byte_rejection_at_api(api_client: TestClient) -> None:
    """Verify API rejects null bytes with 422 rather than causing 500 database errors."""
    payload = {
        "title": "Engineer\x00Lead",
        "description": "Valid job description exceeding 20 characters length.",
    }
    res = api_client.post("/api/v1/jobs/intake", json=payload, headers=local_headers())
    assert res.status_code == 422


def test_job_intake_transaction_rollback_on_failure(api_client: TestClient) -> None:
    """Verify simulated error during match evaluation rolls back completely, leaving zero orphaned records."""
    from backend.app.db.models import JobPosting, JobPostingSnapshot

    payload = {
        "title": "Transaction Rollback Test Engineer",
        "company": "Rollback Corp",
        "description": "Designing transaction-safe relational database ingestion boundaries.",
    }

    with patch("backend.app.api.routes.job_discovery.evaluate_job_posting_match", side_effect=RuntimeError("Simulated matching failure")):
        res = api_client.post("/api/v1/jobs/intake", json=payload, headers=local_headers())
        assert res.status_code == 422
        assert "Simulated matching failure" in res.text

    # Verify that listing jobs does not return the failed posting
    list_res = api_client.get("/api/v1/jobs", headers=local_headers())
    assert list_res.status_code == 200
    items = list_res.json()["items"]
    assert not any(item["title"] == payload["title"] for item in items)


def test_job_intake_employer_handle_boundary_cases_at_api(api_client: TestClient) -> None:
    """Verify various edge-case employer names succeed at the API layer with valid handles."""
    cases = [
        ("_UnderScore Corp", "underscore-corp"),
        ("!@#$%^ Special", "special"),
        ("---Hyphens---", "hyphens"),
        ("123 Tech Solutions", "123-tech-solutions"),
    ]

    for company_name, expected_handle in cases:
        payload = {
            "title": f"Dev at {company_name}",
            "company": company_name,
            "description": "Valid job description exceeding 20 characters length for edge-case company.",
        }
        res = api_client.post("/api/v1/jobs/intake", json=payload, headers=local_headers())
        assert res.status_code == 201, f"Failed for {company_name}: {res.text}"
        data = res.json()
        assert data["employer_handle"] == expected_handle
