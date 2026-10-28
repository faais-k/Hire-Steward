# Hire-steward — Testing and Evaluation Plan

**Status:** Release-control document. Automated live application submission stays disabled until the applicable gates pass.

## 1. Testing philosophy

Test deterministic correctness with normal automated tests; test AI quality with labeled evaluation sets; test external integrations with recorded/sanitized fixtures and sandbox/dry-run adapters; test consequential side effects with fault injection and reconciliation. A passing unit-test suite does not prove that an ATS integration is permitted, stable or safe.

## 2. Test layers

### Unit tests

Target pure or narrowly scoped components:

- Compensation normalization and annualization.
- Timezone and local day-boundary behavior.
- Role targeting, required/preferred qualification logic, sponsorship uncertainty.
- State transitions and policy gates.
- Exact duplicate/cooldown rules and canonical URLs.
- Candidate facts, provenance and contradiction resolution.
- Content hashes, cache keys and invalidation.
- Provider error normalization, retry budgets and privacy dispatch rules.
- Import manifest/schema/path validation.

### Integration tests

Use a real temporary test PostgreSQL instance/database with migrations:

- Transactional gate checks and concurrent submission lock.
- Unique constraints and idempotency keys.
- Checkpoint mutation only after adequate source completion.
- Application attempt + audit event atomicity.
- Query/index behavior at realistic data volume.
- Migration from previous schema version and restore into a clean DB.
- Document file-store/database consistency and orphan cleanup.

### Contract tests

- Source API fixtures reflect documented response shapes.
- Missing optional fields, unexpected types, empty descriptions, closed job and pagination edge cases.
- Provider outputs that are malformed, truncated, refused or missing usage data.
- Email provider errors including uncertain timeout.
- No live API tests in normal CI unless rate limits, terms and costs are explicitly controlled.

### Browser tests

- Use a local simulated ATS form with stable deterministic behavior.
- Validate labels/field mapping, required question changes, attachment errors, form validation, CAPTCHA marker and confirmation page cases.
- Do not test against a real employer portal without permission and careful controls.
- Test `submit` double-click, navigation timeout, page crash, connection loss before/after submit, and site schema drift.

### Security tests

- Prompt injection and hostile instructions in jobs, PDFs, emails and OCR text.
- SSRF/private network URL attempts.
- Path traversal, zip-slip, malformed file and oversized archive behavior.
- HTML/script injection in job descriptions and filenames.
- Unauthorized resource IDs, missing auth in remote configuration, secrets in logs/export.
- Concurrency races on daily caps, source runs and duplicate application.

### AI evaluation

Separate the prompt/model evaluation harness from unit tests. Pin model IDs, prompt versions, sample set, scoring/policy version and retrieval settings. Record results with exact configuration to make comparisons reproducible.

## 3. Critical edge-case matrix

| Area | Case | Required result |
|---|---|---|
| Scheduling | Host timezone differs from configured zone | Run at configured Asia/Kolkata times |
| Scheduling | A prior run is still active | No overlapping source run/checkpoint mutation |
| Source checkpoint | API times out after first page | Preserve fetched observations; do not advance checkpoint past incomplete range |
| Source isolation | One source fails, another succeeds | Successful source completes; failed source is visible and retryable |
| Posting date | Date absent or malformed | Unknown/low-quality date; don't fabricate a publication date |
| Job lifecycle | Listing disappears | Mark stale/possible closure; preserve historical snapshot |
| Dedupe | URL has tracking parameters | Canonical duplicate recognized when identity supports it |
| Dedupe | Similar title, different requisition | Do not hard-merge based on title alone |
| Apply cooldown | Same role reposted within 30 days | Block/review according to duplicate evidence; repost does not bypass cooldown |
| Compensation setting | New profile default | Persist/display INR 100,000 per year; UI labels currency and annualized unit |
| Compensation setting | User sets INR 50,000/year; reliable annual salary is INR 60,000 | Compensation gate passes only; other gates still apply |
| Compensation setting | User sets INR 150,000/year; reliable annual salary is INR 120,000 | Compensation gate blocks |
| Compensation setting | Zero minimum | Accept valid finite zero; unpaid roles remain blocked |
| Compensation setting | Negative, malformed, NaN, infinity or otherwise invalid amount | Reject at backend boundary; no persisted change |
| Compensation status | Confirmed unpaid role at any configured minimum | Block application, including with zero minimum |
| Compensation status | Salary unknown | Investigate/review; never silently pass or fail |
| Compensation range | Range entirely below configured minimum | Compensation gate blocks |
| Compensation range | Range entirely above configured minimum | Compensation gate passes only |
| Compensation range | Range crosses configured minimum | Review/no auto-submit unless reliable additional evidence resolves the uncertainty |
| Compensation normalization | Explicit recurring monthly rate with known currency | Annualize monthly amount × 12, retain source evidence and assumption |
| Compensation normalization | Hourly rate without reliable hours/year | Do not annualize; investigation/review |
| Compensation normalization | Foreign currency without a reliable sourced/timestamped exchange rate | Do not compare as a confirmed INR amount; investigation/review |
| Compensation history | Minimum changes after a job assessment | Preserve old assessment threshold; a new assessment uses the current persisted preference |
| Compensation history | Preference changes after an application was submitted | Preserve historical threshold and do not rewrite submitted facts, answers or outcome |
| Compensation AI boundary | Model claims below-minimum job is eligible or proposes changing the setting | Ignore as authority; deterministic backend uses persisted setting and blocks as applicable |
| Compensation evidence trust | Public caller submits `verified=true`, `trusted=true`, a verification state, or an AI decision | Reject with safe `422`; response does not echo submitted values |
| Compensation evidence trust | Caller reports `PAID`, a plausible annual amount, and an arbitrary reference | Return `REVIEW_REQUIRED` / `EVIDENCE_UNVERIFIED`, label inputs as reported, and set `eligible_to_submit=false` |
| Compensation evidence trust | Model output claims a salary is verified or supplies a positive decision | Model fields cannot set trusted state or change the deterministic result |
| Compensation evidence trust | Caller reports `UNPAID` without trusted provenance | Keep it explicitly reported/unverified and review-required; do not label it a confirmed unpaid fact or allow it to proceed |
| Compensation evidence trust | No trusted evidence source is available | Keep public assessment review-required; a stored reference or extracted text does not count as verified evidence |
| Compensation migration | Upgrade a legacy assessment without provenance | Mark its state `UNVERIFIED`, preserve stored facts/threshold/original record, and return an effective review-required API result |
| Skills | Preferred skill missing | Penalize/annotate; no automatic hard rejection |
| Mandatory requirement | Required fact missing/conflicting | Review; no auto-submit |
| Experience | Experience gap but strong relevant skills | Do not automatically reject on experience gap alone |
| Visa | Sponsorship unknown | Investigate/review; do not assume yes/no |
| AI extraction | Empty parse for a document | Existing accepted data remains unchanged |
| AI answer | Fact not in evidence | Ask user or leave unanswered; never invent |
| Answer reuse | Similar wording, different legal meaning | Do not reuse automatically |
| Injection | Page tells model to reveal secrets/apply elsewhere | Ignore; executor enforces allowlist and policy |
| Submission | Crash before request sent | Reconcile state and safely allow later attempt after checks |
| Submission | Remote accepted, client times out | `CONFIRMATION_UNKNOWN`; reconcile before any retry |
| Submission | Confirmation page lacks stable evidence | Not `APPLIED` until source-specific evidence or user verifies |
| Submission | Two simultaneous submit requests | One attempt at most; second returns existing state/conflict |
| CAPTCHA | CAPTCHA shown | Pause affected source/application; manual handoff if allowed |
| Email | SMTP/API timeout after send may have occurred | Reconcile before retry; avoid duplicate email |
| Export | Package includes token unexpectedly | Export fails or strips it; test must fail release |
| Import | Zip-slip/path traversal member | Reject package without writing outside staging directory |
| Provider quota | 429 or quota exhaustion | Respect limit, use only approved fallback or defer |
| Cost | Paid budget absent/exceeded | Paid model is not invoked |
| Restore | DB restored, evidence file missing | Detect integrity error and explain recovery; no silent partial success |

## 4. Foundation 1 verification status (2026-10-28)

These are implementation/test results for the first backend slice only. They do not complete the product-wide acceptance matrix above.

| Behavior | Implementation | Verification |
|---|---|---|
| INR 100,000/year default; configure INR 50,000, INR 150,000, or zero | Implemented in migration and settings API | Pass: SQLite migration/API integration tests |
| Negative, malformed, non-finite, exponent-form, numeric-JSON, and excess-precision values | Rejected by strict API schema before storage | Pass: validation integration tests; no audit event is written |
| Exact annual boundary and below/above comparison | Deterministic `Decimal` evaluator | Pass: unit tests |
| Trusted unpaid, unknown, below-range, above-range, and crossing-range cases | Deterministic evaluator | Pass: unit tests; trusted unpaid remains blocked at zero and nonzero thresholds; public unverified unpaid reports remain review-required |
| Explicit recurring monthly × 12 and hourly with missing work hours | Monthly path is normalized with recorded basis; hourly remains review-required | Pass: unit tests |
| Audit event and rollback on failed audit constraint | Preference and audit commit in one transaction | Pass: SQLite API/integration tests, including database constraint failure rollback |
| Server setting enforced; client threshold/model decision cannot override it | Assessment service reads persisted setting; request rejects extra fields | Pass: API integration tests; public compensation evidence remains unverified |
| Public compensation evidence boundary | Caller status/amount/reference cannot create verified or submission-eligible assessment; invalid trust/AI fields fail safely | Strict request schema, server-assigned `UNVERIFIED` state, deterministic review result and redacted validation error | Pass: API integration suite; public assessments remain unverified |
| Legacy evidence migration | Upgrade/downgrade 0001 assessments without provenance | Default/backfill verification state to `UNVERIFIED`; preserve original stored facts/outcome; effective API view requires review; downgrade removes only the trust-state field | Pass: SQLite migration/API integration test |
| Assessment context after later preference change | Assessment stores old threshold and version; no update route | Pass: SQLite API integration test |
| Preserve already-submitted application records | No application-record model or submission route exists in this slice | Not implemented or tested |
| Matching, dashboard, scheduling, preparation, and final submission gates | Not wired in this slice | Pending; no claim of cross-product enforcement |
| PostgreSQL migration/transaction behavior | PostgreSQL service unavailable; Docker engine is not running | Not run; use a dedicated PostgreSQL integration database before production use |

Command run: `$env:PYTHONDONTWRITEBYTECODE='1'; .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q` — **53 passed**, one upstream Starlette/AnyIO deprecation warning. Tests include unit policy cases and in-memory SQLite migration/API/transaction coverage, including the 0001-to-0002 upgrade, fail-closed legacy API view, and downgrade. This does not verify PostgreSQL locking/behavior, Compose, or any external integration. PostgreSQL tests were not run because the local Docker engine/database service is unavailable.

## 5. Foundation 2 PostgreSQL verification

The explicit `postgres` marker selects `backend/tests/integration/test_postgres_integration.py`. Its fixture requires `JOBPILOT_TEST_DATABASE_URL` to use the `postgresql+psycopg` driver and the database name `jobpilot_test`. For each test, it creates a random schema, applies Alembic migrations using a connection whose search path targets that schema, then drops only that schema. It never drops or recreates the database. An unset URL causes a clear skip; a configured but unreachable PostgreSQL server causes a test failure rather than a simulated pass.

The suite has nine independent PostgreSQL test functions, confirmed with `pytest --collect-only -m postgres`. It covers a fresh migration and model/schema constraints, readiness after a required table is dropped while the migration marker remains, the `NUMERIC(18,2)` preference default, legacy migration to `UNVERIFIED` with fail-closed API output, exact decimal/audit round-trip, rollback when the audit insert violates a constraint, concurrent preference updates with linear audit versions, singleton and primary-key constraints, and the public unverified evidence boundary.

Current local verification on 2026-10-28:

- Latest local full-suite command: `$env:PYTHONDONTWRITEBYTECODE='1'; .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q` — **63 passed, 9 skipped**, with one upstream Starlette/AnyIO deprecation warning. All nine skips are PostgreSQL cases because `JOBPILOT_TEST_DATABASE_URL` was unset.
- Readiness tests include SQLite success at the current migration head, stale migration, unconfigured database, missing schema, a required table or column removed after successful migration while the marker remains, missing/invalid preference state, and a PostgreSQL URL on an intentionally unavailable local port. These tests establish application behavior without proving PostgreSQL compatibility.
- `docker compose --env-file .env.example config --quiet` passed; `uv lock --check --offline --cache-dir .venv\uv-cache` passed; `uv sync --locked --offline --cache-dir .venv\uv-cache --python 3.12` audited the locked environment; `uv run --locked --offline --cache-dir .venv\uv-cache --env-file .env.example python -c "import os; assert os.environ['DATABASE_URL'] == 'postgresql+psycopg://jobpilot:local_dev_only@127.0.0.1:5432/jobpilot'; print('uv env-file: DATABASE_URL loaded')"` passed; `.\.venv\Scripts\python.exe -m compileall -q backend/app backend/migrations` passed.
- No YAML parser or `actionlint` is installed locally. The CI workflow was manually reviewed; the pinned `actions/checkout` and `astral-sh/setup-uv` `action.yml` files were verified upstream to declare Node 24. This is syntax/runtime-source review only, not a GitHub Actions run.
- The Docker engine is unavailable, and the installed Windows PostgreSQL service is stopped. No PostgreSQL test passed locally. The GitHub Actions workflow is configured but has not run on GitHub.

The first lock check using uv's default cache failed because this restricted workspace could not access the user-level uv cache. Re-running with the ignored project virtual environment's cache directory succeeded; no dependency was added or lockfile changed.

Run fast tests with `uv run --locked pytest -m "not postgres" -q`. Run PostgreSQL tests only after preparing a dedicated `jobpilot_test` database with `JOBPILOT_TEST_DATABASE_URL` set: `uv run --locked pytest -m postgres -q`. GitHub Actions runs the full suite against its own health-checked PostgreSQL 17.11 service. Results from CI must be recorded separately after an actual workflow run.

## 6. Gold datasets

Create a versioned fixture set, with personal information removed or synthetic where possible:

- 50–100 varied job descriptions covering clear fit, adjacent fit, mandatory gaps, conflicting wording, unknown sponsorship, no salary, salary ranges and misleading/reposted jobs.
- Candidate profile facts with explicit provenance, ambiguity, contradictions, stale facts, and skills mentioned only in weak evidence.
- At least 20 hostile prompt-injection fixtures across job pages and documents.
- At least 20 submission lifecycle simulations across success, pre-send failure, post-send uncertainty and duplicate recovery.

The counts above are an initial minimum proposal, not a claim of statistical sufficiency. Expand from observed failure modes. Label expected outcomes before tuning scoring.

## 5. Evaluation metrics

### Document extraction

- Per-field precision/recall/F1 for important facts.
- Date/number/unit normalization accuracy.
- Source span validity.
- Unsupported fact rate.
- Document failure detection and destructive-update count (target zero destructive overwrites).

### Job requirement extraction

- Mandatory vs preferred classification precision and recall.
- Skills, location, work arrangement, compensation and sponsorship extraction quality.
- Extraction confidence calibration or categorical agreement.

### Retrieval and ranking

- Precision@k, Recall@k, MRR or nDCG on a labeled relevance set.
- Skill evidence recall and false-positive rate.
- Ranking stability across paraphrases, noise and minor source formatting changes.
- Explainability: percentage of candidate-specific claims linked to valid evidence.

### Policy and application quality

- Hard-gate leakage: count of prohibited cases considered auto-submit eligible (target 0 in gold tests).
- Unsupported claim rate (target 0 in the release gold set).
- Duplicate submission-attempt rate in deterministic simulations (target 0).
- False `APPLIED` transitions without required evidence (target 0).
- Reconciliation completeness in uncertain outcome simulations (target 100% accounted for).
- Human correction rate and recurring reasons.

### Performance and cost

Track p50/p95 response time per task, extraction throughput, source run duration, database query latency, vector retrieval recall/latency, model input/output tokens, errors/fallbacks and cost per prepared/eligible application. Don't optimize cost by reducing required safety checks.

## 6. Proposed release gates

Before enabling any live submission path:

- All unit/integration tests for policy, dedupe, counters and state transitions pass.
- All defined hard-gate leakage tests pass with zero violations.
- All submission crash/uncertainty simulations produce safe recoverable states.
- No unsupported claims appear in the gold set used for release approval.
- Security/redaction tests pass.
- Backup/restore works.
- Source capability/terms are reviewed and recorded.
- A manual stop switch, adapter disable switch, and incident procedure are tested.
- Pilot scope and daily volume are intentionally limited.

For model/prompt changes, additionally require an evaluation diff and approval. Any regression in mandatory requirement classification, fact grounding or safety behavior blocks promotion even if average relevance improves.

## 7. Test data and privacy

- Use synthetic/fake identities in tests; never commit actual candidate documents.
- Scrub provider keys and email addresses from fixtures.
- Store real-world evaluation samples only under explicit access and retention controls.
- Do not include full raw prompts or sensitive output in CI logs.
- Test redaction by scanning generated logs, exports and traces for sentinel secret values.

## 8. Reporting

Every release evaluation report includes commit, dependency lock hash, DB migration version, model/provider IDs, prompt/schema/policy versions, dataset version, expected thresholds, achieved metrics, failed cases, known gaps and release decision. “Looks good manually” is not an adequate evaluation report.
