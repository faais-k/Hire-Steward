"""Add candidate document evidence and provenance metadata.

Revision ID: 0003_candidate_evidence
Revises: 0002_comp_evidence_trust
Create Date: 2026-10-28

Downgrade intentionally drops all Foundation 3 candidate-evidence metadata.
Only use it with disposable data or after an explicit export/removal decision.
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003_candidate_evidence"
down_revision: str | None = "0002_comp_evidence_trust"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_document_blobs",
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=96), nullable=False),
        sa.Column("media_type", sa.String(length=32), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("content_hash", name="pk_candidate_document_blobs"),
        sa.UniqueConstraint("storage_key", name="uq_candidate_document_blobs_storage_key"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_candidate_blob_hash_length"),
        sa.CheckConstraint("byte_size > 0", name="ck_candidate_blob_size_positive"),
        sa.CheckConstraint("media_type = 'text/plain'", name="ck_candidate_blob_media_type"),
    )
    op.create_table(
        "candidate_evidence_storage_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("committed_bytes", sa.BigInteger(), nullable=False),
        sa.Column("reserved_bytes", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_candidate_evidence_storage_usage"),
        sa.CheckConstraint("id = 1", name="ck_candidate_usage_singleton"),
        sa.CheckConstraint("committed_bytes >= 0", name="ck_candidate_usage_committed_nonnegative"),
        sa.CheckConstraint("reserved_bytes >= 0", name="ck_candidate_usage_reserved_nonnegative"),
        sa.CheckConstraint("version >= 1", name="ck_candidate_usage_version_positive"),
    )
    op.create_table(
        "candidate_evidence_storage_reservations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("reserved_bytes", sa.BigInteger(), nullable=False),
        sa.Column("temp_key", sa.String(length=96), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("final_key", sa.String(length=96), nullable=True),
        sa.Column("actual_size", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_candidate_evidence_storage_reservations"),
        sa.UniqueConstraint("temp_key", name="uq_candidate_evidence_storage_reservations_temp_key"),
        sa.CheckConstraint("reserved_bytes > 0", name="ck_candidate_reservation_size_positive"),
        sa.CheckConstraint("state IN ('STAGING', 'READY_TO_PLACE', 'PLACED')", name="ck_candidate_reservation_state"),
        sa.CheckConstraint("actual_size IS NULL OR actual_size > 0", name="ck_candidate_reservation_actual_size_positive"),
        sa.CheckConstraint(
            "(state = 'STAGING' AND content_hash IS NULL AND final_key IS NULL AND actual_size IS NULL) OR "
            "(state IN ('READY_TO_PLACE', 'PLACED') AND content_hash IS NOT NULL AND final_key IS NOT NULL AND actual_size IS NOT NULL)",
            name="ck_candidate_reservation_state_fields",
        ),
    )
    op.create_table(
        "candidate_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("state", sa.String(length=16), server_default="ACTIVE", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_candidate_documents"),
        sa.CheckConstraint("state IN ('ACTIVE', 'RETIRED')", name="ck_candidate_document_state"),
    )
    op.create_index("ix_candidate_documents_state_created", "candidate_documents", ["state", "created_at"])
    op.create_table(
        "candidate_document_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("blob_hash", sa.String(length=64), nullable=False),
        sa.Column("original_filename", sa.String(length=128), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("extraction_status", sa.String(length=24), server_default="NOT_REQUESTED", nullable=False),
        sa.Column("extraction_error_code", sa.String(length=64), nullable=True),
        sa.Column("extractor_version", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_candidate_document_versions"),
        sa.UniqueConstraint("document_id", "version_number", name="uq_candidate_document_version_number"),
        sa.UniqueConstraint("document_id", "blob_hash", name="uq_candidate_document_version_blob"),
        sa.ForeignKeyConstraint(["document_id"], ["candidate_documents.id"], ondelete="RESTRICT", name="fk_candidate_version_document"),
        sa.ForeignKeyConstraint(["blob_hash"], ["candidate_document_blobs.content_hash"], ondelete="RESTRICT", name="fk_candidate_version_blob"),
        sa.CheckConstraint("version_number > 0", name="ck_candidate_document_version_positive"),
        sa.CheckConstraint("extraction_status = 'NOT_REQUESTED'", name="ck_candidate_document_version_extraction_status"),
    )
    op.create_index("ix_candidate_document_versions_document_ingested", "candidate_document_versions", ["document_id", "ingested_at"])
    op.create_table(
        "candidate_facts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("fact_type", sa.String(length=24), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("value_hash", sa.String(length=64), nullable=False),
        sa.Column("verification_state", sa.String(length=24), server_default="UNREVIEWED", nullable=False),
        sa.Column("supersedes_fact_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_candidate_facts"),
        sa.ForeignKeyConstraint(["supersedes_fact_id"], ["candidate_facts.id"], ondelete="RESTRICT", name="fk_candidate_fact_supersedes"),
        sa.CheckConstraint("fact_type IN ('SKILL', 'EDUCATION', 'EMPLOYMENT', 'PROJECT', 'CERTIFICATION')", name="ck_candidate_fact_type"),
        sa.CheckConstraint("verification_state IN ('UNREVIEWED', 'DOCUMENT_SUPPORTED', 'USER_VERIFIED', 'CONFLICTED', 'REJECTED', 'SUPERSEDED')", name="ck_candidate_fact_verification_state"),
    )
    op.create_table(
        "candidate_fact_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("fact_id", sa.String(length=36), nullable=False),
        sa.Column("document_version_id", sa.String(length=36), nullable=False),
        sa.Column("byte_start", sa.BigInteger(), nullable=False),
        sa.Column("byte_end", sa.BigInteger(), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("method", sa.String(length=32), server_default="LOCAL_API_REPORTED", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_candidate_fact_evidence"),
        sa.ForeignKeyConstraint(["fact_id"], ["candidate_facts.id"], ondelete="RESTRICT", name="fk_candidate_fact_evidence_fact"),
        sa.ForeignKeyConstraint(["document_version_id"], ["candidate_document_versions.id"], ondelete="RESTRICT", name="fk_candidate_fact_evidence_document_version"),
        sa.UniqueConstraint("fact_id", "document_version_id", "byte_start", "byte_end", name="uq_candidate_fact_evidence_span"),
        sa.CheckConstraint("byte_start >= 0", name="ck_candidate_fact_evidence_start_nonnegative"),
        sa.CheckConstraint("byte_end > byte_start", name="ck_candidate_fact_evidence_range"),
    )
    op.create_index("ix_candidate_fact_evidence_fact", "candidate_fact_evidence", ["fact_id"])
    op.create_index("ix_candidate_fact_evidence_version", "candidate_fact_evidence", ["document_version_id"])
    op.execute(
        "INSERT INTO candidate_evidence_storage_usage (id, committed_bytes, reserved_bytes, version, updated_at) "
        "VALUES (1, 0, 0, 1, CURRENT_TIMESTAMP)"
    )


def downgrade() -> None:
    op.drop_index("ix_candidate_fact_evidence_version", table_name="candidate_fact_evidence")
    op.drop_index("ix_candidate_fact_evidence_fact", table_name="candidate_fact_evidence")
    op.drop_table("candidate_fact_evidence")
    op.drop_table("candidate_facts")
    op.drop_index("ix_candidate_document_versions_document_ingested", table_name="candidate_document_versions")
    op.drop_table("candidate_document_versions")
    op.drop_index("ix_candidate_documents_state_created", table_name="candidate_documents")
    op.drop_table("candidate_documents")
    op.drop_table("candidate_evidence_storage_reservations")
    op.drop_table("candidate_evidence_storage_usage")
    op.drop_table("candidate_document_blobs")
