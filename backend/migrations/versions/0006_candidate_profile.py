"""Add candidate profile and answer bank tables (Stage 2).

Revision ID: 0006_candidate_profile
Revises: 0005_application_tracking
Create Date: 2026-11-05
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0006_candidate_profile"
down_revision: str | None = "0005_application_tracking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. candidate_profiles
    op.create_table(
        "candidate_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), server_default="", nullable=False),
        sa.Column("headline", sa.String(length=500), server_default="", nullable=False),
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
        sa.Column("contact_info", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("education", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("employment", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("projects", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("skills", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("certifications", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("completeness_score", sa.Float(), server_default="0.0", nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_candidate_profiles"),
    )

    # 2. answer_bank_items
    op.create_table(
        "answer_bank_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=64), server_default="general", nullable=False),
        sa.Column("fact_ids", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("reuse_consent", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("is_revoked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_answer_bank_items"),
    )
    op.create_index(
        "ix_answer_bank_items_category",
        "answer_bank_items",
        ["category"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_answer_bank_items_category", table_name="answer_bank_items")
    op.drop_table("answer_bank_items")
    op.drop_table("candidate_profiles")
