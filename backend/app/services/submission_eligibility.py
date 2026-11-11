"""Authoritative Submission Eligibility and Deterministic Policy Gating Service.

Normative implementation of:
- ADR-0003: Submission Safety and Reconcilable Intent
- ADR-0005: Configurable Targeting and Policy Controls
- ADR-0006: Hard Compensation Floor
- ADR-0009: Compensation Evidence Trust Boundaries
- ADR-0016: Application Tracking and Pipeline Model
- docs/application-safety-policy.md

Guarantees:
1. Fail-closed: Unknown, missing, or unverified evidence NEVER defaults to eligible.
2. Deterministic: No probabilistic LLM or third-party score can authorize submission.
3. Authoritative: Evaluates persisted candidate preferences, job data, compensation
   assessments, and application history directly from the database system of record.
4. Auditable: Emits explicit reason codes, explanations, and decision metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db.models import (
    CompensationAssessment,
    CompensationPreference,
    EmployerSubscription,
    JobPosting,
    JobPostingSnapshot,
    TrackedApplication,
    UserSettingsModel,
)
from backend.app.domain.application_tracking import ApplicationStatus
from backend.app.domain.compensation import (
    EvidenceVerificationState,
    ReportedCompensationStatus,
)
from backend.app.services.preferences import get_minimum_compensation
from backend.app.services.user_settings import get_user_settings


class EligibilityDecision(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    BLOCKED = "BLOCKED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


@dataclass(frozen=True, slots=True)
class CompensationEligibilityResult:
    outcome: EligibilityDecision
    reason_code: str
    explanation: str
    is_eligible: bool
    requires_review: bool
    threshold_amount: Decimal | None = None
    threshold_currency: str = "INR"
    threshold_period: str = "YEAR"
    normalized_minimum_annual: Decimal | None = None
    evidence_verification_state: str = "UNVERIFIED"
    reported_status: str = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class CooldownEligibilityResult:
    outcome: EligibilityDecision
    reason_code: str
    explanation: str
    is_clear: bool
    requires_review: bool
    cooldown_days: int = 30
    prior_application_id: str | None = None
    days_since_prior: float | None = None
    prior_status: str | None = None


@dataclass(frozen=True, slots=True)
class SubmissionEligibilityReport:
    job_posting_id: str
    overall_decision: EligibilityDecision
    is_compensation_eligible: bool
    is_cooldown_clear: bool
    compensation: CompensationEligibilityResult
    cooldown: CooldownEligibilityResult
    blocking_reasons: list[str] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)

    @property
    def is_fully_eligible(self) -> bool:
        return self.overall_decision == EligibilityDecision.ELIGIBLE


def evaluate_compensation_eligibility(
    session: Session,
    posting: JobPosting,
) -> CompensationEligibilityResult:
    """Evaluate compensation policy deterministically against authoritative persisted state.

    Rules:
    1. A confirmed unpaid job is BLOCKED, regardless of the configured minimum.
    2. Verified compensation below the persisted user minimum is BLOCKED.
    3. Missing or unverified salary evidence is REVIEW_REQUIRED.
    4. Only verified compensation meeting or exceeding the persisted floor is ELIGIBLE.
    5. An LLM or score CANNOT override the decision.
    """
    pref = get_minimum_compensation(session)
    threshold = pref.amount
    currency = pref.currency
    period = pref.period

    # Look up latest compensation assessment for this job reference
    assessment = session.scalar(
        select(CompensationAssessment)
        .where(
            (CompensationAssessment.job_reference == posting.id)
            | (CompensationAssessment.job_reference == posting.posting_id)
        )
        .order_by(CompensationAssessment.created_at.desc())
        .limit(1)
    )

    if assessment is None:
        # Check if job snapshot has explicit unpaid indicators
        snapshot = session.scalar(
            select(JobPostingSnapshot)
            .where(JobPostingSnapshot.posting_id == posting.id)
            .order_by(JobPostingSnapshot.captured_at.desc())
            .limit(1)
        )
        text_content = ""
        if snapshot:
            text_content = f"{snapshot.title} {snapshot.description_plain or ''}".lower()

        if any(marker in text_content for marker in ["unpaid", "volunteer", "no salary", "for college credit only", "0 stipend"]):
            return CompensationEligibilityResult(
                outcome=EligibilityDecision.BLOCKED,
                reason_code="UNPAID_ROLE",
                explanation="Posting text indicates an unpaid position, which is strictly prohibited by policy.",
                is_eligible=False,
                requires_review=False,
                threshold_amount=threshold,
                threshold_currency=currency,
                threshold_period=period,
                reported_status=ReportedCompensationStatus.UNPAID.value,
                evidence_verification_state=EvidenceVerificationState.UNVERIFIED.value,
            )

        return CompensationEligibilityResult(
            outcome=EligibilityDecision.REVIEW_REQUIRED,
            reason_code="NO_VERIFIED_COMPENSATION_ASSESSMENT",
            explanation="No verified compensation assessment exists for this posting. Review required before proceeding.",
            is_eligible=False,
            requires_review=True,
            threshold_amount=threshold,
            threshold_currency=currency,
            threshold_period=period,
            reported_status=ReportedCompensationStatus.UNKNOWN.value,
            evidence_verification_state=EvidenceVerificationState.UNVERIFIED.value,
        )

    # 1. Confirmed unpaid role with verified evidence is strictly BLOCKED
    if assessment.reported_status == ReportedCompensationStatus.UNPAID.value:
        return CompensationEligibilityResult(
            outcome=EligibilityDecision.BLOCKED,
            reason_code="UNPAID_ROLE",
            explanation="Confirmed unpaid role is strictly ineligible under application safety policy.",
            is_eligible=False,
            requires_review=False,
            threshold_amount=threshold,
            threshold_currency=currency,
            threshold_period=period,
            reported_status=assessment.reported_status,
            evidence_verification_state=assessment.evidence_verification_state,
        )

    # 2. Unverified evidence is REVIEW_REQUIRED (cannot authorize submission)
    if assessment.evidence_verification_state != EvidenceVerificationState.VERIFIED.value:
        return CompensationEligibilityResult(
            outcome=EligibilityDecision.REVIEW_REQUIRED,
            reason_code="EVIDENCE_UNVERIFIED",
            explanation="Compensation evidence has not been verified against authoritative documentation.",
            is_eligible=False,
            requires_review=True,
            threshold_amount=threshold,
            threshold_currency=currency,
            threshold_period=period,
            normalized_minimum_annual=assessment.normalized_minimum_annual,
            reported_status=assessment.reported_status,
            evidence_verification_state=assessment.evidence_verification_state,
        )

    # 3. Verified evidence evaluated against persisted floor
    if assessment.outcome == "BLOCKED" or (
        assessment.normalized_minimum_annual is not None and assessment.normalized_minimum_annual < threshold
    ):
        return CompensationEligibilityResult(
            outcome=EligibilityDecision.BLOCKED,
            reason_code="BELOW_MINIMUM_COMPENSATION",
            explanation=f"Verified annual compensation ({assessment.normalized_minimum_annual} {currency}) is below persisted floor ({threshold} {currency}).",
            is_eligible=False,
            requires_review=False,
            threshold_amount=threshold,
            threshold_currency=currency,
            threshold_period=period,
            normalized_minimum_annual=assessment.normalized_minimum_annual,
            reported_status=assessment.reported_status,
            evidence_verification_state=assessment.evidence_verification_state,
        )

    if assessment.outcome in ("MEETS_THRESHOLD", "ELIGIBLE"):
        return CompensationEligibilityResult(
            outcome=EligibilityDecision.ELIGIBLE,
            reason_code="MEETS_THRESHOLD",
            explanation=f"Verified compensation meets or exceeds persisted minimum floor ({threshold} {currency}).",
            is_eligible=True,
            requires_review=False,
            threshold_amount=threshold,
            threshold_currency=currency,
            threshold_period=period,
            normalized_minimum_annual=assessment.normalized_minimum_annual,
            reported_status=assessment.reported_status,
            evidence_verification_state=assessment.evidence_verification_state,
        )

    return CompensationEligibilityResult(
        outcome=EligibilityDecision.REVIEW_REQUIRED,
        reason_code=assessment.reason_code or "COMPENSATION_REVIEW_REQUIRED",
        explanation=assessment.explanation or "Compensation details require candidate review.",
        is_eligible=False,
        requires_review=True,
        threshold_amount=threshold,
        threshold_currency=currency,
        threshold_period=period,
        normalized_minimum_annual=assessment.normalized_minimum_annual,
        reported_status=assessment.reported_status,
        evidence_verification_state=assessment.evidence_verification_state,
    )


def evaluate_same_company_cooldown(
    session: Session,
    posting: JobPosting,
    current_application_id: str | None = None,
    as_of: datetime | None = None,
) -> CooldownEligibilityResult:
    """Evaluate same-company duplicate cooldown against persisted application history.

    Rules:
    1. Checks candidate settings for `same_company_cooldown_days` (default 30 days).
    2. Identifies employer identity via `subscription_id` or `employer_handle`.
    3. Searches for previous applications to the same employer in active pursuit
       (`APPLIED`, `INTERVIEWING`, `OFFER_RECEIVED`).
    4. Previous applications marked `REJECTED` or `WITHDRAWN` do NOT trigger active cooldown.
    5. Applications missing both `applied_at` and `created_at` require review (fail closed).
    6. Timing: elapsed seconds < (cooldown_days * 86400) -> BLOCKED; >= -> ELIGIBLE.
    """
    settings_dict = get_user_settings(session)
    cooldown_days = int(settings_dict.get("same_company_cooldown_days", 30))

    if cooldown_days <= 0:
        return CooldownEligibilityResult(
            outcome=EligibilityDecision.ELIGIBLE,
            reason_code="COOLDOWN_DISABLED",
            explanation="Same-company cooldown is disabled in candidate settings.",
            is_clear=True,
            requires_review=False,
            cooldown_days=0,
        )

    ref_time = as_of or datetime.now(timezone.utc)
    if ref_time.tzinfo is None:
        ref_time = ref_time.replace(tzinfo=timezone.utc)

    # Determine employer handle & subscription IDs
    employer_handle: str | None = None
    sub_ids: list[str] = []

    if posting.subscription_id:
        sub = session.get(EmployerSubscription, posting.subscription_id)
        if sub:
            employer_handle = sub.employer_handle.strip().lower() if sub.employer_handle else None
            sub_ids.append(sub.id)
        else:
            # subscription_id referenced but subscription record not found — unknown employer
            return CooldownEligibilityResult(
                outcome=EligibilityDecision.REVIEW_REQUIRED,
                reason_code="UNKNOWN_EMPLOYER_IDENTITY",
                explanation=(
                    "Cannot verify same-company cooldown: posting references a subscription "
                    "that no longer exists. Candidate review required."
                ),
                is_clear=False,
                requires_review=True,
                cooldown_days=cooldown_days,
            )

    if employer_handle:
        # Normalize: match all subscriptions sharing the same employer handle
        # (case-insensitive, whitespace-stripped for cross-ATS de-duplication)
        normalized = employer_handle.strip().lower()
        matching_subs = session.scalars(
            select(EmployerSubscription.id).where(
                func.lower(EmployerSubscription.employer_handle) == normalized
            )
        ).all()
        sub_ids = list(set(sub_ids) | set(matching_subs))

    if not sub_ids:
        # Standalone posting without an identifiable employer subscription.
        # We cannot verify cooldown, so fail closed per ADR-0003.
        return CooldownEligibilityResult(
            outcome=EligibilityDecision.REVIEW_REQUIRED,
            reason_code="UNKNOWN_EMPLOYER_IDENTITY",
            explanation=(
                "Cannot verify same-company cooldown: the posting has no linked employer "
                "subscription and no identifiable employer handle. Candidate review required."
            ),
            is_clear=False,
            requires_review=True,
            cooldown_days=cooldown_days,
        )

    # Find all posting IDs associated with these employer subscriptions
    matching_posting_ids = session.scalars(
        select(JobPosting.id).where(JobPosting.subscription_id.in_(sub_ids))
    ).all()

    if not matching_posting_ids:
        return CooldownEligibilityResult(
            outcome=EligibilityDecision.ELIGIBLE,
            reason_code="NO_PRIOR_APPLICATIONS",
            explanation="No prior postings found for this employer.",
            is_clear=True,
            requires_review=False,
            cooldown_days=cooldown_days,
        )

    # Query prior applications for this employer
    query = (
        select(TrackedApplication)
        .where(TrackedApplication.job_posting_id.in_(matching_posting_ids))
        .order_by(TrackedApplication.created_at.desc())
    )
    if current_application_id:
        query = query.where(TrackedApplication.id != current_application_id)

    prior_apps = session.scalars(query).all()

    active_statuses = {
        ApplicationStatus.APPLIED.value,
        ApplicationStatus.INTERVIEWING.value,
        ApplicationStatus.OFFER_RECEIVED.value,
        "SUBMITTED",
        "APPLIED",
    }

    for app in prior_apps:
        # Terminal statuses (REJECTED, WITHDRAWN, ARCHIVED, SAVED, PREPARING) do not maintain active cooldown
        if app.status not in active_statuses:
            continue

        if app.applied_at is None:
            return CooldownEligibilityResult(
                outcome=EligibilityDecision.REVIEW_REQUIRED,
                reason_code="MISSING_TIMESTAMP",
                explanation=f"Prior application '{app.id}' lacks applied_at timestamp; cannot verify cooldown.",
                is_clear=False,
                requires_review=True,
                cooldown_days=cooldown_days,
                prior_application_id=app.id,
                prior_status=app.status,
            )

        effective_time = app.applied_at

        if effective_time.tzinfo is None:
            effective_time = effective_time.replace(tzinfo=timezone.utc)

        delta = ref_time - effective_time
        days_elapsed = delta.total_seconds() / 86400.0

        # Boundary check: strictly less than cooldown window is blocked
        if delta.total_seconds() < (cooldown_days * 86400):
            return CooldownEligibilityResult(
                outcome=EligibilityDecision.BLOCKED,
                reason_code="ACTIVE_COOLDOWN",
                explanation=(
                    f"Active cooldown in effect: Applied to this employer {days_elapsed:.1f} days ago "
                    f"(policy requires {cooldown_days} days between applications)."
                ),
                is_clear=False,
                requires_review=False,
                cooldown_days=cooldown_days,
                prior_application_id=app.id,
                days_since_prior=days_elapsed,
                prior_status=app.status,
            )

    return CooldownEligibilityResult(
        outcome=EligibilityDecision.ELIGIBLE,
        reason_code="COOLDOWN_CLEAR",
        explanation=f"No active conflicting applications within {cooldown_days}-day window.",
        is_clear=True,
        requires_review=False,
        cooldown_days=cooldown_days,
    )


def evaluate_submission_eligibility(
    session: Session,
    job_posting_id: str,
    current_application_id: str | None = None,
    as_of: datetime | None = None,
) -> SubmissionEligibilityReport:
    """Authoritative, reusable evaluation of all deterministic submission gates.

    Returns:
    - ELIGIBLE: All gates passed deterministically.
    - BLOCKED: One or more gates definitively failed (unpaid role, below floor, active cooldown).
    - REVIEW_REQUIRED: Missing or unverified evidence requires candidate intervention.
    """
    posting = session.get(JobPosting, job_posting_id)
    if posting is None:
        posting = session.scalar(
            select(JobPosting).where(JobPosting.posting_id == job_posting_id).limit(1)
        )
    if posting is None:
        raise ValueError(f"Job posting '{job_posting_id}' does not exist")

    comp_res = evaluate_compensation_eligibility(session, posting)
    cooldown_res = evaluate_same_company_cooldown(
        session,
        posting,
        current_application_id=current_application_id,
        as_of=as_of,
    )

    blocking_reasons: list[str] = []
    review_reasons: list[str] = []

    if comp_res.outcome == EligibilityDecision.BLOCKED:
        blocking_reasons.append(comp_res.explanation)
    elif comp_res.outcome == EligibilityDecision.REVIEW_REQUIRED:
        review_reasons.append(comp_res.explanation)

    if cooldown_res.outcome == EligibilityDecision.BLOCKED:
        blocking_reasons.append(cooldown_res.explanation)
    elif cooldown_res.outcome == EligibilityDecision.REVIEW_REQUIRED:
        review_reasons.append(cooldown_res.explanation)

    if blocking_reasons:
        overall = EligibilityDecision.BLOCKED
    elif review_reasons:
        overall = EligibilityDecision.REVIEW_REQUIRED
    else:
        overall = EligibilityDecision.ELIGIBLE

    return SubmissionEligibilityReport(
        job_posting_id=posting.id,
        overall_decision=overall,
        is_compensation_eligible=comp_res.is_eligible,
        is_cooldown_clear=cooldown_res.is_clear,
        compensation=comp_res,
        cooldown=cooldown_res,
        blocking_reasons=blocking_reasons,
        review_reasons=review_reasons,
    )
