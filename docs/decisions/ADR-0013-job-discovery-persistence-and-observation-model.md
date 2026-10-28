# ADR-0013: Job Discovery Persistence and Change-Observation Model

- **Status:** Proposed (Revised design review for owner approval; no implementation)
- **Date:** 2026-10-28

## Context

Following the offline Lever discovery vertical slice on `foundation-3-candidate-evidence`, Hire-steward requires a persistent data model to store candidate-managed employer subscriptions, track discovery execution runs, and persist discovered job postings.

Key architectural requirements and lessons from the design review:
1. **Historical Assessment Integrity:** Job postings change over time. If decision-relevant fields (title, location, workplace type, commitment, team, department, level, salary text, requirements) mutate in-place, historical compensation evaluations and match scores lose their factual foundation.
2. **Cross-Subscription Referential Integrity:** An ordinary foreign key from a posting to a discovery run does not prove that the run belongs to the same employer subscription as the posting. Composite foreign keys are required to prevent cross-subscription data corruption at the database level.
3. **Lease Fencing and Wall-Clock Time:** In PostgreSQL, `NOW()` returns the transaction start time and remains frozen during lock acquisition waits. If a runner begins a transaction and waits to acquire a row lock, `NOW()` cannot detect that the runner's lease expired during the wait. Expiry validation must use wall-clock time via `clock_timestamp()`. Fencing must lock the subscription row (`FOR UPDATE`), validate ownership and expiry, and hold the lock through page mutations.
4. **Preserving User Configuration Modification Timestamps:** Lease heartbeats and runner renewals must modify `lease_expires_at` without updating `employer_subscriptions.updated_at`, keeping candidate-initiated configuration changes semantically distinct from automated execution metadata.
5. **Atomic Acquisition for Unclaimed and Expired Leases:** Initial lease acquisition must atomically handle both unclaimed subscriptions (`lease_token IS NULL AND lease_expires_at IS NULL`) and expired leases (`lease_expires_at <= clock_timestamp()`) without overwriting an active unexpired lease.
6. **Lifecycle Reopening Invariants:** Ordinary rediscovery can reactivate `REMOVED` and `STALE` postings, but must not silently change `CLOSED_CONFIRMED` to `ACTIVE`. A confirmed closure requires candidate review if the vacancy reappears.
7. **Database-Level Invariant Precision:** Check constraints must precisely bound page limits (`1 <= page_limit <= 100`) and enforce exact publication date consistency (`EXACT` requires non-null timestamp; `UNKNOWN` and `INVALID` require null).
8. **Snapshot Immutability and Restrictive Deletion:** Snapshots serve as the immutable factual baseline for assessments. Deletion semantics must use `ON DELETE RESTRICT` rather than cascading deletes, preventing accidental destruction of historical evidence while automatic pruning remains deferred.

## Decision

We adopt an acyclic relational model comprising six focused entities in PostgreSQL, enforced by composite foreign keys and transactional fencing:

1. **`job_sources` (Registry):**
   - Reference table defining supported sources (`lever`, `greenhouse`, `ashby`), global capability review states (`NEEDS_REVIEW`, `VERIFIED_READ_ONLY`, `MANUAL_ONLY`, `BLOCKED`, `DISABLED_BY_USER`), and conservative polling limits.
   - Enforces check constraint `ck_job_sources_active_gate`: `is_enabled = TRUE` is forbidden unless `capability_status = 'VERIFIED_READ_ONLY'`.
   - Seeded with Lever as `NEEDS_REVIEW` and `is_enabled = FALSE`. Speculative submission capability states remain excluded per ADR-0012.
   - **Source Terms-Review Freshness Policy (365-Day Ceiling):**
     - Hire-Steward enforces a strict 365-day internal freshness ceiling on `terms_reviewed_at`. If `(wall_clock - terms_reviewed_at) > 365 days`, discovery is immediately blocked with `SourceTermsReviewStaleError`.
     - *Internal Safety Policy, Not External Statutory Claim:* The 365-day interval is an internal Hire-Steward engineering policy to ensure periodic human reassessment of third-party platform terms, robots.txt, and API policies. It is not a claim that any law, regulation, or third-party ATS terms mandate annual review.
     - *Future Timestamps Rejected:* Any review timestamp in the future (`terms_reviewed_at > wall_clock`) indicates invalid or corrupted review metadata and is strictly rejected.
     - *Fail-Closed on Missing or Stale Evidence:* A null review timestamp, an empty `terms_review_reference`, or a timestamp exceeding 365 days immediately halts discovery before any network access or subscription execution.
     - *Independent Gate from Legal Permission:* A fresh, valid review timestamp is a prerequisite for discovery, but **does not itself authorize access**. Live discovery additionally requires explicit approval (`capability_status = 'VERIFIED_READ_ONLY'`), global activation (`is_enabled = TRUE`), and candidate subscription enablement (`is_enabled = TRUE`).
     - *Earlier Review Trigger:* Source-specific restrictions, published terms changes, API deprecations, or security advisories may require earlier re-review before the 365-day ceiling expires.
     - *Zero Live Access Authorization:* This policy does not authorize live access to Lever or any other source. Lever remains `NEEDS_REVIEW` and globally disabled (`is_enabled = FALSE`).

2. **`employer_subscriptions` (User Configuration):**
   - Candidate-managed employer handles (e.g. `source_name = 'lever'`, `employer_handle = 'example-corp'`).
   - Unique on `(source_name, employer_handle)`.
   - Governed by an optimistic concurrency lease (`lease_token`, `lease_expires_at`).
   - Contains no foreign key to `discovery_runs`, eliminating circular references.
   - `updated_at` records user configuration changes exclusively.

3. **`discovery_checkpoints` (Durable Execution Progress):**
   - 1:1 with `employer_subscriptions`, isolating system execution state from user configuration.
   - Advances `last_successful_run_at` **only** upon complete, verified run completion (`status = 'SUCCEEDED'`).
   - Tracks consecutive failures; automatically trips a circuit breaker after 3 consecutive failures to halt polling until user review.
   - Speculative timestamp watermarks (`watermark_created_at_ms`) and run pointers are removed.

4. **`discovery_runs` (Audit Trail & Pagination Cursor):**
   - Audit record of every discovery attempt, tracking start/finish timestamps, pagination state (`current_skip`, `current_page_index`), item counts (seen, new, updated, duplicate), and redacted error codes.
   - `status`: Supports `'PENDING'`, `'RUNNING'`, `'SUCCEEDED'`, `'FAILED'`, `'INTERRUPTED'`, and `'SKIPPED_CONCURRENT_LEASE'`.
   - Bounded by check constraint `ck_discovery_runs_page_limit`: `1 <= page_limit <= 100`.
   - Declares unique constraint `uq_discovery_runs_id_subscription: UNIQUE (id, subscription_id)` to serve as target for composite foreign keys.

5. **`job_postings` (Canonical Vacancy State):**
   - Stable identity keyed by `(subscription_id, posting_id)`. Redundant copies of `source_name` and `employer_handle` are removed.
   - References `discovery_runs` via composite foreign key `(last_seen_run_id, subscription_id) REFERENCES discovery_runs(id, subscription_id) ON DELETE RESTRICT`.
   - Declares unique constraint `uq_job_postings_id_subscription: UNIQUE (id, subscription_id)`.
   - Avoids a circular foreign key to `job_posting_snapshots`. The active snapshot is resolved deterministically via `(id, current_raw_hash)`.
   - Tracks `lifecycle_status`, `consecutive_misses_count`, and `version`.

6. **`job_posting_snapshots` (Change-Triggered Immutable Provenance):**
   - Encapsulates **all** decision-relevant posting data: `title`, `location`, `commitment`, `team`, `department`, `level`, `workplace_type`, `published_at`, `publication_date_status`, `raw_created_at_ms`, `canonical_url`, `apply_url`, `description_plain`, `description_html` (untrusted raw text), `lists_json`, and `additional_plain`.
   - Enforces composite foreign keys:
     - `(posting_id, subscription_id) REFERENCES job_postings(id, subscription_id) ON DELETE RESTRICT`
     - `(run_id, subscription_id) REFERENCES discovery_runs(id, subscription_id) ON DELETE RESTRICT`
   - Enforces exact publication timestamp consistency: `CHECK ((publication_date_status = 'EXACT' AND published_at IS NOT NULL) OR (publication_date_status IN ('UNKNOWN', 'INVALID') AND published_at IS NULL))`.
   - Unique on `(posting_id, source_raw_hash)`.
   - Once inserted, snapshot rows are immutable. Application services expose insert-only operations, and future database privileges or triggers prevent `UPDATE` or `DELETE`.

### Fencing & Lease Protocol
- **Atomic Lease Acquisition:** Handled via:
  ```sql
  UPDATE employer_subscriptions
  SET lease_token = :new_token,
      lease_expires_at = clock_timestamp() + INTERVAL '10 minutes'
  WHERE id = :subscription_id
    AND (
      (lease_token IS NULL AND lease_expires_at IS NULL)
      OR lease_expires_at <= clock_timestamp()
    );
  ```
- **Skipped-Run Outcome:** If acquisition returns `rowcount = 0` (unexpired lease held by another runner), the runner persists a terminal record in `discovery_runs` (`status = 'SKIPPED_CONCURRENT_LEASE'`, `finished_at = NOW()`, `error_code = 'LEASE_ACTIVE'`), but performs:
  1. No network requests.
  2. No posting or snapshot mutations.
  3. No checkpoint advancement.
- **Page-Write Fencing:** In each page transaction:
  1. Executes `SELECT id, lease_token, lease_expires_at FROM employer_subscriptions WHERE id = :subscription_id FOR UPDATE;`
  2. Asserts `lease_token == runner_token AND lease_expires_at > clock_timestamp()`.
  3. If validation fails, executes `ROLLBACK;` and raises `LeaseFencingError`. Stale runners cannot write.
  4. Keeps the lock through page mutations until `COMMIT`.
- **Heartbeat Renewal:** Updates `lease_expires_at = clock_timestamp() + INTERVAL '10 minutes'` without touching `employer_subscriptions.updated_at`.
- **Current Hash Atomicity:** Inserting a new snapshot and updating `job_postings.current_raw_hash` share a single database transaction. A dedicated integration test verifies that an aborted snapshot insert rolls back the posting update, leaving zero dangling hashes.

### Lifecycle Policy: Absence vs. Closure
- **Absence Threshold:** Postings omitted from a successful run increment `consecutive_misses_count`. Postings transition to `REMOVED` only after `consecutive_misses_count >= 2`, absorbing offset pagination jitter.
- **Reopening Guard:** Ordinary rediscovery reactivates `REMOVED` and `STALE` postings. If a `CLOSED_CONFIRMED` posting reappears, the system **never** silently sets it to `ACTIVE`; it flags a `PostingConflict(CONFIRMED_CLOSED_REAPPEARED)` for candidate review.

## Consequences

### Positive
- **Provable Cross-Subscription Isolation:** Composite foreign keys guarantee that postings and snapshots can never reference discovery runs from another employer subscription.
- **Wall-Clock Fencing Safety:** `clock_timestamp()` and row-level locking prevent stale writes after lock-wait delays.
- **Strict Acyclicity (Pure DAG):** Zero circular foreign keys. Alembic migration `0004` creates tables and constraints in a single, linear topological order.
- **Guaranteed Assessment Integrity:** All evaluation-relevant fields are immutably captured in snapshots, protecting past compensation and match scores from mutation.
- **Non-Destructive Deletion Semantics:** `ON DELETE RESTRICT` prevents accidental cascading erasure of historical snapshots.

### Negative & Downgrade Hazards
- **Downgrade Hazard:** Executing `alembic downgrade 0003_candidate_evidence` drops the six discovery tables and **permanently destroys all discovered postings, snapshots, run histories, and subscriptions**. On non-disposable environments, downgrades must be preceded by an explicit export/backup.
- **Deferred Cleanup:** Automatic pruning of unreferenced stale postings is deferred; local storage retention will grow with the number of unique employer job postings observed.

## Traceability
- Formalizes the persistence design for ADR-0012 (Source Access and Lever Evaluation).
- Implements requirements in `docs/job-discovery-sources.md` (Sections 1, 3, 5, 6, 7).
- Preserves the deterministic compensation trust boundary established in ADR-0008 and ADR-0009.
