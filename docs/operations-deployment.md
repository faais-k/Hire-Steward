# Hire-steward — Operations and Deployment Runbook

**Status:** Foundation 2 defines a local PostgreSQL service, readiness behavior, test isolation, and CI. Hosted CI verified `f47b9d1` against its PostgreSQL service on 2026-10-28 (73 passed, 0 failed, one upstream warning). Local Compose startup and operational use remain unverified in this workspace.

## 1. Deployment stages

### Local development

- Foundation 2 Compose currently starts PostgreSQL only. Run the API from the locked local Python environment; no frontend or worker service exists yet.
- Watch/reload features may be enabled only in development.
- PostgreSQL's host port binds to loopback. Run the API on `127.0.0.1` during local development.

### Local daily-use profile

- Build frontend assets and serve through the intended local deployment path.
- Use persistent named volumes for PostgreSQL and evidence files.
- Run API/worker as non-root where practical.
- Configure restart policies, health checks and bounded resources.
- Do not mount editable source code in a production-like container unless development mode requires it.

### Remote/always-on host (future)

- Must use a separate production Compose overlay/config and threat-model review.
- Add authentication, TLS ingress, host firewall, encrypted backups, secret management, monitoring and restore rehearsal.
- Never expose PostgreSQL, browser debugging ports or internal worker ports to the public internet.

Docker's official Compose guidance recommends production-specific overrides such as removing source-code bind mounts, changing port exposure and adding restart policies as appropriate: https://docs.docker.com/compose/how-tos/production/.

## 2. Compose services

The current root `compose.yaml` defines one service, `db`, using the PostgreSQL `17.11-bookworm` image, an environment-configured database/user/password/host port, a named data volume, loopback-only host binding, and a `pg_isready` health check. Compose reads the ignored root `.env` file; `.env.example` contains development placeholders only. The image and isolation decision is recorded in ADR-0010.

No API, frontend, worker, Redis, or broker container exists. Add a service only when its implementation and operational need are approved. Do not add Redis or a broker by default.

## 3. Configuration

Use validated settings, grouped by concerns:

- Application environment/host/port/log level.
- Database URL, pool behavior and migration mode.
- Evidence storage path and maximum upload size.
- Timezone and schedule.
- Source enablement, access method and rate limits.
- Application/email daily caps and the versioned user-configurable minimum compensation preference (INR/year, default INR 100,000/year); do not expose unrelated sensitive values in diagnostics.
- AI providers, model routes, privacy rules, timeouts, retries and cost budget.
- Secret vault integration and OAuth callback config if relevant.
- Data retention, backups, export/import limits.

The committed `.env.example` must contain placeholders only. Start-up should fail with a clear safe message when critical configuration is missing. Do not print secret-bearing settings as part of diagnostic output.

`DATABASE_URL` is the single SQLAlchemy/Alembic URL. `backend/alembic.ini` does not contain a second fallback URL; Alembic receives the URL through the runtime environment. Keep the URL host port, database, username, and password aligned with the corresponding Compose `POSTGRES_*` values. Never commit `.env` or use its development password outside a local environment.

## 4. Local database and API commands

From the repository root in PowerShell:

```powershell
uv lock --check
uv sync --locked --python 3.12
Copy-Item .env.example .env
docker compose up -d db
docker compose ps
docker compose logs db
docker compose exec db pg_isready -U jobpilot -d jobpilot
uv run --locked --env-file .env alembic -c backend/alembic.ini upgrade head
uv run --locked --env-file .env alembic -c backend/alembic.ini current
uv run --locked --env-file .env uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

`GET /health` is process liveness and does not connect to PostgreSQL. `GET /ready` checks a database connection, all tables and columns required by the current model metadata plus `alembic_version`, applied Alembic heads, and the valid singleton INR/year preference row. It performs no schema repair or migration and returns a safe `503` code when any readiness condition fails. Stop the API with `Ctrl+C`.

Fast local tests use SQLite:

```powershell
uv run --locked pytest -m "not postgres" -q
```

For PostgreSQL integration tests, create the dedicated database once and set its URL only in the test process:

```powershell
docker compose exec db createdb -U jobpilot jobpilot_test
$env:JOBPILOT_TEST_DATABASE_URL = "postgresql+psycopg://jobpilot:local_dev_only@127.0.0.1:5432/jobpilot_test"
uv run --locked pytest -m postgres -q
```

The fixture requires the exact `jobpilot_test` database name and creates a unique temporary schema per test. It removes that schema on teardown and never drops the database. Do not set `JOBPILOT_TEST_DATABASE_URL` to a normal development or user database. CI uses the same PostgreSQL image and creates its own disposable service database.

Common connection errors: if the port is occupied, choose another `POSTGRES_PORT` and change the `DATABASE_URL` port; if credentials or database names change after a data volume was initialized, update both Compose settings and the URL to match the existing database; if tables are missing, apply Alembic migrations before starting the API. Do not delete a data volume to resolve a connection problem unless its data is disposable.

To stop the local DB while preserving data, use `docker compose stop db`; `docker compose down` removes the container and network but keeps the named volume. `docker compose down --volumes` **permanently deletes the development database volume and its data**.

## 5. Startup and upgrade procedure

1. Confirm Docker/Compose versions and free disk space.
2. Back up database and evidence store before schema upgrades.
3. Pull/build the reviewed image/commit and verify the image/version.
4. Run migration in a controlled step; do not allow multiple services to race migrations.
5. Start database and wait for readiness.
6. Start API and worker.
7. Check `/health`, `/ready`, worker heartbeat, migration version and source status.
8. Run a safe no-side-effect diagnostic and source dry-run.
9. Keep external submission disabled during upgrade verification.
10. Re-enable only after checking pending `SUBMITTING`/`CONFIRMATION_UNKNOWN` records and source configuration.

Never auto-retry a pending submission after an upgrade merely because the worker restarted.

## 6. Backup and restore

Back up:

- PostgreSQL data including policy/audit/application state.
- Evidence file store and its hashes/manifests.
- Relevant non-secret configuration and model/prompt/policy versions.

Do not put raw provider secrets or browser sessions in ordinary backups. If secrets require backup, use a separate encrypted process and do not store the recovery key beside the backup.

Suggested backup workflow:

1. Pause new external side effects.
2. Record a consistent database backup and evidence-store snapshot or manifest.
3. Encrypt backups if they contain personal data.
4. Store checksum and creation/schema version.
5. Resume the application after the snapshot completes.
6. Verify the backup's existence and metadata.

Restore rehearsal:

1. Restore into an isolated clean environment.
2. Verify schema migration version, record counts, file hashes and key foreign-key relationships.
3. Validate that an exported submission/attempt is not retried automatically.
4. Start API in safe mode with external side effects disabled.
5. Reconcile any historical uncertain attempts manually before enabling submission.

## 7. Health and failure response

### Source failures

Disable or pause the affected source after access-policy warnings, repeated authorization errors, CAPTCHA/anti-bot barriers, unrecognized schema changes or repeated throttling. Preserve last successful checkpoint; retry within documented limits. Other sources continue.

### Provider quota/outage

Use an approved fallback only if privacy, budget and task quality policies permit it. Otherwise defer the task and notify. Never rotate accounts/keys to evade quotas. Keep matching/preparation incomplete rather than generating fabricated content.

### Database unavailable

Do not execute external side effects without durable state and attempt logging. Stop submission worker, preserve local logs safely, recover database, then reconcile attempts.

### Disk full

Pause document ingestion and submissions; preserve database integrity and audit. Alert the user, identify the largest safe cleanup candidates, and never delete the only source artifact or confirmation evidence automatically.

### Browser/ATS drift

Disable the adapter's submission capability immediately. Discovery may continue only if safe and separately permitted. Provide manual handoff. Re-enable only after contract/browser tests pass.

## 8. Versioning and rollback

Each build records application version, commit ID, dependency lock hash, schema migration version, prompt/scoring/policy versions. Keep previous known-good images/commits available for rollback. Rollback must account for irreversible database changes and existing `CONFIRMATION_UNKNOWN` attempts; never reset application history to hide an uncertain side effect.

## 9. Operational maintenance

- Review source terms/capabilities and provider privacy/quota metadata periodically and whenever errors indicate a change.
- Check backup recency and run restore drills.
- Review dependency and container image security advisories.
- Check stale checkpoints, worker queue/backlog, disk use, error rates and provider spend.
- Review manual corrections and evaluation regressions before changing model prompts/scoring.
- Update `memory.md` after a release, incident, source capability change, provider change, or architecture decision.

## 10. Developer diagnostics

Provide `doctor`/diagnostic output that reports safe actionable facts: Docker available, DB connectivity, migration status, storage writable, worker heartbeat, timezone, upcoming run, source permission state, provider configuration present (not values), quota/budget mode, backup age, and unresolved uncertain submissions. Redact environment variable values and credentials.
