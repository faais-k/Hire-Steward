"""Service layer for user settings and matching search preferences (Stage 3)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from sqlalchemy.orm import Session

from backend.app.db.models import UserSettingsModel
from backend.app.domain.user_settings import UserSettings, UserSettingsError
from backend.app.services.preferences import (
    get_minimum_compensation,
    set_minimum_compensation,
)


def get_or_create_settings_record(
    session: Session, settings_id: str = "default"
) -> UserSettingsModel:
    record = session.get(UserSettingsModel, settings_id)
    if record is None:
        defaults = UserSettings()
        record = UserSettingsModel(
            id=settings_id,
            target_roles=defaults.target_roles,
            target_locations=defaults.target_locations,
            workplace_arrangements=defaults.workplace_arrangements,
            sponsorship_requirement=defaults.sponsorship_requirement,
            same_company_cooldown_days=defaults.same_company_cooldown_days,
            daily_application_cap=defaults.daily_application_cap,
            auto_tailor_resume=defaults.auto_tailor_resume,
            dry_run_simulation_mode=defaults.dry_run_simulation_mode,
            ai_provider_mode=defaults.ai_provider_mode,
            ai_budget_limit_usd=defaults.ai_budget_limit_usd,
        )
        session.add(record)
        session.flush()
    return record


def get_user_settings(session: Session | None = None) -> dict[str, Any]:
    """Retrieve combined settings including compensation policies and search preferences."""
    settings = UserSettings()

    if session is not None:
        try:
            record = get_or_create_settings_record(session)
            settings.target_roles = list(record.target_roles or [])
            settings.target_locations = list(record.target_locations or [])
            settings.workplace_arrangements = list(record.workplace_arrangements or [])
            settings.sponsorship_requirement = record.sponsorship_requirement
            settings.same_company_cooldown_days = record.same_company_cooldown_days
            settings.daily_application_cap = record.daily_application_cap
            settings.auto_tailor_resume = record.auto_tailor_resume
            settings.dry_run_simulation_mode = record.dry_run_simulation_mode
            settings.ai_provider_mode = record.ai_provider_mode
            settings.ai_budget_limit_usd = record.ai_budget_limit_usd
        except Exception as exc:
            raise UserSettingsError(f"FAILED_TO_LOAD_SETTINGS: {exc}") from exc

    comp_dict = {
        "amount": "100000.00",
        "currency": "INR",
        "period": "YEAR",
        "version": 1,
    }
    if session is not None:
        try:
            pref = get_minimum_compensation(session)
            comp_dict = {
                "amount": f"{pref.amount:.2f}",
                "currency": pref.currency,
                "period": pref.period,
                "version": pref.version,
            }
        except Exception as exc:
            if "compensation preference is missing" in str(exc).lower():
                pass
            else:
                raise UserSettingsError(f"FAILED_TO_LOAD_COMPENSATION_PREFERENCE: {exc}") from exc

    res = settings.to_dict()
    res["minimum_compensation"] = comp_dict
    return res


def update_user_settings(
    session: Session,
    updates: dict[str, Any],
    auto_commit: bool = True,
) -> dict[str, Any]:
    """Atomically update search policies and compensation preference."""
    record = get_or_create_settings_record(session)

    # Validate against domain
    current = UserSettings(
        target_roles=list(record.target_roles or []),
        target_locations=list(record.target_locations or []),
        workplace_arrangements=list(record.workplace_arrangements or []),
        sponsorship_requirement=record.sponsorship_requirement,
        same_company_cooldown_days=record.same_company_cooldown_days,
        daily_application_cap=record.daily_application_cap,
        auto_tailor_resume=record.auto_tailor_resume,
        dry_run_simulation_mode=record.dry_run_simulation_mode,
        ai_provider_mode=record.ai_provider_mode,
        ai_budget_limit_usd=record.ai_budget_limit_usd,
    )

    for k, v in updates.items():
        if hasattr(current, k) and k != "minimum_compensation":
            setattr(current, k, v)

    current.validate()

    # Apply to DB model
    record.target_roles = current.target_roles
    record.target_locations = current.target_locations
    record.workplace_arrangements = current.workplace_arrangements
    record.sponsorship_requirement = current.sponsorship_requirement
    record.same_company_cooldown_days = current.same_company_cooldown_days
    record.daily_application_cap = current.daily_application_cap
    record.auto_tailor_resume = current.auto_tailor_resume
    record.dry_run_simulation_mode = current.dry_run_simulation_mode
    record.ai_provider_mode = current.ai_provider_mode
    record.ai_budget_limit_usd = current.ai_budget_limit_usd

    # Update compensation if supplied
    if "minimum_compensation" in updates and isinstance(updates["minimum_compensation"], dict):
        comp_in = updates["minimum_compensation"]
        if "amount" in comp_in:
            amt = Decimal(str(comp_in["amount"]))
            set_minimum_compensation(session, amt)

    from backend.app.services.audit import record_audit_event

    record_audit_event(
        session,
        event_type="USER_SETTINGS_UPDATED",
        entity_type="USER_SETTINGS",
        entity_id=record.id,
        payload_json={"updated_keys": list(updates.keys())},
    )

    if auto_commit:
        session.commit()
    else:
        session.flush()

    return get_user_settings(session)
