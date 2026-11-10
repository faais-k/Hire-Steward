"""Support binary document blobs, text artifacts, application attempts, and audit events.

Revision ID: 0009_binary_docs_attempts
Revises: 0008_consent_cooldown_plans
Create Date: 2026-11-05
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0009_binary_docs_attempts"
down_revision: str | None = "0008_consent_cooldown_plans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -------------------------------------------------------------
    # 1. candidate_document_blobs: allow all media types (binary + text)
    # -------------------------------------------------------------
    with op.batch_alter_table("candidate_document_blobs") as batch_op:
        batch_op.drop_constraint("ck_candidate_blob_media_type", type_="check")
        batch_op.create_check_constraint("ck_candidate_blob_media_type", "length(media_type) > 0")

    # -------------------------------------------------------------
    # 2. candidate_document_versions: add text_artifact_hash and allow extraction statuses
    # -------------------------------------------------------------
    with op.batch_alter_table("candidate_document_versions") as batch_op:
        batch_op.drop_constraint("ck_candidate_document_version_extraction_status", type_="check")
        batch_op.create_check_constraint(
            "ck_candidate_document_version_extraction_status",
            "extraction_status IN ('NOT_REQUESTED', 'EXTRACTED', 'FAILED', 'OCR_REQUIRED', 'ENCRYPTED')",
        )
        batch_op.add_column(
            sa.Column("text_artifact_hash", sa.String(length=64), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_candidate_version_text_artifact",
            "candidate_document_blobs",
            ["text_artifact_hash"],
            ["content_hash"],
            ondelete="RESTRICT",
        )

    # -------------------------------------------------------------
    # 3. application_attempts: separate submission attempts from plans
    # -------------------------------------------------------------
    op.create_table(
        "application_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("application_id", sa.String(length=36), nullable=False),
        sa.Column("submission_plan_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("simulation_mode", sa.String(length=32), server_default="SUCCESS", nullable=False),
        sa.Column("plan_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="NOT_DISPATCHED", nullable=False),
        sa.Column("outcome", sa.String(length=32), server_default="PENDING", nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("simulated_receipt", sa.String(length=128), nullable=True),
        sa.Column("metadata_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_application_attempts"),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["tracked_applications.id"],
            name="fk_application_attempts_application_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["submission_plan_id"],
            ["submission_plans.id"],
            name="fk_application_attempts_submission_plan_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("application_id", "idempotency_key", name="uq_application_attempts_idempotency"),
    )
    op.create_index(
        "ix_application_attempts_app_started",
        "application_attempts",
        ["application_id", "started_at"],
    )

    # -------------------------------------------------------------
    # 4. audit_events: unified system, security, and policy audit log
    # -------------------------------------------------------------
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("actor_type", sa.String(length=32), server_default="USER", nullable=False),
        sa.Column("actor_id", sa.String(length=64), server_default="default", nullable=False),
        sa.Column("payload_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    op.create_index(
        "ix_audit_events_type_created",
        "audit_events",
        ["event_type", "created_at"],
    )
    op.create_index(
        "ix_audit_events_entity",
        "audit_events",
        ["entity_type", "entity_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_entity", table_name="audit_events")
    op.drop_index("ix_audit_events_type_created", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index("ix_application_attempts_app_started", table_name="application_attempts")
    op.drop_table("application_attempts")

    with op.batch_alter_table("candidate_document_versions") as batch_op:
        batch_op.drop_constraint("fk_candidate_version_text_artifact", type_="foreignkey")
        batch_op.drop_column("text_artifact_hash")
        batch_op.drop_constraint("ck_candidate_document_version_extraction_status", type_="check")
        batch_op.create_check_constraint("ck_candidate_document_version_extraction_status", "extraction_status = 'NOT_REQUESTED'")

    with op.batch_alter_table("candidate_document_blobs") as batch_op:
        batch_op.drop_constraint("ck_candidate_blob_media_type", type_="check")
        batch_op.create_check_constraint("ck_candidate_blob_media_type", "media_type = 'text/plain'")
