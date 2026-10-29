from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
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
    explanation: Mapped[Text] = mapped_column(Text, nullable=False)
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


class JobSource(Base):
    __tablename__ = "job_sources"
    __table_args__ = (
        PrimaryKeyConstraint("source_name", name="pk_job_sources"),
        CheckConstraint(
            "capability_status IN ('NEEDS_REVIEW', 'VERIFIED_READ_ONLY', 'MANUAL_ONLY', 'BLOCKED', 'DISABLED_BY_USER')",
            name="ck_job_sources_status",
        ),
        CheckConstraint(
            "(is_enabled = TRUE AND capability_status = 'VERIFIED_READ_ONLY') OR (is_enabled = FALSE)",
            name="ck_job_sources_active_gate",
        ),
        CheckConstraint(
            "rate_limit_requests_per_minute > 0 AND min_poll_interval_seconds >= 60",
            name="ck_job_sources_rate_positive",
        ),
    )

    source_name: Mapped[str] = mapped_column(String(32), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    capability_status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="NEEDS_REVIEW"
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=func.false()
    )
    terms_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terms_review_reference: Mapped[str | None] = mapped_column(String(256))
    rate_limit_requests_per_minute: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="10"
    )
    min_poll_interval_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="43200"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class EmployerSubscription(Base):
    __tablename__ = "employer_subscriptions"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_employer_subscriptions"),
        ForeignKeyConstraint(
            ["source_name"], ["job_sources.source_name"],
            ondelete="RESTRICT", name="fk_subscriptions_source",
        ),
        UniqueConstraint("source_name", "employer_handle", name="uq_employer_subscriptions_identity"),
        CheckConstraint(
            "employer_handle ~ '^[a-z0-9][a-z0-9_-]{0,127}$' AND employer_handle NOT IN ('.', '..')",
            name="ck_subscriptions_handle_format",
        ),
        CheckConstraint(
            "(lease_token IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_subscriptions_lease_pair",
        ),
        Index("ix_subscriptions_pollable", "is_enabled", "source_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_name: Mapped[str] = mapped_column(String(32), nullable=False)
    employer_handle: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128))
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=func.true()
    )
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DiscoveryCheckpoint(Base):
    __tablename__ = "discovery_checkpoints"
    __table_args__ = (
        PrimaryKeyConstraint("subscription_id", name="pk_discovery_checkpoints"),
        ForeignKeyConstraint(
            ["subscription_id"], ["employer_subscriptions.id"],
            ondelete="CASCADE", name="fk_checkpoints_subscription",
        ),
        CheckConstraint("consecutive_failure_count >= 0", name="ck_checkpoints_failures_nonneg"),
        CheckConstraint(
            "(circuit_breaker_tripped = FALSE AND circuit_breaker_reason IS NULL AND circuit_breaker_tripped_at IS NULL) OR "
            "(circuit_breaker_tripped = TRUE AND circuit_breaker_reason IS NOT NULL AND circuit_breaker_tripped_at IS NOT NULL)",
            name="ck_checkpoints_cb_consistency",
        ),
    )

    subscription_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    last_successful_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failure_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    circuit_breaker_tripped: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=func.false()
    )
    circuit_breaker_reason: Mapped[str | None] = mapped_column(String(64))
    circuit_breaker_tripped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_discovery_runs"),
        ForeignKeyConstraint(
            ["subscription_id"], ["employer_subscriptions.id"],
            ondelete="RESTRICT", name="fk_discovery_runs_subscription",
        ),
        UniqueConstraint("id", "subscription_id", name="uq_discovery_runs_id_subscription"),
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'INTERRUPTED', 'SKIPPED_CONCURRENT_LEASE')",
            name="ck_discovery_runs_status",
        ),
        CheckConstraint("page_limit >= 1 AND page_limit <= 100", name="ck_discovery_runs_page_limit"),
        CheckConstraint(
            "current_skip >= 0 AND current_page_index >= 0",
            name="ck_discovery_runs_skip_nonneg",
        ),
        CheckConstraint(
            "items_seen_count >= 0 AND items_new_count >= 0 AND items_updated_count >= 0 AND items_duplicate_count >= 0",
            name="ck_discovery_runs_counts_nonneg",
        ),
        CheckConstraint(
            "(status IN ('SUCCEEDED', 'FAILED', 'INTERRUPTED', 'SKIPPED_CONCURRENT_LEASE') AND finished_at IS NOT NULL) OR "
            "(status IN ('PENDING', 'RUNNING') AND finished_at IS NULL)",
            name="ck_discovery_runs_termination",
        ),
        Index("ix_discovery_runs_sub_started", "subscription_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subscription_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(
        String(28), nullable=False, server_default="PENDING"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_skip: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    current_page_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    page_limit: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")
    items_seen_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    items_new_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    items_updated_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    items_duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message_redacted: Mapped[str | None] = mapped_column(Text)


class JobPosting(Base):
    __tablename__ = "job_postings"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_job_postings"),
        ForeignKeyConstraint(
            ["subscription_id"], ["employer_subscriptions.id"],
            ondelete="RESTRICT", name="fk_job_postings_subscription",
        ),
        UniqueConstraint("subscription_id", "posting_id", name="uq_job_postings_identity"),
        UniqueConstraint("id", "subscription_id", name="uq_job_postings_id_subscription"),
        ForeignKeyConstraint(
            ["last_seen_run_id", "subscription_id"],
            ["discovery_runs.id", "discovery_runs.subscription_id"],
            ondelete="RESTRICT",
            name="fk_job_postings_run_composite",
        ),
        CheckConstraint("posting_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'", name="ck_job_postings_posting_id"),
        CheckConstraint("current_raw_hash ~ '^[0-9a-f]{64}$'", name="ck_job_postings_hash_format"),
        CheckConstraint(
            "lifecycle_status IN ('ACTIVE', 'REMOVED', 'STALE', 'UNKNOWN', 'CLOSED_CONFIRMED')",
            name="ck_job_postings_lifecycle",
        ),
        CheckConstraint("consecutive_misses_count >= 0", name="ck_job_postings_misses_nonneg"),
        CheckConstraint("version >= 1", name="ck_job_postings_version_positive"),
        Index("ix_job_postings_sub_status", "subscription_id", "lifecycle_status"),
        Index("ix_job_postings_last_observed", "last_observed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subscription_id: Mapped[str] = mapped_column(String(36), nullable=False)
    posting_id: Mapped[str] = mapped_column(String(128), nullable=False)
    current_raw_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="ACTIVE"
    )
    consecutive_misses_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_run_id: Mapped[str] = mapped_column(String(36), nullable=False)


class JobPostingSnapshot(Base):
    __tablename__ = "job_posting_snapshots"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_job_posting_snapshots"),
        ForeignKeyConstraint(
            ["posting_id", "subscription_id"],
            ["job_postings.id", "job_postings.subscription_id"],
            ondelete="RESTRICT",
            name="fk_snapshots_posting_composite",
        ),
        ForeignKeyConstraint(
            ["run_id", "subscription_id"],
            ["discovery_runs.id", "discovery_runs.subscription_id"],
            ondelete="RESTRICT",
            name="fk_snapshots_run_composite",
        ),
        UniqueConstraint("posting_id", "source_raw_hash", name="uq_snapshots_posting_hash"),
        CheckConstraint("length(trim(title)) > 0", name="ck_snapshots_title_nonempty"),
        CheckConstraint("source_raw_hash ~ '^[0-9a-f]{64}$'", name="ck_snapshots_hash_format"),
        CheckConstraint(
            "publication_date_status IN ('EXACT', 'UNKNOWN', 'INVALID')",
            name="ck_snapshots_pub_status",
        ),
        CheckConstraint(
            "(publication_date_status = 'EXACT' AND published_at IS NOT NULL) OR "
            "(publication_date_status IN ('UNKNOWN', 'INVALID') AND published_at IS NULL)",
            name="ck_snapshots_pub_exact",
        ),
        Index("ix_snapshots_posting_captured", "posting_id", "captured_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subscription_id: Mapped[str] = mapped_column(String(36), nullable=False)
    posting_id: Mapped[str] = mapped_column(String(36), nullable=False)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_raw_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    location: Mapped[str | None] = mapped_column(String(256))
    commitment: Mapped[str | None] = mapped_column(String(64))
    team: Mapped[str | None] = mapped_column(String(128))
    department: Mapped[str | None] = mapped_column(String(128))
    level: Mapped[str | None] = mapped_column(String(64))
    workplace_type: Mapped[str | None] = mapped_column(String(64))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publication_date_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="UNKNOWN"
    )
    raw_created_at_ms: Mapped[int | None] = mapped_column(BigInteger)
    canonical_url: Mapped[str | None] = mapped_column(String(2048))
    apply_url: Mapped[str | None] = mapped_column(String(2048))
    description_plain: Mapped[str] = mapped_column(Text, nullable=False)
    description_html: Mapped[str | None] = mapped_column(Text)
    lists_json: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, server_default="[]")
    additional_plain: Mapped[str | None] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TrackedApplication(Base):
    __tablename__ = "tracked_applications"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_tracked_applications"),
        UniqueConstraint("job_posting_id", name="uq_tracked_applications_posting"),
        ForeignKeyConstraint(
            ["job_posting_id"],
            ["job_postings.id"],
            ondelete="RESTRICT",
            name="fk_tracked_applications_posting",
        ),
        CheckConstraint(
            "status IN ('SAVED', 'PREPARING', 'READY_FOR_REVIEW', 'APPLIED', 'INTERVIEWING', 'OFFER_RECEIVED', 'REJECTED', 'WITHDRAWN', 'ARCHIVED')",
            name="ck_tracked_applications_status",
        ),
        CheckConstraint("version >= 1", name="ck_tracked_applications_version_positive"),
        Index("ix_tracked_applications_status", "status"),
        Index("ix_tracked_applications_updated_at", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_posting_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="SAVED")
    notes: Mapped[str | None] = mapped_column(Text)
    follow_up_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_interview_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status_change_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    submitted_resume_snapshot: Mapped[str | None] = mapped_column(Text)
    submitted_cover_letter_snapshot: Mapped[str | None] = mapped_column(Text)
    submitted_resume_sha256: Mapped[str | None] = mapped_column(String(64))
    submitted_cover_letter_sha256: Mapped[str | None] = mapped_column(String(64))
    reviewed_resume_markdown: Mapped[str | None] = mapped_column(Text)
    reviewed_cover_letter_markdown: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ApplicationStatusHistory(Base):
    __tablename__ = "application_status_history"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_application_status_history"),
        ForeignKeyConstraint(
            ["application_id"],
            ["tracked_applications.id"],
            ondelete="CASCADE",
            name="fk_app_status_history_application",
        ),
        CheckConstraint(
            "to_status IN ('SAVED', 'PREPARING', 'READY_FOR_REVIEW', 'APPLIED', 'INTERVIEWING', 'OFFER_RECEIVED', 'REJECTED', 'WITHDRAWN', 'ARCHIVED')",
            name="ck_app_status_history_to_status",
        ),
        CheckConstraint(
            "from_status IS NULL OR from_status IN ('SAVED', 'PREPARING', 'READY_FOR_REVIEW', 'APPLIED', 'INTERVIEWING', 'OFFER_RECEIVED', 'REJECTED', 'WITHDRAWN', 'ARCHIVED')",
            name="ck_app_status_history_from_status",
        ),
        Index("ix_app_status_history_app_id", "application_id"),
        Index("ix_app_status_history_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    application_id: Mapped[str] = mapped_column(String(36), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    transition_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
