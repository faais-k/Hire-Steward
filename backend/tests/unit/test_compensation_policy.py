from decimal import Decimal

import pytest

from backend.app.domain.compensation import (
    CompensationEvidence,
    EvidenceVerificationState,
    PayPeriod,
    ReportedCompensationStatus,
    assess_compensation,
)


DEFAULT_THRESHOLD = Decimal("100000.00")


def trusted_evidence(**kwargs):
    return CompensationEvidence(
        verification_state=EvidenceVerificationState.VERIFIED,
        **kwargs,
    )


@pytest.mark.parametrize(
    ("minimum", "amount", "expected"),
    [
        (Decimal("50000.00"), Decimal("60000.00"), "MEETS_MINIMUM"),
        (Decimal("150000.00"), Decimal("120000.00"), "BELOW_MINIMUM"),
        (Decimal("0.00"), Decimal("0.00"), "MEETS_MINIMUM"),
        (DEFAULT_THRESHOLD, Decimal("99999.99"), "BELOW_MINIMUM"),
        (DEFAULT_THRESHOLD, Decimal("100000.00"), "MEETS_MINIMUM"),
    ],
)
def test_exact_annual_decimal_comparison(minimum, amount, expected):
    result = assess_compensation(
        trusted_evidence(
            reported_status=ReportedCompensationStatus.PAID,
            currency="INR",
            period=PayPeriod.YEAR,
            amount=amount,
        ),
        minimum,
    )

    assert result.reason_code == expected
    assert result.threshold_amount == minimum


@pytest.mark.parametrize("minimum", [Decimal("0"), DEFAULT_THRESHOLD, Decimal("150000")])
def test_trusted_unpaid_is_blocked_independent_of_threshold(minimum):
    result = assess_compensation(
        trusted_evidence(reported_status=ReportedCompensationStatus.UNPAID), minimum
    )

    assert result.outcome == "BLOCKED"
    assert result.reason_code == "UNPAID_ROLE"
    assert result.verification_state is EvidenceVerificationState.VERIFIED


def test_trusted_unknown_compensation_requires_review_and_is_not_zero():
    result = assess_compensation(
        trusted_evidence(reported_status=ReportedCompensationStatus.UNKNOWN),
        DEFAULT_THRESHOLD,
    )

    assert result.outcome == "REVIEW_REQUIRED"
    assert result.reason_code == "COMPENSATION_UNKNOWN"
    assert result.normalized_minimum_annual is None


@pytest.mark.parametrize(
    ("low", "high", "expected", "outcome"),
    [
        (Decimal("40000"), Decimal("99999.99"), "RANGE_BELOW_MINIMUM", "BLOCKED"),
        (Decimal("100000"), Decimal("120000"), "RANGE_MEETS_MINIMUM", "MEETS_THRESHOLD"),
        (Decimal("80000"), Decimal("120000"), "RANGE_CROSSES_MINIMUM", "REVIEW_REQUIRED"),
    ],
)
def test_annual_range_policy(low, high, expected, outcome):
    result = assess_compensation(
        trusted_evidence(
            reported_status=ReportedCompensationStatus.PAID,
            currency="INR",
            period=PayPeriod.YEAR,
            minimum_amount=low,
            maximum_amount=high,
        ),
        DEFAULT_THRESHOLD,
    )

    assert result.reason_code == expected
    assert result.outcome == outcome


def test_explicit_recurring_monthly_pay_is_annualized_by_twelve():
    result = assess_compensation(
        trusted_evidence(
            reported_status=ReportedCompensationStatus.PAID,
            currency="INR",
            period=PayPeriod.MONTH,
            amount=Decimal("10000.00"),
            recurring=True,
        ),
        DEFAULT_THRESHOLD,
    )

    assert result.outcome == "MEETS_THRESHOLD"
    assert result.normalized_minimum_annual == Decimal("120000.00")
    assert result.conversion_basis == "RECURRING_MONTHLY_AMOUNT_X_12"


def test_hourly_compensation_without_working_hours_requires_review():
    result = assess_compensation(
        trusted_evidence(
            reported_status=ReportedCompensationStatus.PAID,
            currency="INR",
            period=PayPeriod.HOUR,
            amount=Decimal("1000.00"),
        ),
        DEFAULT_THRESHOLD,
    )

    assert result.outcome == "REVIEW_REQUIRED"
    assert result.reason_code == "INSUFFICIENT_CONVERSION_BASIS"
    assert result.normalized_minimum_annual is None


def test_monthly_rate_without_explicit_recurrence_requires_review():
    result = assess_compensation(
        trusted_evidence(
            reported_status=ReportedCompensationStatus.PAID,
            currency="INR",
            period=PayPeriod.MONTH,
            amount=Decimal("10000.00"),
        ),
        DEFAULT_THRESHOLD,
    )

    assert result.outcome == "REVIEW_REQUIRED"
    assert result.reason_code == "INSUFFICIENT_CONVERSION_BASIS"


def test_monthly_annualization_outside_supported_precision_requires_review():
    result = assess_compensation(
        trusted_evidence(
            reported_status=ReportedCompensationStatus.PAID,
            currency="INR",
            period=PayPeriod.MONTH,
            amount=Decimal("9999999999999999.99"),
            recurring=True,
        ),
        DEFAULT_THRESHOLD,
    )

    assert result.outcome == "REVIEW_REQUIRED"
    assert result.reason_code == "NORMALIZED_AMOUNT_OUT_OF_RANGE"
    assert result.normalized_minimum_annual is None


def test_unverified_currency_is_not_converted():
    result = assess_compensation(
        trusted_evidence(
            reported_status=ReportedCompensationStatus.PAID,
            currency="USD",
            period=PayPeriod.YEAR,
            amount=Decimal("100000.00"),
        ),
        DEFAULT_THRESHOLD,
    )

    assert result.outcome == "REVIEW_REQUIRED"
    assert result.reason_code == "UNSUPPORTED_CURRENCY"


def test_unverified_paid_observation_always_requires_review():
    result = assess_compensation(
        CompensationEvidence(
            reported_status=ReportedCompensationStatus.PAID,
            verification_state=EvidenceVerificationState.UNVERIFIED,
            currency="INR",
            period=PayPeriod.YEAR,
            amount=Decimal("250000.00"),
        ),
        DEFAULT_THRESHOLD,
    )

    assert result.outcome == "REVIEW_REQUIRED"
    assert result.reason_code == "EVIDENCE_UNVERIFIED"
    assert result.verification_state is EvidenceVerificationState.UNVERIFIED
    assert result.normalized_minimum_annual is None
    assert "caller-supplied" in result.explanation.lower()
    assert "verified annualized compensation" not in result.explanation.lower()


@pytest.mark.parametrize(
    "reported_status",
    [ReportedCompensationStatus.UNKNOWN, ReportedCompensationStatus.UNPAID],
)
def test_unverified_unknown_or_unpaid_report_is_review_not_verified_fact(
    reported_status,
):
    result = assess_compensation(
        CompensationEvidence(
            reported_status=reported_status,
            verification_state=EvidenceVerificationState.UNVERIFIED,
        ),
        Decimal("0"),
    )

    assert result.outcome == "REVIEW_REQUIRED"
    assert result.reason_code == "EVIDENCE_UNVERIFIED"
    assert result.verification_state is EvidenceVerificationState.UNVERIFIED
    if reported_status is ReportedCompensationStatus.UNPAID:
        assert result.reason_code != "UNPAID_ROLE"
        assert "reported" in result.explanation.lower()


def test_trusted_unpaid_classification_remains_blocked_at_zero():
    result = assess_compensation(
        trusted_evidence(reported_status=ReportedCompensationStatus.UNPAID),
        Decimal("0"),
    )

    assert result.outcome == "BLOCKED"
    assert result.reason_code == "UNPAID_ROLE"
