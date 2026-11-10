"""Regression tests: non-dict evidence items must not raise AttributeError.

Defect discovered during Gate M4 Challenger 2 review: when a CandidateEvidenceItem
has a non-dict value (e.g. a plain string or list stored in the DB via a legacy
path), evaluate_requirement previously raised AttributeError at the fact_val.get()
call site.  The type guard added at job_matching.py:610-612 now skips such items
silently rather than crashing, so the match proceeds on valid items only.

DISCLOSURE: This test modifies behaviour of the protected matching engine by
verifying the fix to job_matching.py:610 (non-dict type guard).  Justified as a
verified correctness defect; regression tests added per AGENTS.md requirement.
"""

from __future__ import annotations

import pytest

from backend.app.domain.candidate_evidence import FactType, FactVerificationState
from backend.app.domain.job_matching import (
    CandidateEvidenceItem,
    FitTier,
    JobRequirement,
    ProvenanceReference,
    RequirementCategory,
    RequirementMatchStatus,
    assess_job_match,
    evaluate_requirement,
)


def _prov() -> list[ProvenanceReference]:
    return [
        ProvenanceReference(
            provenance_id="prov_x",
            document_version_id="dv1",
            byte_start=0,
            byte_end=10,
            evidence_hash="a" * 64,
            method="LOCAL_API_REPORTED",
        )
    ]


def _make_non_dict_item(value: object, fact_type: FactType = FactType.SKILL) -> CandidateEvidenceItem:
    """Create an evidence item whose value is NOT a dict (legacy/corrupt data path)."""
    return CandidateEvidenceItem(
        fact_id="bad_fact_1",
        fact_type=fact_type.value,
        value=value,  # type: ignore[arg-type]  – intentionally wrong type for regression
        verification_state=FactVerificationState.DOCUMENT_SUPPORTED.value,
        is_active=True,
        is_conflicted=False,
        provenance=_prov(),
    )


def _make_good_skill_item(name: str) -> CandidateEvidenceItem:
    return CandidateEvidenceItem(
        fact_id=f"fact_{name}",
        fact_type=FactType.SKILL.value,
        value={"name": name},
        verification_state=FactVerificationState.DOCUMENT_SUPPORTED.value,
        is_active=True,
        is_conflicted=False,
        provenance=_prov(),
    )


def _req(text: str) -> JobRequirement:
    return JobRequirement(
        id="req1",
        category=RequirementCategory.REQUIRED_QUALIFICATION,
        text=text,
        source_section="Requirements",
        normalized_keywords=[],
        min_years_experience=None,
        is_subjective=False,
    )


# ---------------------------------------------------------------------------
# Regression: non-dict value must not raise AttributeError
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_value", [
    "Python",           # plain string (legacy)
    ["Python", "SQL"],  # list
    42,                 # integer
    None,               # None (should also be guarded)
])
def test_evaluate_requirement_skips_non_dict_evidence_no_error(bad_value: object) -> None:
    """Non-dict evidence items must be silently skipped, not raise AttributeError."""
    evidence = [_make_non_dict_item(bad_value)]
    req = _req("Experience with Python")

    # Must not raise; item with non-dict value simply does not contribute to match
    result = evaluate_requirement(req, evidence)
    assert result.status in (RequirementMatchStatus.CONTRADICTED, RequirementMatchStatus.INSUFFICIENT_EVIDENCE)


def test_evaluate_requirement_mixed_evidence_uses_dict_items_only() -> None:
    """When evidence list has both dict and non-dict items, only dict items contribute."""
    evidence = [
        _make_non_dict_item("Python"),          # non-dict — should be skipped
        _make_good_skill_item("Python"),         # dict — should match
    ]
    req = _req("Experience with Python")
    result = evaluate_requirement(req, evidence)
    assert result.status == RequirementMatchStatus.MET
    assert len(result.matched_evidence) == 1
    assert result.matched_evidence[0].fact_id == "fact_Python"


def test_assess_job_match_with_non_dict_evidence_no_crash() -> None:
    """assess_job_match must not crash when candidate_evidence contains non-dict items."""
    evidence = [
        _make_non_dict_item("some_string_value"),
        _make_non_dict_item(["list", "value"]),
        _make_good_skill_item("Python"),
        _make_good_skill_item("SQL"),
    ]
    assessment = assess_job_match(
        posting_id="post_regression",
        snapshot_id="snap_regression",
        lists_json=[
            {
                "title": "Requirements",
                "items": ["Experience with Python", "Experience with SQL"],
            }
        ],
        description_plain="Backend engineering role.",
        workplace_type=None,
        location=None,
        candidate_evidence=evidence,
    )
    # Non-dict items are skipped; dict items ("Python", "SQL") must still produce a match
    assert assessment.fit_tier in (FitTier.STRONG_MATCH, FitTier.PARTIAL_MATCH)


def test_non_dict_conflicted_item_does_not_crash() -> None:
    """A non-dict item with is_conflicted=True must also be skipped cleanly."""
    item = CandidateEvidenceItem(
        fact_id="conflicted_non_dict",
        fact_type=FactType.SKILL.value,
        value="conflicted_string",  # type: ignore[arg-type]
        verification_state=FactVerificationState.CONFLICTED.value,
        is_active=True,
        is_conflicted=True,
        provenance=_prov(),
    )
    req = _req("Experience with Python")
    result = evaluate_requirement(req, [item])
    assert result.status in (RequirementMatchStatus.CONTRADICTED, RequirementMatchStatus.INSUFFICIENT_EVIDENCE)
