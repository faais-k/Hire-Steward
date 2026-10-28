"""Add job discovery persistence and observation models.

Revision ID: 0004_job_discovery_persistence
Revises: 0003_candidate_evidence
Create Date: 2026-10-28

Downgrade intentionally drops all job discovery persistence tables and snapshots.
Only use it with disposable data or after an explicit export/removal decision.
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0004_job_discovery_persistence"
down_revision: str | None = "0003_candidate_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    handle_format_expr = (
        "length(employer_handle) > 0 AND employer_handle NOT IN ('.', '..')"
        if is_sqlite
        else "employer_handle ~ '^[a-z0-9][a-z0-9_-]{0,127}$' AND employer_handle NOT IN ('.', '..')"
    )
    posting_id_expr = (
        "length(posting_id) > 0"
        if is_sqlite
        else "posting_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'"
    )
    current_hash_expr = (
        "length(current_raw_hash) = 64"
        if is_sqlite
        else "current_raw_hash ~ '^[0-9a-f]{64}$'"
    )
    source_hash_expr = (
        "length(source_raw_hash) = 64"
        if is_sqlite
        else "source_raw_hash ~ '^[0-9a-f]{64}$'"
    )

    # 1. job_sources
    op.create_table(
        "job_sources",
        sa.Column("source_name", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=False),
        sa.Column("capability_status", sa.String(length=24), server_default="NEEDS_REVIEW", nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("FALSE"), nullable=False),
        sa.Column("terms_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terms_review_reference", sa.String(length=256), nullable=True),
        sa.Column("rate_limit_requests_per_minute", sa.Integer(), server_default="10", nullable=False),
        sa.Column("min_poll_interval_seconds", sa.Integer(), server_default="43200", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("source_name", name="pk_job_sources"),
        sa.CheckConstraint(
            "capability_status IN ('NEEDS_REVIEW', 'VERIFIED_READ_ONLY', 'MANUAL_ONLY', 'BLOCKED', 'DISABLED_BY_USER')",
            name="ck_job_sources_status",
        ),
        sa.CheckConstraint(
            "(is_enabled = TRUE AND capability_status = 'VERIFIED_READ_ONLY') OR (is_enabled = FALSE)",
            name="ck_job_sources_active_gate",
        ),
        sa.CheckConstraint(
            "rate_limit_requests_per_minute > 0 AND min_poll_interval_seconds >= 60",
            name="ck_job_sources_rate_positive",
        ),
    )

    # 2. employer_subscriptions
    op.create_table(
        "employer_subscriptions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_name", sa.String(length=32), nullable=False),
        sa.Column("employer_handle", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("TRUE"), nullable=False),
        sa.Column("lease_token", sa.String(length=36), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_employer_subscriptions"),
        sa.ForeignKeyConstraint(
            ["source_name"],
            ["job_sources.source_name"],
            ondelete="RESTRICT",
            name="fk_subscriptions_source",
        ),
        sa.UniqueConstraint("source_name", "employer_handle", name="uq_employer_subscriptions_identity"),
        sa.CheckConstraint(
            handle_format_expr,
            name="ck_subscriptions_handle_format",
        ),
        sa.CheckConstraint(
            "(lease_token IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_subscriptions_lease_pair",
        ),
    )
    op.create_index("ix_subscriptions_pollable", "employer_subscriptions", ["is_enabled", "source_name"])

    # 3. discovery_checkpoints
    op.create_table(
        "discovery_checkpoints",
        sa.Column("subscription_id", sa.String(length=36), nullable=False),
        sa.Column("last_successful_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failure_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("circuit_breaker_tripped", sa.Boolean(), server_default=sa.text("FALSE"), nullable=False),
        sa.Column("circuit_breaker_reason", sa.String(length=64), nullable=True),
        sa.Column("circuit_breaker_tripped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("subscription_id", name="pk_discovery_checkpoints"),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["employer_subscriptions.id"],
            ondelete="CASCADE",
            name="fk_checkpoints_subscription",
        ),
        sa.CheckConstraint("consecutive_failure_count >= 0", name="ck_checkpoints_failures_nonneg"),
        sa.CheckConstraint(
            "(circuit_breaker_tripped = FALSE AND circuit_breaker_reason IS NULL AND circuit_breaker_tripped_at IS NULL) OR "
            "(circuit_breaker_tripped = TRUE AND circuit_breaker_reason IS NOT NULL AND circuit_breaker_tripped_at IS NOT NULL)",
            name="ck_checkpoints_cb_consistency",
        ),
    )

    # 4. discovery_runs
    op.create_table(
        "discovery_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("subscription_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=28), server_default="PENDING", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_skip", sa.Integer(), server_default="0", nullable=False),
        sa.Column("current_page_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("page_limit", sa.Integer(), server_default="100", nullable=False),
        sa.Column("items_seen_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("items_new_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("items_updated_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("items_duplicate_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message_redacted", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_discovery_runs"),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["employer_subscriptions.id"],
            ondelete="RESTRICT",
            name="fk_discovery_runs_subscription",
        ),
        sa.UniqueConstraint("id", "subscription_id", name="uq_discovery_runs_id_subscription"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'INTERRUPTED', 'SKIPPED_CONCURRENT_LEASE')",
            name="ck_discovery_runs_status",
        ),
        sa.CheckConstraint("page_limit >= 1 AND page_limit <= 100", name="ck_discovery_runs_page_limit"),
        sa.CheckConstraint(
            "current_skip >= 0 AND current_page_index >= 0",
            name="ck_discovery_runs_skip_nonneg",
        ),
        sa.CheckConstraint(
            "items_seen_count >= 0 AND items_new_count >= 0 AND items_updated_count >= 0 AND items_duplicate_count >= 0",
            name="ck_discovery_runs_counts_nonneg",
        ),
        sa.CheckConstraint(
            "(status IN ('SUCCEEDED', 'FAILED', 'INTERRUPTED', 'SKIPPED_CONCURRENT_LEASE') AND finished_at IS NOT NULL) OR "
            "(status IN ('PENDING', 'RUNNING') AND finished_at IS NULL)",
            name="ck_discovery_runs_termination",
        ),
    )
    op.create_index("ix_discovery_runs_sub_started", "discovery_runs", ["subscription_id", "started_at"])

    # 5. job_postings
    op.create_table(
        "job_postings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("subscription_id", sa.String(length=36), nullable=False),
        sa.Column("posting_id", sa.String(length=128), nullable=False),
        sa.Column("current_raw_hash", sa.String(length=64), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=24), server_default="ACTIVE", nullable=False),
        sa.Column("consecutive_misses_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("last_seen_run_id", sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_job_postings"),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["employer_subscriptions.id"],
            ondelete="RESTRICT",
            name="fk_job_postings_subscription",
        ),
        sa.UniqueConstraint("subscription_id", "posting_id", name="uq_job_postings_identity"),
        sa.UniqueConstraint("id", "subscription_id", name="uq_job_postings_id_subscription"),
        sa.ForeignKeyConstraint(
            ["last_seen_run_id", "subscription_id"],
            ["discovery_runs.id", "discovery_runs.subscription_id"],
            ondelete="RESTRICT",
            name="fk_job_postings_run_composite",
        ),
        sa.CheckConstraint(posting_id_expr, name="ck_job_postings_posting_id"),
        sa.CheckConstraint(current_hash_expr, name="ck_job_postings_hash_format"),
        sa.CheckConstraint(
            "lifecycle_status IN ('ACTIVE', 'REMOVED', 'STALE', 'UNKNOWN', 'CLOSED_CONFIRMED')",
            name="ck_job_postings_lifecycle",
        ),
        sa.CheckConstraint("consecutive_misses_count >= 0", name="ck_job_postings_misses_nonneg"),
        sa.CheckConstraint("version >= 1", name="ck_job_postings_version_positive"),
    )
    op.create_index("ix_job_postings_sub_status", "job_postings", ["subscription_id", "lifecycle_status"])
    op.create_index("ix_job_postings_last_observed", "job_postings", ["last_observed_at"])

    # 6. job_posting_snapshots
    op.create_table(
        "job_posting_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("subscription_id", sa.String(length=36), nullable=False),
        sa.Column("posting_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("source_raw_hash", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("location", sa.String(length=256), nullable=True),
        sa.Column("commitment", sa.String(length=64), nullable=True),
        sa.Column("team", sa.String(length=128), nullable=True),
        sa.Column("department", sa.String(length=128), nullable=True),
        sa.Column("level", sa.String(length=64), nullable=True),
        sa.Column("workplace_type", sa.String(length=64), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publication_date_status", sa.String(length=16), server_default="UNKNOWN", nullable=False),
        sa.Column("raw_created_at_ms", sa.BigInteger(), nullable=True),
        sa.Column("canonical_url", sa.String(length=2048), nullable=True),
        sa.Column("apply_url", sa.String(length=2048), nullable=True),
        sa.Column("description_plain", sa.Text(), nullable=False),
        sa.Column("description_html", sa.Text(), nullable=True),
        sa.Column("lists_json", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("additional_plain", sa.Text(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_job_posting_snapshots"),
        sa.ForeignKeyConstraint(
            ["posting_id", "subscription_id"],
            ["job_postings.id", "job_postings.subscription_id"],
            ondelete="RESTRICT",
            name="fk_snapshots_posting_composite",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "subscription_id"],
            ["discovery_runs.id", "discovery_runs.subscription_id"],
            ondelete="RESTRICT",
            name="fk_snapshots_run_composite",
        ),
        sa.UniqueConstraint("posting_id", "source_raw_hash", name="uq_snapshots_posting_hash"),
        sa.CheckConstraint("length(trim(title)) > 0", name="ck_snapshots_title_nonempty"),
        sa.CheckConstraint(source_hash_expr, name="ck_snapshots_hash_format"),
        sa.CheckConstraint(
            "publication_date_status IN ('EXACT', 'UNKNOWN', 'INVALID')",
            name="ck_snapshots_pub_status",
        ),
        sa.CheckConstraint(
            "(publication_date_status = 'EXACT' AND published_at IS NOT NULL) OR "
            "(publication_date_status IN ('UNKNOWN', 'INVALID') AND published_at IS NULL)",
            name="ck_snapshots_pub_exact",
        ),
    )
    op.create_index("ix_snapshots_posting_captured", "job_posting_snapshots", ["posting_id", "captured_at"])

    # Seed initial source: Lever in NEEDS_REVIEW and disabled
    job_sources_table = sa.table(
        "job_sources",
        sa.column("source_name", sa.String),
        sa.column("display_name", sa.String),
        sa.column("capability_status", sa.String),
        sa.column("is_enabled", sa.Boolean),
        sa.column("terms_reviewed_at", sa.DateTime),
        sa.column("terms_review_reference", sa.String),
        sa.column("rate_limit_requests_per_minute", sa.Integer),
        sa.column("min_poll_interval_seconds", sa.Integer),
    )
    op.bulk_insert(
        job_sources_table,
        [
            {
                "source_name": "lever",
                "display_name": "Lever Postings API",
                "capability_status": "NEEDS_REVIEW",
                "is_enabled": False,
                "terms_reviewed_at": None,
                "terms_review_reference": None,
                "rate_limit_requests_per_minute": 10,
                "min_poll_interval_seconds": 43200,
            }
        ],
    )

    # Immutability trigger on job_posting_snapshots for PostgreSQL
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION trg_fn_prevent_job_posting_snapshot_mutation()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'job_posting_snapshots rows are immutable and cannot be updated or deleted';
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER trg_job_posting_snapshots_immutable
            BEFORE UPDATE OR DELETE ON job_posting_snapshots
            FOR EACH ROW
            EXECUTE FUNCTION trg_fn_prevent_job_posting_snapshot_mutation();
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            DROP TRIGGER IF EXISTS trg_job_posting_snapshots_immutable ON job_posting_snapshots;
            DROP FUNCTION IF EXISTS trg_fn_prevent_job_posting_snapshot_mutation();
            """
        )

    op.drop_index("ix_snapshots_posting_captured", table_name="job_posting_snapshots")
    op.drop_table("job_posting_snapshots")
    op.drop_index("ix_job_postings_last_observed", table_name="job_postings")
    op.drop_index("ix_job_postings_sub_status", table_name="job_postings")
    op.drop_table("job_postings")
    op.drop_index("ix_discovery_runs_sub_started", table_name="discovery_runs")
    op.drop_table("discovery_runs")
    op.drop_table("discovery_checkpoints")
    op.drop_index("ix_subscriptions_pollable", table_name="employer_subscriptions")
    op.drop_table("employer_subscriptions")
    op.drop_table("job_sources")
