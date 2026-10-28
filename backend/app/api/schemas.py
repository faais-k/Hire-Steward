import re
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.domain.compensation import (
    EvidenceVerificationState,
    PayPeriod,
    ReportedCompensationStatus,
    validate_money,
)


MONEY_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,2})?\Z")
REFERENCE_PATTERN = r"^[A-Za-z0-9._:-]+$"


def parse_money_string(value: object) -> Decimal:
    if (
        not isinstance(value, str)
        or len(value) > 19
        or not MONEY_PATTERN.fullmatch(value)
    ):
        raise ValueError("amount must be a plain decimal string with at most two decimal places")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("amount is not a valid decimal") from exc
    return validate_money(amount)


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MinimumCompensationInput(StrictRequest):
    amount: Decimal
    currency: Literal["INR"]
    period: Literal["YEAR"]

    @field_validator("amount", mode="before")
    @classmethod
    def amount_must_be_a_decimal_string(cls, value: object) -> Decimal:
        return parse_money_string(value)


class PolicySettingsUpdate(StrictRequest):
    minimum_compensation: MinimumCompensationInput


class CompensationAssessmentInput(StrictRequest):
    job_reference: str = Field(min_length=1, max_length=160, pattern=REFERENCE_PATTERN)
    reported_status: ReportedCompensationStatus
    amount: Decimal | None = None
    minimum_amount: Decimal | None = None
    maximum_amount: Decimal | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    period: PayPeriod = PayPeriod.UNKNOWN
    recurring: bool | None = None
    evidence_reference: str | None = Field(default=None, max_length=256, pattern=REFERENCE_PATTERN)

    @field_validator("amount", "minimum_amount", "maximum_amount", mode="before")
    @classmethod
    def money_fields_must_be_decimal_strings(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        return parse_money_string(value)

    @model_validator(mode="after")
    def validate_evidence_shape(self) -> "CompensationAssessmentInput":
        has_range = self.minimum_amount is not None or self.maximum_amount is not None
        if has_range and (self.minimum_amount is None or self.maximum_amount is None):
            raise ValueError("both minimum_amount and maximum_amount are required")
        if self.amount is not None and has_range:
            raise ValueError("provide amount or a range, not both")
        if self.reported_status is ReportedCompensationStatus.PAID and self.amount is None and not has_range:
            raise ValueError("paid compensation requires an amount or a range")
        if self.recurring is not None and self.period is not PayPeriod.MONTH:
            raise ValueError("recurring is valid only for monthly compensation")
        if (
            self.minimum_amount is not None
            and self.maximum_amount is not None
            and self.minimum_amount > self.maximum_amount
        ):
            raise ValueError("minimum_amount must not exceed maximum_amount")
        return self


class CompensationPreferenceView(BaseModel):
    amount: str
    currency: str
    period: str
    version: int


class PolicySettingsView(BaseModel):
    minimum_compensation: CompensationPreferenceView


class CompensationAssessmentView(BaseModel):
    assessment_id: str
    job_reference: str
    outcome: str
    reason_code: str
    explanation: str
    evidence_verification_state: EvidenceVerificationState
    eligible_to_submit: bool
    minimum_compensation: CompensationPreferenceView
    reported_status: str
    reported_amount: str | None
    reported_minimum: str | None
    reported_maximum: str | None
    reported_currency: str | None
    reported_period: str
    reported_recurring: bool | None
    reported_evidence_reference: str | None
    normalized_minimum_annual: str | None
    normalized_maximum_annual: str | None
    conversion_basis: str | None
    created_at: str
