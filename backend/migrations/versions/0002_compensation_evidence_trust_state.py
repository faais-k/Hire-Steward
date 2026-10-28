"""Add explicit evidence verification state to compensation assessments.

Revision ID: 0002_compensation_evidence_trust_state
Revises: 0001_compensation_preference
Create Date: 2026-10-28
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0002_compensation_evidence_trust_state"
down_revision: str | None = "0001_compensation_preference"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing records have caller-supplied evidence and no provenance verifier.
    # The default marks them unverified without rewriting their recorded facts,
    # threshold snapshots, or original assessment fields.
    with op.batch_alter_table("compensation_assessments") as batch_op:
        batch_op.add_column(
            sa.Column(
                "evidence_verification_state",
                sa.String(length=16),
                server_default=sa.text("'UNVERIFIED'"),
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_comp_assess_evidence_verification_state",
            "evidence_verification_state IN ('UNVERIFIED', 'VERIFIED')",
        )


def downgrade() -> None:
    with op.batch_alter_table("compensation_assessments") as batch_op:
        batch_op.drop_constraint(
            "ck_comp_assess_evidence_verification_state", type_="check"
        )
        batch_op.drop_column("evidence_verification_state")
