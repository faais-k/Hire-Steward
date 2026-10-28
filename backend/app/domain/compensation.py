"""Deterministic compensation preference evaluation."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


CENT = Decimal("0.01")
MAX_MONEY = Decimal("9999999999999999.99")


class ReportedCompensationStatus(StrEnum):
    PAID = "PAID"
    UNPAID = "UNPAID"
    UNKNOWN = "UNKNOWN"


class EvidenceVerificationState(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


class PayPeriod(StrEnum):
    YEAR = "YEAR"
    MONTH = "MONTH"
    HOUR = "HOUR"
    DAY = "DAY"
    CONTRACT = "CONTRACT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class CompensationEvidence:
    reported_status: ReportedCompensationStatus
    verification_state: EvidenceVerificationState
    currency: str | None = None
    period: PayPeriod = PayPeriod.UNKNOWN
    amount: Decimal | None = None
    minimum_amount: Decimal | None = None
    maximum_amount: Decimal | None = None
    recurring: bool | None = None


@dataclass(frozen=True, slots=True)
class CompensationDecision:
    outcome: str
    reason_code: str
    explanation: str
    verification_state: EvidenceVerificationState
    threshold_amount: Decimal
    threshold_currency: str
    threshold_period: str
    normalized_minimum_annual: Decimal | None
    normalized_maximum_annual: Decimal | None
    conversion_basis: str | None


def validate_money(value: Decimal, *, field_name: str = "amount") -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite decimal amount")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    if value.as_tuple().exponent < -2:
        raise ValueError(f"{field_name} may have at most two decimal places")
    if value > MAX_MONEY:
        raise ValueError(f"{field_name} exceeds the supported precision")
    return value.quantize(CENT)


def assess_compensation(
    evidence: CompensationEvidence, minimum_annual: Decimal
) -> CompensationDecision:
    threshold = validate_money(minimum_annual, field_name="minimum compensation")

    if evidence.verification_state is not EvidenceVerificationState.VERIFIED:
        if evidence.reported_status is ReportedCompensationStatus.UNPAID:
            explanation = (
                "The caller reported this role as unpaid, but that report is unverified. "
                "Review is required; it is not a confirmed unpaid classification."
            )
        elif evidence.reported_status is ReportedCompensationStatus.UNKNOWN:
            explanation = (
                "The caller reported compensation as unknown, and the observation is "
                "unverified. Review is required before proceeding."
            )
        else:
            explanation = (
                "Caller-supplied compensation is an unverified observation. "
                "Verify its provenance before reassessing; it cannot authorize an action."
            )
        return _decision(
            "REVIEW_REQUIRED",
            "EVIDENCE_UNVERIFIED",
            explanation,
            threshold,
            verification_state=evidence.verification_state,
        )

    if evidence.reported_status is ReportedCompensationStatus.UNPAID:
        return _decision(
            "BLOCKED",
            "UNPAID_ROLE",
            "Trusted evidence confirms an unpaid role, which is ineligible at every compensation setting.",
            threshold,
        )

    if evidence.reported_status is ReportedCompensationStatus.UNKNOWN:
        return _decision(
            "REVIEW_REQUIRED",
            "COMPENSATION_UNKNOWN",
            "Compensation is unknown; investigate or review it before proceeding.",
            threshold,
        )

    if evidence.reported_status is not ReportedCompensationStatus.PAID:
        raise ValueError("unsupported compensation status")

    has_amount = evidence.amount is not None
    has_range = (
        evidence.minimum_amount is not None or evidence.maximum_amount is not None
    )
    if has_amount and has_range:
        raise ValueError("provide either an amount or a range, not both")
    if has_range and (
        evidence.minimum_amount is None or evidence.maximum_amount is None
    ):
        raise ValueError("both ends of a compensation range are required")
    if not has_amount and not has_range:
        return _decision(
            "REVIEW_REQUIRED",
            "COMPENSATION_AMOUNT_MISSING",
            "No verified compensation amount is available; review is required.",
            threshold,
        )

    if evidence.currency != "INR":
        return _decision(
            "REVIEW_REQUIRED",
            "UNSUPPORTED_CURRENCY",
            "Compensation is not in INR and no verified exchange-rate basis is available.",
            threshold,
        )

    if evidence.period is PayPeriod.YEAR:
        conversion_basis = "DIRECT_INR_ANNUAL"
        multiplier = Decimal("1")
    elif evidence.period is PayPeriod.MONTH and evidence.recurring is True:
        conversion_basis = "RECURRING_MONTHLY_AMOUNT_X_12"
        multiplier = Decimal("12")
    else:
        return _decision(
            "REVIEW_REQUIRED",
            "INSUFFICIENT_CONVERSION_BASIS",
            "The pay period cannot be annualized from the supplied evidence alone.",
            threshold,
        )

    if has_amount:
        amount = validate_money(evidence.amount, field_name="compensation amount")
        try:
            annual_amount = validate_money(
                amount * multiplier, field_name="annualized compensation"
            )
        except ValueError:
            return _decision(
                "REVIEW_REQUIRED",
                "NORMALIZED_AMOUNT_OUT_OF_RANGE",
                "The annualized amount exceeds the supported exact-decimal range; review is required.",
                threshold,
                conversion_basis=conversion_basis,
            )
        if annual_amount < threshold:
            return _decision(
                "BLOCKED",
                "BELOW_MINIMUM",
                "Verified annualized compensation is below the saved preference.",
                threshold,
                normalized_minimum_annual=annual_amount,
                normalized_maximum_annual=annual_amount,
                conversion_basis=conversion_basis,
            )
        return _decision(
            "MEETS_THRESHOLD",
            "MEETS_MINIMUM",
            "Verified annualized compensation meets the saved preference; this passes only the compensation gate.",
            threshold,
            normalized_minimum_annual=annual_amount,
            normalized_maximum_annual=annual_amount,
            conversion_basis=conversion_basis,
        )

    low = validate_money(evidence.minimum_amount, field_name="range minimum")
    high = validate_money(evidence.maximum_amount, field_name="range maximum")
    if low > high:
        raise ValueError("compensation range minimum exceeds its maximum")
    try:
        annual_low = validate_money(low * multiplier, field_name="annualized range minimum")
        annual_high = validate_money(high * multiplier, field_name="annualized range maximum")
    except ValueError:
        return _decision(
            "REVIEW_REQUIRED",
            "NORMALIZED_AMOUNT_OUT_OF_RANGE",
            "The annualized range exceeds the supported exact-decimal range; review is required.",
            threshold,
            conversion_basis=conversion_basis,
        )
    if annual_high < threshold:
        return _decision(
            "BLOCKED",
            "RANGE_BELOW_MINIMUM",
            "The verified compensation range is entirely below the saved preference.",
            threshold,
            normalized_minimum_annual=annual_low,
            normalized_maximum_annual=annual_high,
            conversion_basis=conversion_basis,
        )
    if annual_low >= threshold:
        return _decision(
            "MEETS_THRESHOLD",
            "RANGE_MEETS_MINIMUM",
            "The verified compensation range meets the saved preference throughout; this passes only the compensation gate.",
            threshold,
            normalized_minimum_annual=annual_low,
            normalized_maximum_annual=annual_high,
            conversion_basis=conversion_basis,
        )
    return _decision(
        "REVIEW_REQUIRED",
        "RANGE_CROSSES_MINIMUM",
        "The verified compensation range crosses the saved preference; review is required unless reliable evidence resolves it.",
        threshold,
        normalized_minimum_annual=annual_low,
        normalized_maximum_annual=annual_high,
        conversion_basis=conversion_basis,
    )


def _decision(
    outcome: str,
    reason_code: str,
    explanation: str,
    threshold: Decimal,
    *,
    verification_state: EvidenceVerificationState = EvidenceVerificationState.VERIFIED,
    normalized_minimum_annual: Decimal | None = None,
    normalized_maximum_annual: Decimal | None = None,
    conversion_basis: str | None = None,
) -> CompensationDecision:
    return CompensationDecision(
        outcome=outcome,
        reason_code=reason_code,
        explanation=explanation,
        verification_state=verification_state,
        threshold_amount=threshold,
        threshold_currency="INR",
        threshold_period="YEAR",
        normalized_minimum_annual=normalized_minimum_annual,
        normalized_maximum_annual=normalized_maximum_annual,
        conversion_basis=conversion_basis,
    )
