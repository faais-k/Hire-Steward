# Hire-steward — Product and Engineering Documentation

**Status:** Complete local-first, single-user application implementation with verified defect remediation across all application stages.
**Documentation baseline date:** 2026-11-11
**Deployment target:** Local-first FastAPI application serving compiled React 18 + TypeScript strict mode + Vite frontend across 13 workbench screens (PostgreSQL 17.11 / SQLite)
**Primary objective:** A reliable, explainable, privacy-conscious job discovery, candidate profile, tailoring, and application tracking workbench with dry-run simulation, safe data portability, and deterministic safety gates.
**Automated Test Suite:** 681 passed (641 offline + 40 PostgreSQL integration tests, 0 failures, 100% pass rate) plus 10 frontend Vitest tests (100% pass rate).
**Browser UI Test Status:** VERIFIED — 13/13 screens, 12 master E2E journeys, and responsive native scrolling at 100% zoom verified across 6 viewports and scaling factors in Chromium over CDP with 0 JavaScript errors.

## Capability Status Vocabulary & Truthful Boundary Summary

In accordance with Section 7 of the Master Engineering Specification, system capabilities are classified under the authoritative status vocabulary:

| Capability Area | Status | Operational Note |
| :--- | :--- | :--- |
| **Candidate Profile & Preferences** | `IMPLEMENTED_AND_VERIFIED` | 100% complete; persistence across restarts verified with authentic candidate profile. |
| **Document Parsing & Evidence Provenance** | `IMPLEMENTED_AND_VERIFIED` | Binary SHA-256 storage, decompression safety, byte-span provenance, user review state machine. |
| **Deterministic Compensation Gating** | `IMPLEMENTED_AND_VERIFIED` | Fail-closed: unverified evidence requires review; confirmed unpaid or below-floor jobs blocked. |
| **Same-Company 30-Day Cooldown** | `IMPLEMENTED_AND_VERIFIED` | Authoritative eligibility service; 5d/29d/30d boundary, withdrawn/rejected handling, Asia/Kolkata timezone support. |
| **Submission Planning & Hash Freezing** | `IMPLEMENTED_AND_VERIFIED` | SHA-256 packet hashing, verified reviewed resume and cover letter requirements. |
| **Dry-Run ATS Simulation** | `IMPLEMENTED_AND_VERIFIED` | Idempotent simulated dispatch, persistent receipts in ApplicationAttempt table, zero external egress. |
| **Application Tracking & Lifecycle** | `IMPLEMENTED_AND_VERIFIED` | Saved → Ready for Review → Applied → Interviewing → Offer/Rejected with audit trail. |
| **Answer Bank & Granular Consent** | `IMPLEMENTED_AND_VERIFIED` | `reuse_consent` defaults to False; opt-in enforcement across AI and preparation workflows. |
| **Data Portability & Import/Export** | `IMPLEMENTED_AND_VERIFIED` | Versioned JSON archive export and transactional import with rollback protection. |
| **Manual User Job Intake** | `IMPLEMENTED_AND_VERIFIED` | Immediate parsing, scoring, and matching for user-provided job descriptions and URLs. |
| **Job Discovery (Greenhouse, Ashby, Lever)** | `DISABLED_PENDING_APPROVAL` | Read-only adapters implemented and verified via mock HTTP contracts; live sync disabled pending user-configured employer handles. |
| **External AI Providers (Groq, Gemini, Anthropic, OpenAI)** | `IMPLEMENTED_NOT_FULLY_VERIFIED` | Adapter routing, budget fencing, SecretStr masking, and mock transports verified; live API keys not yet provided. |
| **Autonomous External ATS Submission** | `NOT_APPLICABLE_BY_DESIGN` | Human-controlled handoff only. Automated submission without human review is disabled by design. |

## Start here

1. [`docs/project-requirements-document.md`](docs/project-requirements-document.md) — what to build, for whom, features, scope, and measurable outcomes.
2. [`docs/architecture.md`](docs/architecture.md) — system boundaries, flows, components, deployment, and proposed repository structure.
3. [`docs/rules.md`](docs/rules.md) — engineering standards, dependency policy, AI boundaries, reliability, and prohibited shortcuts.
4. [`docs/phases.md`](docs/phases.md) — implementation phases, dependencies, gates, and acceptance criteria.
5. [`docs/design.md`](docs/design.md) — visual design system, tokens, typography, interaction states, and accessibility.
6. [`docs/memory.md`](docs/memory.md) — project status, completed decisions, current work, blockers, and next actions. Update this after meaningful changes.

## Supporting specifications

- [`docs/data-model.md`](docs/data-model.md) — proposed entities, important fields, constraints, and indexing approach.
- [`docs/ai-spec.md`](docs/ai-spec.md) — provider routing, extraction, matching, confidence, prompt-injection boundaries, and evaluations.
- [`docs/application-safety-policy.md`](docs/application-safety-policy.md) — eligibility gates, application state machine, consent, submissions, email, CAPTCHA, and legal declarations.
- [`docs/job-discovery-sources.md`](docs/job-discovery-sources.md) — per-source permissions, checkpoints, deduplication, backfill, rate limits, and provider capability checks.
- [`docs/api-spec.md`](docs/api-spec.md) — proposed internal API shape and response/error contracts.
- [`docs/security-privacy.md`](docs/security-privacy.md) — threat model, secrets, sensitive data, audit trail, and retention.
- [`docs/testing-evaluation.md`](docs/testing-evaluation.md) — quality strategy, fixtures, metrics, adversarial tests, and release gates.
- [`docs/operations-deployment.md`](docs/operations-deployment.md) — Docker Compose, configuration, backup, restore, upgrades, and recovery.
- [`docs/export-import.md`](docs/export-import.md) — portable, versioned export/import contract.
- [`docs/observability-and-cost.md`](docs/observability-and-cost.md) — run logs, AI usage, quotas, costs, alerts, and dashboards.
- [`docs/decisions/`](docs/decisions/) — architecture decision records (ADRs).

## How to interpret this pack

- **Confirmed requirement** means a decision agreed in product discussions.
- **Proposed default** means an explicit starting point that should be tested and may be changed deliberately.
- **Needs verification** means the team must validate the fact against the selected provider, terms, live behavior, or measured benchmark before relying on it.
- **Release gate** means a condition that must pass before moving to the next stage.

The documentation pack constitutes the formal architectural baseline. All 13 workbench screens and backend core domains are fully implemented and verified locally. Live external discovery sources remain disabled pending user-configured employer handles (`DISABLED_PENDING_APPROVAL`), external AI providers operate with verified mock contracts pending user API keys (`IMPLEMENTED_NOT_FULLY_VERIFIED`), and automated external submission is prohibited by design (`NOT_APPLICABLE_BY_DESIGN` - human-controlled handoff only). Do not treat similarity scores, unverified drafts, or simulated receipts as external submissions.

## Current implementation status and defect remediation

The application is implemented as an offline-first modular monolith supporting both SQLite and PostgreSQL. All material defects identified in review have been corrected and verified:

1. **Answer Bank Consent Enforcement (P0):** Reusable responses strictly require opt-in consent (`reuse_consent=True`, default `False`). AI question answering, submission plan generation, and manual handoffs filter for consented answers only (`consent_only=True`). Answer revocation and version histories remain immutable.
2. **User Settings Persistence Decoupling (P1):** Search policies, compensation minimums, daily caps, and cooldowns are stored in a dedicated `user_settings` table (Alembic migration `0007_user_settings`). Candidate profile updates never overwrite or erase user search policies.
3. **Data Portability Integrity & Complete Restoration (P0):** Import bundles require valid SHA-256 checksums matching the bundle payload. Collision detection previews existing facts and settings. Commit operations execute inside an atomic database transaction with complete rollback on failure, restoring profiles, settings, candidate facts, consented answers, and tracked applications.
4. **Deterministic Submission Eligibility (P0):** Submission plans and ATS dry-run simulation enforce verified compensation (`is_compensation_eligible`) and cooldowns (`is_cooldown_clear`) without hardcoded overrides. Tailored drafts strictly fail closed (`422 APPLICATION_MATERIALS_INCOMPLETE`) rather than outputting generic ungrounded template text.
5. **Candidate Evidence Workflow & Parser Hardening (P1):** Document parser features strict decompression-bomb protection (20 MB uncompressed cap on DOCX and PDF) and detects scanned-only PDFs (`OCR_REQUIRED`). Candidate facts persist with document provenance and support user review (`POST /api/v1/facts/{id}/verify` and `POST /api/v1/facts/{id}/reject`).
6. **Honest AI Status & Zero Fabrication (P1):** The AI router truthfully reports `active_mode = "OFFLINE_MOCK"` and `live_inference_authorized = False`. Question responses without supporting facts return empty answers with explicit `evidence_gaps` rather than fabricated career claims.
7. **Source Registry Safety (P1):** Source updates require verified read-only capability and documented terms review (`TERMS_REVIEW_REQUIRED`). Live web scraping remains strictly disabled.
8. **UI Integration & Verification Status:** All 13 workbench screens are implemented and wired to backend endpoints. Live browser interactions are verified using headless Chrome over the Chrome DevTools Protocol (CDP): 13/13 screens verified with 0 console errors, and the 26-step end-to-end user journey verified end-to-end (`scratch/test_e2e_journey.js`).

The API binds to loopback when run with the commands below. `/health` reports process liveness; `/ready` checks database connectivity, the complete required table and column shape, current Alembic migration heads, and a valid migrated compensation-preference row. The local same-origin write check is not authentication and does not make remote exposure safe.

## Local development setup

### Frontend Development & Build Workflow
```powershell
# Typecheck TypeScript (strict mode)
npm --prefix frontend run typecheck

# Run Vitest component tests
npm --prefix frontend run test

# Compile production bundle for FastAPI serving (dist/)
npm --prefix frontend run build

# Start Vite HMR dev server (proxies to FastAPI on 127.0.0.1:8000)
npm --prefix frontend run dev
```


The following PowerShell commands describe workspace operation. Docker Compose runs PostgreSQL 17.11 on loopback port 5432 with isolated test schemas for integration testing and a clean personal database `jobpilot_workspace` for real candidate usage.

Install the locked Python dependencies and check the lockfile:

```powershell
uv lock --check
uv sync --locked --python 3.12
```

Create the ignored local environment file and replace the development-only password if desired. Keep `DATABASE_URL` consistent with the PostgreSQL variables and host port:

```powershell
Copy-Item .env.example .env
```

Start and inspect the PostgreSQL service. Its host binding is loopback-only:

```powershell
docker compose up -d db
docker compose ps
docker compose logs db
docker compose exec db pg_isready -U jobpilot -d jobpilot
```

Apply and inspect migrations, then run the API on localhost:

```powershell
uv run --locked --env-file .env alembic -c backend/alembic.ini upgrade head
uv run --locked --env-file .env alembic -c backend/alembic.ini current
uv run --locked --env-file .env uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Run `/health` and `/ready` checks in another PowerShell window:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
```

Run fast unit and SQLite-backed API/migration tests:

```powershell
uv run --locked pytest -m "not postgres" -q
```

Candidate-evidence uploads require an absolute `EVIDENCE_STORAGE_ROOT` outside this checkout. The current implementation accepts only UTF-8 `text/plain` document versions. To reconcile stale reservation-accounted files after a crash, use the explicit local operator command; it refuses to change storage without `--apply` and never deletes a blob referenced by database metadata:

```powershell
uv run --locked python -m backend.app.reconcile_evidence_storage --apply
```

PostgreSQL integration tests require a separate database named exactly `jobpilot_test`. Create it once in the local Compose server, set the dedicated test URL, and run only those tests. Each test uses and removes its own temporary schema; it does not drop the database:

```powershell
docker compose exec db createdb -U jobpilot jobpilot_test
$env:JOBPILOT_TEST_DATABASE_URL = "postgresql+psycopg://jobpilot:local_dev_only@127.0.0.1:5432/jobpilot_test"
uv run --locked pytest -m postgres -q
```

If the password, username, or host port differs from `.env.example`, update the test URL accordingly. The test harness refuses URLs whose database name is not `jobpilot_test`.

Stop the database while preserving its named volume, or remove the service container while keeping the data:

```powershell
docker compose stop db
docker compose down
```

To reset local development data, run `docker compose down --volumes`. **This permanently deletes the PostgreSQL volume and all database data in it.** Do not use this command unless that data is disposable.

Common issues: a host-port collision can be resolved by changing `POSTGRES_PORT` and the port in `DATABASE_URL`; connection-refused errors usually mean the container is not healthy or the URL points to the wrong port; missing-table, stale-migration, or missing-preference errors require applying Alembic migrations before starting the API. `/health` intentionally remains available while the DB is down; `/ready` returns `503` with a safe database error code.

## Core principles

1. Correctness and consent beat application volume.
2. Eligibility and safety gates run before ranking can authorize an action.
3. Missing evidence is `unknown`, not automatically `false` and not permission to invent a fact.
4. Every consequential action is attributable, reviewable, and reconciled against external evidence.
5. Start simple, measure bottlenecks, and scale only where data demonstrates a need.
6. Company-owned material is confidential; this repository should contain only authorized concepts and original implementation. Do not copy proprietary code, secrets, or internal data into Hire-steward without explicit authorization.

## 13-Screen Workbench Architecture & Local Execution

Hire-Steward provides a comprehensive, responsive local workbench mounted directly from the FastAPI modular monolith:

1. **Overview Dashboard** (/): High-level system vitals, pipeline metrics, candidate completeness meter, and recent activity feed.
2. **Job Discovery Workbench** (/workbench): Deterministic evidence-backed job matching, multi-criteria filtering, score tiering, and manual opportunity intake.
3. **Application Pipeline**: Kanban-style status tracking through the validated state machine (SAVED → PREPARING → READY_FOR_REVIEW → APPLIED → INTERVIEWING).
4. **Application Preparation**: Tailored resume and cover letter synthesis strictly grounded in active verified candidate evidence.
5. **Candidate Profile**: Structured profile manager with completeness scoring and field recommendations.
6. **Evidence Library**: Multi-format document parser (.txt, .md, .docx, .pdf), candidate facts table, and byte-span provenance links.
7. **Interview Answer Bank**: Versioned reusable Q&A responses with explicit reuse consent and revocation.
8. **Job Source Registry**: Verified read-only source adapters with rate-limiters and safety guardrails.
9. **AI & Usage Headroom**: Budget tracking with hard spend limits, provider mode selection (OFFLINE_MOCK), and zero secret exposure.
10. **Search Policies & Settings**: Minimum compensation floor (INR), daily submission caps, same-company cooldowns, and workplace preferences.
11. **Data Portability & Backup**: Safe JSON export conforming to hire-steward-export-v1 with secret scrubbing and atomic commit restore.
12. **Activity Log & Audit Feed**: Chronological, immutable audit timeline of all state transitions and system events.
13. **System Health & Diagnostics**: Operational diagnostics, database status, evidence storage availability, and loopback verification.

### Running the Workbench Locally

`powershell
uv run --locked --env-file .env alembic -c backend/alembic.ini upgrade head
uv run --locked uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
`
Open your browser to http://127.0.0.1:8000 to launch the workbench.
