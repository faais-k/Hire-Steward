# Hire-steward — Phased Implementation Plan

**Plan date:** 2026-10-28  
**Goal:** Build a local-first, evidence-led job discovery and application workspace whose deterministic safety controls remain authoritative.  
**Architecture:** Start with a modular monolith: React/TypeScript UI, Python API, PostgreSQL, a same-codebase background worker and Docker Compose. Keep source, document, AI, email and browser operations behind narrow interfaces. Add infrastructure only when measured need justifies it.  
**Stack:** Python 3.12+, FastAPI/Pydantic, SQLAlchemy 2.x/Alembic, PostgreSQL, React/TypeScript/Vite, Docker Compose, pytest and frontend test tooling. The backend uses a root `pyproject.toml` and a single `uv.lock`; exact resolved package versions are recorded in that lock. Frontend tooling and container versions remain unselected.

## Global constraints

- Safety rules in `application-safety-policy.md` are backend-enforced; scores and models cannot override them.
- Targeting and the minimum annual compensation preference are configurable in the application. The preference defaults to INR 100,000/year and accepts any finite non-negative amount including zero; unpaid roles remain independently ineligible.
- Unknown/conflicting facts remain explicit; no fabrication or silent fail/pass conversion.
- No source is enabled until its exact permitted operation, method, terms, credentials and limits are reviewed.
- Paid AI fallback stays disabled until the user explicitly configures and authorizes a budget.
- No secrets in prompts, ordinary logs, tracked files or default exports.
- No CAPTCHA/access-control/rate-limit evasion, stealth, proxy rotation or account/key rotation.
- Live submission and recruiter email remain disabled until dry-run, permission, duplicate, consent and recovery gates pass and the user explicitly enables them.
- Tests must be deterministic, include regression cases, and must not hit live job boards or employer forms in normal CI.
- Do not add Redis, Celery, Kafka, a separate vector database or Kubernetes without evidence and an ADR.

## Stage A — Audit and baseline

**State:** Audit findings and requested documentation were prepared on 2026-10-28. Phase 0 remains incomplete because no Hire-steward source has been approved and no parser/provider/restore prototype has been run. The owner explicitly authorized the isolated compensation-preference foundation slice before completing the full Phase 0 review; this does not waive any source, provider, or external-action gate.

### Completed in this audit

- Read the Hire-steward Markdown specifications, existing ADRs and project memory.
- Inspected the root, current Git metadata, runtime versions, configuration files and empty `backend/`/`frontend/` directories.
- Audited the eight local references with URLs, SHAs, licenses, source/test/security evidence and reuse cautions.
- Checked current official Greenhouse, Lever, Ashby, Gemini and Groq technical documentation; did not infer legal permission, account-specific quota or cost.
- Recorded the earlier fixed-floor decision in ADR-0006; that decision was superseded by the owner's configurable-preference decision in ADR-0007 and affected policy documents.
- Created/updated the traceability matrix, architecture review, risk register, reference audit, implementation plan and memory.

### Remaining Phase 0 work

1. Owner review of these findings, especially source capability, reference-reuse and operational risks.
2. Root Git/ignore setup and Python lock ownership are in place; review the staged initial baseline before committing. Frontend/Node/container lock and runtime pins remain for their implementation phase.
3. FastAPI/SQLAlchemy/Alembic compatibility has been exercised on Python 3.12.10 with unit and SQLite integration tests; PostgreSQL behavior remains unverified.
4. Current compensation writes have a loopback trusted-host and same-origin guard under ADR-0008. Review any broader local UI/API auth/CSRF design before adding other state-changing routes; remote mode remains out of scope.
5. Select a first source only after current terms and exact operation are reviewed for a concrete source/employer. No live job request is needed during the audit.
6. Select document extractors and any AI provider only after privacy/license/maintenance review and fixture-based quality checks. No paid provider call without explicit budget approval.
7. Specify file-store/DB crash recovery, backup consistency and restore acceptance before accepting real user documents.

**Phase 0 acceptance:** The audit documents the initial state and current source/provider permission remains a hard gate for integrations. The owner explicitly authorized one isolated Foundation 1 slice before all Phase 0 review is complete. This does not mark Phase 0 complete, approve integrations, or remove the current `phases.md` gates. Whether to split Phase 0 into separate foundation-ready and integration-ready gates remains an open planning decision.

## Stage B — Foundation (in progress)

**Entry:** The owner has directly authorized the narrow compensation-preference slice. This does not mean all Stage A findings have been reviewed or that Phase 0 is complete. The root Git repository and ignore policy now exist; package/lock ownership and a loopback/same-origin boundary for the implemented routes are recorded. No external source or live submission is part of this phase.

### Work order

1. Add repository hygiene and tooling: non-empty `.gitignore`, root Python lock strategy, pytest suite, repository instructions, and CI configuration. The root `uv.lock`, focused tests, `AGENTS.md`, and CI workflow now exist; formatting/lint/type checks and frontend lock/runtime remain unselected. CI has not run yet.
2. Create minimal typed backend/API and database boundaries. The compensation-only backend modules now exist; the frontend remains empty and no broad skeleton was created.
3. Persist the minimum-compensation preference as exact INR/year decimal, default to INR 100,000/year, allow zero, validate at the API boundary and enforce the stored value on assessments. **Implemented and locally tested in Foundation 1.**
4. Persist setting changes and immutable assessment snapshots transactionally. **Implemented and locally tested in Foundation 1.**
5. Complete general API readiness and the local PostgreSQL Compose service. `/ready` and the database-only Compose service are implemented; structured logging and broader error/correlation handling remain pending.
6. Add additional durable audit/task/run infrastructure only when required by the next approved slice.

### Foundation 1 — Configurable compensation preference

**Status:** Implemented and locally verified on 2026-10-28. Scope is limited to settings and deterministic compensation assessment; it does not complete Stage B or Phase 4.

- Migration seeds one local preference row as INR 100,000.00/year with exact `NUMERIC(18,2)` storage, database constraints, and version 1.
- `GET/PATCH /api/v1/settings/policies` uses strict decimal-string validation, allows zero, rejects malformed/non-finite/negative values, requires loopback same-origin on writes, and commits the preference plus audit event in one transaction.
- The deterministic evaluator reviews unverified public observations, blocks trusted unpaid roles independently of the threshold, reviews unknown or unsupported compensation, converts only explicitly recurring INR/month pay by 12 when evidence is trusted, and reviews threshold-crossing ranges.
- Assessment rows snapshot reported evidence, explicit verification state, conversion basis, the persisted threshold/currency/unit/version, outcome and stable reason code. Public clients cannot set trusted state, threshold, or AI decision. Migration `0002` marks legacy evidence unverified without rewriting stored facts or threshold snapshots.
- Trusted source-ingestion/verification is not implemented; public compensation assessments remain review-required and cannot proceed to submission. PostgreSQL, UI, dashboard, matching, scheduling, preparation and submission integration remain unverified or unimplemented.

### Foundation 2 — PostgreSQL, Compose, and CI

**Status:** Configuration and test code implemented on 2026-10-28; actual PostgreSQL and hosted CI verification remain pending.

- Root `compose.yaml` runs only PostgreSQL `17.11-bookworm`, with a named persistent volume, environment-configured database/user/password/host port, a loopback-only host binding, and `pg_isready` health check. No frontend, worker, Redis, or broker container was added.
- `.env.example` contains local placeholders and the single SQLAlchemy/Alembic `DATABASE_URL`; `.env` remains ignored. `backend/alembic.ini` no longer carries a second database URL. Alembic requires runtime `DATABASE_URL` when it is not given an injected connection.
- `/health` remains liveness-only. `/ready` checks database connectivity, required model tables and columns plus `alembic_version`, current Alembic heads, and the valid migrated compensation-preference row; it returns a safe `503` if any check fails and never repairs schema state.
- PostgreSQL integration tests require `JOBPILOT_TEST_DATABASE_URL` for the exact `jobpilot_test` database. Each test creates and drops a uniquely named schema rather than dropping the database. Coverage includes fresh/legacy migrations, defaults and numeric precision, audit rollback, decimal persistence, concurrent preference updates, constraints, and public unverified evidence behavior.
- `.github/workflows/ci.yml` uses Python 3.12, pinned uv 0.13.5, locked commands, and a health-checked PostgreSQL service. It checks the lock, compiles backend/migrations, and runs SQLite plus PostgreSQL tests without external secrets or job-site requests.
- The local Docker engine is unavailable, and the installed PostgreSQL Windows service is stopped. PostgreSQL tests were therefore not run locally; CI has not run on GitHub. Compose config validation and SQLite-backed checks are tracked separately in `docs/memory.md`.

**Architecture record:** ADR-0010 selects the PostgreSQL image pin, local environment setup, explicit test-database/schema isolation, and CI verification path. This decision configures local development only; it does not establish production readiness or PostgreSQL compatibility.

### Remaining Stage B acceptance criteria

- A clean checkout starts through a documented local command and shuts down cleanly. **Commands and Compose configuration are documented; not end-to-end verified because the Docker engine is unavailable.**
- API binds to loopback by default; PostgreSQL's Compose host port also binds to loopback. No browser-debug port is exposed.
- `/health` reports liveness only; `/ready` verifies DB connectivity, complete required schema shape, migration heads, and preference state without leaking secrets. **SQLite-backed API tests pass; actual PostgreSQL readiness remains unverified.**
- Invalid config fails clearly and safely. Compensation settings accept zero and other finite non-negative values; reject malformed, negative, NaN, infinite and otherwise invalid values. The unpaid-role prohibition is independent of the setting.
- Logs/errors expose correlation IDs and safe error codes but not environment values, tokens or candidate text.
- Clean-install and migration-upgrade paths are described with a single root lockfile and a pinned PostgreSQL image. **Lockfile checks and SQLite migration paths are verified; PostgreSQL migration execution remains pending.**
- CI runs locked dependencies, compilation, SQLite tests, and PostgreSQL integration tests. **Workflow configuration exists; no hosted CI run has occurred.**
- Unit/integration tests cover settings validation, health/readiness, logging redaction, DB session isolation and initial constraints. CI does not contact live sources/providers.

## Stage C — Core product

### Phase 2 — Candidate evidence and provenance

**Depends on:** Foundation, storage permissions, selected extractors and file limits.

- Implement document registry, safe file ingestion, hash/version metadata and staged filesystem writes.
- Store raw extraction separately from accepted facts; attach evidence ID, source version/span, confidence, sensitivity and verification state.
- Add conflict resolution and manual profile editing; changed-file scans must be incremental.
- Add PDF/DOCX/TXT/Markdown/CSV/XLSX fixtures; keep OCR optional until measured.

**Acceptance:** Re-ingesting identical content creates no duplicate active version; parse failure/empty output cannot erase accepted facts; every accepted fact traces to a version or user entry; malformed/oversized input is rejected or quarantined; file/DB consistency checks detect missing/orphaned artifacts.

### Phase 3 — Permitted discovery and source registry

**Depends on:** Phase 2 data contracts, the source-specific terms/method review, and an explicit capability record for the first adapter.

- Add a versioned source registry: exact host/method/operation, review date, credentials, rate limits, request caps, schema version and disable conditions.
- Implement one read-only adapter only after its capability is verified; add fixture-only contract tests and source-run/checkpoint records.
- Add bounded page fetching, timeouts, `Retry-After`, per-source leases, raw observations, normalized snapshots and conservative dedupe.
- Use manual URL intake or fixtures when no source is approved.

**Acceptance:** Source is disabled by default; enabling requires current capability/terms metadata; one source failure does not halt another; partial/failed runs never advance successful checkpoints; duplicate logic records its rationale and does not merge on title alone; no live request runs in CI.

### Phase 4 — Deterministic policy, retrieval and explainability

**Depends on:** Candidate evidence and job snapshots. Labeled evaluation data must be prepared before score thresholds authorize actions.

- Implement compensation parsing with decimal arithmetic, source evidence, explicit units and recorded annualization/FX assumptions.
- Implement deterministic gates for unpaid and below-configured-minimum compensation, mandatory qualification mismatches, unknown sponsorship, user targeting, confidence, exact duplicates, 30-day cooldown and consent. Snapshot the persisted minimum/currency/unit at every assessment and policy evaluation; audit changes and preserve prior assessment/submitted-application history.
- Establish lexical FTS baseline and evaluation set. Add semantic embeddings/pgvector only if privacy approval and evaluation justify it.
- Version score components separately from confidence and eligibility; attach evidence IDs to explanations.

**Acceptance:** Zero hard-gate leakage in the release gold set; trusted confirmed unpaid and verified annualized compensation below the configured minimum are blocked; unverified/unknown/non-normalizable/threshold-straddling compensation routes to review; above-minimum trusted compensation passes the compensation gate only; the persisted setting is enforced consistently through matching, dashboard, schedules, preparation and the final gate; historical thresholds and submitted records remain unchanged after edits. Foundation 1 covers the deterministic compensation cases listed in `testing-evaluation.md`; public compensation evidence remains unverified until a trusted ingestion path exists. Cross-product wiring, submitted-application preservation, labeled retrieval quality and the full Phase 4 release gate remain pending. Relevant skills/work evidence can outweigh experience/keyword gaps without overriding hard gates; ranking metrics and false-positive cases are reported; ranking thresholds remain provisional until calibrated.

### Phase 5 — Grounded AI preparation

**Depends on:** Phases 2–4, provider/privacy decisions, schema validation and explicit provider data-sharing settings.

- Add task-specific provider adapters/router, schemas, limits, privacy classification, usage telemetry and evaluation harness.
- Implement evidence-grounded requirement extraction, explanations, minimal resume edits, optional cover letters and answer-bank reuse with scoped consent.
- Add hostile prompt-injection and malformed-output fixtures.

**Acceptance:** Every candidate-specific claim references valid evidence or is held for user confirmation; unsupported claims are rejected; one-time answers are not reused without consent; secrets do not enter prompts/logs; provider quota/budget exhaustion defers work; paid fallback remains off absent authorized budget.

## Stage D — Automation after foundations

### Phase 6 — Application state machine and dry-run executor

**Depends on:** Phases 1–5, source-specific submission capability record, final form mapping, consent UI and application/legal policy.

- Implement immutable `SubmissionPlan`, fresh final gate evaluation, one active attempt, daily counters, transactional dedupe and audit event.
- Build a simulated ATS and a dry-run preview showing exact destination/documents/answers/consent.
- Implement `CONFIRMATION_UNKNOWN` and read-only/manual reconciliation; no blind retry.

**Acceptance:** Fault-injection cases cover crash before request, remote acceptance plus timeout, browser crash after click, unclear confirmation, simultaneous clicks and reconciliation. Unknown result never becomes `APPLIED`; duplicate/cap gates are transactional; real submission is still disabled by default.

### Phase 7 — Limited live submission pilot (separate explicit approval)

**Entry conditions:** All earlier gates pass; current source terms and exact method are verified; one source is enabled; user explicitly approves source/action mode; emergency stop and rollback are tested.

- Enable one source/method at a time; start with manually approved `READY_TO_SUBMIT` actions.
- Maintain one active external attempt and the default daily cap; collect source-specific confirmation evidence.
- Disable on schema drift, CAPTCHA/access warning, unexpected fields or ambiguous outcome.

**Acceptance:** No duplicate in the pilot; every outcome has evidence or remains uncertain; no unsupported answer; user can stop immediately. No amount of model score substitutes for these checks.

### Phase 8 — Recruiter email, portability and operations

**Depends on:** Stable application records, consent, secure credential storage, restore design and separate Gmail/OAuth review.

- Add draft-only email by default; send only to a verified application-channel address after consent and policy gates.
- Add uncertain-send reconciliation and daily caps.
- Implement versioned export/import with staging, checksums, traversal/size checks, secret exclusion and conflict reports.
- Implement encrypted backup/recovery process, retention/deletion controls and restore drill.

**Acceptance:** No duplicate send after uncertain outcome; no secrets in sentinel scans; export/import preserves hashes/provenance/counts; invalid archives do not mutate live state; restore into a clean instance reconciles uncertain attempts before external actions.

## Phase 9 — Scale only on measured need

**Revisit triggers:** sustained scheduler backlog, measured database latency, retrieval recall/latency failure at representative corpus size, approved multi-user scope, or remote availability requirement.

Possible changes include a broker-backed queue, separate worker pools, managed PostgreSQL/object storage, approximate vector indexes, remote auth/TLS deployment or reranking. Each change requires measurements, an ADR, security/recovery updates and a rollback path. No trigger is currently evidenced.

## Dependency order

`Repository/security baseline → foundation → evidence/provenance → permitted discovery → deterministic policy/evaluation → AI preparation → dry-run application lifecycle → separately approved live pilot → email/export/operational hardening → evidence-based scaling`

## Current implementation status

Stage B is `IN_PROGRESS`; Foundations 1 and 2 have local backend/database/CI configuration with a public compensation-evidence trust boundary. Public assessments remain unverified until a controlled source verifier is implemented. Current SQLite, Compose syntax, lockfile, and compilation results are recorded in `docs/memory.md`; actual PostgreSQL and hosted CI evidence remain outstanding. Phase 0 remains incomplete, and the owner-directed work does not approve sources/providers or satisfy their entry gates. Next, run the PostgreSQL suite against the isolated test DB or CI, then continue the remaining general foundation before any source integration.
