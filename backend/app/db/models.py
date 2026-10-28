from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class CompensationPreference(Base):
    __tablename__ = "compensation_preferences"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_compensation_preferences_singleton"),
        CheckConstraint("amount >= 0", name="ck_compensation_preferences_amount_nonnegative"),
        CheckConstraint("currency = 'INR'", name="ck_compensation_preferences_currency_inr"),
        CheckConstraint("period = 'YEAR'", name="ck_compensation_preferences_period_year"),
        CheckConstraint("version >= 1", name="ck_compensation_preferences_version_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    period: Mapped[str] = mapped_column(String(8), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CompensationPreferenceAudit(Base):
    __tablename__ = "compensation_preference_audits"
    __table_args__ = (
        CheckConstraint("previous_amount >= 0", name="ck_comp_pref_audit_previous_nonnegative"),
        CheckConstraint("new_amount >= 0", name="ck_comp_pref_audit_new_nonnegative"),
        CheckConstraint("currency = 'INR'", name="ck_comp_pref_audit_currency_inr"),
        CheckConstraint("period = 'YEAR'", name="ck_comp_pref_audit_period_year"),
        CheckConstraint("settings_version >= 2", name="ck_comp_pref_audit_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    preference_id: Mapped[int] = mapped_column(
        ForeignKey("compensation_preferences.id", ondelete="RESTRICT"), nullable=False
    )
    previous_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    new_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    period: Mapped[str] = mapped_column(String(8), nullable=False)
    settings_version: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CompensationAssessment(Base):
    __tablename__ = "compensation_assessments"
    __table_args__ = (
        CheckConstraint("threshold_amount >= 0", name="ck_comp_assess_threshold_nonnegative"),
        CheckConstraint("source_amount IS NULL OR source_amount >= 0", name="ck_comp_assess_source_amount_nonnegative"),
        CheckConstraint("source_minimum IS NULL OR source_minimum >= 0", name="ck_comp_assess_source_min_nonnegative"),
        CheckConstraint("source_maximum IS NULL OR source_maximum >= 0", name="ck_comp_assess_source_max_nonnegative"),
        CheckConstraint("normalized_minimum_annual IS NULL OR normalized_minimum_annual >= 0", name="ck_comp_assess_normal_min_nonnegative"),
        CheckConstraint("normalized_maximum_annual IS NULL OR normalized_maximum_annual >= 0", name="ck_comp_assess_normal_max_nonnegative"),
        CheckConstraint(
            "(source_minimum IS NULL AND source_maximum IS NULL) OR "
            "(source_minimum IS NOT NULL AND source_maximum IS NOT NULL AND source_minimum <= source_maximum)",
            name="ck_comp_assess_source_range_ordered",
        ),
        CheckConstraint(
            "source_amount IS NULL OR (source_minimum IS NULL AND source_maximum IS NULL)",
            name="ck_comp_assess_single_amount_or_range",
        ),
        CheckConstraint("threshold_currency = 'INR'", name="ck_comp_assess_threshold_currency_inr"),
        CheckConstraint("threshold_period = 'YEAR'", name="ck_comp_assess_threshold_period_year"),
        CheckConstraint("threshold_version >= 1", name="ck_comp_assess_threshold_version"),
        CheckConstraint("source_status IN ('PAID', 'UNPAID', 'UNKNOWN')", name="ck_comp_assess_source_status"),
        CheckConstraint(
            "evidence_verification_state IN ('UNVERIFIED', 'VERIFIED')",
            name="ck_comp_assess_evidence_verification_state",
        ),
        CheckConstraint("source_period IN ('YEAR', 'MONTH', 'HOUR', 'DAY', 'CONTRACT', 'UNKNOWN')", name="ck_comp_assess_source_period"),
        CheckConstraint("outcome IN ('BLOCKED', 'MEETS_THRESHOLD', 'REVIEW_REQUIRED')", name="ck_comp_assess_outcome"),
        Index("ix_compensation_assessments_job_created", "job_reference", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    reported_status: Mapped[str] = mapped_column(
        "source_status", String(8), nullable=False
    )
    evidence_verification_state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="UNVERIFIED"
    )
    source_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    source_minimum: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    source_maximum: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    source_currency: Mapped[str | None] = mapped_column(String(3))
    source_period: Mapped[str] = mapped_column(String(8), nullable=False)
    source_recurring: Mapped[bool | None] = mapped_column(nullable=True)
    evidence_reference: Mapped[str | None] = mapped_column(String(256))
    threshold_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    threshold_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    threshold_period: Mapped[str] = mapped_column(String(8), nullable=False)
    threshold_version: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_minimum_annual: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    normalized_maximum_annual: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    conversion_basis: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(48), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
