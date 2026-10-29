# ADR-0015: Evidence-Grounded Application Preparation

- **Status:** Accepted (Milestone 4 Design & Implementation)
- **Date:** 2026-10-29

## Context

Hire-Steward has established:
1. Verified offline job-posting persistence and observation tracking (ADR-0013, Alembic revision `0004_job_discovery_persistence`).
2. Candidate document versions with bounded storage and server-derived byte span provenance (ADR-0011, Alembic revision `0003_candidate_evidence`).
3. Deterministic explainable job matching and fit scoring (ADR-0014, `v1.0.0-deterministic`).
4. Local review workbench for inspecting opportunities and evidence coverage (Milestone 3 / 3.1).

The next objective is helping candidates prepare tailored application materials (tailored resume and cover letter drafts) for a target vacancy based strictly on actual candidate evidence and job requirements.

Key challenges and design requirements:
1. **Zero Hallucination Invariant:** Traditional AI resume builders hallucinate credentials, exaggerate metrics, fabricate employment dates, or invent skills to appease ATS screeners. Hire-Steward must refuse to invent facts. Every substantive claim must trace to a verified `CandidateFact`.
2. **Exclusion of Discredited or Conflicted Data:** `REJECTED` and `SUPERSEDED` candidate facts must never appear in application drafts. `CONFLICTED` facts must be excluded from positive claims and treated as unresolved.
3. **Transparent Review Notice for Unreviewed Claims:** If a candidate fact has `UNREVIEWED` verification status, it may be used conditionally but must be explicitly flagged with a verification notice so the candidate reviews it before submission.
4. **Honest Epistemic Gap Handling:** Missing candidate evidence must be described honestly as "no recorded evidence in candidate profile", never as proof that the candidate lacks the skill. If the candidate profile has no usable evidence, the system must return `has_sufficient_evidence = False` and refuse to fabricate draft materials.
5. **Clear Separation of Concerns and Persistence Strategy:** Server-side draft generation is 100% deterministic and reproducible from existing persisted job snapshots and candidate facts. For candidate drafting, editing, and preview retention across reloads, browser `localStorage` provides persistent client-side state while keeping database schema migrations clean until Milestone 5 (formal application submissions).

---

## Decision

We implement deterministic evidence-grounded application preparation structured around three layers:

### 1. Domain Engine (`backend/app/domain/application_preparation.py`)
- **`filter_usable_evidence(candidate_evidence)`**:
  - Filters out inactive, `REJECTED`, and `SUPERSEDED` candidate facts.
  - Partitions remaining evidence into usable facts, unreviewed facts (`UNREVIEWED`), and conflicted facts (`CONFLICTED`).
- **`generate_tailored_resume(...)`**:
  - Organizes candidate evidence to highlight alignment with target job requirements.
  - Groups matched technical skills under "Relevant Qualifications (Target Alignment)" with verification state tags (`[DOCUMENT_SUPPORTED]`, `[USER_VERIFIED]`, `[UNREVIEWED]`) and provenance span counts.
  - Places additional non-matching skills under "Additional Technical Skills".
  - Structures employment experience, technical projects, education, and certifications directly from validated candidate facts.
- **`generate_tailored_cover_letter(...)`**:
  - Assembles a professional, job-specific cover letter connecting candidate's documented experience to stated requirements.
  - Explicitly and honestly mentions qualification gaps where candidate lacks recorded evidence without making unverified claims of familiarity, experience, or adaptability.
- **`build_application_draft(...)`**:
  - Extracts requirements from `lists_json` and snapshot metadata via existing domain logic.
  - If usable evidence is empty, returns `has_sufficient_evidence = False`, empty resume/cover markdown, and lists all requirements under `evidence_gaps`.
  - Itemizes every requirement into `addressed_requirements` (with supporting claims and provenance) or `evidence_gaps` (with honest explanations).
  - Flags all `unreviewed_claims` and lists `conflicted_claims` excluded from draft.

### 2. Service & API Layer (`backend/app/services/application_preparation.py`, `backend/app/api/routes/job_discovery.py`)
- **`prepare_application_draft(session, posting_id, fact_ids)`**:
  - Loads `JobPosting` and its latest `JobPostingSnapshot`.
  - Loads active candidate evidence via `load_candidate_evidence(session)`.
  - Calls `build_application_draft(...)` and returns the structured draft.
- **Endpoint `GET /api/v1/jobs/{posting_id}/application-draft`**:
  - Returns the complete `ApplicationDraft` package with 404 handling for non-existent postings or snapshots.

### 3. Workbench UI Integration (`frontend/index.html`, `frontend/app.css`, `frontend/app.js`)
- **Detail Pane Header:** Adds "Prepare Application" primary button.
- **Navigation Tabs:** Adds "Application Draft" tab.
- **Draft Interface & Subtabs:**
  - Tailored Resume: Monospace markdown editor, rendered HTML preview toggle, copy button, export `.md` button.
  - Tailored Cover Letter: Markdown editor, rendered preview toggle, copy button, export `.md` button.
  - Addressed Qualifications: Itemized list of requirements satisfied by candidate facts with provenance chips.
  - Evidence Gaps: Itemized list of requirements lacking evidence with honest explanations.
  - Traceability Audit: Complete provenance audit ledger and heuristic notice.
- **Local Persistence & Autosave:**
  - Keyed by `hire_steward_draft_${job_id}` in browser `localStorage`.
  - Detects edits in real time and updates save pill ("Autosaved in browser").
  - Provides "Reset to Original" action to discard edits and restore the grounded server baseline.

---

## Consequences

### Positive
- **Guaranteed Truthfulness:** Zero risk of hallucinating credentials, employers, dates, or skills.
- **Complete Audit Traceability:** Every substantive statement links directly to a candidate fact with verification state and provenance span count.
- **Safety by Default:** Excludes conflicted/rejected facts and warns candidates of unreviewed statements.
- **Clean Architecture:** No unnecessary database migrations prior to Milestone 5 submission lifecycle; uses client-side persistence for working drafts.
- **Local-Only & Offline:** Operates entirely locally with zero external network or third-party AI dependencies.

### Negative / Trade-Offs
- Prose is structured and template-synthesized rather than creative fiction, prioritizing truthfulness and transparency over rhetorical flourishes.
