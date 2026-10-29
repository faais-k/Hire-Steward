"""Unit tests for user-controlled job intake without live source activation."""

import hashlib
import socket
from unittest.mock import patch
import pydantic
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from alembic import command
from alembic.config import Config

from backend.app.db.models import (
    Base,
    CandidateFact,
    EmployerSubscription,
    JobPosting,
    JobPostingSnapshot,
    JobSource,
)
from backend.app.domain.job_posting import (
    DuplicateJobPostingError,
    InvalidJobIntakeError,
    SourceCapabilityStatus,
    SourceNotApprovedError,
    UserJobIntake,
    extract_sections_from_plain_text,
    validate_reference_url,
)
from backend.app.services.job_discovery import (
    create_user_job_intake,
    verify_source_authorization_gate,
)
from backend.app.services.job_matching import evaluate_job_posting_match


@pytest.fixture
def sqlite_session() -> Session:
    """Provides an isolated in-memory SQLite database upgraded via Alembic migrations."""
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    config = Config("backend/alembic.ini")
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_valid_user_job_intake_creates_posting_and_snapshot(sqlite_session: Session) -> None:
    """Verify that valid user job intake creates clean posting and snapshot records."""
    intake = UserJobIntake(
        title="Senior Python Backend Engineer",
        description_plain=(
            "We are looking for a Senior Python Engineer to lead architecture.\n\n"
            "Requirements:\n"
            "- 5+ years of Python experience\n"
            "- Strong experience with FastAPI and PostgreSQL\n\n"
            "Preferred Qualifications:\n"
            "- Experience with Docker and container orchestration"
        ),
        employer_name="Acme Technologies Inc.",
        location="Berlin, Germany",
        workplace_type="remote",
        commitment="Full-time",
        canonical_url="https://acme.example.com/careers/python-lead-123",
    )

    posting, snapshot = create_user_job_intake(sqlite_session, intake)
    sqlite_session.commit()

    # 1. Check JobSource
    source = sqlite_session.get(JobSource, "manual_intake")
    assert source is not None
    assert source.capability_status == SourceCapabilityStatus.MANUAL_ONLY.value
    assert source.is_enabled is False
    assert "User-entered" in (source.terms_review_reference or "")

    # 2. Check EmployerSubscription
    sub = sqlite_session.get(EmployerSubscription, posting.subscription_id)
    assert sub is not None
    assert sub.source_name == "manual_intake"
    assert sub.employer_handle == "acme-technologies-inc"

    # 3. Check JobPosting
    assert posting.id is not None
    assert posting.posting_id.startswith("user_")
    assert posting.lifecycle_status == "ACTIVE"
    assert posting.current_raw_hash == snapshot.source_raw_hash

    # 4. Check JobPostingSnapshot
    assert snapshot.title == "Senior Python Backend Engineer"
    assert snapshot.location == "Berlin, Germany"
    assert snapshot.workplace_type == "remote"
    assert snapshot.commitment == "Full-time"
    assert snapshot.canonical_url == "https://acme.example.com/careers/python-lead-123"
    assert snapshot.publication_date_status == "UNKNOWN"
    assert snapshot.published_at is None
    assert snapshot.additional_plain == "User-entered job intake; unverified by external source."
    assert len(snapshot.lists_json) >= 1

    req_section = next((s for s in snapshot.lists_json if "requirement" in s.get("title", "").lower()), None)
    assert req_section is not None
    assert any("Python" in item for item in req_section["items"])


def test_reference_url_validation_offline_without_network() -> None:
    """Verify that URL validation strictly checks syntax in-memory without network sockets."""
    # Defensively intercept any socket creation attempt
    def disallow_sockets(*args, **kwargs):
        raise AssertionError("Network socket opened during URL validation! Live requests are strictly forbidden.")

    with patch.object(socket, "socket", side_effect=disallow_sockets):
        # Valid URLs
        assert validate_reference_url("https://example.com/jobs/123") == "https://example.com/jobs/123"
        assert validate_reference_url("http://sub.domain.org:8080/path?q=1") == "http://sub.domain.org:8080/path?q=1"
        assert validate_reference_url(None) is None
        assert validate_reference_url("   ") is None

        # Disallowed schemes
        for invalid_scheme in [
            "javascript:alert(1)",
            "data:text/html;base64,PHNjcmlwdD4=",
            "file:///etc/passwd",
            "ftp://ftp.example.com",
            "mailto:jobs@example.com",
        ]:
            with pytest.raises(InvalidJobIntakeError) as exc_info:
                validate_reference_url(invalid_scheme)
            assert exc_info.value.code == "INVALID_URL_SCHEME"

        # Missing hostname / malformed
        for malformed in ["https://", "https:///path", "http://", "not-a-url"]:
            with pytest.raises(InvalidJobIntakeError) as exc_info:
                validate_reference_url(malformed)
            assert exc_info.value.code in {"MISSING_HOSTNAME", "MALFORMED_URL", "INVALID_URL_SCHEME"}

        # Credentials in URL
        with pytest.raises(InvalidJobIntakeError) as exc_info:
            validate_reference_url("https://user:password@example.com/jobs")
        assert exc_info.value.code == "CREDENTIALS_IN_URL"

        # Whitespace / control chars / XSS chars
        with pytest.raises(InvalidJobIntakeError) as exc_info:
            validate_reference_url("https://example.com/jobs<script>")
        assert exc_info.value.code == "INVALID_URL_CHARACTERS"

        # URL length limit
        long_url = "https://example.com/" + "a" * 2040
        with pytest.raises(InvalidJobIntakeError) as exc_info:
            validate_reference_url(long_url)
        assert exc_info.value.code == "URL_TOO_LONG"


def test_validation_boundaries_and_error_handling() -> None:
    """Verify input validation rules for title, description, workplace_type, and lengths."""
    # 1. Missing or whitespace title
    with pytest.raises((InvalidJobIntakeError, pydantic.ValidationError)):
        UserJobIntake(title="", description_plain="Valid description exceeding 20 characters length.")

    with pytest.raises((InvalidJobIntakeError, pydantic.ValidationError)):
        UserJobIntake(title="   ", description_plain="Valid description exceeding 20 characters length.")

    # 2. Description too short (< 20 characters)
    with pytest.raises((InvalidJobIntakeError, pydantic.ValidationError)):
        UserJobIntake(title="Engineer", description_plain="Too short")

    # 3. Description too large (> 50,000 characters)
    large_desc = "A" * 50001
    with pytest.raises((InvalidJobIntakeError, pydantic.ValidationError)):
        UserJobIntake(title="Engineer", description_plain=large_desc)

    # 4. Invalid workplace_type
    with pytest.raises((InvalidJobIntakeError, pydantic.ValidationError)):
        UserJobIntake(
            title="Engineer",
            description_plain="Valid description exceeding 20 characters length.",
            workplace_type="anywhere_in_the_universe",
        )


def test_duplicate_submission_handling(sqlite_session: Session) -> None:
    """Verify that submitting the identical user job under the same employer raises DuplicateJobPostingError."""
    intake = UserJobIntake(
        title="Frontend Architect",
        description_plain="Design and maintain responsive modern design systems using React and TypeScript.",
        employer_name="Design Systems Corp",
    )

    posting1, _ = create_user_job_intake(sqlite_session, intake)
    sqlite_session.commit()

    # Second submission of identical job
    with pytest.raises(DuplicateJobPostingError) as exc_info:
        create_user_job_intake(sqlite_session, intake)

    assert exc_info.value.code == "DUPLICATE_JOB_POSTING"
    assert exc_info.value.posting_id == posting1.id


def test_extract_sections_from_plain_text() -> None:
    """Verify plain text section and bullet extraction."""
    text = (
        "Role Overview\n"
        "We are looking for a Python developer.\n\n"
        "Requirements:\n"
        "- 3+ years experience with Python\n"
        "* Experience with relational databases\n"
        "• Linux command line knowledge\n\n"
        "Nice to have:\n"
        "1. Docker container experience\n"
        "2. AWS cloud deployment\n"
    )

    sections = extract_sections_from_plain_text(text)
    assert len(sections) == 2
    assert "Requirements" in sections[0]["title"]
    assert len(sections[0]["items"]) == 3
    assert "3+ years experience with Python" in sections[0]["items"]
    assert "Nice to have" in sections[1]["title"]
    assert len(sections[1]["items"]) == 2
    assert "Docker container experience" in sections[1]["items"]


def test_matching_integration_with_empty_and_matching_evidence(sqlite_session: Session) -> None:
    """Verify that a user-entered job integrates with the explainable matching engine."""
    intake = UserJobIntake(
        title="Full Stack Engineer",
        description_plain=(
            "Full stack role.\n\n"
            "Requirements:\n"
            "- Python backend development\n"
            "- PostgreSQL database management\n"
        ),
        employer_name="Startup Inc",
    )
    posting, _ = create_user_job_intake(sqlite_session, intake)
    sqlite_session.commit()

    # Case 1: Empty candidate evidence produces honest INSUFFICIENT_DATA
    assessment_empty = evaluate_job_posting_match(sqlite_session, posting.id)
    assert assessment_empty.fit_tier.value == "INSUFFICIENT_DATA"
    assert assessment_empty.overall_score is None
    assert assessment_empty.scores.required_coverage == 0.0

    # Case 2: Add matching candidate facts
    fact1 = CandidateFact(
        id="fact_py_01",
        fact_type="SKILL",
        value_json={"name": "Python"},
        value_hash=hashlib.sha256(b"Python").hexdigest(),
        verification_state="USER_VERIFIED",
    )
    fact2 = CandidateFact(
        id="fact_pg_02",
        fact_type="SKILL",
        value_json={"name": "PostgreSQL"},
        value_hash=hashlib.sha256(b"PostgreSQL").hexdigest(),
        verification_state="USER_VERIFIED",
    )
    sqlite_session.add_all([fact1, fact2])
    sqlite_session.commit()

    assessment_matched = evaluate_job_posting_match(sqlite_session, posting.id)
    assert assessment_matched.fit_tier.value in {"STRONG_MATCH", "PARTIAL_MATCH"}
    assert assessment_matched.overall_score is not None
    assert assessment_matched.overall_score > 0.0
    assert assessment_matched.scores.required_coverage > 0.0


def test_source_gate_fails_closed_for_manual_intake_discovery(sqlite_session: Session) -> None:
    """Verify that manual_intake source cannot be used as an automated discovery crawler."""
    intake = UserJobIntake(
        title="Test Engineer",
        description_plain="Testing manual intake source gate enforcement and security invariants.",
        employer_name="Gate Test Co",
    )
    create_user_job_intake(sqlite_session, intake)
    sqlite_session.commit()

    # Attempting to verify source gate for automated crawler must fail closed
    with pytest.raises(SourceNotApprovedError):
        verify_source_authorization_gate(sqlite_session, "manual_intake")

def test_employer_handle_normalization_adversarial_inputs(sqlite_session: Session) -> None:
    """Verify that adversarial, symbol-only, leading-underscore employer names produce valid handles."""
    import re

    test_cases = [
        ("_Acme Corp", "acme-corp"),
        ("___", "user-provided"),
        ("!@#$%^", "user-provided"),
        ("---Acme---", "acme"),
        (".hidden.", "hidden"),
        ("123 Distributed Labs", "123-distributed-labs"),
        ("A" * 128, "a" * 128),
        ("", "user-provided"),
        (None, "user-provided"),
    ]

    for raw_emp, expected_prefix in test_cases:
        intake = UserJobIntake(
            title=f"Engineer at {raw_emp}",
            description_plain="Valid description exceeding 20 characters length for testing.",
            employer_name=raw_emp,
        )
        posting, _ = create_user_job_intake(sqlite_session, intake)
        sub = sqlite_session.get(EmployerSubscription, posting.subscription_id)
        assert sub is not None
        # Must conform strictly to PostgreSQL database check constraint ^[a-z0-9][a-z0-9_-]{0,127}$
        assert re.match(r"^[a-z0-9][a-z0-9_-]{0,127}$", sub.employer_handle), f"Handle failed constraint: {sub.employer_handle}"
        assert sub.employer_handle not in {".", ".."}


def test_null_byte_injection_rejected() -> None:
    """Verify that null bytes are strictly rejected across all text fields."""
    with pytest.raises((InvalidJobIntakeError, pydantic.ValidationError)):
        UserJobIntake(title="Senior Engineer\x00Lead", description_plain="Valid description exceeding 20 characters length.")

    with pytest.raises((InvalidJobIntakeError, pydantic.ValidationError)):
        UserJobIntake(title="Senior Engineer", description_plain="Valid description with \x00 null byte inside.")

    with pytest.raises((InvalidJobIntakeError, pydantic.ValidationError)):
        UserJobIntake(title="Senior Engineer", description_plain="Valid description exceeding 20 chars.", employer_name="Acme\x00Corp")


def test_lists_json_adversarial_validation() -> None:
    """Verify lists_json accepts valid sections and ignores or cleans malformed entries."""
    intake = UserJobIntake(
        title="ML Engineer",
        description_plain="Valid description exceeding 20 characters length for testing.",
        lists_json=[
            {"title": "Requirements", "items": ["Python", 123, "   ", "Docker"]},
            "not a dict",
            {"no_items": "key"},
            {"title": "Empty section", "items": []},
        ],
    )
    assert intake.lists_json is not None
    assert len(intake.lists_json) == 1
    assert intake.lists_json[0]["title"] == "Requirements"
    assert "Python" in intake.lists_json[0]["items"]
    assert "123" in intake.lists_json[0]["items"]
    assert "Docker" in intake.lists_json[0]["items"]


def test_untrusted_html_and_script_payloads_preserved_as_plain_text(sqlite_session: Session) -> None:
    """Verify script and HTML payloads are stored as uninterpreted plain text without execution."""
    xss_title = "<script>alert('XSS')</script> Backend Lead"
    xss_desc = "Seeking an engineer who knows <b>Python</b> & <img src=x onerror=alert(1)> and SQL. Requirements:\n- Microservices"
    xss_emp = "<svg onload=alert(1)> Inc"

    intake = UserJobIntake(
        title=xss_title,
        description_plain=xss_desc,
        employer_name=xss_emp,
    )
    posting, snapshot = create_user_job_intake(sqlite_session, intake)
    sqlite_session.commit()

    # Values must be preserved verbatim in storage as literal plain text
    assert snapshot.title == xss_title
    assert snapshot.description_plain == xss_desc
    assert snapshot.description_html is None
    sub = sqlite_session.get(EmployerSubscription, posting.subscription_id)
    assert sub is not None
    assert "<" not in sub.employer_handle
