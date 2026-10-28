from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_session, require_local_same_origin
from backend.app.api.schemas import (
    CompensationAssessmentInput,
    CompensationAssessmentView,
    CompensationPreferenceView,
    PolicySettingsUpdate,
    PolicySettingsView,
)
from backend.app.db.models import CompensationAssessment, CompensationPreference
from backend.app.domain.compensation import (
    CompensationEvidence,
    EvidenceVerificationState,
    PayPeriod,
    ReportedCompensationStatus,
    assess_compensation,
    validate_money,
)
from backend.app.services.assessments import (
    create_compensation_assessment,
    get_compensation_assessment,
)
from backend.app.services.preferences import (
    get_minimum_compensation,
    set_minimum_compensation,
)


router = APIRouter(prefix="/api/v1")


def preference_view(preference: CompensationPreference) -> CompensationPreferenceView:
    return CompensationPreferenceView(
        amount=f"{preference.amount:.2f}",
        currency=preference.currency,
        period=preference.period,
        version=preference.version,
    )


def assessment_view(assessment: CompensationAssessment) -> CompensationAssessmentView:
    unverified = (
        assessment.evidence_verification_state
        != EvidenceVerificationState.VERIFIED.value
    )
    if unverified:
        decision = assess_compensation(
            CompensationEvidence(
                reported_status=ReportedCompensationStatus(assessment.reported_status),
                verification_state=EvidenceVerificationState.UNVERIFIED,
                currency=assessment.source_currency,
                period=PayPeriod(assessment.source_period),
                amount=assessment.source_amount,
                minimum_amount=assessment.source_minimum,
                maximum_amount=assessment.source_maximum,
                recurring=assessment.source_recurring,
            ),
            assessment.threshold_amount,
        )
        outcome = decision.outcome
        reason_code = decision.reason_code
        explanation = decision.explanation
    else:
        outcome = assessment.outcome
        reason_code = assessment.reason_code
        explanation = assessment.explanation

    return CompensationAssessmentView(
        assessment_id=assessment.id,
        job_reference=assessment.job_reference,
        outcome=outcome,
        reason_code=reason_code,
        explanation=explanation,
        evidence_verification_state=EvidenceVerificationState(
            assessment.evidence_verification_state
        ),
        eligible_to_submit=False,
        minimum_compensation=CompensationPreferenceView(
            amount=f"{assessment.threshold_amount:.2f}",
            currency=assessment.threshold_currency,
            period=assessment.threshold_period,
            version=assessment.threshold_version,
        ),
        reported_status=assessment.reported_status,
        reported_amount=_decimal_string(assessment.source_amount),
        reported_minimum=_decimal_string(assessment.source_minimum),
        reported_maximum=_decimal_string(assessment.source_maximum),
        reported_currency=assessment.source_currency,
        reported_period=assessment.source_period,
        reported_recurring=assessment.source_recurring,
        reported_evidence_reference=assessment.evidence_reference,
        normalized_minimum_annual=(
            None
            if unverified
            else _decimal_string(assessment.normalized_minimum_annual)
        ),
        normalized_maximum_annual=(
            None
            if unverified
            else _decimal_string(assessment.normalized_maximum_annual)
        ),
        conversion_basis=None if unverified else assessment.conversion_basis,
        created_at=_timestamp_string(assessment.created_at),
    )


def _decimal_string(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def _timestamp_string(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@router.get("/settings/policies", response_model=PolicySettingsView)
def read_policy_settings(session: Session = Depends(get_session)) -> PolicySettingsView:
    try:
        preference = get_minimum_compensation(session)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="DATABASE_MIGRATION_REQUIRED") from exc
    return PolicySettingsView(minimum_compensation=preference_view(preference))


@router.patch(
    "/settings/policies",
    response_model=PolicySettingsView,
    dependencies=[Depends(require_local_same_origin)],
)
def update_policy_settings(
    request: PolicySettingsUpdate, session: Session = Depends(get_session)
) -> PolicySettingsView:
    try:
        amount = validate_money(
            request.minimum_compensation.amount,
            field_name="minimum compensation",
        )
        preference = set_minimum_compensation(session, amount)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="DATABASE_MIGRATION_REQUIRED") from exc
    return PolicySettingsView(minimum_compensation=preference_view(preference))


@router.post(
    "/compensation/assessments",
    status_code=status.HTTP_201_CREATED,
    response_model=CompensationAssessmentView,
    dependencies=[Depends(require_local_same_origin)],
)
def assess_job_compensation(
    request: CompensationAssessmentInput,
    session: Session = Depends(get_session),
) -> CompensationAssessmentView:
    try:
        assessment = create_compensation_assessment(session, request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="INVALID_COMPENSATION_EVIDENCE") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="DATABASE_MIGRATION_REQUIRED") from exc
    return assessment_view(assessment)


@router.get(
    "/compensation/assessments/{assessment_id}",
    response_model=CompensationAssessmentView,
)
def read_compensation_assessment(
    assessment_id: str, session: Session = Depends(get_session)
) -> CompensationAssessmentView:
    assessment = get_compensation_assessment(session, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=404, detail="ASSESSMENT_NOT_FOUND")
    return assessment_view(assessment)
