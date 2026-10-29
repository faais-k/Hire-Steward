"""CLI runner for offline job quality and matching evaluation."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from backend.app.evaluation.dataset import (
    load_candidate_profiles,
    load_evaluation_cases,
)
from backend.app.evaluation.engine import run_evaluation
from backend.app.evaluation.reporter import (
    generate_json_report,
    generate_markdown_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Hire-Steward offline matching evaluation benchmark."
    )
    parser.add_argument(
        "--cases-path",
        type=Path,
        default=None,
        help="Path to evaluation cases JSON fixture file.",
    )
    parser.add_argument(
        "--profiles-path",
        type=Path,
        default=None,
        help="Path to candidate profiles JSON fixture file.",
    )
    parser.add_argument(
        "--format",
        choices=["text", "markdown", "json"],
        default="text",
        help="Output report format.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path to save the generated report file.",
    )

    args = parser.parse_args()

    try:
        cases = load_evaluation_cases(args.cases_path)
        profiles = load_candidate_profiles(args.profiles_path)
    except Exception as exc:
        print(f"Error loading evaluation fixtures: {exc}", file=sys.stderr)
        return 1

    report = run_evaluation(cases, profiles)
    m = report.metrics

    if args.format == "json":
        output_str = generate_json_report(report)
    elif args.format == "markdown":
        output_str = generate_markdown_report(report)
    else:
        # Clean text summary for console
        sep = "=" * 80
        lines = [
            sep,
            "HIRE-STEWARD — OFFLINE MATCHING EVALUATION BENCHMARK",
            sep,
            f"Evaluated Cases: {m.total_cases}",
            f"Git HEAD:        {report.git_head}",
            f"Scoring Model:   {report.scoring_version}",
            f"Dataset Version: {report.dataset_version}",
            "-" * 80,
            f"Hard-Gate Leakage (Overall):       {m.hard_gate_leakage_rate:.1%} ({m.hard_gate_leakage_count}/{m.total_cases} cases)  [TARGET: 0.0%]",
            f"Hard-Gate Leakage (Gated Subset):  {m.gated_subset_leakage_rate:.1%} ({m.hard_gate_leakage_count}/{m.hard_gated_cases_count} cases)  [TARGET: 0.0%]",
            f"Fit Tier Accuracy:            {m.tier_accuracy:.1%} ({sum(1 for r in report.case_results if r.tier_matches)}/{m.total_cases})",
            f"Confidence Level Accuracy:    {m.confidence_accuracy:.1%} ({sum(1 for r in report.case_results if r.confidence_matches)}/{m.total_cases})",
            f"Required Count Match Rate:    {m.required_count_accuracy:.1%} ({sum(1 for r in report.case_results if r.required_count_matches)}/{m.total_cases})",
            f"Preferred Count Match Rate:   {m.preferred_count_accuracy:.1%} ({sum(1 for r in report.case_results if r.preferred_count_matches)}/{m.total_cases})",
            f"Requirement Met Accuracy:     {m.met_count_accuracy:.1%} ({sum(1 for r in report.case_results if r.met_count_matches)}/{m.total_cases})",
            f"Qualification Gaps Accuracy:  {m.gaps_accuracy:.1%} ({sum(1 for r in report.case_results if r.gaps_count_matches)}/{m.total_cases})",
            f"Provenance Grounding Rate:    {m.provenance_grounding_rate:.1%}",
            f"Deterministic Stability:      {'STABLE' if m.deterministic_stability else 'UNSTABLE'}",
            sep,
        ]

        if report.failure_cases:
            lines.append(f"FAILURES DETECTED: {len(report.failure_cases)} case(s)")
            lines.append("-" * 80)
            for f in report.failure_cases:
                lines.append(f"Case [{f['case_id']}] {f['title']}:")
                for r in f["failures"]:
                    lines.append(f"  * {r}")
                lines.append("")
            lines.append(sep)
        else:
            lines.append("ALL BENCHMARK CASES PASSED WITH 100% GROUND TRUTH AGREEMENT.")
            lines.append(sep)

        output_str = "\n".join(lines)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_str)
        print(f"Report successfully saved to {args.output}")

    print(output_str)
    return 0 if m.hard_gate_leakage_count == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
