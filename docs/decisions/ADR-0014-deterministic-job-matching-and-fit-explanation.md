# ADR-0014: Deterministic Job Matching and Fit Explanation

- **Status:** Accepted (Milestone 2 Design & Implementation)
- **Date:** 2026-10-29

## Context

Hire-Steward has established:
1. Verified offline job-posting persistence and observation tracking (ADR-0013, Alembic revision `0004_job_discovery_persistence`).
2. Candidate document versions with bounded storage and server-derived byte span provenance (ADR-0011, Alembic revision `0003_candidate_evidence`).
3. Deterministic compensation assessment with an immutable threshold preference and audited settings (ADR-0006 through ADR-0009).

The next product milestone requires evaluating persisted job postings against stored candidate evidence to explain which opportunities are worth pursuing.

Key challenges and design requirements:
1. **Explainability Over Black-Box Scoring:** An opaque similarity percentage (e.g., from an embedding or LLM) cannot explain *why* a candidate is a good or poor fit, nor can it identify specific qualification gaps. Candidates need transparent, auditable explanations grounded in verifiable facts.
2. **Three-State Epistemic Distinction:** Traditional applicant screening systems conflate "no evidence of skill X" with "candidate does not possess skill X". Missing evidence must not automatically disqualify a candidate or be treated as a confirmed deficit. The system must explicitly distinguish:
   - Evidence that a requirement is **MET**.
   - Evidence that a requirement is **CONTRADICTED** (active conflict, incompatible location, or discredited fact).
   - **INSUFFICIENT_EVIDENCE** to determine whether a requirement is met.
3. **No Inferred Truth or Hallucination:** Qualifications must never be invented. Inferred skills or unreviewed claims must not be silently promoted to verified qualifications.
4. **Evidence Grounding & Provenance:** Every conclusion that a requirement is met must link directly to specific `CandidateFact` records and their underlying `CandidateFactEvidence` document byte spans. When provenance is missing or evidence is unreviewed, the system must report uncertainty.
5. **Deterministic, Versioned Scoring:** Match scoring must be repeatable, transparent, and versioned (`v1.0.0-deterministic`), avoiding magic numbers or arbitrary percentages presented as hiring probabilities.
6. **Independence from External Infrastructure:** Matching must execute completely offline against local database models without requiring live job-board access, external LLM APIs, or vector databases.

---

## Decision

We implement a deterministic, evidence-backed matching service structured around three layers:

### 1. Job Requirement Extraction & Normalization
From a `JobPostingSnapshot`:
- Extract **Required Qualifications** and **Preferred Qualifications** from structured `lists_json` (sections such as "Requirements", "Qualifications", "Preferred", "Nice to have") or well-defined plaintext section headers.
- Extract structural constraints: `workplace_type` (remote, onsite, hybrid), `location`, `commitment`, and stated minimum years of experience.
- Deduplicate overlapping or redundant bullet points to prevent artificial skewing of qualification counts.
- If the posting lacks identifiable requirement sections, explicitly mark the job description as `INCOMPLETE`, penalizing confidence rather than guessing.

### 2. Candidate Evidence Evaluation
Candidate evidence is evaluated strictly using active `CandidateFact` records:
- **Active State Filtering:** Superseded (`verification_state = 'SUPERSEDED'`) and rejected (`verification_state = 'REJECTED'`) facts are strictly excluded from positive evidence.
- **Conflict Handling:** Facts with `verification_state = 'CONFLICTED'` are treated as conflicting evidence, preventing clean satisfaction of the requirement and lowering assessment confidence.
- **Provenance Tracing:** For every matching fact, look up `CandidateFactEvidence`. If document byte spans exist, record document version ID, byte range, and evidence hash. If absent, flag `MISSING_PROVENANCE` and record uncertainty.
- **Three-State Qualification Outcome:**
  - `MET`: Supported by active candidate facts (skills, education, employment duration, projects, or certifications).
  - `CONTRADICTED`: Directly contradicted by active candidate evidence (e.g., location mismatch, conflicting education, or verified insufficient tenure).
  - `INSUFFICIENT_EVIDENCE`: No relevant evidence found in the candidate profile. Clearly documented as missing data, not confirmed absence of ability.

### 3. Versioned Scoring & Fit Classification (`v1.0.0-deterministic`)
- **Required Qualification Coverage ($R$):** Ratio of met required qualifications to total required qualifications ($R_{met} / R_{total}$).
- **Preferred Qualification Coverage ($P$):** Ratio of met preferred qualifications to total preferred qualifications ($P_{met} / P_{total}$).
- **Fit Tiering:**
  - `STRONG_MATCH`: All mandatory required qualifications met ($R_{met} == R_{total}$, 100% required coverage), zero contradicted requirements, workplace/location compatible. Missing even one mandatory qualification drops the tier to prevent misleading candidates.
  - `PARTIAL_MATCH`: At least one required qualification met ($0 < R_{met} < R_{total}$) with remaining requirements having `INSUFFICIENT_EVIDENCE`, zero contradicted requirements.
  - `WEAK_MATCH`: Zero required qualifications met ($R_{met} == 0$). Crucially, high preferred coverage ($P$) cannot compensate for missing required qualifications.
  - `BLOCKED_OR_CONTRADICTED`: Any required qualification or hard location constraint is explicitly `CONTRADICTED`.
  - `INSUFFICIENT_DATA`: The job posting lacks requirement sections or candidate evidence is empty.
- **Confidence Rating:**
  - `HIGH`: Clear job requirements, all supporting evidence verified (`DOCUMENT_SUPPORTED` / `USER_VERIFIED`) with document byte spans, zero conflicts.
  - `MEDIUM`: Structured requirements present, but supporting evidence contains `UNREVIEWED` facts or lacks document provenance spans.
  - `LOW`: Incomplete job description, high proportion of `INSUFFICIENT_EVIDENCE`, or presence of `CONFLICTED` facts.
  - `UNKNOWN`: Insufficient data to assess confidence.

---

## Minimal Compatible Database Extension Proposal

To store match assessments persistently in PostgreSQL in a future migration without altering existing schemas:

```sql
CREATE TABLE job_match_assessments (
    id VARCHAR(36) PRIMARY KEY,
    posting_id VARCHAR(36) NOT NULL,
    snapshot_id VARCHAR(36) NOT NULL,
    scoring_version VARCHAR(32) NOT NULL DEFAULT 'v1.0.0-deterministic',
    fit_tier VARCHAR(32) NOT NULL,
    overall_score NUMERIC(5, 4),
    required_coverage NUMERIC(5, 4),
    preferred_coverage NUMERIC(5, 4),
    confidence_level VARCHAR(16) NOT NULL,
    assessment_json JSONB NOT NULL,
    assessed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT fk_match_posting FOREIGN KEY (posting_id)
        REFERENCES job_postings(id) ON DELETE RESTRICT,
    CONSTRAINT fk_match_snapshot FOREIGN KEY (snapshot_id)
        REFERENCES job_posting_snapshots(id) ON DELETE RESTRICT
);
CREATE INDEX ix_job_match_posting_tier ON job_match_assessments(posting_id, fit_tier);
```

For Milestone 2, the matching engine operates directly over the existing ORM entities (`JobPosting`, `JobPostingSnapshot`, `CandidateFact`, `CandidateFactEvidence`, `CompensationPreference`) with typed domain output models.

---

## Consequences

- **Positives:**
  - Full transparency: Every match decision explicitly references candidate facts and document byte spans.
  - Ethical safety: Missing resume evidence is never conflated with candidate incompetence.
  - Deterministic and testable: Zero LLM latency, zero API costs, zero hallucination risk, and 100% reproducible results.
  - Preserves system boundaries: Lever remains `NEEDS_REVIEW` and disabled. Offline operation is strictly maintained.
- **Limitations:**
  - Keyword and rule-based normalization cannot recognize highly novel phrasing or distant synonyms without explicit mapping or ontology expansion.
  - Complex multi-clause requirements (e.g., "5 years Python OR 7 years Java with distributed systems") require structured parsing rules.
