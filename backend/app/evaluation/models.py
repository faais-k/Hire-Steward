"""Typed schemas and data models for offline matching evaluation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.domain.candidate_evidence import FactType, FactVerificationState
from backend.app.domain.job_matching import (
    CandidateEvidenceItem,
    ConfidenceLevel,
    FitTier,
    ProvenanceReference,
    RequirementCategory,
    RequirementMatchStatus,
    normalize_confidence_level,
    normalize_fit_tier,
)


class ExpectedOutcome(BaseModel):
    """Ground-truth expectation for an evaluation case."""

    model_config = ConfigDict(frozen=True)

    expected_required_count: int
    expected_preferred_count: int
    expected_fit_tier: FitTier
    expected_confidence_level: ConfidenceLevel
    expected_required_met: int
    expected_required_gaps_count: int
    expected_gaps_keywords: list[str] = Field(default_factory=list)
    expected_workplace_ok: bool | None = None
    expected_compensation_ineligible: bool = False
    rationale: str = ""

    @field_validator("expected_fit_tier", mode="before")
    @classmethod
    def _validate_fit_tier(cls, v: Any) -> FitTier:
        return normalize_fit_tier(v)

    @field_validator("expected_confidence_level", mode="before")
    @classmethod
    def _validate_confidence_level(cls, v: Any) -> ConfidenceLevel:
        return normalize_confidence_level(v)


class EvaluationCase(BaseModel):
    """A single evaluation job case."""

    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    employer_handle: str
    workplace_type: str | None = None
    location: str | None = None
    candidate_profile_id: str
    lists_json: list[dict[str, Any]] | None = None
    description_plain: str | None = None
    expected: ExpectedOutcome


class CaseExecutionResult(BaseModel):
    """Result of running a single evaluation case against the matching engine."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    case_title: str
    candidate_profile_id: str

    # Actual measurements
    actual_required_count: int
    actual_preferred_count: int
    actual_required_met: int
    actual_fit_tier: FitTier
    actual_overall_score: float | None
    actual_confidence_level: ConfidenceLevel
    actual_gaps_count: int
    actual_gaps: list[str]
    actual_workplace_ok: bool | None
    is_compensation_ineligible: bool

    # Ground-truth comparison
    tier_matches: bool
    confidence_matches: bool
    required_count_matches: bool
    preferred_count_matches: bool
    met_count_matches: bool
    gaps_count_matches: bool
    is_hard_gated: bool = False
    submission_eligible: bool = False
    hard_gate_leakage: bool
    provenance_grounded: bool
    failure_reasons: list[str] = Field(default_factory=list)

    @field_validator("actual_fit_tier", mode="before")
    @classmethod
    def _validate_actual_tier(cls, v: Any) -> FitTier:
        return normalize_fit_tier(v)

    @field_validator("actual_confidence_level", mode="before")
    @classmethod
    def _validate_actual_confidence(cls, v: Any) -> ConfidenceLevel:
        return normalize_confidence_level(v)


class EvaluationBenchmarkMetrics(BaseModel):
    """Aggregated metrics across the evaluation corpus."""

    model_config = ConfigDict(frozen=True)

    total_cases: int
    tier_accuracy: float
    confidence_accuracy: float
    required_count_accuracy: float
    preferred_count_accuracy: float
    met_count_accuracy: float
    gaps_accuracy: float

    # Hard-gate safety metrics (target 0.0)
    hard_gated_cases_count: int = 0
    hard_gate_leakage_count: int = 0
    hard_gate_leakage_rate: float = 0.0
    gated_subset_leakage_rate: float = 0.0

    # Grounding & explainability metrics (target 100.0%)
    provenance_grounding_rate: float
    deterministic_stability: bool


class EvaluationReport(BaseModel):
    """Full offline benchmark evaluation report."""

    model_config = ConfigDict(frozen=True)

    report_id: str
    run_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    git_head: str
    scoring_version: str = "v1.0.0-deterministic"
    dataset_version: str = "1.0.0-offline-eval"
    metrics: EvaluationBenchmarkMetrics
    case_results: list[CaseExecutionResult]
    failure_cases: list[dict[str, Any]]
