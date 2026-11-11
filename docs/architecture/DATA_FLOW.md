# Hire-Steward — Data Flow Architecture

**Product:** Hire-Steward / JobPilot  
**Scope:** End-to-End Data Transformation, Persistence Lifecycle, and Invariant Verification  

---

## 1. End-to-End Discovery to Application Flow

```mermaid
sequenceDiagram
    autonumber
    actor User as Candidate / User
    participant UI as React Frontend
    participant API as FastAPI Router
    participant Service as Application Preparation
    participant Matching as Job Matching Engine
    participant DB as PostgreSQL 17.11
    participant ATS as Simulated ATS Adapter

    User->>UI: Select Job Opportunity
    UI->>API: POST /api/v1/preparation/tailor { job_posting_id }
    API->>Service: prepare_application_draft()
    Service->>DB: Load Posting Snapshot & Verified Evidence Facts
    DB-->>Service: Return Posting & Active Facts (Excluding Conflicted/Rejected)
    Service->>Matching: Match Requirements to Grounded Evidence
    Matching-->>Service: Yield Addressed Reqs, Gaps, Grounded Claims
    Service-->>API: ApplicationDraft (Resume Markdown, Cover Letter, Claims)
    API-->>UI: Return Tailored Draft Data

    User->>UI: Click "Audit Submission Readiness"
    UI->>API: GET /api/v1/preparation/readiness/{posting_id}
    API->>Service: check_application_readiness()
    Service->>DB: Check Compensation Floor, Cooldown & Evidence Status
    DB-->>Service: Return Audit Metrics
    Service-->>API: ApplicationReadinessReport (Gate Passes/Fails)
    API-->>UI: Display Readiness Badge & Policy Checklist

    User->>UI: Click "Save to Pipeline Plan"
    UI->>API: POST /api/v1/preparation/plan
    API->>DB: Insert SubmissionPlan (Compute SHA-256 Packet Hash)
    DB-->>API: Commit SubmissionPlanModel
    API-->>UI: Return Plan ID & Cryptographic Hash

    User->>UI: Click "Simulate Submission (Dry-Run)"
    UI->>API: POST /api/v1/preparation/simulate
    API->>ATS: simulate_dispatch(submission_packet)
    ATS-->>API: SimulatedSubmissionResult (Receipt ID, Status)
    API->>DB: Log ApplicationAttempt & Audit Event
    API-->>UI: Return Simulation Receipt & Verified Dry-Run State
```

---

## 2. Ingestion & Evidence Grounding Data Flow

1. **Document Ingestion:**
   - Candidate uploads file (PDF, DOCX, TXT, CSV, XLSX) via UI.
   - Server computes SHA-256 hash of binary content (`CandidateDocumentBlob`).
   - Content-addressed deduplication ensures identical files are stored only once.
2. **Text Parsing & Fact Extraction:**
   - Text is parsed into clean Unicode NFC normalized strings.
   - Candidate facts (`CandidateFact`) are linked to source documents via `CandidateFactEvidence` storing exact `byte_start` and `byte_end` offsets.
3. **Verification State Lifecycle:**
   - Facts start in `UNREVIEWED` or `DOCUMENT_SUPPORTED` state.
   - User reviews and confirms facts to transition them to `USER_VERIFIED`.
   - Conflicted facts are flagged as `CONFLICTED` and strictly excluded from positive claims in tailored resumes.
   - Rejected or superseded facts are permanently excluded from application materials.

---

## 3. Policy Gating & Safety Data Flows

- **Hard Compensation Floor Gate (R-01):**
  - If a job's salary range is below the candidate's configured floor, or if compensation assessment outcome is `BLOCKED`, submission is barred.
- **Employer Cooldown Gate (R-06):**
  - Query existing active applications (`SUBMITTED`, `INTERVIEWING`, `ACCEPTED`) for the same employer subscription.
  - If an active application exists within the cooldown window, submission is blocked.
- **Evidence Verification Gate (R-03, R-04):**
  - Application readiness check ensures zero conflicted facts and alerts candidate on unreviewed claims prior to submission.
