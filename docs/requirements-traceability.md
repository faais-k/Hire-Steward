# JobPilot — Requirements Traceability and Source of Truth

**Audit date:** 2026-10-28  
**Status:** Audit baseline plus Foundation 1 implementation evidence. Only the narrow compensation-preference backend slice is implemented; remaining product requirements are not implied complete.

## Authority and status labels

- **Agreed requirement** — stated by the project owner in the current implementation brief or recorded planning decisions. It is not evidence of implementation.
- **Proposed architecture** — a documented design choice that remains open to deliberate review.
- **Verified fact** — directly observed in the current workspace or in an official technical source linked below.
- **Unverified assumption** — plausible, but not established by local evidence or current official material.
- **Outstanding decision** — requires an explicit choice before the dependent integration or policy is implemented.
- **Implemented and tested** — requires code plus recorded verification evidence. Only the Foundation 1 compensation-preference slice currently meets this status.

## Current baseline facts

| ID | Verified fact | Evidence |
|---|---|---|
| F-01 | The root is a new Git repository on an unborn `main` branch; `origin` is configured to the user-provided GitHub URL. There is no commit or push. Read-only remote lookup succeeded and advertised no `HEAD` or branch heads. | `git init --initial-branch=main`, `git remote -v`, `git status`, and `git ls-remote --symref origin HEAD refs/heads/main refs/heads/master` plus `git ls-remote --heads origin` on 2026-10-28. |
| F-02 | Backend code, root `pyproject.toml`/`uv.lock`, Alembic migration and unit/SQLite integration tests now exist. `frontend/` remains empty. There is no Compose file or CI workflow. | Workspace inventory and test run on 2026-10-28. |
| F-03 | Root `.gitignore` now excludes `reference-repos/`, `Chatgpt-chat/`, duplicate `docs (2).zip`, secrets, local environments, build output and local databases. Empty root `AGENTS.md` remains. | `git check-ignore -v` and file inspection on 2026-10-28. |
| F-04 | The pre-audit memory statement that the repository/source audit had not started was superseded by the completed Stage A audit and subsequent memory updates. | Earlier `docs/memory.md` baseline versus current `docs/memory.md`; current implementation/test status is recorded there. |
| F-05 | All eight reference repositories are local clean Git checkouts; their URLs and exact SHAs are in `reference-repo-audit.md`. | Read-only `git status`, `git remote`, `git rev-parse HEAD`, and recent log checks on 2026-10-28. |
| F-06 | The environment has Git 2.50.1, Python 3.10.11 as `python`, Python 3.12.10 through `py`, Node 24.14.1, npm 10.8.2, pnpm 11.25.0, uv 0.11.28, Docker 28.4.0, Compose v2.39.4 and `psql` 18.4. Bun is not on PATH. | Read-only version commands on 2026-10-28. These versions do not prove a database service is running or that project dependencies work. |
| F-07 | Current official source documentation distinguishes public listing reads from application submission credentials; details and links are in `job-discovery-sources.md`. No source terms review or live source request was performed. | Official Greenhouse, Lever and Ashby docs checked 2026-10-28; see that file. |
| F-08 | Gemini's current pricing documentation distinguishes free and paid tiers on content use, and Groq documents model/account-specific limits and response headers. No provider account, model or quota was inspected. | Official Gemini pricing and Groq rate-limit pages checked 2026-10-28; see `architecture-review.md`. |
| F-09 | Docker CLI is present but the Docker Desktop engine is unavailable; no PostgreSQL service is available for integration testing. | `docker info` on 2026-10-28 returned a missing `dockerDesktopLinuxEngine` pipe. |
| F-10 | Foundation 1 has a focused settings/evaluation API, exact-decimal persistence, migrations, audit rows, assessment snapshots, local Host/Origin checks, and a fail-closed public evidence trust boundary. It has no UI, trusted evidence ingestion/verifier, job model, submitted application model, source adapter, scheduler, or submission route. | Files under `backend/app/`, migrations `0001_compensation_preference` and `0002_compensation_evidence_trust_state`, ADR-0008/0009, and current test results recorded below. |

## Safety and product requirements

All rows below are **specified, not implemented** unless implementation evidence is added later.

| ID | Agreed requirement | Source of truth | Current status / verification needed |
|---|---|---|---|
| R-01 | Targeting criteria must be configurable in the application rather than hard-coded to a single role. | Current brief; PRD FR-02; ADR-0005 | Specified only. UI/API absent. Verify edits persist as versioned settings and are audited. |
| R-02 | Relevance must consider skills, work evidence, transferability and role fit; experience gaps or missing exact keywords alone do not reject a relevant role. | Current brief; PRD FR-05; `ai-spec.md` §7–8 | Specified only. Requires labeled evaluation set and regression tests. |
| R-03 | Classify mandatory vs preferred requirements. Every mandatory mismatch or unresolved requirement requires review before submission. | Current brief; PRD FR-05; `application-safety-policy.md` §3 | Specified only. Deterministic backend gate not implemented. |
| R-04 | Unknown sponsorship/work authorization is investigated or held for review; do not infer legal status from proxies. | Current brief; PRD FR-05; safety policy §3 | Specified only. Source extraction and user fact model absent. |
| R-05 | Unknown, contradictory, unverified, non-normalizable or threshold-straddling compensation is investigated/reviewed and is not silently treated as a pass or confirmed failure. | Current brief; PRD FR-05; safety policy §3; ADR-0007/0009 | The domain evaluator and public API review behavior are implemented/tested. Public observations always remain unverified; reliable source verification and uncertainty resolution are pending because trusted ingestion does not exist. |
| R-06 | Default the user-configurable minimum to INR 100,000/year; accept finite non-negative amounts including zero. Trusted annual compensation below the persisted preference fails the compensation gate; a threshold-meeting amount passes only that gate. A trusted unpaid role is always blocked independently of the preference. | Current brief; PRD FR-02/FR-05; safety policy §3; ADR-0007; ADR-0006 superseded | Setting persistence, exact decimal validation and pure deterministic evaluator are implemented. Publicly supplied observations cannot receive a trusted result and remain review-required. UI, trusted evidence ingestion, matching, dashboard, scheduling, preparation and final-submission wiring are pending. Only recurring INR/month × 12 is supported for trusted domain evidence; other units/currencies stay in review. |
| R-07 | A score can never override hard eligibility, confidence, source permission, user consent or other safety gates. | Current brief; PRD FR-05/FR-07; ADR-0005; safety policy §2 | Specified only. No policy engine exists. |
| R-08 | Never fabricate candidate facts, qualifications, experience, metrics, salary expectations or answers. Unsupported or unknown required answers block automatic submission. | Current brief; PRD FR-06; `ai-spec.md` §9; `rules.md` §5 | Specified only. No evidence store, output schema or validator exists. |
| R-09 | Do not submit a duplicate application to the same vacancy. Same-company/similar-role cooldown is 30 days, with only a verified new requisition eligible for normal re-review. | Current brief; PRD FR-04; safety policy §4; ADR-0003 | Specified only. No transactional dedupe/constraint exists. |
| R-10 | Treat external submission as non-idempotent; reconcile uncertain outcomes before any retry and require evidence before marking `APPLIED`. | Current brief; PRD FR-07; ADR-0003; safety policy §5–6 | Specified only. No state machine or simulated executor exists. |
| R-11 | Pause for required user input, permitted human CAPTCHA interaction, and material legal commitments; never bypass CAPTCHA or access controls. | Current brief; PRD FR-09; safety policy §7–10 | Specified only. No browser executor or handoff exists. Site-specific permission remains unverified. |
| R-12 | Use only source methods permitted for the relevant provider/site. A public listing endpoint does not imply application permission. | Current brief; `job-discovery-sources.md`; ADR-0003 | Specified only. No source has been activated. Terms and employer-specific capabilities remain to be reviewed. |
| R-13 | Job pages, resumes, documents, emails and model output are untrusted data, not policy instructions. | Current brief; `rules.md` §1/§5–6; `security-privacy.md` §3 | Specified only. No ingestion/UI/LLM path exists. |
| R-14 | API keys, credentials, session cookies, OTPs and secrets stay out of LLM prompts and ordinary logs; paid AI fallback is disabled without an explicitly authorized budget. | Current brief; PRD FR-12; `ai-spec.md` §3–4; `security-privacy.md` §2–6 | Specified only. No provider integration or secret store exists. |
| R-15 | No source/platform access-control, CAPTCHA, rate-limit or restriction evasion. | Current brief; `rules.md` §8; safety policy §7–8 | Specified only. JobSpy's proxy/impersonation patterns are explicitly excluded; see reference audit. |
| R-16 | Local-first single-user deployment is the starting target; remote exposure needs authentication and security review. | PRD §1/§6; ADR-0001; `security-privacy.md` §1/§8; ADR-0008 | Loopback trusted-host and same-origin checks are implemented for current writes. No authentication or remote deployment is implemented; local request guard is not remote authorization. |
| R-17 | PostgreSQL is the transactional system of record; FTS is the starting lexical search; pgvector is optional after model/privacy/quality/performance evaluation. | ADR-0002; `architecture.md` §4.4/§7 | Python models and migration exist; migration/API tests use SQLite. PostgreSQL server, migration test, FTS, and pgvector remain unimplemented/unverified. |
| R-18 | Provider integrations are behind typed interfaces; every model output is validated; no model performs a consequential action. Paid fallback requires explicit budget authorization. | ADR-0004; `ai-spec.md`; `rules.md` | Proposed architecture and agreed safety rule; no implementation or chosen model/provider. |
| R-19 | Source runs use checkpoints, bounded requests, idempotency and per-source isolation; failed/incomplete runs do not advance successful checkpoints. | PRD FR-03; `job-discovery-sources.md`; `data-model.md` | Specified only. No task store, scheduler or adapter exists. |
| R-20 | Candidate documents/facts retain immutable versions, provenance and explicit uncertainty; parse failures must not erase accepted facts. | PRD FR-01; `ai-spec.md` §5; `data-model.md` | Specified only. No file store, extractor, migrations or UI exists. |
| R-21 | Backups, restore, export/import and deletion must preserve integrity/provenance while excluding secrets by default. | PRD FR-11; `export-import.md`; `operations-deployment.md` | Specified only. No implementation or restore rehearsal exists. |
| R-22 | Structured logs/metrics must distinguish run health, eligibility, confidence and submission outcome without exposing sensitive values. | `observability-and-cost.md`; `security-privacy.md` | Proposed design only. No logger, metrics or redaction tests exist. |
| R-23 | Compensation preference changes are audited with old/new value, timestamp, actor and settings version; assessments/policy evaluations snapshot threshold currency/unit and conversion basis; changes never rewrite already-submitted facts, answers or outcomes. | Current brief; PRD; `data-model.md`; API spec; ADR-0007/0008 | Preference audit and compensation-assessment snapshot are implemented/tested. No application-record model or submission route exists; preserving submitted application rows is not exercised and remains a future acceptance gate. |
| R-24 | Caller-supplied or model-generated compensation status/amount/reference cannot establish trusted evidence. Unverified observations must be explicitly labeled as reported, review-required and ineligible to proceed; only a controlled internal verifier may establish trust after source and content provenance checks. | Current brief; API/security/data-model specs; ADR-0009 | Public schema rejects verification/decision claims; all public assessments are forced to `UNVERIFIED`/`REVIEW_REQUIRED`/`EVIDENCE_UNVERIFIED`, and `eligible_to_submit` is false. Migration marks legacy evidence unverified while preserving stored facts/threshold/outcome; effective API output is fail-closed. Trusted ingestion/verifier and actual source permissions remain unimplemented. |

## Proposed architecture, not yet agreed or proven

| Topic | Proposed default | Evidence and caveat |
|---|---|---|
| Application shape | Modular monolith with React/TypeScript, FastAPI/Pydantic, PostgreSQL, same-codebase worker, Docker Compose | Fits the single-user workload described in PRD; no spike or implementation yet. |
| Database search | PostgreSQL FTS first; pgvector only if retrieval evaluation justifies it | Avoids another service, but model, dimension, privacy, filters and recall/latency are not yet evaluated. |
| Background work | Small scheduler plus durable database task/run/lease records; no broker by default | Workload is only three scheduled runs/day and one submission at a time in the baseline; actual source count/run duration unknown. |
| Retrieval and ranking | Lexical + semantic lists; RRF candidate; no reranker by default; deterministic eligibility separate from score/confidence | `k=60`, weights and score bands are provisional; no labeled data or benchmark exists. |
| Browser automation | Source-specific permitted path, constrained domain allowlist, Playwright only if approved, otherwise manual handoff | No real source path has been reviewed for JobPilot. |
| File persistence | Controlled local file volume plus DB metadata/content hashes | Cross-store atomicity, encryption-at-rest, cleanup and backup protocol still need a concrete design. |

## Contradictions, gaps and resolutions

| Finding | Affected files | Resolution / next action |
|---|---|---|
| An earlier owner decision made INR 100,000/year non-overridable; the current owner decision restores user configurability while retaining an independent unpaid-role prohibition and deterministic gate. | PRD, safety policy, rules, ADR-0005, ADR-0006, ADR-0007, traceability, risk register, implementation plan and memory | ADR-0006 remains superseded history. ADR-0007 records the current preference. Foundation 1 implements only the backend setting and compensation-only assessment; UI and cross-product policy wiring remain pending. |
| Memory and README said implementation was not started; the owner later authorized Foundation 1. | `memory.md`, README, `implementation-plan.md` | Updated to distinguish the implemented compensation slice from the unimplemented remainder of Stage B and the product. |
| Root initially had no Git metadata and an empty `.gitignore`; reference clones and conversation exports must not enter the product baseline. | `.gitignore`, `AGENTS.md`, exported JSON | Root Git initialized on `main`, remote configured, and ignore rules verified for reference repos/export/archive/secrets/build artifacts. No commit or push has occurred; staged review comes first. |
| Local browser/API request protection was open. | `architecture.md`, `api-spec.md`, `security-privacy.md`, ADR-0008 | Current compensation writes require loopback `Host` and matching `Origin`; this is not authentication or remote authorization. |
| Stack/lockfile ownership was split between a proposed root and backend package. | `architecture.md`, `rules.md`, ADR-0008 | Python dependency ownership is now at root with one `uv.lock`; frontend lock and Node/container pins remain pending until those components exist. |
| Source documentation describes candidate APIs but cannot establish permission for JobPilot to aggregate boards or submit to employer accounts. | `job-discovery-sources.md`, `security-privacy.md` | Keep all sources disabled until per-source/per-employer access method, terms, credentials and allowed operations are reviewed. Current official API facts are recorded; no permission conclusion is made. |
| The staged compensation API previously treated caller-reported `PAID` and numeric salary as verified, allowing an arbitrary reference to support a `MEETS_THRESHOLD` result. | `backend/app/api/schemas.py`, `backend/app/services/assessments.py`, `backend/app/domain/compensation.py`, API/security/data model, ADR-0009 | Public requests now create only unverified observations and receive review-required outcomes; migration 0002 marks legacy records unverified; arbitrary references and AI claims do not confer trust. A complete source verifier remains a prerequisite before any trusted assessment path. |

## Implemented and tested status

- **Product code:** Foundation 1 compensation backend exists; frontend, source/job/application workflows, AI integration and submission are absent.
- **Unit/integration tests:** Current trust-boundary verification results are recorded in `docs/memory.md` and `docs/testing-evaluation.md`; tests use deterministic policy and Alembic/API/transaction integration against in-memory SQLite.
- **PostgreSQL tests:** Not run; Docker engine/PostgreSQL service is unavailable. SQLite does not verify PostgreSQL locking or concurrency behavior.
- **Reference repositories:** Their tests and CI were inspected but not run.
- **Stage A documents:** This audit, traceability, architecture review, risk register and implementation plan are documentation artifacts; they are not product functionality or test evidence.
- **Live job access, account authentication, AI providers, browser automation and application submission:** Not implemented and not exercised.
