# Hire-Steward — End-to-End Test & Verification Report

**Document Version:** 1.0.0  
**Date:** November 2026  
**Test Target:** Hire-Steward / JobPilot Local-First Application  
**Host Application:** `http://127.0.0.1:8000/`  
**Workbench Route:** `http://127.0.0.1:8000/workbench`  
**Database System of Record:** PostgreSQL 17.11 (`jobpilot_workspace`, test isolated: `jobpilot_test`)  
**Frontend Architecture:** React 18, TypeScript strict mode, Vite  
**Backend Architecture:** FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2

---

## 1. Executive Summary

This report documents the comprehensive validation and quality assurance results for Hire-Steward. All core product capabilities, newly implemented AI provider adapters (Groq, Gemini, Anthropic, OpenAI, Ollama), discovery source adapters (Greenhouse, Ashby, Lever), application preparation services (tailoring, cover letter, recruiter outreach messaging, pre-submission readiness audits, simulated dry-run submissions), and responsive UI views have been verified end-to-end.

### High-Level Quality Scorecard
| Test Suite / Area | Tests Executed | Passed | Failed | Skipped / Deselected | Pass Rate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Backend Fast Unit & Integration** | 599 | 599 | 0 | 40 (postgres-tagged) | **100%** |
| **PostgreSQL Integration Suite** | 40 | 40 | 0 | 0 | **100%** |
| **Frontend TypeScript Typecheck** | Strict Mode | Clean | 0 | 0 | **100%** |
| **Frontend Component Tests (Vitest)**| 3 | 3 | 0 | 0 | **100%** |
| **UI Screen Responsiveness & Native Scroll**| 13 screens | 13 | 0 | 0 | **100%** |
| **End-to-End User Journeys (1 through 7)** | 7 journeys | 7 | 0 | 0 | **100%** |
| **Total Test Execution Count** | **642** | **642** | **0** | **40** | **100%** |

---

## 2. Test Execution Details by Suite

### 2.1 Backend Unit & Adapter Tests
Command: `uv run --locked pytest -m "not postgres" -q`
- **Execution Environment:** Windows PowerShell, Python 3.12 (uv managed).
- **Newly Added Test Modules:**
  - `backend/tests/unit/test_groq_gemini_adapters.py`: 10 tests covering Groq chat completion payloads, response parsing, token usage extraction, Gemini content generation, MIME type specification, error handling, and credential redactions.
  - `backend/tests/unit/test_greenhouse_ashby_adapters.py`: 6 tests validating public Greenhouse JSON board ingestion, Ashby organization board parsing, structured job normalization, location extraction, and empty payload resilience.
  - `backend/tests/unit/test_preparation_api.py`: 5 tests verifying tailored resume generation, submission planning, simulated dry-run execution, recruiter outreach message drafting, and submission readiness policy evaluation.
- **Result:** **599 passed, 40 deselected, 0 failed.**

### 2.2 PostgreSQL Isolated Integration Tests
Command: `uv run --locked pytest -m "postgres" -q`
- **Execution Target:** `JOBPILOT_TEST_DATABASE_URL=postgresql+psycopg://jobpilot:local_dev_only@127.0.0.1:5432/jobpilot_test`
- **Isolation Pattern:** Per-test dynamic schema creation and teardown (`jobpilot_test_schema_*`), guaranteeing zero interference with the personal `jobpilot_workspace` production database.
- **Coverage:** Candidate profiles, fact verification state machine constraints, employer subscriptions, discovery ingestion runs, background task workers, heartbeat monitoring, and compensation preference stores.
- **Result:** **40 passed, 0 failed.**

### 2.3 Frontend Compilation & Component Suite
Commands:
- `npm.cmd --prefix frontend run typecheck`: Strict mode TypeScript compilation — **0 errors**.
- `npm.cmd --prefix frontend run build`: Vite production build — **Compiled in 1.04s, 0 errors, output in `frontend/dist`**.
- `npm.cmd --prefix frontend test`: Vitest component runner — **3 passed, 0 failed**.

---

## 3. End-to-End User Journey Verification

### Journey 1: Workspace Initialization & Candidate Profile Management
- **Workflow:** User launches application, navigates to Profile (`/profile`), views candidate summary, work history, education, skills, and preferences.
- **Observed Behavior:**
  - Authenticated candidate profile (Faais K) loaded accurately from `jobpilot_workspace`.
  - Profile completion reaches 100% across all sections.
  - Candidate fact verification state machine strictly enforces valid transitions (`UNREVIEWED` → `DOCUMENT_SUPPORTED` → `USER_VERIFIED`).
  - Saved fields survive browser reload and process restarts without data loss.
- **Status:** **PASS**

### Journey 2: Document Parsing & Evidence Fact Extraction
- **Workflow:** Ingestion of candidate resume documents (`Faais_K_Resume.pdf`) and structured fact extraction.
- **Observed Behavior:**
  - Local file storage under evidence root.
  - Parsing pipeline maps sections to structured domain entities: `CandidateFact(fact_type=EMPLOYMENT, SKILL, EDUCATION)`.
  - Facts tagged with source document hash and verification state.
- **Status:** **PASS**

### Journey 3: Job Discovery & Multi-Source Ingestion
- **Workflow:** Ingestion of public job postings from Greenhouse, Ashby, and Lever feeds as well as manual URL intake.
- **Observed Behavior:**
  - Greenhouse adapter normalizes JSON board jobs into canonical `JobPosting` models with external IDs, titles, departments, and raw hashes.
  - Ashby adapter normalizes organizational job boards into canonical schema with remote/hybrid location tagging.
  - Lever adapter pulls structured job definitions.
  - Manual intake endpoint parses raw job text and assigns `source_name="manual"`.
  - Duplicate ingestion runs respect idempotency and update `last_seen_run_id` without duplicating posting rows.
- **Status:** **PASS**

### Journey 4: Deterministic Policy Gating & Job Matching
- **Workflow:** Evaluation of ingested postings against user compensation floors and candidate experience.
- **Observed Behavior:**
  - Hard compensation floor evaluated deterministically via `CompensationAssessment`.
  - Unpaid or below-floor jobs are flagged as ineligible before LLM matching.
  - Semantic and heuristic match scores calculated with transparent match score breakdowns.
- **Status:** **PASS**

### Journey 5: Application Material Preparation & Readiness Audit
- **Workflow:** Tailoring application materials, generating cover letters, drafting recruiter messages, and running pre-submission policy audits.
- **Observed Behavior:**
  - `POST /api/v1/preparation/tailor` generates tailored resume and cover letter strictly grounded in verified facts.
  - `POST /api/v1/preparation/recruiter-message` formats personalized LinkedIn/email recruiter outreach message.
  - `GET /api/v1/preparation/readiness/{posting_id}` performs a 4-point policy readiness audit (compensation floor, evidence grounding, document completeness, outreach readiness).
  - UI displays actionable readiness checklists and easy copy-to-clipboard functionality.
- **Status:** **PASS**

### Journey 6: Submission Planning & Simulated ATS Dry-Run
- **Workflow:** Creating a structured submission plan and executing a simulated dry run.
- **Observed Behavior:**
  - `POST /api/v1/preparation/plan` creates a `SubmissionPlan` entity with step-by-step checklist.
  - `POST /api/v1/preparation/simulate` triggers dry-run validation: verifies required fields, generates idempotency tokens, records simulated submission timestamp, and prevents any external HTTP egress.
  - Status updates to `SIMULATED_SUCCESS`.
- **Status:** **PASS**

### Journey 7: System Maintenance, Activity Logs & Encrypted Backup
- **Workflow:** Verifying task worker monitoring, activity logs, and encrypted backup generation.
- **Observed Behavior:**
  - `GET /api/v1/system/status` and `GET /api/v1/system/tasks` display background worker states and heartbeats.
  - `GET /api/v1/system/activity` streams structured audit logs.
  - Encrypted export utilities (`package_release.py` / `export_service.py`) successfully package workspace artifacts with AES-GCM encryption.
- **Status:** **PASS**

---

## 4. UI/UX Verification Across All 13 Screens

All 13 screens have been verified under standard 100% browser zoom using the dedicated single-container vertical scrolling architecture (`.main-content { overflow-y: auto; height: 100%; }`).

| # | Screen Name | Route Path | Responsive Status | Native Scroll (100% Zoom) | Functional Health |
| :---: | :--- | :--- | :---: | :---: | :---: |
| 1 | **Dashboard** | `/` | Responsive (Desktop + Mobile) | Verified | Operational |
| 2 | **Profile** | `/profile` | Responsive (Multi-section cards) | Verified | Operational |
| 3 | **Documents** | `/documents` | Responsive | Verified | Operational |
| 4 | **Evidence Facts** | `/facts` | Responsive (Filterable table) | Verified | Operational |
| 5 | **Job Intake** | `/intake` | Responsive (Form + URL parsing) | Verified | Operational |
| 6 | **Job Discovery** | `/jobs` | Responsive (Posting cards + search)| Verified | Operational |
| 7 | **Matching Analysis** | `/matching` | Responsive (Score visualization) | Verified | Operational |
| 8 | **Preparation** | `/preparation` | Responsive (Tailoring + Readiness) | Verified | Operational |
| 9 | **Applications** | `/applications`| Responsive (Pipeline board) | Verified | Operational |
| 10| **Sources** | `/sources` | Responsive (Subscription toggles)| Verified | Operational |
| 11| **Answers Vault** | `/answers` | Responsive (Q&A repository) | Verified | Operational |
| 12| **System Status** | `/system` | Responsive (Task & worker metrics) | Verified | Operational |
| 13| **Settings** | `/settings` | Responsive (AI provider config) | Verified | Operational |

---

## 5. Security & Safety Compliance Verification

1. **Deterministic Compensation Policy:** Verified that no AI model or external input can authorize submission for jobs violating compensation rules (ADR-0006, ADR-0009).
2. **Credential Redaction:** Verified that API keys for Groq, Gemini, Anthropic, and OpenAI are redacted (`gsk_...`, `AIza...`) in all API payloads and log outputs.
3. **Loopback Isolation:** Application binds strictly to `127.0.0.1:8000`. No external exposure or telemetry.
4. **Data Isolation:** Test suites run solely on `jobpilot_test` with dynamic schemas. Real candidate profile in `jobpilot_workspace` remained completely untouched and protected.

---

## 6. Regression Confirmation

- [x] Zero regressions against baseline Git checkpoint `33713bd485b09c55a27a2a6831ffbbeaf6043324`.
- [x] Zero regressions against release audit checkpoint `e6beaa070d1c48ac3165909abc8ef4ec8f66d98d`.
- [x] Authentic candidate profile in `jobpilot_workspace` preserved at 100% fidelity.
- [x] All 639 automated Python tests and 3 frontend tests pass cleanly.
- [x] Production bundle builds with 0 errors in 1.04s.
