"""Add application tracking and status history tables.

Revision ID: 0005_application_tracking
Revises: 0004_job_discovery_persistence
Create Date: 2026-10-29

Downgrade intentionally drops all application tracking records and history.
Only use it with disposable data or after an explicit export/removal decision.
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0005_application_tracking"
down_revision: str | None = "0004_job_discovery_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. tracked_applications
    op.create_table(
        "tracked_applications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_posting_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="SAVED", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("follow_up_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_interview_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_status_change_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("submitted_resume_snapshot", sa.Text(), nullable=True),
        sa.Column("submitted_cover_letter_snapshot", sa.Text(), nullable=True),
        sa.Column("submitted_resume_sha256", sa.String(length=64), nullable=True),
        sa.Column("submitted_cover_letter_sha256", sa.String(length=64), nullable=True),
        sa.Column("reviewed_resume_markdown", sa.Text(), nullable=True),
        sa.Column("reviewed_cover_letter_markdown", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_tracked_applications"),
        sa.UniqueConstraint("job_posting_id", name="uq_tracked_applications_posting"),
        sa.ForeignKeyConstraint(
            ["job_posting_id"],
            ["job_postings.id"],
            ondelete="RESTRICT",
            name="fk_tracked_applications_posting",
        ),
        sa.CheckConstraint(
            "status IN ('SAVED', 'PREPARING', 'READY_FOR_REVIEW', 'APPLIED', 'INTERVIEWING', 'OFFER_RECEIVED', 'REJECTED', 'WITHDRAWN', 'ARCHIVED')",
            name="ck_tracked_applications_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_tracked_applications_version_positive"),
    )
    op.create_index("ix_tracked_applications_status", "tracked_applications", ["status"])
    op.create_index("ix_tracked_applications_updated_at", "tracked_applications", ["updated_at"])

    # 2. application_status_history
    op.create_table(
        "application_status_history",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer, "sqlite"),
            primary_key=True,
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("application_id", sa.String(length=36), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("transition_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_application_status_history"),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["tracked_applications.id"],
            ondelete="CASCADE",
            name="fk_app_status_history_application",
        ),
        sa.CheckConstraint(
            "to_status IN ('SAVED', 'PREPARING', 'READY_FOR_REVIEW', 'APPLIED', 'INTERVIEWING', 'OFFER_RECEIVED', 'REJECTED', 'WITHDRAWN', 'ARCHIVED')",
            name="ck_app_status_history_to_status",
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN ('SAVED', 'PREPARING', 'READY_FOR_REVIEW', 'APPLIED', 'INTERVIEWING', 'OFFER_RECEIVED', 'REJECTED', 'WITHDRAWN', 'ARCHIVED')",
            name="ck_app_status_history_from_status",
        ),
    )
    op.create_index(
        "ix_app_status_history_app_id", "application_status_history", ["application_id"]
    )
    op.create_index(
        "ix_app_status_history_created_at", "application_status_history", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_app_status_history_created_at", table_name="application_status_history")
    op.drop_index("ix_app_status_history_app_id", table_name="application_status_history")
    op.drop_table("application_status_history")
    op.drop_index("ix_tracked_applications_updated_at", table_name="tracked_applications")
    op.drop_index("ix_tracked_applications_status", table_name="tracked_applications")
    op.drop_table("tracked_applications")
