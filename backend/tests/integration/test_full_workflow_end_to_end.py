"""Full end-to-end integration tests for Hire-Steward autonomous application workflow.

Covers the complete 10-stage lifecycle:
1. Operational system health & loopback check
2. Synthetic opportunity seeding & discovery
3. Candidate profile management & document parsing
4. Deterministic job matching
5. Application pipeline tracking & status transitions
6. Tailored application material generation (AI router)
7. Answer Bank reusable responses
8. Submission plan & simulated ATS dry-run
9. Human manual handoff packet export
10. Policy settings & source registry management
11. Data portability export, preview, and atomic restore
12. System activity & audit logging
"""

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
    storage_root = Path(tempfile.gettempdir()) / "hire-steward-e2e-tests" / uuid4().hex
    settings = EvidenceSettings(storage_root=storage_root)

    app = create_app(session_factory=factory, evidence_settings=settings)
    with TestClient(app, base_url="http://localhost") as client:
        yield client

    engine.dispose()
    shutil.rmtree(storage_root, ignore_errors=True)


def test_full_application_lifecycle_end_to_end(api_client: TestClient) -> None:
    # ---------------------------------------------------------
    # 1. Operational System Health & Diagnostics
    # ---------------------------------------------------------
    sys_res = api_client.get("/api/v1/system/status")
    assert sys_res.status_code == 200
    sys_data = sys_res.json()
    assert sys_data["status"] == "healthy"
    assert sys_data["database"]["connected"] is True
    assert sys_data["storage"]["writable"] is True

    # ---------------------------------------------------------
    # 2. Seed Synthetic Opportunities
    # ---------------------------------------------------------
    seed_res = api_client.post("/api/v1/jobs/seed-fixtures", headers=local_headers())
    assert seed_res.status_code == 200
    seed_data = seed_res.json()
    assert seed_data["status"] == "SUCCESS"
    assert seed_data["postings_seeded"] == 4

    # ---------------------------------------------------------
    # 3. Candidate Profile Creation & Extraction
    # ---------------------------------------------------------
    profile_payload = {
        "name": "Jane Doe",
        "headline": "Senior Staff Distributed Systems Engineer",
        "summary": "Specialist in high-throughput distributed systems, Python, FastAPI, and data platforms.",
        "contact_info": {
            "email": "jane.doe@example.com",
            "phone": "+1-555-0199",
            "location": "San Francisco, CA",
            "portfolio_url": "https://janedoe.dev",
        },
        "skills": [
            {"name": "Python", "category": "LANGUAGES"},
            {"name": "FastAPI", "category": "FRAMEWORKS"},
            {"name": "PostgreSQL", "category": "DATABASES"},
            {"name": "Distributed Systems", "category": "SYSTEMS"},
        ],
        "work_history": [
            {
                "title": "Lead Infrastructure Engineer",
                "organization": "Acme Cloud",
                "start_date": "2020-01-01",
                "end_date": "2024-01-01",
                "description": "Architected multi-region transactional event pipeline.",
            }
        ],
        "education": [
            {
                "institution": "UC Berkeley",
                "degree": "B.S. Computer Science",
                "end_date": "2018-05-15",
            }
        ],
    }
    put_prof_res = api_client.put(
        "/api/v1/profile",
        json=profile_payload,
        headers=local_headers(),
    )
    assert put_prof_res.status_code == 200
    prof_data = put_prof_res.json()
    assert prof_data["profile"]["name"] == "Jane Doe"
    assert prof_data["completeness"]["percentage"] >= 50

    # Test multi-format document extraction
    sample_resume = b"""Jane Doe
Staff Engineer
Summary:
Expert in high scale systems architecture and database optimization.
Experience:
Senior Engineer at CloudCorp leading database migrations.
"""
    doc_res = api_client.post(
        "/api/v1/profile/parse-document",
        content=sample_resume,
        headers={"x-filename": "sample_resume.txt", **local_headers()},
    )
    assert doc_res.status_code == 200
    doc_data = doc_res.json()
    assert doc_data["filename"] == "sample_resume.txt"
    assert doc_data["char_count"] > 50
    assert doc_data["sections_count"] >= 1

    # Register candidate evidence facts for matching and tailored drafting
    f_skill_res = api_client.post(
        "/api/v1/facts",
        json={"fact_type": "SKILL", "value": {"name": "Python"}},
        headers=local_headers(),
    )
    assert f_skill_res.status_code == 201

    f_emp_res = api_client.post(
        "/api/v1/facts",
        json={"fact_type": "EMPLOYMENT", "value": {"employer": "Acme Corp", "title": "Lead Engineer"}},
        headers=local_headers(),
    )
    assert f_emp_res.status_code == 201

    # ---------------------------------------------------------
    # 4. Job Discovery & Deterministic Match Scoring
    # ---------------------------------------------------------
    jobs_res = api_client.get("/api/v1/jobs")
    assert jobs_res.status_code == 200
    jobs_data = jobs_res.json()
    assert jobs_data["total"] == 4
    first_job = jobs_data["items"][0]
    job_id = first_job["id"]
    assert first_job["assessment"] is not None
    assert "fit_tier" in first_job["assessment"]

    # ---------------------------------------------------------
    # 5. Application Pipeline Tracking
    # ---------------------------------------------------------
    track_res = api_client.post(
        "/api/v1/applications/track",
        json={"job_posting_id": job_id, "notes": "E2E automated testing pipeline entry"},
        headers=local_headers(),
    )
    assert track_res.status_code == 201
    app_id = track_res.json()["id"]

    # Verify listing in pipeline
    pipe_res = api_client.get("/api/v1/applications")
    assert pipe_res.status_code == 200
    pipe_data = pipe_res.json()
    assert len(pipe_data) >= 1
    tracked_entry = next(item for item in pipe_data if item["id"] == app_id)
    assert tracked_entry["status"] == "SAVED"

    # Status Transition: SAVED -> PREPARING
    trans_res = api_client.patch(
        f"/api/v1/applications/{app_id}/status",
        json={"target_status": "PREPARING", "reason": "Preparing tailored resume"},
        headers=local_headers(),
    )
    assert trans_res.status_code == 200
    assert trans_res.json()["status"] == "PREPARING"

    # ---------------------------------------------------------
    # 6. Tailored Material Preparation (Controlled AI Router)
    # ---------------------------------------------------------
    draft_res = api_client.post(
        "/api/v1/ai/generate-draft",
        json={"job_posting_id": job_id},
        headers=local_headers(),
    )
    assert draft_res.status_code == 200
    draft_data = draft_res.json()
    assert "Python" in draft_data["resume_markdown"]
    assert "Acme Corp" in draft_data["resume_markdown"]
    assert "Dear Hiring Team" in draft_data["cover_letter_markdown"]
    assert len(draft_data["addressed_requirements"]) > 0

    # ---------------------------------------------------------
    # 7. Answer Bank Reusable Responses
    # ---------------------------------------------------------
    answer_res = api_client.post(
        "/api/v1/answers",
        json={
            "question": "What is your experience with asynchronous pipelines?",
            "answer": "Over 8 years building distributed asynchronous event streams using Python and SQL.",
            "category": "technical",
            "reuse_consent": True,
        },
        headers=local_headers(),
    )
    assert answer_res.status_code == 201
    answer_id = answer_res.json()["id"]

    # AI Answering query using Answer Bank
    q_res = api_client.post(
        "/api/v1/ai/answer-question",
        json={"question": "What is your experience with asynchronous pipelines?"},
        headers=local_headers(),
    )
    assert q_res.status_code == 200
    q_data = q_res.json()
    assert "asynchronous" in q_data["answer"].lower()

    # ---------------------------------------------------------
    # 8. Submission Plan & ATS Dry-Run Simulation
    # ---------------------------------------------------------
    plan_res = api_client.post(
        f"/api/v1/applications/{app_id}/submission-plan",
        json={
            "resume_markdown": draft_data["resume_markdown"],
            "cover_letter_markdown": draft_data["cover_letter_markdown"],
            "form_answers": {"question_1": "Authorized to work"},
        },
        headers=local_headers(),
    )
    assert plan_res.status_code == 200
    plan_data = plan_res.json()
    assert plan_data["application_id"] == app_id
    assert len(plan_data["packet_sha256"]) == 64

    # Run dry-run simulation (offline safe mock adapter)
    sim_res = api_client.post(
        f"/api/v1/applications/{app_id}/simulate-submission",
        json={"mode": "SUCCESS"},
        headers=local_headers(),
    )
    assert sim_res.status_code == 200
    sim_data = sim_res.json()
    assert sim_data["success"] is True
    assert sim_data["receipt_id"] is not None
    assert sim_data["application_status"] == "READY_FOR_REVIEW"

    # ---------------------------------------------------------
    # 9. Manual Handoff Packet Generation
    # ---------------------------------------------------------
    handoff_res = api_client.get(f"/api/v1/applications/{app_id}/handoff")
    assert handoff_res.status_code == 200
    handoff_data = handoff_res.json()
    assert handoff_data["application_id"] == app_id
    assert "resume_markdown" in handoff_data
    assert "cover_letter_markdown" in handoff_data
    assert "instructions" in handoff_data

    # ---------------------------------------------------------
    # 10. Search Policy Settings & Source Registry
    # ---------------------------------------------------------
    put_set_res = api_client.put(
        "/api/v1/settings",
        json={
            "minimum_compensation": {"amount": "120000.00"},
            "daily_application_cap": 10,
            "same_company_cooldown_days": 60,
            "target_roles": ["Staff Engineer", "Distributed Systems Engineer"],
            "target_locations": ["Remote", "San Francisco"],
            "workplace_arrangements": ["remote"],
            "sponsorship_requirement": "not_required",
        },
        headers=local_headers(),
    )
    assert put_set_res.status_code == 200
    set_data = put_set_res.json()
    assert set_data["daily_application_cap"] == 10
    assert set_data["minimum_compensation"]["amount"] == "120000.00"

    # Source registry toggle
    patch_src_res = api_client.patch(
        "/api/v1/sources/synthetic_fixtures",
        json={"is_enabled": True},
        headers=local_headers(),
    )
    assert patch_src_res.status_code == 200
    assert patch_src_res.json()["is_enabled"] is True

    # ---------------------------------------------------------
    # 11. Data Portability Export, Preview, & Restore
    # ---------------------------------------------------------
    export_res = api_client.post("/api/v1/data/export", headers=local_headers())
    assert export_res.status_code == 200
    bundle = export_res.json()
    assert "manifest" in bundle
    assert bundle["manifest"]["format_version"] == "hire-steward-export-v1"
    assert bundle["candidate_profile"]["name"] == "Jane Doe"
    assert len(bundle["answer_bank_items"]) >= 1

    # Preview import
    prev_res = api_client.post(
        "/api/v1/data/import/preview",
        json=bundle,
        headers=local_headers(),
    )
    assert prev_res.status_code == 200
    prev_data = prev_res.json()
    assert prev_data["checksum_verified"] is True
    assert prev_data["collision_counts"]["candidate_profile"] == 1

    # Commit restore
    commit_res = api_client.post(
        "/api/v1/data/import/commit",
        json={"bundle": bundle, "overwrite_existing": True},
        headers=local_headers(),
    )
    assert commit_res.status_code == 200, commit_res.text
    commit_data = commit_res.json()
    assert commit_data["status"] == "COMPLETED"
    assert commit_data["restored_counts"]["candidate_profile"] == 1

    # ---------------------------------------------------------
    # 12. System Activity & Audit Trail
    # ---------------------------------------------------------
    act_res = api_client.get("/api/v1/system/activity?limit=20")
    assert act_res.status_code == 200
    acts = act_res.json()
    assert len(acts) > 0
    # Confirm activity records state transition
    transition_events = [a for a in acts if a["type"] == "APPLICATION_STATUS_CHANGE"]
    assert len(transition_events) >= 1
