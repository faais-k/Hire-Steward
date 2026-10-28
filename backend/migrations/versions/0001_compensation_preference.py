"""Persist compensation preference, audit events, and assessment snapshots.

Revision ID: 0001_compensation_preference
Revises:
Create Date: 2026-10-28
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0001_compensation_preference"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "compensation_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("period", sa.String(length=8), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_compensation_preferences_singleton"),
        sa.CheckConstraint("amount >= 0", name="ck_compensation_preferences_amount_nonnegative"),
        sa.CheckConstraint("currency = 'INR'", name="ck_compensation_preferences_currency_inr"),
        sa.CheckConstraint("period = 'YEAR'", name="ck_compensation_preferences_period_year"),
        sa.CheckConstraint("version >= 1", name="ck_compensation_preferences_version_positive"),
        sa.PrimaryKeyConstraint("id", name="pk_compensation_preferences"),
    )
    op.create_table(
        "compensation_preference_audits",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("preference_id", sa.Integer(), nullable=False),
        sa.Column("previous_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("new_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("period", sa.String(length=8), nullable=False),
        sa.Column("settings_version", sa.Integer(), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("previous_amount >= 0", name="ck_comp_pref_audit_previous_nonnegative"),
        sa.CheckConstraint("new_amount >= 0", name="ck_comp_pref_audit_new_nonnegative"),
        sa.CheckConstraint("currency = 'INR'", name="ck_comp_pref_audit_currency_inr"),
        sa.CheckConstraint("period = 'YEAR'", name="ck_comp_pref_audit_period_year"),
        sa.CheckConstraint("settings_version >= 2", name="ck_comp_pref_audit_version"),
        sa.ForeignKeyConstraint(
            ["preference_id"],
            ["compensation_preferences.id"],
            name="fk_comp_pref_audit_preference",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_compensation_preference_audits"),
    )
    op.create_table(
        "compensation_assessments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_reference", sa.String(length=160), nullable=False),
        sa.Column("source_status", sa.String(length=8), nullable=False),
        sa.Column("source_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("source_minimum", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("source_maximum", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("source_currency", sa.String(length=3), nullable=True),
        sa.Column("source_period", sa.String(length=8), nullable=False),
        sa.Column("source_recurring", sa.Boolean(), nullable=True),
        sa.Column("evidence_reference", sa.String(length=256), nullable=True),
        sa.Column("threshold_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("threshold_currency", sa.String(length=3), nullable=False),
        sa.Column("threshold_period", sa.String(length=8), nullable=False),
        sa.Column("threshold_version", sa.Integer(), nullable=False),
        sa.Column("normalized_minimum_annual", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("normalized_maximum_annual", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("conversion_basis", sa.String(length=64), nullable=True),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("reason_code", sa.String(length=48), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("threshold_amount >= 0", name="ck_comp_assess_threshold_nonnegative"),
        sa.CheckConstraint("source_amount IS NULL OR source_amount >= 0", name="ck_comp_assess_source_amount_nonnegative"),
        sa.CheckConstraint("source_minimum IS NULL OR source_minimum >= 0", name="ck_comp_assess_source_min_nonnegative"),
        sa.CheckConstraint("source_maximum IS NULL OR source_maximum >= 0", name="ck_comp_assess_source_max_nonnegative"),
        sa.CheckConstraint("normalized_minimum_annual IS NULL OR normalized_minimum_annual >= 0", name="ck_comp_assess_normal_min_nonnegative"),
        sa.CheckConstraint("normalized_maximum_annual IS NULL OR normalized_maximum_annual >= 0", name="ck_comp_assess_normal_max_nonnegative"),
        sa.CheckConstraint(
            "(source_minimum IS NULL AND source_maximum IS NULL) OR "
            "(source_minimum IS NOT NULL AND source_maximum IS NOT NULL AND source_minimum <= source_maximum)",
            name="ck_comp_assess_source_range_ordered",
        ),
        sa.CheckConstraint(
            "source_amount IS NULL OR (source_minimum IS NULL AND source_maximum IS NULL)",
            name="ck_comp_assess_single_amount_or_range",
        ),
        sa.CheckConstraint("threshold_currency = 'INR'", name="ck_comp_assess_threshold_currency_inr"),
        sa.CheckConstraint("threshold_period = 'YEAR'", name="ck_comp_assess_threshold_period_year"),
        sa.CheckConstraint("threshold_version >= 1", name="ck_comp_assess_threshold_version"),
        sa.CheckConstraint("source_status IN ('PAID', 'UNPAID', 'UNKNOWN')", name="ck_comp_assess_source_status"),
        sa.CheckConstraint("source_period IN ('YEAR', 'MONTH', 'HOUR', 'DAY', 'CONTRACT', 'UNKNOWN')", name="ck_comp_assess_source_period"),
        sa.CheckConstraint("outcome IN ('BLOCKED', 'MEETS_THRESHOLD', 'REVIEW_REQUIRED')", name="ck_comp_assess_outcome"),
        sa.PrimaryKeyConstraint("id", name="pk_compensation_assessments"),
    )
    op.create_index(
        "ix_compensation_assessments_job_created",
        "compensation_assessments",
        ["job_reference", "created_at"],
        unique=False,
    )
    op.execute(
        "INSERT INTO compensation_preferences (id, amount, currency, period, version, updated_at) "
        "VALUES (1, 100000.00, 'INR', 'YEAR', 1, CURRENT_TIMESTAMP)"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_compensation_assessments_job_created",
        table_name="compensation_assessments",
    )
    op.drop_table("compensation_assessments")
    op.drop_table("compensation_preference_audits")
    op.drop_table("compensation_preferences")
