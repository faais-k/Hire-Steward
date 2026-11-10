"""Service layer for Candidate Profile persistence and completeness management (Stage 2)."""

from __future__ import annotations

from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import CandidateProfile
from backend.app.domain.candidate_profile import CompletenessReport, calculate_profile_completeness


def get_or_create_profile(session: Session, profile_id: str = "default") -> CandidateProfile:
    """Retrieve candidate profile or create initialized singleton profile."""
    profile = session.scalar(select(CandidateProfile).where(CandidateProfile.id == profile_id))
    if profile is None:
        profile = CandidateProfile(
            id=profile_id,
            name="",
            headline="",
            summary="",
            contact_info={},
            education=[],
            employment=[],
            projects=[],
            skills=[],
            certifications=[],
            completeness_score=0.0,
        )
        session.add(profile)
        session.flush()
    return profile


def update_profile(
    session: Session, profile_data: dict[str, Any], profile_id: str = "default"
) -> CandidateProfile:
    """Update profile fields, recalculating completeness score deterministically."""
    profile = get_or_create_profile(session, profile_id)

    # Allowed updatable fields
    fields = [
        "name",
        "headline",
        "summary",
        "contact_info",
        "education",
        "employment",
        "projects",
        "skills",
        "certifications",
    ]
    for f in fields:
        if f in profile_data:
            setattr(profile, f, profile_data[f])

    # Re-evaluate completeness score
    report = calculate_profile_completeness({
        "name": profile.name,
        "headline": profile.headline,
        "summary": profile.summary,
        "contact_info": profile.contact_info,
        "education": profile.education,
        "employment": profile.employment,
        "projects": profile.projects,
        "skills": profile.skills,
        "certifications": profile.certifications,
    })
    profile.completeness_score = report.score

    session.flush()
    return profile


def get_profile_report(session: Session, profile_id: str = "default") -> CompletenessReport:
    """Generate detailed completeness report with strengths and recommendations."""
    profile = get_or_create_profile(session, profile_id)
    return calculate_profile_completeness({
        "name": profile.name,
        "headline": profile.headline,
        "summary": profile.summary,
        "contact_info": profile.contact_info,
        "education": profile.education,
        "employment": profile.employment,
        "projects": profile.projects,
        "skills": profile.skills,
        "certifications": profile.certifications,
    })
