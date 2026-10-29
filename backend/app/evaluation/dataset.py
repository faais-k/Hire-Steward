"""Dataset loader for offline matching evaluation fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.domain.candidate_evidence import FactType, FactVerificationState
from backend.app.domain.job_matching import (
    CandidateEvidenceItem,
    ConfidenceLevel,
    FitTier,
    ProvenanceReference,
    normalize_confidence_level,
    normalize_fit_tier,
)
from backend.app.evaluation.models import EvaluationCase, ExpectedOutcome

DEFAULT_FIXTURES_DIR = (
    Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "matching_eval"
)


def load_candidate_profiles(
    profiles_path: Path | str | None = None,
) -> dict[str, list[CandidateEvidenceItem]]:
    """Load normalized candidate evidence profiles from fixture file."""
    path = Path(profiles_path) if profiles_path else DEFAULT_FIXTURES_DIR / "candidate_profiles.json"
    with open(path, encoding="utf-8") as f:
        raw_data: dict[str, Any] = json.load(f)

    profiles: dict[str, list[CandidateEvidenceItem]] = {}
    for profile_id, profile_dict in raw_data.items():
        facts_list: list[CandidateEvidenceItem] = []
        for fact_dict in profile_dict.get("facts", []):
            prov_list = [
                ProvenanceReference(
                    provenance_id=p["provenance_id"],
                    document_version_id=p["document_version_id"],
                    byte_start=p["byte_start"],
                    byte_end=p["byte_end"],
                    evidence_hash=p["evidence_hash"],
                    method=p["method"],
                )
                for p in fact_dict.get("provenance", [])
            ]
            facts_list.append(
                CandidateEvidenceItem(
                    fact_id=fact_dict["fact_id"],
                    fact_type=fact_dict["fact_type"],
                    value=fact_dict["value"],
                    verification_state=fact_dict["verification_state"],
                    is_active=fact_dict.get("is_active", True),
                    is_conflicted=fact_dict.get("is_conflicted", False),
                    provenance=prov_list,
                )
            )
        profiles[profile_id] = facts_list

    return profiles


def load_evaluation_cases(
    cases_path: Path | str | None = None,
) -> list[EvaluationCase]:
    """Load evaluation cases from fixture file."""
    path = Path(cases_path) if cases_path else DEFAULT_FIXTURES_DIR / "evaluation_cases.json"
    with open(path, encoding="utf-8") as f:
        raw_cases: list[dict[str, Any]] = json.load(f)

    cases: list[EvaluationCase] = []
    for c in raw_cases:
        exp = c["expected"]
        expected_outcome = ExpectedOutcome(
            expected_required_count=exp["expected_required_count"],
            expected_preferred_count=exp["expected_preferred_count"],
            expected_fit_tier=normalize_fit_tier(exp["expected_fit_tier"]),
            expected_confidence_level=normalize_confidence_level(exp["expected_confidence_level"]),
            expected_required_met=exp["expected_required_met"],
            expected_required_gaps_count=exp["expected_required_gaps_count"],
            expected_gaps_keywords=exp.get("expected_gaps_keywords", []),
            expected_workplace_ok=exp.get("expected_workplace_ok"),
            expected_compensation_ineligible=exp.get("expected_compensation_ineligible", False),
            rationale=exp.get("rationale", ""),
        )
        cases.append(
            EvaluationCase(
                id=c["id"],
                title=c["title"],
                employer_handle=c["employer_handle"],
                workplace_type=c.get("workplace_type"),
                location=c.get("location"),
                candidate_profile_id=c["candidate_profile_id"],
                lists_json=c.get("lists_json"),
                description_plain=c.get("description_plain"),
                expected=expected_outcome,
            )
        )

    return cases


def load_adversarial_cases(
    cases_path: Path | str | None = None,
) -> list[EvaluationCase]:
    """Load post-fix adversarial regression cases from fixture file."""
    path = Path(cases_path) if cases_path else DEFAULT_FIXTURES_DIR / "adversarial_cases.json"
    return load_evaluation_cases(path)


# Backward-compatible alias
load_holdout_cases = load_adversarial_cases
