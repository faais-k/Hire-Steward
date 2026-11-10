from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import CompensationPreference, CompensationPreferenceAudit
from backend.app.domain.compensation import validate_money


def get_minimum_compensation(
    session: Session, *, lock: bool = False
) -> CompensationPreference:
    statement = select(CompensationPreference).where(CompensationPreference.id == 1)
    if lock:
        statement = statement.with_for_update()
    preference = session.scalar(statement)
    if preference is None:
        raise RuntimeError("compensation preference is missing; apply database migrations")
    return preference


def set_minimum_compensation(
    session: Session, amount: Decimal
) -> CompensationPreference:
    amount = validate_money(amount, field_name="minimum compensation")
    ctx = session.begin_nested() if session.in_transaction() else session.begin()
    with ctx:
        preference = get_minimum_compensation(session, lock=True)
        if preference.amount != amount:
            previous_amount = preference.amount
            preference.amount = amount
            preference.version += 1
            session.add(
                CompensationPreferenceAudit(
                    preference_id=preference.id,
                    previous_amount=previous_amount,
                    new_amount=amount,
                    currency="INR",
                    period="YEAR",
                    settings_version=preference.version,
                    actor_type="local_api",
                    actor_id="local",
                )
            )
            from backend.app.services.audit import record_audit_event

            record_audit_event(
                session,
                event_type="COMPENSATION_PREFERENCE_UPDATED",
                entity_type="COMPENSATION_PREFERENCE",
                entity_id="1",
                payload_json={
                    "previous_amount": str(previous_amount),
                    "new_amount": str(amount),
                    "currency": "INR",
                    "period": "YEAR",
                    "version": preference.version,
                },
            )
            session.flush()
    return preference
