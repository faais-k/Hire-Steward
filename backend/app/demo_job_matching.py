"""Demonstration of deterministic, evidence-backed job matching and fit explanation."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.app.domain.candidate_evidence import FactType, FactVerificationState
from backend.app.domain.job_matching import (
    CandidateEvidenceItem,
    ProvenanceReference,
    assess_job_match,
)


def run_demonstration() -> None:
    print("=" * 80)
    print("HIRE-STEWARD -- DETERMINISTIC JOB MATCHING & FIT EXPLANATION DEMO")
    print("=" * 80)

    # 1. Candidate Evidence Profile (Synthetic Facts with Provenance)
    candidate_evidence = [
        CandidateEvidenceItem(
            fact_id="fact_python",
            fact_type=FactType.SKILL.value,
            value={"name": "Python"},
            verification_state=FactVerificationState.DOCUMENT_SUPPORTED.value,
            is_active=True,
            is_conflicted=False,
            provenance=[
                ProvenanceReference(
                    provenance_id="prov_1",
                    document_version_id="doc_ver_resume_v1",
                    byte_start=120,
                    byte_end=155,
                    evidence_hash="a1b2c3d4e5f60102030405060708090a1b2c3d4e5f60102030405060708090a1",
                    method="LOCAL_API_REPORTED",
                )
            ],
        ),
        CandidateEvidenceItem(
            fact_id="fact_postgres",
            fact_type=FactType.SKILL.value,
            value={"name": "PostgreSQL"},
            verification_state=FactVerificationState.USER_VERIFIED.value,
            is_active=True,
            is_conflicted=False,
            provenance=[
                ProvenanceReference(
                    provenance_id="prov_2",
                    document_version_id="doc_ver_resume_v1",
                    byte_start=160,
                    byte_end=190,
                    evidence_hash="b2c3d4e5f60102030405060708090a1b2c3d4e5f60102030405060708090a1b2",
                    method="LOCAL_API_REPORTED",
                )
            ],
        ),
        CandidateEvidenceItem(
            fact_id="fact_education",
            fact_type=FactType.EDUCATION.value,
            value={
                "institution": "Anna University",
                "credential": "B.Tech",
                "field_of_study": "Computer Science",
                "graduation_year": 2020,
            },
            verification_state=FactVerificationState.DOCUMENT_SUPPORTED.value,
            is_active=True,
            is_conflicted=False,
            provenance=[
                ProvenanceReference(
                    provenance_id="prov_3",
                    document_version_id="doc_ver_degree_v1",
                    byte_start=0,
                    byte_end=45,
                    evidence_hash="c3d4e5f60102030405060708090a1b2c3d4e5f60102030405060708090a1b2c3",
                    method="LOCAL_API_REPORTED",
                )
            ],
        ),
        # Overlapping employment periods to demonstrate non-overlapping calendar tenure merging
        CandidateEvidenceItem(
            fact_id="fact_employment_1",
            fact_type=FactType.EMPLOYMENT.value,
            value={
                "employer": "TechCorp Solutions",
                "title": "Senior Software Engineer",
                "start_date": "2020-06-01",
                "end_date": "2025-06-01",
            },
            verification_state=FactVerificationState.DOCUMENT_SUPPORTED.value,
            is_active=True,
            is_conflicted=False,
            provenance=[
                ProvenanceReference(
                    provenance_id="prov_4",
                    document_version_id="doc_ver_resume_v1",
                    byte_start=250,
                    byte_end=320,
                    evidence_hash="d4e5f60102030405060708090a1b2c3d4e5f60102030405060708090a1b2c3d4",
                    method="LOCAL_API_REPORTED",
                )
            ],
        ),
        CandidateEvidenceItem(
            fact_id="fact_employment_concurrent",
            fact_type=FactType.EMPLOYMENT.value,
            value={
                "employer": "Advisory Client",
                "title": "Technical Consultant",
                "start_date": "2021-01-01",
                "end_date": "2022-01-01",  # Completely subsumed inside 2020-2025
            },
            verification_state=FactVerificationState.DOCUMENT_SUPPORTED.value,
            is_active=True,
            is_conflicted=False,
            provenance=[],
        ),
        CandidateEvidenceItem(
            fact_id="fact_fastapi",
            fact_type=FactType.SKILL.value,
            value={"name": "FastAPI"},
            verification_state=FactVerificationState.UNREVIEWED.value,
            is_active=True,
            is_conflicted=False,
            provenance=[],  # Missing provenance to illustrate uncertainty reporting
        ),
    ]

    # 2. Input Job Posting (Senior Backend Engineer)
    job_lists = [
        {
            "title": "Minimum Qualifications",
            "items": [
                "4+ years of professional software engineering experience",
                "Proficiency in Python programming",
                "Hands-on experience with PostgreSQL or relational databases",
                "Bachelor's degree in Computer Science or equivalent field",
                "Experience with Kubernetes and container orchestration",
            ],
        },
        {
            "title": "Preferred Qualifications",
            "items": [
                "Experience building async APIs with FastAPI",
                "Familiarity with distributed queue architectures",
            ],
        },
    ]

    print("\n[INPUT JOB POSTING]")
    print("Title: Senior Backend Engineer")
    print("Workplace Arrangement: Remote")
    print("Location: Worldwide")
    print("Extracted Required Qualifications: 5 items")
    print("Extracted Preferred Qualifications: 2 items")

    print("\n[CANDIDATE EVIDENCE PROFILE]")
    for item in candidate_evidence:
        prov_note = f"(Provenance: {len(item.provenance)} span(s))" if item.provenance else "(MISSING PROVENANCE)"
        print(f"- [{item.fact_type}] {item.display_label} -- Status: {item.verification_state} {prov_note}")

    # 3. Perform Deterministic Assessment
    assessment = assess_job_match(
        posting_id="posting_synth_001",
        snapshot_id="snap_synth_001",
        lists_json=job_lists,
        description_plain=None,
        workplace_type="remote",
        location="Worldwide",
        candidate_evidence=candidate_evidence,
    )

    print("\n" + "=" * 80)
    print("[EVALUATION RESULTS]")
    print(f"Fit Tier:             {assessment.fit_tier.value}")
    print(f"Confidence Level:     {assessment.confidence_level.value}")
    print(f"Scoring Version:      {assessment.scoring_version}")
    print(f"Evidence Coverage:    {assessment.overall_score:.1%}" if assessment.overall_score else "N/A")
    print(f"Calculation Basis:    {assessment.scores.calculation_basis}")
    print(f"Heuristic Notice:     {assessment.heuristic_notice}")

    print("\n[CONFIDENCE REASONS]")
    for r in assessment.confidence_reasons:
        print(f"  * {r}")

    print("\n[DETAILED REQUIREMENT EVALUATIONS]")
    print("--- Required Qualifications ---")
    for ev in assessment.required_evaluations:
        print(f"  * Requirement: '{ev['text']}'")
        print(f"    Status:      {ev['status']}")
        print(f"    Explanation: {ev['explanation']}")
        if ev["is_uncertain"]:
            print(f"    Uncertainty: Flagged as uncertain ({ev['provenance_status']})")
        print()

    print("--- Preferred Qualifications ---")
    for ev in assessment.preferred_evaluations:
        print(f"  * Requirement: '{ev['text']}'")
        print(f"    Status:      {ev['status']}")
        print(f"    Explanation: {ev['explanation']}")
        print()

    print("[QUALIFICATION GAPS]")
    if assessment.qualification_gaps:
        for g in assessment.qualification_gaps:
            print(f"  [!] {g}")
    else:
        print("  None detected.")

    print("\n[UNCERTAINTIES & MISSING PROVENANCE]")
    if assessment.uncertainties:
        for u in assessment.uncertainties:
            print(f"  [i] {u}")
    else:
        print("  None detected.")

    print("\n[OVERALL EXPLAINABLE SUMMARY]")
    print(assessment.overall_explanation)
    print("=" * 80)


if __name__ == "__main__":
    run_demonstration()
