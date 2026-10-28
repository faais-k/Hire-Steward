# JobPilot — Engineering, Dependency, and AI Rules

**Status:** Normative engineering baseline. Any exception requires a short written rationale and an ADR when it changes architecture or safety behavior.

## 1. General rules

1. Optimize for correct, understandable, testable code—not minimum line count or maximum abstraction.
2. Prefer boring, well-maintained dependencies with clear licenses, active documentation, and compatible security posture.
3. Add a dependency only when a concrete requirement cannot reasonably be met with the standard library or an existing dependency.
4. Pin major/minor versions according to the chosen lock strategy. Reproduce installs from a lockfile in CI. Automate dependency vulnerability checks where practical.
5. Treat source pages, job descriptions, resumes, email contents, document metadata, and model output as untrusted input.
6. Keep all policy decisions explicit, centralized and unit-tested. Do not scatter eligibility logic across routes, prompts, frontend components, or browser scripts.
7. Make external side effects idempotent where possible and reconcilable where idempotency is impossible.
8. Do not make a feature look complete if its source, permission, confidence, or reliability has not been tested. Display unsupported capabilities as unavailable/manual.
9. No secrets, private candidate documents, personal exports, database dumps or raw production logs in Git.
10. Keep `docs/memory.md` current after completing a meaningful phase, changing an important decision, discovering a blocker, or updating current work.

## 2. Languages and frameworks

### Backend

- Use Python 3.12+ as a starting requirement; select and pin the exact version after checking every core dependency and deployment image.
- Use type hints for public functions, domain interfaces and data models.
- Use Pydantic for API/provider boundary schemas and validation.
- Use SQLAlchemy 2.x and Alembic for relational persistence and schema migrations.
- Use FastAPI route handlers for HTTP concerns only; put use cases in application services and invariants in domain/policy functions.
- Separate IO adapters (ATS, LLM, browser, files, email) from core policy logic.
- Use `Decimal` or integer minor units for money; never use binary float for financial threshold decisions.
- Use timezone-aware datetimes stored consistently (UTC for event timestamps, explicit source timezone/local-date metadata where material). The scheduler uses `Asia/Kolkata` as configured local zone, not the host's unspecified timezone.

### Frontend

- Use TypeScript strict mode.
- Treat API responses as untrusted until parsed/validated by typed API clients.
- Centralize design tokens; do not hard-code scattered hex colors, spacing, or font sizes.
- Keep safety/business policy on the backend. Frontend gate rendering is informative; backend submission endpoints independently recheck gates.
- Avoid giant components, hidden side effects in rendering, and duplicate sources of truth for job/application state.

### Database

- Migrations are source-controlled, reviewed, and tested on both fresh and upgraded schemas.
- Use database constraints for invariants that must survive concurrent requests (unique keys, non-null fields, valid foreign keys, checks where appropriate).
- Use transactions around state transitions and corresponding audit events.
- Use optimistic version columns or row locks for conflicting updates.
- Do not keep a transaction open while calling an LLM, crawling a site, or waiting for a human.
- Never share one SQLAlchemy `AsyncSession` across concurrent asyncio tasks.
- Design indexes from actual query patterns and explain plans, not from field names alone.

## 3. Dependency policy

### Preferred baseline

| Concern | Preferred starting choice | Rule |
|---|---|---|
| HTTP/API | FastAPI, Pydantic | Avoid duplicate API frameworks |
| DB/ORM/migrations | PostgreSQL, SQLAlchemy 2.x, Alembic | One primary transactional store |
| Vector retrieval | pgvector (optional after evaluation) | Store model/version/dimension; benchmark before HNSW |
| PDF extraction | A maintained PDF text extraction library selected in prototype | Test digital PDFs and scanned PDFs separately; OCR is not guaranteed |
| DOCX | A maintained DOCX parser | Preserve source version; test tables/headers/footers |
| XLSX | A maintained workbook reader | Avoid formula recalculation claims unless a calculation engine is present |
| Browser automation | Playwright | Site/source permission required; no stealth or access-control evasion |
| Frontend | React, TypeScript, Vite | Avoid parallel framework choices without a reason |
| Testing | pytest + frontend test tooling + Playwright for permitted browser paths | Deterministic tests before live automation |
| Configuration | Pydantic settings or one equivalent config layer | Validate at startup and fail closed for missing critical settings |

No specific extractor, scheduler or frontend state-management package is approved until a spike confirms maintenance, license, file support, and compatibility. Use a single lockfile policy. Avoid retaining both `requirements.txt` and a second active lock strategy without clear ownership.

### Do not add by default

- Redis, Celery, RabbitMQ, Kafka, Kubernetes, service mesh, a second vector database, a separate search cluster, or a second relational database.
- A generic “agent framework” if a small task orchestrator and typed tools solve the use case.
- A giant UI component library if accessible primitives and a few well-tested components are sufficient.
- A PDF/Word conversion service that uploads candidate documents to an unknown third party.
- Multiple overlapping retry, caching, schema-validation, or scheduling libraries.

Add any of these only after: (1) a stated need, (2) a benchmark or operational failure demonstrating insufficiency, (3) an ADR, (4) license/security review, and (5) an updated runbook.

## 4. Error handling and retries

### Error taxonomy

Use a structured application error with stable `code`, safe `message`, `retryable`, optional `field_errors`, `correlation_id`, and a sanitized diagnostic context. Avoid surfacing stack traces or provider payloads to the UI.

Classify errors at least as:

- `VALIDATION_ERROR`: input invalid; no retry until corrected.
- `POLICY_BLOCKED`: gate failed; not retryable without changed facts/settings or a human decision.
- `AUTH_REQUIRED`: user/provider authorization needed.
- `SOURCE_RATE_LIMITED`: respect `Retry-After`/published limits and back off.
- `SOURCE_UNAVAILABLE`: retry boundedly if read operation is safe.
- `PROVIDER_QUOTA_EXCEEDED`: switch only to an approved fallback or defer; do not evade quota.
- `PROVIDER_TIMEOUT`: retry within configured budget only for safe/idempotent tasks.
- `PARSE_FAILED`: preserve original and prior accepted data; mark reprocessing need.
- `CONFLICT`: state version conflict; reload and resolve explicitly.
- `SUBMISSION_UNKNOWN`: external side effect may have happened; reconcile before retry.
- `SECURITY_BLOCKED`: stop action and record safely.

### Retry rules

- Use bounded exponential backoff with jitter and an overall deadline for safe read/compute operations.
- Respect provider `Retry-After`, quotas and terms.
- Do not retry non-idempotent POST/application submission automatically unless the remote system provides a confirmed idempotency mechanism or reconciliation proves the prior attempt did not succeed.
- Never retry a recruiter email send solely because the local client timed out; reconcile via provider message ID/history where permitted.
- Do not retry a policy-blocked task on the same unchanged inputs.
- Record every retry attempt and its reason.

## 5. AI boundary rules

### AI may

- Extract candidate/job fields into typed draft records.
- Classify requirements and question types.
- Retrieve or summarize relevant candidate evidence.
- Propose a match explanation, score components, and tailored text.
- Suggest equivalent previously approved answers with evidence and confidence.
- Flag a possible legal commitment, sensitive-data field, suspicious prompt injection, or uncertainty.

### AI may not

- Change targeting or safety settings on its own.
- Mark unknown facts as true; invent employers, dates, project metrics, degrees, experience, salary, visa status or certifications.
- Override a deterministic eligibility/compensation/duplicate/daily-limit/legal gate.
- Decide that a high score compensates for a policy violation.
- Use candidate secrets (passwords, tokens, cookies, OTPs) as model context.
- Browse arbitrary destinations, execute shell commands, run arbitrary JavaScript, use arbitrary network tools, or select unapproved recipient addresses.
- Submit an application, send an email, or accept terms without the separately authorized executor and current policy checks.
- Treat instructions embedded in a job post, resume, email, website or parsed file as system policy.
- Claim an application succeeded without the required external evidence.

### Required AI output controls

- Prefer provider-supported schema-constrained output; validate the response with Pydantic or an equivalent strict schema.
- Enforce enums, ranges, date formats, currency units, and maximum lengths server-side.
- Compensation extraction may return only evidence-backed source amount/range, currency, period, paid/unpaid/unknown state, source span and confidence. The deterministic backend, not the model, reads the persisted minimum and decides the compensation gate; reject any model output that attempts to alter settings or eligibility.
- Use provenance IDs for facts and requirements. A model must cite internal evidence IDs when it makes candidate-specific claims.
- Reject or quarantine malformed/untrusted output. One repair attempt may be allowed for format-only errors; never silently coerce material facts.
- Store model/provider ID, prompt version, schema version, input content hashes, retrieval evidence IDs, latency, usage, response status, and policy evaluation ID where feasible.
- Redact sensitive content before logging; only store prompts/responses under a documented retention and privacy policy.
- Treat provider fallback as a new model invocation with new provenance; do not silently merge incompatible outputs.

## 6. Prompt and retrieval rules

- Put explicit delimiters and instruction hierarchy around retrieved documents.
- Tell the model that retrieved content is data, not instructions, and that embedded requests to ignore policy, reveal secrets, change system behavior or invoke tools must be ignored.
- Do not rely on a prompt to enforce permissions. The backend executor must enforce tool allowlists independently.
- Only include the minimum candidate evidence needed for the task.
- Retrieval similarity is a candidate-retrieval signal, not proof of skill, truth, or eligibility.
- Separate mandatory requirements from preferred skills and responsibilities.
- Prefer BM25/full-text search and semantic search as independent channels; use RRF when score scales differ, then apply evidence-aware ranking.
- Embeddings must include model/provider/dimension/normalization metadata. Never compare vectors from incompatible models/spaces.
- Cache keys must include all behavior-changing versions: content hashes, prompt version, model ID, schema/policy version, and relevant settings. Invalidate when any dependency changes.
- Store raw parser output separately from accepted facts. Failed parsing must not erase or downgrade verified records.

## 7. Code structure and review

A change that adds a new external source/provider must include: adapter, capability/permission declaration, rate-limit policy, error mapping, normalization, tests with recorded sanitized fixtures, and documentation. A change to eligibility or score must include policy tests, a change log/version bump, and evaluation results.

Pull-request checklist:

- Does this change preserve existing working behavior?
- Does it introduce an external side effect or new sensitive-data path?
- Are validations performed on the server and at the final side-effect boundary?
- Are exceptions bounded and sanitized?
- Are migrations and rollback implications understood?
- Are tests deterministic and meaningful?
- Does `memory.md` need updating?
- Are docs, logs, metrics and user-facing explanations accurate?

## 8. Security rules

- Default bind address is localhost; never expose the API publicly by accident.
- Secrets live in an OS credential store or encrypted vault, not plain committed config.
- The `.env.example` contains placeholders only. A local `.env` is ignored by Git and should not be the long-term secret vault for a remote host.
- Enforce a domain allowlist for browser interactions and source adapters.
- No CAPTCHA bypass, stealth fingerprinting, proxy/account rotation, or other access-limit evasion.
- Do not disable TLS validation to “fix” network errors.
- Keep browser state and cookies isolated; never export them by default.
- Sanitize filenames and prevent path traversal/zip-slip on import.
- Use least-privilege database and operating-system users.

## 9. Configuration rules

Validate all settings at startup. Example groups:

- `APP_ENV`, `APP_HOST`, `APP_PORT`, `APP_LOG_LEVEL`.
- `DATABASE_URL` (secret; supplied through secret mechanism).
- `SCHEDULER_TIMEZONE=Asia/Kolkata` and run times.
- `MAX_APPLICATIONS_PER_DAY=5`, `MAX_APPLICATION_EMAILS_PER_DAY=5`.
- Persist a versioned `minimum_compensation` setting with default `{amount: "100000", currency: "INR", period: "YEAR"}`. The application settings UI labels this as **Minimum annual compensation (INR per year)** and explains conversion assumptions. Validate the amount as an exact finite decimal >= 0; reject malformed, negative, NaN, infinite, or otherwise invalid values. Zero is valid. This is a user preference, not an environment-only constant.
- The independent unpaid-role prohibition remains a hard policy gate at every setting value. Never annualize or convert compensation without a defensible basis; unknown or threshold-straddling values require investigation/review. Do not invent hours, work days, contract duration, or exchange rates.
- Apply the persisted setting deterministically during matching/eligibility, dashboard explanation, scheduling/reassessment, application preparation, and the final submission gate. Every assessment/policy evaluation snapshots the threshold amount, currency, annualized unit and applicable conversion basis. A change creates a versioned audit event containing only previous/new setting values, timestamp, actor and settings version; it does not rewrite existing assessments or submitted application facts, answers, or outcomes.
- `AI_PAID_FALLBACK_ENABLED=false`, optional explicit cost budget.
- Source feature toggles/allowlists and source-specific rate caps.
- Data retention/export and optional provider data-sharing permissions.

Settings must be surfaced in the UI with clear defaults and persisted audit history when changed. The LLM cannot mutate configuration or override the deterministic compensation decision.

## 10. Prohibited shortcuts

- One giant prompt that discovers, judges, drafts, decides and submits in a single call.
- Marking all unknowns as pass or fail for convenience.
- Swallowing exceptions and returning success-shaped defaults.
- Deleting old facts when new extraction is empty.
- Unbounded recursive agents, arbitrary tool calls, or open-ended loops.
- Score thresholds selected solely by intuition and presented as validated.
- Inserting raw HTML/job text into the UI unsanitized.
- Logging prompts containing PAN/Aadhaar, passwords, tokens, OTPs, or unredacted personal data.
- Faking submission success from a click, route change, or generic page load.
- Automatically resubmitting after a timeout without reconciliation.
- Dependency sprawl and premature microservices.
