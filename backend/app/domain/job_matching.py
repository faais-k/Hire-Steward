from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import StrEnum
import re
from typing import Any
import unicodedata
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.app.domain.candidate_evidence import FactType, FactVerificationState


class RequirementCategory(StrEnum):
    """Category of job requirement."""

    REQUIRED_QUALIFICATION = "REQUIRED_QUALIFICATION"
    PREFERRED_QUALIFICATION = "PREFERRED_QUALIFICATION"
    EXPERIENCE_REQUIREMENT = "EXPERIENCE_REQUIREMENT"
    WORKPLACE_REQUIREMENT = "WORKPLACE_REQUIREMENT"
    COMPENSATION_REQUIREMENT = "COMPENSATION_REQUIREMENT"


class RequirementMatchStatus(StrEnum):
    """Evaluation status of a specific requirement against candidate evidence.

    Three-state epistemic model:
    - MET: Direct positive evidence exists supporting the qualification.
    - CONTRADICTED: Direct negative or conflicting evidence exists disproving or conflicting.
    - INSUFFICIENT_EVIDENCE: No evidence found. Missing evidence does not mean the candidate lacks the skill.
    """

    MET = "MET"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class FitTier(StrEnum):
    """Categorical fit classification."""

    STRONG_MATCH = "STRONG_MATCH"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    WEAK_MATCH = "WEAK_MATCH"
    BLOCKED_OR_CONTRADICTED = "BLOCKED_OR_CONTRADICTED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


def normalize_fit_tier(tier: str | FitTier) -> FitTier:
    """Normalize a fit tier value, alias, or string into the canonical FitTier enum."""
    if isinstance(tier, FitTier):
        return tier
    raw = str(tier).strip()
    upper = raw.upper()
    if upper in ("BLOCKED", "CONTRADICTED", "BLOCKED_OR_CONTRADICTED"):
        return FitTier.BLOCKED_OR_CONTRADICTED
    if upper in ("INSUFFICIENT", "INSUFFICIENT_DATA", "INCOMPLETE"):
        return FitTier.INSUFFICIENT_DATA
    if upper in ("STRONG", "STRONG_MATCH"):
        return FitTier.STRONG_MATCH
    if upper in ("PARTIAL", "PARTIAL_MATCH", "GOOD", "GOOD_MATCH"):
        return FitTier.PARTIAL_MATCH
    if upper in ("WEAK", "WEAK_MATCH"):
        return FitTier.WEAK_MATCH
    return FitTier(raw)


class ConfidenceLevel(StrEnum):
    """Confidence in the assessment based on data completeness and verification."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


def normalize_confidence_level(level: str | ConfidenceLevel) -> ConfidenceLevel:
    """Normalize a confidence level value or alias into the canonical ConfidenceLevel enum."""
    if isinstance(level, ConfidenceLevel):
        return level
    raw = str(level).strip().upper()
    return ConfidenceLevel(raw)


@dataclass(frozen=True)
class ProvenanceReference:
    """Document byte span provenance backing a candidate fact."""

    provenance_id: str
    document_version_id: str
    byte_start: int
    byte_end: int
    evidence_hash: str
    method: str


@dataclass(frozen=True)
class CandidateEvidenceItem:
    """Normalized representation of a candidate fact for matching."""

    fact_id: str
    fact_type: str
    value: dict[str, Any]
    verification_state: str
    is_active: bool
    is_conflicted: bool
    provenance: list[ProvenanceReference] = field(default_factory=list)

    @property
    def display_label(self) -> str:
        if self.fact_type == FactType.SKILL.value:
            return str(self.value.get("name", "Skill"))
        if self.fact_type == FactType.EDUCATION.value:
            inst = self.value.get("institution", "")
            cred = self.value.get("credential", "")
            field_name = self.value.get("field_of_study", "")
            parts = [p for p in (cred, field_name, inst) if p]
            return " - ".join(parts) if parts else "Education"
        if self.fact_type == FactType.EMPLOYMENT.value:
            employer = self.value.get("employer", "")
            title = self.value.get("title", "")
            return f"{title} at {employer}" if title and employer else "Employment"
        if self.fact_type == FactType.PROJECT.value:
            return str(self.value.get("name", "Project"))
        if self.fact_type == FactType.CERTIFICATION.value:
            name = self.value.get("name", "")
            issuer = self.value.get("issuer", "")
            return f"{name} ({issuer})" if issuer else str(name)
        return f"{self.fact_type}: {self.value}"


@dataclass(frozen=True)
class JobRequirement:
    """A single discrete requirement extracted from a job posting."""

    id: str
    category: RequirementCategory
    text: str
    source_section: str
    normalized_keywords: list[str] = field(default_factory=list)
    min_years_experience: float | None = None
    is_subjective: bool = False


@dataclass(frozen=True)
class RequirementEvaluation:
    """Evaluation of a specific requirement against candidate evidence."""

    requirement: JobRequirement
    status: RequirementMatchStatus
    matched_evidence: list[CandidateEvidenceItem] = field(default_factory=list)
    conflicting_evidence: list[CandidateEvidenceItem] = field(default_factory=list)
    explanation: str = ""
    is_uncertain: bool = False
    provenance_status: str = "VERIFIED_PROVENANCE"  # "VERIFIED_PROVENANCE", "MISSING_PROVENANCE", "NO_EVIDENCE"


class MatchScoreBreakdown(BaseModel):
    """Detailed score breakdown and calculation basis."""

    model_config = ConfigDict(frozen=True)

    required_coverage: float | None = None
    preferred_coverage: float | None = None
    experience_coverage: float | None = None
    workplace_match: bool | None = None
    overall_fit_score: float | None = None
    calculation_basis: str


class JobMatchAssessment(BaseModel):
    """Complete, explainable match assessment between a candidate and a job posting snapshot."""

    model_config = ConfigDict(frozen=True)

    id: str
    job_posting_id: str
    job_snapshot_id: str
    scoring_version: str = "v1.0.0-deterministic"
    fit_tier: FitTier
    overall_score: float | None
    scores: MatchScoreBreakdown
    confidence_level: ConfidenceLevel
    confidence_reasons: list[str]

    required_evaluations: list[dict[str, Any]]
    preferred_evaluations: list[dict[str, Any]]
    structural_evaluations: list[dict[str, Any]]

    qualification_gaps: list[str]
    uncertainties: list[str]
    overall_explanation: str
    heuristic_notice: str = (
        "This assessment is a deterministic evidence-coverage heuristic measuring documented "
        "alignment against stated job requirements. It is not an offer probability or guarantee of employment."
    )
    assessed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- Symbol-Safe Normalization and Boundary Matching ---

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "he", "in", "is", "it", "its", "of", "on", "that", "the",
    "to", "was", "were", "will", "with", "or", "our", "you", "your",
    "we", "they", "this", "must", "have", "ability", "experience",
    "knowledge", "strong", "proficient", "skills", "good", "demonstrated",
    "working", "understanding", "familiarity", "plus", "preferred",
    "candidate", "ideal", "opportunity", "responsible", "join",
}

YEARS_EXP_PATTERN = re.compile(
    r"(?:(?:at\s+least|minimum|min|over)\s+)?(\d+(?:\.\d+)?)\+?\s*(?:-\s*(\d+(?:\.\d+)?)\s*)?(?:years?|yrs?)(?:\s+of)?(?:\s+experience)?",
    re.IGNORECASE,
)

DEGREE_MENTION_PATTERN = re.compile(
    r"\b(?:bachelor'?s?|master'?s?|ph\.?d\.?|doctorate|b\.?s\.?|b\.?a\.?|b\.?tech|b\.?e\.?|m\.?s\.?|m\.?a\.?|m\.?tech|degree|undergraduate|postgraduate)\b",
    re.IGNORECASE,
)

DEGREE_LEVELS = {
    "bachelor": [
        r"\bbachelor'?s?\b", r"\bb\.?s\.?\b", r"\bb\.?a\.?\b",
        r"\bb\.?tech\b", r"\bbtech\b", r"\bb\.?e\.?\b", r"\bundergraduate\b"
    ],
    "master": [
        r"\bmaster'?s?\b", r"\bm\.?s\.?\b", r"\bm\.?a\.?\b",
        r"\bm\.?tech\b", r"\bmtech\b", r"\bpostgraduate\b"
    ],
    "phd": [
        r"\bph\.?d\.?\b", r"\bdoctorate\b"
    ],
}

SUBJECTIVE_REQUIREMENT_PATTERN = re.compile(
    r"\b(?:communication|interpersonal|team\s+player|fast-paced|self-starter|collaborative|passion|enthusiastic|attitude|adaptable|mentoring|problem-solving)\b",
    re.IGNORECASE,
)

# Common general-experience words that denote general tenure rather than specific technical domains
GENERAL_EXPERIENCE_WORDS = {
    "software", "engineering", "development", "developer", "professional",
    "industry", "work", "technical", "coding", "programming", "related",
    "field", "equivalent", "role", "roles", "relevant", "total", "overall",
    "experience", "years", "yrs",
}


CANONICAL_SKILL_SYNONYMS: dict[str, set[str]] = {
    "postgres": {"postgresql", "postgres", "psql"},
    "postgresql": {"postgresql", "postgres", "psql"},
    "aws": {"aws", "amazon web services"},
    "amazon web services": {"aws", "amazon web services"},
    "react": {"react", "reactjs", "react.js"},
    "reactjs": {"react", "reactjs", "react.js"},
    "react.js": {"react", "reactjs", "react.js"},
    "k8s": {"k8s", "kubernetes"},
    "kubernetes": {"k8s", "kubernetes"},
    "golang": {"golang", "go"},
    "go": {"golang", "go"},
    "nodejs": {"nodejs", "node.js", "node"},
    "node.js": {"nodejs", "node.js", "node"},
    "node": {"nodejs", "node.js", "node"},
    "typescript": {"typescript", "ts"},
    "ts": {"typescript", "ts"},
    "javascript": {"javascript", "js"},
    "js": {"javascript", "js"},
    "gcp": {"gcp", "google cloud platform", "google cloud"},
    "google cloud platform": {"gcp", "google cloud platform", "google cloud"},
    "google cloud": {"gcp", "google cloud platform", "google cloud"},
    "azure": {"azure", "microsoft azure"},
    "microsoft azure": {"azure", "microsoft azure"},
}

TECHNICAL_ACTIVITY_WORDS = {
    "tuning", "design", "development", "maintenance", "debugging",
    "testing", "architecture", "management", "optimization", "administration",
    "practices", "internals", "modules", "systems", "solutions",
    "services", "infrastructure", "pipelines", "applications", "implementation",
    "deployment", "monitoring", "troubleshooting", "review", "reviews",
    "query", "data", "database", "backend", "frontend", "fullstack",
    "software", "engineering", "programming", "code", "coding", "memory",
    "concurrency", "performance", "security", "integration", "operations",
    "workflow", "tooling", "scalability", "reliability", "standards",
    "low", "level", "high", "deep", "solid", "broad", "advanced", "basic",
    "hands", "end", "real", "time", "scalable", "distributed", "concurrent",
    "modern", "legacy", "native", "open", "source", "cross", "functional",
}


def _single_symbol_safe_match(term: str, text: str) -> bool:
    cleaned_term = term.strip().lower()
    if not cleaned_term:
        return False
    escaped = re.escape(cleaned_term)
    pattern = rf"(?<![a-zA-Z0-9_+#.]){escaped}(?![a-zA-Z0-9_+#])"
    return bool(re.search(pattern, text, re.IGNORECASE))


def symbol_safe_match(term: str, text: str) -> bool:
    """Matches a term as a distinct whole entity, handling programming symbols (+, #, .).

    Prevents:
    - 'C' matching 'C++' or 'C#'
    - 'Java' matching 'JavaScript'
    - 'Go' matching 'Django'
    - 'R' matching 'React'
    - 'c++' failing to match because of trailing symbols
    """
    if _single_symbol_safe_match(term, text):
        return True

    cleaned_lower = term.strip().lower()
    if cleaned_lower in CANONICAL_SKILL_SYNONYMS:
        for syn in CANONICAL_SKILL_SYNONYMS[cleaned_lower]:
            if _single_symbol_safe_match(syn, text):
                return True
    return False


def is_skill_negated_in_text(skill_name: str, text: str) -> bool:
    """Check if a skill or any of its canonical aliases are mentioned in a negated or prohibitive context."""
    cleaned = skill_name.strip().lower()
    if not cleaned:
        return False
    variants = {cleaned}
    if cleaned in CANONICAL_SKILL_SYNONYMS:
        variants |= CANONICAL_SKILL_SYNONYMS[cleaned]
    for v in variants:
        escaped = re.escape(v)
        pattern = (
            rf"\b(?:no|not|without|never|avoid|do\s+not(?:\s+(?:use|need|want|have))?)\s+"
            rf"[^.;,]*(?<![a-zA-Z0-9_+#.]){escaped}(?![a-zA-Z0-9_+#])"
        )
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def normalize_text_tokens(text: str) -> list[str]:
    """Tokenize and normalize text into clean lower-case alphanumeric tokens."""
    normalized = unicodedata.normalize("NFC", text).lower()
    cleaned = re.sub(r"[^a-z0-9+#.]", " ", normalized)
    tokens = [t.strip(".") for t in cleaned.split() if t.strip(".")]
    return [t for t in tokens if t not in STOPWORDS and len(t) > 1]


def extract_years_experience(text: str) -> float | None:
    """Extract minimum years of experience from requirement text if present."""
    match = YEARS_EXP_PATTERN.search(text)
    if match:
        try:
            return float(match.group(1))
        except (ValueError, IndexError):
            return None
    return None


def calculate_merged_employment_tenure_years(intervals: list[tuple[str | None, str | None]]) -> tuple[float, bool]:
    """Calculate total non-overlapping calendar employment duration in years.

    Merges overlapping or concurrent employment periods so months are not double-counted.
    Returns (total_years, has_uncertain_dates).
    """
    has_uncertain_dates = False
    valid_date_ranges: list[tuple[date, date]] = []

    for s_str, e_str in intervals:
        if not s_str:
            has_uncertain_dates = True
            continue
        try:
            s = date.fromisoformat(s_str)
        except ValueError:
            has_uncertain_dates = True
            continue

        if e_str:
            try:
                e = date.fromisoformat(e_str)
            except ValueError:
                has_uncertain_dates = True
                e = date.today()
        else:
            e = date.today()

        if e < s:
            has_uncertain_dates = True
            continue

        valid_date_ranges.append((s, e))

    if not valid_date_ranges:
        return 0.0, has_uncertain_dates

    # Sort intervals by start date
    valid_date_ranges.sort(key=lambda r: r[0])

    # Merge overlapping or contiguous ranges
    merged: list[tuple[date, date]] = [valid_date_ranges[0]]
    for cur_s, cur_e in valid_date_ranges[1:]:
        prev_s, prev_e = merged[-1]
        if cur_s <= prev_e:
            # Overlapping or contiguous interval
            merged[-1] = (prev_s, max(prev_e, cur_e))
        else:
            merged.append((cur_s, cur_e))

    total_days = sum((e - s).days for s, e in merged)
    return round(total_days / 365.25, 2), has_uncertain_dates


# --- Requirement Extraction ---

REQUIRED_SECTION_TITLES = {
    "requirements", "qualifications", "minimum qualifications",
    "what you need", "what you bring", "must have", "basic qualifications",
    "required skills", "skills & experience", "who you are",
}

PREFERRED_SECTION_TITLES = {
    "preferred qualifications", "preferred", "nice to have", "bonus",
    "desired qualifications", "bonus points", "additional qualifications",
    "good to have", "what's nice to have", "plus",
}


def extract_requirements_from_snapshot(
    lists_json: list[dict[str, Any]] | None,
    description_plain: str | None,
    workplace_type: str | None = None,
    location: str | None = None,
) -> tuple[list[JobRequirement], list[JobRequirement], list[JobRequirement], bool]:
    """Extract required, preferred, and structural requirements from job posting snapshot."""
    required_reqs: list[JobRequirement] = []
    preferred_reqs: list[JobRequirement] = []
    structural_reqs: list[JobRequirement] = []

    seen_texts: set[str] = set()

    # 1. Parse structured lists_json
    if lists_json:
        for section in lists_json:
            raw_title = str(section.get("title", "")).strip().lower()
            items = section.get("items", [])
            if not isinstance(items, list):
                continue

            is_preferred = any(p in raw_title for p in PREFERRED_SECTION_TITLES)
            is_required = any(r in raw_title for r in REQUIRED_SECTION_TITLES)

            category = RequirementCategory.PREFERRED_QUALIFICATION if is_preferred else RequirementCategory.REQUIRED_QUALIFICATION

            # If section is explicitly responsibilities, skip
            if "responsibilit" in raw_title or "what you'll do" in raw_title:
                continue

            if not is_preferred and not is_required:
                category = RequirementCategory.REQUIRED_QUALIFICATION

            for item in items:
                if not isinstance(item, str) or not item.strip():
                    continue
                clean_text = item.strip()
                normalized_key = re.sub(r"\s+", " ", clean_text.lower())
                if normalized_key in seen_texts:
                    continue  # Deduplicate duplicate requirements
                seen_texts.add(normalized_key)

                tokens = normalize_text_tokens(clean_text)
                min_exp = extract_years_experience(clean_text)
                is_subj = bool(SUBJECTIVE_REQUIREMENT_PATTERN.search(clean_text)) and not min_exp and not DEGREE_MENTION_PATTERN.search(clean_text)

                req = JobRequirement(
                    id=f"req_{len(seen_texts)}",
                    category=category,
                    text=clean_text,
                    source_section=section.get("title", "Lists"),
                    normalized_keywords=tokens,
                    min_years_experience=min_exp,
                    is_subjective=is_subj,
                )
                if category == RequirementCategory.PREFERRED_QUALIFICATION:
                    preferred_reqs.append(req)
                else:
                    required_reqs.append(req)

    # 2. If lists_json yielded nothing, parse description_plain headings
    if not required_reqs and not preferred_reqs and description_plain:
        lines = description_plain.splitlines()
        current_category: RequirementCategory | None = None
        current_section = "Description"

        for line in lines:
            trimmed = line.strip()
            if not trimmed:
                continue

            lowered = trimmed.lower()
            if any(p in lowered for p in PREFERRED_SECTION_TITLES) and (len(trimmed) < 60 or trimmed.endswith(":")):
                current_category = RequirementCategory.PREFERRED_QUALIFICATION
                current_section = trimmed.rstrip(":")
                continue
            if any(r in lowered for r in REQUIRED_SECTION_TITLES) and (len(trimmed) < 60 or trimmed.endswith(":")):
                current_category = RequirementCategory.REQUIRED_QUALIFICATION
                current_section = trimmed.rstrip(":")
                continue

            if current_category is not None:
                if trimmed.startswith(("-", "*", "•")) or (len(trimmed) > 10 and not trimmed.endswith(":")):
                    bullet_text = re.sub(r"^[-*•\s]+", "", trimmed).strip()
                    normalized_key = re.sub(r"\s+", " ", bullet_text.lower())
                    if normalized_key in seen_texts:
                        continue
                    seen_texts.add(normalized_key)

                    tokens = normalize_text_tokens(bullet_text)
                    min_exp = extract_years_experience(bullet_text)
                    is_subj = bool(SUBJECTIVE_REQUIREMENT_PATTERN.search(bullet_text)) and not min_exp and not DEGREE_MENTION_PATTERN.search(bullet_text)

                    req = JobRequirement(
                        id=f"req_{len(seen_texts)}",
                        category=current_category,
                        text=bullet_text,
                        source_section=current_section,
                        normalized_keywords=tokens,
                        min_years_experience=min_exp,
                        is_subjective=is_subj,
                    )
                    if current_category == RequirementCategory.PREFERRED_QUALIFICATION:
                        preferred_reqs.append(req)
                    else:
                        required_reqs.append(req)

    # 3. Structural constraints
    if workplace_type:
        structural_reqs.append(
            JobRequirement(
                id="req_workplace_type",
                category=RequirementCategory.WORKPLACE_REQUIREMENT,
                text=f"Workplace arrangement: {workplace_type}",
                source_section="Metadata",
                normalized_keywords=[workplace_type.lower()],
            )
        )
    if location:
        structural_reqs.append(
            JobRequirement(
                id="req_workplace_location",
                category=RequirementCategory.WORKPLACE_REQUIREMENT,
                text=f"Workplace location: {location}",
                source_section="Metadata",
                normalized_keywords=normalize_text_tokens(location),
            )
        )

    is_incomplete = (len(required_reqs) == 0 and len(preferred_reqs) == 0)
    return required_reqs, preferred_reqs, structural_reqs, is_incomplete


# --- Matching Engine ---

def evaluate_requirement(
    req: JobRequirement,
    candidate_evidence: list[CandidateEvidenceItem],
) -> RequirementEvaluation:
    """Evaluate a single requirement against active candidate evidence."""
    # 0. Check for subjective / soft-skill requirement that cannot be evaluated deterministically
    if req.is_subjective:
        return RequirementEvaluation(
            requirement=req,
            status=RequirementMatchStatus.INSUFFICIENT_EVIDENCE,
            matched_evidence=[],
            conflicting_evidence=[],
            explanation=(
                f"Subjective or behavioral requirement ('{req.text}') cannot be verified "
                "deterministically from structured candidate records. Flagged for candidate self-assessment or interview."
            ),
            is_uncertain=True,
            provenance_status="NO_EVIDENCE",
        )

    matched: list[CandidateEvidenceItem] = []
    conflicted: list[CandidateEvidenceItem] = []

    req_lower = req.text.lower()
    req_mentions_degree = bool(DEGREE_MENTION_PATTERN.search(req.text))

    for item in candidate_evidence:
        if not item.is_active:
            continue
        if item.verification_state in (
            FactVerificationState.REJECTED.value,
            FactVerificationState.SUPERSEDED.value,
        ):
            continue

        fact_val = item.value

        # Check for conflicts
        if item.is_conflicted:
            if item.fact_type == FactType.SKILL.value:
                skill_name = str(fact_val.get("name", ""))
                if symbol_safe_match(skill_name, req.text) and not is_skill_negated_in_text(skill_name, req.text):
                    conflicted.append(item)
            continue

        # 1. Skill evaluation using symbol-safe match
        if item.fact_type == FactType.SKILL.value:
            skill_name = str(fact_val.get("name", "")).strip()
            if symbol_safe_match(skill_name, req.text):
                if not is_skill_negated_in_text(skill_name, req.text):
                    matched.append(item)

        # 2. Education evaluation (Only evaluate if requirement explicitly pertains to degrees/education)
        elif item.fact_type == FactType.EDUCATION.value and req_mentions_degree:
            cred = str(fact_val.get("credential", "")).lower()
            field_name = str(fact_val.get("field_of_study", "")).lower()

            degree_matched = False
            for degree_level, regex_variants in DEGREE_LEVELS.items():
                req_has_level = any(re.search(pat, req_lower) for pat in regex_variants)
                cred_has_level = any(re.search(pat, cred) for pat in regex_variants)
                if req_has_level and cred_has_level:
                    degree_matched = True
                    break

            if degree_matched:
                matched.append(item)

        # 3. Employment / Title evaluation
        elif item.fact_type == FactType.EMPLOYMENT.value and req.min_years_experience is None:
            title = str(fact_val.get("title", "")).strip()
            if title and symbol_safe_match(title, req.text):
                matched.append(item)

        # 4. Certification evaluation
        elif item.fact_type == FactType.CERTIFICATION.value:
            cert_name = str(fact_val.get("name", "")).strip()
            issuer = str(fact_val.get("issuer", "")).strip()
            if cert_name and symbol_safe_match(cert_name, req.text):
                matched.append(item)
            elif issuer and symbol_safe_match(issuer, req.text):
                matched.append(item)

        # 5. Project evaluation
        elif item.fact_type == FactType.PROJECT.value:
            proj_name = str(fact_val.get("name", "")).strip()
            if proj_name and symbol_safe_match(proj_name, req.text):
                matched.append(item)

    # Check for conflicted evidence
    if conflicted:
        explanation = (
            f"Requirement '{req.text}' is disputed: candidate fact "
            f"'{conflicted[0].display_label}' has CONFLICTED verification state."
        )
        return RequirementEvaluation(
            requirement=req,
            status=RequirementMatchStatus.CONTRADICTED,
            matched_evidence=[],
            conflicting_evidence=conflicted,
            explanation=explanation,
            is_uncertain=True,
            provenance_status="CONFLICTED_EVIDENCE",
        )

    # Check for years of experience requirement
    if req.min_years_experience is not None:
        # Calculate non-overlapping employment intervals
        employment_intervals = [
            (
                item.value.get("start_date") if isinstance(item.value.get("start_date"), str) else None,
                item.value.get("end_date") if isinstance(item.value.get("end_date"), str) else None,
            )
            for item in candidate_evidence
            if item.is_active and item.fact_type == FactType.EMPLOYMENT.value and not item.is_conflicted
        ]
        total_exp_years, has_uncertain_dates = calculate_merged_employment_tenure_years(employment_intervals)
        matched_emp = [item for item in candidate_evidence if item.fact_type == FactType.EMPLOYMENT.value and item.is_active]

        # Check if requirement ALSO demands specific domain/technologies beyond general software engineering
        cleaned_req_text = re.sub(YEARS_EXP_PATTERN, "", req.text).strip()
        cleaned_tokens = [t for t in normalize_text_tokens(cleaned_req_text) if t not in STOPWORDS]
        specific_domain_tokens = [t for t in cleaned_tokens if t not in GENERAL_EXPERIENCE_WORDS]
        is_general_experience = len(specific_domain_tokens) == 0

        if is_general_experience:
            # Pure tenure requirement
            if not matched_emp:
                return RequirementEvaluation(
                    requirement=req,
                    status=RequirementMatchStatus.INSUFFICIENT_EVIDENCE,
                    explanation="No candidate employment records found to assess years of experience.",
                    is_uncertain=True,
                    provenance_status="NO_EVIDENCE",
                )
            if total_exp_years >= req.min_years_experience:
                uncertain_note = " (Note: some employment dates are incomplete/uncertain)" if has_uncertain_dates else ""
                return RequirementEvaluation(
                    requirement=req,
                    status=RequirementMatchStatus.MET,
                    matched_evidence=matched_emp,
                    explanation=(
                        f"Candidate has {total_exp_years:.1f} years verified non-overlapping employment experience, "
                        f"satisfying requirement for {req.min_years_experience:.1f}+ years.{uncertain_note}"
                    ),
                    is_uncertain=has_uncertain_dates or any(item.verification_state == FactVerificationState.UNREVIEWED.value for item in matched_emp),
                    provenance_status="VERIFIED_PROVENANCE" if any(item.provenance for item in matched_emp) else "MISSING_PROVENANCE",
                )
            else:
                return RequirementEvaluation(
                    requirement=req,
                    status=RequirementMatchStatus.CONTRADICTED,
                    conflicting_evidence=matched_emp,
                    explanation=(
                        f"Candidate records show {total_exp_years:.1f} years non-overlapping experience, "
                        f"which does not satisfy the required {req.min_years_experience:.1f}+ years."
                    ),
                    is_uncertain=has_uncertain_dates,
                    provenance_status="VERIFIED_PROVENANCE" if any(item.provenance for item in matched_emp) else "MISSING_PROVENANCE",
                )
        else:
            # Combined tenure AND specific skill/domain requirement (e.g. "5+ years of C++ experience")
            # Both conditions must be satisfied!
            if not matched:
                return RequirementEvaluation(
                    requirement=req,
                    status=RequirementMatchStatus.INSUFFICIENT_EVIDENCE,
                    matched_evidence=[],
                    explanation=(
                        f"Candidate lacks evidence for required skill/domain in '{req.text}'. "
                        f"(Tenure record: {total_exp_years:.1f} years recorded, but required skill has no matching evidence)."
                    ),
                    is_uncertain=True,
                    provenance_status="NO_EVIDENCE",
                )
            elif not matched_emp:
                return RequirementEvaluation(
                    requirement=req,
                    status=RequirementMatchStatus.INSUFFICIENT_EVIDENCE,
                    matched_evidence=matched,
                    explanation=(
                        f"Candidate matches required domain ({', '.join(item.display_label for item in matched)}), "
                        f"but profile lacks employment records to verify {req.min_years_experience:.1f}+ years tenure."
                    ),
                    is_uncertain=True,
                    provenance_status="NO_EVIDENCE",
                )
            elif total_exp_years < req.min_years_experience:
                return RequirementEvaluation(
                    requirement=req,
                    status=RequirementMatchStatus.CONTRADICTED,
                    conflicting_evidence=matched_emp,
                    matched_evidence=matched,
                    explanation=(
                        f"Candidate has evidence for required skill, but total non-overlapping experience "
                        f"({total_exp_years:.1f} years) falls short of the required {req.min_years_experience:.1f}+ years."
                    ),
                    is_uncertain=has_uncertain_dates,
                    provenance_status="VERIFIED_PROVENANCE",
                )
            else:
                all_evidence = matched + matched_emp
                return RequirementEvaluation(
                    requirement=req,
                    status=RequirementMatchStatus.MET,
                    matched_evidence=all_evidence,
                    explanation=(
                        f"Met: candidate satisfies both tenure requirement ({total_exp_years:.1f} years >= {req.min_years_experience:.1f}+ years) "
                        f"and required domain evidence ({', '.join(item.display_label for item in matched)})."
                    ),
                    is_uncertain=has_uncertain_dates or any(item.verification_state == FactVerificationState.UNREVIEWED.value for item in all_evidence),
                    provenance_status="VERIFIED_PROVENANCE" if any(item.provenance for item in all_evidence) else "MISSING_PROVENANCE",
                )

    # Workplace / Location requirement evaluation
    if req.category == RequirementCategory.WORKPLACE_REQUIREMENT:
        workplace_facts = [
            item for item in candidate_evidence
            if item.is_active and (
                "remote" in str(item.value).lower()
                or "onsite" in str(item.value).lower()
                or "hybrid" in str(item.value).lower()
                or "location" in str(item.value).lower()
            )
        ]
        if workplace_facts:
            is_compat = True
            for wf in workplace_facts:
                wf_str = str(wf.value).lower()
                if "remote only" in wf_str and "onsite" in req_lower:
                    is_compat = False
                    conflicted.append(wf)
            if not is_compat:
                return RequirementEvaluation(
                    requirement=req,
                    status=RequirementMatchStatus.CONTRADICTED,
                    conflicting_evidence=conflicted,
                    explanation=f"Workplace requirement '{req.text}' conflicts with candidate constraint: {conflicted[0].display_label}.",
                    is_uncertain=False,
                    provenance_status="VERIFIED_PROVENANCE",
                )
            else:
                return RequirementEvaluation(
                    requirement=req,
                    status=RequirementMatchStatus.MET,
                    matched_evidence=workplace_facts,
                    explanation=f"Workplace requirement '{req.text}' is compatible with candidate profile.",
                    is_uncertain=False,
                    provenance_status="VERIFIED_PROVENANCE",
                )
        else:
            if "remote" in req_lower:
                return RequirementEvaluation(
                    requirement=req,
                    status=RequirementMatchStatus.MET,
                    explanation="Remote role is inherently accessible; no location conflict detected.",
                    is_uncertain=False,
                    provenance_status="VERIFIED_PROVENANCE",
                )
            return RequirementEvaluation(
                requirement=req,
                status=RequirementMatchStatus.INSUFFICIENT_EVIDENCE,
                explanation="No candidate workplace or relocation preference recorded. Missing preference does not imply incompatibility.",
                is_uncertain=True,
                provenance_status="NO_EVIDENCE",
            )

    # Check for compound conjunctive ("AND") requirement with multiple skills
    # e.g. "Experience with Python and Kubernetes"
    if " and " in req_lower or " as well as " in req_lower:
        # Check if the requirement mentions alternatives ("OR")
        if not re.search(r"\b(?:or|either)\b", req_lower):
            # Pure conjunctive requirement: verify whether candidate matched multiple distinct skills
            parts = [p.strip() for p in re.split(r"\s+(?:and|as well as)\s+", req.text, flags=re.IGNORECASE) if p.strip()]
            if len(parts) >= 2:
                substantive_parts: list[tuple[str, list[str]]] = []
                unmatched_parts: list[str] = []
                for p in parts:
                    sub_tokens = [t for t in normalize_text_tokens(p) if t not in STOPWORDS]
                    is_tech_conjunct = any(tok not in TECHNICAL_ACTIVITY_WORDS for tok in sub_tokens)
                    if sub_tokens and is_tech_conjunct:
                        substantive_parts.append((p, sub_tokens))
                        part_matched = any(
                            symbol_safe_match(item.display_label, p)
                            or any(symbol_safe_match(tok, item.display_label) for tok in sub_tokens)
                            or any(symbol_safe_match(str(v), p) for v in item.value.values() if isinstance(v, str))
                            for item in matched
                        )
                        if not part_matched:
                            unmatched_parts.append(p)

                if matched and len(substantive_parts) >= 2 and unmatched_parts:
                    # Candidate matched at least one part, but one or more conjuncts lack evidence
                    unmatched_desc = "', '".join(unmatched_parts)
                    matched_labels = ", ".join(item.display_label for item in matched)
                    return RequirementEvaluation(
                        requirement=req,
                        status=RequirementMatchStatus.INSUFFICIENT_EVIDENCE,
                        matched_evidence=matched,
                        explanation=(
                            f"Partially evidenced: candidate has evidence for '{matched_labels}', "
                            f"but compound conjunctive requirement also demands unverified qualifications ('{unmatched_desc}')."
                        ),
                        is_uncertain=True,
                        provenance_status="MISSING_PROVENANCE" if any(not item.provenance for item in matched) else "VERIFIED_PROVENANCE",
                    )

    # General skill / credential outcome
    if matched:
        has_provenance = any(item.provenance for item in matched)
        unreviewed_items = [item for item in matched if item.verification_state == FactVerificationState.UNREVIEWED.value]
        is_unreviewed = bool(unreviewed_items)
        prov_status = "VERIFIED_PROVENANCE" if has_provenance else "MISSING_PROVENANCE"

        fact_names = ", ".join(f"'{item.display_label}' ({item.verification_state})" for item in matched)
        unreviewed_prefix = "[UNREVIEWED CLAIM] " if is_unreviewed else ""
        missing_prov_note = " [UNGROUNDED: lacks document byte span provenance]" if not has_provenance else ""
        explanation = f"{unreviewed_prefix}Met by candidate evidence: {fact_names}.{missing_prov_note}"

        return RequirementEvaluation(
            requirement=req,
            status=RequirementMatchStatus.MET,
            matched_evidence=matched,
            explanation=explanation,
            is_uncertain=(is_unreviewed or not has_provenance),
            provenance_status=prov_status,
        )

    # No evidence found either way -> INSUFFICIENT_EVIDENCE
    return RequirementEvaluation(
        requirement=req,
        status=RequirementMatchStatus.INSUFFICIENT_EVIDENCE,
        matched_evidence=[],
        explanation=(
            f"No candidate evidence found regarding '{req.text}'. "
            f"Missing evidence does not mean the candidate lacks this qualification."
        ),
        is_uncertain=True,
        provenance_status="NO_EVIDENCE",
    )


def assess_job_match(
    posting_id: str,
    snapshot_id: str,
    lists_json: list[dict[str, Any]] | None,
    description_plain: str | None,
    workplace_type: str | None,
    location: str | None,
    candidate_evidence: list[CandidateEvidenceItem],
) -> JobMatchAssessment:
    """Perform deterministic, explainable match evaluation between a job snapshot and candidate evidence."""
    required_reqs, preferred_reqs, structural_reqs, is_incomplete = extract_requirements_from_snapshot(
        lists_json=lists_json,
        description_plain=description_plain,
        workplace_type=workplace_type,
        location=location,
    )

    required_evals = [evaluate_requirement(req, candidate_evidence) for req in required_reqs]
    preferred_evals = [evaluate_requirement(req, candidate_evidence) for req in preferred_reqs]
    structural_evals = [evaluate_requirement(req, candidate_evidence) for req in structural_reqs]

    # Calculate coverage scores
    r_total = len(required_evals)
    r_met = sum(1 for e in required_evals if e.status == RequirementMatchStatus.MET)
    r_contradicted = sum(1 for e in required_evals if e.status == RequirementMatchStatus.CONTRADICTED)

    p_total = len(preferred_evals)
    p_met = sum(1 for e in preferred_evals if e.status == RequirementMatchStatus.MET)
    p_contradicted = sum(1 for e in preferred_evals if e.status == RequirementMatchStatus.CONTRADICTED)

    s_contradicted = sum(1 for e in structural_evals if e.status == RequirementMatchStatus.CONTRADICTED)

    req_coverage = round(r_met / r_total, 4) if r_total > 0 else None
    pref_coverage = round(p_met / p_total, 4) if p_total > 0 else None

    # Structural match: 1.0 if explicitly confirmed, 0.0 if contradicted, None if unspecified
    if s_contradicted > 0:
        workplace_ok: bool | None = False
    elif structural_evals:
        # Check if confirmed met
        has_met_structural = any(e.status == RequirementMatchStatus.MET for e in structural_evals)
        workplace_ok = True if has_met_structural else None
    else:
        workplace_ok = None

    # Calculate overall composite fit score
    # Formula: 70% required coverage + 20% preferred coverage + 10% workplace compatibility
    calc_parts: list[str] = []
    composite_score: float | None = None

    if not candidate_evidence:
        calc_parts.append("Candidate evidence profile is empty; insufficient data to calculate match score.")
        composite_score = None
    elif r_total > 0:
        base_req = (r_met / r_total) * 0.70
        calc_parts.append(f"Required qualifications coverage: {r_met}/{r_total} ({r_met/r_total:.1%}) * 70%")

        base_pref = (p_met / p_total) * 0.20 if p_total > 0 else 0.20
        pref_desc = f"{p_met}/{p_total} ({p_met/p_total:.1%})" if p_total > 0 else "None specified (full weight)"
        calc_parts.append(f"Preferred qualifications coverage: {pref_desc} * 20%")

        # Unknown workplace arrangements are NOT awarded full 10%
        if workplace_ok is True:
            base_work = 0.10
            work_desc = "Compatible (100% * 10%)"
        elif workplace_ok is False:
            base_work = 0.0
            work_desc = "Contradicted (0% * 10%)"
        else:
            base_work = 0.0
            work_desc = "Unspecified / Unknown (0% * 10%)"
        calc_parts.append(f"Workplace compatibility: {work_desc}")

        composite_score = round(base_req + base_pref + base_work, 4)
    else:
        calc_parts.append("No structured required qualifications extracted from job posting.")
        composite_score = None

    calculation_basis = "; ".join(calc_parts)

    # Classify Fit Tier
    qualification_gaps: list[str] = []
    uncertainties: list[str] = []
    confidence_reasons: list[str] = []

    # Identify gaps and uncertainties
    for e in required_evals:
        if e.status == RequirementMatchStatus.INSUFFICIENT_EVIDENCE:
            qualification_gaps.append(f"Required: '{e.requirement.text}' (No candidate evidence found)")
        elif e.status == RequirementMatchStatus.CONTRADICTED:
            qualification_gaps.append(f"Contradicted: '{e.requirement.text}' ({e.explanation})")

        if e.is_uncertain:
            uncertainties.append(f"Requirement '{e.requirement.text}': {e.explanation}")

    for e in preferred_evals:
        if e.status == RequirementMatchStatus.INSUFFICIENT_EVIDENCE:
            qualification_gaps.append(f"Preferred: '{e.requirement.text}' (No candidate evidence found)")
        elif e.status == RequirementMatchStatus.CONTRADICTED:
            qualification_gaps.append(f"Preferred contradicted: '{e.requirement.text}' ({e.explanation})")

    # Fit Tier Assignment
    # Strict rule: STRONG_MATCH requires that 100% of required qualifications have evidence (r_met == r_total).
    # Missing even one required qualification precludes STRONG_MATCH to prevent misleading users!
    if r_contradicted > 0 or s_contradicted > 0 or p_contradicted > 0:
        fit_tier = FitTier.BLOCKED_OR_CONTRADICTED
    elif is_incomplete or (r_total == 0 and p_total == 0) or not candidate_evidence:
        fit_tier = FitTier.INSUFFICIENT_DATA
    elif r_total > 0 and r_met == 0:
        fit_tier = FitTier.WEAK_MATCH
    elif r_total > 0 and r_met == r_total and (workplace_ok is not False):
        fit_tier = FitTier.STRONG_MATCH
    elif r_total > 0 and r_met > 0:
        fit_tier = FitTier.PARTIAL_MATCH
    else:
        fit_tier = FitTier.WEAK_MATCH

    # Confidence Evaluation
    if is_incomplete:
        confidence_level = ConfidenceLevel.LOW
        confidence_reasons.append("Job description lacks structured requirement sections or lists.")
    elif not candidate_evidence:
        confidence_level = ConfidenceLevel.LOW
        confidence_reasons.append("Candidate evidence profile is empty.")
    elif r_contradicted > 0 or s_contradicted > 0:
        confidence_level = ConfidenceLevel.HIGH
        confidence_reasons.append("Direct contradictory evidence reliably identifies mismatch.")
    else:
        matched_items = [item for e in (required_evals + preferred_evals) for item in e.matched_evidence]
        missing_prov = sum(1 for item in matched_items if not item.provenance)
        unreviewed = sum(1 for item in matched_items if item.verification_state == FactVerificationState.UNREVIEWED.value)

        # Count subjective requirements
        subj_count = sum(1 for e in (required_evals + preferred_evals) if e.requirement.is_subjective)
        if subj_count > 0:
            confidence_reasons.append(f"{subj_count} requirement(s) are subjective and cannot be evaluated deterministically.")

        # Count requirements with partial conjunct evidence
        partial_conjunct_count = sum(
            1 for e in (required_evals + preferred_evals)
            if e.matched_evidence and e.status == RequirementMatchStatus.INSUFFICIENT_EVIDENCE
        )
        if partial_conjunct_count > 0:
            confidence_reasons.append(f"{partial_conjunct_count} requirement(s) are partially evidenced with unresolved conjuncts.")

        if unreviewed > 0 or missing_prov > 0 or subj_count > 0 or partial_conjunct_count > 0:
            confidence_level = ConfidenceLevel.MEDIUM
            if unreviewed > 0:
                confidence_reasons.append(f"{unreviewed} supporting candidate facts have UNREVIEWED status.")
            if missing_prov > 0:
                confidence_reasons.append(f"{missing_prov} supporting facts lack document byte span provenance.")
        else:
            confidence_level = ConfidenceLevel.HIGH
            confidence_reasons.append("All matched qualifications are backed by document-supported or user-verified facts with provenance.")

    if not confidence_reasons:
        confidence_reasons.append("Evaluation completed based on available structured evidence.")

    # Build human-readable overall explanation
    explanation_lines: list[str] = [
        f"Fit Tier: {fit_tier.value} (Confidence: {confidence_level.value}).",
    ]
    if r_total > 0:
        explanation_lines.append(f"Required qualifications evidence: {r_met} of {r_total} met ({r_met/r_total:.0%}).")
    if p_total > 0:
        explanation_lines.append(f"Preferred qualifications evidence: {p_met} of {p_total} met ({p_met/p_total:.0%}).")

    if fit_tier == FitTier.BLOCKED_OR_CONTRADICTED:
        explanation_lines.append("Assessment BLOCKED due to direct contradictions or incompatible constraints.")
    elif fit_tier == FitTier.STRONG_MATCH:
        explanation_lines.append("Candidate possesses documented evidence satisfying all evaluated mandatory requirements.")
    elif fit_tier == FitTier.PARTIAL_MATCH:
        explanation_lines.append(
            f"Candidate evidence satisfies {r_met} of {r_total} required qualifications, "
            f"with {r_total - r_met} requirement(s) lacking evidence. Not a full match."
        )
    elif fit_tier == FitTier.WEAK_MATCH:
        if p_met > 0 and r_met == 0:
            explanation_lines.append(
                "Candidate matches preferred qualifications but lacks evidence for mandatory required qualifications. "
                "Preferred skills cannot substitute for mandatory requirements."
            )
        else:
            explanation_lines.append("Candidate evidence covers none of the mandatory required qualifications.")
    elif fit_tier == FitTier.INSUFFICIENT_DATA:
        explanation_lines.append("Job description lacks identifiable requirements or candidate profile lacks evidence.")

    overall_explanation = " ".join(explanation_lines)

    def serialize_eval(ev: RequirementEvaluation) -> dict[str, Any]:
        return {
            "requirement_id": ev.requirement.id,
            "category": ev.requirement.category.value,
            "text": ev.requirement.text,
            "source_section": ev.requirement.source_section,
            "status": ev.status.value,
            "explanation": ev.explanation,
            "is_uncertain": ev.is_uncertain,
            "provenance_status": ev.provenance_status,
            "matched_facts": [
                {
                    "fact_id": item.fact_id,
                    "fact_type": item.fact_type,
                    "label": item.display_label,
                    "verification_state": item.verification_state,
                    "provenance_count": len(item.provenance),
                }
                for item in ev.matched_evidence
            ],
            "conflicting_facts": [
                {
                    "fact_id": item.fact_id,
                    "fact_type": item.fact_type,
                    "label": item.display_label,
                    "verification_state": item.verification_state,
                }
                for item in ev.conflicting_evidence
            ],
        }

    return JobMatchAssessment(
        id=str(uuid4()),
        job_posting_id=posting_id,
        job_snapshot_id=snapshot_id,
        scoring_version="v1.0.0-deterministic",
        fit_tier=fit_tier,
        overall_score=composite_score,
        scores=MatchScoreBreakdown(
            required_coverage=req_coverage,
            preferred_coverage=pref_coverage,
            experience_coverage=None,
            workplace_match=workplace_ok,
            overall_fit_score=composite_score,
            calculation_basis=calculation_basis,
        ),
        confidence_level=confidence_level,
        confidence_reasons=confidence_reasons,
        required_evaluations=[serialize_eval(e) for e in required_evals],
        preferred_evaluations=[serialize_eval(e) for e in preferred_evals],
        structural_evaluations=[serialize_eval(e) for e in structural_evals],
        qualification_gaps=qualification_gaps,
        uncertainties=uncertainties,
        overall_explanation=overall_explanation,
    )
