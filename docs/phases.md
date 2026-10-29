# Hire-steward — Implementation Phases and Release Gates

**Status:** Proposed roadmap. Complete each phase's acceptance gate before building the next high-risk capability. Timelines are intentionally omitted until repository and workload are inspected.

**Current implementation:** Milestone 6 (User-Controlled Job Intake) is committed and pushed as `b709013` on branch `foundation-3-candidate-evidence`, passing 333 tests locally and verified in hosted GitHub Actions CI (Run 40884209323: 333 passed, 0 failed, 3 warnings, all 24 PostgreSQL integration tests passing). Offline discovery (Milestone 1, `214dfea`), deterministic matching (Milestone 2, `e022a47`), review workbench (Milestones 3 & 3.1, `8f19559` & `3dba991`), evidence-grounded application preparation (Milestones 4 & 4.1, `b8a9b59`), and application tracking pipeline (Milestone 5, `7182b65`) are completed and committed. The intake flow remains strictly offline and does not activate live job sources. Phase 0 remains `IN_PROGRESS / NOT PASSED` until its source-permission exit gate is formally resolved by the product owner; live-source permission is still unresolved, and Lever and the other candidate sources remain disabled, unapproved, and in `NEEDS_REVIEW`. No live ATS requests, scraping, or external network discovery are activated. Live discovery cannot begin while Phase 0 is not passed.

## Delivery principle

Build vertical slices that prove the core lifecycle and safety properties. Do not begin unattended live application submission before source permissions, facts/provenance, deterministic gates, state persistence, crash recovery and test evidence exist.

## Phase 0 — Repository and feasibility audit

### Work
- Establish the actual repository, Python/Node versions, dependency lock strategy, environment, CI, database status, and existing code boundaries.
- Review any company-owned architectural material only for authorized concepts; do not copy proprietary source code or secrets without explicit permission.
- Select initial one or two permitted job sources after checking current official documentation, terms, and available public interfaces.
- Build a source capability matrix distinguishing public read, authenticated read, application submission, browser-only/manual, rate limit and terms status.
- Confirm free-tier model availability, quotas, data use and budget behavior from official dashboards/docs.
- Create an initial data inventory and threat model.

### Deliverables
- Repository audit findings.
- Initial ADRs for deployment architecture, database, source access and AI privacy.
- Prototype findings for file extraction, source ingestion and backup/restore.
- Updated `memory.md` with verified repo state.

### Exit gate
- No unresolved license or source-permission blocker for the first source (Criterion 1: Owner formal source-access decision / legal risk acceptance).
- Approved single-request live test protocol (Criterion 2: Owner sign-off on isolated live test against agreed board).
- Verified offline invariant suite (Criterion 3: 88 Lever adapter tests passing with loop detection, pagination bounds, and honest attribution).
- Stack versions selected with compatibility confirmed.
- Data handling and provider-sharing behavior understood.

## Phase 1 — Foundation and local runtime

Foundation 1 implements the compensation setting, deterministic compensation-only evaluation, change audit, migrations, assessment snapshot, and a fail-closed public evidence boundary. Foundation 2 implements local PostgreSQL Compose configuration, database readiness, an isolated PostgreSQL integration suite, CI workflow configuration, and operator guidance. PostgreSQL execution, GitHub CI execution, trusted source ingestion/verification, frontend, structured logging, and other Phase 1 acceptance criteria remain incomplete. See `implementation-plan.md`, ADR-0008, ADR-0009 and ADR-0010.

### Work
- Create backend/frontend skeleton, configuration validation, health/readiness endpoints, structured logs, migrations, Compose, and local persistent volume.
- Add localhost-only defaults and a startup diagnostic command.
- Implement DB session lifecycle, correlation IDs, standard error schema, and append-only audit event foundation.
- Set up formatting, linting, typing, unit tests, security/dependency scans where practical, and CI.

### Deliverables
- Repeatable single-command startup, health check and clean shutdown.
- Migration-upgrade tests and environment template.
- No real secrets in repository.

### Exit gate
- Fresh install and upgrade path both work from documented steps.
- Local API cannot be reached from external interfaces by default.

## Phase 2 — Candidate evidence and fact provenance

### Work
- Implement document registry, content hashing, immutable file versions, directory scanner, format adapters and extraction jobs.
- Add candidate fact schema, source provenance, confidence, sensitivity, verification state and conflict workflow.
- Keep raw extraction separate from user-accepted facts.
- Make failed/empty extraction non-destructive.
- Build manual profile editor and document review screens.
- Add safe file-type checks and file-size limits; quarantine malformed inputs.

### Deliverables
- Evidence library, version history and user fact verification.
- Parser fixtures covering text PDFs, multi-page docs, DOCX tables, CSV and XLSX cases.
- Incremental rescan without duplicate versions for unchanged content.

### Exit gate
- No lost prior accepted facts on parser error.
- Every accepted candidate fact traces to a document/version or explicit user entry.
- Contradictions are visible rather than silently resolved.

## Phase 3 — Permitted discovery and source registry

### Work
- Implement source adapters for the first verified source(s), source registry, rate limiter, checkpoints, page cursors, run records and raw observations.
- Support first-run 14-day search and scheduled runs at 10:00/17:00/22:00 Asia/Kolkata.
- Ensure failed sources do not advance checkpoints; healthy sources continue if another source errors.
- Normalize jobs and save immutable job snapshots/observation history.
- Build duplicate detection using source IDs, canonical URLs and conservative matching.

### Deliverables
- Job inbox with source, publication/observation date, original URL, normalized fields, source status and dedupe explanation.
- Source health dashboard.

### Exit gate
- Fixture-based pagination, rate limit, retry and checkpoint tests pass.
- No source is activated without a recorded permitted access method.
- A first run and an interrupted run can be resumed without losing unseen jobs.

## Phase 4 — Matching, policy gates and explainability

### Work
- Parse job requirements into mandatory/preferred categories.
- Implement deterministic eligibility policies for compensation, unpaid work, duplicates/cooldowns, sponsorship unknowns, mandatory mismatches, user targeting and confidence.
- Add hybrid retrieval only if the evidence corpus warrants it: PostgreSQL full-text search plus a selected embedding model/pgvector, with versioned embeddings and RRF.
- Implement versioned score components and a separate confidence signal.
- Build labeled evaluation data from representative real/synthetic jobs and candidate evidence.

### Deliverables
- Job assessment detail screen with reasons, evidence IDs, unknowns and score breakdown.
- Policy unit tests and versioned scoring configuration.
- Evaluation report comparing simple keyword baseline, full-text, semantic and hybrid retrieval where available.

### Exit gate
- Mandatory failures and unresolved mandatory facts cannot be auto-submitted.
- The configurable minimum preference defaults to INR 100,000/year; finite non-negative values including zero are valid. Backend policy uses the persisted preference at assessment time.
- Trusted confirmed unpaid roles are always blocked, regardless of the minimum; unverified reported unpaid status routes to review and cannot proceed. Reliable values/ranges wholly below the minimum block; values/ranges wholly above pass this gate only; unknown, unsupported conversions and ranges crossing the minimum route to review unless reliable evidence resolves uncertainty.
- Assessment and application policy snapshots retain the minimum/currency/unit and conversion basis used. A setting change does not rewrite prior assessments or submitted application facts, answers or outcomes.
- Matching, dashboard explanations, scheduled reassessment, application preparation and final submission use the same deterministic evaluator. Model output cannot alter the setting or gate result.
- All compensation acceptance cases in `testing-evaluation.md` pass before this phase exits. These are pending; no implementation or test evidence exists yet.
- Unknown compensation/sponsorship routes to investigation/review as defined.
- Score and confidence never collapse into one decision variable.
- Initial thresholds are explicitly provisional until enough labeled cases exist.

## Phase 5 — Resume/answer preparation and review

### Work
- Add AI provider interface/adapters, schema-bound extraction/classification, model router, privacy gating and usage telemetry.
- Prepare conservative resume edits and optional cover letters.
- Implement answer bank with separate reusable consent and context/equivalence checks.
- Build question-answer review queue and source evidence display.
- Add prompt-injection fixtures for hostile job descriptions, documents and emails.

### Deliverables
- Proposed application package with claim-to-evidence mapping.
- Provider usage/quota/error view.
- Human edit/approve/reject flow.

### Exit gate
- Gold-set claims are grounded; unsupported facts fail validation.
- A one-time user answer is not reused without consent.
- Provider data-sharing settings are respected; secret values never reach the LLM.

## Phase 6 — Application state machine and dry-run executor

### Work
- Implement states, immutable `SubmissionPlan`, policy evaluation snapshot including the current persisted compensation preference, daily counters, one-at-a-time external attempt lock, and state-transition audit.
- Create a simulated ATS adapter for deterministic crash/recovery testing.
- Add submission-attempt reconciliation and `CONFIRMATION_UNKNOWN` handling.
- Build exact document/answer snapshot storage and pre-submit final checks.

### Deliverables
- Dry-run application workflow showing what would be submitted, to whom, on what source, and why.
- Fault-injection tests for crashes before/after request and browser timeout.

### Exit gate
- No real external submission is enabled by default.
- Unknown result never becomes `APPLIED` automatically.
- Retrying after an uncertain result is blocked pending reconciliation.
- Duplicate and daily-limit gates are enforced transactionally.

## Phase 7 — Limited live submission pilot

### Entry conditions
- All earlier release gates pass.
- Source terms and submission paths are verified on a per-source basis.
- User explicitly enables the source and application mode.
- A documented rollback/disable switch exists.

### Work
- Enable only one known permitted submission path at a time.
- Start with manually approved `READY_TO_SUBMIT` actions; broaden automation only after observed reliability.
- Keep one active external application at a time and default cap at five/day.
- Collect confirmation evidence and reconcile every result.
- Monitor form drift and errors; disable an adapter after repeated unexpected behavior.

### Exit gate
- No duplicate submissions in the pilot.
- All submission outcomes supported by evidence or visibly marked uncertain.
- No unsupported or false answer in reviewed sample.
- Human can stop automation immediately.

## Phase 8 — Recruiter email, portability and operational hardening

### Work
- Add Gmail OAuth only after scope/verification review; use drafts for ambiguous contact purposes.
- Implement email dedupe and uncertain-send reconciliation.
- Implement versioned export/import with manifest, hashes and secret exclusion.
- Implement backup/restore, upgrade rollback, data retention controls, and local system diagnostics.

### Exit gate
- Export passes schema and integrity verification and imports into a clean instance.
- No credentials/tokens/cookies are present in export fixtures.
- Email tests prove no duplicate resend after uncertain outcome.
- Backup restore is rehearsed.

## Phase 9 — Scale and quality optimization

### Evidence that may justify change
- Sustained scheduler backlog or worker timeouts.
- Database query latency exceeding a defined target on representative data.
- Vector retrieval at the chosen corpus size failing measured latency/quality targets.
- Multi-user requirements explicitly approved.
- Remote availability needed and threat model updated.

### Potential changes
- Add a durable queue such as a broker-backed worker system.
- Add managed PostgreSQL/object storage, separate worker pools or a deployment orchestrator.
- Add an optional reranker only if it improves measured precision/recall enough to justify cost/latency.
- Partition/retention/archive larger event and observation tables after monitoring query plans.

### Exit gate
- Each added component has a measured need, ADR, operational owner and rollback plan.

## Critical path

`Foundation → Evidence/provenance → Permitted discovery → Policy/matching → Prepared content → Dry-run state machine → Limited live pilot → Email/export hardening → Scale`

Do not invert the order by building browser submission first. The highest-risk defect is not a poor UI; it is an incorrect, duplicate, unauthorized or untraceable external action.

## Phase status tracking format

Update this file or `memory.md` with:

- Phase state: `NOT_STARTED | IN_PROGRESS | BLOCKED | COMPLETE`.
- Evidence: commit/PR, test run, screenshots/log references, or measured report.
- Gate owner and remaining failure cases.
- Date of last verification.

A phase is not `COMPLETE` because code exists; it is complete when its acceptance gate is proven.
