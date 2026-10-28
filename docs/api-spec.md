# JobPilot — Internal API Specification (Proposed)

**Status:** Partial implementation. Foundation 1 implements health, compensation policy settings, and compensation-only assessment endpoints; other routes below remain proposals.

## 1. API conventions

- Prefix all endpoints with `/api/v1`.
- Use JSON for structured data and multipart upload for documents.
- Use Pydantic request/response schemas and stable error codes.
- All state-changing requests should accept an idempotency key where repeated client requests could duplicate work.
- Long-running tasks return a run/task ID and `202 Accepted`; UI polls status or consumes a future push channel. Do not keep a request open while crawling sources or waiting for an LLM/human.
- Provide pagination, stable sorting and bounded page size.
- Use UTC ISO 8601 for timestamps; include configured timezone when displaying schedule-local times.
- Include `request_id` / `correlation_id` in responses and logs.
- The current API is loopback-only by default and requires matching local `Host`/`Origin` on state-changing requests. This is not authentication and is not a remote-deployment security boundary.

## 2. Error response

Proposed shape:

```json
{
  "error": {
    "code": "POLICY_BLOCKED",
    "message": "This application needs review before submission.",
    "retryable": false,
    "field_errors": [],
    "correlation_id": "..."
  }
}
```

Do not return stack traces, secret values, full provider requests, raw resumes or unredacted source payloads. `message` is safe and user-facing; diagnostics live in restricted logs.

## 3. Proposed routes

### Implemented in Foundation 1

- `GET /health` — process liveness; does not check PostgreSQL.
- `GET /api/v1/settings/policies` — returns the persisted `minimum_compensation` as an exact two-decimal string, currency, annual period, and version. Returns `503` when the database setting or migration is unavailable.
- `PATCH /api/v1/settings/policies` — accepts `{ "minimum_compensation": { "amount": "100000.00", "currency": "INR", "period": "YEAR" } }`. `amount` must be a plain decimal string with at most two fractional digits and fit `NUMERIC(18,2)`; JSON numbers, negatives, exponent notation, NaN, infinity, and unknown fields are rejected. Zero is valid. The change and audit row commit together; unchanged values do not create a change event. State-changing local requests require matching loopback `Host` and `Origin` headers.
- `POST /api/v1/compensation/assessments` — synchronously stores one deterministic compensation-only assessment. Required `job_reference` is an opaque ID; `reported_status` is `PAID`, `UNPAID`, or `UNKNOWN`. For a paid report, send either `amount` or paired `minimum_amount`/`maximum_amount`, each as a decimal string, and source `currency`/`period`. Monthly input is annualized only after evidence is trusted and only with `period: "MONTH"` and `recurring: true`. The server loads the persisted preference in a transaction and snapshots its amount, currency, period, and version. **Every observation received through this public endpoint is `UNVERIFIED`**, returns `REVIEW_REQUIRED`/`EVIDENCE_UNVERIFIED`, and has `eligible_to_submit: false`, regardless of amount or reported status. A caller cannot set a verification state, trusted status, outcome, reason code, or threshold; unknown fields are rejected with safe HTTP `422` response `{"detail":"INVALID_REQUEST"}`. The endpoint returns reported fields (`reported_status`, `reported_amount`, `reported_currency`, `reported_period`, `reported_evidence_reference`) and an explicit evidence verification state. An arbitrary reference, including a URL-shaped value, is not proof of retrieval, authenticity, or support for an amount. A reported unpaid status is not presented as a confirmed unpaid fact; a trusted, confirmed unpaid classification will remain independently blocked once an authorized verifier exists.
- `GET /api/v1/compensation/assessments/{assessment_id}` — returns the threshold snapshot and reported observation. Legacy rows without verification provenance are treated as unverified by the effective API result; original stored assessment fields are preserved but are not authoritative for eligibility.

These assessment endpoints are not connected to job discovery, matching, the dashboard, scheduling, application preparation, or submission. There is no submission route in the current backend. The backend currently has **no complete trusted compensation evidence-ingestion or verification path**. The public API can only record an unverified observation; even a `MEETS_THRESHOLD` result from the pure domain evaluator for an internally trusted test fixture would not authorize application submission. Assessment is not application eligibility, user consent, or permission to submit.

### Health and system

- `GET /health` — process liveness only.
- `GET /ready` — readiness: DB connectivity and required schema/config state.
- `GET /api/v1/system/status` — application version, scheduler state, worker heartbeat, next run time, enabled source count. Must not reveal secrets.
- `POST /api/v1/system/pause` — pause selected work class (`discovery`, `preparation`, `submission`, `all`). Requires authenticated local action if remote mode exists.
- `POST /api/v1/system/resume` — resume a paused class after checks.

### Settings and profile

- `GET /api/v1/settings`
- `PATCH /api/v1/settings/targeting`
- `PATCH /api/v1/settings/policies`
- `PATCH /api/v1/settings/schedule`
- `PATCH /api/v1/settings/privacy`
- `POST /api/v1/settings/consents` — create versioned scope consent.
- `DELETE /api/v1/settings/consents/{consent_id}` — revoke future actions; preserve audit history.

All patches validate the entire setting, persist a version, and write an audit event. Secret changes are handled through a separate credential flow; API responses never return stored secret contents.

`PATCH /api/v1/settings/policies` includes the user's `minimum_compensation` preference. Its implemented request shape is `{ "minimum_compensation": { "amount": "100000.00", "currency": "INR", "period": "YEAR" } }`; amount is a strict decimal string to avoid binary floating-point ambiguity. The database migration defaults the local profile setting to INR 100,000/year. Accept any finite, non-negative amount, including zero, and reject malformed, negative, NaN, infinite, or otherwise invalid input with HTTP `422`. A future UI must label the setting **Minimum annual compensation (INR per year)** and describe any conversion basis. A successful intentional change records previous/new values, timestamp, server-assigned actor and settings version in a redacted audit row, without unrelated sensitive data. The server owns validation and persistence; a client or model cannot supply authority for policy decisions.

### Compensation evidence trust boundary

`reported_status` and `evidence_verification_state` describe different things. Caller-supplied status, amounts/ranges, units and reference are observations only; public callers cannot assign `VERIFIED` or another trusted state. Model-extracted status, amount, confidence, explanation, or decision is also unverified and cannot make an observation authoritative. A stored reference is metadata only. Before an assessment may use compensation as trusted evidence, a future controlled source-ingestion/verifier component must establish source identity and permitted access, retrieve and retain a content/version hash or immutable source snapshot, preserve the exact supporting text/span, validate amount/currency/period and paid status against that source, and record verifier method/version and timestamp. No such component exists today, so the current API has no route or code path that marks public evidence verified.

The assessment endpoint and read endpoint do not establish eligibility to submit. Any unverified evidence is review-required and not submission-eligible. Once trusted ingestion exists, only an internal service may construct the trusted domain evidence object; the HTTP schema remains unable to manufacture that authority. Safe request validation errors do not echo submitted values.

### Candidate evidence

- `GET /api/v1/documents`
- `POST /api/v1/documents` — upload file, validate size/media type, return document and ingest task IDs.
- `GET /api/v1/documents/{document_id}`
- `GET /api/v1/documents/{document_id}/versions`
- `POST /api/v1/documents/{document_id}/reprocess` — explicit reprocessing task; must be non-destructive.
- `GET /api/v1/facts`
- `PATCH /api/v1/facts/{fact_id}` — correct/verify fact with version check and provenance.
- `POST /api/v1/facts/{fact_id}/resolve-conflict`
- `GET /api/v1/facts/{fact_id}/evidence`

### Sources and discovery

- `GET /api/v1/sources`
- `GET /api/v1/sources/{source_id}`
- `PATCH /api/v1/sources/{source_id}/settings` — enable/disable, allowed operations and rate cap; requires current terms/capability metadata for activation.
- `POST /api/v1/runs/discovery` — start a permitted discovery run.
- `GET /api/v1/runs`
- `GET /api/v1/runs/{run_id}`
- `GET /api/v1/sources/{source_id}/health`

### Jobs and assessment

- `GET /api/v1/jobs` — filters for status, score band, confidence, location, salary, sponsorship, source and recency.
- `GET /api/v1/jobs/{job_id}` — normalized job plus current snapshot/source links.
- `GET /api/v1/jobs/{job_id}/snapshots`
- `POST /api/v1/jobs/{job_id}/assess` — async assessment task.
- `GET /api/v1/jobs/{job_id}/assessment`
- `POST /api/v1/jobs/{job_id}/decision` — user decision such as pursue, skip, snooze; decision must not override truthfulness, source permission or external policy gates.

Each future job assessment response must include the threshold amount/currency/annualized period used and any recorded conversion basis. Reassessment after a preference change creates a new assessment; it must not rewrite prior assessment or application history. Dashboard and scheduled evaluations must use the same persisted setting. Unknown, unverified, not defensibly annualizable, or threshold-straddling compensation requires review; a verified unpaid classification is ineligible at every setting. Publicly reported unpaid status remains unverified and cannot proceed.

### Application preparation and workflow

- `POST /api/v1/jobs/{job_id}/prepare` — creates preparation task; no external submission.
- `GET /api/v1/applications`
- `GET /api/v1/applications/{application_id}`
- `GET /api/v1/applications/{application_id}/timeline`
- `GET /api/v1/applications/{application_id}/preview`
- `PATCH /api/v1/applications/{application_id}/answers/{answer_id}` — user correction with version check.
- `POST /api/v1/applications/{application_id}/approve-preview` — captures approval for exact preview hash and scope.
- `POST /api/v1/applications/{application_id}/submit` — accepts only a valid approval/consent ID and idempotency key; backend reruns all gates and creates an immutable attempt.
- `POST /api/v1/applications/{application_id}/reconcile` — starts read-only status reconciliation or requests manual review; it is not itself a retry.
- `POST /api/v1/applications/{application_id}/manual-handoff` — returns official source URL, prepared artifacts and missing items.
- `POST /api/v1/applications/{application_id}/skip` — stores a reason.

### Answer bank

- `GET /api/v1/answer-bank`
- `POST /api/v1/answer-bank`
- `PATCH /api/v1/answer-bank/{item_id}`
- `POST /api/v1/answer-bank/{item_id}/approve-reuse`
- `POST /api/v1/answer-bank/{item_id}/revoke-reuse`

### AI usage and evaluations

- `GET /api/v1/ai/usage`
- `GET /api/v1/ai/providers`
- `PATCH /api/v1/ai/provider-policy` — no secret values returned.
- `GET /api/v1/metrics/summary`
- `GET /api/v1/evaluations/runs`

### Export/import

- `POST /api/v1/exports` — create versioned export with explicit data selection.
- `GET /api/v1/exports/{export_id}`
- `POST /api/v1/imports/validate` — inspect manifest/integrity/schema without mutating live state.
- `POST /api/v1/imports` — stage import; commit only after report/confirmation.

## 4. Core request contracts

### Start discovery

```json
{
  "source_ids": ["source-id"],
  "mode": "incremental",
  "backfill_days": null,
  "dry_run": true
}
```

`mode` should be one of `initial_backfill`, `incremental`, `reconcile`. The server decides allowed backfill behavior based on source capability and stored checkpoint. User-supplied source IDs cannot bypass the source registry.

### Start submission

```json
{
  "approved_preview_hash": "sha256:...",
  "consent_record_id": "...",
  "idempotency_key": "client-generated-unique-value"
}
```

Do not accept arbitrary answer JSON, arbitrary destination URL, headers, browser scripts, or a field map from the client as authority. The server loads the frozen preview, reads the current persisted settings, rechecks all policy gates deterministically, including unpaid and minimum-compensation checks, and creates the trusted plan. A setting change after a prior assessment does not alter that saved history; preparation, scheduled work and final submission must apply the current persisted setting and preserve the setting snapshot used for each new evaluation. Never change records of already-submitted applications merely because a preference changes.

## 5. Concurrency and idempotency

- Use idempotency key table/record for task-creating POST operations.
- The same key and same request payload returns the original task/attempt response.
- Same key with a different payload returns a conflict.
- Database unique constraints and transactions enforce one active submission per vacancy and global concurrency limit.
- Long tasks use a durable task/run record; process memory is not the sole state store.
- A browser or HTTP submission attempt is not replayable after uncertainty without a reconciliation path.

## 6. Security and input validation

- Limit upload bytes and parsed content length; reject unsupported media safely.
- Sanitize and never trust original filenames as filesystem paths.
- Validate external URLs against source registry/domain allowlist to reduce SSRF risk.
- Prevent user-controlled callback URLs, arbitrary redirects and internal-network access from source adapters.
- Escape/render job descriptions safely; do not insert raw HTML unsanitized.
- Rate limit state-changing operations, exports and login/authentication if remote access is enabled.
- Validate IDs and authorization for every referenced resource; do not rely on opaque IDs as access control.

## 7. Versioning and API documentation

FastAPI-generated OpenAPI is useful but not a replacement for this behavior contract. Any breaking response/request change needs an explicit migration/deprecation decision. Record API schema version with exported data and important application snapshots.
