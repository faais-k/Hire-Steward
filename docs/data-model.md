# JobPilot — Data Model and Persistence Specification

**Status:** The full product schema remains conceptual. The focused compensation-preference tables are implemented in Alembic revisions `0001_compensation_preference` and `0002_compensation_evidence_trust_state`; other entities remain proposed.

## 1. Modeling principles

- PostgreSQL is the system of record for state, identities, provenance, policy decisions, attempts and audit events.
- Keep source observations and accepted normalized records separate. Preserve enough raw/source context to debug normalization while honoring privacy and retention controls.
- Use immutable version records for evidence and submitted application artifacts.
- Represent unknown, conflicting and unverified data explicitly; do not encode missing data as empty string or `false`.
- Use foreign keys, unique constraints and transactions to enforce safety under concurrency.
- Store money as a decimal amount plus currency and period; store normalized annualized amounts only with the assumptions/conversion basis recorded.
- Store UTC timestamps for events and explicit source/local timezone metadata where date interpretation matters.
- Every consequential decision should reference a policy version and the facts/snapshots used to reach it.

## 2. Main entities

### 2.1 `candidate_profiles`

The main user profile/settings document. Even in a single-user MVP, keep preferences structured and versioned.

Suggested fields: `id`, `display_name`, `created_at`, `updated_at`, `profile_version`, `timezone`, `targeting_config_json`, `policy_config_json`, `privacy_config_json`, `submission_config_json`, `active`. `policy_config_json.minimum_compensation` is a versioned object with exact decimal `amount`, `currency` (`INR`) and `period` (`YEAR`); default is INR 100,000/year. Validate as finite and non-negative; zero is valid. Keep the unpaid-role prohibition in deterministic policy code, independent of this preference.

Do not store secrets or entire resumes as profile JSON. Use dedicated records for files and facts.

### 2.2 `candidate_documents`

Represents a logical document/asset, such as the current resume or a certificate.

Suggested fields: `id`, `kind`, `display_name`, `active_file_version_id`, `active`, `sensitivity_class`, `created_at`, `updated_at`, `removed_from_watch_path_at`, `retention_state`.

### 2.3 `candidate_document_versions`

Immutable bytes/version metadata: `id`, `document_id`, `version_number`, `content_sha256`, `storage_key`, `original_filename`, `media_type`, `size_bytes`, `source_path_label`, `ingested_at`, `extraction_status`, `extraction_method`, `extractor_version`, `page_count`, `language_guess`, `error_code`, `created_by`.

Unique constraints: `(document_id, version_number)` and optionally `(document_id, content_sha256)` to avoid duplicate identical versions, subject to product behavior.

Avoid storing an unsafe absolute filesystem path as the permanent identity. Use a storage key and sanitized display path.

### 2.4 `candidate_facts`

Each fact is a claim about the candidate, not automatically a verified truth.

Suggested fields: `id`, `profile_id`, `fact_type`, `subject_key`, `value_json`, `normalized_value_json`, `verification_status`, `confidence`, `sensitivity_class`, `valid_from`, `valid_to`, `supersedes_fact_id`, `source_type` (`document`, `user_entry`, `approved_import`), `created_at`, `verified_at`, `verified_by`, `retired_at`, `fact_version`.

Suggested verification states: `UNREVIEWED`, `USER_VERIFIED`, `DOCUMENT_SUPPORTED`, `CONFLICTED`, `REJECTED`, `SUPERSEDED`. The phrase `DOCUMENT_SUPPORTED` does not imply every source document is authoritative; record the user's verification and source quality separately.

### 2.5 `candidate_fact_evidence`

Many-to-many fact provenance. Fields: `id`, `fact_id`, `document_version_id`, `extract_job_id`, `page_number`, `section_path`, `quote_or_span`, `byte_or_text_offsets`, `evidence_hash`, `created_at`.

Store only the excerpt necessary to support the fact, and redact sensitive values where not required. Avoid fragile line offsets as the sole locator; content hash and version are essential.

### 2.6 `answer_bank_items`

Fields: `id`, `question_canonical_text`, `question_category`, `answer_text`, `context_scope`, `approved_for_reuse`, `approved_at`, `approval_version`, `sensitivity_class`, `source_application_id`, `evidence_fact_ids`, `valid_until`, `created_at`, `updated_at`.

One-time answers should remain tied to a single application unless the user explicitly opts in to reuse. Sensitive answers require expiry/revalidation where appropriate.

### 2.7 `job_sources`

Fields: `id`, `source_name`, `source_type`, `base_domain`, `provider`, `capability_status`, `access_method`, `terms_reviewed_at`, `terms_review_reference`, `allowed_operations`, `rate_limit_config`, `daily_limit`, `enabled`, `last_success_at`, `last_error_at`, `last_error_code`, `created_at`, `updated_at`.

Do not store a permanent “allowed” boolean without review timestamp and rationale. Capability status examples: `VERIFIED_READ_ONLY`, `VERIFIED_READ_AND_SUBMIT`, `MANUAL_ONLY`, `BLOCKED`, `NEEDS_REVIEW`.

### 2.8 `source_checkpoints`

Fields: `id`, `source_id`, `checkpoint_key`, `checkpoint_value_json`, `last_attempt_run_id`, `last_successful_run_id`, `last_successful_watermark`, `updated_at`, `version`.

Checkpoint values may be cursors, opaque tokens, publication timestamps or pagination markers. Never invent a cursor for sources without one. Failed/incomplete runs must not move the last successful watermark.

### 2.9 `scheduled_runs` and `source_run_results`

`scheduled_runs`: `id`, `trigger_type`, `scheduled_for`, `started_at`, `finished_at`, `timezone`, `status`, `config_snapshot_json`, `correlation_id`, `error_summary`.

`source_run_results`: `id`, `run_id`, `source_id`, `status`, `started_at`, `finished_at`, `checkpoint_before_json`, `checkpoint_after_json`, `pages_seen`, `items_seen`, `items_new`, `items_updated`, `items_duplicate`, `rate_limit_events`, `error_code`, `error_details_redacted`, `complete_enough_to_advance_checkpoint`.

A run containing one failed source and one healthy source should preserve both outcomes independently.

### 2.10 `jobs`

Canonical vacancy identity. Fields: `id`, `company_name_normalized`, `title_normalized`, `canonical_location`, `employment_type`, `work_arrangement`, `seniority`, `first_seen_at`, `last_seen_at`, `current_snapshot_id`, `lifecycle_status`, `dedupe_cluster_id`.

### 2.11 `job_source_observations` and `job_snapshots`

Observations represent a source's view of a job at a time. Fields: `id`, `job_id`, `source_id`, `source_job_id`, `source_url`, `canonical_url`, `observed_at`, `published_at`, `raw_payload_hash`, `raw_payload_storage_key`, `http_status`, `parse_status`, `observation_version`.

Snapshots represent normalized details as they were seen: `id`, `job_id`, `observation_id`, `title`, `company_name`, `description_text`, `description_hash`, `location_json`, `salary_json`, `work_arrangement`, `employment_type`, `posted_date_quality`, `normalized_fields_json`, `created_at`.

Do not overwrite submitted-application snapshots if the current listing changes or disappears.

### 2.12 `job_requirements`

Fields: `id`, `job_snapshot_id`, `requirement_text`, `normalized_skill_id` nullable, `requirement_type` (`MANDATORY`, `PREFERRED`, `RESPONSIBILITY`, `OTHER`), `importance`, `extraction_confidence`, `source_span`, `created_at`, `extractor_version`.

Store original wording alongside normalized labels. The normalized label must not replace the source text.

### 2.13 `job_assessments`

Fields: `id`, `job_snapshot_id`, `candidate_profile_version`, `assessment_version`, `score_total`, `score_components_json`, `confidence_level`, `confidence_reasons_json`, `policy_version`, `gate_results_json`, `compensation_threshold_amount`, `compensation_threshold_currency`, `compensation_threshold_period`, `compensation_conversion_basis_json`, `evidence_ids_json`, `result_status`, `created_at`, `model_run_id`.

Scores and gates are separate. Preserve each assessment as immutable history so a new model/policy change does not rewrite past reasoning. Snapshot the exact persisted minimum and its currency/annualized unit at assessment time; also retain the job's original compensation evidence and any conversion source/date/assumptions. A setting change affects future/recomputed decisions but does not edit an existing assessment.

### 2.14 `application_records`

A logical application opportunity/candidate history. Fields: `id`, `job_id`, `job_snapshot_id`, `source_id`, `status`, `first_prepared_at`, `last_state_change_at`, `final_outcome`, `applied_at`, `confirmation_reference`, `confirmation_evidence_key`, `cooldown_key`, `created_at`, `updated_at`, `version`.

Potential uniqueness constraint on normalized source requisition ID plus candidate/profile; exact schema depends on source identity quality. Dedupe remains a policy service as well as a DB invariant.

### 2.15 `application_attempts`

Every attempt to produce an external side effect gets an immutable attempt record: `id`, `application_id`, `attempt_number`, `submission_method`, `source_capability_version`, `submission_plan_hash`, `policy_evaluation_id`, `consent_record_id`, `started_at`, `finished_at`, `request_started`, `request_sent`, `response_received`, `remote_reference`, `result_state`, `result_evidence_key`, `error_code`, `error_details_redacted`, `reconciled_at`, `reconciliation_result`.

Use uniqueness and transactional locking to prevent concurrent attempts for the same vacancy. Do not reuse an attempt ID after an external call.

### 2.16 `application_artifacts` and `application_answers`

Artifacts: `id`, `application_id`, `document_version_id`, `artifact_role`, `rendered_file_version_id`, `content_hash`, `created_at`.

Answers: `id`, `application_id`, `question_source_id`, `question_text_snapshot`, `answer_text`, `answer_hash`, `evidence_fact_ids`, `answer_bank_item_id`, `reuse_permission_snapshot`, `confidence`, `user_approved_at`, `submitted_at`.

Exact submitted materials and answers must be retained as a snapshot per configured retention policy.

### 2.17 `policy_evaluations` and `consent_records`

Policy evaluation: `id`, `subject_type`, `subject_id`, `policy_version`, `input_snapshot_hash`, `gate_results_json`, `compensation_threshold_amount`, `compensation_threshold_currency`, `compensation_threshold_period`, `compensation_conversion_basis_json`, `decision`, `evaluated_at`, `engine_version`. Submission attempts reference the immutable policy evaluation used at the final gate. Updating a setting must not rewrite a submitted application's prior facts, answers or outcomes.

Consent record: `id`, `consent_type`, `subject_type`, `subject_id`, `exact_scope_json`, `granted_at`, `revoked_at`, `consent_text_version`, `actor`.

Store what the user approved and when; a generic “consented=true” without scope and version is inadequate for consequential actions.

### 2.18 Provider and audit records

`provider_calls`: provider/model, task, input/output usage where available, latency, HTTP/result status, quota headers if available, estimated cost, fallback reason, prompt/schema/model version, privacy category, input/output hashes, correlation ID. Avoid storing raw prompts by default if they contain personal data; if needed for debugging, require an explicit retention configuration and redaction.

`audit_events`: `id`, `occurred_at`, `actor_type`, `actor_id`, `event_type`, `subject_type`, `subject_id`, `correlation_id`, `before_hash`, `after_hash`, `metadata_redacted_json`, `previous_event_hash` optional, `event_version`. A `COMPENSATION_PREFERENCE_CHANGED` event records only previous/new amount, currency, period and settings version in addition to timestamp/actor metadata; exclude unrelated sensitive information.

“Append-only” means application code updates by inserting events rather than rewriting old events. It is not cryptographic tamper proof by itself; use OS/database access controls and optional hash chaining if tamper evidence is required.

### 2.19 Implemented compensation-preference slice

The first backend slice deliberately uses a narrow schema instead of creating a generic profile/settings framework:

| Table | Implemented fields and invariants |
|---|---|
| `compensation_preferences` | One local row (`id = 1`), `amount NUMERIC(18,2)`, `currency = 'INR'`, `period = 'YEAR'`, positive `version`, and `updated_at`. The migration seeds `100000.00`, `INR`, `YEAR`, version 1. A database check enforces a non-negative value. |
| `compensation_preference_audits` | Append-by-service rows with `preference_id`, exact old/new amounts, `INR`/`YEAR`, resulting settings version, server-assigned actor metadata (`local_api` / `local` in this unauthenticated slice), and database timestamp. The preference update and audit insert share a transaction. This metadata does not assert a verified human identity. No salary facts or unrelated sensitive data are stored here. |
| `compensation_assessments` | Insert-only API snapshots keyed by UUID and opaque `job_reference`; captures reported status/amount or range/currency/period/recurrence/reference, explicit `evidence_verification_state`, exact threshold amount/currency/period/version, normalized annual bounds when supported, conversion basis, deterministic outcome/reason/explanation, and timestamp. The request cannot supply threshold, verification state, or decision. Public API creates only `UNVERIFIED` assessments. |

The database column `source_status` is exposed in the ORM as `reported_status`; it describes what the caller/model/source reported, not a verified fact. Revision `0002_compensation_evidence_trust_state` adds a constrained `evidence_verification_state` (`UNVERIFIED` or `VERIFIED`) with a server default/backfill of `UNVERIFIED`. Existing `0001` assessments retain their original facts, threshold snapshots and recorded outcomes, but the effective API view treats legacy rows as unverified, returns `REVIEW_REQUIRED`/`EVIDENCE_UNVERIFIED`, suppresses any old normalized amount/conversion basis, and does not expose the old recorded decision as authoritative. No application records are changed. The public assessment API has no route to create a verified state.

The current evaluator can assess trusted domain evidence for deterministic policy tests, but there is no production trust-granting service. A future controlled source-ingestion/verifier component must establish permitted source access, prove retrieval and source/version provenance, retain an immutable snapshot/hash and exact supporting text/span, validate the compensation facts and record verification method/version/time. Storing a reference alone is insufficient. The current public endpoint treats all inputs as unverified and review-required. The pure evaluator converts a direct INR/year amount and an explicitly recurring INR/month amount (`amount × 12`) only for evidence marked trusted; it does not convert other currencies or hourly, daily or contract pay without a defensible basis. The initial `job_reference` is not a foreign key because the canonical `jobs` table is not implemented. There are no application-record tables or submission routes in this slice.

## 3. Application state machine

Allowed transitions are explicit and validated by a single service:

`DISCOVERED → ASSESSING → REVIEW_REQUIRED | ELIGIBLE → PREPARING → NEEDS_USER_INPUT | READY_TO_SUBMIT → SUBMITTING → APPLIED | CONFIRMATION_UNKNOWN | FAILED_RETRYABLE | MANUAL_ACTION_REQUIRED`.

`SKIPPED` and `BLOCKED` can be reached from defined states with a reason. `APPLIED` requires external confirmation evidence. `CONFIRMATION_UNKNOWN` cannot transition back to `SUBMITTING` without a completed reconciliation record and re-evaluated policy. Any retry path increments attempt number and rechecks duplicates, caps, job validity and consent.

## 4. Indexing and data volume

Start with indexes for common access paths, verified by `EXPLAIN ANALYZE` on representative data:

- `jobs(last_seen_at)`, normalized company/title as needed.
- `job_source_observations(source_id, observed_at DESC)` and unique source identifiers where stable.
- `scheduled_runs(status, scheduled_for)`.
- `application_records(status, last_state_change_at DESC)`.
- `application_attempts(application_id, attempt_number)` unique.
- `candidate_facts(profile_id, fact_type, verification_status)`.
- GIN/full-text indexes for job description and requirement text where needed.
- pgvector index only after an embedding model is selected and recall/latency tests indicate benefit.

Do not create HNSW or other approximate indexes solely because they are available. Exact vector search can be preferable for small datasets. Approximate indexes trade recall for speed and need filtered-query testing.

## 5. Migration and retention rules

- Every schema change has an Alembic migration and an upgrade test. Revisions `0001_compensation_preference` and `0002_compensation_evidence_trust_state` have clean-install SQLite and legacy-assessment upgrade coverage; PostgreSQL integration remains unverified until a test database is available.
- Prefer additive migrations, backfills, then cleanup in separate releases.
- When introducing the versioned minimum-compensation setting, default new profiles to INR 100,000/year. Preserve any valid existing user-configured preference; do not silently clamp it. If a legacy value is invalid or a historical assessment lacks a threshold snapshot, preserve available records and mark the missing/uncertain provenance rather than fabricating a value.
- Never change vector dimensions or embedding model in place without a migration/rehydration plan.
- Retention/deletion must account for provenance and submitted artifacts. User deletion should be explicit; report which records will be removed, retained in backups until expiry, or required for audit/export semantics.
- Test export/import against schema-version upgrades and unknown fields.
