# JobPilot — Architecture Review

**Review date:** 2026-10-28  
**Scope:** Validate the proposed local-first architecture against the documented single-user workload, safety rules, reliability requirements and observed workspace.  
**Conclusion:** The modular-monolith direction remains justified. Foundation 1 now proves a small FastAPI/SQLAlchemy/Alembic slice with exact decimal settings, transactional audit, assessment snapshots, and local-origin checks. The broader architecture, PostgreSQL behavior, source access and all external actions remain unimplemented or unverified.

## Verified state and assumptions

As of 2026-10-28, the root is a new Git repository on unborn `main`, with `origin` set to the user-provided GitHub URL; no commit or push exists. `.gitignore` excludes `reference-repos/`, the conversation export, local secrets, virtual environments, build output and databases. A root `pyproject.toml`/`uv.lock`, backend code, one Alembic migration and unit/SQLite integration tests now exist. `frontend/` remains empty; there is no Compose file, CI, PostgreSQL service or full product implementation. Python 3.12.10 was used for the test environment. Docker CLI is present but its engine is unavailable; the PostgreSQL service was not started. PostgreSQL production behavior therefore remains unverified.

The workload assumptions in the PRD are one local user, three scheduled runs per day, small-to-medium evidence data, up to five applications/day, one active external submission and a modest number of configured sources. These are proposed starting assumptions, not measured traffic. The service boundaries should be reconsidered only when measured workload or a new product requirement changes them.

## Component boundaries and dependency direction

Recommended direction:

```text
React UI → HTTP/API schemas → application services → domain and deterministic policies
                                      ↓                         ↑
                             persistence adapters       AI/source/browser interfaces
                                      ↓                         ↓
                                  PostgreSQL          approved external systems
```

The API and worker can be separate processes from one codebase and one release. Route handlers should validate transport input and call use cases; eligibility, compensation, deduplication, consent, state transitions and authorization should live in deterministic backend policy/domain code. Source, file, AI, email and browser code should depend on narrow typed interfaces. The UI displays server decisions and can never serve as the final enforcement point.

The compensation slice demonstrates typed API validation, service/domain separation, persistence adapters and deterministic policy code. It uses the root `uv.lock`; the rest of the proposed folder tree remains a design sketch and should not be scaffolded wholesale.

## Major decisions and validation

| Decision | Assessment and rationale | Alternatives and trade-offs | Failure mode / evidence that should change it |
|---|---|---|---|
| **Modular monolith, one codebase** | Recommended. The first user is local and single-user; state correctness and safe external effects matter more than independent horizontal scaling. API and worker processes isolate long work without introducing a service network. | Microservices add deployment, auth, tracing and consistency surfaces. A single process is simpler but couples long worker failures to API availability. | Split a worker/source only after sustained backlog, resource contention, independent scaling needs or a failure-isolation requirement is measured. Multi-user SaaS needs a new architecture review. |
| **PostgreSQL as the system of record** | Recommended for transactions, constraints, durable state, audit, FTS and one primary structured-data backup boundary. ADR-0002 is consistent with the requirements. | SQLite is simpler for a single user but has weaker operational headroom and concurrent-work patterns for this design. A second database creates synchronization and recovery complexity. | Revisit if representative query plans, concurrent write patterns, offline packaging or measured operational constraints demonstrate PostgreSQL is the wrong fit. No benchmark currently exists. |
| **PostgreSQL FTS first; pgvector optional** | Use relational filters and FTS as a lexical baseline. Add pgvector only after selecting an embedding model, obtaining data-sharing approval, building a labeled set and testing filtered retrieval. RRF is a candidate fusion method; `k=60` is not a validated constant. | Exact vector search is simpler for a small corpus. Approximate indexes reduce latency at a recall/maintenance cost. A separate vector store adds another backup, access-control and consistency boundary. | Add vector indexes only when measured relevance/latency warrants them. Change model/index if recall, filtering, dimension compatibility or latency fails a documented target. No target or dataset exists yet. |
| **Durable DB task/run records; no broker initially** | A small scheduler plus database records, leases and source checkpoints matches the stated three runs/day and provides restart visibility. A separate worker process should claim bounded work. | In-process background tasks are simplest but can lose work on restart. A broker adds operations and delivery semantics; use it only when DB claiming/leases are demonstrably insufficient. | Add a broker only for measured sustained queue age, throughput, worker pool isolation or lease contention. Database outages must stop external side effects because they cannot be safely audited without durable state. |
| **Provider-neutral AI interface** | Required by provider volatility and privacy/cost rules. Task-specific schemas, privacy class, timeout, budget, model ID and fallback reason must be explicit. Do not build a general autonomous agent framework. | One provider is less code but more lock-in; local models reduce external sharing but need device-specific quality/footprint evaluation. A generic agent framework widens permissions and debugging scope. | Add a provider/model only after task evaluation, exact tier/data terms, quota, schema support, and budget behavior are recorded. No provider/account is selected. |
| **Local evidence volume plus relational metadata** | Fits local-first data ownership and preserves original files with content hashes and versions. Store metadata, provenance and accepted facts in PostgreSQL. | Storing all blobs in the DB simplifies atomic backup but increases database and migration burden. Object storage is future work for remote use. | Revisit when file volume, backup time or remote access requires an object store. First specify staged writes, DB/file reconciliation, permissions, encryption and orphan cleanup. |
| **Source-specific adapters and manual handoff by default** | Capability records must cover exact operation, method, terms review date, limits and auth. Read and submit capabilities are separate. Manual handoff is the safe fallback when permission or form state is uncertain. | Generic scraping/browser automation has wider drift and compliance surface. Aggregators simplify discovery but add another provider dependency and data-use policy. | Enable a source only after current source terms, employer configuration, auth, fields, limits and permitted method are reviewed. No source is approved by this audit. |
| **Constrained Playwright executor only after policy review** | A narrow, site-specific executor can fill approved fields from an immutable plan; it must not accept model-chosen URLs/scripts. Manual workflow is preferable when allowed automation is unclear. | Direct APIs are more stable when officially authorized but may require employer credentials. A generic browser agent is flexible but unsafe and brittle. | Disable a browser adapter after CAPTCHA/access-policy warnings, schema drift, unexpected field mapping or ambiguous confirmation. Do not add stealth, proxies or evasion. |

## Data model, constraints and migrations

The proposed model has strong domain coverage: immutable candidate-document versions and facts, fact-evidence links, source capabilities/checkpoints, source observations and job snapshots, immutable assessments, application/attempt records, consent/policy evaluations, provider calls and audit events. It distinguishes unknown/conflicting data and captures provenance. This is a sound conceptual direction.

Before writing migrations, make these database invariants concrete:

- Stable unique identity for a source posting and idempotency keys; identity strength must be source-specific.
- At most one active or unresolved external attempt for a vacancy, protected by transaction/locking and database constraints rather than an in-memory check.
- Daily limits and single-active-submission limits checked transactionally across concurrent tasks.
- An application attempt, frozen plan/hash, policy evaluation, consent reference and audit event committed consistently before network side effects.
- State transitions validated by one service and constrained against invalid terminal transitions. `APPLIED` requires source-specific evidence.
- Version columns or locking for profile/settings, fact verification, answer edits and consent revocation races.
- UTC event timestamps plus an explicit configured timezone/day boundary for local schedules and daily caps.
- A file-store protocol for staged writes, hash verification, crash recovery and database references. A DB transaction cannot atomically commit filesystem bytes.
- Retention and deletion behavior that distinguishes active evidence from artifacts needed for prior applications and uncertain-outcome reconciliation.

The first schema now has three focused tables and an initial Alembic migration, with a clean-install SQLite migration/API test. Its index reflects assessment history by job reference and creation time; query-plan behavior is not measured. PostgreSQL migration, numeric behavior, locking and concurrent update behavior still require integration testing against the supported production database. The broader application schema remains conceptual.

## Source adapters and compliance boundary

The source registry and adapter model are justified, but no source can yet be marked `VERIFIED_READ_ONLY` or `VERIFIED_READ_AND_SUBMIT` for JobPilot. Current official docs checked on 2026-10-28 show:

- [Greenhouse Job Board API](https://docs.greenhouse.io/job-board) documents unauthenticated GETs for public board data; application POST requires an employer-issued Basic Auth key and is described as a server-side custom career-form workflow.
- [Lever Postings API](https://github.com/lever/postings-api) documents published posting reads and application POST. Application creation is rate limited, and its POST requires a key generated by that employer's Super Admin.
- [Ashby `jobPosting.list`](https://developers.ashbyhq.com/reference/jobpostinglist) returns published postings by default. Its [custom careers page guide](https://developers.ashbyhq.com/docs/creating-a-custom-careers-page) describes posting details and application submission endpoints for an organization's jobs.

These documents establish technical capabilities, not blanket permission for a third party to aggregate or submit to every employer board. Site terms, provider-specific conditions, employer configuration, authentication and actual request limits remain unverified. Source status must stay disabled until the exact source/operation is reviewed. No live board request was made.

## Document ingestion, retrieval and ranking

The versioned evidence flow is appropriate: preserve original bytes, content hash and parser output; create candidate facts with source spans, confidence and verification; never overwrite accepted facts on empty/failed extraction; reprocess only changed versions. File format support, OCR, extraction quality, resource limits and malware handling remain unproven and need synthetic/fixture spikes before accepting real personal documents.

Use deterministic filtering and evidence-linked retrieval. FTS is a low-cost baseline. Semantic embeddings can improve recall for paraphrases but introduce model/data-sharing, versioning and migration concerns; never compare incompatible vector spaces. Score, confidence and gate outcomes must remain separate. A missing keyword or retrieval hit is not proof that a person has or lacks a qualification. Initial weights, thresholds and score bands remain uncalibrated and cannot authorize submission.

## Provider routing and cost controls

Define bounded tasks with strict schemas, maximum input/output, task privacy class, timeout, retry budget, candidate model set and evaluation fixtures. Validate every response before domain code sees it. Keep secret material outside prompts and ordinary logs. Fallback must be a new traceable provider call and must pass privacy and budget checks again.

Official provider references checked 2026-10-28:

- [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing) currently distinguishes free and paid tiers on whether content is used to improve products; the precise model/tier terms change and must be rechecked when configured. This supports the conservative rule: do not send private candidate material to a free tier unless the user explicitly approves that specific data sharing and it is necessary.
- [Gemini API additional terms](https://ai.google.dev/gemini-api/terms) describe submitted content and generated responses for unpaid services. Do not infer privacy from “free.”
- [Groq rate limits](https://console.groq.com/docs/rate-limits) are model/account dependent and expose rate-limit information in headers; current organization limits require the user's account and were not inspected.

No provider, model, quota, current account limit or cost estimate was selected or verified. Paid fallback remains disabled unless the user sets and authorizes an explicit budget. Do not rotate accounts or keys to evade quotas.

## Scheduling, retries and idempotency

Use timezone-aware scheduling for `Asia/Kolkata`; record `scheduled_for`, run IDs, config snapshots, per-source checkpoint before/after, completeness and error state. A per-source lease prevents overlapping checkpoint writes. Persist fetched observations as work proceeds, but advance a watermark only when that source's completeness rule passes. Isolate source failures.

Retry safe reads and compute operations with bounded attempts, backoff, deadlines and cancellation. Do not retry an uncertain application or email side effect. Worker restart must resume from durable state, not blindly replay a submission. There is no selected scheduler library, task schema or concurrency implementation yet.

## Authentication, authorization and secrets

The current compensation write routes require matching loopback `Host` and `Origin` values, reject other hosts, and enable no permissive CORS. This is a narrow local browser request guard recorded in ADR-0008, not authentication and not a complete DNS-rebinding defense. Remote hosting remains out of scope until authentication, authorization, TLS, firewall, secret management and restore controls are implemented and tested.

Use an OS credential store or encrypted vault for durable secrets. Environment-variable injection may be useful at runtime but does not constitute a durable secret-management design. Do not copy JobNavigator's plaintext key handling or any reference repo's permissive auth defaults.

## Browser submission and reconciliation

The proposed immutable `SubmissionPlan` plus fresh deterministic rechecks is appropriate. Persist the plan, hashes, exact documents/answers, policy evaluation, consent scope and attempt ID before the external call. Permit only one active external submission initially. A click, HTTP 200 or page transition is not proof of success. Use source-specific confirmation evidence; otherwise mark `CONFIRMATION_UNKNOWN`, reconcile through a permitted authoritative signal or user review, and block retry until the old attempt is proven unsuccessful and all gates are fresh.

Start with a simulated ATS and dry-run executor. The current brief does not authorize live applications during the audit; none were started. Live submission remains disabled until all safety, permission, duplicate, recovery and consent gates pass and the user explicitly enables the source/mode.

## Backups, recovery and observability

The docs correctly identify database state plus evidence files as a joint recovery set, and require export/import manifests, checksums and secret exclusion. Still missing: a consistent snapshot protocol across database and filesystem; encryption/key recovery procedure; storage permission baseline; backup retention; clean-restore evidence; and consistency checks for missing/orphaned files. A successful checksum is not proof that an import is trustworthy.

The correlation IDs, structured logs, audit records, source health and provider usage fields in `observability-and-cost.md` are appropriate. Keep operational logs separate from durable business events. Unknown provider cost/usage must remain unknown, not be estimated as actual. No metrics backend is justified at this scale; a small local dashboard can consume database run/usage records first.

## Open decisions before the dependent work

1. Review the staged baseline before any commit; root Git/ignore are configured but there is no commit yet.
2. Add frontend lock ownership and exact Node/container pins only when frontend/Compose work starts.
3. Complete the local threat model before adding more state-changing UI/API paths; the current origin check does not authorize remote access.
4. Verify a dedicated PostgreSQL migration/concurrency test path; current tests use SQLite because the Docker engine/database is unavailable.
5. Choose the first source only after per-source/per-operation terms and capability review; until then use fixtures/manual handoff.
6. Select document extraction libraries only after maintenance/license/security review and synthetic fixture evaluation.
7. Select an AI provider/model only after privacy/data-use, structured-output, quota and budget review. No paid fallback without explicit user budget authorization.
8. Define DB constraints, file-store recovery protocol, timezone/day-boundary rules and source-specific confirmation evidence before their respective migrations or side-effect paths.

## Recommended implementation direction

Continue in small stages: review the staged repository baseline; verify the migration against PostgreSQL; complete general foundation readiness/logging/Compose/CI; then implement evidence/provenance and a disabled-by-default, verified read-only source; then connect deterministic policy and evaluation; then grounded drafting; then simulated submission and reconciliation. Keep live application submission and recruiter email disabled.
