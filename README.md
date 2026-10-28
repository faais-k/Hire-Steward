# JobPilot — Product and Engineering Documentation

**Status:** Foundation 1 includes a locally tested backend compensation-preference slice; the product remains incomplete.  
**Documentation baseline date:** 2026-10-27  
**Initial deployment target:** Local-first Docker Compose  
**Primary objective:** A reliable, explainable, privacy-conscious job discovery and application preparation system with carefully gated submission automation.

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

The documents are the product requirements and architecture baseline. Only the backend compensation-preference API, deterministic evaluator, migration, audit and assessment snapshot slice is currently implemented and locally tested. The frontend, other product features, source integrations and application submission are not implemented. No third-party endpoint is approved by this implementation. The source capability registry must be verified before use. Do not treat similarity scores, generated text, or a successful browser click as proof of eligibility or successful submission.

## Current implementation status and limitations

Foundation 1 implements the compensation preference and compensation-assessment backend only. The default minimum is INR 100,000 per year, and the preference is configurable, including zero.

- Compensation evidence supplied through the public API is treated as unverified. Public assessments currently return `REVIEW_REQUIRED` and cannot authorize application submission. There is no trusted compensation evidence-ingestion or verification service yet.
- There is no frontend, job-source integration, or application-submission workflow. Live applications remain disabled.
- The local API and migration instructions below are development guidance, not a production-ready setup. No Docker Compose database service, CI pipeline, or production hardening is implemented.
- Automated tests currently use SQLite. PostgreSQL-specific migration, locking, and concurrency behavior have not been verified because the Docker engine is unavailable.

`GET/PATCH /api/v1/settings/policies` reads and updates the persisted preference. `POST /api/v1/compensation/assessments` records a deterministic compensation-only assessment using the saved server value; the API rejects client-supplied thresholds and AI decision fields. Assessment records retain the threshold version and conversion basis when one is established. This evaluator is not wired into job matching, scheduling, the dashboard, application preparation, or a submission gate; no submission route exists.

The application is loopback-only by default and state-changing requests require matching local `Host` and `Origin` headers. This is not authentication and does not make remote exposure safe. The server needs a PostgreSQL database and an applied Alembic migration; no Compose database service has been added yet.

```powershell
uv sync --python 3.12
$env:DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE"
uv run --locked alembic -c backend/alembic.ini upgrade head
uv run --locked uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Run local unit and SQLite migration/API integration tests with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Core principles

1. Correctness and consent beat application volume.
2. Eligibility and safety gates run before ranking can authorize an action.
3. Missing evidence is `unknown`, not automatically `false` and not permission to invent a fact.
4. Every consequential action is attributable, reviewable, and reconciled against external evidence.
5. Start simple, measure bottlenecks, and scale only where data demonstrates a need.
6. Company-owned material is confidential; this repository should contain only authorized concepts and original implementation. Do not copy proprietary code, secrets, or internal data into JobPilot without explicit authorization.
