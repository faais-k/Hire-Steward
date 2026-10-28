# Hire-steward — Project Memory and Current Status

**Last updated:** 2026-10-28  
**Purpose:** Single concise, reliable source of truth for what is decided, evidenced as complete, currently in progress, blocked, and next. Update this file after meaningful implementation or decision changes.

## 1. Current state

**Overall:** Stage A planning/audit documents remain the product requirements baseline. Foundation 1 implements a narrow compensation-preference backend slice plus a fail-closed public compensation evidence trust boundary. Foundation 2 adds local PostgreSQL Compose configuration, API readiness, isolated PostgreSQL test code, CI configuration and setup documentation. No trusted evidence verifier, job-source integration, AI provider, frontend, scheduling, application preparation, or live submission is implemented.

**Current work item:** Foundation 2 plus the Hire-steward rebrand correction are in progress from committed baseline `d7bfa7f` on `main`. The Foundation 2 worktree was clean when it began; its infrastructure and documentation changes, and the later rebrand/correction changes, remain uncommitted and unstaged. Git author and committer identities are configured locally. No commit or push has occurred, and the existing remote has not changed.

**Current phase:** Stage B `IN_PROGRESS` by direct owner authorization for Foundation 2. Phase 0 remains `IN_PROGRESS`; source/provider/storage and wider security feasibility are unresolved. The local write-route guard and root Python lock choice are documented in ADR-0008; this does not authorize external integrations.

**Verified workspace state:** Baseline is Git commit `d7bfa7f` on `main`; the worktree was clean at the start of this task. Git author and committer identities are configured locally. No commit or push has occurred during this task. `.gitignore` excludes `reference-repos/`, `Chatgpt-chat/`, `docs (2).zip`, secrets, environments, build outputs and local databases; `.env` is ignored and no `.env` file existed at inspection. Root `pyproject.toml`/`uv.lock`, backend code, migrations `0001`/`0002`, and tests exist. Foundation 2 adds `compose.yaml`, `.github/workflows/ci.yml`, and a PostgreSQL-marked suite. `frontend/` remains empty. Docker CLI 28.4.0 and Compose v2.39.4 are installed, but the Docker Desktop engine is unavailable. PostgreSQL 18 tools/service are installed; the service is stopped and `127.0.0.1:5432` does not respond. All eight reference repositories remain excluded and unchanged.

## 2. Decisions agreed in planning

- Product name: **Hire-steward**. The machine-safe distribution slug is `hire-steward`. Existing database names, table names, migration identifiers, module imports, and `JOBPILOT_*` test prefix remain technical identifiers for compatibility; the GitHub remote also remains `https://github.com/faais-k/Hire-Steward.git`.
- First deployment: local-first Docker Compose; Foundation 2 currently runs only the PostgreSQL service. Remote/always-on hosting is a later option.
- Targeting profile is configurable in the UI, not hard-coded for one role.
- Editable profile defaults may be prefilled from the user's current preferences, but settings remain changeable.
- Initial job search: postings from the previous 14 days.
- Default scheduled runs: 10:00, 17:00 and 22:00 in `Asia/Kolkata`.
- Future runs resume/backfill using each source's last successful checkpoint where supported. Failed sources must not advance checkpoints.
- Source permissions and capabilities are tracked per source; no universal coverage is promised.
- CAPTCHA/human-only steps pause the affected application; other jobs continue. No bypassing controls or evading rate limits.
- At most one active external application submission initially; discovery and preparation may run in parallel within bounds.
- Default daily application cap: 5; recruiter application-email cap: 5/day. Both are configurable.
- Exact known duplicate applications are blocked. Same-company/similar-role cooldown is 30 days, with a verified new requisition treated separately.
- Every mandatory qualification mismatch/unresolved requirement needs review; no auto-submit while unresolved.
- Relevant skills and work evidence matter; missing some listed skills or an experience gap by itself is not automatic rejection.
- Unknown sponsorship/compensation requires investigation/review rather than invented assumptions.
- Never apply to unpaid work, regardless of the compensation setting. The user-configurable minimum defaults to INR 100,000/year; a known annualized amount below the persisted preference fails the compensation gate.
- Compensation reported status and evidence verification are distinct. Public caller/model reports and their references remain unverified and review-required; only a future controlled source verifier can create trusted evidence. A trusted unpaid result remains blocked at any threshold.
- High score cannot override low confidence or hard gates.
- Resume changes should be minimal and fact-supported. Reusable answers require explicit consent; one-time answers are not reusable by default.
- Explicit application email address can be used for sending only when it is clearly the designated application channel and all gates pass; ambiguous/general contacts get drafts only.
- Pause on bonds, repayment obligations, restrictive covenants, material commitments or ambiguous high-stakes declarations.
- Secrets are excluded from exports by default; sensitive personal data requires explicit opt-in.
- Paid AI fallback is disabled until a user-defined budget is explicitly authorized.
- Current owner decision (2026-10-28): minimum compensation is configurable in settings, default INR 100,000/year; finite non-negative INR values including zero are allowed. Unpaid roles remain independently ineligible. Unknown, unsupported conversions and threshold-straddling ranges require review. ADR-0006 is historical and superseded by ADR-0007.
- Foundation 2 decision (2026-10-28): use official `postgres:17.11-bookworm` for Compose and CI; test PostgreSQL only through explicit `JOBPILOT_TEST_DATABASE_URL` to a dedicated `jobpilot_test` database with a random schema per test. See ADR-0010. This records configuration choices, not runtime verification.
- The uploaded company-owned AI search architecture is confidential. Only authorized general concepts may inform design; do not copy company-owned implementation/code without explicit authorization. Do not mention its company project name in Hire-steward docs or user-facing artifacts.

## 3. Proposed but unvalidated defaults

- Initial matching weights: role alignment 25; required technical skills 20; verified project/work evidence 15; experience fit 15; seniority 10; location/work arrangement 10; compensation/contract preferences 5.
- Proposed score bands: `>=85` potential eligible-for-automation only if every hard gate and confidence requirement passes; `75–84` review; `<75` skip/review according to user configuration. These bands are not calibrated and must not be treated as proven.
- Initial stack: Python, FastAPI, Pydantic, SQLAlchemy, Alembic, PostgreSQL, optional pgvector/FTS, React + TypeScript + Vite, Playwright only where permitted, Docker Compose, pytest.
- RRF is a candidate rank-fusion technique; `k=60` is a starting proposal, not a measured optimum.
- One modular monolith plus separate worker process. No Redis, Celery, Kafka, Kubernetes or second vector database by default.
- Initial UI palette and typography are proposed tokens; contrast must be tested.

## 4. Work evidenced as complete

- [x] Core requirements and guardrails consolidated from planning discussions.
- [x] Initial product scope, system boundaries, source capability model, state machine and safety expectations documented.
- [x] Proposed documentation set drafted.
- [x] Read all current Hire-steward Markdown specifications, existing ADRs, README, root instruction file and project memory.
- [x] At the start of this work, verified the root had no product source, manifests, migrations, CI, Compose setup or tests; this is the historical baseline, not the current state.
- [x] Audited all eight local reference checkouts read-only; recorded origins, SHAs, license obligations, implementation paths, test/CI evidence and risks in `docs/reference-repo-audit.md`. No tests or setup scripts were run and no code was copied.
- [x] Rechecked official Greenhouse, Lever and Ashby API docs, plus Gemini pricing/data-use and Groq rate-limit docs, on 2026-10-28. This verifies documentation facts only; no blanket source permission, provider quota, legal conclusion or cost estimate was established.
- [x] Added the initial source capability matrix in `docs/job-discovery-sources.md`; Greenhouse, Lever and Ashby all remain `NEEDS_REVIEW`, with no source enabled or selected as permitted.
- [x] Created `docs/requirements-traceability.md`, `docs/architecture-review.md`, `docs/risk-register.md` and `docs/implementation-plan.md`.
- [x] Recorded the earlier fixed INR 100,000 floor decision in ADR-0006; it is now marked superseded by ADR-0007.
- [x] Updated policy documentation, acceptance criteria, traceability, risk and memory for the configurable INR/year preference. The current duplicate archive `docs (2).zip` is excluded and is not treated as source of truth.
- [x] Searched project-owned Markdown/config/script files for the former spaced project path; no matching references were found, so no path edits were needed. External reference repositories and the historical conversation export were excluded.
- [x] Initialized the root Git repository on `main`, configured the requested `origin`, and added ignore rules for reference clones, conversation export, secrets, local environments, generated output and local databases. At that historical point no commit or push had been made; the reviewed initial snapshot was later committed as `d7bfa7f` before Foundation 2.
- [x] Added the focused backend preference API, exact `Decimal` policy evaluator, Alembic migration, transactional audit, and assessment snapshots. Files are listed in the Foundation 1 change record below and in the staged review.
- [x] Historical Foundation 1 run before the trust-boundary correction: 36 tests passed with one upstream AnyIO deprecation warning. This is not the current full-suite result.
- [x] Corrected the public compensation trust boundary: strict requests cannot claim verification or decision authority; the service sets public observations to `UNVERIFIED`; the evaluator returns `REVIEW_REQUIRED`/`EVIDENCE_UNVERIFIED`; responses identify values/references as reported and set `eligible_to_submit=false`.
- [x] Added migration `0002_compensation_evidence_trust_state`; legacy rows receive the `UNVERIFIED` default without rewriting stored facts, threshold snapshots, or original outcomes. The effective API view returns review-required and does not expose a legacy stored outcome as authoritative.
- [x] Added adversarial API, domain, and migration upgrade/downgrade coverage. Latest freshly rerun full suite on 2026-10-28: 53 passed, one upstream Starlette/AnyIO deprecation warning. Tests use in-memory SQLite; PostgreSQL migration, locking and concurrency behavior remain unverified because the Docker engine is unavailable.

### Foundation 1 files changed

- Repository/tooling: `.gitignore`, `.env.example`, `pyproject.toml`, `uv.lock`, `README.md`.
- Backend: `backend/__init__.py`; `backend/app/__init__.py`; `backend/app/api/__init__.py`; `backend/app/api/dependencies.py`; `backend/app/api/routes/__init__.py`; `backend/app/api/routes/compensation.py`; `backend/app/api/routes/health.py`; `backend/app/api/schemas.py`; `backend/app/db/__init__.py`; `backend/app/db/base.py`; `backend/app/db/models.py`; `backend/app/db/session.py`; `backend/app/domain/__init__.py`; `backend/app/domain/compensation.py`; `backend/app/main.py`; `backend/app/services/__init__.py`; `backend/app/services/assessments.py`; `backend/app/services/preferences.py`; `backend/alembic.ini`; `backend/migrations/env.py`; `backend/migrations/script.py.mako`; `backend/migrations/versions/0001_compensation_preference.py`; `backend/tests/integration/test_compensation_api.py`; `backend/tests/unit/test_compensation_policy.py`.
- Documentation: `docs/api-spec.md`; `docs/architecture-review.md`; `docs/architecture.md`; `docs/data-model.md`; `docs/decisions/ADR-0008-compensation-preference-storage.md`; `docs/implementation-plan.md`; `docs/memory.md`; `docs/phases.md`; `docs/reference-repo-audit.md`; `docs/requirements-traceability.md`; `docs/risk-register.md`; `docs/security-privacy.md`; `docs/testing-evaluation.md`.

### Foundation 1 trust-boundary correction

- Backend: `backend/app/api/schemas.py`; `backend/app/api/routes/compensation.py`; `backend/app/db/models.py`; `backend/app/domain/compensation.py`; `backend/app/main.py`; `backend/app/services/assessments.py`; `backend/migrations/versions/0002_compensation_evidence_trust_state.py`; `backend/tests/unit/test_compensation_policy.py`; `backend/tests/integration/test_compensation_api.py`.
- Documentation: `docs/ai-spec.md`; `docs/api-spec.md`; `docs/application-safety-policy.md`; `docs/data-model.md`; `docs/decisions/ADR-0007-configurable-compensation-preference.md`; `docs/decisions/ADR-0008-compensation-preference-storage.md`; `docs/decisions/ADR-0009-compensation-evidence-trust-boundary.md`; `docs/implementation-plan.md`; `docs/memory.md`; `docs/phases.md`; `docs/requirements-traceability.md`; `docs/risk-register.md`; `docs/security-privacy.md`; `docs/testing-evaluation.md`.

- [x] The reviewed initial snapshot, including the trust-boundary correction, was committed as `d7bfa7f` before Foundation 2 began. The commit is the preserved baseline; current Foundation 2 changes are not committed.
- [x] Baseline full suite before Foundation 2 changes: 53 passed with one upstream Starlette/AnyIO deprecation warning on 2026-10-28. This is historical and not the latest full-suite result after Foundation 2.

### Foundation 2 — PostgreSQL, Docker Compose, and CI

**Status:** Implemented in the working tree on 2026-10-28; PostgreSQL runtime behavior and hosted CI remain unverified. No commit or push was made.

- Root Compose runs only PostgreSQL `17.11-bookworm`, with a named volume, env-configured DB/user/password/port, loopback-only host binding, and `pg_isready` health check. `.env.example` holds local placeholders; `.env` is ignored. `DATABASE_URL` is the one SQLAlchemy/Alembic URL; `backend/alembic.ini` no longer holds a competing URL.
- Alembic now requires `DATABASE_URL` when run without an injected connection. `/health` stays process liveness; `/ready` checks database connectivity, all required model tables and columns plus `alembic_version`, applied migration heads, and the valid singleton INR/year preference row. It never creates, repairs, or migrates schema, and returns safe `503` codes when unavailable, stale, incomplete, or invalid.
- Nine PostgreSQL-marked integration tests use only `JOBPILOT_TEST_DATABASE_URL` for a database named exactly `jobpilot_test`. Each test applies migrations in a generated schema and removes only that schema. Coverage includes fresh schema/model constraints, readiness after a required table is removed while the migration marker remains, default and precision, 0001-to-0002 historical evidence, assessment API fail-closed behavior, audited decimal update, rollback after failed audit insert, concurrent settings updates, and primary/singleton constraints. `pytest --collect-only -m postgres` confirmed nine independent functions and no parameterized PostgreSQL cases.
- `.github/workflows/ci.yml` sets up Python 3.12, uv 0.13.5, locked dependencies, PostgreSQL 17.11 with a health check, lock validation, compilation, and the full pytest suite. It pins `actions/checkout` v7.0.1 at `3d3c42e5aac5ba805825da76410c181273ba90b1`; upstream `action.yml` declares Node 24. The existing pinned `setup-uv` action also declares Node 24. The workflow uses no external source/provider credentials and has not run on GitHub.
- Files changed: `.env.example`, `AGENTS.md`, `README.md`, `compose.yaml`, `.github/workflows/ci.yml`, `pyproject.toml`, `backend/alembic.ini`, `backend/app/api/routes/health.py`, `backend/migrations/env.py`, `backend/tests/integration/test_compensation_api.py`, `backend/tests/integration/test_postgres_integration.py`, `docs/api-spec.md`, `docs/architecture-review.md`, `docs/architecture.md`, `docs/decisions/ADR-0010-postgresql-development-and-ci.md`, `docs/implementation-plan.md`, `docs/memory.md`, `docs/operations-deployment.md`, `docs/phases.md`, `docs/requirements-traceability.md`, `docs/risk-register.md`, `docs/security-privacy.md`, `docs/testing-evaluation.md`.
- Latest full local suite on 2026-10-28: **63 passed, 9 skipped**, one upstream Starlette/AnyIO deprecation warning. All nine skips are PostgreSQL tests because `JOBPILOT_TEST_DATABASE_URL` was not configured. The earlier 58-pass/8-skip Foundation 2 result is historical.
- `docker compose --env-file .env.example config --quiet`, `uv lock --check --offline --cache-dir .venv\uv-cache`, uv environment-file loading, and Python compilation passed. The default user uv cache path was denied by the restricted workspace; a project `.venv` cache succeeded. The Docker engine is unavailable and installed PostgreSQL 18 is stopped, so no real PostgreSQL migration/locking/concurrency test or end-to-end Compose startup was run. No GitHub workflow run exists.
- No YAML parser or `actionlint` is installed in this workspace. The workflow was manually inspected and its two JavaScript action metadata files were verified from their pinned upstream commits; this is not a hosted workflow result.
- No dependency was added. `uv.lock` was regenerated with installed uv solely to change the root distribution from `jobpilot` to `hire-steward`; resolved dependency versions remain unchanged. `reference-repos/` remains excluded and untouched. The existing origin was not changed. Live applications remain disabled.

## 5. Remaining product gaps

- [ ] Run PostgreSQL migration, NUMERIC precision, transaction, constraint, trust-boundary, and concurrent-update tests against an actual dedicated PostgreSQL 17.11 service. The tests exist but are not verified; Docker is unavailable and the installed PostgreSQL 18 service is stopped.
- [ ] Obtain the first successful GitHub Actions run. Workflow configuration exists but has not run on GitHub.
- [ ] Complete Phase 0 owner review. The current compensation API has a loopback same-origin write guard, but broader local auth/CSRF/remote policy remains open.
- [ ] Implement and review a permitted compensation evidence-ingestion/verifier with retrieved source/version provenance and supporting text spans. Until then, all public compensation assessments remain review-required and no public assessment can pass the compensation gate.
- [ ] Complete the remaining general foundation: structured redacted logging, broader error/correlation handling, and a clean end-to-end local startup/upgrade check on a Docker-capable host.
- [ ] Select frontend lock/runtime and container versions when those components are started.
- [ ] Verify current source terms and choose a concrete first source/operation. No source is currently permitted/activated for Hire-steward.
- [ ] Select and evaluate document extraction and OCR paths with synthetic fixtures; no prototype has been run.
- [ ] Select a provider/model and data-sharing mode only after current terms, quota, structured output and budget behavior are reviewed; no provider account or limit was inspected.
- [ ] Specify and prototype consistent DB/filesystem backup/restore and recovery; no restore was run.
- [ ] Wire the deterministic compensation evaluator into future job assessments, matching, dashboard explanations, scheduling, application preparation and final submission only after those systems and their safety tests exist. Preserve submitted application history; no application model or submission path exists today.
- [ ] Add unit, integration, contract, security, migration-upgrade and browser tests for the remaining product phases. Current implementation/test counts are recorded in this file's latest Foundation 2 entry; the rest of the product is not implemented.
- [ ] Verify first source access permission and permitted method, including application submission capability.
- [ ] Select and test current document extractors and OCR path.
- [ ] Select embedding model, dimensions and data-sharing policy.
- [ ] Build labeled job/candidate evidence evaluation set and benchmark matching.
- [ ] Implement candidate evidence ingestion/provenance.
- [ ] Implement job-source registry, checkpointing and dedupe.
- [ ] Implement policy engine and versioned scoring.
- [ ] Implement review UI and grounded application package preparation.
- [ ] Implement dry-run submission executor and reconciliation.
- [ ] Test secure secret storage, redaction, backup/restore and export/import.
- [ ] Enable any live submission; none is authorized by this document alone.

## 6. Blockers / risks

- The initial commit `d7bfa7f` is the preserved baseline. Author and committer identities are configured locally. Foundation 2 changes remain uncommitted; do not commit or push without owner review.
- Docker CLI exists but the Docker Desktop engine is unavailable, and the local PostgreSQL service is stopped; PostgreSQL migration/locking behavior and GitHub CI are unverified.
- No production trusted compensation evidence path exists. Public compensation reports cannot become verified or pass the assessment endpoint; this is a deliberate fail-closed limitation, not a completed verifier.
- Third-party source terms and endpoints may not permit the intended automation. A public listing endpoint does not mean the application endpoint is publicly authorized.
- Provider quotas, model availability, pricing and data terms can change; current limits are not committed in code yet.
- ADR-0006 reflects an earlier owner decision that made INR 100,000/year non-overridable. The current owner instruction supersedes it: INR 100,000/year is the configurable default and unpaid roles remain independently prohibited. Follow ADR-0007.
- The current Host/Origin guard is limited to the compensation routes and is not authentication or a remote security boundary.
- Matching thresholds remain uncalibrated.
- Document extraction/OCR quality for varied formats and languages is not verified.
- Browser automation can drift when sites change; every live source needs a disable switch and manual handoff.

## 7. Current next actions, in order

1. Run the nine PostgreSQL-marked tests against the dedicated `jobpilot_test` database using Docker or another approved PostgreSQL 17.11 server; never point the test URL at the normal development database.
2. Review and run the GitHub Actions workflow on the repository when a CI run is available; record actual results separately, including checkout v7.0.1 execution on a hosted runner.
3. Complete Stage B with structured redacted logging, broader error/correlation handling, and a documented end-to-end Compose/API startup check on a Docker-capable host.
4. Complete Stage A owner review and per-source permission review before adding any source adapter; choose AI data-sharing and budget policy before any provider integration.
5. Design and test trusted compensation evidence ingestion, then wire the deterministic evaluator into broader product workflows. Keep live submissions disabled until every release gate passes and the user separately authorizes them.

## 8. Change log

| Date | Change | Evidence/status |
|---|---|---|
| 2026-10-27 | Created documentation planning baseline | Files created; implementation not audited |
| 2026-10-28 | Completed read-only Stage A workspace and eight-reference audit; recorded root Git/code/config gaps and environment versions | Audit artifacts in `docs/reference-repo-audit.md`, `docs/requirements-traceability.md`, `docs/architecture-review.md`, `docs/risk-register.md`, and `docs/implementation-plan.md`; no tests/setup/live integrations run |
| 2026-10-28 | Earlier compensation decision set a non-overridable INR 100,000/year minimum | Historical decision retained in ADR-0006; superseded by ADR-0007 below |
| 2026-10-28 | Owner made INR 100,000/year the default configurable minimum; zero and any finite non-negative INR amount are allowed, while unpaid roles remain independently ineligible | ADR-0007 and updated policy specifications; documentation only, implementation/tests pending |
| 2026-10-28 | Owner authorized Foundation 1. Initialized root Git on `main`, configured `origin`, and added ignore rules; wrote first backend setting/evaluator/migration/audit/assessment slice and updated related docs | Files: `.gitignore`, `.env.example`, `pyproject.toml`, `uv.lock`, `backend/app/**`, `backend/migrations/**`, `backend/tests/**`, `README.md`, `docs/decisions/ADR-0008-compensation-preference-storage.md`, `docs/{architecture,architecture-review,api-spec,data-model,implementation-plan,memory,phases,requirements-traceability,security-privacy,testing-evaluation}.md`; no commit/push; user review of staged baseline remains pending |
| 2026-10-28 | Ran Foundation 1 unit and SQLite migration/API integration suite | `.venv\Scripts\python.exe -m pytest -q`: 35 passed with one upstream AnyIO deprecation warning. PostgreSQL not run because Docker engine/database was unavailable. |

| 2026-10-28 | Re-ran Foundation 1 verification after the final regression case; updated status notes and confirmed remote branch state | `.venv\Scripts\python.exe -m pytest -q`: 36 passed, one upstream AnyIO deprecation warning. `.venv\Scripts\python.exe -m compileall -q backend/app backend/migrations`: passed. `uv lock --check --offline --cache-dir (Join-Path $env:TEMP 'jobpilot-uv-cache')`: passed. `git ls-remote --heads origin`: exit 0, no branch heads. PostgreSQL remains untested. |

| 2026-10-28 | Fixed Foundation 1 compensation evidence trust boundary after staged snapshot review: public values are reported/unverified, trust and AI decision claims are rejected, legacy records default to unverified, and effective API results fail closed. Added ADR-0009 and updated specifications/traceability/risk. | Full suite command `$env:PYTHONDONTWRITEBYTECODE='1'; .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q`: 53 passed, one upstream Starlette/AnyIO deprecation warning. Migration test covers 0001→0002, API review state, and downgrade. PostgreSQL unavailable; no commit/push/staging operation; staged 59-file initial snapshot remains intact. |

| 2026-10-28 | Staged the initial repository baseline for owner review | At that review stage, `git diff --cached --stat` showed 59 files and `git diff --cached --check` flagged intentional Markdown two-space hard-breaks; no source whitespace errors were reported. The reviewed snapshot was later committed as `d7bfa7f`. |

| 2026-10-28 | Corrected stale pre-commit status, clarified README implementation limits, and staged the complete corrected initial snapshot | At that point, `git add -A` staged 61 paths, including migration `0002` and ADR-0009. The snapshot was later committed as `d7bfa7f`; this row records the earlier pre-commit state. |
| 2026-10-28 | Implemented Foundation 2 PostgreSQL/Compose/CI configuration, API readiness, isolated PostgreSQL tests, and operator documentation | Final full suite: 58 passed, 8 PostgreSQL tests skipped, one upstream Starlette/AnyIO deprecation warning. Compose config, uv lock/env-file checks, locked sync, and compile passed. No PostgreSQL server or hosted CI run; Docker engine unavailable and local PostgreSQL service stopped. Current changes remain uncommitted; no push. See the Foundation 2 section above. |
| 2026-10-28 | Renamed active product branding to Hire-steward; corrected Foundation 2 readiness and checkout runtime defects | `pyproject.toml`/`uv.lock` now use `hire-steward`; FastAPI exposes Hire-steward metadata. Checkout is SHA-pinned to v7.0.1 with Node 24 metadata. `/ready` now verifies required table/column shape, migration head and valid preference state; SQLite regression tests cover dropped table/column, missing/invalid preference, stale/unreachable/unconfigured DB, and liveness isolation. Latest full suite: 63 passed, 9 PostgreSQL tests skipped, one upstream warning. No commit/push/staging; PostgreSQL and hosted CI remain unverified. |

## 9. Update protocol

After meaningful work, update sections 1, 4, 5, 6, 7 and the change log. Record only verifiable outcomes. A checkbox may be marked complete only with an artifact, test result, decision record or reproducible observation. Never infer completion from intended work or from a model-generated summary alone.
