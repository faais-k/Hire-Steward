"""Add durable background tasks, workers, and task runs tables.

Revision ID: 0010_background_tasks
Revises: 0009_binary_docs_attempts
Create Date: 2026-11-10
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0010_background_tasks"
down_revision: str | None = "0009_binary_docs_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -------------------------------------------------------------
    # 1. background_tasks: durable task queue
    # -------------------------------------------------------------
    op.create_table(
        "background_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("priority", sa.Integer(), server_default="100", nullable=False),
        sa.Column("status", sa.String(length=24), server_default="PENDING", nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column(
            "scheduled_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("backoff_base_seconds", sa.Integer(), server_default="10", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("lease_token", sa.String(length=36), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(length=64), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_background_tasks"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED', 'PAUSED')",
            name="ck_background_tasks_status",
        ),
        sa.CheckConstraint("attempts_count >= 0", name="ck_background_tasks_attempts_count"),
        sa.CheckConstraint("max_attempts >= 1", name="ck_background_tasks_max_attempts"),
        sa.CheckConstraint(
            "backoff_base_seconds >= 1", name="ck_background_tasks_backoff_base_seconds"
        ),
    )
    op.create_index("ix_background_tasks_task_type", "background_tasks", ["task_type"])
    op.create_index("ix_background_tasks_priority", "background_tasks", ["priority"])
    op.create_index("ix_background_tasks_status", "background_tasks", ["status"])
    op.create_index("ix_background_tasks_scheduled_at", "background_tasks", ["scheduled_at"])
    op.create_index(
        "ix_background_tasks_lease_expires_at", "background_tasks", ["lease_expires_at"]
    )
    op.create_index(
        "ix_background_tasks_idempotency_key",
        "background_tasks",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_background_tasks_status_sched_prio",
        "background_tasks",
        ["status", "scheduled_at", "priority"],
    )

    # -------------------------------------------------------------
    # 2. background_workers: worker heartbeats and lifecycle registry
    # -------------------------------------------------------------
    op.create_table(
        "background_workers",
        sa.Column("worker_id", sa.String(length=64), nullable=False),
        sa.Column("hostname", sa.String(length=128), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="ACTIVE", nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "last_heartbeat_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("current_task_id", sa.String(length=36), nullable=True),
        sa.PrimaryKeyConstraint("worker_id", name="pk_background_workers"),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'PAUSED', 'STOPPED', 'DRAINING')",
            name="ck_background_workers_status",
        ),
    )
    op.create_index(
        "ix_background_workers_last_heartbeat_at",
        "background_workers",
        ["last_heartbeat_at"],
    )

    # -------------------------------------------------------------
    # 3. background_task_runs: run history ledger
    # -------------------------------------------------------------
    op.create_table(
        "background_task_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("worker_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_background_task_runs"),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["background_tasks.id"],
            name="fk_background_task_runs_task_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "attempt_number >= 1", name="ck_background_task_runs_attempt_number"
        ),
        sa.CheckConstraint("duration_ms >= 0", name="ck_background_task_runs_duration_ms"),
    )
    op.create_index(
        "ix_background_task_runs_task_id",
        "background_task_runs",
        ["task_id"],
    )


def downgrade() -> None:
    # Reverse dependency order teardown
    op.drop_index("ix_background_task_runs_task_id", table_name="background_task_runs")
    op.drop_table("background_task_runs")

    op.drop_index(
        "ix_background_workers_last_heartbeat_at", table_name="background_workers"
    )
    op.drop_table("background_workers")

    op.drop_index("ix_background_tasks_status_sched_prio", table_name="background_tasks")
    op.drop_index("ix_background_tasks_idempotency_key", table_name="background_tasks")
    op.drop_index("ix_background_tasks_lease_expires_at", table_name="background_tasks")
    op.drop_index("ix_background_tasks_scheduled_at", table_name="background_tasks")
    op.drop_index("ix_background_tasks_status", table_name="background_tasks")
    op.drop_index("ix_background_tasks_priority", table_name="background_tasks")
    op.drop_index("ix_background_tasks_task_type", table_name="background_tasks")
    op.drop_table("background_tasks")
