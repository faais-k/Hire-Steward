# ADR-0010 — PostgreSQL Development and CI Baseline

- **Status:** Accepted for local development and CI configuration; runtime verification pending
- **Date:** 2026-10-28

## Context

Foundation 1's migrations and persistence tests ran against SQLite, while PostgreSQL is the selected system of record. Foundation 2 needs a repeatable local database, a safe test target, and automated verification without making the developer's normal database disposable.

## Decision

- Use the official `postgres:17.11-bookworm` image for local Compose and CI. This pins PostgreSQL major/minor and Debian base instead of following `latest`; update both environments together after review. The official image currently publishes this tag family. [Official PostgreSQL image tags](https://github.com/docker-library/docs/blob/master/postgres/README.md)
- Root `compose.yaml` starts only PostgreSQL. It reads database name, username, password, and host port from environment, persists data in a named volume, binds the host port to loopback, and checks readiness with `pg_isready`.
- Keep `DATABASE_URL` as the sole SQLAlchemy/Alembic URL, loaded from the runtime environment. `backend/alembic.ini` has no second connection URL. The ignored `.env` is for local development; `.env.example` contains placeholders.
- PostgreSQL tests require a separate database named exactly `jobpilot_test`. Each test creates a random schema, sets its connection `search_path` to that schema, applies migrations there, and removes only that schema afterward. The fixture does not drop or recreate the database.
- CI creates its own PostgreSQL service initialized as `jobpilot_test`, installs locked dependencies with Python 3.12 and uv 0.13.5, checks `uv.lock`, compiles the backend, and runs the complete pytest suite. No external provider credentials or job-site accounts are used.
- Pin `actions/checkout` to `3d3c42e5aac5ba805825da76410c181273ba90b1` (release `v7.0.1`). The official release page identifies the tag and commit, and `action.yml` at that exact commit declares `runs.using: node24`. [v7.0.1 release](https://github.com/actions/checkout/releases/tag/v7.0.1), [pinned action.yml](https://github.com/actions/checkout/blob/3d3c42e5aac5ba805825da76410c181273ba90b1/action.yml)
- Keep `astral-sh/setup-uv` pinned to `07a047e608db84b3d8c06cd9a7c7dcc9c355c18e` (v10.3.2); its `action.yml` at that commit also declares `runs.using: node24`. [pinned setup-uv action.yml](https://github.com/astral-sh/setup-uv/blob/07a047e608db84b3d8c06cd9a7c7dcc9c355c18e/action.yml)
- The earlier v4.4.0 checkout pin is superseded. Its action metadata declares Node 20, which GitHub removed from Actions runners on 2026-09-23. [v4.4.0 action.yml](https://github.com/actions/checkout/blob/v4.4.0/action.yml), [GitHub Node 20 removal notice](https://github.blog/changelog/2026-09-23-node-20-is-no-longer-available-in-github-actions/)
- `/ready` checks connectivity, the complete required table/column shape from current SQLAlchemy metadata plus `alembic_version`, the expected migration heads, and the singleton INR/year preference assumptions. It performs inspection only; migrations and schema repair remain operator actions.

## Rationale and trade-offs

Using one PostgreSQL service keeps the development stack small and matches the selected database. Loopback binding limits the development listener to the local machine. A persistent named volume preserves ordinary development state across container removal. Temporary test schemas isolate the suite from that state while avoiding destructive database-level cleanup.

Pinning the image, CI actions, and uv version improves reproducibility, but requires deliberate updates for security fixes and upstream lifecycle changes. The checkout action is pinned to a full commit SHA to avoid a mutable tag; its runtime metadata was inspected at that SHA. The setup-uv pin was checked the same way. Per-test schemas isolate application tables; the suite still connects to the explicitly configured test database, so the fixture checks its exact database name and must never be configured with a production URL. The selected uv 0.13.5 release was checked against the upstream release page on 2026-10-28. [uv releases](https://github.com/astral-sh/uv/releases)

The local PostgreSQL service, migrations, transaction behavior, constraints, decimal round-tripping, and concurrency tests have not been run in this workspace because Docker is unavailable and the installed local PostgreSQL service is stopped. The workflow has not run on GitHub. Configuration and test code are not evidence of PostgreSQL compatibility.

## Consequences

- Developers must create `jobpilot_test` once before running the PostgreSQL-marked tests locally.
- `/health` remains liveness-only. `/ready` checks database connectivity, required model tables and columns, `alembic_version`, current migration heads, and the valid singleton preference row; it returns a safe `503` if a check fails. It never mutates schema state.
- Deleting the Compose volume destroys local database state and must be explicitly treated as a destructive reset.
- No frontend, worker, Redis, external integration, production deployment, or submission behavior is introduced.

## Revisit when

Revisit the image pin at routine security/update review or when the supported PostgreSQL lifecycle changes. Revisit schema isolation if CI parallelization, database extensions, or cross-schema migration behavior creates a measured need. Do not move to a broker or additional database service without measured requirements and a separate decision.

## Verification history

- On 2026-10-28, the first Foundation 2 review found that the original `actions/checkout@v4.4.0` pin used retired Node 20 and that readiness could return success after a required table was dropped while the migration marker remained. This correction upgrades and SHA-pins checkout to v7.0.1 and adds non-mutating schema-shape and preference-state checks with regression tests.
- The PostgreSQL test module currently collects nine independent test functions (no parameterized PostgreSQL cases), including a readiness regression that drops a required table after migration. Local PostgreSQL and hosted GitHub Actions verification remain pending; configuration and SQLite tests do not establish those results.
