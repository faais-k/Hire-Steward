"""Integration tests for Job Discovery & Review Workbench API endpoints."""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.models import (
    CandidateDocument,
    CandidateDocumentBlob,
    CandidateDocumentVersion,
    CandidateFact,
    CandidateFactEvidence,
)
from backend.app.domain.candidate_evidence import FactType, FactVerificationState
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
    storage_root = Path(tempfile.gettempdir()) / "hire-steward-workbench-tests" / uuid4().hex
    settings = EvidenceSettings(storage_root=storage_root)

    app = create_app(session_factory=factory, evidence_settings=settings)
    with TestClient(app, base_url="http://localhost") as client:
        yield client

    engine.dispose()
    shutil.rmtree(storage_root, ignore_errors=True)


def test_workbench_static_assets_served(api_client: TestClient) -> None:
    # 1. Root index.html
    root_res = api_client.get("/")
    assert root_res.status_code == 200
    assert "text/html" in root_res.headers["content-type"]
    assert "Hire-Steward" in root_res.text
    assert "Job Discovery Workbench" in root_res.text

    # 2. Explicit /workbench route
    wb_res = api_client.get("/workbench")
    assert wb_res.status_code == 200
    assert "text/html" in wb_res.headers["content-type"]

    # 3. CSS stylesheet
    css_res = api_client.get("/app.css")
    assert css_res.status_code == 200
    assert "text/css" in css_res.headers["content-type"]
    assert "--fs-title" in css_res.text

    # 4. JS application script
    js_res = api_client.get("/app.js")
    assert js_res.status_code == 200
    assert any(t in js_res.headers["content-type"] for t in ["javascript", "text/plain"])
    assert "fetchJobs" in js_res.text


def test_list_jobs_empty_database(api_client: TestClient) -> None:
    res = api_client.get("/api/v1/jobs")
    assert res.status_code == 200
    data = res.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["candidate_evidence_count"] == 0


def test_seed_synthetic_fixtures_and_list_jobs(api_client: TestClient) -> None:
    # 1. Unauthenticated or non-origin call fails guard
    unauth = api_client.post("/api/v1/jobs/seed-fixtures")
    assert unauth.status_code == 403
    assert unauth.json()["detail"] == "LOCAL_SAME_ORIGIN_REQUIRED"

    # 2. Seed synthetic demo fixtures
    seed_res = api_client.post("/api/v1/jobs/seed-fixtures", headers=local_headers())
    assert seed_res.status_code == 200
    seed_data = seed_res.json()
    assert seed_data["status"] == "SUCCESS"
    assert seed_data["postings_seeded"] == 4

    # 3. List jobs now returns seeded items
    list_res = api_client.get("/api/v1/jobs")
    assert list_res.status_code == 200
    data = list_res.json()
    assert data["total"] == 4
    assert len(data["items"]) == 4
    # Candidate profile is empty and was NOT contaminated by seeding fixtures
    assert data["candidate_evidence_count"] == 0
    assert data["is_synthetic_fixture"] is True

    # 4. Check properties on an item
    py_job = next(j for j in data["items"] if "Python" in j["title"])
    assert py_job["workplace_type"] == "remote"
    assert py_job["employer_handle"] == "example-tech-corp"
    assert "assessment" in py_job
    # Empty candidate profile produces an honest INSUFFICIENT_DATA evaluation
    assert py_job["assessment"]["fit_tier"] == "INSUFFICIENT_DATA"
    assert py_job["assessment"]["overall_score"] is None
    assert py_job["assessment"]["required_coverage"] == 0.0


def test_search_and_filter_jobs(api_client: TestClient) -> None:
    api_client.post("/api/v1/jobs/seed-fixtures", headers=local_headers())

    # 1. Filter by keyword search "embedded"
    search_res = api_client.get("/api/v1/jobs?search=embedded")
    assert search_res.status_code == 200
    s_data = search_res.json()
    assert s_data["total"] == 1
    assert "Embedded" in s_data["items"][0]["title"]

    # 2. Filter by workplace_type="onsite"
    onsite_res = api_client.get("/api/v1/jobs?workplace_type=onsite")
    assert onsite_res.status_code == 200
    o_data = onsite_res.json()
    assert o_data["total"] == 2
    for item in o_data["items"]:
        assert item["workplace_type"] == "onsite"

    # 3. Filter by tier
    tier_res = api_client.get("/api/v1/jobs?tier=INSUFFICIENT_DATA")
    assert tier_res.status_code == 200
    t_data = tier_res.json()
    assert t_data["total"] == 4
    for item in t_data["items"]:
        assert item["assessment"]["fit_tier"] == "INSUFFICIENT_DATA"

    # 4. Sort by observed descending
    sort_res = api_client.get("/api/v1/jobs?sort_by=observed_desc")
    assert sort_res.status_code == 200
    assert sort_res.json()["total"] == 4


def test_get_job_detail_and_match_explanation(api_client: TestClient) -> None:
    api_client.post("/api/v1/jobs/seed-fixtures", headers=local_headers())

    list_res = api_client.get("/api/v1/jobs")
    job = list_res.json()["items"][0]
    job_id = job["id"]

    detail_res = api_client.get(f"/api/v1/jobs/{job_id}")
    assert detail_res.status_code == 200
    data = detail_res.json()

    assert data["posting"]["id"] == job_id
    assert data["posting"]["employer_handle"] == "example-tech-corp"
    assert data["snapshot"]["title"] == job["title"]
    assert "description_plain" in data["snapshot"]
    assert "description_html" not in data["snapshot"]
    assert "lists_json" in data["snapshot"]

    assessment = data["assessment"]
    assert assessment["fit_tier"] == "INSUFFICIENT_DATA"
    assert assessment["overall_score"] is None
    assert assessment["confidence_level"] == "LOW"
    assert "Candidate evidence profile is empty." in assessment["confidence_reasons"]
    assert "scores" in assessment
    assert "required_evaluations" in assessment
    assert "heuristic_notice" in assessment

    # Heuristic notice must explicitly disclaim offer probability
    assert "not an offer probability or guarantee of employment" in assessment["heuristic_notice"]

    # Each evaluation must have status and explanation
    for ev in assessment["required_evaluations"]:
        assert ev["status"] in ["MET", "CONTRADICTED", "INSUFFICIENT_EVIDENCE"]
        assert len(ev["explanation"]) > 0


def test_get_job_detail_404_on_missing(api_client: TestClient) -> None:
    res = api_client.get("/api/v1/jobs/non-existent-uuid")
    assert res.status_code == 404
    assert res.json()["detail"] == "POSTING_NOT_FOUND"


def test_seed_fixtures_is_strictly_idempotent(api_client: TestClient) -> None:
    # First seed call creates 4 postings
    first_res = api_client.post("/api/v1/jobs/seed-fixtures", headers=local_headers())
    assert first_res.status_code == 200
    first_data = first_res.json()
    assert first_data["status"] == "SUCCESS"
    assert first_data["postings_seeded"] == 4

    # Second seed call detects all fixtures already present and does not create duplicate runs
    second_res = api_client.post("/api/v1/jobs/seed-fixtures", headers=local_headers())
    assert second_res.status_code == 200
    second_data = second_res.json()
    assert second_data["status"] == "ALREADY_SEEDED"
    assert second_data["postings_seeded"] == 0

    # Verify job count is still 4
    list_res = api_client.get("/api/v1/jobs")
    assert list_res.status_code == 200
    assert list_res.json()["total"] == 4


def test_invalid_query_parameters_return_422(api_client: TestClient) -> None:
    # Invalid sort_by
    r = api_client.get("/api/v1/jobs?sort_by=arbitrary_sort")
    assert r.status_code == 422
    assert "INVALID_SORT_BY" in r.text

    # Invalid workplace_type
    r = api_client.get("/api/v1/jobs?workplace_type=underwater")
    assert r.status_code == 422
    assert "INVALID_WORKPLACE_TYPE" in r.text

    # Invalid tier
    r = api_client.get("/api/v1/jobs?tier=SUPER_HERO")
    assert r.status_code == 422
    assert "INVALID_TIER" in r.text

    # Invalid lifecycle_status
    r = api_client.get("/api/v1/jobs?lifecycle_status=DELETED_FOREVER")
    assert r.status_code == 422
    assert "INVALID_LIFECYCLE_STATUS" in r.text

    # Invalid limit (< 1)
    r = api_client.get("/api/v1/jobs?limit=0")
    assert r.status_code == 422

    # Invalid limit (> 100)
    r = api_client.get("/api/v1/jobs?limit=101")
    assert r.status_code == 422

    # Invalid offset (< 0)
    r = api_client.get("/api/v1/jobs?offset=-1")
    assert r.status_code == 422


def test_remote_client_ip_blocked_by_local_middleware() -> None:
    app = create_app()
    # Simulate a remote client on the LAN connecting to the port
    with TestClient(app, base_url="http://localhost", client=("192.168.1.50", 49152)) as remote_client:
        res = remote_client.get("/api/v1/jobs")
        assert res.status_code == 403
        assert res.json() == {"detail": "LOCAL_LOOPBACK_REQUIRED"}

        res_root = remote_client.get("/")
        assert res_root.status_code == 403
        assert res_root.json() == {"detail": "LOCAL_LOOPBACK_REQUIRED"}


def test_cross_origin_requests_from_untrusted_origins_blocked(api_client: TestClient) -> None:
    # Cross-origin request from malicious third-party site
    res = api_client.get("/api/v1/jobs", headers={"origin": "https://evil-attacker.example"})
    assert res.status_code == 403
    assert res.json() == {"detail": "LOCAL_LOOPBACK_REQUIRED"}

    # Origin null (sandboxed iframe or data: URI)
    res_null = api_client.get("/api/v1/jobs", headers={"origin": "null"})
    assert res_null.status_code == 403
    assert res_null.json() == {"detail": "LOCAL_LOOPBACK_REQUIRED"}


def test_seed_fixtures_does_not_modify_candidate_tables(api_client: TestClient) -> None:
    """Seeding fixtures into an empty database leaves candidate documents, blobs, facts, and evidence untouched."""
    seed_res = api_client.post("/api/v1/jobs/seed-fixtures", headers=local_headers())
    assert seed_res.status_code == 200

    with api_client.app.state.session_factory() as session:
        assert session.scalar(select(func.count(CandidateDocument.id))) == 0
        assert session.scalar(select(func.count(CandidateDocumentBlob.content_hash))) == 0
        assert session.scalar(select(func.count(CandidateDocumentVersion.id))) == 0
        assert session.scalar(select(func.count(CandidateFact.id))) == 0
        assert session.scalar(select(func.count(CandidateFactEvidence.id))) == 0


def test_seed_fixtures_preserves_existing_real_candidate_evidence(api_client: TestClient) -> None:
    """Seeding fixtures into a database with real candidate facts leaves all those records unchanged."""
    with api_client.app.state.session_factory() as session:
        real_fact = CandidateFact(
            id=str(uuid4()),
            fact_type=FactType.SKILL.value,
            value_json={"name": "Python"},
            value_hash="python-real-hash",
            verification_state=FactVerificationState.USER_VERIFIED.value,
        )
        session.add(real_fact)
        session.commit()
        real_fact_id = real_fact.id

    seed_res = api_client.post("/api/v1/jobs/seed-fixtures", headers=local_headers())
    assert seed_res.status_code == 200

    # Verify real candidate evidence remains intact and unpolluted
    with api_client.app.state.session_factory() as session:
        facts = list(session.scalars(select(CandidateFact)).all())
        assert len(facts) == 1
        assert facts[0].id == real_fact_id
        assert facts[0].value_json == {"name": "Python"}
        assert facts[0].verification_state == FactVerificationState.USER_VERIFIED.value

    # Verify list jobs reports 1 candidate fact and matches against real evidence
    list_res = api_client.get("/api/v1/jobs")
    assert list_res.status_code == 200
    data = list_res.json()
    assert data["candidate_evidence_count"] == 1
    py_job = next(j for j in data["items"] if "Python" in j["title"])
    # With Python verified in candidate evidence, required Python qualification is met!
    assert py_job["assessment"]["fit_tier"] in ["PARTIAL_MATCH", "STRONG_MATCH"]
    assert py_job["assessment"]["overall_score"] is not None


def test_job_detail_does_not_expose_raw_description_html(api_client: TestClient) -> None:
    """The job-detail API must not return raw description_html when only plain text/lists are consumed."""
    api_client.post("/api/v1/jobs/seed-fixtures", headers=local_headers())
    list_res = api_client.get("/api/v1/jobs")
    job_id = list_res.json()["items"][0]["id"]

    detail_res = api_client.get(f"/api/v1/jobs/{job_id}")
    assert detail_res.status_code == 200
    snapshot = detail_res.json()["snapshot"]
    assert "description_plain" in snapshot
    assert "description_html" not in snapshot


def test_middleware_fails_closed_when_client_address_is_missing() -> None:
    """LocalClientOnlyMiddleware fails closed when the ASGI request has no client address."""
    import asyncio
    app = create_app()

    async def invoke_asgi(client_tuple):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/health",
            "headers": [(b"host", b"localhost")],
            "client": client_tuple,
            "query_string": b"",
        }
        messages = []
        async def receive():
            return {"type": "http.request"}
        async def send(msg):
            messages.append(msg)
        await app(scope, receive, send)
        return messages

    # 1. client is None -> 403
    msgs_none = asyncio.run(invoke_asgi(None))
    start_none = next(m for m in msgs_none if m["type"] == "http.response.start")
    assert start_none["status"] == 403

    # 2. client is ("", 0) -> 403
    msgs_empty = asyncio.run(invoke_asgi(("", 0)))
    start_empty = next(m for m in msgs_empty if m["type"] == "http.response.start")
    assert start_empty["status"] == 403

    # 3. client is external LAN IP -> 403
    msgs_lan = asyncio.run(invoke_asgi(("192.168.1.50", 12345)))
    start_lan = next(m for m in msgs_lan if m["type"] == "http.response.start")
    assert start_lan["status"] == 403

    # 4. client is 127.0.0.1 -> 200
    msgs_local = asyncio.run(invoke_asgi(("127.0.0.1", 12345)))
    start_local = next(m for m in msgs_local if m["type"] == "http.response.start")
    assert start_local["status"] == 200
