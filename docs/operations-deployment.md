# JobPilot — Operations and Deployment Runbook

**Status:** Initial local-first operational baseline.

## 1. Deployment stages

### Local development

- Frontend dev server, FastAPI API, PostgreSQL and worker run through one documented development setup.
- Watch/reload features may be enabled only in development.
- Bind development services to localhost by default.

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

Initial suggested services:

- `frontend` — static assets or dev server depending on profile.
- `api` — FastAPI HTTP service.
- `worker` — scheduler and durable background work.
- `db` — PostgreSQL, with pgvector extension only if chosen and migrations include it.

Do not add Redis or a broker to the initial Compose file by default. If later required, introduce it in an ADR and update backup/recovery/monitoring procedures.

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

## 4. Startup and upgrade procedure

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

## 5. Backup and restore

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

## 6. Health and failure response

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

## 7. Versioning and rollback

Each build records application version, commit ID, dependency lock hash, schema migration version, prompt/scoring/policy versions. Keep previous known-good images/commits available for rollback. Rollback must account for irreversible database changes and existing `CONFIRMATION_UNKNOWN` attempts; never reset application history to hide an uncertain side effect.

## 8. Operational maintenance

- Review source terms/capabilities and provider privacy/quota metadata periodically and whenever errors indicate a change.
- Check backup recency and run restore drills.
- Review dependency and container image security advisories.
- Check stale checkpoints, worker queue/backlog, disk use, error rates and provider spend.
- Review manual corrections and evaluation regressions before changing model prompts/scoring.
- Update `memory.md` after a release, incident, source capability change, provider change, or architecture decision.

## 9. Developer diagnostics

Provide `doctor`/diagnostic output that reports safe actionable facts: Docker available, DB connectivity, migration status, storage writable, worker heartbeat, timezone, upcoming run, source permission state, provider configuration present (not values), quota/budget mode, backup age, and unresolved uncertain submissions. Redact environment variable values and credentials.
