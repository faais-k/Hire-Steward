from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import (
    CandidateFact,
    CandidateFactEvidence,
    CandidateProfile,
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

    # When querying broad candidate evidence, also incorporate user-verified items from CandidateProfile
    if fact_ids is None:
        profile = session.scalar(select(CandidateProfile).limit(1))
        if profile is not None:
            existing_skill_names = {
                (str(f.value_json.get("name") or f.value_json.get("text") or f.value_json.get("skill") or "") if isinstance(f.value_json, dict) else str(f.value_json or "")).strip().lower()
                for f in facts if f.fact_type == "SKILL"
            }
            for i, s in enumerate(profile.skills or []):
                s_name = (s.get("name") if isinstance(s, dict) else str(s)).strip()
                if s_name and s_name.lower() not in existing_skill_names:
                    evidence_items.append(
                        CandidateEvidenceItem(
                            fact_id=f"profile_skill_{i}",
                            fact_type="SKILL",
                            value={"name": s_name},
                            verification_state=FactVerificationState.USER_VERIFIED.value,
                            is_active=True,
                            is_conflicted=False,
                            provenance=[],
                        )
                    )

            existing_employers = {
                (f.value_json.get("employer") or f.value_json.get("company") or "").strip().lower()
                for f in facts if f.fact_type == "EMPLOYMENT" and isinstance(f.value_json, dict)
            }
            for i, emp in enumerate(profile.employment or []):
                comp = (emp.get("company") or emp.get("employer") or "").strip()
                if comp and comp.lower() not in existing_employers:
                    emp_val = dict(emp)
                    emp_val.setdefault("employer", comp)
                    emp_val.setdefault("title", emp.get("role") or emp.get("title", ""))
                    evidence_items.append(
                        CandidateEvidenceItem(
                            fact_id=f"profile_emp_{i}",
                            fact_type="EMPLOYMENT",
                            value=emp_val,
                            verification_state=FactVerificationState.USER_VERIFIED.value,
                            is_active=True,
                            is_conflicted=False,
                            provenance=[],
                        )
                    )

            existing_institutions = {
                (f.value_json.get("institution") or "").strip().lower()
                for f in facts if f.fact_type == "EDUCATION" and isinstance(f.value_json, dict)
            }
            for i, edu in enumerate(profile.education or []):
                inst = (edu.get("institution") or "").strip()
                if inst and inst.lower() not in existing_institutions:
                    edu_val = dict(edu)
                    edu_val.setdefault("credential", edu.get("degree") or edu.get("credential", ""))
                    evidence_items.append(
                        CandidateEvidenceItem(
                            fact_id=f"profile_edu_{i}",
                            fact_type="EDUCATION",
                            value=edu_val,
                            verification_state=FactVerificationState.USER_VERIFIED.value,
                            is_active=True,
                            is_conflicted=False,
                            provenance=[],
                        )
                    )

            existing_projects = {
                (f.value_json.get("name") or f.value_json.get("title") or "").strip().lower()
                for f in facts if f.fact_type == "PROJECT" and isinstance(f.value_json, dict)
            }
            for i, proj in enumerate(profile.projects or []):
                p_name = (proj.get("title") or proj.get("name") if isinstance(proj, dict) else str(proj)).strip()
                if p_name and p_name.lower() not in existing_projects:
                    proj_val = dict(proj) if isinstance(proj, dict) else {"name": p_name}
                    proj_val.setdefault("name", p_name)
                    proj_val.setdefault("title", p_name)
                    evidence_items.append(
                        CandidateEvidenceItem(
                            fact_id=f"profile_proj_{i}",
                            fact_type="PROJECT",
                            value=proj_val,
                            verification_state=FactVerificationState.USER_VERIFIED.value,
                            is_active=True,
                            is_conflicted=False,
                            provenance=[],
                        )
                    )

            existing_certs = {
                (f.value_json.get("name") or "").strip().lower()
                for f in facts if f.fact_type == "CERTIFICATION" and isinstance(f.value_json, dict)
            }
            for i, cert in enumerate(profile.certifications or []):
                c_name = (cert.get("name") if isinstance(cert, dict) else str(cert)).strip()
                if c_name and c_name.lower() not in existing_certs:
                    cert_val = dict(cert) if isinstance(cert, dict) else {"name": c_name}
                    cert_val.setdefault("name", c_name)
                    evidence_items.append(
                        CandidateEvidenceItem(
                            fact_id=f"profile_cert_{i}",
                            fact_type="CERTIFICATION",
                            value=cert_val,
                            verification_state=FactVerificationState.USER_VERIFIED.value,
                            is_active=True,
                            is_conflicted=False,
                            provenance=[],
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
