"""Execution engine for offline job quality and matching evaluation."""

from __future__ import annotations

import subprocess
from uuid import uuid4

from decimal import Decimal

from backend.app.domain.compensation import (
    assess_compensation,
    CompensationEvidence,
    EvidenceVerificationState,
    PayPeriod,
    ReportedCompensationStatus,
)
from backend.app.domain.job_matching import (
    CandidateEvidenceItem,
    ConfidenceLevel,
    FitTier,
    RequirementMatchStatus,
    assess_job_match,
)
from backend.app.domain.job_posting import extract_sections_from_plain_text
from backend.app.evaluation.models import (
    CaseExecutionResult,
    EvaluationBenchmarkMetrics,
    EvaluationCase,
    EvaluationReport,
)


def get_git_head_commit() -> str:
    """Retrieve current Git HEAD commit SHA if available."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return "unknown"


def evaluate_case(
    case: EvaluationCase,
    candidate_evidence: list[CandidateEvidenceItem],
) -> CaseExecutionResult:
    """Evaluate a single job case against candidate evidence and ground truth."""
    lists = case.lists_json
    if lists is None and case.description_plain:
        lists = extract_sections_from_plain_text(case.description_plain)

    assessment = assess_job_match(
        posting_id=case.id,
        snapshot_id=f"snap_{case.id}",
        lists_json=lists,
        description_plain=case.description_plain,
        workplace_type=case.workplace_type,
        location=case.location,
        candidate_evidence=candidate_evidence,
    )

    # Check compensation policy if case indicates unpaid/volunteer
    is_comp_ineligible = False
    if "unpaid" in (case.description_plain or "").lower() or "volunteer" in (case.title or "").lower():
        comp_evidence = CompensationEvidence(
            reported_status=ReportedCompensationStatus.UNPAID,
            verification_state=EvidenceVerificationState.VERIFIED,
            currency="INR",
            period=PayPeriod.YEAR,
            amount=Decimal("0.00"),
        )
        comp_decision = assess_compensation(comp_evidence, minimum_annual=Decimal("100000.00"))
        is_comp_ineligible = comp_decision.outcome == "BLOCKED" or comp_decision.reason_code == "UNPAID_ROLE"

    req_evals = assessment.required_evaluations
    pref_evals = assessment.preferred_evaluations
    r_count = len(req_evals)
    p_count = len(pref_evals)
    r_met = sum(1 for e in req_evals if e["status"] == RequirementMatchStatus.MET.value)
    gaps_count = len(assessment.qualification_gaps)

    # Match validations
    exp = case.expected
    tier_matches = (assessment.fit_tier == exp.expected_fit_tier)
    conf_matches = (assessment.confidence_level == exp.expected_confidence_level)
    req_count_matches = (r_count == exp.expected_required_count)
    pref_count_matches = (p_count == exp.expected_preferred_count)
    met_count_matches = (r_met == exp.expected_required_met)
    gaps_count_matches = (gaps_count == exp.expected_required_gaps_count)

    # Hard-gate and submission eligibility tests:
    # 1. Hard-Gated Case Determination:
    # A case is hard-gated if it has contradictory constraints, missing mandatory requirements,
    # ineligible compensation (unpaid), or insufficient data.
    is_hard_gated = (
        exp.expected_fit_tier in (FitTier.BLOCKED_OR_CONTRADICTED, FitTier.INSUFFICIENT_DATA)
        or exp.expected_required_met < exp.expected_required_count
        or exp.expected_compensation_ineligible
    )

    # 2. Submission Eligibility Gate:
    # In Hire-Steward, a job is eligible for application submission only if:
    # - Compensation is not blocked/ineligible
    # - Job has non-empty requirements
    # - All mandatory requirements are MET (0 gaps, r_met == r_count)
    # - Fit tier is not BLOCKED_OR_CONTRADICTED and not INSUFFICIENT_DATA
    # - Confidence is not LOW or UNKNOWN
    submission_eligible = (
        not is_comp_ineligible
        and assessment.fit_tier not in (FitTier.BLOCKED_OR_CONTRADICTED, FitTier.INSUFFICIENT_DATA)
        and r_count > 0
        and r_met == r_count
        and gaps_count == 0
        and assessment.confidence_level in (ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM)
    )

    # 3. Hard-Gate Leakage Test:
    # Leakage occurs if ANY of the following safety violations occur:
    # a) An ineligible / hard-gated case is deemed submission_eligible.
    # b) A case with failed mandatory qualifications or insufficient data receives STRONG_MATCH.
    # c) A contradictory/blocked constraint case receives a positive fit tier (STRONG_MATCH or PARTIAL_MATCH).
    # d) An unpaid/ineligible role bypasses the compensation policy gate.
    hard_gate_leakage = False
    if is_hard_gated and submission_eligible:
        hard_gate_leakage = True
    if exp.expected_fit_tier == FitTier.BLOCKED_OR_CONTRADICTED and assessment.fit_tier != FitTier.BLOCKED_OR_CONTRADICTED:
        hard_gate_leakage = True
    if exp.expected_fit_tier == FitTier.INSUFFICIENT_DATA and assessment.fit_tier in (FitTier.STRONG_MATCH, FitTier.PARTIAL_MATCH):
        hard_gate_leakage = True
    if exp.expected_required_met < exp.expected_required_count and assessment.fit_tier == FitTier.STRONG_MATCH:
        hard_gate_leakage = True
    if exp.expected_compensation_ineligible and not is_comp_ineligible:
        hard_gate_leakage = True

    # Provenance grounding test:
    # All met requirements must have at least one matched fact with byte span provenance
    provenance_grounded = True
    for e in (req_evals + pref_evals):
        if e["status"] == RequirementMatchStatus.MET.value:
            facts = e.get("matched_facts", [])
            if not facts:
                provenance_grounded = False
            elif any(f.get("provenance_count", 0) == 0 for f in facts):
                # If facts lack provenance, it's ungrounded
                provenance_grounded = False

    failure_reasons: list[str] = []
    if not tier_matches:
        failure_reasons.append(
            f"Fit tier mismatch: actual '{assessment.fit_tier.value}' != expected '{exp.expected_fit_tier.value}'"
        )
    if not conf_matches:
        failure_reasons.append(
            f"Confidence mismatch: actual '{assessment.confidence_level.value}' != expected '{exp.expected_confidence_level.value}'"
        )
    if not req_count_matches:
        failure_reasons.append(
            f"Required count mismatch: actual {r_count} != expected {exp.expected_required_count}"
        )
    if not pref_count_matches:
        failure_reasons.append(
            f"Preferred count mismatch: actual {p_count} != expected {exp.expected_preferred_count}"
        )
    if not met_count_matches:
        failure_reasons.append(
            f"Met required count mismatch: actual {r_met} != expected {exp.expected_required_met}"
        )
    if not gaps_count_matches:
        failure_reasons.append(
            f"Gaps count mismatch: actual {gaps_count} != expected {exp.expected_required_gaps_count}"
        )
    if hard_gate_leakage:
        failure_reasons.append("CRITICAL: Hard gate leakage detected! Ineligible case breached safety or submission gates.")

    return CaseExecutionResult(
        case_id=case.id,
        case_title=case.title,
        candidate_profile_id=case.candidate_profile_id,
        actual_required_count=r_count,
        actual_preferred_count=p_count,
        actual_required_met=r_met,
        actual_fit_tier=assessment.fit_tier,
        actual_overall_score=assessment.overall_score,
        actual_confidence_level=assessment.confidence_level,
        actual_gaps_count=gaps_count,
        actual_gaps=assessment.qualification_gaps,
        actual_workplace_ok=assessment.scores.workplace_match,
        is_compensation_ineligible=is_comp_ineligible,
        tier_matches=tier_matches,
        confidence_matches=conf_matches,
        required_count_matches=req_count_matches,
        preferred_count_matches=pref_count_matches,
        met_count_matches=met_count_matches,
        gaps_count_matches=gaps_count_matches,
        is_hard_gated=is_hard_gated,
        submission_eligible=submission_eligible,
        hard_gate_leakage=hard_gate_leakage,
        provenance_grounded=provenance_grounded,
        failure_reasons=failure_reasons,
    )


def run_evaluation(
    cases: list[EvaluationCase],
    profiles: dict[str, list[CandidateEvidenceItem]],
) -> EvaluationReport:
    """Execute complete evaluation suite across all cases and candidate profiles."""
    results: list[CaseExecutionResult] = []
    failure_cases: list[dict[str, Any]] = []

    for case in cases:
        profile = profiles.get(case.candidate_profile_id, [])
        res = evaluate_case(case, profile)
        results.append(res)
        if res.failure_reasons:
            failure_cases.append(
                {
                    "case_id": case.id,
                    "title": case.title,
                    "candidate_profile": case.candidate_profile_id,
                    "failures": res.failure_reasons,
                    "rationale": case.expected.rationale,
                }
            )

    # Check deterministic stability by running twice and comparing output
    stability = True
    for case in cases[:5]:  # sample 5 cases
        profile = profiles.get(case.candidate_profile_id, [])
        res_a = evaluate_case(case, profile)
        res_b = evaluate_case(case, profile)
        if res_a.actual_overall_score != res_b.actual_overall_score or res_a.actual_fit_tier != res_b.actual_fit_tier:
            stability = False
            break

    total = len(results)
    gated_total = sum(1 for r in results if r.is_hard_gated)
    tier_acc = round(sum(1 for r in results if r.tier_matches) / total, 4) if total > 0 else 0.0
    conf_acc = round(sum(1 for r in results if r.confidence_matches) / total, 4) if total > 0 else 0.0
    req_acc = round(sum(1 for r in results if r.required_count_matches) / total, 4) if total > 0 else 0.0
    pref_acc = round(sum(1 for r in results if r.preferred_count_matches) / total, 4) if total > 0 else 0.0
    met_acc = round(sum(1 for r in results if r.met_count_matches) / total, 4) if total > 0 else 0.0
    gaps_acc = round(sum(1 for r in results if r.gaps_count_matches) / total, 4) if total > 0 else 0.0
    leak_count = sum(1 for r in results if r.hard_gate_leakage)
    leak_rate = round(leak_count / total, 4) if total > 0 else 0.0
    gated_leak_rate = round(leak_count / gated_total, 4) if gated_total > 0 else 0.0
    prov_rate = round(sum(1 for r in results if r.provenance_grounded) / total, 4) if total > 0 else 0.0

    metrics = EvaluationBenchmarkMetrics(
        total_cases=total,
        tier_accuracy=tier_acc,
        confidence_accuracy=conf_acc,
        required_count_accuracy=req_acc,
        preferred_count_accuracy=pref_acc,
        met_count_accuracy=met_acc,
        gaps_accuracy=gaps_acc,
        hard_gated_cases_count=gated_total,
        hard_gate_leakage_count=leak_count,
        hard_gate_leakage_rate=leak_rate,
        gated_subset_leakage_rate=gated_leak_rate,
        provenance_grounding_rate=prov_rate,
        deterministic_stability=stability,
    )

    return EvaluationReport(
        report_id=f"rep_{uuid4().hex[:12]}",
        git_head=get_git_head_commit(),
        scoring_version="v1.0.0-deterministic",
        dataset_version="1.0.0-offline-eval",
        metrics=metrics,
        case_results=results,
        failure_cases=failure_cases,
    )
