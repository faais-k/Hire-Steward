# Hire-Steward — Known Limitations & Operating Boundaries

**Document Version:** 1.0.0  
**Effective Date:** November 2026  
**Audience:** Operators, Developers, and Auditors

---

## 1. Executive Summary

Hire-Steward (JobPilot) is an architecture-compliant, local-first, privacy-by-default job search and application orchestration platform. To guarantee user safety, privacy, deterministic policy enforcement, and regulatory compliance, the application is governed by strict operating boundaries.

This document explicitly defines what Hire-Steward does and does **not** do across networking, AI providers, discovery sources, application submissions, data storage, and operating environments.

---

## 2. Core Functional Boundaries

### 2.1 What the System Does
1. **Candidate Profile & Evidence Grounding:** Manages candidate profiles, work histories, skills, and evidence documents locally. Extracts candidate facts and traces every tailored statement to verified documentary proof.
2. **Job Discovery & Ingestion:** Ingests job postings via structured feeds (Greenhouse public boards, Ashby public boards, Lever public postings) and manual intake (URL or pasted text).
3. **Deterministic Compensation & Policy Gating:** Evaluates compensation floors and policy constraints deterministically without delegating trusted authorization to probabilistic LLMs.
4. **Offline & Online Job Matching:** Computes weighted semantic and heuristic match scores between candidate facts and job requirements.
5. **Application Material Preparation:** Generates tailored resumes, cover letters, recruiter outreach messages, and pre-submission readiness audit reports.
6. **Submission Planning & Verification:** Prepares step-by-step submission checklists and executes simulated dry-run submissions in a controlled, non-destructive sandbox.
7. **Local Lifecycle Tracking:** Records application stages (Discovered, Reviewing, Applied, Interviewing, Offered, Rejected, Archived) with full local audit logging.

### 2.2 What the System Does NOT Do
1. **No Autonomous External Submissions (`NOT_APPLICABLE_BY_DESIGN`):** Hire-Steward **never** submits applications, uploads resumes, or fills external forms without explicit, manual human consent and execution. The system produces frozen submission packets for human-controlled handoff only.
2. **No Blind Auto-Apply / Botting (`NOT_APPLICABLE_BY_DESIGN`):** There is no "auto-apply to 500 jobs while you sleep" feature. Every submission requires human review of tailored artifacts.
3. **No Unverified Fact Fabrication (`ENFORCED`):** The AI tailoring engine cannot invent degrees, companies, certifications, skills, or metrics not grounded in the candidate's verified evidence store.
4. **No Direct Candidate Compensation Authorization by LLM (`ENFORCED`):** A model cannot override user compensation floors or mark an unpaid posting as eligible. Missing or unverified salary evidence fails closed to `REVIEW_REQUIRED`.
5. **No CAPTCHA Solving or Cloudflare Bypass (`NOT_APPLICABLE_BY_DESIGN`):** Hire-Steward strictly respects anti-bot protections, WAFs, and `robots.txt`. It will never attempt to circumvent access controls or anti-bot challenges.
6. **No External Telemetry or Cloud Sync (`NOT_APPLICABLE_BY_DESIGN`):** There is no remote SaaS server, user tracking, crash analytics, or phone-home telemetry.
7. **No Unapproved Live Discovery Ingestion (`DISABLED_PENDING_APPROVAL`):** While Greenhouse, Ashby, and Lever read-only adapters are verified via mock HTTP contracts, live external feed polling remains disabled pending user configuration of approved employer handles.
8. **No Live External Inference Without User API Keys (`IMPLEMENTED_NOT_FULLY_VERIFIED`):** Frontier AI providers (Groq, Gemini, Anthropic, OpenAI) operate in verified offline mock mode until the user provides active API keys in local environment variables.

---

## 3. Network & Local-First Boundaries

1. **Loopback Binding Only:** By default, all backend and frontend services bind strictly to loopback interfaces (`127.0.0.1` or `localhost`). External incoming connections are rejected.
2. **Zero Ambient External Network Calls:** During normal development, testing, and idle operation, zero outgoing network requests are initiated.
3. **Explicit Outbound Egress:** Outbound HTTP requests only occur during:
   - User-initiated job discovery syncs against explicitly configured public ATS endpoints (Greenhouse, Ashby, Lever).
   - User-initiated AI evaluation calls when an external provider (Groq, Gemini, Anthropic, OpenAI) is configured with an active API key.
4. **Sandboxed Integration Tests:** All routine test suites (`pytest -m "not postgres"`, `pytest -m "postgres"`, and frontend tests) execute with network egress disabled or mocked via deterministic HTTP fixtures.

---

## 4. AI Provider & Evaluation Boundaries

Hire-Steward incorporates a provider-neutral AI routing abstraction supporting Groq, Google Gemini, Anthropic, OpenAI, local Ollama, and offline mock adapters.

### 4.1 Operating Boundaries by Provider
| Provider | Default Model | Network Requirement | Rate Limits / Budget Boundary | Fallback Behavior |
| :--- | :--- | :--- | :--- | :--- |
| **Local Mock** | `mock-evaluator` | None (100% offline) | Unlimited, $0.00 cost | Default out-of-the-box mode; deterministic responses |
| **Ollama** | `llama3.2:latest` | Local LAN / localhost | Dependent on local hardware; $0.00 cost | Falls back to mock if endpoint unreachable |
| **Groq** | `llama-3.3-70b-versatile` | Outbound HTTPS | Sub-second latency; Tier-based RPM/TPM limits | Falls back to mock on 429 / network error |
| **Google Gemini**| `gemini-2.0-flash` | Outbound HTTPS | High throughput; standard Google Cloud quotas | Falls back to mock on 401 / 429 |
| **Anthropic** | `claude-3-5-sonnet-latest` | Outbound HTTPS | Standard Anthropic usage tiers | Falls back to mock on auth failure |
| **OpenAI** | `gpt-4o` | Outbound HTTPS | Standard OpenAI org limits | Falls back to mock on auth failure |

### 4.2 Security & Credential Protection
- API keys are supplied strictly via environment variables (`HIRE_STEWARD_GROQ_API_KEY`, `HIRE_STEWARD_GEMINI_API_KEY`, etc.).
- Keys are wrapped in Pydantic `SecretStr` instances and are systematically redacted from API responses (`GET /api/v1/ai/status` displays `configured: true` and `masked: "gsk_...3a"`, never raw keys).
- Raw API keys are never written to database tables, logs, audit trails, or git commits.

---

## 5. Job Discovery & ATS Ingestion Boundaries

### 5.1 Supported Discovery Adapters
1. **Greenhouse Public Boards:** Reads public job listings from `https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs`.
2. **Ashby Public Boards:** Reads public job postings from `https://api.ashbyhq.com/posting-api/job-board/{organization_name}`.
3. **Lever Public Feed:** Ingests public posting listings from `https://api.lever.co/v0/postings/{company}`.
4. **Manual Intake:** Accepts user-submitted URLs and raw text payloads for arbitrary ATS or portal listings.

### 5.2 Scraping Restrictions
- **No Private Login Scraping:** The system does not automate candidate login behind employer portals or LinkedIn/Workday authenticated sessions.
- **Respect for `robots.txt` & Terms of Service:** Automated polling rates are strictly capped (minimum 15-minute polling interval per employer subscription).
- **Public Feeds Only:** Only publicly accessible job feeds that do not require authentication or challenge tokens are ingested automatically.

---

## 6. Auto-Apply, Simulation & Submission Safety Boundaries

To prevent accidental submissions, employer blacklisting, or untracked applications, Hire-Steward operates under the **Submission Safety Policy (ADR-0003)**:

1. **Mandatory Human-in-the-Loop:** Automated final submissions to employer ATS portals are disabled by design. Every application submission requires explicit human review and physical confirmation.
2. **Pre-Submission Readiness Audit:** Prior to drafting or exporting an application package, the system evaluates:
   - Compensation alignment (must satisfy configured hard floors).
   - Grounded facts audit (zero unverified claims or hallucinatory assertions).
   - Document completeness (resume, cover letter, target role title, employer name).
   - Recruiter outreach message readiness.
3. **Simulated Dry-Run Submissions:** The application preparation module provides simulated submission execution (`POST /api/v1/preparation/simulate`). This verifies:
   - Schema conformance of submission payloads.
   - Idempotency key generation.
   - Application stage transition from `DRAFTING` to `SIMULATED`.
   - Logging of submission artifacts to local disk without issuing live external HTTP requests.

---

## 7. Data Privacy, Storage & Cryptographic Boundaries

1. **System of Record:** Local PostgreSQL instance (`jobpilot_workspace` in development/production mode, `jobpilot_test` in test mode).
2. **Candidate Identity & Resume Storage:**
   - Raw uploaded resumes (PDF, DOCX, TXT) are stored strictly on the local filesystem under `$LOCALAPPDATA/HireSteward/workspace/evidence/` or configured local path.
   - Candidate profile facts are stored in local database tables (`candidate_facts`, `candidate_evidence_items`).
3. **Database Integrity Protections:**
   - Real candidate profiles are protected against automated fixture overwrites.
   - Isolated per-test schemas are generated during automated integration test runs and destroyed immediately upon completion.
4. **Encrypted Export & Backup:**
   - Full workspace backups use authenticated AES-GCM encryption (`scripts/package_release.py` / `export_service.py`).
   - Backup passphrases are controlled entirely by the user; no external key recovery service exists.

---

## 8. Platform & Environmental Boundaries

1. **Operating System:** Windows 10/11, macOS 12+, or modern Linux (Ubuntu 22.04+).
2. **Shell Requirements:** Windows PowerShell 5.1+ / PowerShell 7+ on Windows; Bash/Zsh on Unix.
3. **Runtimes:**
   - Python 3.12+ managed via `uv` package manager.
   - Node.js 18+ and npm 9+ for frontend bundling and Vite compilation.
   - PostgreSQL 15+ (tested on PostgreSQL 17.11).
4. **Browser Requirements:**
   - Modern evergreen browsers: Google Chrome, Chromium, Microsoft Edge, Mozilla Firefox, or Safari.
   - Responsive viewport baseline: 1280x720 desktop resolution; responsive down to mobile viewports (375px+).
   - Single-container native scrolling architecture verified at 100% standard browser zoom.
