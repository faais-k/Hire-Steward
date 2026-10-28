from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.schemas import CompensationAssessmentInput
from backend.app.db.models import CompensationAssessment
from backend.app.domain.compensation import (
    CompensationEvidence,
    EvidenceVerificationState,
    assess_compensation,
)
from backend.app.services.preferences import get_minimum_compensation


def create_compensation_assessment(
    session: Session, request: CompensationAssessmentInput
) -> CompensationAssessment:
    with session.begin():
        preference = get_minimum_compensation(session, lock=True)
        decision = assess_compensation(
            CompensationEvidence(
                reported_status=request.reported_status,
                verification_state=EvidenceVerificationState.UNVERIFIED,
                currency=request.currency,
                period=request.period,
                amount=request.amount,
                minimum_amount=request.minimum_amount,
                maximum_amount=request.maximum_amount,
                recurring=request.recurring,
            ),
            preference.amount,
        )
        assessment = CompensationAssessment(
            id=str(uuid4()),
            job_reference=request.job_reference,
            reported_status=request.reported_status.value,
            evidence_verification_state=decision.verification_state.value,
            source_amount=request.amount,
            source_minimum=request.minimum_amount,
            source_maximum=request.maximum_amount,
            source_currency=request.currency,
            source_period=request.period.value,
            source_recurring=request.recurring,
            evidence_reference=request.evidence_reference,
            threshold_amount=preference.amount,
            threshold_currency=preference.currency,
            threshold_period=preference.period,
            threshold_version=preference.version,
            normalized_minimum_annual=decision.normalized_minimum_annual,
            normalized_maximum_annual=decision.normalized_maximum_annual,
            conversion_basis=decision.conversion_basis,
            outcome=decision.outcome,
            reason_code=decision.reason_code,
            explanation=decision.explanation,
        )
        session.add(assessment)
        session.flush()
    return assessment


def get_compensation_assessment(
    session: Session, assessment_id: str
) -> CompensationAssessment | None:
    return session.scalar(
        select(CompensationAssessment).where(CompensationAssessment.id == assessment_id)
    )
