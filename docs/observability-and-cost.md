# JobPilot — Observability, Usage, and Cost Controls

**Status:** Proposed operational specification.

## 1. Goals

Make every run's health and cost understandable without exposing candidate secrets. Enable debugging and quality improvement with correlation IDs, source state, model/provider telemetry and immutable application history. Do not optimize costs by removing essential safety gates.

## 2. Correlation model

Use stable IDs across boundaries:

- `scheduled_run_id`: one schedule/manual discovery cycle.
- `source_run_id`: one source's work within a run.
- `task_id`: one background task.
- `job_id` and `job_snapshot_id`: canonical job and exact version assessed.
- `assessment_id`: immutable match/policy evaluation.
- `application_id`: logical application history.
- `application_attempt_id`: each external side-effect attempt.
- `provider_call_id`: each model/API call.
- `correlation_id`: safe trace across related events.

Propagate IDs in structured logs, DB records and UI diagnostics. Do not put candidate name/email/phone or secrets into correlation IDs.

## 3. Structured logs

Suggested fields: timestamp, level, service, app version, event, correlation ID, run/task IDs, source ID, safe subject ID, duration, result code, retry count, policy/prompt/model version and redacted attributes.

Never log unredacted candidate documents, API keys, bearer headers, cookies, OTPs, credentials, raw sensitive answers, or full browser page content. Provider error bodies may echo prompts, so sanitize before storage.

Separate operational logs from auditable business events. A log line is not an authoritative record of application state; transactional state and audit events are.

## 4. Metrics

### Scheduler and source

- scheduled runs started/completed/failed;
- source run success ratio and duration p50/p95;
- last successful checkpoint age and estimated backfill gap;
- listings fetched/new/updated/deduplicated;
- source rate-limit events, 401/403 and schema failures;
- queue/backlog age and worker heartbeat.

### Document processing

- documents processed by type;
- extraction success/failure and field-level validation rates;
- parser/OCR duration;
- changed files versus no-op scans;
- unresolved fact conflicts and user correction rate.

### Matching and preparation

- score distribution, confidence distribution, gate reasons;
- mandatory requirement classifications and review rate;
- jobs that match user preferences versus jobs actually eligible;
- percentage of claims grounded to valid evidence;
- user edits/corrections to generated documents/answers.

Do not expose the aggregate “match score” as predicted hiring probability.

### Applications

- submissions by state and source;
- `CONFIRMATION_UNKNOWN` count/age;
- time from uncertain outcome to reconciliation;
- false success transition count (target zero);
- duplicate blocked count and any duplicate incident;
- daily application/email caps and rejected attempts;
- manual handoffs and CAPTCHA/source drift events.

### AI providers

- provider/model/task, request count, latency, input/output tokens (if supported), errors, rate limits, fallback count, estimated/actual cost and budget remaining;
- quota header snapshots when the provider supplies them;
- data category and privacy decision without recording the underlying sensitive content;
- prompt/schema/model versions and cache hit/miss.

Do not assume all providers report tokens or costs in the same way. Record `unknown` rather than fabricate a cost. Label estimate vs billed/actual value.

## 5. Cost and quota behavior

- Define task budgets and limits by provider/model.
- Paid model use is disabled unless the user configures and confirms a budget.
- Check budget and task privacy classification before every call.
- Stop or defer a task when the budget is exhausted; never silently use a paid fallback.
- Treat free-tier quota as provider-controlled and dynamic. Query available quota/dashboard when possible and respect response headers/429 behavior.
- No account/key rotation to evade limits.
- Cache only deterministic/version-keyed outputs whose inputs and behavior-affecting settings match.
- Batch embedding operations only if the provider supports it and privacy/performance tests justify it.
- Report per-task cost and cost per prepared job/application to reveal expensive steps.

## 6. Caching metrics and correctness

Track cache hit rate, stale-cache invalidation events and mismatches. Cache key includes content hashes and versions for document, job snapshot, profile facts, prompt, schema, policy, scoring, retrieval and model. Cached results may speed preparation but never bypass final gate checks or consent.

## 7. Alerts and thresholds

Initially use visible dashboard warnings before external alerting is added. Suggested conditions:

- worker heartbeat stale;
- source checkpoint older than expected schedule window;
- repeated 401/403, 429 or schema failures;
- any `CONFIRMATION_UNKNOWN` older than configured SLA;
- any duplicate-attempt invariant violation;
- backup age beyond the configured maximum;
- disk below safe free-space threshold;
- provider budget reached or unexpectedly high error/latency;
- secret-redaction test failure;
- unexpected external submission while global pause is enabled.

Thresholds must be measured/configured and documented, not silently hard-coded as universal service-level objectives.

## 8. Dashboard requirements

The dashboard should show:

- last/next run in Asia/Kolkata;
- source status, last success, checkpoint age, error and retry availability;
- new/updated/duplicate job counts;
- applications by state including uncertain confirmation;
- questions/missing facts needing user input;
- AI calls/tokens/cost/limits by provider and task;
- backup age and storage usage;
- pause/stop controls and their effective state.

A green health indicator means the component is operating, not that all discovered job data is complete, the role is eligible, or an application succeeded.

## 9. Incident metrics and postmortem

For a duplicate, false success, privacy leak or unauthorized submission, stop affected automation, preserve sanitized records, identify affected job/source/attempt IDs, establish the failure boundary, add a regression test, update safety docs and `memory.md`, and re-enable only after a documented review.
