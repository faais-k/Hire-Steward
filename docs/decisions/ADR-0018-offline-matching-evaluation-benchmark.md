# ADR-0018: Offline Job-Quality & Matching-Evaluation Benchmark

- **Status:** Accepted (Milestone 7 Design & Implementation)
- **Date:** 2026-10-29

## Context

Hire-Steward has implemented deterministic job discovery persistence (ADR-0013), candidate evidence provenance (ADR-0011), explainable matching (ADR-0014), review workbench UI (Milestone 3 & 3.1), application drafting (ADR-0015), application tracking (ADR-0016), and user-controlled job intake (ADR-0017).

Before expanding automated job discovery capabilities, we needed an evidence-based, repeatable benchmark to measure how accurately these existing functions perform, identify where they fail, and evaluate corrections—strictly offline with zero external network access, zero live crawling, and zero third-party dependencies.

Key evaluation challenges:
1. **Extraction Robustness:** Raw user-entered descriptions frequently contain HTML formatting, unusual header capitalization, or numbered/Unicode bullets.
2. **Deterministic Naming Variations:** Real-world postings use synonymous terminology (`Postgres` vs `PostgreSQL`, `React.js` vs `React`, `AWS` vs `Amazon Web Services`, `K8s` vs `Kubernetes`, `Golang` vs `Go`). Testing exact literal string matches alone created artificial false negatives.
3. **Compound Conjunction Nuance:** Bullet points frequently combine engineering activities with technical skills (e.g. "PostgreSQL database design and query tuning"). Treating general engineering activity words as separate unevidenced technologies falsely penalized qualified candidates.
4. **Epistemic Invariance & Hard-Gate Non-Leakage:** Prohibited roles (unpaid work, below-floor compensation, contradictory location constraints, conflicted evidence) must never leak into `STRONG_MATCH` or auto-submit eligibility.
5. **Score vs. Confidence Independence:** Score reflects evidence coverage; confidence reflects evidence completeness and provenance verification. The two must remain strictly decoupled.

---

## Decision

We establish an offline evaluation framework and implement targeted, deterministic refinements:

### 1. Version-Controlled Gold Evaluation Corpus
We create a 37-case labeled gold dataset (`backend/tests/fixtures/matching_eval/evaluation_cases.json`) paired with 7 candidate evidence profiles (`candidate_profiles.json`) spanning:
- Standard structured requirements and preferred qualifications.
- Seniority, experience expressions (`5+ years`, `minimum 6 years`), and overlapping tenure calculations.
- Workplace arrangements (remote, hybrid, onsite, unspecified).
- Adversarial inputs (embedded prompt injection strings, inline HTML tags, responsibilities formatted as requirements).
- Epistemic edge cases (unreviewed facts, conflicted facts, empty candidate profiles, empty job descriptions).
- Duplicate and near-duplicate opportunities across requisitions.
- Ground-truth expectations defined independently of algorithmic predictions.

### 2. Deterministic Canonical Skill Synonyms
We introduce `CANONICAL_SKILL_SYNONYMS` in `backend/app/domain/job_matching.py`. When matching a candidate skill against requirement text:
- The symbol-safe boundary matching first tests the candidate fact label.
- If no direct match occurs and the term exists in the canonical synonym dictionary, it tests synonymous aliases using the same symbol-safe word boundaries (`_single_symbol_safe_match`).
- This eliminates false negatives for standard industry synonyms while strictly preserving symbol boundaries (`C` != `C++`, `Java` != `JavaScript`, `Go` != `Django`).

### 3. Substantive Conjunct Distinction
In compound conjunctive requirements (`and`, `as well as`), we introduce `TECHNICAL_ACTIVITY_WORDS` (engineering qualifiers, descriptors, and common activities such as tuning, design, maintenance, debugging, optimization, distributed, low-level).
- A clause is treated as an independent required technology only if it contains substantive domain terms beyond general activity/descriptor words.
- This prevents false negatives on descriptive phrases like "PostgreSQL database design and query tuning" while maintaining strict enforcement on true compound technology requirements like "Python and Kubernetes".

### 4. HTML Normalization for User Intake
In `backend/app/domain/job_posting.py`, `extract_sections_from_plain_text` now includes deterministic HTML tag preprocessing (`_normalize_html_markup`):
- Converts block closing and break tags (`<br>`, `<p>`, `</li>`, `</div>`, `</h[1-6]>`) to newlines.
- Converts opening `<li>` tags to markdown bullet prefixes (`- `).
- Strips remaining inline formatting tags (`<b>`, `<i>`, `<span>`).
- Decodes standard HTML entities (`&amp;`, `&lt;`, `&gt;`, `&quot;`).

### 5. Confidence Downgrade on Partially Evidenced Conjuncts
In `assess_job_match`, confidence rating now checks for requirements with partial conjunct evidence (`e.matched_evidence and e.status == RequirementMatchStatus.INSUFFICIENT_EVIDENCE`).
- When a candidate matches only one part of a multi-skill compound requirement, the assessment is accurately flagged as `MEDIUM` confidence with an explicit note in `confidence_reasons`.

### 6. Truthful UI Gap Indicators
In `frontend/app.js`:
- Jobs with `INSUFFICIENT_DATA` display `Insufficient data` rather than misleadingly asserting `All reqs met`.
- Jobs with `BLOCKED_OR_CONTRADICTED` display `Blocked constraint` when the blocking factor is structural (e.g. location conflict).

---

## Consequences

### Positive:
- **Zero Hard-Gate Leakage:** 0.0% leakage across all blocked, unpaid, and contradictory cases.
- **High Measured Accuracy:** Across 37 diverse cases, fit tier accuracy improved from 83.8% (baseline) to 100.0%, requirement met accuracy from 83.8% to 100.0%, and confidence accuracy from 94.6% to 100.0%.
- **Zero External Overhead:** Entirely offline, deterministic, zero LLM API costs, zero database migrations.
- **Repeatable & Auditable:** Standalone CLI runner (`python -m backend.app.evaluation.runner`) generates timestamped benchmark reports conforming to `docs/testing-evaluation.md`.
