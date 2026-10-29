"""Unit tests for deterministic evidence-grounded application preparation.

Verifies:
1. Zero hallucinations: Every claim traces strictly to candidate evidence.
2. Exclusions: REJECTED and SUPERSEDED facts are never used.
3. CONFLICTED facts are excluded from positive claims and listed as conflicted.
4. UNREVIEWED facts carry verification notices.
5. Missing evidence is never asserted as proof of lacking a skill.
6. Empty candidate evidence profile honestly returns has_sufficient_evidence=False.
7. Service layer integration with JobPosting and JobPostingSnapshot.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from alembic import command
from alembic.config import Config

from backend.app.db.models import (
    CandidateDocument,
    CandidateDocumentBlob,
    CandidateDocumentVersion,
    CandidateFact,
    CandidateFactEvidence,
    DiscoveryCheckpoint,
    DiscoveryRun,
    EmployerSubscription,
    JobPosting,
    JobPostingSnapshot,
    JobSource,
)
from backend.app.domain.candidate_evidence import FactType, FactVerificationState
from backend.app.domain.job_matching import (
    CandidateEvidenceItem,
    ProvenanceReference,
)
from backend.app.domain.application_preparation import (
    ApplicationDraft,
    ApplicationPreparationError,
    build_application_draft,
    filter_usable_evidence,
    generate_tailored_cover_letter,
    generate_tailored_resume,
)
from backend.app.services.application_preparation import prepare_application_draft


@pytest.fixture
def sqlite_session() -> Session:
    """In-memory SQLite session with full schema upgraded via Alembic migrations."""
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


def make_evidence_item(
    fact_id: str,
    fact_type: str,
    value: dict,
    verification_state: str = FactVerificationState.DOCUMENT_SUPPORTED.value,
    is_conflicted: bool = False,
    is_active: bool = True,
    provenance: list[ProvenanceReference] | None = None,
) -> CandidateEvidenceItem:
    return CandidateEvidenceItem(
        fact_id=fact_id,
        fact_type=fact_type,
        value=value,
        verification_state=verification_state,
        is_active=is_active,
        is_conflicted=is_conflicted,
        provenance=provenance or [
            ProvenanceReference(
                provenance_id=str(uuid4()),
                document_version_id=str(uuid4()),
                byte_start=0,
                byte_end=50,
                evidence_hash="a" * 64,
                method="EXACT_SPAN",
            )
        ],
    )


def test_filter_usable_evidence_partitions_and_excludes():
    """Confirms REJECTED and SUPERSEDED are excluded, CONFLICTED partitioned, UNREVIEWED flagged."""
    v_doc = make_evidence_item("f1", FactType.SKILL.value, {"name": "Python"}, FactVerificationState.DOCUMENT_SUPPORTED.value)
    v_user = make_evidence_item("f2", FactType.SKILL.value, {"name": "FastAPI"}, FactVerificationState.USER_VERIFIED.value)
    unrev = make_evidence_item("f3", FactType.SKILL.value, {"name": "Docker"}, FactVerificationState.UNREVIEWED.value)
    conf = make_evidence_item("f4", FactType.SKILL.value, {"name": "AWS"}, FactVerificationState.CONFLICTED.value, is_conflicted=True)
    rej = make_evidence_item("f5", FactType.SKILL.value, {"name": "PHP"}, FactVerificationState.REJECTED.value)
    sup = make_evidence_item("f6", FactType.SKILL.value, {"name": "Java"}, FactVerificationState.SUPERSEDED.value)

    items = [v_doc, v_user, unrev, conf, rej, sup]
    usable, unreviewed, conflicted = filter_usable_evidence(items)

    assert set(e.fact_id for e in usable) == {"f1", "f2", "f3"}
    assert set(e.fact_id for e in unreviewed) == {"f3"}
    assert set(e.fact_id for e in conflicted) == {"f4"}
    # REJECTED and SUPERSEDED not in any returned list
    assert "f5" not in [e.fact_id for e in usable + unreviewed + conflicted]
    assert "f6" not in [e.fact_id for e in usable + unreviewed + conflicted]


def test_build_application_draft_empty_evidence():
    """Empty candidate evidence produces honest has_sufficient_evidence=False with all requirements in gaps."""
    lists_json = [
        {"title": "Requirements", "items": ["Python 3+", "PostgreSQL", "Docker"]},
    ]

    draft = build_application_draft(
        job_posting_id="job_123",
        job_title="Senior Backend Engineer",
        employer_handle="acme-corp",
        lists_json=lists_json,
        description_plain="Senior engineer role.",
        workplace_type="remote",
        location="Remote",
        candidate_evidence=[],
    )

    assert draft.has_sufficient_evidence is False
    assert draft.resume_markdown == ""
    assert draft.cover_letter_markdown == ""
    assert len(draft.addressed_requirements) == 0
    assert len(draft.evidence_gaps) >= 3
    assert "empty" in draft.draft_explanation.lower()
    assert "Truthful Application Invariant" in draft.heuristic_notice


def test_build_application_draft_tailoring_and_traceability():
    """Tailors resume and cover letter with proper requirement matching and gap tracking."""
    py_skill = make_evidence_item(
        "f_py", FactType.SKILL.value, {"name": "Python", "years_experience": 5},
        verification_state=FactVerificationState.DOCUMENT_SUPPORTED.value,
    )
    react_skill = make_evidence_item(
        "f_react", FactType.SKILL.value, {"name": "React", "years_experience": 2},
        verification_state=FactVerificationState.USER_VERIFIED.value,
    )
    unrev_k8s = make_evidence_item(
        "f_k8s", FactType.SKILL.value, {"name": "Kubernetes"},
        verification_state=FactVerificationState.UNREVIEWED.value,
    )
    emp = make_evidence_item(
        "f_emp", FactType.EMPLOYMENT.value,
        {
            "employer": "Tech Labs",
            "title": "Senior Systems Developer",
            "start_date": "2018-01-01",
            "end_date": "2024-05-01",
            "description": "Architected distributed ETL microservices in Python.",
            "skills": ["Python", "Docker"],
        },
    )
    proj = make_evidence_item(
        "f_proj", FactType.PROJECT.value,
        {
            "name": "Pipeline Orchestrator",
            "description": "Autonomous data workflow engine.",
            "technologies": ["Python", "FastAPI"],
        },
    )
    edu = make_evidence_item(
        "f_edu", FactType.EDUCATION.value,
        {
            "credential": "B.Tech Computer Science",
            "institution": "State University",
            "graduation_year": 2020,
        },
    )

    candidate_evidence = [py_skill, react_skill, unrev_k8s, emp, proj, edu]

    lists_json = [
        {"title": "Requirements", "items": ["5+ years of Python experience", "Kubernetes cluster administration", "Rust"]},
    ]

    draft = build_application_draft(
        job_posting_id="job_456",
        job_title="Lead Python Developer",
        employer_handle="globex-tech",
        lists_json=lists_json,
        description_plain="Leading Python backend systems.",
        workplace_type="hybrid",
        location="Boston, MA",
        candidate_evidence=candidate_evidence,
    )

    assert draft.has_sufficient_evidence is True
    assert draft.job_title == "Lead Python Developer"
    assert draft.employer_handle == "globex-tech"

    # Check Addressed Requirements
    addressed_texts = [r.requirement_text for r in draft.addressed_requirements]
    assert any("Python" in t for t in addressed_texts)

    # Check Evidence Gaps: Rust should be an evidence gap
    gap_texts = [g.requirement_text for g in draft.evidence_gaps]
    assert any("Rust" in t for t in gap_texts)
    # Check that gap explanation does not claim candidate is incompetent
    rust_gap = next(g for g in draft.evidence_gaps if "Rust" in g.requirement_text)
    assert "no" in rust_gap.gap_explanation.lower() or "not" in rust_gap.gap_explanation.lower()

    # Check Unreviewed Claims: Kubernetes is unreviewed
    assert any(c.fact_id == "f_k8s" for c in draft.unreviewed_claims)

    # Check Tailored Resume content
    assert "Tech Labs" in draft.resume_markdown
    assert "Senior Systems Developer" in draft.resume_markdown
    assert "Python" in draft.resume_markdown
    assert "State University" in draft.resume_markdown
    assert "[UNREVIEWED]" in draft.resume_markdown  # Kubernetes flagged

    # Check Tailored Cover Letter content
    assert "globex-tech" in draft.cover_letter_markdown
    assert "Lead Python Developer" in draft.cover_letter_markdown
    assert "Tech Labs" in draft.cover_letter_markdown
    assert "Pipeline Orchestrator" in draft.cover_letter_markdown
    # Honest gap mention in cover letter
    assert "Rust" in draft.cover_letter_markdown


def test_build_application_draft_excludes_conflicted_and_rejected():
    """Conflicted facts are not put in positive resume claims; rejected are dropped entirely."""
    conf_skill = make_evidence_item(
        "f_conf", FactType.SKILL.value, {"name": "Go"},
        verification_state=FactVerificationState.CONFLICTED.value,
        is_conflicted=True,
    )
    rej_skill = make_evidence_item(
        "f_rej", FactType.SKILL.value, {"name": "Perl"},
        verification_state=FactVerificationState.REJECTED.value,
    )
    doc_skill = make_evidence_item(
        "f_doc", FactType.SKILL.value, {"name": "Python"},
        verification_state=FactVerificationState.DOCUMENT_SUPPORTED.value,
    )

    draft = build_application_draft(
        job_posting_id="job_789",
        job_title="Software Engineer",
        employer_handle="initech",
        lists_json=[{"title": "Requirements", "items": ["Go", "Python"]}],
        description_plain="Software engineer role.",
        workplace_type="remote",
        location="Remote",
        candidate_evidence=[conf_skill, rej_skill, doc_skill],
    )

    # Go is conflicted, so it must not be in positive resume text
    assert "- **Go**" not in draft.resume_markdown
    assert any(c.fact_id == "f_conf" for c in draft.conflicted_claims)

    # Perl is rejected, so it must be completely excluded
    assert "Perl" not in draft.resume_markdown
    assert not any(c.fact_id == "f_rej" for c in draft.unreviewed_claims + draft.conflicted_claims)


def test_prepare_application_draft_service(sqlite_session: Session):
    """Test full prepare_application_draft service call from DB models."""
    sub = EmployerSubscription(
        id=str(uuid4()),
        source_name="lever_direct",
        employer_handle="stellar-ai",
        display_name="Stellar AI",
        is_enabled=True,
    )
    sqlite_session.add(sub)

    posting = JobPosting(
        id=str(uuid4()),
        subscription_id=sub.id,
        posting_id="stellar-eng-001",
        current_raw_hash="1" * 64,
        lifecycle_status="ACTIVE",
        last_seen_run_id=str(uuid4()),
    )
    sqlite_session.add(posting)

    snapshot = JobPostingSnapshot(
        id=str(uuid4()),
        subscription_id=sub.id,
        posting_id=posting.id,
        run_id=posting.last_seen_run_id,
        source_raw_hash="1" * 64,
        title="Staff ML Platform Engineer",
        location="San Francisco, CA",
        description_plain="Seeking Staff ML Engineer experienced with PyTorch and Ray.",
        lists_json=[
            {"title": "Requirements", "items": ["PyTorch experience", "Kubernetes"]},
        ],
    )
    sqlite_session.add(snapshot)

    # Add candidate fact with evidence
    doc = CandidateDocument(
        id=str(uuid4()),
        display_name="Resume_2026.txt",
        state="ACTIVE",
    )
    sqlite_session.add(doc)

    blob_content = b"Candidate Profile\nSkills: PyTorch, Python, Docker\n"
    blob_hash = hashlib.sha256(blob_content).hexdigest()
    blob = CandidateDocumentBlob(
        content_hash=blob_hash,
        storage_key=f"blobs/{blob_hash}",
        byte_size=len(blob_content),
        media_type="text/plain",
    )
    sqlite_session.add(blob)

    doc_ver = CandidateDocumentVersion(
        id=str(uuid4()),
        document_id=doc.id,
        version_number=1,
        blob_hash=blob.content_hash,
        original_filename="Resume_2026.txt",
    )
    sqlite_session.add(doc_ver)

    fact = CandidateFact(
        id=str(uuid4()),
        fact_type="SKILL",
        value_json={"name": "PyTorch", "years_experience": 4},
        value_hash=hashlib.sha256(b'{"name": "PyTorch", "years_experience": 4}').hexdigest(),
        verification_state="DOCUMENT_SUPPORTED",
    )
    sqlite_session.add(fact)

    ev = CandidateFactEvidence(
        id=str(uuid4()),
        fact_id=fact.id,
        document_version_id=doc_ver.id,
        byte_start=26,
        byte_end=33,
        evidence_hash=blob.content_hash,
        method="EXACT_SPAN",
    )
    sqlite_session.add(ev)

    sqlite_session.commit()

    # Call service
    draft = prepare_application_draft(sqlite_session, posting.id)

    assert draft.has_sufficient_evidence is True
    assert draft.job_title == "Staff ML Platform Engineer"
    assert draft.employer_handle == "stellar-ai"
    assert "PyTorch" in draft.resume_markdown
    assert any("PyTorch" in r.requirement_text for r in draft.addressed_requirements)
    assert any("Kubernetes" in g.requirement_text for g in draft.evidence_gaps)


def test_prepare_application_draft_missing_posting_or_snapshot(sqlite_session: Session):
    """Test 404/not found errors on non-existent posting or snapshot."""
    with pytest.raises(ApplicationPreparationError) as exc_info:
        prepare_application_draft(sqlite_session, "non_existent_id")
    assert exc_info.value.code == "POSTING_NOT_FOUND"

    # Add posting without snapshot
    sub = EmployerSubscription(
        id=str(uuid4()),
        source_name="lever_direct",
        employer_handle="test-employer",
        display_name="Test Employer",
        is_enabled=True,
    )
    sqlite_session.add(sub)
    posting = JobPosting(
        id=str(uuid4()),
        subscription_id=sub.id,
        posting_id="test-post-001",
        current_raw_hash="2" * 64,
        lifecycle_status="ACTIVE",
        last_seen_run_id=str(uuid4()),
    )
    sqlite_session.add(posting)
    sqlite_session.commit()

    with pytest.raises(ApplicationPreparationError) as exc_info2:
        prepare_application_draft(sqlite_session, posting.id)
    assert exc_info2.value.code == "SNAPSHOT_NOT_FOUND"


def test_no_ungrounded_generic_claims_in_cover_letter():
    """Adversarial check: Cover letter must never claim unverified adaptability or accomplishments."""
    py_skill = make_evidence_item(
        "f_py", FactType.SKILL.value, {"name": "Python"},
        verification_state=FactVerificationState.DOCUMENT_SUPPORTED.value,
    )
    emp = make_evidence_item(
        "f_emp", FactType.EMPLOYMENT.value,
        {
            "employer": "Data Corp",
            "title": "Backend Engineer",
            "start_date": "2020-01-01",
        },
    )
    proj = make_evidence_item(
        "f_proj", FactType.PROJECT.value,
        {
            "name": "Sync Engine",
            "technologies": ["Python", "SQLite"],
        },
    )

    draft = build_application_draft(
        job_posting_id="job_999",
        job_title="Senior Python Engineer",
        employer_handle="target-corp",
        lists_json=[{"title": "Requirements", "items": ["Python", "Rust", "Kubernetes"]}],
        description_plain="Senior python engineer role.",
        workplace_type="remote",
        location="Remote",
        candidate_evidence=[py_skill, emp, proj],
    )

    cover = draft.cover_letter_markdown

    # Assert prohibited ungrounded embellishments are absent
    prohibited_phrases = [
        "built and maintained reliable software systems",
        "deliver measurable outcomes",
        "foundation in core engineering principles",
        "complementary technologies",
        "rapidly adapt",
        "approach new challenges methodically",
        "deepen my expertise in these areas",
        "familiarity with these areas",
        "my familiarity",
    ]
    for phrase in prohibited_phrases:
        assert phrase.lower() not in cover.lower(), f"Ungrounded phrase detected in cover letter: {phrase}"

    # Assert honest factual statements are present
    assert "target-corp" in cover
    assert "Data Corp" in cover
    assert "Backend Engineer" in cover
    assert "candidate evidence record does not currently contain documentation" in cover
    assert "how my documented background relates to these requirements" in cover


def test_resume_summary_no_ungrounded_title_default():
    """Adversarial check: Resume summary must not invent 'Software Professional' if no title exists."""
    emp_without_title = make_evidence_item(
        "f_emp2", FactType.EMPLOYMENT.value,
        {
            "employer": "Acme Inc",
            "start_date": "2021-01-01",
        },
    )
    draft = build_application_draft(
        job_posting_id="job_888",
        job_title="Specialist",
        employer_handle="acme-inc",
        lists_json=[{"title": "Requirements", "items": ["Communication"]}],
        description_plain="Specialist role.",
        workplace_type="remote",
        location="Remote",
        candidate_evidence=[emp_without_title],
    )
    assert "Software Professional" not in draft.resume_markdown
    assert "Professional with documented experience at Acme Inc" in draft.resume_markdown
