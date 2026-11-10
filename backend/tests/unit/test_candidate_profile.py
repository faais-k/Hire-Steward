"""Unit tests for Candidate Profile domain, completeness engine, and API routes (Stage 2)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.models import CandidateFact, CandidateProfile
from backend.app.domain.candidate_profile import (
    calculate_profile_completeness,
)
from backend.app.main import create_app
from backend.app.services import candidate_profile as profile_service


def local_headers() -> dict[str, str]:
    return {"host": "localhost", "origin": "http://localhost"}


def test_completeness_scoring_progression() -> None:
    # 1. Empty profile
    empty_report = calculate_profile_completeness({})
    assert empty_report.score == 0.0
    assert empty_report.percentage == 0
    assert len(empty_report.missing_elements) > 3

    # 2. Add Name & Contact
    step1_report = calculate_profile_completeness({
        "name": "Jane Developer",
        "contact_info": {
            "email": "jane@example.com",
            "phone": "+1-555-0199",
            "location": "Bengaluru, India",
        },
    })
    assert step1_report.score == 0.30
    assert step1_report.percentage == 30

    # 3. Add Headline & Summary
    step2_report = calculate_profile_completeness({
        "name": "Jane Developer",
        "headline": "Lead Staff Architect",
        "summary": "Experienced distributed systems and AI systems engineer.",
        "contact_info": {
            "email": "jane@example.com",
            "phone": "+1-555-0199",
        },
    })
    assert step2_report.score == 0.40

    # 4. Add Employment & Education & Skills
    complete_report = calculate_profile_completeness({
        "name": "Jane Developer",
        "headline": "Lead Staff Architect",
        "summary": "Experienced distributed systems and AI systems engineer.",
        "contact_info": {
            "email": "jane@example.com",
            "phone": "+1-555-0199",
            "location": "Bengaluru, India",
        },
        "employment": [
            {"company": "Tech Corp", "role": "Senior Engineer"},
            {"company": "Global Solutions", "role": "Staff Architect"},
        ],
        "education": [
            {"institution": "National University", "degree": "B.Tech Computer Science"},
        ],
        "skills": [
            {"name": "Python"},
            {"name": "PostgreSQL"},
            {"name": "FastAPI"},
            {"name": "Docker"},
            {"name": "Machine Learning"},
        ],
    })
    assert complete_report.score == 1.00
    assert complete_report.percentage == 100
    assert len(complete_report.missing_elements) == 0
    assert len(complete_report.strengths) >= 5


def test_candidate_profile_service_sqlite() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    CandidateProfile.__table__.create(engine)
    session_factory = sessionmaker(bind=engine)
    session: Session = session_factory()

    try:
        # Retrieve initialized singleton
        prof = profile_service.get_or_create_profile(session)
        assert prof.id == "default"
        assert prof.completeness_score == 0.0

        # Update profile
        updated = profile_service.update_profile(
            session,
            {
                "name": "Alex Mercer",
                "headline": "Security Engineer",
                "summary": "Specialist in appsec and offline AI pipelines.",
                "contact_info": {"email": "alex@mercer.dev", "location": "Remote"},
                "employment": [{"company": "SecureNet", "role": "Lead Analyst"}],
                "education": [{"institution": "MIT", "degree": "BS CS"}],
                "skills": [{"name": "Python"}, {"name": "Cryptography"}, {"name": "Linux"}],
            },
        )
        assert updated.name == "Alex Mercer"
        assert updated.completeness_score > 0.70

        # Report matches
        report = profile_service.get_profile_report(session)
        assert report.score == updated.completeness_score
    finally:
        session.close()


def test_candidate_profile_api_endpoints() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    CandidateProfile.__table__.create(engine)
    session_factory = sessionmaker(bind=engine)

    app = create_app(session_factory=session_factory)
    client = TestClient(app)

    # 1. GET profile
    resp = client.get("/api/v1/profile", headers=local_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert "profile" in data
    assert "completeness" in data
    assert data["profile"]["id"] == "default"

    # 2. PUT profile
    update_payload = {
        "name": "Sarah Connor",
        "headline": "Systems Defense Architect",
        "summary": "Resilient systems and autonomous agent protection.",
        "contact_info": {"email": "sarah@resistance.org", "phone": "555-0100"},
        "skills": [{"name": "Python"}, {"name": "Linux"}, {"name": "Hardening"}],
    }
    put_resp = client.put("/api/v1/profile", json=update_payload, headers=local_headers())
    assert put_resp.status_code == 200
    res_data = put_resp.json()
    assert res_data["profile"]["name"] == "Sarah Connor"
    assert res_data["completeness"]["score"] > 0.40

    # 3. POST /api/v1/profile/completeness (stateless assessment)
    assess_resp = client.post("/api/v1/profile/completeness", json={"name": "Only Name"}, headers=local_headers())
    assert assess_resp.status_code == 200
    assert assess_resp.json()["score"] == 0.10

    # 4. POST /api/v1/profile/parse-document
    resume_text = "# Sarah Connor\n\nExperienced Architect.\n\n## Skills\n- Python\n- Rust"
    headers = local_headers()
    headers["x-filename"] = "resume.md"
    parse_resp = client.post(
        "/api/v1/profile/parse-document",
        headers=headers,
        content=resume_text.encode("utf-8"),
    )
    assert parse_resp.status_code == 200
    parsed_json = parse_resp.json()
    assert parsed_json["filename"] == "resume.md"
    assert parsed_json["sections_count"] > 0


def test_candidate_profile_projects_completeness_strength() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    CandidateProfile.__table__.create(engine)
    session_factory = sessionmaker(bind=engine)
    session: Session = session_factory()

    try:
        updated = profile_service.update_profile(
            session,
            {
                "name": "Alex Mercer",
                "headline": "Security Engineer",
                "summary": "Specialist in appsec and offline AI pipelines.",
                "contact_info": {"email": "alex@mercer.dev", "location": "Remote"},
                "employment": [{"company": "SecureNet", "role": "Lead Analyst"}],
                "education": [{"institution": "MIT", "degree": "BS CS"}],
                "skills": [{"name": "Python"}, {"name": "Cryptography"}, {"name": "Linux"}],
                "projects": [
                    {"title": "Autonomous Agent", "role": "Creator", "description": "Local-first agent"},
                    {"title": "Job Search Engine", "role": "Maintainer", "description": "Deterministic matcher"},
                ],
            },
        )
        report = profile_service.get_profile_report(session)
        assert report.score == updated.completeness_score
        assert "2 project(s) recorded" in report.strengths
    finally:
        session.close()


def test_map_fact_skill_populates_name() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    CandidateProfile.__table__.create(engine)
    CandidateFact.__table__.create(engine)
    session_factory = sessionmaker(bind=engine)

    app = create_app(session_factory=session_factory)
    client = TestClient(app)

    # Map fact with section_text and fact_type="SKILL"
    map_resp = client.post(
        "/api/v1/profile/map-fact",
        headers=local_headers(),
        json={
            "fact_type": "SKILL",
            "section_text": "PostgreSQL Database Administration",
        },
    )
    assert map_resp.status_code == 201
    fact_data = map_resp.json()
    assert fact_data["value"]["name"] == "PostgreSQL Database Administration"
    assert fact_data["value"]["text"] == "PostgreSQL Database Administration"
