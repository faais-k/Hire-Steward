# ADR-0016: Application Tracking and Job-Search Pipeline Lifecycle

- **Status:** Accepted (Milestone 5 Design & Implementation)
- **Date:** 2026-10-29

## Context

Hire-Steward has established:
1. Deterministic job discovery and persistence (ADR-0013, Alembic revision `0004_job_discovery_persistence`).
2. Candidate document evidence and provenance tracing (ADR-0011, Alembic revision `0003_candidate_evidence`).
3. Explainable job matching and qualification scoring (ADR-0014).
4. Secure local discovery workbench (Milestones 3 and 3.1).
5. Evidence-grounded application material synthesis and client-side draft management (ADR-0015).

While candidates can discover opportunities, evaluate qualification matches, and synthesize tailored application drafts, there is currently no persistent system of record tracking the candidate's job-search decisions, external submission confirmations, follow-up deadlines, interview milestones, or outcomes.

### Core Problems & Risks to Prevent:
1. **Accidental Assumption of Submission:** Creating or editing a tailored resume/cover letter draft must never be conflated with applying. An application record must only move to `APPLIED` upon explicit, deliberate user confirmation.
2. **Loss of Historical Fidelity:** If a candidate applies with a specific version of their resume and later edits their master profile or draft, the record of what was submitted must remain unchanged and verifiable.
3. **Destructive Data Loss on Closed Jobs:** When an employer unpublishes a listing or a job becomes stale/closed (`JobPosting.lifecycle_status IN ('REMOVED', 'CLOSED_CONFIRMED', 'STALE')`), the user's application history, notes, and submitted materials must not be deleted or hidden.
4. **Invalid State Transitions:** A job cannot jump arbitrarily between disconnected states (e.g., from `SAVED` directly to `OFFER_RECEIVED` without an application). Transitions must follow an explicit, deterministic state machine.
5. **Duplicate Tracking Records:** Tracking multiple applications for the exact same job posting must be prevented at the database constraint level.

---

## Decision

We implement a relational application tracking system and state machine:

### 1. Application Lifecycle & State Machine

```
              ┌─────────┐
              │  SAVED  │◄────────────┐
              └────┬────┘             │
                   │                  │
         ┌─────────┴─────────┐        │
         ▼                   ▼        │ (unarchive / re-open)
   ┌───────────┐    ┌─────────────────┤
   │ PREPARING │◄──►│ READY_FOR_REVIEW│
   └─────┬─────┘    └────────┬────────┘
         │                   │
         └─────────┬─────────┘
                   ▼ (explicit user confirmation only)
              ┌─────────┐
              │ APPLIED │
              └────┬────┘
                   │
         ┌─────────┴─────────┐
         ▼                   ▼
  ┌──────────────┐     ┌───────────┐
  │ INTERVIEWING │◄───►│ REJECTED  │
  └──────┬───────┘     └─────┬─────┘
         │                   │
         ▼                   │
  ┌────────────────┐         │
  │ OFFER_RECEIVED │         │
  └──────┬─────────┘         │
         │                   │
         ▼                   ▼
    ┌───────────┐      ┌───────────┐
    │ WITHDRAWN │      │ ARCHIVED  │
    └───────────┘      └───────────┘
```

#### Supported Statuses:
- **`SAVED`**: Candidate bookmarked the posting for later evaluation.
- **`PREPARING`**: Application materials are actively being tailored or edited.
- **`READY_FOR_REVIEW`**: Candidate finished tailoring and marked materials as reviewed.
- **`APPLIED`**: Candidate explicitly confirmed external submission (records submission timestamp, notes, and frozen snapshot).
- **`INTERVIEWING`**: Candidate is actively in communication or interviews with employer.
- **`OFFER_RECEIVED`**: Employer extended a job offer.
- **`REJECTED`**: Application was rejected (pre- or post-interview).
- **`WITHDRAWN`**: Candidate chose to withdraw their candidacy.
- **`ARCHIVED`**: Candidate archived the record without deleting history.

#### Strict State Transition Invariants:
1. Transition to `APPLIED` strictly requires deliberate user confirmation via `/confirm-submission`. Generic status updates (`PATCH /status`) attempting to transition to `APPLIED` are blocked with `DirectAppliedTransitionNotAllowedError` (HTTP 400).
2. Repeated submission confirmation on already submitted applications is rejected with `AlreadySubmittedError` (HTTP 409), preventing silent overwrites of historical snapshots.
3. Once an application has been submitted (`APPLIED`), it cannot be unapplied back to `SAVED`, `PREPARING`, or `READY_FOR_REVIEW`, even if revived through `ARCHIVED`.
4. Direct jumps across stages without prerequisite phases (such as `SAVED` -> `OFFER_RECEIVED`) are rejected with `InvalidStateTransitionError`.
5. Terminal states (`REJECTED`, `WITHDRAWN`, `ARCHIVED`) preserve full history and allow archival. Non-submitted `ARCHIVED` records may be restored to `SAVED`.
6. **Application-Layer vs. Database-Level Immutability:** Historical snapshots and SHA-256 hashes are immutable at the application/domain service layer via explicit one-time confirmation lifecycle, concurrency token checks, and read-only view models. Database-level direct SQL execution is prevented from cascading or deleting history via `RESTRICT` foreign keys, while row-level write-once snapshot constraints are enforced at the service boundary.

---

### 2. Relational Persistence Model (`backend/migrations/versions/0005_application_tracking.py`)

We introduce two tables:

#### `tracked_applications`
- `id` (UUID string, PK): Unique tracking record ID.
- `job_posting_id` (String 36, FK -> `job_postings.id` RESTRICT): Unique link to discovered job.
- `status` (String 32, indexed): Current lifecycle state.
- `created_at` (DateTime TZ): Timestamp when tracking initiated.
- `updated_at` (DateTime TZ): Timestamp of latest modification.
- `last_status_change_at` (DateTime TZ): Timestamp of most recent state change.
- `applied_at` (DateTime TZ, nullable): Exact timestamp of user-confirmed external submission.
- `follow_up_deadline` (DateTime TZ, nullable): User-specified follow-up date.
- `next_interview_at` (DateTime TZ, nullable): Scheduled interview date/time.
- `notes` (Text, nullable): Candidate private notes.
- `reviewed_resume_content` (Text, nullable): User-approved resume draft.
- `reviewed_cover_letter_content` (Text, nullable): User-approved cover letter draft.
- `reviewed_at` (DateTime TZ, nullable): When candidate approved materials.
- `submitted_resume_snapshot` (Text, nullable): Immutable frozen resume markdown captured at confirmed submission.
- `submitted_cover_letter_snapshot` (Text, nullable): Immutable frozen cover letter markdown captured at confirmed submission.
- `submitted_resume_hash` (String 64, nullable): SHA-256 hash of submitted resume.
- `submitted_cover_letter_hash` (String 64, nullable): SHA-256 hash of submitted cover letter.
- `version` (Integer, default 1): Optimistic concurrency token.
- **Constraints:**
  - `uq_tracked_applications_posting`: Enforces exactly one tracking record per job posting.
  - `ck_tracked_apps_status`: Enum check across valid lifecycle statuses.
  - `ck_tracked_apps_applied_at`: `applied_at IS NULL OR status IN ('APPLIED', 'INTERVIEWING', 'OFFER_RECEIVED', 'REJECTED', 'WITHDRAWN', 'ARCHIVED')`.

#### `application_status_history`
- `id` (UUID string, PK): History event ID.
- `application_id` (String 36, FK -> `tracked_applications.id` ondelete CASCADE, indexed).
- `from_status` (String 32, nullable): Previous status (NULL on initial creation).
- `to_status` (String 32, NOT NULL): Target status transitioned into.
- `transition_reason` (String 255, nullable): Optional user-supplied explanation.
- `created_at` (DateTime TZ): Timestamp of transition event.

---

### 3. Non-Destructive Preservation for Stale / Closed Jobs

When a `JobPosting` in the discovery pipeline transitions to `REMOVED`, `STALE`, or `CLOSED_CONFIRMED`:
- The foreign key constraint `ondelete="RESTRICT"` ensures job postings with tracking history cannot be inadvertently deleted.
- The tracking record, submitted snapshots, status history, and notes remain fully readable in the workbench.
- The UI displays an honest banner indicating that the employer's posting has expired or been removed, while keeping the candidate's application record intact.

---

### 4. Service & API Layer

- **`backend/app/domain/application_tracking.py`**:
  - `ApplicationStatus` enum.
  - `VALID_TRANSITIONS` mapping and validation logic.
  - Pydantic models for request validation and structured responses.
- **`backend/app/services/application_tracking.py`**:
  - Transactional service operations for tracking creation, state transitions, submission confirmation, review checkpointing, and note updates.
  - Optimistic locking using `version` column to prevent concurrent clobbering.
- **`backend/app/api/routes/application_tracking.py`**:
  - REST endpoints protected by `LocalOnlyMiddleware`.
  - Input validation and honest error reporting (`404` for not found, `409` for invalid transitions or concurrency conflicts, `422` for payload errors).

---

### 5. Workbench UI Integration

- Pipeline navigation tab ("Pipeline / Tracker") alongside Discovery.
- Status filters (`All`, `Saved`, `Preparing`, `Ready`, `Applied`, `Interviewing`, `Offers`, `Archived`).
- Application detail sidebar with notes editor, deadline dates, status history timeline, and next-action reminders.
- Two-step submission confirmation modal that displays the exact text to be snapshot before marking `APPLIED`.
- Submitted Snapshot viewer allowing candidates to review the frozen historical documents even after further draft edits.

---

## Consequences

### Positive
- Full visibility and control over the candidate's active job hunt without third-party exposure.
- Historical integrity guaranteed through immutable submission snapshots and SHA-256 hashes.
- Absolute prevention of accidental or model-inferred application submission.
- Complete audit trail of application progress and milestone dates.
- Preserves all data when job postings close or expire.

### Negative / Trade-Offs
- Requires database migration `0005_application_tracking` adding two tables.
- Candidate must manually confirm external submissions rather than having automatic submission (deliberate design safety choice).
