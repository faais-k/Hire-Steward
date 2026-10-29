from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import (
    CandidateFact,
    CandidateFactEvidence,
    JobPosting,
    JobPostingSnapshot,
)
from backend.app.domain.candidate_evidence import FactVerificationState
from backend.app.domain.job_matching import (
    CandidateEvidenceItem,
    JobMatchAssessment,
    ProvenanceReference,
    assess_job_match,
)


class JobMatchingServiceError(Exception):
    """Base error for job matching operations."""

    def __init__(self, message: str, code: str) -> None:
        self.message = message
        self.code = code
        super().__init__(message)


def load_candidate_evidence(
    session: Session,
    fact_ids: list[str] | None = None,
) -> list[CandidateEvidenceItem]:
    """Load active candidate facts and their provenance from the database."""
    query = select(CandidateFact).where(
        CandidateFact.verification_state.not_in([
            FactVerificationState.SUPERSEDED.value,
            FactVerificationState.REJECTED.value,
        ])
    )
    if fact_ids is not None:
        query = query.where(CandidateFact.id.in_(fact_ids))

    facts = list(session.scalars(query.order_by(CandidateFact.created_at.asc())))
    if not facts:
        return []

    fact_ids_list = [f.id for f in facts]
    evidence_query = select(CandidateFactEvidence).where(
        CandidateFactEvidence.fact_id.in_(fact_ids_list)
    )
    evidence_records = list(session.scalars(evidence_query))

    evidence_by_fact: dict[str, list[ProvenanceReference]] = {f_id: [] for f_id in fact_ids_list}
    for ev in evidence_records:
        evidence_by_fact[ev.fact_id].append(
            ProvenanceReference(
                provenance_id=ev.id,
                document_version_id=ev.document_version_id,
                byte_start=ev.byte_start,
                byte_end=ev.byte_end,
                evidence_hash=ev.evidence_hash,
                method=ev.method,
            )
        )

    evidence_items: list[CandidateEvidenceItem] = []
    for f in facts:
        is_conflicted = (f.verification_state == FactVerificationState.CONFLICTED.value)
        evidence_items.append(
            CandidateEvidenceItem(
                fact_id=f.id,
                fact_type=f.fact_type,
                value=f.value_json,
                verification_state=f.verification_state,
                is_active=True,
                is_conflicted=is_conflicted,
                provenance=evidence_by_fact.get(f.id, []),
            )
        )

    return evidence_items


def evaluate_job_posting_match(
    session: Session,
    posting_id: str,
    fact_ids: list[str] | None = None,
) -> JobMatchAssessment:
    """Evaluate match between a persisted job posting and candidate evidence.

    1. Loads the job posting and its latest snapshot.
    2. Loads candidate facts and their document provenance.
    3. Runs deterministic assessment.
    """
    posting = session.get(JobPosting, posting_id)
    if posting is None:
        raise JobMatchingServiceError(f"Job posting '{posting_id}' not found", "POSTING_NOT_FOUND")

    snapshot = session.scalar(
        select(JobPostingSnapshot)
        .where(JobPostingSnapshot.posting_id == posting_id)
        .order_by(JobPostingSnapshot.captured_at.desc())
        .limit(1)
    )
    if snapshot is None:
        raise JobMatchingServiceError(f"No snapshot found for posting '{posting_id}'", "SNAPSHOT_NOT_FOUND")

    candidate_evidence = load_candidate_evidence(session, fact_ids=fact_ids)

    return assess_job_match(
        posting_id=posting.id,
        snapshot_id=snapshot.id,
        lists_json=snapshot.lists_json,
        description_plain=snapshot.description_plain,
        workplace_type=snapshot.workplace_type,
        location=snapshot.location,
        candidate_evidence=candidate_evidence,
    )

def evaluate_snapshot_match(
    snapshot: JobPostingSnapshot,
    candidate_evidence: list[CandidateEvidenceItem],
) -> JobMatchAssessment:
    """Evaluate match directly against an in-memory or loaded snapshot instance."""
    return assess_job_match(
        posting_id=snapshot.posting_id,
        snapshot_id=snapshot.id,
        lists_json=snapshot.lists_json,
        description_plain=snapshot.description_plain,
        workplace_type=snapshot.workplace_type,
        location=snapshot.location,
        candidate_evidence=candidate_evidence,
    )
