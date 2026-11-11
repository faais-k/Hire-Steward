"""Add frozen material and review approval columns to submission_plans and tracked_applications.

Revision ID: 0011_plan_frozen_material
Revises: 0010_background_tasks
Create Date: 2026-11-11
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0011_plan_frozen_material"
down_revision: str | None = "0010_background_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add frozen material columns to submission_plans
    op.add_column("submission_plans", sa.Column("resume_markdown", sa.Text(), nullable=True))
    op.add_column("submission_plans", sa.Column("cover_letter_markdown", sa.Text(), nullable=True))
    op.add_column(
        "submission_plans",
        sa.Column("review_state", sa.String(length=32), server_default="UNREVIEWED", nullable=False),
    )

    # 2. Add explicit approval tracking columns to tracked_applications
    op.add_column(
        "tracked_applications",
        sa.Column("reviewed_resume_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "tracked_applications",
        sa.Column("reviewed_cover_letter_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "tracked_applications",
        sa.Column("review_approval_state", sa.String(length=32), server_default="UNREVIEWED", nullable=False),
    )
    op.add_column(
        "tracked_applications",
        sa.Column("approved_submission_plan_id", sa.String(length=36), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tracked_applications", "approved_submission_plan_id")
    op.drop_column("tracked_applications", "review_approval_state")
    op.drop_column("tracked_applications", "reviewed_cover_letter_sha256")
    op.drop_column("tracked_applications", "reviewed_resume_sha256")

    op.drop_column("submission_plans", "review_state")
    op.drop_column("submission_plans", "cover_letter_markdown")
    op.drop_column("submission_plans", "resume_markdown")
