"""Integration tests for application tracking and job-search pipeline API."""

from __future__ import annotations

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
    storage_root = Path(tempfile.gettempdir()) / "hire-steward-tracking-tests" / uuid4().hex
    settings = EvidenceSettings(storage_root=storage_root)

    app = create_app(session_factory=factory, evidence_settings=settings)

    with TestClient(app, base_url="http://localhost") as client:
        # Seed fixtures so jobs are present
        res = client.post("/api/v1/jobs/seed-fixtures", headers=local_headers())
        assert res.status_code == 200
        yield client

    if storage_root.exists():
        shutil.rmtree(storage_root, ignore_errors=True)


def test_track_job_and_retrieve_details(api_client: TestClient):
    """Verify tracking a job returns 201 Created and detailed status history."""
    res = api_client.post(
        "/api/v1/applications/track",
        json={"job_posting_id": "syn_py_backend_01", "notes": "Top tier target"},
        headers=local_headers(),
    )
    assert res.status_code == 201
    data = res.json()
    app_id = data["id"]
    assert data["status"] == "SAVED"
    assert data["notes"] == "Top tier target"
    assert data["version"] == 1
    assert data["job_title"] == "Senior Python Backend Engineer"
    assert len(data["status_history"]) == 1
    assert data["status_history"][0]["to_status"] == "SAVED"

    # Retrieve directly
    get_res = api_client.get(f"/api/v1/applications/{app_id}", headers=local_headers())
    assert get_res.status_code == 200
    assert get_res.json()["id"] == app_id

    # Check via job endpoint
    chk_res = api_client.get("/api/v1/jobs/syn_py_backend_01/tracking", headers=local_headers())
    assert chk_res.status_code == 200
    chk_data = chk_res.json()
    assert chk_data["tracked"] is True
    assert chk_data["application"]["id"] == app_id


def test_track_job_errors(api_client: TestClient):
    """Verify non-existent job gives 404 and duplicate gives 409."""
    # 404 for non-existent job
    res_404 = api_client.post(
        "/api/v1/applications/track",
        json={"job_posting_id": "non_existent_posting_999"},
        headers=local_headers(),
    )
    assert res_404.status_code == 404
    assert res_404.json()["detail"] == "POSTING_NOT_FOUND"

    # Track once
    res_ok = api_client.post(
        "/api/v1/applications/track",
        json={"job_posting_id": "syn_k8s_infra_02"},
        headers=local_headers(),
    )
    assert res_ok.status_code == 201

    # Track again -> 409
    res_dup = api_client.post(
        "/api/v1/applications/track",
        json={"job_posting_id": "syn_k8s_infra_02"},
        headers=local_headers(),
    )
    assert res_dup.status_code == 409
    assert res_dup.json()["detail"] == "DUPLICATE_APPLICATION_TRACKING"


def test_list_applications_filtering_and_sorting(api_client: TestClient):
    """Verify listing applications with status filtering and invalid validation handling."""
    # Track two jobs
    api_client.post(
        "/api/v1/applications/track",
        json={"job_posting_id": "syn_py_backend_01"},
        headers=local_headers(),
    )
    app2_res = api_client.post(
        "/api/v1/applications/track",
        json={"job_posting_id": "syn_data_eng_03"},
        headers=local_headers(),
    )
    app2_id = app2_res.json()["id"]

    # Transition second job to PREPARING
    api_client.patch(
        f"/api/v1/applications/{app2_id}/status",
        json={"target_status": "PREPARING"},
        headers=local_headers(),
    )

    # Filter by status=PREPARING
    filter_res = api_client.get("/api/v1/applications?status=PREPARING", headers=local_headers())
    assert filter_res.status_code == 200
    items = filter_res.json()
    assert len(items) == 1
    assert items[0]["id"] == app2_id

    # Invalid status filter -> 422
    inv_res = api_client.get("/api/v1/applications?status=INVALID_STATUS", headers=local_headers())
    assert inv_res.status_code == 422

    # Invalid sort_by -> 422
    inv_sort = api_client.get("/api/v1/applications?sort_by=unknown_col", headers=local_headers())
    assert inv_sort.status_code == 422


def test_status_transition_rules_and_concurrency(api_client: TestClient):
    """Verify valid transitions, illegal transitions, and optimistic locking."""
    res = api_client.post(
        "/api/v1/applications/track",
        json={"job_posting_id": "syn_py_backend_01"},
        headers=local_headers(),
    )
    app_id = res.json()["id"]

    # Illegal jump SAVED -> OFFER_RECEIVED -> 400
    bad_res = api_client.patch(
        f"/api/v1/applications/{app_id}/status",
        json={"target_status": "OFFER_RECEIVED"},
        headers=local_headers(),
    )
    assert bad_res.status_code == 400
    assert bad_res.json()["detail"] == "INVALID_STATUS_TRANSITION"

    # Concurrency error -> 409
    conflict_res = api_client.patch(
        f"/api/v1/applications/{app_id}/status",
        json={"target_status": "PREPARING", "expected_version": 99},
        headers=local_headers(),
    )
    assert conflict_res.status_code == 409
    assert conflict_res.json()["detail"] == "CONCURRENCY_CONFLICT"

    # Valid transition SAVED -> PREPARING with expected_version=1
    ok_res = api_client.patch(
        f"/api/v1/applications/{app_id}/status",
        json={"target_status": "PREPARING", "expected_version": 1},
        headers=local_headers(),
    )
    assert ok_res.status_code == 200
    assert ok_res.json()["status"] == "PREPARING"
    assert ok_res.json()["version"] == 2


def test_confirm_application_submission(api_client: TestClient):
    """Verify submission confirmation freezes snapshots and records SHA-256."""
    res = api_client.post(
        "/api/v1/applications/track",
        json={"job_posting_id": "syn_py_backend_01"},
        headers=local_headers(),
    )
    app_id = res.json()["id"]

    confirm_res = api_client.post(
        f"/api/v1/applications/{app_id}/confirm-submission",
        json={
            "resume_markdown": "# Senior Engineer Resume",
            "cover_letter_markdown": "# Cover Letter\n\nTo Team",
            "notes": "Applied on official careers portal",
        },
        headers=local_headers(),
    )
    assert confirm_res.status_code == 200
    data = confirm_res.json()
    assert data["status"] == "APPLIED"
    assert data["applied_at"] is not None
    assert data["submitted_resume_snapshot"] == "# Senior Engineer Resume"
    assert data["submitted_cover_letter_snapshot"] == "# Cover Letter\n\nTo Team"
    assert len(data["submitted_resume_sha256"]) == 64
    assert len(data["submitted_cover_letter_sha256"]) == 64


def test_mark_reviewed_and_archive(api_client: TestClient):
    """Verify mark-reviewed moves to READY_FOR_REVIEW and archive transitions to ARCHIVED."""
    res = api_client.post(
        "/api/v1/applications/track",
        json={"job_posting_id": "syn_py_backend_01"},
        headers=local_headers(),
    )
    app_id = res.json()["id"]

    # Mark reviewed
    rev_res = api_client.post(
        f"/api/v1/applications/{app_id}/mark-reviewed",
        json={"reviewed_resume": "# Verified Resume"},
        headers=local_headers(),
    )
    assert rev_res.status_code == 200
    assert rev_res.json()["status"] == "READY_FOR_REVIEW"
    assert rev_res.json()["reviewed_at"] is not None

    # Archive
    arch_res = api_client.post(
        f"/api/v1/applications/{app_id}/archive",
        json={"target_status": "ARCHIVED", "reason": "No longer interested"},
        headers=local_headers(),
    )
    assert arch_res.status_code == 200
    assert arch_res.json()["status"] == "ARCHIVED"


def test_local_loopback_enforcement(api_client: TestClient):
    """Verify untrusted origin / remote host is rejected."""
    untrusted_headers = {"host": "localhost", "origin": "http://evil-site.com"}
    res = api_client.get("/api/v1/applications", headers=untrusted_headers)
    assert res.status_code == 403
    assert res.json()["detail"] == "LOCAL_LOOPBACK_REQUIRED"



def test_direct_applied_status_patch_rejected(api_client: TestClient):
    """Verify that calling PATCH /status with target_status=APPLIED is rejected with 400."""
    res = api_client.post(
        "/api/v1/applications/track",
        json={"job_posting_id": "syn_py_backend_01"},
        headers=local_headers(),
    )
    app_id = res.json()["id"]

    patch_res = api_client.patch(
        f"/api/v1/applications/{app_id}/status",
        json={"target_status": "APPLIED"},
        headers=local_headers(),
    )
    assert patch_res.status_code == 400
    assert patch_res.json()["detail"] == "DIRECT_APPLIED_TRANSITION_NOT_ALLOWED"


def test_repeated_submission_confirmation_api_409(api_client: TestClient):
    """Verify that repeated submission confirmation returns 409 Conflict."""
    res = api_client.post(
        "/api/v1/applications/track",
        json={"job_posting_id": "syn_py_backend_01"},
        headers=local_headers(),
    )
    app_id = res.json()["id"]

    # First confirmation succeeds
    res1 = api_client.post(
        f"/api/v1/applications/{app_id}/confirm-submission",
        json={"resume_markdown": "# Resume V1", "cover_letter_markdown": "# Cover V1"},
        headers=local_headers(),
    )
    assert res1.status_code == 200

    # Second confirmation returns 409 Conflict
    res2 = api_client.post(
        f"/api/v1/applications/{app_id}/confirm-submission",
        json={"resume_markdown": "# Mutated", "cover_letter_markdown": "# Mutated"},
        headers=local_headers(),
    )
    assert res2.status_code == 409
    assert res2.json()["detail"] == "APPLICATION_ALREADY_SUBMITTED"


def test_cannot_unapply_via_archive_api(api_client: TestClient):
    """Verify that once submitted, an application cannot revert to SAVED through archive."""
    res = api_client.post(
        "/api/v1/applications/track",
        json={"job_posting_id": "syn_py_backend_01"},
        headers=local_headers(),
    )
    app_id = res.json()["id"]

    api_client.post(
        f"/api/v1/applications/{app_id}/confirm-submission",
        json={"resume_markdown": "# Resume V1"},
        headers=local_headers(),
    )

    # Archive
    api_client.post(
        f"/api/v1/applications/{app_id}/archive",
        headers=local_headers(),
    )

    # Revert to SAVED must be rejected with 400
    revert_res = api_client.patch(
        f"/api/v1/applications/{app_id}/status",
        json={"target_status": "SAVED"},
        headers=local_headers(),
    )
    assert revert_res.status_code == 400
    assert revert_res.json()["detail"] == "INVALID_STATUS_TRANSITION"


def test_track_with_initial_applied_rejected_api(api_client: TestClient):
    """Verify that POST /applications/track with initial_status=APPLIED is rejected."""
    res = api_client.post(
        "/api/v1/applications/track",
        json={"job_posting_id": "syn_py_backend_01", "initial_status": "APPLIED"},
        headers=local_headers(),
    )
    assert res.status_code == 422
