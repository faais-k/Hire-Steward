# Hire-Steward: Full UI & Feature Inventory

**Product:** Hire-Steward Autonomous Job-Search & Application-Management Workbench  
**Audit Date:** 2026-11-11  
**Architecture:** React 18, TypeScript strict mode, Vite, FastAPI Typed Modular Monolith, PostgreSQL 17.11  
**Integrity Mode:** Production Read-Only Audit & Verified Safe Local-First Execution  
**Current Checkpoint:** `eaf2875` (plus verified scroll and responsive repairs)

---

## 1. Executive Summary & Screen Inventory Overview

Hire-Steward is built on a typed React 18 single-page application shell served via FastAPI loopback (`http://127.0.0.1:8000/`). The user interface contains **13 distinct full-page functional views**, a persistent collapsible sidebar navigation, a persistent global topbar with search and quick actions, modal dialogs, and a non-intrusive toast notification system.

| # | Screen Name | Route / Nav ID | Primary View Container ID | Layout Model | Status |
|---|-------------|----------------|---------------------------|--------------|--------|
| 1 | **Overview Dashboard** | `#nav-overview-btn` (`overview`) | `#overview-view` | KPI Grid + Action Grid + Feed | PASS |
| 2 | **Opportunities Workbench** | `#nav-opportunities-btn` (`opportunities`) | `#workbench-view` | 2-Pane Split (List + Detail) | PASS |
| 3 | **Application Pipeline** | `#nav-pipeline-btn` (`pipeline`) | `#pipeline-view` | 5-Column Kanban / Stage Table | PASS |
| 4 | **Application Preparation & Tailoring** | `#nav-preparation-btn` (`preparation`) | `#preparation-view` | Split View + Tailoring Editor | PASS |
| 5 | **Candidate Profile & Verification** | `#nav-profile-btn` (`profile`) | `#profile-view` | Multi-Card Structured Form | PASS |
| 6 | **Evidence Library** | `#nav-evidence-btn` (`evidence`) | `#evidence-view` | Multi-Format Upload + Fact Cards | PASS |
| 7 | **Answer Bank** | `#nav-answers-btn` (`answers`) | `#answers-view` | Question/Answer List + Form | PASS |
| 8 | **Source Registry** | `#nav-sources-btn` (`sources`) | `#sources-view` | Discovery Gate Cards + Metrics | PASS |
| 9 | **AI & Usage Diagnostics** | `#nav-ai-btn` (`ai`) | `#ai-view` | Spend Gauge + Provider Cards | PASS |
| 10 | **Settings & Operational Policy** | `#nav-settings-btn` (`settings`) | `#settings-view` | Policy Sliders + Safeguards | PASS |
| 11 | **Export & Portability** | `#nav-portability-btn` (`portability`) | `#portability-view` | JSON Bundle Export/Import Drawer | PASS |
| 12 | **Activity Log & Audit Feed** | `#nav-activity-btn` (`activity`) | `#activity-view` | Chronological Event Feed | PASS |
| 13 | **System Health & Diagnostics** | `#nav-system-btn` (`system`) | `#system-view` | Node/DB/Storage Health Grid | PASS |

---

## 2. Global Shell & Navigation Components

### 2.1 Sidebar Navigation (`Sidebar.tsx`)
- **Container:** `<aside className="sidebar {sidebar-open open}" id="app-sidebar" aria-label="Application navigation">`
- **Sections:**
  - **Brand Header:** Icon avatar with letter 'H', brand title "Hire-Steward", and "Local" scope badge.
  - **Core Workflow:** Overview (0), Opportunities (badge count), Pipeline (badge count), Preparation.
  - **Candidate Profile:** Candidate Profile (health score % badge), Evidence Library (facts count badge), Answer Bank (answers count badge).
  - **Platform & Governance:** Source Registry, AI & Usage Diagnostics, Settings & Policies, Export & Portability, Activity Log, System Health.
  - **Sidebar Bottom Notice:** "Local-First Mode: Loopback enforced. External scraping & telemetry disabled."
  - **Mobile Backdrop:** `<div id="sidebar-backdrop" className="sidebar-backdrop {active}">` for touch outside-dismissal on narrow viewports.
- **Controls & States:**
  - Active view highlighted with `var(--active)` ground and left border accent.
  - Dynamic count badges updated via API event handlers (`loadJobs`, `loadApplications`, `setFactsCount`, `setProfileScore`).

### 2.2 Global Topbar (`Topbar.tsx`)
- **Container:** `<header className="topbar">`
- **Controls:**
  - **Mobile Menu Toggle:** `#mobile-menu-btn` (visible on viewports <= 900px, toggles sidebar drawer).
  - **Title Heading:** "Job Discovery Workbench" + "Offline Safe" pill badge.
  - **Search Input:** `#search-input` with keyboard shortcut badge hint `Ctrl+K` (`Cmd+K`).
  - **Action Button 1:** `#topbar-seed-btn` ("Seed Demo Fixtures") with loading spinner (`isSeeding`).
  - **Action Button 2:** `#topbar-add-job-btn` ("+ Add Job") opening the manual job intake modal.
- **Wheel Forwarding:** Topbar intercepts mouse-wheel delta and routes it to the active view container, ensuring seamless scroll behavior without header dead-zones.

### 2.3 Add Job Modal Dialog (`AddJobModal.tsx`)
- **Dialog Container:** `<div className="modal-backdrop" id="add-job-modal" role="dialog" aria-modal="true" aria-labelledby="intake-modal-title">`
- **Header:** Title "Manual Job Intake", close button (`aria-label="Close dialog"`).
- **Form Fields:**
  - `Job Title *` (`#intake-title`, required text input)
  - `Employer Name *` (`#intake-employer`, required text input)
  - `Location` (`#intake-location`, text input)
  - `Workplace Type` (`#intake-workplace`, dropdown: Remote, Hybrid, Onsite)
  - `Job Description Text` (`#intake-desc`, multi-line textarea)
- **Controls:** Cancel button, Submit button ("Add Opportunity to Workbench").
- **Accessibility:** Escape key listener dismisses dialog; clicks outside modal window close dialog; focus is trapped within active dialog.

---

## 3. Screen-by-Screen Detailed Inventory

### Screen 1: Overview Dashboard (`OverviewView.tsx`)
- **Route:** `currentView === 'overview'`
- **Major Sections:**
  1. **Dashboard KPI Grid:**
     - Opportunities count (`#dash-opportunities-count`)
     - Active Pipeline count (`#dash-pipeline-count`)
     - Candidate Facts count (`#dash-facts-count`)
     - Profile Health Score % (`#dash-profile-pct`, labels: "Verified & Ready", "In Progress", "Incomplete")
     - AI Budget Remaining (`#dash-ai-budget`, Offline Mock Cap: $5.00)
  2. **Quick Actions Grid:**
     - `#qa-upload-resume`: Upload Resume & Documents (routes to `evidence`)
     - `#qa-explore-jobs`: Review Opportunities (routes to `opportunities`)
     - `#qa-view-pipeline`: Manage Pipeline (routes to `pipeline`)
     - `#qa-backup-data`: Export Safe Backup (routes to `portability`)
  3. **Recent Activity Timeline:**
     - Refresh button (`#dash-refresh-activity`)
     - Feed container (`#overview-activity-feed`) rendering event badge, entity name/ID, timestamp.
- **States:**
  - *Empty State:* "No recent activity events recorded yet."
  - *Loading State:* "Refreshing..." on button disabled state.
- **API Dependencies:** `GET /api/v1/system/activity?limit=10`
- **Scroll Model:** Single-column flex container, auto vertical scroll.

---

### Screen 2: Opportunities Workbench (`OpportunitiesView.tsx`)
- **Route:** `currentView === 'opportunities'`
- **Major Sections:**
  1. **Master Split-Pane:** Two-column grid (`420px minmax(0, 1fr)`).
  2. **Left Column (Jobs List):**
     - Total visible count (`#total-visible`)
     - Tier Filter Pills: All, Strong, Partial, Weak, Blocked (`.tier-filter-pill`)
     - Job Item Cards (`.job-item`, `#job-item-{id}`) showing Title, Employer, Location, Match Score badge, observed timestamp.
  3. **Right Column (Job Detail & Match Inspector):**
     - Job Header: Title, Employer, Workplace badge, Match tier badge (`.tier-badge`).
     - Action Bar: "Track in Pipeline" button (`#track-opp-btn`), "Tailor Application" button.
     - Match Score Breakdown: Overall score, deterministic criteria, matched requirements vs missing qualifications.
     - Raw Job Description Card: Plain text job description preserved from ingestion.
- **States:**
  - *Empty State (No Jobs):* "No opportunities found. Click 'Seed Demo Fixtures' or '+ Add Job' above."
  - *Empty State (No Selection):* "Select an opportunity from the list to inspect qualifications."
- **API Dependencies:** `GET /api/v1/jobs`, `POST /api/v1/applications`
- **Scroll Model:** Independent column scrolling (`.jobs-pane` and `.detail-pane` each have `overflow-y: auto`).

---

### Screen 3: Application Pipeline (`PipelineView.tsx`)
- **Route:** `currentView === 'pipeline'`
- **Major Sections:**
  1. **Pipeline Summary Header:** Active count, conversion rate metric, refresh button (`#refresh-pipeline-btn`).
  2. **Kanban / Stage Columns:**
     - `SAVED` (Bookmarked opportunities)
     - `PREPARING` (Resume & cover letter tailoring in progress)
     - `READY_TO_SUBMIT` (Tailored bundle verified and awaiting user approval)
     - `SUBMITTED` (Live submission recorded)
     - `INTERVIEWING` (Active recruiter or technical interviews)
     - `OFFER` / `ARCHIVED`
  3. **Application Cards:** Job Title, Company, Date added, Stage action controls (`Transition to Next Stage`).
- **States:**
  - *Empty State:* "No tracked applications in pipeline. Discover opportunities in the Workbench."
- **API Dependencies:** `GET /api/v1/applications`, `POST /api/v1/applications/{id}/status`
- **Scroll Model:** Vertical auto scroll for whole board or columns.

---

### Screen 4: Application Preparation & Tailoring (`PreparationView.tsx`)
- **Route:** `currentView === 'preparation'`
- **Major Sections:**
  1. **Job Selector Dropdown:** Select target opportunity from tracked applications.
  2. **Candidate Credentials Inspector:** Selected verified facts from Evidence Library.
  3. **Tailored Application Generator:**
     - "Generate Tailored Resume & Cover Letter" button.
     - Deterministic alignment verification (checks that 100% of claims are grounded in Candidate Facts).
  4. **Draft Preview Card:**
     - Tailored Resume Markdown editor / preview.
     - Tailored Cover Letter Markdown editor / preview.
     - "Save Draft" & "Mark Ready for Submission" buttons.
- **States:**
  - *Empty State:* "Select an opportunity to start preparing tailored application materials."
- **API Dependencies:** `GET /api/v1/jobs`, `GET /api/v1/facts`, `POST /api/v1/tailor`
- **Scroll Model:** Full view container vertical scroll.

---

### Screen 5: Candidate Profile & Verification (`ProfileView.tsx`)
- **Route:** `currentView === 'profile'`
- **Major Sections:**
  1. **Profile Completeness Header:**
     - Completeness Badge (`#profile-completeness-badge`, e.g. "100% Complete").
     - Progress Bar (`#profile-completeness-fill`).
     - Live status message banner (success / error alerts with preserved local edits).
  2. **Personal Information Card:**
     - Full Name (`#prof-name`, text input)
     - Professional Headline (`#prof-headline`, text input)
     - Executive Summary (`#prof-summary`, textarea)
     - Contact Email (`#prof-email`, email input)
     - Phone Number (`#prof-phone`, tel input)
     - Location (`#prof-location`, text input)
     - LinkedIn URL (`#prof-linkedin`, url input)
     - GitHub URL (`#prof-github`, url input)
     - Portfolio URL (`#prof-portfolio`, url input)
  3. **Work Experience Card:**
     - List of experiences with Role, Company, Location, Start/End Dates, Highlights textarea.
     - Add Experience button (`#prof-add-exp-btn`).
     - Remove Experience button per row (`.prof-remove-exp-btn`).
  4. **Education Card:**
     - Degree, Institution, Location, Graduation Year, Details.
     - Add Education button (`#prof-add-edu-btn`).
     - Remove Education button per row (`.prof-remove-edu-btn`).
  5. **Projects Card:**
     - Project Title, Role, URL, Description.
     - Add Project button (`#prof-add-proj-btn`).
     - Remove Project button per row (`.prof-remove-proj-btn`).
  6. **Certifications & Accreditations Card:**
     - Certification Name, Issuing Org, Issue Date, Credential ID / URL.
     - Add Certification button (`#prof-add-cert-btn`).
     - Remove Certification button per row (`.prof-remove-cert-btn`).
  7. **Skills & Languages Card:**
     - Comma-separated Skills input (`#prof-skills`).
     - Comma-separated Languages input (`#prof-languages`).
  8. **Submission Action Bar:**
     - Submit Button (`#save-profile-btn`: "Save & Verify Profile", disabled during saving with "Saving Profile...").
- **States:**
  - *Initial Load:* Populated with authenticated candidate profile (`Faais K`, 100% complete).
  - *Dirty State:* Form fields update locally; completeness percentage dynamically recalculated.
  - *Persistence:* Re-verified against server API on save and reload.
- **API Dependencies:** `GET /api/v1/profile`, `PUT /api/v1/profile`
- **Scroll Model:** Full view container vertical scroll (`overflow-y: auto`, `height: 100%`, smooth wheel and keyboard navigation).

---

### Screen 6: Evidence Library (`EvidenceView.tsx`)
- **Route:** `currentView === 'evidence'`
- **Major Sections:**
  1. **Document Ingestion Card:**
     - Drag-and-drop / file browser upload zone (`#file-drop-zone`).
     - Supported formats: PDF, DOCX, Markdown, TXT, CSV, XLSX, JSON.
     - Document type selector (Resume, Cover Letter, Transcript, Portfolio, Cert).
  2. **Ingested Files Inventory Table:**
     - Filename, File Size, SHA-256 Checksum, Parsing Status, Upload Date.
  3. **Extracted Facts Library:**
     - Category filter pills: All, Work Experience, Education, Skill, Project, Certification.
     - Fact cards showing Fact Type, Extracted Value, Verification Status (`USER_VERIFIED` badge).
     - Manual fact intake button.
- **States:**
  - *Empty State:* "No candidate documents uploaded. Upload a resume to automatically extract structured facts."
- **API Dependencies:** `GET /api/v1/facts`, `POST /api/v1/facts/upload`, `POST /api/v1/facts`
- **Scroll Model:** Full view container vertical scroll.

---

### Screen 7: Answer Bank (`AnswersView.tsx`)
- **Route:** `currentView === 'answers'`
- **Major Sections:**
  1. **Answer Bank Header & Counter:** Total questions answered, verified reuse consent rate.
  2. **Add Standard Answer Form:**
     - Question Category (Behavioral, Technical, Logistics, Compensation, Work Authorization).
     - Standard Prompt / Question text.
     - Standard Answer Markdown body.
     - "Authorize Automatic Reuse" checkbox (`reuse_consent`).
     - Save Answer button (`#save-answer-btn`).
  3. **Curated Answers List:**
     - Categorized question cards with quick copy button, edit button, and revoke consent button.
- **States:**
  - *Empty State:* "No standard interview answers stored yet. Create reusable answers for repetitive application forms."
- **API Dependencies:** `GET /api/v1/answers`, `POST /api/v1/answers`, `PUT /api/v1/answers/{id}`
- **Scroll Model:** Full view container vertical scroll.

---

### Screen 8: Source Registry (`SourcesView.tsx`)
- **Route:** `currentView === 'sources'`
- **Major Sections:**
  1. **Registry Health Header:** Active sources count, last ingest sync time, offline loopback badge.
  2. **Discovery Source Cards:**
     - Manual Intake Source (Status: ACTIVE, Gate: OPEN).
     - Local JSON Feed Source (Status: ACTIVE, Gate: OPEN).
     - Mock Greenhouse ATS Adapter (Status: OFFLINE_MOCK, Gate: MOCK_ONLY).
     - Mock Lever ATS Adapter (Status: OFFLINE_MOCK, Gate: MOCK_ONLY).
     - Mock Workday ATS Adapter (Status: OFFLINE_MOCK, Gate: MOCK_ONLY).
  3. **Ingestion Controls:**
     - "Trigger Ingestion Run" button (pure loopback mock).
     - Source sync log table.
- **States:**
  - *Governance Notice:* "External scraping is disabled. Only local files, manual entries, and synthetic fixtures are allowed."
- **API Dependencies:** `GET /api/v1/sources`
- **Scroll Model:** Full view container vertical scroll.

---

### Screen 9: AI & Usage Diagnostics (`AiView.tsx`)
- **Route:** `currentView === 'ai'`
- **Major Sections:**
  1. **Cost & Spend Tracking Gauge:**
     - Current Spend: $0.00 / Cap: $5.00.
     - Status: `OFFLINE_MOCK` (Zero paid API calls permitted).
  2. **Model Providers Configuration Cards:**
     - Offline Mock Engine: ACTIVE (Deterministic keyword and rule matching).
     - Anthropic Claude Provider: NOT CONFIGURED (Safety disabled).
     - OpenAI GPT-4 Provider: NOT CONFIGURED (Safety disabled).
     - Google Gemini Provider: NOT CONFIGURED (Safety disabled).
  3. **Safety & Redaction Enforcement:**
     - Redacting Formatter: ACTIVE (PII, credentials, and API keys automatically stripped before inference).
- **States:**
  - *Safety Warning:* "Paid AI API access is hard-disabled in local development mode to prevent unauthorized charges."
- **API Dependencies:** `GET /api/v1/ai/status`
- **Scroll Model:** Full view container vertical scroll.

---

### Screen 10: Settings & Operational Policy (`SettingsView.tsx`)
- **Route:** `currentView === 'settings'`
- **Major Sections:**
  1. **Application Safety Controls:**
     - Application Cooldown Days (slider / number input, default: 30 days).
     - Same-Company Cooldown Days (slider / number input, default: 30 days).
     - Daily Submission Cap (slider / number input, default: 5 applications/day).
  2. **Execution Mode Controls:**
     - Dry-Run Simulation Mode: ENFORCED (Cannot be disabled in development mode).
     - Headless Browser Automation: OFFLINE_ONLY.
  3. **Policy Save Action:**
     - "Update Operational Policy" button (`#save-settings-btn`).
- **States:**
  - *Validation State:* Values constrained to safe operating boundaries (cooldown >= 7 days, cap <= 10).
- **API Dependencies:** `GET /api/v1/settings`, `PUT /api/v1/settings`
- **Scroll Model:** Full view container vertical scroll.

---

### Screen 11: Export & Portability (`PortabilityView.tsx`)
- **Route:** `currentView === 'portability'`
- **Major Sections:**
  1. **Export Full Backup Card:**
     - Description: "Download complete local JSON bundle with candidate profile, answer bank, facts, and settings."
     - Action Button: `#export-download-btn` ("Download Backup (.json)").
     - Automatic SHA-256 checksum and manifest generation.
  2. **Restore from Backup Card:**
     - File input (`#import-file-input`, accepts `.json`).
     - "Choose Backup File" button (`#import-browse-btn`).
  3. **Import Bundle Preview Drawer / Box:**
     - `#import-preview-modal-box` showing incoming record counts, collision warnings, and manifest validity.
     - "Confirm & Restore" button (`#import-confirm-btn`) and "Cancel" button (`#import-cancel-btn`).
- **States:**
  - *Preview State:* Displays checksum, entity counts before applying changes.
- **API Dependencies:** `GET /api/v1/portability/export`, `POST /api/v1/portability/import/preview`, `POST /api/v1/portability/import`
- **Scroll Model:** Full view container vertical scroll.

---

### Screen 12: Activity Log & Audit Feed (`ActivityView.tsx`)
- **Route:** `currentView === 'activity'`
- **Major Sections:**
  1. **Header & Controls:** Title, description, Refresh button (`#refresh-activity-btn`).
  2. **Audit Event Feed (`#full-activity-feed`):**
     - Chronological list of events:
       - Event Type badge (`PROFILE_UPDATED`, `APPLICATION_CREATED`, `STATUS_CHANGED`, `BACKUP_EXPORTED`, etc.)
       - Entity Type & ID (e.g. `job_posting (job-1)`)
       - Timestamp with localized formatting.
- **States:**
  - *Empty State:* "No audit events recorded."
- **API Dependencies:** `GET /api/v1/system/activity?limit=50`
- **Scroll Model:** Full view container vertical scroll.

---

### Screen 13: System Health & Diagnostics (`SystemView.tsx`)
- **Route:** `currentView === 'system'`
- **Major Sections:**
  1. **Diagnostics KPI Cards:**
     - System Status (`#sys-status-val`: Healthy) & Loopback Enforced indicator (`#sys-loopback-indicator`).
     - Database Connection (`#sys-db-val`: Connected, PostgreSQL 17.11).
     - Evidence Storage (`#sys-storage-val`: Writable, path display).
     - Total Opportunities (`#sys-total-jobs`).
  2. **Security & Runtime Diagnostics Card:**
     - Allowed Hosts: `localhost, 127.0.0.1, [::1], testserver`
     - External Scraping: Disabled
     - Model Inference: Offline Mock Adapter
     - Credentials Policy: Redacting Formatter active
  3. **Background Tasks Table:**
     - Scheduled worker status, queue depth, active background tasks, heartbeat timestamp.
- **States:**
  - *Live Polling:* Periodic heartbeat check via `/health` and `/ready` endpoints.
- **API Dependencies:** `GET /api/v1/system/status`, `GET /api/v1/system/tasks`
- **Scroll Model:** Full view container vertical scroll.

---

## 4. Toast Notification System (`ToastContainer.tsx`)
- **Container:** `<div id="toast-container" aria-live="polite">`
- **Styles:** `toast`, `toast-{type}` (success, error, info, warning).
- **Behavior:** Renders fixed to bottom-right (`bottom: 24px; right: 24px`), auto-dismisses after 4000ms, dismiss button (`×`) for instant closure.
- **Non-blocking:** `pointer-events: none` on container, `pointer-events: auto` on individual toast bubbles to allow background interactions while visible.

---

## 5. Verification Matrix Summary

| Screen # | Screen Name | Verified in Real Chrome | Keyboard Scroll | Mouse Wheel Scroll | Form / Controls Tested | Status |
|---|---|---|---|---|---|---|
| 1 | Overview Dashboard | YES | PASS | PASS | Quick Action Nav buttons | PASS |
| 2 | Opportunities Workbench | YES | PASS | PASS | Tier pills, split panes | PASS |
| 3 | Application Pipeline | YES | PASS | PASS | Stage transition buttons | PASS |
| 4 | Application Preparation | YES | PASS | PASS | Opportunity selector | PASS |
| 5 | Candidate Profile | YES | PASS | PASS | 11 form inputs, save button | PASS |
| 6 | Evidence Library | YES | PASS | PASS | Category filter pills | PASS |
| 7 | Answer Bank | YES | PASS | PASS | Question category selector | PASS |
| 8 | Source Registry | YES | PASS | PASS | Ingestion controls | PASS |
| 9 | AI & Usage Diagnostics | YES | PASS | PASS | Provider status cards | PASS |
| 10 | Settings & Policy | YES | PASS | PASS | Cooldown sliders | PASS |
| 11 | Export & Portability | YES | PASS | PASS | Backup download button | PASS |
| 12 | Activity Log | YES | PASS | PASS | Refresh feed button | PASS |
| 13 | System Health | YES | PASS | PASS | Diagnostics KPIs | PASS |

*All 13 screens verified in live headless Chrome 131+ with real backend loopback.*
