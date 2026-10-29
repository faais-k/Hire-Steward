# ADR-0017: User-Controlled Job Intake Without Live Source Activation

- **Status:** Accepted (Milestone 6 / User Intake)
- **Date:** 2026-10-29

## Context

Hire-Steward has established:
1. Deterministic job discovery persistence and observation models (ADR-0013, Alembic revision `0004_job_discovery_persistence`).
2. Candidate document evidence and provenance tracing (ADR-0011, Alembic revision `0003_candidate_evidence`).
3. Explainable job matching and qualification scoring (ADR-0014).
4. Secure local discovery workbench (Milestones 3 & 3.1).
5. Evidence-grounded application material synthesis and client-side draft management (ADR-0015).
6. Application tracking, status history, and immutable snapshot freezing (ADR-0016, Alembic revision `0005_application_tracking`).

However, automated live job discovery remains gated: Phase 0 is `IN_PROGRESS / NOT PASSED`, and all candidate external sources (Lever, Greenhouse, Ashby, and Direct Employer Portals) remain in `NEEDS_REVIEW` and disabled (ADR-0012, Phase 4.1). Automated crawlers cannot be activated without product owner risk posture resolution and explicit source authorization.

In real-world job searches, candidates encounter job postings across various external channels (company career pages, direct referrals, specialized forums, or recruiter communications). To provide immediate value without waiting for live crawler licensing, Hire-Steward must allow candidates to manually bring specific job opportunities into the workbench for explainable matching, evidence-grounded application drafting, and pipeline tracking.

### Core Problems & Risks to Mitigate:
1. **Network Evasion & Covert Scraping Risk:** Job intake must not fetch the reference URL in the background. Crawling, headless browser rendering, or background scraping of employer URLs would bypass source-permission gates and anti-scraping policies.
2. **Schema Fragmentation / Parallel Silos:** Creating a separate table or schema for "user jobs" would duplicate matching, drafting, and pipeline logic. User-entered jobs must seamlessly integrate into the existing relational model.
3. **Provenance Confusion & Data Integrity:** User-supplied jobs must never masquerade as source-verified postings. Downstream UI, match evaluations, and application records must explicitly indicate unverified user provenance.
4. **Input Size & Malicious Injection Boundaries:** Unsanitized, arbitrarily large text inputs could cause denial-of-service, database bloating, or memory exhaustion. Inputs must enforce strict boundary limits.
5. **Duplicate Postings:** Submitting the same job multiple times could pollute the workbench and duplicate application tracking pipelines.
6. **Safety Gate Bypass:** The manual intake mechanism must not create a backdoor that enables automated crawlers to run against unapproved sources.

---

## Decision

We implement a user-controlled, strictly offline job intake mechanism:

### 1. In-Memory Validation and Offline URL Handling

- Reference URLs are validated strictly for syntax using standard in-memory parsing (`urllib.parse`).
- Only `http` and `https` schemes with non-empty hostnames are permitted. Dangerous schemes (`javascript:`, `data:`, `file:`, `ftp:`) and credentials (`user:pass@host`) are rejected (`422 Unprocessable Content`).
- Maximum URL length is capped at 2,048 characters.
- **Zero Sockets / Zero Network Traffic:** No DNS resolution, HTTP request, or socket creation is performed. The reference URL is stored strictly as unverified text reference for the candidate's personal browser navigation.

### 2. Schema and Relational Model Reuse

Zero database migrations are introduced. User job intake fully reuses the existing relational schema:
- **`JobSource`**: Idempotently seeds a `manual_intake` source record with `capability_status="MANUAL_ONLY"` and `is_enabled=False`. This satisfies database check constraints (`ck_job_sources_status` and `ck_job_sources_active_gate`) while ensuring the source cannot be scheduled or executed by discovery runners.
- **`EmployerSubscription`**: Uses normalized employer handles (e.g., `acme-corp` or `user-provided`).
- **`DiscoveryRun`**: Records a synthetic `DiscoveryRun` (`status="SUCCEEDED"`).
- **`JobPosting`**: Assigned a unique identifier (`user_{hash[:16]}`) and lifecycle status `ACTIVE`.
- **`JobPostingSnapshot`**: Stores title, location, workplace type, commitment, reference URL (`canonical_url`), plain-text description, and parsed bulleted sections (`lists_json`). Sets `publication_date_status="UNKNOWN"`, `published_at=None`, and provenance notice `additional_plain="User-entered job intake; unverified by external source."`.

### 3. Strict Provenance and UI Indicators

User-supplied records are clearly distinguished from source-verified or synthetic fixture data:
- API responses explicitly return:
  - `is_user_entered: True`
  - `source_type: "USER_INTAKE"`
  - `source_verification_status: "UNVERIFIED_USER_SUPPLIED"`
  - `is_reference_url_only: True` (when a reference URL is present)
- Workbench UI displays:
  - `User Added` badge in the opportunity card list.
  - `User-Provided (Unverified)` tag in the detail header.
  - Clear label indicating that the URL is a user-provided reference link.

### 4. Input Boundaries and Deduplication

- **Title:** 1 to 500 characters. Cannot be empty or whitespace only.
- **Description:** 20 to 50,000 characters. Plain-text bulleted lists and section headers (e.g., "Requirements:", "Qualifications:") are parsed into structured `lists_json` blocks for deterministic requirement extraction.
- **Workplace Type:** Strictly normalized to `"remote"`, `"hybrid"`, `"onsite"`, or `None`.
- **Deduplication:** A deterministic raw hash (`manual_intake\n{employer_handle}\n{title}\n{description}`) is computed. Attempting to add an identical job under the same employer raises `DuplicateJobPostingError` and returns `HTTP 409 Conflict`.

### 5. Seamless Downstream Interoperability

Because user-entered jobs produce standard `JobPosting` and `JobPostingSnapshot` records:
- **Explainable Matching (`assess_job_match`):** Immediately evaluates qualification coverage, gaps, and confidence scores against candidate evidence facts.
- **Application Drafting (`prepare_application_draft`):** Synthesizes evidence-grounded resume and cover letter drafts tailored to the user-entered requirements with zero hallucinatory claims.
- **Application Pipeline (`save_or_track_job`):** Allows candidates to track the position (`SAVED`, `PREPARING`, `APPLIED`), freeze immutable submission snapshots with SHA-256 digests, and record interview progress.

---

## Consequences

### Positive:
- Candidates can immediately use Hire-Steward's core value proposition (matching, drafting, tracking) on any real-world opportunity.
- Preserves complete legal, network, and contractual safety: zero web scraping, zero automated crawl requests, zero bot evasion.
- Zero schema migration overhead: eliminates database drift and reduces architectural complexity.
- Fail-closed security: `manual_intake` source cannot be targeted by automated discovery crawlers.

### Mitigations:
- Candidates must manually paste job descriptions rather than pasting a link and expecting automatic import. This trade-off is intentional to prevent unauthorized web scraping and fragile crawler maintenance.
- Visual badges ensure candidates and reviewers always recognize that user-entered postings have not been verified by an external job source.
