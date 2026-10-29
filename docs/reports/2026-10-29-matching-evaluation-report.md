# Hire-Steward — Offline Matching Evaluation Benchmark Report

- **Report ID:** `rep_864d9d2f4403`
- **Timestamp:** `2026-10-29T15:24:02.350177+00:00`
- **Git HEAD:** `7a21cbe79fa0a4c9b8017ff7fd27b6d3ec487fba`
- **Scoring Model Version:** `v1.0.0-deterministic`
- **Evaluation Dataset Version:** `1.0.0-offline-eval`
- **Evaluated Cases Count:** `37`

## 1. Executive Summary & Benchmark Metrics

| Evaluation Metric | Measured Result | Benchmark Target | Status |
|---|---|---|---|
| **Hard-Gate Leakage Rate (Overall)** | **0.0%** (0/37 cases) | 0.0% | PASS |
| **Hard-Gate Leakage Rate (Gated Subset)** | **0.0%** (0/18 cases) | 0.0% | PASS |
| **Fit Tier Accuracy** | **100.0%** (37/37) | >= 85.0% | PASS |
| **Confidence Level Accuracy** | **100.0%** (37/37) | >= 85.0% | PASS |
| **Required Count Match Rate (Exact)** | **100.0%** (37/37) | >= 90.0% | PASS |
| **Preferred Count Match Rate (Exact)** | **100.0%** (37/37) | >= 90.0% | PASS |
| **Requirement Met Accuracy** | **100.0%** (37/37) | >= 85.0% | PASS |
| **Qualification Gaps Accuracy** | **100.0%** (37/37) | >= 85.0% | PASS |
| **Provenance Grounding Rate** | **97.3%** | 100.0% | PASS |
| **Deterministic Stability** | **STABLE** | STABLE | PASS |

## 2. Failure Cases & Diagnostic Details

No failures detected across all benchmark cases! 100% agreement with ground-truth expectations.
## 3. Case-by-Case Breakdown

| Case ID | Candidate Profile | Actual Tier | Expected Tier | Score | Confidence | Gaps | Status |
|---|---|---|---|---|---|---|---|
| `eval_01_clear_senior_backend` | `standard_senior_dev` | `STRONG_MATCH` | `STRONG_MATCH` | 100.0% | `HIGH` | 0 | **PASS** |
| `eval_02_partial_missing_skills` | `standard_senior_dev` | `PARTIAL_MATCH` | `PARTIAL_MATCH` | 53.3% | `HIGH` | 2 | **PASS** |
| `eval_03_weak_match_preferred_only` | `standard_senior_dev` | `WEAK_MATCH` | `WEAK_MATCH` | 30.0% | `HIGH` | 2 | **PASS** |
| `eval_04_failed_mandatory_tenure` | `standard_senior_dev` | `BLOCKED_OR_CONTRADICTED` | `BLOCKED_OR_CONTRADICTED` | 76.7% | `HIGH` | 1 | **PASS** |
| `eval_05_failed_mandatory_location` | `remote_only_dev` | `BLOCKED_OR_CONTRADICTED` | `BLOCKED_OR_CONTRADICTED` | 90.0% | `HIGH` | 0 | **PASS** |
| `eval_06_synonym_postgres` | `standard_senior_dev` | `STRONG_MATCH` | `STRONG_MATCH` | 100.0% | `HIGH` | 0 | **PASS** |
| `eval_07_synonym_aws` | `remote_only_dev` | `STRONG_MATCH` | `STRONG_MATCH` | 100.0% | `HIGH` | 0 | **PASS** |
| `eval_08_synonym_reactjs` | `junior_frontend_dev` | `STRONG_MATCH` | `STRONG_MATCH` | 100.0% | `HIGH` | 0 | **PASS** |
| `eval_09_symbol_c_vs_cpp` | `standard_senior_dev` | `PARTIAL_MATCH` | `PARTIAL_MATCH` | 65.0% | `HIGH` | 1 | **PASS** |
| `eval_10_symbol_go_vs_django` | `standard_senior_dev` | `PARTIAL_MATCH` | `PARTIAL_MATCH` | 65.0% | `HIGH` | 1 | **PASS** |
| `eval_11_unstructured_prose_explicit_reqs` | `standard_senior_dev` | `STRONG_MATCH` | `STRONG_MATCH` | 100.0% | `HIGH` | 0 | **PASS** |
| `eval_12_unstructured_prose_no_headers` | `standard_senior_dev` | `INSUFFICIENT_DATA` | `INSUFFICIENT_DATA` | None | `LOW` | 0 | **PASS** |
| `eval_13_compound_and_conjunctive` | `standard_senior_dev` | `WEAK_MATCH` | `WEAK_MATCH` | 30.0% | `MEDIUM` | 1 | **PASS** |
| `eval_14_compound_or_alternative` | `standard_senior_dev` | `STRONG_MATCH` | `STRONG_MATCH` | 100.0% | `HIGH` | 0 | **PASS** |
| `eval_15_subjective_behavioral` | `standard_senior_dev` | `PARTIAL_MATCH` | `PARTIAL_MATCH` | 65.0% | `MEDIUM` | 1 | **PASS** |
| `eval_16_conflicted_fact_matching` | `conflicted_skills_dev` | `BLOCKED_OR_CONTRADICTED` | `BLOCKED_OR_CONTRADICTED` | 65.0% | `HIGH` | 1 | **PASS** |
| `eval_17_unreviewed_fact_confidence` | `unreviewed_evidence_dev` | `STRONG_MATCH` | `STRONG_MATCH` | 100.0% | `MEDIUM` | 0 | **PASS** |
| `eval_18_empty_candidate_profile` | `empty_profile` | `INSUFFICIENT_DATA` | `INSUFFICIENT_DATA` | None | `LOW` | 1 | **PASS** |
| `eval_19_empty_job_description` | `standard_senior_dev` | `INSUFFICIENT_DATA` | `INSUFFICIENT_DATA` | None | `LOW` | 0 | **PASS** |
| `eval_20_adversarial_prompt_injection` | `junior_frontend_dev` | `WEAK_MATCH` | `WEAK_MATCH` | 30.0% | `HIGH` | 2 | **PASS** |
| `eval_21_adversarial_html_tags` | `standard_senior_dev` | `STRONG_MATCH` | `STRONG_MATCH` | 100.0% | `HIGH` | 0 | **PASS** |
| `eval_22_degree_bachelors_equivalent` | `standard_senior_dev` | `STRONG_MATCH` | `STRONG_MATCH` | 100.0% | `HIGH` | 0 | **PASS** |
| `eval_23_degree_masters_gap` | `standard_senior_dev` | `PARTIAL_MATCH` | `PARTIAL_MATCH` | 65.0% | `HIGH` | 1 | **PASS** |
| `eval_24_overlapping_tenure_calculation` | `overlapping_tenure_dev` | `BLOCKED_OR_CONTRADICTED` | `BLOCKED_OR_CONTRADICTED` | 65.0% | `HIGH` | 1 | **PASS** |
| `eval_25_unspecified_workplace` | `standard_senior_dev` | `STRONG_MATCH` | `STRONG_MATCH` | 90.0% | `HIGH` | 0 | **PASS** |
| `eval_26_remote_workplace_inherently_accessible` | `junior_frontend_dev` | `STRONG_MATCH` | `STRONG_MATCH` | 100.0% | `HIGH` | 0 | **PASS** |
| `eval_27_duplicate_requirements_in_posting` | `standard_senior_dev` | `STRONG_MATCH` | `STRONG_MATCH` | 100.0% | `HIGH` | 0 | **PASS** |
| `eval_28_responsibilities_misclassified_as_reqs` | `standard_senior_dev` | `STRONG_MATCH` | `STRONG_MATCH` | 100.0% | `HIGH` | 0 | **PASS** |
| `eval_29_mixed_case_headings` | `standard_senior_dev` | `STRONG_MATCH` | `STRONG_MATCH` | 100.0% | `HIGH` | 0 | **PASS** |
| `eval_30_numbered_list_prefix` | `standard_senior_dev` | `STRONG_MATCH` | `STRONG_MATCH` | 100.0% | `HIGH` | 0 | **PASS** |
| `eval_31_unicode_bullets` | `standard_senior_dev` | `STRONG_MATCH` | `STRONG_MATCH` | 100.0% | `HIGH` | 0 | **PASS** |
| `eval_32_duplicate_opportunity_detection` | `standard_senior_dev` | `STRONG_MATCH` | `STRONG_MATCH` | 100.0% | `HIGH` | 0 | **PASS** |
| `eval_32_b_duplicate_opportunity_collision` | `standard_senior_dev` | `STRONG_MATCH` | `STRONG_MATCH` | 100.0% | `HIGH` | 0 | **PASS** |
| `eval_33_near_duplicate_different_requisition` | `standard_senior_dev` | `PARTIAL_MATCH` | `PARTIAL_MATCH` | 65.0% | `MEDIUM` | 1 | **PASS** |
| `eval_34_many_skills_failed_mandatory_tenure` | `standard_senior_dev` | `BLOCKED_OR_CONTRADICTED` | `BLOCKED_OR_CONTRADICTED` | 91.2% | `HIGH` | 1 | **PASS** |
| `eval_35_tenure_expression_variations` | `standard_senior_dev` | `STRONG_MATCH` | `STRONG_MATCH` | 100.0% | `HIGH` | 0 | **PASS** |
| `eval_36_compensation_unpaid_guard` | `standard_senior_dev` | `STRONG_MATCH` | `STRONG_MATCH` | 100.0% | `HIGH` | 0 | **PASS** |
