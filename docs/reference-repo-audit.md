# Hire-steward — Reference Repository Audit

**Audit date:** 2026-10-28 (local checkouts; GitHub origin metadata recorded below)  
**Scope:** Read-only source, documentation, dependency, license, test-structure and history review of the eight requested repositories.  
**Execution:** No repository setup scripts, dependencies, tests, containers, migrations, external accounts, job boards or application workflows were run. No reference code was copied into Hire-steward.

## Audit method and limits

For each checkout, the audit inspected its README, license, dependency manifests, source layout, representative implementation, tests, security guidance when present, CI configuration and recent commit history. A local commit SHA and origin URL were recorded. All eight checkouts were clean on their checked-out branches at audit time. Test counts below are file counts or repository-reported counts, not executed test results or measured coverage. Transitive dependency licensing and a full line-by-line security review were not performed.

At the time of this Stage A audit, the Hire-steward root was not a Git repository, so there was no root branch, commit, or reliable Git diff for the project files. The reference clones themselves were independent Git repositories. After the audit, Foundation 1 initialized the root repository on `main`; it still has no commit. Do not treat the reference clones' clean status as evidence about Hire-steward files.

## Repository index

| Repository | Origin / local commit | License | Stack and persistence | Quality evidence observed |
|---|---|---|---|---|
| JobNavigator | [vesaias/JobNavigator](https://github.com/vesaias/JobNavigator) · `0fe65e8fa8275fc34b2fd4d12887872f4ba07545` | MIT | Python 3.12, FastAPI, SQLAlchemy, PostgreSQL 16; React 18/Vite; Playwright; Compose; Caddy/nginx | 258 backend test modules and 30 frontend test files; tests not run |
| mr-jobs | [humancto/mr-jobs](https://github.com/humancto/mr-jobs) · `8bd2ac4c01b2929c504dd5f25825cc9b33d1f60e` | MIT | Python 3.11, FastAPI, Playwright, APScheduler, SQLite/WAL, Docker Compose; YAML profile | 3 test modules; one navigates to public ATS pages if run; tests not run |
| ai-job-search | [ai-job-search-dev/ai-job-search](https://github.com/ai-job-search-dev/ai-job-search) · `83c788d779b74522bb346145ef675b984bf2d3f7` | MIT | Claude Code workflow, Python helpers, Bun/TypeScript portal CLIs, LaTeX; file-based state | 67 test files; fixture/unit CI excludes live portal requests; tests not run |
| last-job-search | [aranculleton/last-job-search](https://github.com/aranculleton/last-job-search) · `893e79568e59dbb5f72770781e98042d873a788a` | MIT; original and fork copyrights | Python, Bun/TypeScript, Claude skills, LaTeX; files and ChatGPT ArtifactData, no PostgreSQL | 397 test files by filename glob; CI exists; private-copy checks partly manual; tests not run |
| applypack | [applypack/applypack](https://github.com/applypack/applypack) · `82d8e312042794a70d580292636bf31eb112f93a` | MIT | TypeScript/Node, Hono, Prisma, PostgreSQL 16, node-cron; web and worker processes | 332 `*.test.ts` files under `src/`; CI runs audit, Prisma validation, types, tests and route smoke checks; not run here |
| dossier | [AienTech/dossier](https://github.com/AienTech/dossier) · `5446f4cb117b0e4b4bbf26c6156c97406b0a4ff2` | AGPL-3.0-only | Next.js/React, TypeScript, Prisma/PostgreSQL, Docker Compose; in-process job runner | 209 `*.test.ts`/`*.test.tsx` files; CI includes lint, typecheck, coverage, PostgreSQL and Playwright E2E; not run here |
| openroles | [aranculleton/openroles](https://github.com/aranculleton/openroles) · `3edb660a675ffca651400e0f9b5aecf6b4894b25` | MIT | Python 3.9+, standard library at runtime; ATS reader/CLI/MCP; no database | 22 test modules; CI matrix covers Python 3.9–3.13; tests not run |
| JobSpy | [speedyapply/JobSpy](https://github.com/speedyapply/JobSpy) · `68b88d6909a2342ad75fbb945c4204a3a7ed666` | MIT | Python 3.10+, requests, BeautifulSoup, pandas, Pydantic, curl_cffi, markdownify; CLI/MCP/DataFrame | No test files found in the checkout; CI builds/lints/typechecks but has no test job |

## Individual findings

### JobNavigator

- **License/reuse:** MIT (`reference-repos/JobNavigator/LICENSE`); retain copyright and license notices in copied substantial portions. Review dependency licenses and source provenance separately.
- **Implementation evidence:** ATS adapters and orchestration in `backend/scraper/`; schema and scoping in `backend/models/db.py` and `backend/accounts/scoping.py`; custom startup migration/seed logic in `backend/seed.py`; provider routing/cost and logging in `backend/analyzer/llm_client.py`, `llm_cost.py`, and `llm_logger.py`; prompt/schema patterns in `prompt_fence.py`, `model_json.py`, and `autofill_schema.py`. Compose includes database, backend, frontend and proxy services; scheduling is in the backend rather than a dedicated worker service.
- **Useful ideas:** Source-specific adapters, database ownership constraints, structured model output validation, test fixtures, provider usage logging and source health.
- **Risks / do not copy:** `SECURITY.md` describes best-effort maintenance and warns against internet exposure; an unset install password can leave the dashboard open. The inspected security guidance reports provider keys and database backups as plaintext. `LEGAL_DISCLAIMER.md` acknowledges source-method terms risks, including opt-in LinkedIn access. Browser autofill is not evidence of a safe or permitted submission workflow. Do not copy provider-key storage, authentication defaults or scraping methods.
- **Fit:** A useful architecture reference, not a policy-complete implementation. No evidence that it implements Hire-steward's hard eligibility gates or uncertain-submission reconciliation.

### mr-jobs

- **License/reuse:** MIT (`reference-repos/mr-jobs/LICENSE`); retain notices if code is copied. No `SECURITY.md` was present.
- **Implementation evidence:** Source discovery under `utils/discovery.py` and source modules; tracking in `utils/tracker.py`; model scoring in `utils/brain.py`; Stagehand form filling in `adapters/stagehand_adapter.py`; HTTP/WebSocket and application routes in `dashboard/server.py`. Uses SQLite WAL and YAML profile data; Docker Compose exposes the dashboard.
- **Useful ideas:** Isolated discovery adapters and a visible dry-run form workflow may inform interface design after independent review.
- **Risks / do not copy:** The code exposes live/batch/continuous application modes. Model output includes an `apply` decision with score thresholds; the audit found no deterministic implementation of Hire-steward's eligibility/consent/legal gates or an uncertain-outcome reconciliation state. The server defaults to `0.0.0.0`, Compose publishes port 8080, and no apparent authentication middleware was found in the reviewed dashboard path. Profile examples/defaults include sponsorship/work authorization/experience answers such as “No,” “Yes,” or “five years”; these can convert unknown facts into assertions. The model prompt includes resume and posting text. `tests/test_real_forms.py` may navigate real public ATS pages if run; it was not run.
- **Fit:** Poor safety-boundary fit. Do not reuse its application decision, answer defaults, live submission path or network exposure defaults.

### ai-job-search

- **License/reuse:** MIT (`reference-repos/ai-job-search/LICENSE`); preserve the notice if code is copied. The repository identifies personal workflow content and recommends private use for candidate data.
- **Implementation evidence:** `tools/job_key.py`, `scrape_state.py`, and `rank_state.py` implement identity/state helpers; `posting_guard.py` performs deterministic posting checks; `security_guards.py`, `fetch_page.py`, and `robots_check.py` cover guards and fetch policy. `README.md`, `SETUP.md`, `AGENTS.md`, `CLAUDE.md`, and `SECURITY.md` explain the workflow. CI is in `.github/workflows/ci.yml`.
- **Useful ideas:** Cheap deterministic screening before expensive model work, fixture-based source checks, source allowlists, posting-integrity checks, and keeping live portal access out of normal CI.
- **Risks / do not copy:** No local web application, API or database; state is file-based and tightly integrated with Claude Code, Bun CLIs and LaTeX. Its own security notes say model defenses are not a sandbox and a posting guard is not an oracle. It documents portal-specific risks, including LinkedIn terms concerns; those are repository statements, not legal findings. Do not adopt its prompts/tool permissions wholesale or treat its workflow as authorization to access a source.
- **Fit:** Strong reference for bounded, reviewable workflow steps; not a local-first full-stack base.

### last-job-search

- **License/reuse:** MIT with separate copyright attributions for upstream and fork additions (`reference-repos/last-job-search/LICENSE`). Preserve both relevant notices if copying fork-derived code.
- **Implementation evidence:** Deterministic stages and time bounds in `ARCHITECTURE.md` and `tools/run_round.py`; source handling in `tools/ats_boards.py`, `robots_check.py`, and `hydrate.py`; state contracts/locks in `tools/page_db.py` and `tools/app.py`; untrusted text and claim checks in `tools/untrusted.py`, `check_claims.py`, and `verify_batch.py`.
- **Useful ideas:** Deterministic prefiltering before model judgment, quote-backed gates, provenance, bounded stages, single-writer claims/locks, safe retries, and platform-specific fixture tests.
- **Risks / do not copy:** A file-based pipeline and ChatGPT ArtifactData-backed page state are not PostgreSQL and are not a standalone local UI. It documents no application or message sending, but its source-platform assumptions still need independent verification. GitHub-based private-copy update flow is another trust surface; profile files can contain personal data. Repository claims about LinkedIn/source restrictions are not legal conclusions.
- **Fit:** Useful process patterns; avoid adopting candidate-specific state, cloud ArtifactData contracts, portal behavior or update workflow wholesale.

### applypack

- **License/reuse:** MIT (`reference-repos/applypack/LICENSE` and package metadata); preserve notices for copied code. Review bundled assets/dependency licenses separately.
- **Implementation evidence:** `ARCHITECTURE.md`, `docker-compose.yml`, and `src/local/` show local and Compose modes; fetchers in `src/fetchers/`; deterministic relevance and edit gates in `src/classifier.ts`, `src/resume/score.ts`, `src/pack/gate.ts`, and `src/pack/policy.ts`; untrusted-text fencing in `src/prompt-fence.ts`; application pack generation in `src/pack/prepare.ts`. The pack path prepares artifacts rather than submitting applications.
- **Useful ideas:** Source-specific fetchers, bounded web/worker processes, idempotent fetch processing, explicit preparation gates, localhost defaults and host/origin checks.
- **Risks / do not copy:** `SECURITY.md` notes prompt injection, SSRF, XSS and data leakage risks. The local dashboard is single-user; keys may be stored in database settings or environment, and the inspected paths do not establish at-rest encryption. README says “no telemetry,” while an optional release check and external AI/notification integrations still make outbound calls. Node requirements differ between package/readme and CI/Docker (22+ versus 24); verify before adopting. Its source-access ADR and claims are time-sensitive, not Hire-steward permission evidence.
- **Fit:** Good policy/testing patterns to study, not a drop-in backend; no authorization to reuse its source decisions.

### dossier

- **License/reuse:** AGPL-3.0-only (`reference-repos/dossier/LICENSE`, `package.json`). This is a reciprocal license with network-use obligations; do not incorporate or adapt code without explicit legal review and an intentional compliance decision.
- **Implementation evidence:** Prisma data model in `prisma/schema.prisma`; provider interface/tasks in `src/lib/ai/provider.ts`, `src/lib/ai/index.ts`, `src/lib/ai/tasks/score-posting.ts`, and `src/lib/ai/fact-guard.ts`; draft-only job agent in `src/lib/agent/run.ts`; database-backed import/export, state history and retention modules in `src/lib/`.
- **Useful ideas:** Evidence-grounded drafting, typed AI task outputs, explicit status history, guarded fetches, and import/export tests.
- **Risks / do not copy:** Next.js/server deployment and auth assumptions do not match the proposed Vite/FastAPI local-first app; the in-process runner assumes one application instance. Development Compose publishes PostgreSQL with default credentials and maps the app broadly; `SECURITY.md` warns against exposing the app port and recommends a protected ingress. Opt-in usage pings are documented. `src/lib/job-search/arbeitsagentur.ts` and `.env.example` describe a public-client endpoint and explicitly state automated access is not permitted by its terms; do not copy that adapter or its assumptions. These are repository statements, not an independent legal ruling.
- **Fit:** Useful concepts only. AGPL requires legal review before any code incorporation.

### openroles

- **License/reuse:** MIT (`reference-repos/openroles/LICENSE`); retain notices if code is copied. Runtime has no third-party Python dependencies (`pyproject.toml`); build/test tooling is separate.
- **Implementation evidence:** Provider discovery in `src/openroles/discover.py`; network client, timeouts, conditional caching, redirects and per-host concurrency in `src/openroles/_http.py`; robots/content-signal behavior in `src/openroles/robots.py`; ATS adapters under `src/openroles/providers/`; fixtures/tests under `tests/`; security reporting guidance in `SECURITY.md`. README documents 15 ATS families plus schema.org career pages. CI uses fixtures and a Python 3.9–3.13 matrix.
- **Useful ideas:** Per-source adapters, typed normalized job records, request timeouts, conservative request concurrency, `Retry-After` handling, conditional caching, robots-aware redirect checks, and offline fixtures.
- **Risks / do not copy:** The README's claims that particular paths are allowed or that a vendor endpoint is public are project claims, not an authorization or legal conclusion. Several documented vendor endpoints are not public developer APIs and can drift. `detect()` can fetch a user-provided careers URL; any embedding must add Hire-steward's own SSRF/private-network and redirect policy. Robots rules are one input to source policy, not proof of permission. The library is discovery-only, not a submission executor.
- **Fit:** Closest source-adapter reference, but it is not a permission registry, durable checkpoint system, Hire-steward domain model or complete security boundary.

### JobSpy

- **License/reuse:** MIT (`reference-repos/JobSpy/LICENSE`); preserve notices if code is copied. Python dependencies are listed in `pyproject.toml` and pinned in `poetry.lock`; optional MCP packaging is separate.
- **Implementation evidence:** `README.md` documents LinkedIn, Indeed, Glassdoor, ZipRecruiter, Bayt, Naukri, BDJobs and HelloWork scrapers; source-specific modules live under `jobspy/`. `jobspy/model.py` defines the shared model and float compensation values; `jobspy/util.py` implements sessions and retries/status handling. CI builds packages and runs Ruff/mypy, but no test files or test job were found in this checkout.
- **Risks / do not copy:** The README promotes proxy support “to bypass blocking”; `jobspy/util.py` rotates configured proxies, `TLSRotating` impersonates Chrome, and 403/429 errors suggest using a proxy. These behaviors conflict directly with Hire-steward's no-evasion rule. Source terms, access permissions and rate limits are not centrally verified by Hire-steward. Compensation uses floating-point amounts and approximate conversion factors (`2080` hours/year, etc.), unsuitable for reliable financial decisions. Do not use the proxy/impersonation paths, anti-blocking behavior, financial normalization or unverified source adapters.
- **Fit:** Useful only for viewing source-specific parsing shapes after each source's permissions are independently established. Not a safe adapter baseline.

## Cross-repository conclusions

1. The most transferable concepts are boundaries and tests: deterministic gates, evidence IDs, immutable snapshots, source-specific capabilities, bounded work, fixtures, and reconciliation records.
2. None of the repositories proves that Hire-steward's policies have been implemented or that a source method is permitted for Hire-steward. Multiple projects explicitly permit live forms, proxy use, or source-specific methods that conflict with Hire-steward's constraints.
3. MIT repositories still require notice retention if their code is copied. Dossier is AGPL-3.0-only and needs explicit legal review before incorporation. No code was reused in this audit.
4. The next implementation should be original and narrow. Use the references as design evidence only; review exact files, provenance, dependencies, license obligations, security behavior and compatibility before any future reuse.
