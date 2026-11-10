"""Blinded Evaluation Serializer for Task 8.2 Checkpoint A.

Enforces:
1. Strict field allowlist serialization preventing leakage of internal scores,
   ground-truth labels, target tiers, or curator adjudications.
2. Complete exclusion of raw contact details (email, phone) from model-facing payloads.
3. Deterministic canonical sorting for requirements, skills, and certifications.
4. RFC 8785 canonical JSON formatting (UTF-8, sorted keys, no extraneous whitespace).
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.app.evaluation.pii_mapper import (
    PIICoordinateMapper,
    SectionMaskingRegistry,
)

PROHIBITED_LEAKAGE_KEYS: frozenset[str] = frozenset(
    {
        "human_suitability",
        "human_suitability_label",
        "target_system_tier",
        "target_submission_eligible",
        "adjudication_notes",
        "owner_adjudication_notes",
        "expected_fit_tier",
        "expected_required_met",
        "match_score",
        "fit_score",
        "evaluator_role",
        "internal_scoring_leak",
        "formatting_cluster_id",
        "source_platform",
        "employer_id",
        "candidate_profile_id",
        "contact_info",
    }
)


class BlindedRequirements(BaseModel):
    """Explicitly allowed job requirement fields."""

    model_config = ConfigDict(extra="ignore")

    mandatory_constraints: list[str] = Field(default_factory=list)
    core_competencies: list[str] = Field(default_factory=list)
    preferred_qualifications: list[str] = Field(default_factory=list)
    experience_years_requested: float | int | None = None


class BlindedCompensation(BaseModel):
    """Explicitly allowed compensation fields."""

    model_config = ConfigDict(extra="ignore")

    currency: str | None = None
    amount_min: float | None = None
    amount_max: float | None = None
    period: str | None = None
    compensation_structure: str | None = None
    guaranteed_base: float | None = None
    is_disclosed: bool = False
    is_explicitly_unpaid: bool = False


class BlindedJobPosting(BaseModel):
    """Explicitly allowed job posting fields."""

    model_config = ConfigDict(extra="ignore")

    title: str
    workplace_type: str | None = None
    location: str | None = None
    description_plain: str = ""
    requirements: BlindedRequirements = Field(default_factory=BlindedRequirements)
    compensation: BlindedCompensation | None = None


class BlindedEducation(BaseModel):
    """Explicitly allowed education declaration fields."""

    model_config = ConfigDict(extra="ignore")

    declaration_state: str
    status_stated: str | None = None
    degree_level: str | None = None
    field_of_study: str | None = None


class BlindedExperienceItem(BaseModel):
    """Explicitly allowed candidate work experience fields."""

    model_config = ConfigDict(extra="ignore")

    title: str
    employer: str
    years: float | None = None
    description: str | None = None


class BlindedFact(BaseModel):
    """Explicitly allowed candidate verified evidence fact fields."""

    model_config = ConfigDict(extra="ignore")

    fact_type: str
    statement: str
    skills: list[str] = Field(default_factory=list)
    years_of_experience: float | None = None


class BlindedCandidateProfile(BaseModel):
    """Explicitly allowed candidate profile fields (strictly excluding contact info)."""

    model_config = ConfigDict(extra="ignore")

    name: str
    education_status: BlindedEducation
    experience: list[BlindedExperienceItem] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    evidence_facts: list[BlindedFact] = Field(default_factory=list)


class BlindedCasePayload(BaseModel):
    """Blinded model-facing evaluation case payload."""

    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    case_id: str
    job_posting: BlindedJobPosting
    candidate_profile: BlindedCandidateProfile
    masking_result: Any = Field(default=None, exclude=True)


class BlindedEvaluationSerializer:
    """Serializes raw evaluation cases into blinded, deterministic payloads with PII pseudonymization."""

    def __init__(self, pii_mapper: PIICoordinateMapper | None = None) -> None:
        self.pii_mapper = pii_mapper or PIICoordinateMapper()

    def serialize(self, raw_case: dict[str, Any]) -> BlindedCasePayload:
        """Parse raw case dictionary through strict allowlist Pydantic models with PII pseudonymization."""
        case_id = str(raw_case.get("case_id", ""))
        jp_raw = raw_case.get("job_posting") or {}
        cp_raw = raw_case.get("candidate_profile") or {}

        candidate_raw_name = str(cp_raw.get("name") or "").strip()
        registry = SectionMaskingRegistry()

        # 1. Parse and sort requirements
        reqs_raw = jp_raw.get("requirements") or {}
        mandatory = sorted(str(x) for x in (reqs_raw.get("mandatory_constraints") or []))
        competencies = sorted(str(x) for x in (reqs_raw.get("core_competencies") or []))
        preferred = sorted(str(x) for x in (reqs_raw.get("preferred_qualifications") or []))
        reqs = BlindedRequirements(
            mandatory_constraints=mandatory,
            core_competencies=competencies,
            preferred_qualifications=preferred,
            experience_years_requested=reqs_raw.get("experience_years_requested"),
        )

        # Register requirements sections
        comp_text = "\n".join(competencies)
        registry.register_section(
            "job_posting.requirements.core_competencies",
            self.pii_mapper.mask_text(comp_text, candidate_name=candidate_raw_name),
            ["core_competencies"],
        )
        mand_text = "\n".join(mandatory)
        registry.register_section(
            "job_posting.requirements.mandatory_constraints",
            self.pii_mapper.mask_text(mand_text, candidate_name=candidate_raw_name),
            ["mandatory_constraints"],
        )
        pref_text = "\n".join(preferred)
        registry.register_section(
            "job_posting.requirements.preferred_qualifications",
            self.pii_mapper.mask_text(pref_text, candidate_name=candidate_raw_name),
            ["preferred_qualifications"],
        )
        all_reqs_text = "\n".join(competencies + mandatory + preferred)
        registry.register_section(
            "job_posting.requirements",
            self.pii_mapper.mask_text(all_reqs_text, candidate_name=candidate_raw_name),
            ["requirements", "job_requirements"],
        )

        # 2. Parse compensation
        comp_raw = jp_raw.get("compensation")
        comp = BlindedCompensation.model_validate(comp_raw) if comp_raw else None

        # 3. Construct blinded job posting with sanitized text
        desc_plain = str(jp_raw.get("description_plain") or "")
        desc_mask_res = (
            self.pii_mapper.mask_text(desc_plain, candidate_name=candidate_raw_name)
            if desc_plain
            else self.pii_mapper.mask_text("")
        )
        desc_plain_masked = desc_mask_res.sanitized_text if desc_plain else ""
        registry.register_section(
            "job_posting.description_plain",
            desc_mask_res,
            ["job_description", "description_plain"],
        )

        job_posting = BlindedJobPosting(
            title=str(jp_raw.get("title") or ""),
            workplace_type=jp_raw.get("workplace_type"),
            location=jp_raw.get("location"),
            description_plain=desc_plain_masked,
            requirements=reqs,
            compensation=comp,
        )

        # 4. Parse education status
        edu_raw = cp_raw.get("education_status") or {}
        edu = BlindedEducation(
            declaration_state=str(edu_raw.get("declaration_state", "DECLARED_NONE")),
            status_stated=edu_raw.get("status_stated"),
            degree_level=edu_raw.get("degree_level"),
            field_of_study=edu_raw.get("field_of_study"),
        )

        # 5. Parse experience list with narrative text sanitized
        exp_list: list[BlindedExperienceItem] = []
        raw_exp_descriptions: list[str] = []
        for i, exp in enumerate(cp_raw.get("experience") or []):
            if isinstance(exp, dict):
                raw_exp_desc = str(exp.get("description") or "")
                raw_exp_descriptions.append(raw_exp_desc)
                exp_item_res = (
                    self.pii_mapper.mask_text(raw_exp_desc, candidate_name=candidate_raw_name)
                    if raw_exp_desc
                    else self.pii_mapper.mask_text("")
                )
                registry.register_section(
                    f"candidate_profile.experience[{i}].description",
                    exp_item_res,
                    [f"experience[{i}].description", f"experience[{i}]"],
                )
                exp_list.append(
                    BlindedExperienceItem(
                        title=str(exp.get("title") or ""),
                        employer=str(exp.get("employer") or ""),
                        years=exp.get("years"),
                        description=exp_item_res.sanitized_text if raw_exp_desc else None,
                    )
                )
        all_exp_text = "\n".join(raw_exp_descriptions)
        registry.register_section(
            "candidate_profile.experience",
            self.pii_mapper.mask_text(all_exp_text, candidate_name=candidate_raw_name),
            ["experience", "candidate_experience"],
        )

        # 6. Parse and sort skills, certifications
        skills = sorted(str(s) for s in (cp_raw.get("skills") or []))
        certifications = sorted(str(c) for c in (cp_raw.get("certifications") or []))

        # 7. Parse evidence facts with narrative statement sanitized
        facts_list: list[BlindedFact] = []
        raw_fact_statements: list[str] = []
        for j, f in enumerate(cp_raw.get("evidence_facts") or []):
            if isinstance(f, dict):
                raw_stmt = str(f.get("statement") or "")
                raw_fact_statements.append(raw_stmt)
                fact_item_res = (
                    self.pii_mapper.mask_text(raw_stmt, candidate_name=candidate_raw_name)
                    if raw_stmt
                    else self.pii_mapper.mask_text("")
                )
                registry.register_section(
                    f"candidate_profile.evidence_facts[{j}].statement",
                    fact_item_res,
                    [f"evidence_facts[{j}].statement", f"evidence_facts[{j}]"],
                )
                facts_list.append(
                    BlindedFact(
                        fact_type=str(f.get("fact_type") or ""),
                        statement=fact_item_res.sanitized_text if raw_stmt else "",
                        skills=sorted(str(s) for s in (f.get("skills") or [])),
                        years_of_experience=f.get("years_of_experience"),
                    )
                )
        all_facts_text = "\n".join(raw_fact_statements)
        registry.register_section(
            "candidate_profile.evidence_facts",
            self.pii_mapper.mask_text(all_facts_text, candidate_name=candidate_raw_name),
            ["evidence_facts", "candidate_evidence"],
        )

        # 8. Construct blinded candidate profile with pseudonymized name
        candidate_profile = BlindedCandidateProfile(
            name="[CANDIDATE_NAME]" if candidate_raw_name else "",
            education_status=edu,
            experience=exp_list,
            skills=skills,
            certifications=certifications,
            evidence_facts=facts_list,
        )

        return BlindedCasePayload(
            case_id=case_id,
            job_posting=job_posting,
            candidate_profile=candidate_profile,
            masking_result=registry,
        )

    def to_canonical_json(self, raw_case: dict[str, Any]) -> str:
        """Produce RFC 8785 canonical JSON string for the blinded payload."""
        payload = self.serialize(raw_case)
        return json.dumps(
            payload.model_dump(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
