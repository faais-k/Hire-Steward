"""Service layer for evidence-grounded application preparation.

Loads job postings, snapshots, and candidate evidence to assemble
deterministic tailored resumes, cover letters, and traceability records.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import EmployerSubscription, JobPosting, JobPostingSnapshot
from backend.app.domain.application_preparation import (
    ApplicationDraft,
    ApplicationPreparationError,
    build_application_draft,
)
from backend.app.services.job_matching import load_candidate_evidence


def prepare_application_draft(
    session: Session,
    posting_id: str,
    fact_ids: list[str] | None = None,
) -> ApplicationDraft:
    """Prepare a deterministic, evidence-grounded application draft for a job posting.

    1. Loads the job posting and its employer subscription.
    2. Loads the latest job posting snapshot.
    3. Loads active candidate evidence (excluding REJECTED / SUPERSEDED).
    4. Deterministically synthesizes tailored resume and cover-letter drafts.
    """
    posting = session.get(JobPosting, posting_id)
    if posting is None:
        posting = session.scalar(
            select(JobPosting).where(JobPosting.posting_id == posting_id).limit(1)
        )
    if posting is None:
        raise ApplicationPreparationError(f"Job posting '{posting_id}' not found", "POSTING_NOT_FOUND")

    sub = session.get(EmployerSubscription, posting.subscription_id)
    employer_handle = sub.employer_handle if sub else "Employer"

    snapshot = session.scalar(
        select(JobPostingSnapshot)
        .where(JobPostingSnapshot.posting_id == posting.id)
        .order_by(JobPostingSnapshot.captured_at.desc())
        .limit(1)
    )
    if snapshot is None:
        raise ApplicationPreparationError(f"No snapshot found for posting '{posting_id}'", "SNAPSHOT_NOT_FOUND")

    candidate_evidence = load_candidate_evidence(session, fact_ids=fact_ids)

    return build_application_draft(
        job_posting_id=posting.id,
        job_title=snapshot.title,
        employer_handle=employer_handle,
        lists_json=snapshot.lists_json,
        description_plain=snapshot.description_plain,
        workplace_type=snapshot.workplace_type,
        location=snapshot.location,
        candidate_evidence=candidate_evidence,
    )
