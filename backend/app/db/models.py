from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
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


class CandidateDocumentBlob(Base):
    __tablename__ = "candidate_document_blobs"
    __table_args__ = (
        PrimaryKeyConstraint("content_hash", name="pk_candidate_document_blobs"),
        UniqueConstraint("storage_key", name="uq_candidate_document_blobs_storage_key"),
        CheckConstraint("length(content_hash) = 64", name="ck_candidate_blob_hash_length"),
        CheckConstraint("byte_size > 0", name="ck_candidate_blob_size_positive"),
        CheckConstraint("media_type = 'text/plain'", name="ck_candidate_blob_media_type"),
    )

    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    storage_key: Mapped[str] = mapped_column(String(96), nullable=False)
    media_type: Mapped[str] = mapped_column(String(32), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CandidateEvidenceStorageUsage(Base):
    __tablename__ = "candidate_evidence_storage_usage"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_candidate_evidence_storage_usage"),
        CheckConstraint("id = 1", name="ck_candidate_usage_singleton"),
        CheckConstraint("committed_bytes >= 0", name="ck_candidate_usage_committed_nonnegative"),
        CheckConstraint("reserved_bytes >= 0", name="ck_candidate_usage_reserved_nonnegative"),
        CheckConstraint("version >= 1", name="ck_candidate_usage_version_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    committed_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reserved_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CandidateEvidenceStorageReservation(Base):
    __tablename__ = "candidate_evidence_storage_reservations"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_candidate_evidence_storage_reservations"),
        UniqueConstraint("temp_key", name="uq_candidate_evidence_storage_reservations_temp_key"),
        CheckConstraint("reserved_bytes > 0", name="ck_candidate_reservation_size_positive"),
        CheckConstraint(
            "state IN ('STAGING', 'READY_TO_PLACE', 'PLACED')",
            name="ck_candidate_reservation_state",
        ),
        CheckConstraint(
            "actual_size IS NULL OR actual_size > 0",
            name="ck_candidate_reservation_actual_size_positive",
        ),
        CheckConstraint(
            "(state = 'STAGING' AND content_hash IS NULL AND final_key IS NULL AND actual_size IS NULL) OR "
            "(state IN ('READY_TO_PLACE', 'PLACED') AND content_hash IS NOT NULL "
            "AND final_key IS NOT NULL AND actual_size IS NOT NULL)",
            name="ck_candidate_reservation_state_fields",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reserved_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    temp_key: Mapped[str] = mapped_column(String(96), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    final_key: Mapped[str | None] = mapped_column(String(96))
    actual_size: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CandidateDocument(Base):
    __tablename__ = "candidate_documents"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_candidate_documents"),
        CheckConstraint("state IN ('ACTIVE', 'RETIRED')", name="ck_candidate_document_state"),
        Index("ix_candidate_documents_state_created", "state", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CandidateDocumentVersion(Base):
    __tablename__ = "candidate_document_versions"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_candidate_document_versions"),
        CheckConstraint("version_number > 0", name="ck_candidate_document_version_positive"),
        CheckConstraint(
            "extraction_status = 'NOT_REQUESTED'",
            name="ck_candidate_document_version_extraction_status",
        ),
        ForeignKeyConstraint(
            ["document_id"], ["candidate_documents.id"],
            ondelete="RESTRICT", name="fk_candidate_version_document",
        ),
        ForeignKeyConstraint(
            ["blob_hash"], ["candidate_document_blobs.content_hash"],
            ondelete="RESTRICT", name="fk_candidate_version_blob",
        ),
        UniqueConstraint("document_id", "version_number", name="uq_candidate_document_version_number"),
        UniqueConstraint("document_id", "blob_hash", name="uq_candidate_document_version_blob"),
        Index("ix_candidate_document_versions_document_ingested", "document_id", "ingested_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    blob_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(128), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    extraction_status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="NOT_REQUESTED")
    extraction_error_code: Mapped[str | None] = mapped_column(String(64))
    extractor_version: Mapped[str | None] = mapped_column(String(64))


class CandidateFact(Base):
    __tablename__ = "candidate_facts"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_candidate_facts"),
        CheckConstraint(
            "fact_type IN ('SKILL', 'EDUCATION', 'EMPLOYMENT', 'PROJECT', 'CERTIFICATION')",
            name="ck_candidate_fact_type",
        ),
        CheckConstraint(
            "verification_state IN ('UNREVIEWED', 'DOCUMENT_SUPPORTED', 'USER_VERIFIED', "
            "'CONFLICTED', 'REJECTED', 'SUPERSEDED')",
            name="ck_candidate_fact_verification_state",
        ),
        ForeignKeyConstraint(
            ["supersedes_fact_id"], ["candidate_facts.id"],
            ondelete="RESTRICT", name="fk_candidate_fact_supersedes",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fact_type: Mapped[str] = mapped_column(String(24), nullable=False)
    value_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    value_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_state: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="UNREVIEWED"
    )
    supersedes_fact_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CandidateFactEvidence(Base):
    __tablename__ = "candidate_fact_evidence"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_candidate_fact_evidence"),
        CheckConstraint("byte_start >= 0", name="ck_candidate_fact_evidence_start_nonnegative"),
        CheckConstraint("byte_end > byte_start", name="ck_candidate_fact_evidence_range"),
        ForeignKeyConstraint(
            ["fact_id"], ["candidate_facts.id"],
            ondelete="RESTRICT", name="fk_candidate_fact_evidence_fact",
        ),
        ForeignKeyConstraint(
            ["document_version_id"], ["candidate_document_versions.id"],
            ondelete="RESTRICT",
            name="fk_candidate_fact_evidence_document_version",
        ),
        UniqueConstraint(
            "fact_id",
            "document_version_id",
            "byte_start",
            "byte_end",
            name="uq_candidate_fact_evidence_span",
        ),
        Index("ix_candidate_fact_evidence_fact", "fact_id"),
        Index("ix_candidate_fact_evidence_version", "document_version_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fact_id: Mapped[str] = mapped_column(String(36), nullable=False)
    document_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    byte_start: Mapped[int] = mapped_column(BigInteger, nullable=False)
    byte_end: Mapped[int] = mapped_column(BigInteger, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False, server_default="LOCAL_API_REPORTED")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
