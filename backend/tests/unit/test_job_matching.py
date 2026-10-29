"""Unit tests for deterministic, evidence-backed job matching and fit explanation."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.models import (
    Base,
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
    ConfidenceLevel,
    FitTier,
    JobRequirement,
    ProvenanceReference,
    RequirementCategory,
    RequirementMatchStatus,
    assess_job_match,
    evaluate_requirement,
    extract_requirements_from_snapshot,
)
from backend.app.services.job_matching import (
    JobMatchingServiceError,
    evaluate_job_posting_match,
    load_candidate_evidence,
)


from alembic import command
from alembic.config import Config


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

    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def make_evidence_item(
    fact_id: str,
    fact_type: FactType,
    value: dict[str, object],
    verification_state: FactVerificationState = FactVerificationState.DOCUMENT_SUPPORTED,
    has_provenance: bool = True,
    is_active: bool = True,
) -> CandidateEvidenceItem:
    prov = []
    if has_provenance:
        prov.append(
            ProvenanceReference(
                provenance_id=f"prov_{fact_id}",
                document_version_id="doc_ver_1",
                byte_start=10,
                byte_end=50,
                evidence_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                method="LOCAL_API_REPORTED",
            )
        )
    return CandidateEvidenceItem(
        fact_id=fact_id,
        fact_type=fact_type.value,
        value=value,
        verification_state=verification_state.value,
        is_active=is_active,
        is_conflicted=(verification_state == FactVerificationState.CONFLICTED),
        provenance=prov,
    )


# --- 1. Strong Evidence-Backed Matches ---

def test_strong_evidence_backed_match() -> None:
    candidate_evidence = [
        make_evidence_item("f1", FactType.SKILL, {"name": "Python"}),
        make_evidence_item("f2", FactType.SKILL, {"name": "PostgreSQL"}),
        make_evidence_item("f3", FactType.EDUCATION, {"credential": "B.Tech", "field_of_study": "Computer Science"}),
        make_evidence_item("f4", FactType.EMPLOYMENT, {"title": "Software Engineer", "start_date": "2019-01-01", "end_date": "2024-01-01"}),
        make_evidence_item("f5", FactType.SKILL, {"name": "Docker"}),
    ]

    job_lists = [
        {
            "title": "Requirements",
            "items": [
                "4+ years of software engineering experience",
                "Proficiency in Python programming",
                "Experience with PostgreSQL",
                "Bachelor's degree in Computer Science",
            ],
        },
        {
            "title": "Preferred Qualifications",
            "items": [
                "Experience with Docker",
            ],
        },
    ]

    assessment = assess_job_match(
        posting_id="post_1",
        snapshot_id="snap_1",
        lists_json=job_lists,
        description_plain=None,
        workplace_type="remote",
        location="Worldwide",
        candidate_evidence=candidate_evidence,
    )

    assert assessment.fit_tier == FitTier.STRONG_MATCH
    assert assessment.confidence_level == ConfidenceLevel.HIGH
    assert assessment.scores.required_coverage == 1.0  # 4/4 met
    assert assessment.scores.preferred_coverage == 1.0  # 1/1 met
    assert assessment.scores.overall_fit_score == 1.0
    assert len(assessment.qualification_gaps) == 0


# --- 2. Partial Matches ---

def test_partial_match_with_insufficient_evidence_gaps() -> None:
    candidate_evidence = [
        make_evidence_item("f1", FactType.SKILL, {"name": "Python"}),
        make_evidence_item("f2", FactType.SKILL, {"name": "PostgreSQL"}),
    ]

    job_lists = [
        {
            "title": "Requirements",
            "items": [
                "Proficiency in Python",
                "Experience with PostgreSQL",
                "Experience with Kubernetes",
                "Experience with Apache Kafka",
            ],
        },
    ]

    assessment = assess_job_match(
        posting_id="post_2",
        snapshot_id="snap_2",
        lists_json=job_lists,
        description_plain=None,
        workplace_type="remote",
        location="Worldwide",
        candidate_evidence=candidate_evidence,
    )

    assert assessment.fit_tier == FitTier.PARTIAL_MATCH
    assert assessment.scores.required_coverage == 0.50  # 2 of 4
    # The 2 missing items must be INSUFFICIENT_EVIDENCE, not CONTRADICTED
    eval_by_text = {e["text"]: e for e in assessment.required_evaluations}
    assert eval_by_text["Proficiency in Python"]["status"] == RequirementMatchStatus.MET.value
    assert eval_by_text["Experience with Kubernetes"]["status"] == RequirementMatchStatus.INSUFFICIENT_EVIDENCE.value
    assert "Missing evidence does not mean the candidate lacks this qualification" in eval_by_text["Experience with Kubernetes"]["explanation"]
    assert eval_by_text["Experience with Apache Kafka"]["status"] == RequirementMatchStatus.INSUFFICIENT_EVIDENCE.value


# --- 3. Missing Required Qualifications ---

def test_missing_required_qualifications_does_not_assume_candidate_incompetence() -> None:
    req = JobRequirement(
        id="req_k8s",
        category=RequirementCategory.REQUIRED_QUALIFICATION,
        text="Hands-on experience with Kubernetes",
        source_section="Requirements",
        normalized_keywords=["kubernetes"],
    )
    candidate_evidence = [
        make_evidence_item("f1", FactType.SKILL, {"name": "Python"}),
    ]

    res = evaluate_requirement(req, candidate_evidence)
    assert res.status == RequirementMatchStatus.INSUFFICIENT_EVIDENCE
    assert res.is_uncertain is True
    assert "No candidate evidence found regarding 'Hands-on experience with Kubernetes'" in res.explanation
    assert "Missing evidence does not mean the candidate lacks this qualification" in res.explanation


# --- 4. Preferred Qualifications Without Required Qualifications ---

def test_preferred_qualifications_without_required_qualifications_is_weak_match() -> None:
    candidate_evidence = [
        make_evidence_item("f1", FactType.SKILL, {"name": "Docker"}),
        make_evidence_item("f2", FactType.SKILL, {"name": "GraphQL"}),
        make_evidence_item("f3", FactType.SKILL, {"name": "Redis"}),
    ]

    job_lists = [
        {
            "title": "Required Qualifications",
            "items": [
                "5+ years of C++ programming experience",
                "Deep experience with embedded Linux systems",
            ],
        },
        {
            "title": "Nice to Have",
            "items": [
                "Experience with Docker",
                "Experience with GraphQL",
                "Experience with Redis",
            ],
        },
    ]

    assessment = assess_job_match(
        posting_id="post_3",
        snapshot_id="snap_3",
        lists_json=job_lists,
        description_plain=None,
        workplace_type="remote",
        location="Worldwide",
        candidate_evidence=candidate_evidence,
    )

    # 100% preferred coverage, but 0% required coverage
    assert assessment.scores.required_coverage == 0.0
    assert assessment.scores.preferred_coverage == 1.0
    # Must be WEAK_MATCH because required qualifications are not met
    assert assessment.fit_tier == FitTier.WEAK_MATCH
    assert "Preferred skills cannot substitute for mandatory requirements" in assessment.overall_explanation


# --- 5. Contradictory and Outdated Evidence ---

def test_contradictory_candidate_fact_state_blocks_requirement() -> None:
    candidate_evidence = [
        make_evidence_item("f1", FactType.SKILL, {"name": "Python"}, verification_state=FactVerificationState.CONFLICTED),
    ]

    req = JobRequirement(
        id="req_py",
        category=RequirementCategory.REQUIRED_QUALIFICATION,
        text="Strong experience in Python",
        source_section="Requirements",
        normalized_keywords=["python"],
    )

    res = evaluate_requirement(req, candidate_evidence)
    assert res.status == RequirementMatchStatus.CONTRADICTED
    assert res.is_uncertain is True
    assert "has CONFLICTED verification state" in res.explanation


def test_workplace_location_conflict_causes_blocked_fit_tier() -> None:
    candidate_evidence = [
        make_evidence_item("f1", FactType.SKILL, {"name": "Python"}),
        make_evidence_item("f2", FactType.PROJECT, {"name": "Remote Only Work Preference", "description": "Strictly remote only, cannot relocate"}),
    ]

    job_lists = [
        {
            "title": "Requirements",
            "items": ["Proficiency in Python"],
        },
    ]

    assessment = assess_job_match(
        posting_id="post_onsite",
        snapshot_id="snap_onsite",
        lists_json=job_lists,
        description_plain=None,
        workplace_type="onsite",
        location="Frankfurt, Germany",
        candidate_evidence=candidate_evidence,
    )

    assert assessment.fit_tier == FitTier.BLOCKED_OR_CONTRADICTED
    assert "Assessment BLOCKED due to direct contradictions or incompatible constraints" in assessment.overall_explanation


def test_superseded_and_rejected_facts_are_ignored() -> None:
    candidate_evidence = [
        make_evidence_item("f_old", FactType.SKILL, {"name": "Python"}, is_active=False),
    ]

    req = JobRequirement(
        id="req_py",
        category=RequirementCategory.REQUIRED_QUALIFICATION,
        text="Proficiency in Python",
        source_section="Requirements",
        normalized_keywords=["python"],
    )

    res = evaluate_requirement(req, candidate_evidence)
    # The inactive fact must not match
    assert res.status == RequirementMatchStatus.INSUFFICIENT_EVIDENCE
    assert len(res.matched_evidence) == 0


def test_insufficient_tenure_contradicts_experience_requirement() -> None:
    candidate_evidence = [
        make_evidence_item("f_emp", FactType.EMPLOYMENT, {"title": "Software Engineer", "start_date": "2023-01-01", "end_date": "2024-01-01"}),
    ]

    req = JobRequirement(
        id="req_exp",
        category=RequirementCategory.EXPERIENCE_REQUIREMENT,
        text="7+ years of software engineering experience",
        source_section="Requirements",
        normalized_keywords=["software", "engineer"],
        min_years_experience=7.0,
    )

    res = evaluate_requirement(req, candidate_evidence)
    assert res.status == RequirementMatchStatus.CONTRADICTED
    assert "Candidate records show 1.0 years non-overlapping experience" in res.explanation
    assert "does not satisfy the required 7.0+ years" in res.explanation


# --- 6. Incomplete Job Descriptions ---

def test_incomplete_job_description_assigns_insufficient_data() -> None:
    candidate_evidence = [
        make_evidence_item("f1", FactType.SKILL, {"name": "Python"}),
    ]

    assessment = assess_job_match(
        posting_id="post_empty",
        snapshot_id="snap_empty",
        lists_json=[],
        description_plain="We are looking for great people to join our passionate company. Apply today!",
        workplace_type=None,
        location=None,
        candidate_evidence=candidate_evidence,
    )

    assert assessment.fit_tier == FitTier.INSUFFICIENT_DATA
    assert assessment.confidence_level == ConfidenceLevel.LOW
    assert "Job description lacks structured requirement sections or lists." in assessment.confidence_reasons
    assert assessment.overall_score is None


# --- 7. Duplicate or Overlapping Requirements ---

def test_duplicate_requirements_are_deduplicated() -> None:
    lists_json = [
        {
            "title": "Requirements",
            "items": [
                "Proficiency in Python",
                "Proficiency in Python",  # exact duplicate
                "proficiency in python",  # casing duplicate
                "Experience with PostgreSQL",
            ],
        },
    ]

    reqs, _, _, _ = extract_requirements_from_snapshot(lists_json, None)
    # Must only contain 2 requirements, not 4
    assert len(reqs) == 2
    texts = [r.text.lower() for r in reqs]
    assert "proficiency in python" in texts
    assert "experience with postgresql" in texts


# --- 8. Unsupported Conclusions and Missing Provenance ---

def test_missing_provenance_and_unreviewed_state_penalizes_confidence() -> None:
    candidate_evidence = [
        # Fact without byte span provenance and with UNREVIEWED state
        make_evidence_item(
            "f1",
            FactType.SKILL,
            {"name": "Python"},
            verification_state=FactVerificationState.UNREVIEWED,
            has_provenance=False,
        ),
    ]

    job_lists = [
        {
            "title": "Requirements",
            "items": ["Experience with Python"],
        },
    ]

    assessment = assess_job_match(
        posting_id="post_unreviewed",
        snapshot_id="snap_unreviewed",
        lists_json=job_lists,
        description_plain=None,
        workplace_type=None,
        location=None,
        candidate_evidence=candidate_evidence,
    )

    assert assessment.fit_tier == FitTier.STRONG_MATCH
    # Confidence drops from HIGH to MEDIUM due to unreviewed and missing provenance
    assert assessment.confidence_level == ConfidenceLevel.MEDIUM
    assert any("UNREVIEWED" in r for r in assessment.confidence_reasons)
    assert any("lack document byte span provenance" in r for r in assessment.confidence_reasons)
    assert assessment.required_evaluations[0]["is_uncertain"] is True
    assert assessment.required_evaluations[0]["provenance_status"] == "MISSING_PROVENANCE"


# --- 9. Deterministic Stability ---

def test_deterministic_stability_across_multiple_runs() -> None:
    candidate_evidence = [
        make_evidence_item("f1", FactType.SKILL, {"name": "Python"}),
        make_evidence_item("f2", FactType.SKILL, {"name": "PostgreSQL"}),
        make_evidence_item("f3", FactType.EDUCATION, {"credential": "B.Tech", "field_of_study": "Computer Science"}),
    ]

    job_lists = [
        {
            "title": "Requirements",
            "items": [
                "Proficiency in Python programming",
                "Hands-on experience with PostgreSQL",
                "Degree in Computer Science",
                "Familiarity with Kubernetes",
            ],
        },
        {
            "title": "Preferred",
            "items": [
                "Experience with Docker",
            ],
        },
    ]

    assessment_1 = assess_job_match("p1", "s1", job_lists, None, "remote", "US", candidate_evidence)
    assessment_2 = assess_job_match("p1", "s1", job_lists, None, "remote", "US", candidate_evidence)

    assert assessment_1.fit_tier == assessment_2.fit_tier
    assert assessment_1.overall_score == assessment_2.overall_score
    assert assessment_1.scores.required_coverage == assessment_2.scores.required_coverage
    assert assessment_1.scores.preferred_coverage == assessment_2.scores.preferred_coverage
    assert assessment_1.confidence_level == assessment_2.confidence_level
    assert assessment_1.overall_explanation == assessment_2.overall_explanation
    assert assessment_1.scores.calculation_basis == assessment_2.scores.calculation_basis


# --- 10. Database Service Integration ---

def test_evaluate_job_posting_match_from_database(sqlite_session: Session) -> None:
    # 1. Setup job source, subscription, run, posting, snapshot
    source = JobSource(
        source_name="fixture_source",
        display_name="Fixture Source",
        capability_status="VERIFIED_READ_ONLY",
        is_enabled=True,
    )
    sqlite_session.add(source)

    sub = EmployerSubscription(
        id=str(uuid4()),
        source_name="fixture_source",
        employer_handle="acme-corp",
        is_enabled=True,
    )
    sqlite_session.add(sub)
    sqlite_session.flush()

    checkpoint = DiscoveryCheckpoint(
        subscription_id=sub.id,
    )
    sqlite_session.add(checkpoint)

    run = DiscoveryRun(
        id=str(uuid4()),
        subscription_id=sub.id,
        status="SUCCEEDED",
        finished_at=datetime.now(timezone.utc),
    )
    sqlite_session.add(run)
    sqlite_session.flush()

    posting = JobPosting(
        id=str(uuid4()),
        subscription_id=sub.id,
        posting_id="acme_backend_dev",
        current_raw_hash="a" * 64,
        lifecycle_status="ACTIVE",
        last_seen_run_id=run.id,
    )
    sqlite_session.add(posting)
    sqlite_session.flush()

    snapshot = JobPostingSnapshot(
        id=str(uuid4()),
        subscription_id=sub.id,
        posting_id=posting.id,
        run_id=run.id,
        source_raw_hash="a" * 64,
        title="Senior Python Backend Developer",
        location="Remote",
        workplace_type="remote",
        description_plain="We are hiring a backend engineer.",
        lists_json=[
            {
                "title": "Requirements",
                "items": [
                    "Strong proficiency in Python",
                    "Experience with PostgreSQL",
                ],
            },
            {
                "title": "Nice to have",
                "items": [
                    "Experience with FastAPI",
                ],
            },
        ],
    )
    sqlite_session.add(snapshot)

    # 2. Setup candidate document, version, facts, provenance
    doc = CandidateDocument(
        id=str(uuid4()),
        display_name="Resume",
        state="ACTIVE",
    )
    sqlite_session.add(doc)
    sqlite_session.flush()

    blob = CandidateDocumentBlob(
        content_hash="b" * 64,
        storage_key="sha256/bb/" + "b" * 64,
        media_type="text/plain",
        byte_size=1024,
    )
    sqlite_session.add(blob)

    doc_ver = CandidateDocumentVersion(
        id=str(uuid4()),
        document_id=doc.id,
        version_number=1,
        blob_hash=blob.content_hash,
        original_filename="resume.txt",
    )
    sqlite_session.add(doc_ver)
    sqlite_session.flush()

    fact_py = CandidateFact(
        id=str(uuid4()),
        fact_type=FactType.SKILL.value,
        value_json={"name": "Python"},
        value_hash="c" * 64,
        verification_state=FactVerificationState.DOCUMENT_SUPPORTED.value,
    )
    fact_pg = CandidateFact(
        id=str(uuid4()),
        fact_type=FactType.SKILL.value,
        value_json={"name": "PostgreSQL"},
        value_hash="d" * 64,
        verification_state=FactVerificationState.USER_VERIFIED.value,
    )
    fact_old = CandidateFact(
        id=str(uuid4()),
        fact_type=FactType.SKILL.value,
        value_json={"name": "OutdatedTech"},
        value_hash="e" * 64,
        verification_state=FactVerificationState.SUPERSEDED.value,
    )
    sqlite_session.add_all([fact_py, fact_pg, fact_old])
    sqlite_session.flush()

    prov_py = CandidateFactEvidence(
        id=str(uuid4()),
        fact_id=fact_py.id,
        document_version_id=doc_ver.id,
        byte_start=10,
        byte_end=30,
        evidence_hash="f" * 64,
        method="LOCAL_API_REPORTED",
    )
    sqlite_session.add(prov_py)
    sqlite_session.commit()

    # 3. Test load_candidate_evidence
    evidence_items = load_candidate_evidence(sqlite_session)
    # OutdatedTech must be filtered out
    item_labels = [item.display_label for item in evidence_items]
    assert "Python" in item_labels
    assert "PostgreSQL" in item_labels
    assert "OutdatedTech" not in item_labels

    py_item = next(i for i in evidence_items if i.display_label == "Python")
    assert len(py_item.provenance) == 1
    assert py_item.provenance[0].document_version_id == doc_ver.id

    # 4. Test evaluate_job_posting_match
    assessment = evaluate_job_posting_match(sqlite_session, posting.id)
    assert assessment.job_posting_id == posting.id
    assert assessment.job_snapshot_id == snapshot.id
    assert assessment.fit_tier == FitTier.STRONG_MATCH
    assert assessment.scores.required_coverage == 1.0  # 2 of 2 met
    assert len(assessment.required_evaluations) == 2


def test_evaluate_job_posting_match_errors_on_missing_posting(sqlite_session: Session) -> None:
    with pytest.raises(JobMatchingServiceError) as exc_info:
        evaluate_job_posting_match(sqlite_session, "non_existent_posting_id")
    assert exc_info.value.code == "POSTING_NOT_FOUND"


# --- 11. Adversarial Symbol-Safe Boundaries (C, C++, C#, Java, JavaScript, .NET) ---

def test_symbol_safe_matching_c_vs_cpp_and_csharp() -> None:
    candidate_c = [make_evidence_item("f1", FactType.SKILL, {"name": "C"})]
    candidate_cpp = [make_evidence_item("f2", FactType.SKILL, {"name": "C++"})]
    candidate_csharp = [make_evidence_item("f3", FactType.SKILL, {"name": "C#"})]
    candidate_java = [make_evidence_item("f4", FactType.SKILL, {"name": "Java"})]
    candidate_dotnet = [make_evidence_item("f5", FactType.SKILL, {"name": ".NET"})]

    req_cpp = JobRequirement(
        id="req_cpp",
        category=RequirementCategory.REQUIRED_QUALIFICATION,
        text="Strong experience in C++ systems programming",
        source_section="Requirements",
        normalized_keywords=["c++", "systems"],
    )
    req_c = JobRequirement(
        id="req_c",
        category=RequirementCategory.REQUIRED_QUALIFICATION,
        text="Proficiency in C programming",
        source_section="Requirements",
        normalized_keywords=["c"],
    )
    req_js = JobRequirement(
        id="req_js",
        category=RequirementCategory.REQUIRED_QUALIFICATION,
        text="Full-stack JavaScript development",
        source_section="Requirements",
        normalized_keywords=["javascript"],
    )
    req_dotnet = JobRequirement(
        id="req_dotnet",
        category=RequirementCategory.REQUIRED_QUALIFICATION,
        text="Backend development with .NET Core",
        source_section="Requirements",
        normalized_keywords=[".net"],
    )

    # 1. Candidate with only "C" must NOT match "C++"
    eval_c_on_cpp = evaluate_requirement(req_cpp, candidate_c)
    assert eval_c_on_cpp.status == RequirementMatchStatus.INSUFFICIENT_EVIDENCE
    assert len(eval_c_on_cpp.matched_evidence) == 0

    # 2. Candidate with "C++" MUST match "C++"
    eval_cpp_on_cpp = evaluate_requirement(req_cpp, candidate_cpp)
    assert eval_cpp_on_cpp.status == RequirementMatchStatus.MET
    assert len(eval_cpp_on_cpp.matched_evidence) == 1

    # 3. Candidate with "C++" must NOT match pure "C"
    eval_cpp_on_c = evaluate_requirement(req_c, candidate_cpp)
    assert eval_cpp_on_c.status == RequirementMatchStatus.INSUFFICIENT_EVIDENCE

    # 4. Candidate with "C#" must NOT match "C" or "C++"
    eval_cs_on_c = evaluate_requirement(req_c, candidate_csharp)
    assert eval_cs_on_c.status == RequirementMatchStatus.INSUFFICIENT_EVIDENCE
    eval_cs_on_cpp = evaluate_requirement(req_cpp, candidate_csharp)
    assert eval_cs_on_cpp.status == RequirementMatchStatus.INSUFFICIENT_EVIDENCE

    # 5. Candidate with "Java" must NOT match "JavaScript"
    eval_java_on_js = evaluate_requirement(req_js, candidate_java)
    assert eval_java_on_js.status == RequirementMatchStatus.INSUFFICIENT_EVIDENCE

    # 6. Candidate with ".NET" matches ".NET Core"
    eval_dotnet = evaluate_requirement(req_dotnet, candidate_dotnet)
    assert eval_dotnet.status == RequirementMatchStatus.MET


# --- 12. Combined Tenure and Skill Requirement ---

def test_combined_tenure_and_skill_requirement_fails_without_skill() -> None:
    # Candidate has 6 years total employment tenure, but skill is Python, not C++
    candidate_evidence = [
        make_evidence_item(
            "f_emp",
            FactType.EMPLOYMENT,
            {"title": "Software Engineer", "start_date": "2018-01-01", "end_date": "2024-01-01"},
        ),
        make_evidence_item("f_py", FactType.SKILL, {"name": "Python"}),
    ]

    req = JobRequirement(
        id="req_cpp_exp",
        category=RequirementCategory.REQUIRED_QUALIFICATION,
        text="5+ years of C++ experience",
        source_section="Requirements",
        normalized_keywords=["c++"],
        min_years_experience=5.0,
    )

    res = evaluate_requirement(req, candidate_evidence)
    # MUST NOT be MET! The candidate has tenure but no C++ skill evidence!
    assert res.status == RequirementMatchStatus.INSUFFICIENT_EVIDENCE
    assert "lacks evidence for required skill/domain in '5+ years of C++ experience'" in res.explanation
    assert "Tenure record: 6.0 years recorded, but required skill has no matching evidence" in res.explanation

    # Now add C++ skill
    candidate_evidence.append(make_evidence_item("f_cpp", FactType.SKILL, {"name": "C++"}))
    res_with_cpp = evaluate_requirement(req, candidate_evidence)
    assert res_with_cpp.status == RequirementMatchStatus.MET
    assert "Met: candidate satisfies both tenure requirement" in res_with_cpp.explanation


# --- 13. Compound Conjunctive ("AND") and Alternative ("OR") Requirements ---

def test_compound_conjunctive_and_requirement_requires_all_skills() -> None:
    # Requirement: "Experience with Python and Kubernetes"
    req = JobRequirement(
        id="req_py_k8s",
        category=RequirementCategory.REQUIRED_QUALIFICATION,
        text="Experience with Python and Kubernetes",
        source_section="Requirements",
        normalized_keywords=["python", "kubernetes"],
    )

    # Candidate only has Python
    candidate_py_only = [
        make_evidence_item("f1", FactType.SKILL, {"name": "Python"}),
    ]

    res_partial = evaluate_requirement(req, candidate_py_only)
    # Must NOT claim MET when candidate only has Python
    assert res_partial.status == RequirementMatchStatus.INSUFFICIENT_EVIDENCE
    assert "Partially evidenced" in res_partial.explanation
    assert "Python" in res_partial.explanation
    assert "Kubernetes" in res_partial.explanation

    # Candidate has both Python and Kubernetes
    candidate_both = [
        make_evidence_item("f1", FactType.SKILL, {"name": "Python"}),
        make_evidence_item("f2", FactType.SKILL, {"name": "Kubernetes"}),
    ]
    res_both = evaluate_requirement(req, candidate_both)
    assert res_both.status == RequirementMatchStatus.MET


def test_compound_alternative_or_requirement_satisfied_by_any_option() -> None:
    req = JobRequirement(
        id="req_db",
        category=RequirementCategory.REQUIRED_QUALIFICATION,
        text="Experience with PostgreSQL or MySQL",
        source_section="Requirements",
        normalized_keywords=["postgresql", "mysql"],
    )

    candidate_pg = [make_evidence_item("f1", FactType.SKILL, {"name": "PostgreSQL"})]
    candidate_mysql = [make_evidence_item("f2", FactType.SKILL, {"name": "MySQL"})]
    candidate_redis = [make_evidence_item("f3", FactType.SKILL, {"name": "Redis"})]

    assert evaluate_requirement(req, candidate_pg).status == RequirementMatchStatus.MET
    assert evaluate_requirement(req, candidate_mysql).status == RequirementMatchStatus.MET
    assert evaluate_requirement(req, candidate_redis).status == RequirementMatchStatus.INSUFFICIENT_EVIDENCE


# --- 14. Overlapping Employment Tenure Merging ---

def test_overlapping_employment_tenure_merging_prevents_double_counting() -> None:
    # Job 1: 2020-01-01 to 2022-01-01 (2.0 years)
    # Job 2: 2021-01-01 to 2023-01-01 (2.0 years)
    # Naive sum = 4.0 years.
    # True non-overlapping duration = 2020-01-01 to 2023-01-01 = 3.0 years.
    candidate_evidence = [
        make_evidence_item(
            "f_job1",
            FactType.EMPLOYMENT,
            {"title": "Consultant", "start_date": "2020-01-01", "end_date": "2022-01-01"},
        ),
        make_evidence_item(
            "f_job2",
            FactType.EMPLOYMENT,
            {"title": "Founder", "start_date": "2021-01-01", "end_date": "2023-01-01"},
        ),
    ]

    # Requirement asks for 3.5+ years of software experience
    req = JobRequirement(
        id="req_exp",
        category=RequirementCategory.EXPERIENCE_REQUIREMENT,
        text="3.5+ years of software engineering experience",
        source_section="Requirements",
        normalized_keywords=["software", "engineering"],
        min_years_experience=3.5,
    )

    res = evaluate_requirement(req, candidate_evidence)
    # If double counted (4.0 years), it would falsely be MET.
    # With non-overlapping merge (3.0 years), it is CONTRADICTED.
    assert res.status == RequirementMatchStatus.CONTRADICTED
    assert "Candidate records show 3.0 years non-overlapping experience" in res.explanation
    assert "does not satisfy the required 3.5+ years" in res.explanation


# --- 15. Subjective / Behavioral Requirements ---

def test_subjective_requirement_reported_as_uncertain() -> None:
    req = JobRequirement(
        id="req_comm",
        category=RequirementCategory.REQUIRED_QUALIFICATION,
        text="Excellent communication and collaborative problem-solving skills",
        source_section="Requirements",
        normalized_keywords=["communication", "collaborative", "problem", "solving"],
        is_subjective=True,
    )
    candidate_evidence = [
        make_evidence_item("f1", FactType.SKILL, {"name": "Python"}),
    ]

    res = evaluate_requirement(req, candidate_evidence)
    assert res.status == RequirementMatchStatus.INSUFFICIENT_EVIDENCE
    assert res.is_uncertain is True
    assert "Subjective or behavioral requirement" in res.explanation
    assert "cannot be verified deterministically" in res.explanation


# --- 16. Strict STRONG_MATCH Invariant: 100% Required Coverage ---

def test_strict_strong_match_requires_all_mandatory_qualifications() -> None:
    # 5 required qualifications, candidate meets 4 (80% coverage) and 1 preferred (100% coverage)
    candidate_evidence = [
        make_evidence_item("f1", FactType.SKILL, {"name": "Python"}),
        make_evidence_item("f2", FactType.SKILL, {"name": "PostgreSQL"}),
        make_evidence_item("f3", FactType.SKILL, {"name": "FastAPI"}),
        make_evidence_item("f4", FactType.SKILL, {"name": "AWS"}),
        make_evidence_item("f5", FactType.SKILL, {"name": "Docker"}),  # preferred
    ]

    job_lists = [
        {
            "title": "Requirements",
            "items": [
                "Proficiency in Python",
                "Experience with PostgreSQL",
                "Experience with FastAPI",
                "Cloud infrastructure experience with AWS",
                "Hands-on production experience with Kubernetes",  # missing!
            ],
        },
        {
            "title": "Nice to have",
            "items": [
                "Containerization with Docker",
            ],
        },
    ]

    assessment = assess_job_match(
        posting_id="post_strict",
        snapshot_id="snap_strict",
        lists_json=job_lists,
        description_plain=None,
        workplace_type="remote",
        location=None,
        candidate_evidence=candidate_evidence,
    )

    # Required coverage is 4/5 = 80%. Overall score is 0.80 * 0.70 + 1.0 * 0.20 + 0.10 = 0.86 (86%).
    # However, because 1 mandatory requirement is missing, FitTier MUST be PARTIAL_MATCH, NOT STRONG_MATCH!
    assert assessment.scores.required_coverage == 0.80
    assert assessment.fit_tier == FitTier.PARTIAL_MATCH
    assert "Candidate evidence satisfies 4 of 5 required qualifications, with 1 requirement(s) lacking evidence. Not a full match." in assessment.overall_explanation


# --- 17. Unspecified Workplace Not Awarded Compatibility Score ---

def test_unspecified_workplace_not_awarded_compatibility_score() -> None:
    candidate_evidence = [
        make_evidence_item("f1", FactType.SKILL, {"name": "Python"}),
    ]
    job_lists = [
        {
            "title": "Requirements",
            "items": ["Proficiency in Python"],
        },
    ]

    # Workplace unspecified
    assessment = assess_job_match(
        posting_id="post_nowork",
        snapshot_id="snap_nowork",
        lists_json=job_lists,
        description_plain=None,
        workplace_type=None,
        location=None,
        candidate_evidence=candidate_evidence,
    )

    # 1/1 required (0.70), 0 preferred (0.20), workplace unspecified (0.00) => total 0.90
    assert assessment.scores.required_coverage == 1.0
    assert assessment.scores.workplace_match is None
    assert assessment.overall_score == 0.90
    assert "Workplace compatibility: Unspecified / Unknown (0% * 10%)" in assessment.scores.calculation_basis
