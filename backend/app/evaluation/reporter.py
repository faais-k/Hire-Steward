"""Report generator for offline job quality and matching evaluation."""

from __future__ import annotations

import json
from backend.app.evaluation.models import EvaluationReport


def generate_markdown_report(report: EvaluationReport) -> str:
    """Generate a clean, auditable GitHub-flavored Markdown report from evaluation results."""
    m = report.metrics

    lines: list[str] = [
        f"# Hire-Steward — Offline Matching Evaluation Benchmark Report",
        "",
        f"- **Report ID:** `{report.report_id}`",
        f"- **Timestamp:** `{report.run_timestamp.isoformat()}`",
        f"- **Git HEAD:** `{report.git_head}`",
        f"- **Scoring Model Version:** `{report.scoring_version}`",
        f"- **Evaluation Dataset Version:** `{report.dataset_version}`",
        f"- **Evaluated Cases Count:** `{m.total_cases}`",
        "",
        "## 1. Executive Summary & Benchmark Metrics",
        "",
        "| Evaluation Metric | Measured Result | Benchmark Target | Status |",
        "|---|---|---|---|",
        f"| **Hard-Gate Leakage Rate (Overall)** | **{m.hard_gate_leakage_rate:.1%}** ({m.hard_gate_leakage_count}/{m.total_cases} cases) | 0.0% | {'PASS' if m.hard_gate_leakage_count == 0 else 'FAIL'} |",
        f"| **Hard-Gate Leakage Rate (Gated Subset)** | **{m.gated_subset_leakage_rate:.1%}** ({m.hard_gate_leakage_count}/{m.hard_gated_cases_count} cases) | 0.0% | {'PASS' if m.hard_gate_leakage_count == 0 else 'FAIL'} |",
        f"| **Fit Tier Accuracy** | **{m.tier_accuracy:.1%}** ({sum(1 for r in report.case_results if r.tier_matches)}/{m.total_cases}) | >= 85.0% | {'PASS' if m.tier_accuracy >= 0.85 else 'FAIL'} |",
        f"| **Confidence Level Accuracy** | **{m.confidence_accuracy:.1%}** ({sum(1 for r in report.case_results if r.confidence_matches)}/{m.total_cases}) | >= 85.0% | {'PASS' if m.confidence_accuracy >= 0.85 else 'FAIL'} |",
        f"| **Required Count Match Rate (Exact)** | **{m.required_count_accuracy:.1%}** ({sum(1 for r in report.case_results if r.required_count_matches)}/{m.total_cases}) | >= 90.0% | {'PASS' if m.required_count_accuracy >= 0.90 else 'FAIL'} |",
        f"| **Preferred Count Match Rate (Exact)** | **{m.preferred_count_accuracy:.1%}** ({sum(1 for r in report.case_results if r.preferred_count_matches)}/{m.total_cases}) | >= 90.0% | {'PASS' if m.preferred_count_accuracy >= 0.90 else 'FAIL'} |",
        f"| **Requirement Met Accuracy** | **{m.met_count_accuracy:.1%}** ({sum(1 for r in report.case_results if r.met_count_matches)}/{m.total_cases}) | >= 85.0% | {'PASS' if m.met_count_accuracy >= 0.85 else 'FAIL'} |",
        f"| **Qualification Gaps Accuracy** | **{m.gaps_accuracy:.1%}** ({sum(1 for r in report.case_results if r.gaps_count_matches)}/{m.total_cases}) | >= 85.0% | {'PASS' if m.gaps_accuracy >= 0.85 else 'FAIL'} |",
        f"| **Provenance Grounding Rate** | **{m.provenance_grounding_rate:.1%}** | 100.0% | {'PASS' if m.provenance_grounding_rate >= 0.95 else 'WARN'} |",
        f"| **Deterministic Stability** | **{'STABLE' if m.deterministic_stability else 'UNSTABLE'}** | STABLE | {'PASS' if m.deterministic_stability else 'FAIL'} |",
        "",
        "## 2. Failure Cases & Diagnostic Details",
        "",
    ]

    if not report.failure_cases:
        lines.append("No failures detected across all benchmark cases! 100% agreement with ground-truth expectations.")
    else:
        lines.append(f"Detected **{len(report.failure_cases)} failure case(s)** out of {m.total_cases} total cases:")
        lines.append("")
        for f in report.failure_cases:
            lines.append(f"### Case: `{f['case_id']}` — {f['title']}")
            lines.append(f"- **Candidate Profile:** `{f['candidate_profile']}`")
            lines.append(f"- **Rationale:** {f['rationale']}")
            lines.append("- **Discrepancies:**")
            for reason in f["failures"]:
                lines.append(f"  - {reason}")
            lines.append("")

    lines.extend([
        "## 3. Case-by-Case Breakdown",
        "",
        "| Case ID | Candidate Profile | Actual Tier | Expected Tier | Score | Confidence | Gaps | Status |",
        "|---|---|---|---|---|---|---|---|",
    ])

    for r in report.case_results:
        status_icon = "PASS" if not r.failure_reasons else "FAIL"
        score_str = f"{r.actual_overall_score:.1%}" if r.actual_overall_score is not None else "None"
        lines.append(
            f"| `{r.case_id}` | `{r.candidate_profile_id}` | `{r.actual_fit_tier.value}` | `{r.tier_matches and r.actual_fit_tier.value or 'mismatch'}` | {score_str} | `{r.actual_confidence_level.value}` | {r.actual_gaps_count} | **{status_icon}** |"
        )

    lines.append("")
    return "\n".join(lines)


def generate_json_report(report: EvaluationReport) -> str:
    """Generate a structured JSON report."""
    return report.model_dump_json(indent=2)
