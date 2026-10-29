# Hire-steward — Product and Engineering Documentation

**Status:** Foundations 1, 2, and 3 implemented and hosted-CI verified on feature branch `foundation-3-candidate-evidence`; product remains incomplete.
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

The documents are the product requirements and architecture baseline. The backend implements the compensation-preference/assessment slice and a narrow candidate-evidence metadata slice. The frontend, source integrations and application submission are not implemented. No third-party endpoint is approved by this implementation. The source capability registry must be verified before use. Do not treat similarity scores, generated text, a stored document, or a successful browser click as proof of eligibility or successful submission.

## Current implementation status and limitations

Foundation 1 implements the configurable compensation preference and deterministic assessment backend. The default minimum is INR 100,000 per year, and the preference can be changed, including to zero. Foundation 2 adds a local PostgreSQL Compose service, an explicit PostgreSQL integration-test suite, a CI workflow, and database readiness reporting.

Foundation 3 adds local-only candidate-document metadata, immutable UTF-8 `text/plain` versions, closed-shape unreviewed facts, and byte-span provenance. Uploads use a configured external storage root, 10 MiB per-version cap, 100 MiB service-managed reservation budget, server-computed hashes, and operator-only stale-reservation reconciliation. Stored documents and provenance links are not fact verification; no parser, OCR, model, extraction worker, or user-verification workflow exists.

- Compensation evidence supplied through the public API remains unverified. Public assessments return `REVIEW_REQUIRED` and cannot authorize submission. There is no trusted compensation evidence verifier or ingestion path yet.
- There is no frontend, job-source integration, AI provider integration, or application-submission workflow. Live applications remain disabled.
- Candidate-evidence PostgreSQL migration/concurrency tests passed in hosted CI (commit `fe0baf0`) but remain unverified locally because the dedicated `JOBPILOT_TEST_DATABASE_URL` and Docker engine are unavailable. The single-process reservation limit is not an operating-system disk quota or a multi-process storage protocol.
- The Compose service and CI workflow are development infrastructure, not a production-ready setup. Authentication, production secret management, backup/restore, monitoring, and remote deployment hardening remain out of scope.
- The routine local suite uses SQLite. Hosted GitHub Actions verified commit `fe0baf0` (`foundation-3-candidate-evidence`) on 2026-10-28: its PostgreSQL service became healthy and `uv run --locked pytest -q` reported **95 passed, 0 failed**, with one upstream Starlette/AnyIO deprecation warning (workflow run: https://github.com/faais-k/Hire-Steward/actions/runs/40664831364). All 13 PostgreSQL integration tests passed. Foundation 3 remains on its feature branch and has not yet been merged into `main`. This does not verify local Docker Compose startup, backups, recovery, or production operation.

`GET/PATCH /api/v1/settings/policies` reads and updates the persisted preference. `POST /api/v1/compensation/assessments` records a deterministic assessment using the saved server value; the API rejects client-supplied thresholds and AI decision fields. Assessment records retain their threshold snapshot. This evaluator is not wired into job matching, scheduling, the dashboard, application preparation, or a submission gate; no submission route exists.

The API binds to loopback when run with the commands below. `/health` reports process liveness; `/ready` checks database connectivity, the complete required table and column shape, current Alembic migration heads, and a valid migrated compensation-preference row. The local same-origin write check is not authentication and does not make remote exposure safe.

## Local development setup

The following PowerShell commands are the intended setup. They have not been run end to end in this workspace because Docker Desktop's engine is unavailable; Compose syntax and non-PostgreSQL tests are verified separately in `docs/memory.md`.

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
