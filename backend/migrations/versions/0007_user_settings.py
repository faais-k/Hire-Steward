"""Add user settings table and persist search policies (Stage 3).

Revision ID: 0007_user_settings
Revises: 0006_candidate_profile
Create Date: 2026-11-05
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0007_user_settings"
down_revision: str | None = "0006_candidate_profile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_settings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("target_roles", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("target_locations", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("workplace_arrangements", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("sponsorship_requirement", sa.String(length=32), server_default="not_required", nullable=False),
        sa.Column("same_company_cooldown_days", sa.Integer(), server_default="90", nullable=False),
        sa.Column("daily_application_cap", sa.Integer(), server_default="5", nullable=False),
        sa.Column("auto_tailor_resume", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("dry_run_simulation_mode", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("ai_provider_mode", sa.String(length=32), server_default="OFFLINE_MOCK", nullable=False),
        sa.Column("ai_budget_limit_usd", sa.Float(), server_default="5.0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_settings"),
    )


def downgrade() -> None:
    op.drop_table("user_settings")
