# JobPilot — Project Requirements Document (PRD)

**Status:** Draft baseline for implementation planning  
**Owner:** Product owner / project maintainer  
**Last reviewed:** 2026-10-27  
**Normative language:** MUST = mandatory; SHOULD = recommended; MAY = optional.

## 1. Executive summary

JobPilot is a local-first, user-controlled job discovery and application workflow platform. It discovers relevant jobs from explicitly configured and permitted sources, normalizes job information, compares requirements against evidence-backed candidate facts, explains the match, prepares tailored application materials, and can submit an application only when the source supports a permitted submission path and every policy gate passes.

The product is not a blind bulk-apply bot. It is an evidence-led job search workspace with controlled automation, transparent scoring, duplicate prevention, auditable outcomes, secure handling of candidate information, and a clear handoff when a human decision or site interaction is required.

## 2. Problem statement

Job searches require repeated work across fragmented career pages: finding new vacancies, checking role and experience fit, evaluating sponsorship and compensation, tailoring resumes, answering repeated questions, avoiding duplicate applications, and tracking submission outcomes. Manual processes are slow and inconsistent. Uncontrolled automation creates different risks: false claims, duplicate applications, violations of site rules, untracked submissions, data exposure, and wasted model/API quota.

JobPilot should reduce repetitive effort while preserving the user's control over facts, commitments, identity data, and external actions.

## 3. Target user and non-goals

### 3.1 Primary user

A single job seeker using their own machine initially. The system may hold a structured candidate profile, resumes, certificates, work evidence, reusable answers explicitly approved for reuse, application history, and preferences. The first product should optimize the workflow for one local user, not enterprise multi-tenancy.

The app must allow targeting settings to be edited in the UI. The initial profile may be prefilled with known preferences, but neither role titles nor location assumptions may be hard-coded into ranking logic.

### 3.2 Configurable profile defaults

These may be offered as editable initial values, not immutable rules:

- Target roles: AI Engineer / AI Developer.
- Excluded role categories: ML Engineer, Data Scientist, Data Analyst, unless the user changes them.
- Work arrangements: remote, work-from-home, and on-site roles in preferred regions.
- International roles: assess work authorization and employer visa sponsorship explicitly.
- Skill-first matching: a shortfall in years of experience or some listed skills must not independently reject an otherwise relevant role.
- Minimum compensation preference: configurable in application settings, defaulting to INR 100,000 per year. The user may choose any finite, non-negative INR amount, including zero. This preference is not an override of the independent prohibition on applying to unpaid roles. Changes are intentional and audited.

The user's target settings are data, not source code constants. Global safety controls—no fabrication, no bypassing controls, and no unapproved legal commitments—must not be overridden by the model.

### 3.3 Out of scope for the initial release

- Multi-user SaaS, billing, teams, roles, and tenant administration.
- Guaranteed coverage of every job board or employer ATS.
- CAPTCHA bypass, access-control evasion, fingerprint spoofing, proxy rotation, or account rotation to evade limits.
- Bulk indiscriminate applications or mass generic recruiter outreach.
- Autonomous acceptance of bonds or materially binding declarations.
- Autonomous fabrication or inference of candidate facts.
- A separate vector database, distributed queue, Kubernetes, or microservices before load tests justify them.
- Unattended submission to a site when permission, required fields, result, or policy state is uncertain.

## 4. Product outcomes and success measures

Initial success is measured by quality and reliability, not raw application count.

| Outcome | Initial measure / target | Status |
|---|---|---|
| New-job freshness | Each permitted source is checked on schedule; failures are visible and do not advance its checkpoint | Acceptance target |
| Duplicate control | Zero known duplicate submissions in automated tests and pilot | Release gate |
| Fact integrity | Zero unsupported claims in generated application answers in the gold test set | Release gate |
| Safety | Zero submissions bypassing an unresolved hard gate in tests | Release gate |
| Auditability | Every submission attempt has a unique ID, captured job snapshot, document versions, exact answers, and result evidence | Release gate |
| Resumability | Crash/restart does not silently repeat a submission or lose an in-progress application | Release gate |
| Efficiency | Measure discovery-to-review time saved and user correction rate in a pilot | Establish baseline first |
| Matching quality | Evaluate precision@k, recall@k, ranking stability, and false-positive rate on labeled jobs | Establish dataset first |
| Cost control | Provider, model, task, token, latency, error, fallback, and cost telemetry available for every AI call where provider supports it | Release gate |
| Portability | Export can be validated and imported into a clean instance without secrets | Release gate for portability phase |

Do not claim numerical quality thresholds until a labeled dataset and baseline exist. Phase-specific minimums are defined in `testing-evaluation.md`.

## 5. Functional requirements

### FR-01 — Candidate evidence workspace

- Import and track resumes, cover letters, certificates, work reports, project documents, employment history, and other user-selected evidence.
- Support PDF, DOCX, TXT, Markdown, CSV, and XLSX at minimum; images and OCR are optional and require language/quality testing.
- Extract structured facts with provenance: source file ID, content hash, document version, page/section when available, extraction method/model, timestamp, verification state, and sensitivity.
- Preserve the original document and raw extraction. A failed, empty, or low-confidence parse MUST NOT erase a previously accepted fact or profile field.
- Detect file addition, modification, and removal at startup and before each scheduled run. Reprocess only changed artifacts.
- Represent contradictions and uncertainty; request resolution instead of silently choosing one value.
- Freeze the precise candidate evidence/document versions used in a submitted application.

### FR-02 — Targeting and policy settings

Provide editable settings for target roles, excluded categories, skills, seniority, location, work arrangement, work authorization/sponsorship, minimum compensation, contract type, experience preference, source allowlist, schedule, daily limits, auto-submit level, email limit, and data sharing permissions. Explain how each setting affects results. The minimum compensation preference defaults to INR 100,000 per year and is user-configurable, including zero. Label it clearly as INR per year and explain any conversion assumptions used to compare job compensation. Persist and audit changes. The unpaid-role prohibition remains independent and non-configurable.

### FR-03 — Job discovery

- On first activation, search jobs published within the previous 14 days, subject to source support.
- Run at 10:00, 17:00, and 22:00 Asia/Kolkata by default.
- On later runs, query from each source's last successful checkpoint/backfill window where the source supports it. Failed sources must not advance checkpoints.
- Prevent overlapping runs for the same source; isolate source errors so one failure does not halt all healthy sources.
- Track source access method, relevant terms/permissions, pagination, rate limits, failure history, and checkpoint state.
- Store original URL, canonical URL, source, source identifier, observed timestamp, published timestamp (if provided), job snapshot/hash, and raw/normalized data.

### FR-04 — Normalization and deduplication

Normalize company names, title variants, URL parameters, ATS requisition IDs, locations, job type, currency, compensation period, publication dates, and description content. Deduplicate by strong identity signals first (source + requisition ID / canonical vacancy ID), then conservative composite signals. Never treat similar titles alone as proof that two requisitions are identical.

Hard-block an exact known vacancy that has already been applied to. Same-company/similar-role cooldown is 30 days; a genuinely new verified requisition can be reviewed, but a repost or duplicate must not bypass the cooldown.

### FR-05 — Eligibility and matching

- Parse explicit required and preferred qualifications separately.
- Identify candidate-supported evidence for requirements and show the evidence location.
- Treat states as `met`, `not_met`, `unknown`, `conflicting`, or `not_applicable` rather than forcing a binary answer.
- Every mandatory-qualification mismatch or unresolved mandatory field enters review; it is not eligible for automatic submission.
- A confirmed experience gap alone is not a rejection. Skill relevance, demonstrated work, transferable skills, seniority and user settings all matter.
- Unknown sponsorship triggers investigation/review, not automatic rejection. Confirmed legal/work-authorization ineligibility may block application.
- Never apply to unpaid work, regardless of the configured minimum. Block compensation reliably established below the persisted user minimum. Compensation that is unknown, contradictory, not defensibly annualizable, or a range that crosses the minimum requires investigation/review; do not infer a pass or failure. A range wholly below the minimum fails this compensation gate; one wholly above passes this gate only. Convert units/currencies only on a defensible, recorded basis.
- The backend loads the persisted user setting and applies the same deterministic compensation gate during matching/eligibility, scheduled reassessment, dashboard explanation, application preparation, and the final submission check. Frontend checks and AI output are not authoritative. AI may extract and explain evidence but cannot change the setting or decision.
- Keep score and confidence separate. Low confidence prevents automation even if the match score is high.
- Show a human-readable match explanation and negative evidence.

Proposed initial score weights (unvalidated): role alignment 25, required technical skills 20, verified project/work evidence 15, experience fit 15, seniority 10, location/work arrangement 10, compensation/contract preferences 5. These sum to 100 but are not scientifically calibrated. Use them only behind the evaluation framework and version them. Policy gates always outrank the score.

### FR-06 — Document and answer preparation

- Tailor resumes conservatively; preserve structure and factual claims; only make changes supported by verified evidence.
- Generate a cover letter only when required or likely useful; avoid generic filler.
- Answer application questions using verified facts or an explicitly approved reusable answer bank.
- One-time answers are not reusable unless the user separately approves reuse.
- Semantic reuse is allowed only when the prior answer's meaning and context are equivalent; show source and confidence.
- Unknown, contradictory, sensitive, or high-stakes answers request user input. The system can continue preparing other jobs.
- Never make unsupported claims, invent dates/metrics, or auto-answer declarations by guessing.

### FR-07 — Submission workflow

- Initial release supports one active external application submission at a time. Discovery and preparation may run concurrently within bounded limits.
- Submit only through a verified permitted API or an allowed browser workflow.
- A successful button click or HTTP request is not proof of application success.
- Capture confirmation evidence, source identifiers, result page or permitted confirmation details, and timestamp.
- If outcome is uncertain, reconcile by checking the portal/confirmation evidence before any retry. Never mark `APPLIED` without evidence.
- If CAPTCHA or a human-only task appears, pause the affected application, preserve state, request user action if permitted, and continue unrelated discovery/preparation.
- If the site prohibits automation, switch to manual handoff mode.

### FR-08 — Recruiter email

If the posting explicitly specifies an application email address and the message is an application channel, sending may be automated after all gates pass. A general contact address or ambiguous purpose yields a draft only. Default cap: 5 application emails/day, configurable. Record exact recipient, message, attachments and versions, timestamp, provider message ID if available, and result. Reconcile an uncertain send before retry. No bulk generic emailing or limit evasion.

Gmail API authorization is separate from any connector used by ChatGPT. Use OAuth and the narrowest feasible scope. Check current Google verification requirements before a public release; the `gmail.send` scope is classified as sensitive in Google's scope documentation.

### FR-09 — Legal commitments and declarations

Classify application statements and declarations. Pause for human review when they contain a bond, repayment obligation, restrictive covenant, material legal commitment, unusual financial obligation, or ambiguous material consequences. Routine declarations may proceed only when the underlying facts are verified and the user explicitly pre-approved that category. Do not accept a bond or materially binding commitment without explicit approval.

### FR-10 — Dashboard and history

Show jobs and filters; score and confidence; eligibility gates; evidence; source and posting date; salary/sponsorship uncertainty; proposed resume/answers; application status; exact submission versions; source health; scheduled run history; pending questions; provider usage, quota, cost and latency; errors and recovery actions. A user must be able to reject, snooze, edit, approve, retry a safe non-submission task, or move an application to manual handling.

### FR-11 — Export and import

Support a versioned portable export of selected history and evidence, with manifest, checksums, provenance and schema version. Exclude API keys, credentials, cookies, access tokens, refresh tokens and OTPs by default. Sensitive personal fields require explicit opt-in with a clear warning. Import must validate integrity and schema, stage data before committing, report conflicts, and never overwrite live state silently.

### FR-12 — AI provider usage

Use a provider-neutral model router with task-specific candidates, user privacy preferences, quota and budget awareness, fallbacks, and telemetry. Paid fallback is disabled until the user explicitly configures and authorizes a budget. Do not rotate keys/accounts to evade limits. Local models and local embeddings are optional future paths.

## 6. Non-functional requirements

### Reliability

- Idempotent internal operations and explicit state transitions.
- Bounded retries with exponential backoff and jitter for retryable errors only.
- No automatic retry of an uncertain external side effect before reconciliation.
- Migrations tested in both clean and upgrade paths.
- Backup/restore documented and tested.

### Security and privacy

- Localhost-only by default, no public listener without explicit deployment configuration and authentication.
- Candidate documents, job descriptions, emails, and web content are untrusted input, never policy instructions.
- Encrypt secrets using an OS credential store or an encrypted local vault; do not log or pass secrets into LLM prompts.
- Redact sensitive values from logs, traces, screenshots, errors, and exports.
- Data minimization, user-visible deletion/export, retention settings, and explicit provider data-sharing consent.

### Performance and scale

- Initial workload: one user, bounded source calls, small-to-medium evidence library, and a maximum of five application submissions/day by default.
- Use PostgreSQL for transactional records, full-text search, and pgvector where benchmarked useful; do not add a second database without evidence.
- Background work must not hold web requests open for long-running extraction or source crawls.
- Establish query latency, run duration, memory, and cost baselines before setting hard performance SLAs.
- Design for a future worker process and external database/object store without forcing distributed infrastructure into the first release.

### Accessibility and usability

- Keyboard navigation, visible focus, semantic form labels, accessible contrast, and clear error summaries.
- State and policy reasons must be understandable without reading raw logs.

## 7. Initial limits and proposed defaults

| Setting | Initial default | Why / caveat |
|---|---|---|
| Deployment | Local Docker Compose | Simplest operational model for one user |
| Schedule | 10:00, 17:00, 22:00 Asia/Kolkata | Agreed starting schedule; editable |
| Initial historical search | Previous 14 days | Source publication dates may be missing or unreliable |
| Submission concurrency | 1 external submission | Limits race conditions and makes reconciliation easier |
| Daily application cap | 5 | Configurable safety limit |
| Daily application email cap | 5 | Configurable; only explicit application-channel addresses |
| Similar-role cooldown | 30 days | A verified new requisition is treated separately |
| Minimum annual compensation preference | INR 100,000 per year | User-configurable to any finite, non-negative INR amount, including zero. Unpaid roles remain prohibited. Compare only with defensible annualized evidence. |
| Reranker | Off until benchmarked | Avoid unnecessary model cost/complexity |
| Message queue | None initially | Add only when single worker/background task mechanisms are inadequate |

## 8. Product risks

1. Source access terms may restrict discovery or automated application.
2. Job data may omit salary, sponsorship, dates, or requisition identifiers.
3. LLM extraction/matching can be inconsistent or hallucinate.
4. External forms can change and produce ambiguous outcomes.
5. Free API quotas and terms can change without notice.
6. Sensitive candidate data could leak through logs, model calls or exports.
7. Overly strict rules may reduce recall; overly loose rules increase false positives.
8. Uncalibrated weights can produce misleading scores.

Mitigations live in the source registry, strict policy gates, provenance, human handoffs, evaluation suite, usage dashboard, redaction, and phase release gates.

## 9. Acceptance criteria for MVP

MVP is accepted only when all of the following work end-to-end in a dry-run environment:

- Candidate documents are versioned, parsed, and associated with evidence-backed facts; parser failure does not erase prior data.
- Target preferences can be edited without a code change.
- At least one permitted job source is ingested with checkpointing and failure-safe behavior.
- Duplicate vacancy detection blocks a repeated submission candidate.
- Unknown mandatory facts, compensation, sponsorship or declarations create the correct review/handoff state.
- Scoring is deterministic for a fixed input, has a version, and displays reasons and confidence separately.
- Resume/answers contain only grounded facts, with the supporting evidence traceable.
- A submission simulation covers pre-submit crash, post-submit uncertainty, and reconciliation without a duplicate attempt.
- Logs and exported packages contain no secrets in the adversarial test suite.
- Backups can be restored into a clean environment.
- Release gates in `testing-evaluation.md` are passed and documented.

### Compensation policy acceptance criteria (pending implementation)

These are required cases for future deterministic policy tests and end-to-end acceptance. They have not been implemented or run.

| Case | Required result |
|---|---|
| New profile/default | Show and persist `INR 100,000 per year`; label currency and annualized unit. |
| User sets INR 50,000/year; reliable annual salary is INR 60,000 | Compensation gate passes; this alone does not grant overall eligibility. |
| User sets INR 150,000/year; reliable annual salary is INR 120,000 | Compensation gate blocks application. |
| Confirmed unpaid role at any configured minimum, including zero | Always ineligible for application. |
| Salary is unknown | Investigation/review; neither assumed pass nor assumed failure. |
| Reliable salary range lies entirely below the configured minimum | Compensation gate blocks application. |
| Reliable salary range lies entirely above the configured minimum | Compensation gate passes, subject to all other gates. |
| Reliable salary range crosses the configured minimum | Investigation/review unless reliable additional evidence resolves the range. |
| Explicit recurring monthly salary in a known currency | Annualize at monthly amount × 12, record the assumption and source evidence; do not represent it as guaranteed total contract earnings. |
| Hourly compensation without reliable working hours/year | Do not annualize; require investigation/review. |
| Negative, malformed, NaN, infinite, or otherwise invalid setting | Reject. Accept finite non-negative amounts, including zero; use exact decimal arithmetic for decisions. |
| Minimum changes after a job assessment | Preserve the assessment's threshold snapshot; any reassessment uses the new persisted setting. Do not silently rewrite a prior assessment. |
| Historical application was assessed/submitted under an earlier minimum | Retain the threshold/currency/unit and conversion basis used at that time; do not rewrite submitted facts, answers, or outcomes after a setting change. |
| AI output asks to lower the minimum or mark below-minimum compensation eligible | Ignore the attempt; backend deterministic evaluation uses the persisted setting and blocks as applicable. |

For currencies other than INR, require a reliable exchange rate with source, timestamp and basis; otherwise review. Daily, hourly and contract compensation can be annualized only with explicit, reliable work-time/duration evidence. Never invent hours, work days, contract duration or exchange rates.
