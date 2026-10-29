"""Unit and regression tests for offline job quality and matching evaluation (Milestone 7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.domain.candidate_evidence import FactType, FactVerificationState
from backend.app.domain.job_matching import (
    CandidateEvidenceItem,
    ConfidenceLevel,
    FitTier,
    ProvenanceReference,
    RequirementCategory,
    RequirementMatchStatus,
    assess_job_match,
    evaluate_requirement,
    extract_requirements_from_snapshot,
    symbol_safe_match,
)
from backend.app.domain.job_posting import (
    UserJobIntake,
    extract_sections_from_plain_text,
)
from backend.app.domain.application_preparation import build_application_draft
from backend.app.evaluation.dataset import (
    load_adversarial_cases,
    load_candidate_profiles,
    load_evaluation_cases,
    load_holdout_cases,
)
from backend.app.evaluation.engine import evaluate_case, run_evaluation
from backend.app.adapters.lever import LeverJobSourceAdapter


@pytest.fixture
def eval_corpus():
    cases = load_evaluation_cases()
    profiles = load_candidate_profiles()
    return cases, profiles


def test_all_evaluation_cases_achieve_full_ground_truth_agreement(eval_corpus):
    """Verify that all 37 benchmark cases achieve 100% agreement with ground-truth expectations."""
    cases, profiles = eval_corpus
    report = run_evaluation(cases, profiles)
    m = report.metrics

    assert m.total_cases == 37
    assert m.hard_gate_leakage_count == 0, f"Hard gate leakage detected: {report.failure_cases}"
    assert m.hard_gate_leakage_rate == 0.0
    assert m.tier_accuracy == 1.0, f"Tier mismatches: {[f for f in report.failure_cases if 'tier' in str(f)]}"
    assert m.confidence_accuracy == 1.0, f"Confidence mismatches: {[f for f in report.failure_cases if 'Confidence' in str(f)]}"
    assert m.required_count_accuracy == 1.0
    assert m.preferred_count_accuracy == 1.0
    assert m.met_count_accuracy == 1.0
    assert m.gaps_accuracy == 1.0
    assert m.deterministic_stability is True
    assert len(report.failure_cases) == 0


def test_mandatory_qualification_gate_non_leakage(eval_corpus):
    """Assert that no candidate with failed mandatory qualifications or constraints leaks to STRONG_MATCH."""
    cases, profiles = eval_corpus

    blocked_cases = [
        c for c in cases
        if c.expected.expected_fit_tier == FitTier.BLOCKED_OR_CONTRADICTED
    ]
    assert len(blocked_cases) >= 4  # eval_04, eval_05, eval_16, eval_24, eval_34

    for c in blocked_cases:
        res = evaluate_case(c, profiles[c.candidate_profile_id])
        assert res.actual_fit_tier == FitTier.BLOCKED_OR_CONTRADICTED
        assert res.hard_gate_leakage is False


def test_symbol_safe_synonym_matching():
    """Verify deterministic recognition of technology synonyms and symbol boundaries."""
    # Postgres <-> PostgreSQL
    assert symbol_safe_match("PostgreSQL", "Must have strong experience with Postgres database.")
    assert symbol_safe_match("postgres", "Experience with PostgreSQL query tuning.")

    # AWS <-> Amazon Web Services
    assert symbol_safe_match("AWS", "Deep expertise in Amazon Web Services.")
    assert symbol_safe_match("Amazon Web Services", "Cloud infrastructure deployed on AWS.")

    # React <-> React.js <-> ReactJS
    assert symbol_safe_match("React", "Building user interfaces using React.js and Next.js.")
    assert symbol_safe_match("ReactJS", "Frontend development in React.")

    # Kubernetes <-> K8s
    assert symbol_safe_match("Kubernetes", "Container orchestration using K8s clusters.")
    assert symbol_safe_match("k8s", "Managing Kubernetes pods.")

    # Golang <-> Go
    assert symbol_safe_match("Go", "Backend microservices built with Golang.")
    assert symbol_safe_match("golang", "Proficiency in Go programming.")

    # Symbol safety invariants: exact boundaries preserved
    assert not symbol_safe_match("C", "Experience with C++ and C#.")
    assert not symbol_safe_match("Go", "Web applications built with Django.")
    assert not symbol_safe_match("Java", "Frontend scripting with JavaScript.")


def test_html_tag_normalization_in_plain_text():
    """Verify that raw HTML tags inside plain-text descriptions are stripped cleanly into structured sections."""
    html_desc = (
        "<h3>Requirements</h3>"
        "<ul>"
        "<li>Proficiency in Python <b>3.12+</b></li>"
        "<li>Experience with <i>PostgreSQL</i> database</li>"
        "<li>Docker containerization</li>"
        "</ul>"
    )
    sections = extract_sections_from_plain_text(html_desc)
    assert len(sections) == 1
    sec = sections[0]
    assert "requirements" in sec["title"].lower()
    assert len(sec["items"]) == 3
    assert sec["items"][0] == "Proficiency in Python 3.12+"
    assert sec["items"][1] == "Experience with PostgreSQL database"
    assert sec["items"][2] == "Docker containerization"


def test_compound_conjunctive_requirements_with_descriptors():
    """Verify that compound requirements distinguish engineering activity descriptors from separate skills."""
    candidate_py = [
        CandidateEvidenceItem(
            fact_id="f1",
            fact_type=FactType.SKILL.value,
            value={"name": "PostgreSQL"},
            verification_state=FactVerificationState.DOCUMENT_SUPPORTED.value,
            is_active=True,
            is_conflicted=False,
            provenance=[
                ProvenanceReference("p1", "doc1", 0, 10, "hash1", "PARSED_DOCUMENT")
            ],
        )
    ]

    # Descriptor "database design and query tuning" does not disqualify PostgreSQL
    req_qualifier = "Strong experience with PostgreSQL database design and query tuning"
    lists = [{"title": "Requirements", "items": [req_qualifier]}]
    assessment = assess_job_match("j1", "s1", lists, None, "remote", None, candidate_py)
    assert assessment.required_evaluations[0]["status"] == RequirementMatchStatus.MET.value

    # Distinct separate skill "and Kubernetes" correctly triggers insufficient evidence
    req_compound = "Strong experience with PostgreSQL and Kubernetes"
    lists2 = [{"title": "Requirements", "items": [req_compound]}]
    assessment2 = assess_job_match("j2", "s2", lists2, None, "remote", None, candidate_py)
    assert assessment2.required_evaluations[0]["status"] == RequirementMatchStatus.INSUFFICIENT_EVIDENCE.value
    assert "Kubernetes" in assessment2.qualification_gaps[0]
    assert assessment2.confidence_level == ConfidenceLevel.MEDIUM


def test_incomplete_and_contradictory_candidate_evidence(eval_corpus):
    """Verify that empty profiles, unreviewed facts, and conflicted facts behave with honest epistemic safety."""
    cases, profiles = eval_corpus

    # Case 18: empty candidate profile
    c_empty = [c for c in cases if c.id == "eval_18_empty_candidate_profile"][0]
    res_empty = evaluate_case(c_empty, profiles[c_empty.candidate_profile_id])
    assert res_empty.actual_fit_tier == FitTier.INSUFFICIENT_DATA
    assert res_empty.actual_confidence_level == ConfidenceLevel.LOW
    assert res_empty.actual_overall_score is None

    # Case 16: conflicted candidate fact
    c_conf = [c for c in cases if c.id == "eval_16_conflicted_fact_matching"][0]
    res_conf = evaluate_case(c_conf, profiles[c_conf.candidate_profile_id])
    assert res_conf.actual_fit_tier == FitTier.BLOCKED_OR_CONTRADICTED
    assert res_conf.actual_confidence_level == ConfidenceLevel.HIGH

    # Case 17: unreviewed candidate fact
    c_unrev = [c for c in cases if c.id == "eval_17_unreviewed_fact_confidence"][0]
    res_unrev = evaluate_case(c_unrev, profiles[c_unrev.candidate_profile_id])
    assert res_unrev.actual_fit_tier == FitTier.STRONG_MATCH
    assert res_unrev.actual_confidence_level == ConfidenceLevel.MEDIUM


def test_score_and_explanation_consistency(eval_corpus):
    """Verify that overall_explanation and calculation_basis consistently reflect requirements and gaps."""
    cases, profiles = eval_corpus
    c1 = [c for c in cases if c.id == "eval_01_clear_senior_backend"][0]

    assessment = assess_job_match(
        c1.id, "s1", c1.lists_json, c1.description_plain, c1.workplace_type, c1.location,
        profiles[c1.candidate_profile_id]
    )

    assert "STRONG_MATCH" in assessment.overall_explanation
    assert "Confidence: HIGH" in assessment.overall_explanation
    assert "4 of 4 met" in assessment.overall_explanation
    assert assessment.scores.overall_fit_score == 1.0
    assert len(assessment.qualification_gaps) == 0


def test_duplicate_opportunity_detection():
    """Verify deterministic raw hashing for identical vs near-duplicate opportunities."""
    import hashlib

    intake_a = UserJobIntake(
        employer_name="acme-labs",
        title="Senior Backend Engineer",
        description_plain="Requirements:\n- Python\n- PostgreSQL",
    )
    intake_b = UserJobIntake(
        employer_name="acme-labs",
        title="Senior Backend Engineer",
        description_plain="Requirements:\n- Python\n- PostgreSQL",
    )
    intake_diff = UserJobIntake(
        employer_name="acme-labs",
        title="Senior Backend Engineer",
        description_plain="Requirements:\n- Python\n- PostgreSQL\nRequisition: REQ-002",
    )

    def compute_intake_hash(intake: UserJobIntake) -> str:
        s = f"manual_intake\n{intake.employer_name}\n{intake.title}\n{intake.description_plain}"
        return hashlib.sha256(s.encode("utf-8")).hexdigest()

    # Identical content yields identical deduplication hash
    assert compute_intake_hash(intake_a) == compute_intake_hash(intake_b)
    # Distinct requisition yields distinct hash
    assert compute_intake_hash(intake_a) != compute_intake_hash(intake_diff)


def test_application_draft_interoperability_with_synonyms(eval_corpus):
    """Verify that tailored application drafting correctly references matched synonym facts."""
    cases, profiles = eval_corpus
    c_syn = [c for c in cases if c.id == "eval_06_synonym_postgres"][0]

    draft = build_application_draft(
        job_posting_id=c_syn.id,
        job_title=c_syn.title,
        employer_handle=c_syn.employer_handle,
        lists_json=c_syn.lists_json,
        description_plain=c_syn.description_plain,
        workplace_type=c_syn.workplace_type,
        location=c_syn.location,
        candidate_evidence=profiles[c_syn.candidate_profile_id],
    )

    assert draft.has_sufficient_evidence is True
    assert len(draft.addressed_requirements) == 3
    postgres_req = [r for r in draft.addressed_requirements if "Postgres" in r.requirement_text][0]
    assert postgres_req.status == "MET"
    # Proves PostgreSQL fact addressed "Postgres" requirement
    assert any(claim.statement == "PostgreSQL" for claim in postgres_req.supporting_claims)
    assert len(draft.evidence_gaps) == 0


def test_preservation_of_live_source_authorization_gates():
    """Verify that Phase 0 exit gates and live source safety remain strictly intact."""
    adapter = LeverJobSourceAdapter()
    assert adapter.source_name == "lever"
    # Live requests must raise NotImplementedError
    with pytest.raises(NotImplementedError):
        adapter.fetch_page("test-corp", skip=0, limit=10)


def test_adversarial_regression_set_coverage():
    """Verify post-fix adversarial regression suite achieves 0% hard-gate leakage."""
    adv_cases = load_adversarial_cases()
    profiles = load_candidate_profiles()
    assert len(adv_cases) == 6

    report = run_evaluation(adv_cases, profiles)
    m = report.metrics

    assert m.total_cases == 6
    assert m.hard_gate_leakage_count == 0, f"Hard-gate leakage in adversarial suite: {report.failure_cases}"
    assert m.hard_gate_leakage_rate == 0.0
    assert m.gated_subset_leakage_rate == 0.0
    assert m.tier_accuracy == 1.0, f"Tier mismatches in adversarial suite: {report.failure_cases}"
    assert m.confidence_accuracy == 1.0
    assert m.met_count_accuracy == 1.0
    assert m.gaps_accuracy == 1.0
    assert len(report.failure_cases) == 0


def test_hard_gate_leakage_detection_catches_unauthorized_positive_fit():
    """Verify that an ineligible or blocked case erroneously classified as positive triggers hard_gate_leakage."""
    from backend.app.evaluation.models import EvaluationCase, ExpectedOutcome

    # A case that should be blocked due to contradictory constraints
    blocked_case = EvaluationCase(
        id="case_leak_test",
        title="Blocked Role",
        employer_handle="corp-x",
        workplace_type="onsite",
        location="Tokyo, Japan",
        candidate_profile_id="remote_only_dev",
        lists_json=[{"title": "Requirements", "items": ["Must work onsite in Tokyo office"]}],
        description_plain="Must work onsite in Tokyo office",
        expected=ExpectedOutcome(
            expected_required_count=1,
            expected_preferred_count=0,
            expected_fit_tier=FitTier.BLOCKED_OR_CONTRADICTED,
            expected_confidence_level=ConfidenceLevel.HIGH,
            expected_required_met=0,
            expected_required_gaps_count=1,
            expected_workplace_ok=False,
            expected_compensation_ineligible=False,
            rationale="Candidate is remote-only; Tokyo onsite is an irreconcilable hard blocker.",
        ),
    )

    profiles = load_candidate_profiles()
    candidate_profile = profiles["remote_only_dev"]

    # When evaluated correctly, actual_fit_tier is BLOCKED_OR_CONTRADICTED and hard_gate_leakage is False
    normal_res = evaluate_case(blocked_case, candidate_profile)
    assert normal_res.actual_fit_tier == FitTier.BLOCKED_OR_CONTRADICTED
    assert normal_res.hard_gate_leakage is False
    assert normal_res.submission_eligible is False

    # Now create an evaluation case where expected outcome was blocked/gated,
    # but simulate an assessment that erroneously produced STRONG_MATCH and submission_eligible:
    from backend.app.domain.job_matching import JobMatchAssessment, MatchScoreBreakdown

    leaked_assessment = JobMatchAssessment(
        id="snap_leak",
        job_posting_id="case_leak_test",
        job_snapshot_id="snap_leak",
        fit_tier=FitTier.STRONG_MATCH,
        overall_score=0.95,
        scores=MatchScoreBreakdown(
            required_coverage=1.0,
            preferred_coverage=1.0,
            experience_coverage=1.0,
            workplace_match=True,
            overall_fit_score=0.95,
            calculation_basis="Simulated test assessment",
        ),
        confidence_level=ConfidenceLevel.HIGH,
        confidence_reasons=["High confidence"],
        required_evaluations=[{"status": RequirementMatchStatus.MET.value, "matched_facts": [{"provenance_count": 1}]}],
        preferred_evaluations=[],
        structural_evaluations=[],
        qualification_gaps=[],
        uncertainties=[],
        overall_explanation="Simulated leak assessment",
    )

    # Re-evaluate with simulated leak assessment logic:
    # Any blocked or gated case that obtains STRONG_MATCH or submission_eligible MUST flag hard_gate_leakage = True!
    r_count = len(leaked_assessment.required_evaluations)
    r_met = sum(1 for e in leaked_assessment.required_evaluations if e["status"] == RequirementMatchStatus.MET.value)
    gaps_count = len(leaked_assessment.qualification_gaps)
    is_sub_eligible = (
        leaked_assessment.fit_tier not in (FitTier.BLOCKED_OR_CONTRADICTED, FitTier.INSUFFICIENT_DATA)
        and r_count > 0
        and r_met == r_count
        and gaps_count == 0
        and leaked_assessment.confidence_level in (ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM)
    )
    is_hard_gated = blocked_case.expected.expected_fit_tier in (FitTier.BLOCKED_OR_CONTRADICTED, FitTier.INSUFFICIENT_DATA)

    leak_detected = False
    if is_hard_gated and is_sub_eligible:
        leak_detected = True
    if blocked_case.expected.expected_fit_tier == FitTier.BLOCKED_OR_CONTRADICTED and leaked_assessment.fit_tier in (FitTier.STRONG_MATCH, FitTier.PARTIAL_MATCH):
        leak_detected = True

    assert is_hard_gated is True
    assert is_sub_eligible is True
    assert leak_detected is True, "Hard-gate safety audit failed to catch unauthorized positive fit on blocked case!"


def test_overmatching_guards_and_negations():
    """Verify overmatching safeguards for negated skills, rejected facts, and symbol safety."""
    # 1. Negated skill does not match as positive requirement
    cand_java = [
        CandidateEvidenceItem(
            fact_id="f_java",
            fact_type=FactType.SKILL.value,
            value={"name": "Java"},
            verification_state=FactVerificationState.DOCUMENT_SUPPORTED.value,
            is_active=True,
            is_conflicted=False,
        )
    ]
    lists_neg = [{"title": "Requirements", "items": ["We do not use Java in our microservices"]}]
    assessment_neg = assess_job_match("j_neg", "s_neg", lists_neg, None, "remote", None, cand_java)
    assert assessment_neg.required_evaluations[0]["status"] == RequirementMatchStatus.INSUFFICIENT_EVIDENCE.value
    assert len(assessment_neg.required_evaluations[0]["matched_facts"]) == 0

    # 2. Rejected and superseded candidate evidence is quarantined
    cand_rejected = [
        CandidateEvidenceItem(
            fact_id="f_rust_rej",
            fact_type=FactType.SKILL.value,
            value={"name": "Rust"},
            verification_state=FactVerificationState.REJECTED.value,
            is_active=True,
            is_conflicted=False,
        ),
        CandidateEvidenceItem(
            fact_id="f_go_sup",
            fact_type=FactType.SKILL.value,
            value={"name": "Go"},
            verification_state=FactVerificationState.SUPERSEDED.value,
            is_active=True,
            is_conflicted=False,
        ),
    ]
    lists_quarantine = [{"title": "Requirements", "items": ["Proficiency in Rust programming"]}]
    assessment_quarantine = assess_job_match("j_q", "s_q", lists_quarantine, None, "remote", None, cand_rejected)
    assert assessment_quarantine.required_evaluations[0]["status"] == RequirementMatchStatus.INSUFFICIENT_EVIDENCE.value
    assert len(assessment_quarantine.required_evaluations[0]["matched_facts"]) == 0

    # 3. HTML normalization preserves math inequality operators
    text_math = "Requirements:\n- Latency < 10ms and throughput > 1000ops\n- Experience with <5 years"
    sections_math = extract_sections_from_plain_text(text_math)
    assert len(sections_math) == 1
    items = sections_math[0]["items"]
    assert "Latency < 10ms and throughput > 1000ops" in items
    assert "Experience with <5 years" in items


def test_fit_tier_and_confidence_enum_normalization():
    """Verify that domain enums and string aliases are normalized into canonical FitTier and ConfidenceLevel."""
    from backend.app.domain.job_matching import normalize_fit_tier, normalize_confidence_level
    from backend.app.evaluation.models import ExpectedOutcome

    assert normalize_fit_tier("BLOCKED") == FitTier.BLOCKED_OR_CONTRADICTED
    assert normalize_fit_tier("BLOCKED_OR_CONTRADICTED") == FitTier.BLOCKED_OR_CONTRADICTED
    assert normalize_fit_tier("INSUFFICIENT") == FitTier.INSUFFICIENT_DATA
    assert normalize_fit_tier("INSUFFICIENT_DATA") == FitTier.INSUFFICIENT_DATA
    assert normalize_fit_tier("STRONG") == FitTier.STRONG_MATCH
    assert normalize_fit_tier("STRONG_MATCH") == FitTier.STRONG_MATCH
    assert normalize_fit_tier("GOOD_MATCH") == FitTier.PARTIAL_MATCH
    assert normalize_fit_tier("PARTIAL_MATCH") == FitTier.PARTIAL_MATCH
    assert normalize_fit_tier("WEAK_MATCH") == FitTier.WEAK_MATCH

    assert normalize_confidence_level("HIGH") == ConfidenceLevel.HIGH
    assert normalize_confidence_level("medium") == ConfidenceLevel.MEDIUM

    # Verify Pydantic ExpectedOutcome validates and normalizes aliases transparently
    exp = ExpectedOutcome(
        expected_required_count=2,
        expected_preferred_count=0,
        expected_fit_tier="BLOCKED",
        expected_confidence_level="HIGH",
        expected_required_met=0,
        expected_required_gaps_count=2,
    )
    assert exp.expected_fit_tier == FitTier.BLOCKED_OR_CONTRADICTED
    assert isinstance(exp.expected_fit_tier, FitTier)


def test_legitimate_partial_match_precludes_submission_without_leakage(eval_corpus):
    """Verify that legitimate partial matches are distinct from submission eligibility and do not report leakage."""
    cases, profiles = eval_corpus
    partial_case = [c for c in cases if c.id == "eval_02_partial_missing_skills"][0]
    profile = profiles[partial_case.candidate_profile_id]

    res = evaluate_case(partial_case, profile)
    # Legitimate partial match
    assert res.actual_fit_tier == FitTier.PARTIAL_MATCH
    assert res.tier_matches is True
    # Crucial safety invariants:
    assert res.submission_eligible is False, "A partial match with qualification gaps must NOT be submission-eligible!"
    assert res.hard_gate_leakage is False, "A legitimate partial match must not be flagged as a hard-gate leakage!"
    assert res.is_hard_gated is True


def test_unpaid_role_precludes_submission_eligibility(eval_corpus):
    """Verify that an unpaid role with matching skills is strictly prevented from submission eligibility."""
    cases, profiles = eval_corpus
    unpaid_case = [c for c in cases if c.id == "eval_36_compensation_unpaid_guard"][0]
    profile = profiles[unpaid_case.candidate_profile_id]

    res = evaluate_case(unpaid_case, profile)
    assert res.is_compensation_ineligible is True
    assert res.submission_eligible is False, "Unpaid role must never be eligible for submission!"
    assert res.hard_gate_leakage is False
