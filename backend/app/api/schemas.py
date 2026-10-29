import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal
import unicodedata
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.domain.compensation import (
    EvidenceVerificationState,
    PayPeriod,
    ReportedCompensationStatus,
    validate_money,
)


MONEY_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,2})?\Z")
REFERENCE_PATTERN = r"^[A-Za-z0-9._:-]+$"
EXTENDED_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")


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


def _clean_text(value: str, maximum: int) -> str:
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized or len(normalized) > maximum or "\x00" in normalized:
        raise ValueError("text is invalid")
    return normalized


class DocumentCreateInput(StrictRequest):
    display_name: str = Field(min_length=1, max_length=120)

    @field_validator("display_name")
    @classmethod
    def display_name_is_safe(cls, value: str) -> str:
        return _clean_text(value, 120)


class CandidateFactInput(StrictRequest):
    fact_type: Literal["SKILL", "EDUCATION", "EMPLOYMENT", "PROJECT", "CERTIFICATION"]
    value: dict[str, object]

    @model_validator(mode="after")
    def value_matches_closed_fact_schema(self) -> "CandidateFactInput":
        expected: dict[str, tuple[set[str], set[str], dict[str, int]]] = {
            "SKILL": ({"name"}, set(), {"name": 120}),
            "EDUCATION": (
                {"institution", "credential"}, {"field_of_study", "graduation_year"},
                {"institution": 160, "credential": 120, "field_of_study": 120},
            ),
            "EMPLOYMENT": (
                {"employer", "title"}, {"start_date", "end_date"},
                {"employer": 160, "title": 160, "start_date": 10, "end_date": 10},
            ),
            "PROJECT": ({"name"}, {"description"}, {"name": 160, "description": 1000}),
            "CERTIFICATION": (
                {"name"}, {"issuer", "credential_id"},
                {"name": 160, "issuer": 160, "credential_id": 128},
            ),
        }
        required, optional, text_limits = expected[self.fact_type]
        keys = set(self.value)
        if not required <= keys or not keys <= required | optional:
            raise ValueError("fact value has an invalid shape")
        cleaned: dict[str, object] = {}
        for key, value in self.value.items():
            if key == "graduation_year":
                if type(value) is not int or not 1900 <= value <= 2100:
                    raise ValueError("graduation year is invalid")
                cleaned[key] = value
                continue
            if not isinstance(value, str):
                raise ValueError("fact value text is invalid")
            normalized = _clean_text(value, text_limits[key])
            if key in {"start_date", "end_date"}:
                if not EXTENDED_DATE_PATTERN.fullmatch(normalized):
                    raise ValueError("employment date is invalid")
                try:
                    date.fromisoformat(normalized)
                except ValueError as exc:
                    raise ValueError("employment date is invalid") from exc
            cleaned[key] = normalized
        if self.fact_type == "EMPLOYMENT" and {
            "start_date", "end_date"
        } <= set(cleaned):
            if str(cleaned["end_date"]) < str(cleaned["start_date"]):
                raise ValueError("employment end date precedes start date")
        self.value = cleaned
        return self


class ProvenanceInput(StrictRequest):
    document_version_id: UUID
    byte_start: int = Field(ge=0)
    byte_end: int = Field(gt=0)
    excerpt: str | None = Field(default=None, max_length=4096)

    @model_validator(mode="after")
    def range_is_valid(self) -> "ProvenanceInput":
        if self.byte_end <= self.byte_start or self.byte_end - self.byte_start > 4096:
            raise ValueError("provenance range is invalid")
        return self
