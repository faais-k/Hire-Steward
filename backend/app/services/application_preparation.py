"""Service layer for evidence-grounded application preparation.

Loads job postings, snapshots, and candidate evidence to assemble
deterministic tailored resumes, cover letters, and traceability records.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import (
    CandidateProfile,
    CompensationAssessment,
    CompensationPreference,
    EmployerSubscription,
    JobPosting,
    JobPostingSnapshot,
    TrackedApplication,
)
from backend.app.domain.application_preparation import (
    ApplicationDraft,
    ApplicationPreparationError,
    ApplicationReadinessReport,
    RecruiterMessageDraft,
    assess_application_readiness,
    build_application_draft,
    build_recruiter_message,
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


def prepare_recruiter_message(
    session: Session,
    posting_id: str,
    fact_ids: list[str] | None = None,
    tone: str = "Professional & Direct",
) -> RecruiterMessageDraft:
    """Generate a tailored recruiter outreach note using candidate facts and target job details."""
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

    profile = session.scalar(select(CandidateProfile).limit(1))
    candidate_name = profile.name if profile and profile.name else "Candidate"
    candidate_headline = profile.headline if profile and profile.headline else ""

    candidate_evidence = load_candidate_evidence(session, fact_ids=fact_ids)

    return build_recruiter_message(
        job_posting_id=posting.id,
        job_title=snapshot.title,
        employer_handle=employer_handle,
        candidate_evidence=candidate_evidence,
        candidate_name=candidate_name,
        candidate_headline=candidate_headline,
        tone=tone,
    )


def check_application_readiness(
    session: Session,
    posting_id: str,
) -> ApplicationReadinessReport:
    """Assess readiness of a candidate's application for a specific posting against all safety gates."""
    posting = session.get(JobPosting, posting_id)
    if posting is None:
        posting = session.scalar(
            select(JobPosting).where(JobPosting.posting_id == posting_id).limit(1)
        )
    if posting is None:
        raise ApplicationPreparationError(f"Job posting '{posting_id}' not found", "POSTING_NOT_FOUND")

    profile = session.scalar(select(CandidateProfile).limit(1))
    contact = profile.contact_info if (profile and isinstance(profile.contact_info, dict)) else {}
    has_contact = bool(profile and (profile.name or contact.get("email") or contact.get("phone")))

    # Check for existing application draft / materials
    app = session.scalar(
        select(TrackedApplication)
        .where(TrackedApplication.job_posting_id == posting.id)
        .order_by(TrackedApplication.created_at.desc())
        .limit(1)
    )

    has_resume = False
    has_cover = False
    if app:
        has_resume = bool(app.reviewed_resume_markdown or app.submitted_resume_snapshot)
        has_cover = bool(app.reviewed_cover_letter_markdown or app.submitted_cover_letter_snapshot)

    # If not yet drafted in application table, check if snapshot can build a draft
    if not has_resume:
        try:
            draft = prepare_application_draft(session, posting.id)
            has_resume = bool(draft.resume_markdown)
            has_cover = bool(draft.cover_letter_markdown)
        except Exception:
            has_resume = False

    # Check compensation policy gate
    comp_assessment = session.scalar(
        select(CompensationAssessment)
        .where(
            (CompensationAssessment.job_reference == posting.id)
            | (CompensationAssessment.job_reference == posting.posting_id)
        )
        .order_by(CompensationAssessment.created_at.desc())
        .limit(1)
    )
    meets_floor = True
    if comp_assessment is not None and comp_assessment.outcome == "BLOCKED":
        meets_floor = False

    # Check cooldown
    is_cooldown = False
    if posting.subscription_id:
        existing_sub_app = session.scalar(
            select(TrackedApplication)
            .join(JobPosting, TrackedApplication.job_posting_id == JobPosting.id)
            .where(
                JobPosting.subscription_id == posting.subscription_id,
                TrackedApplication.status.in_(["SUBMITTED", "INTERVIEWING", "ACCEPTED"]),
            )
            .limit(1)
        )
        if existing_sub_app and existing_sub_app.job_posting_id != posting.id:
            is_cooldown = True

    # Check candidate evidence state counts
    evidence = load_candidate_evidence(session)
    unreviewed = sum(1 for e in evidence if e.verification_state == "UNREVIEWED")
    conflicted = sum(1 for e in evidence if e.is_conflicted or e.verification_state == "CONFLICTED")

    return assess_application_readiness(
        job_posting_id=posting.id,
        has_resume=has_resume,
        has_cover_letter=has_cover,
        has_contact_info=has_contact,
        compensation_meets_floor=meets_floor,
        is_cooldown_active=is_cooldown,
        unreviewed_fact_count=unreviewed,
        conflicted_fact_count=conflicted,
    )
