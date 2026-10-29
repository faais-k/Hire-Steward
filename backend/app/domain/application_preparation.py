"""Evidence-grounded application preparation domain engine.

Produces truthful, tailored resume and cover-letter drafts deterministically
from persisted job requirements and candidate evidence facts.

Critical Invariants:
1. Never invent skills, employers, titles, dates, metrics, or education.
2. Every substantive claim traces to an active CandidateFact.
3. REJECTED and SUPERSEDED facts are never used.
4. CONFLICTED facts are treated as unresolved and excluded from positive claims.
5. UNREVIEWED facts are explicitly flagged with verification warnings.
6. Missing evidence is never described as proof that the candidate lacks a skill.
7. Empty candidate evidence produces an honest insufficient-evidence state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.app.domain.candidate_evidence import FactType, FactVerificationState
from backend.app.domain.job_matching import (
    CandidateEvidenceItem,
    JobRequirement,
    RequirementCategory,
    RequirementEvaluation,
    RequirementMatchStatus,
    evaluate_requirement,
    extract_requirements_from_snapshot,
)


class ApplicationPreparationError(Exception):
    """Domain error during application draft generation."""

    def __init__(self, message: str, code: str) -> None:
        self.message = message
        self.code = code
        super().__init__(message)


class TailoredClaim(BaseModel):
    """A single factual candidate claim embedded in a tailored draft."""

    model_config = ConfigDict(frozen=True)

    claim_id: str
    fact_id: str
    fact_type: str
    statement: str
    verification_state: str
    is_unreviewed: bool
    provenance_count: int
    target_requirement_id: str | None = None
    relevance_reason: str = ""


class AddressedRequirement(BaseModel):
    """Job requirement addressed by one or more candidate evidence claims."""

    model_config = ConfigDict(frozen=True)

    requirement_id: str
    requirement_text: str
    category: str
    supporting_claims: list[TailoredClaim]
    status: str
    explanation: str


class EvidenceGap(BaseModel):
    """Job requirement lacking supporting candidate evidence."""

    model_config = ConfigDict(frozen=True)

    requirement_id: str
    requirement_text: str
    category: str
    gap_explanation: str


class ApplicationDraft(BaseModel):
    """Complete tailored application draft package."""

    model_config = ConfigDict(frozen=True)

    id: str
    job_posting_id: str
    job_title: str
    employer_handle: str
    candidate_evidence_count: int
    has_sufficient_evidence: bool

    # Tailored materials
    resume_markdown: str
    cover_letter_markdown: str

    # Evidence traceability & audit
    addressed_requirements: list[AddressedRequirement]
    evidence_gaps: list[EvidenceGap]
    unreviewed_claims: list[TailoredClaim]
    conflicted_claims: list[TailoredClaim]

    draft_explanation: str
    heuristic_notice: str
    generated_at: str


def filter_usable_evidence(
    evidence_items: list[CandidateEvidenceItem],
) -> tuple[list[CandidateEvidenceItem], list[CandidateEvidenceItem], list[CandidateEvidenceItem]]:
    """Partition candidate evidence into usable facts, unreviewed facts, and conflicted facts.

    Excludes REJECTED and SUPERSEDED facts entirely.
    """
    usable: list[CandidateEvidenceItem] = []
    unreviewed: list[CandidateEvidenceItem] = []
    conflicted: list[CandidateEvidenceItem] = []

    for item in evidence_items:
        if not item.is_active:
            continue
        v_state = item.verification_state
        if v_state in {FactVerificationState.REJECTED.value, FactVerificationState.SUPERSEDED.value}:
            continue
        if item.is_conflicted or v_state == FactVerificationState.CONFLICTED.value:
            conflicted.append(item)
            continue
        if v_state == FactVerificationState.UNREVIEWED.value:
            unreviewed.append(item)
            usable.append(item)
        else:
            usable.append(item)

    return usable, unreviewed, conflicted


def generate_tailored_resume(
    job_title: str,
    employer_handle: str,
    usable_evidence: list[CandidateEvidenceItem],
    matched_evaluations: list[RequirementEvaluation],
) -> tuple[str, list[TailoredClaim]]:
    """Build a tailored resume markdown strictly from usable candidate evidence.

    Prioritizes skills and experiences directly matching the target job.
    """
    lines: list[str] = []
    claims: list[TailoredClaim] = []

    # 1. Header
    lines.append(f"# Candidate Application Profile")
    lines.append(f"**Target Role:** {job_title} at {employer_handle}")
    lines.append(f"*Tailored from verified candidate evidence records*\n")

    # Group evidence by type
    skills = [e for e in usable_evidence if e.fact_type == FactType.SKILL.value]
    employment = [e for e in usable_evidence if e.fact_type == FactType.EMPLOYMENT.value]
    education = [e for e in usable_evidence if e.fact_type == FactType.EDUCATION.value]
    projects = [e for e in usable_evidence if e.fact_type == FactType.PROJECT.value]
    certs = [e for e in usable_evidence if e.fact_type == FactType.CERTIFICATION.value]

    # Identify skills directly matching job requirements
    matched_fact_ids = set()
    for ev in matched_evaluations:
        for m in ev.matched_evidence:
            matched_fact_ids.add(m.fact_id)

    matched_skills = [s for s in skills if s.fact_id in matched_fact_ids]
    other_skills = [s for s in skills if s.fact_id not in matched_fact_ids]

    # 2. Summary
    lines.append("## Professional Summary")
    if employment:
        primary_emp = employment[0]
        curr_title = primary_emp.value.get("title")
        curr_emp = primary_emp.value.get("employer")
        if curr_title and curr_emp:
            summary_intro = f"Professional with documented experience as {curr_title} at {curr_emp}"
        elif curr_title:
            summary_intro = f"Professional with documented experience as {curr_title}"
        elif curr_emp:
            summary_intro = f"Professional with documented experience at {curr_emp}"
        else:
            summary_intro = "Professional with documented employment history"
    elif skills:
        summary_intro = "Candidate with documented technical skills"
    else:
        summary_intro = "Candidate profile with no verified employment or skill records"

    if matched_skills:
        skill_names = [str(s.value.get("name", "")) for s in matched_skills[:4]]
        summary_intro += f", bringing documented capability in {', '.join(skill_names)}."
    else:
        summary_intro += "."

    lines.append(summary_intro)
    lines.append("")

    # 3. Core Competencies & Technical Skills
    lines.append("## Technical Skills & Competencies")
    if matched_skills:
        lines.append("### Relevant Qualifications (Target Alignment)")
        for s in matched_skills:
            name = str(s.value.get("name", "Skill"))
            years = s.value.get("years_experience")
            years_str = f" ({years} yrs)" if years else ""
            status_tag = f"[{s.verification_state}]"
            prov_str = f" ({len(s.provenance)} span{'s' if len(s.provenance) != 1 else ''})" if s.provenance else ""
            lines.append(f"- **{name}**{years_str} {status_tag}{prov_str}")
            claims.append(
                TailoredClaim(
                    claim_id=f"claim_{uuid4().hex[:8]}",
                    fact_id=s.fact_id,
                    fact_type=s.fact_type,
                    statement=f"Skill: {name}{years_str}",
                    verification_state=s.verification_state,
                    is_unreviewed=(s.verification_state == FactVerificationState.UNREVIEWED.value),
                    provenance_count=len(s.provenance),
                    relevance_reason="Directly matches stated job qualification",
                )
            )

    if other_skills:
        lines.append("### Additional Technical Skills")
        other_names = []
        for s in other_skills:
            name = str(s.value.get("name", "Skill"))
            other_names.append(name)
            claims.append(
                TailoredClaim(
                    claim_id=f"claim_{uuid4().hex[:8]}",
                    fact_id=s.fact_id,
                    fact_type=s.fact_type,
                    statement=f"Skill: {name}",
                    verification_state=s.verification_state,
                    is_unreviewed=(s.verification_state == FactVerificationState.UNREVIEWED.value),
                    provenance_count=len(s.provenance),
                    relevance_reason="Documented candidate capability",
                )
            )
        lines.append(", ".join(other_names))
    lines.append("")

    # 4. Employment Experience
    if employment:
        lines.append("## Employment Experience")
        for emp in employment:
            val = emp.value
            title = val.get("title", "Position")
            employer = val.get("employer", "Company")
            start = val.get("start_date", "")
            end = val.get("end_date") or "Present"
            loc = val.get("location", "")
            loc_str = f" | {loc}" if loc else ""
            date_str = f"*{start} – {end}*" if start else ""

            lines.append(f"### {title} — {employer}")
            if date_str or loc_str:
                lines.append(f"{date_str}{loc_str}")

            desc = val.get("description")
            if desc:
                lines.append(f"{desc}")

            emp_skills = val.get("skills")
            if emp_skills and isinstance(emp_skills, list):
                lines.append(f"**Technologies & Tools:** {', '.join(str(x) for x in emp_skills)}")

            lines.append("")
            claims.append(
                TailoredClaim(
                    claim_id=f"claim_{uuid4().hex[:8]}",
                    fact_id=emp.fact_id,
                    fact_type=emp.fact_type,
                    statement=f"Employment: {title} at {employer} ({start} - {end})",
                    verification_state=emp.verification_state,
                    is_unreviewed=(emp.verification_state == FactVerificationState.UNREVIEWED.value),
                    provenance_count=len(emp.provenance),
                    relevance_reason="Documented candidate employment history",
                )
            )

    # 5. Technical Projects
    if projects:
        lines.append("## Projects & Technical Initiatives")
        for proj in projects:
            val = proj.value
            p_name = val.get("name", "Project")
            p_desc = val.get("description", "")
            techs = val.get("technologies")

            lines.append(f"### {p_name}")
            if p_desc:
                lines.append(f"{p_desc}")
            if techs and isinstance(techs, list):
                lines.append(f"**Technologies:** {', '.join(str(t) for t in techs)}")
            lines.append("")

            claims.append(
                TailoredClaim(
                    claim_id=f"claim_{uuid4().hex[:8]}",
                    fact_id=proj.fact_id,
                    fact_type=proj.fact_type,
                    statement=f"Project: {p_name}",
                    verification_state=proj.verification_state,
                    is_unreviewed=(proj.verification_state == FactVerificationState.UNREVIEWED.value),
                    provenance_count=len(proj.provenance),
                    relevance_reason="Documented technical project evidence",
                )
            )

    # 6. Education & Certifications
    if education or certs:
        lines.append("## Education & Credentials")
        for edu in education:
            val = edu.value
            cred = val.get("credential", "Degree")
            field_name = val.get("field_of_study", "")
            inst = val.get("institution", "Institution")
            grad = val.get("graduation_year", "")
            grad_str = f" ({grad})" if grad else ""
            field_str = f" in {field_name}" if field_name else ""
            lines.append(f"- **{cred}{field_str}** — {inst}{grad_str}")

            claims.append(
                TailoredClaim(
                    claim_id=f"claim_{uuid4().hex[:8]}",
                    fact_id=edu.fact_id,
                    fact_type=edu.fact_type,
                    statement=f"Education: {cred}{field_str} at {inst}",
                    verification_state=edu.verification_state,
                    is_unreviewed=(edu.verification_state == FactVerificationState.UNREVIEWED.value),
                    provenance_count=len(edu.provenance),
                    relevance_reason="Documented academic credential",
                )
            )

        for cert in certs:
            val = cert.value
            c_name = val.get("name", "Certification")
            issuer = val.get("issuer", "")
            iss_str = f" (Issued by {issuer})" if issuer else ""
            lines.append(f"- **{c_name}**{iss_str}")
            claims.append(
                TailoredClaim(
                    claim_id=f"claim_{uuid4().hex[:8]}",
                    fact_id=cert.fact_id,
                    fact_type=cert.fact_type,
                    statement=f"Certification: {c_name}{iss_str}",
                    verification_state=cert.verification_state,
                    is_unreviewed=(cert.verification_state == FactVerificationState.UNREVIEWED.value),
                    provenance_count=len(cert.provenance),
                    relevance_reason="Documented certification",
                )
            )
        lines.append("")

    return "\n".join(lines).strip(), claims


def generate_tailored_cover_letter(
    job_title: str,
    employer_handle: str,
    usable_evidence: list[CandidateEvidenceItem],
    matched_evaluations: list[RequirementEvaluation],
    gaps: list[JobRequirement],
) -> str:
    """Build a truthful, job-specific cover-letter draft grounded in candidate evidence."""
    lines: list[str] = []

    lines.append(f"Dear Hiring Team at {employer_handle},\n")

    # Group evidence
    skills = [e for e in usable_evidence if e.fact_type == FactType.SKILL.value]
    employment = [e for e in usable_evidence if e.fact_type == FactType.EMPLOYMENT.value]
    projects = [e for e in usable_evidence if e.fact_type == FactType.PROJECT.value]

    # Collect matched skills
    matched_skill_names: list[str] = []
    for ev in matched_evaluations:
        for m in ev.matched_evidence:
            if m.fact_type == FactType.SKILL.value:
                s_name = str(m.value.get("name", "")).strip()
                if s_name and s_name not in matched_skill_names:
                    matched_skill_names.append(s_name)

    # Paragraph 1: Purpose & Background
    if employment:
        recent_emp = employment[0]
        recent_title = recent_emp.value.get("title")
        recent_co = recent_emp.value.get("employer")
        if recent_title and recent_co:
            bg_phrase = f"In my career as a {recent_title} at {recent_co}, I have acquired practical experience in this field."
        elif recent_title:
            bg_phrase = f"In my career as a {recent_title}, I have acquired practical experience in this field."
        elif recent_co:
            bg_phrase = f"In my employment at {recent_co}, I have acquired practical experience in this field."
        else:
            bg_phrase = "My background includes practical experience documented in my candidate record."
        lines.append(
            f"I am writing to express my interest in the {job_title} role at {employer_handle}. "
            f"{bg_phrase} "
            f"I welcome the opportunity to bring my documented, evidence-backed capabilities to your team.\n"
        )
    elif matched_skill_names:
        lines.append(
            f"I am writing to express my interest in the {job_title} position at {employer_handle}. "
            f"With verified capability in {', '.join(matched_skill_names[:3])}, my background directly aligns with "
            f"the technical requirements documented for this vacancy.\n"
        )
    else:
        lines.append(
            f"I am writing to submit my application for the {job_title} position with {employer_handle}. "
            f"I have reviewed the role requirements and welcome the opportunity to discuss how my background aligns with your team's needs.\n"
        )

    # Paragraph 2: Core Qualification Alignment
    if matched_evaluations:
        req_highlights: list[str] = []
        for ev in matched_evaluations[:3]:
            req_text = ev.requirement.text
            ev_skills = [str(m.value.get("name", "")) for m in ev.matched_evidence if m.fact_type == FactType.SKILL.value]
            if ev_skills:
                req_highlights.append(f"addressing '{req_text}' through hands-on work with {', '.join(ev_skills)}")
            else:
                req_highlights.append(f"meeting '{req_text}'")

        alignment_text = (
            f"Your team seeks expertise in key technical areas where I have demonstrable experience. Specifically, "
            f"my background includes {'; '.join(req_highlights)}. "
        )
        if projects:
            p = projects[0]
            p_name = p.value.get("name")
            p_techs = p.value.get("technologies")
            if p_name and p_techs:
                alignment_text += f"Furthermore, in the {p_name} project, I utilized {', '.join(str(t) for t in p_techs[:3])}."
        lines.append(f"{alignment_text}\n")

    # Paragraph 3: Honest addressing of requirements & gaps
    if gaps:
        gap_texts = [f"'{g.text}'" for g in gaps[:2]]
        lines.append(
            f"Regarding the stated requirements for {', '.join(gap_texts)}, my candidate evidence record does not currently contain documentation for these specific qualifications. "
            f"I would welcome the opportunity to discuss how my documented background relates to these requirements.\n"
        )

    # Paragraph 4: Closing
    lines.append(
        f"Thank you for your consideration. I look forward to the opportunity to discuss how my documented background "
        f"will contribute to {employer_handle}.\n"
    )
    lines.append("Sincerely,")
    lines.append("Candidate")

    return "\n".join(lines).strip()


def build_application_draft(
    job_posting_id: str,
    job_title: str,
    employer_handle: str,
    lists_json: list[dict[str, Any]] | None,
    description_plain: str | None,
    workplace_type: str | None,
    location: str | None,
    candidate_evidence: list[CandidateEvidenceItem],
) -> ApplicationDraft:
    """Deterministically assemble an application draft tailored to a specific job."""
    # 1. Extract requirements
    req_reqs, pref_reqs, struct_reqs, _ = extract_requirements_from_snapshot(
        lists_json=lists_json,
        description_plain=description_plain,
        workplace_type=workplace_type,
        location=location,
    )
    all_reqs = req_reqs + pref_reqs + struct_reqs

    # 2. Partition candidate evidence
    usable_evidence, unreviewed_evidence, conflicted_evidence = filter_usable_evidence(candidate_evidence)

    # 3. Handle empty candidate evidence profile
    if not usable_evidence and not conflicted_evidence:
        gaps = [
            EvidenceGap(
                requirement_id=r.id,
                requirement_text=r.text,
                category=r.category.value,
                gap_explanation="No recorded evidence in candidate profile for this qualification.",
            )
            for r in all_reqs
        ]
        return ApplicationDraft(
            id=str(uuid4()),
            job_posting_id=job_posting_id,
            job_title=job_title,
            employer_handle=employer_handle,
            candidate_evidence_count=0,
            has_sufficient_evidence=False,
            resume_markdown="",
            cover_letter_markdown="",
            addressed_requirements=[],
            evidence_gaps=gaps,
            unreviewed_claims=[],
            conflicted_claims=[],
            draft_explanation=(
                "Cannot generate truthful application materials: Candidate evidence profile is empty. "
                "Upload candidate documents or add verified profile facts before preparing an application."
            ),
            heuristic_notice=(
                "Truthful Application Invariant: Hire-Steward refuses to fabricate credentials. "
                "Every application draft must be grounded in verified candidate evidence."
            ),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    # 4. Evaluate each requirement against usable evidence
    matched_evaluations: list[RequirementEvaluation] = []
    evidence_gaps: list[EvidenceGap] = []
    addressed_requirements: list[AddressedRequirement] = []

    for req in all_reqs:
        ev = evaluate_requirement(req, usable_evidence)
        if ev.status == RequirementMatchStatus.MET:
            matched_evaluations.append(ev)
            claims_for_req: list[TailoredClaim] = []
            for item in ev.matched_evidence:
                is_unrev = (item.verification_state == FactVerificationState.UNREVIEWED.value)
                label = item.display_label
                claims_for_req.append(
                    TailoredClaim(
                        claim_id=f"claim_{uuid4().hex[:8]}",
                        fact_id=item.fact_id,
                        fact_type=item.fact_type,
                        statement=label,
                        verification_state=item.verification_state,
                        is_unreviewed=is_unrev,
                        provenance_count=len(item.provenance),
                        target_requirement_id=req.id,
                        relevance_reason=f"Supports qualification '{req.text}'",
                    )
                )
            addressed_requirements.append(
                AddressedRequirement(
                    requirement_id=req.id,
                    requirement_text=req.text,
                    category=req.category.value,
                    supporting_claims=claims_for_req,
                    status="MET",
                    explanation=ev.explanation,
                )
            )
        else:
            evidence_gaps.append(
                EvidenceGap(
                    requirement_id=req.id,
                    requirement_text=req.text,
                    category=req.category.value,
                    gap_explanation=ev.explanation or "No direct candidate evidence recorded for this qualification.",
                )
            )

    # 5. Generate tailored resume & cover letter
    gap_requirements = [req for req in all_reqs if any(g.requirement_id == req.id for g in evidence_gaps)]

    resume_md, resume_claims = generate_tailored_resume(
        job_title=job_title,
        employer_handle=employer_handle,
        usable_evidence=usable_evidence,
        matched_evaluations=matched_evaluations,
    )

    cover_letter_md = generate_tailored_cover_letter(
        job_title=job_title,
        employer_handle=employer_handle,
        usable_evidence=usable_evidence,
        matched_evaluations=matched_evaluations,
        gaps=gap_requirements,
    )

    # 6. Collect unreviewed claims and conflicted claims
    unreviewed_claims = [c for c in resume_claims if c.is_unreviewed]

    conflicted_claims = [
        TailoredClaim(
            claim_id=f"conflicted_{uuid4().hex[:8]}",
            fact_id=c.fact_id,
            fact_type=c.fact_type,
            statement=c.display_label,
            verification_state=c.verification_state,
            is_unreviewed=False,
            provenance_count=len(c.provenance),
            relevance_reason="Excluded from draft because fact is in CONFLICTED state",
        )
        for c in conflicted_evidence
    ]

    # 7. Draft explanation
    explanation_parts = [
        f"Tailored draft assembled from {len(usable_evidence)} active candidate fact(s).",
        f"Addressed {len(addressed_requirements)} of {len(all_reqs)} job requirement(s) with direct candidate evidence.",
    ]
    if evidence_gaps:
        explanation_parts.append(f"Identified {len(evidence_gaps)} qualification gap(s) lacking documented evidence.")
    if unreviewed_claims:
        explanation_parts.append(f"Notice: {len(unreviewed_claims)} claim(s) rely on unreviewed evidence requiring user confirmation.")
    if conflicted_claims:
        explanation_parts.append(f"Excluded {len(conflicted_claims)} conflicted fact(s) to avoid unverified assertions.")

    return ApplicationDraft(
        id=str(uuid4()),
        job_posting_id=job_posting_id,
        job_title=job_title,
        employer_handle=employer_handle,
        candidate_evidence_count=len(candidate_evidence),
        has_sufficient_evidence=True,
        resume_markdown=resume_md,
        cover_letter_markdown=cover_letter_md,
        addressed_requirements=addressed_requirements,
        evidence_gaps=evidence_gaps,
        unreviewed_claims=unreviewed_claims,
        conflicted_claims=conflicted_claims,
        draft_explanation=" ".join(explanation_parts),
        heuristic_notice=(
            "Evidence Grounding Invariant: This application material is generated deterministically from candidate "
            "records. Substantive claims are traceable to source evidence. Unreviewed statements must be confirmed prior to submission."
        ),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
