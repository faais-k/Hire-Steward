"""Domain models, validation, and completeness scoring for Candidate Profile (Stage 2)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ContactInfo:
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    languages: list[str] = field(default_factory=list)


@dataclass
class EducationEntry:
    institution: str
    degree: str
    field_of_study: str = ""
    start_date: str = ""
    end_date: str = ""
    gpa: str = ""
    highlights: list[str] = field(default_factory=list)


@dataclass
class EmploymentEntry:
    company: str
    role: str
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    is_current: bool = False
    description: str = ""
    skills_used: list[str] = field(default_factory=list)


@dataclass
class ProjectEntry:
    title: str
    role: str = ""
    description: str = ""
    url: str = ""
    skills_used: list[str] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)


@dataclass
class SkillEntry:
    name: str
    category: str = "General"  # e.g. "Programming Languages", "Frameworks", "Cloud"
    proficiency_level: str = "Intermediate"  # "Beginner", "Intermediate", "Advanced", "Expert"
    years_experience: float = 0.0


@dataclass
class CertificationEntry:
    name: str
    issuer: str
    issue_date: str = ""
    expiration_date: str = ""
    credential_id: str = ""
    credential_url: str = ""


@dataclass
class CompletenessReport:
    score: float  # 0.0 to 1.0
    percentage: int  # 0 to 100
    missing_elements: list[str]
    strengths: list[str]


def calculate_profile_completeness(profile_dict: dict[str, Any]) -> CompletenessReport:
    """Calculate deterministic completeness score (0.0 to 1.0) and missing requirements."""
    score = 0.0
    missing: list[str] = []
    strengths: list[str] = []

    # 1. Full name (10%)
    name = (profile_dict.get("name") or profile_dict.get("full_name") or "").strip()
    if name:
        score += 0.10
        strengths.append("Full name provided")
    else:
        missing.append("Candidate full name is missing")

    # 2. Contact info (20%)
    contact = profile_dict.get("contact_info") or {}
    email = (contact.get("email") or profile_dict.get("contact_email") or profile_dict.get("email") or "").strip()
    phone = (contact.get("phone") or profile_dict.get("phone") or "").strip()
    location = (contact.get("location") or profile_dict.get("location") or "").strip()
    if email and (phone or location):
        score += 0.20
        strengths.append("Verified contact information present")
    elif email:
        score += 0.10
        missing.append("Add phone number or location to complete contact info")
    else:
        missing.append("Contact email is missing")

    # 3. Headline & Summary (10%)
    headline = (profile_dict.get("headline") or "").strip()
    summary = (profile_dict.get("summary") or "").strip()
    if headline and summary:
        score += 0.10
        strengths.append("Professional headline and summary present")
    elif headline or summary:
        score += 0.05
        missing.append("Add both a headline and summary")
    else:
        missing.append("Professional summary and headline are missing")

    # 4. Employment Experience (25%)
    employment = profile_dict.get("employment") or profile_dict.get("experiences") or []
    valid_jobs = [
        j for j in employment
        if isinstance(j, dict) and (j.get("company") and j.get("role"))
    ]
    if len(valid_jobs) >= 2:
        score += 0.25
        strengths.append(f"{len(valid_jobs)} work experiences recorded")
    elif len(valid_jobs) == 1:
        score += 0.18
        strengths.append("1 work experience recorded")
    else:
        missing.append("At least one employment history entry required")

    # 5. Education (15%)
    education = profile_dict.get("education") or profile_dict.get("educations") or []
    valid_edu = [
        e for e in education
        if isinstance(e, dict) and (e.get("institution") and e.get("degree"))
    ]
    if valid_edu:
        score += 0.15
        strengths.append("Educational background provided")
    else:
        missing.append("At least one education entry required")

    # 6. Skills (20%)
    skills = profile_dict.get("skills") or []
    valid_skills = [
        s for s in skills
        if (isinstance(s, str) and s.strip()) or (isinstance(s, dict) and (s.get("name") or "").strip())
    ]
    if len(valid_skills) >= 5:
        score += 0.20
        strengths.append(f"{len(valid_skills)} skills listed")
    elif len(valid_skills) >= 2:
        score += 0.12
        missing.append("Add at least 5 key skills for best match accuracy")
    else:
        missing.append("Add key technical/professional skills (at least 3)")

    # Additional profile enhancements (strengths)
    projects = profile_dict.get("projects") or []
    if projects:
        strengths.append(f"{len(projects)} project(s) recorded")
    certs = profile_dict.get("certifications") or []
    if certs:
        strengths.append(f"{len(certs)} certification(s) listed")
    langs = contact.get("languages") or profile_dict.get("languages") or []
    if langs:
        strengths.append(f"{len(langs)} language(s) recorded")

    normalized_score = round(min(score, 1.0), 2)
    percentage = int(normalized_score * 100)

    return CompletenessReport(
        score=normalized_score,
        percentage=percentage,
        missing_elements=missing,
        strengths=strengths,
    )
