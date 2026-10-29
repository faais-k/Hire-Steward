from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_session, require_local_same_origin
from backend.app.db.models import (
    DiscoveryCheckpoint,
    DiscoveryRun,
    EmployerSubscription,
    JobPosting,
    JobPostingSnapshot,
    JobSource,
)
from backend.app.domain.application_preparation import ApplicationPreparationError
from backend.app.domain.job_matching import assess_job_match
from backend.app.services.application_preparation import prepare_application_draft
from backend.app.services.job_matching import (
    evaluate_job_posting_match,
    load_candidate_evidence,
)


router = APIRouter(prefix="/api/v1")

VALID_SORT_BY = {"observed_desc", "observed_asc", "score_desc", "title_asc"}
VALID_WORKPLACE_TYPES = {"remote", "hybrid", "onsite"}
VALID_TIERS = {
    "STRONG_MATCH",
    "PARTIAL_MATCH",
    "WEAK_MATCH",
    "BLOCKED_OR_CONTRADICTED",
    "INSUFFICIENT_DATA",
}
VALID_LIFECYCLE_STATUSES = {
    "ACTIVE",
    "REMOVED",
    "STALE",
    "UNKNOWN",
    "CLOSED_CONFIRMED",
}


@router.get("/jobs")
def list_job_postings(
    search: str | None = Query(None, description="Search term for title, employer, location, description"),
    workplace_type: str | None = Query(None, description="Filter by workplace type (remote, hybrid, onsite)"),
    tier: str | None = Query(None, description="Filter by fit tier (STRONG_MATCH, PARTIAL_MATCH, etc.)"),
    lifecycle_status: str | None = Query(None, description="Filter by lifecycle status (ACTIVE, etc.)"),
    sort_by: str = Query("observed_desc", description="Sort order (observed_desc, observed_asc, score_desc, title_asc)"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """List job postings with their latest snapshot and deterministic fit evaluation."""
    if workplace_type is not None and workplace_type.lower() not in VALID_WORKPLACE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"INVALID_WORKPLACE_TYPE: Must be one of {sorted(VALID_WORKPLACE_TYPES)}",
        )
    if tier is not None and tier.upper() not in VALID_TIERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"INVALID_TIER: Must be one of {sorted(VALID_TIERS)}",
        )
    if lifecycle_status is not None and lifecycle_status.upper() not in VALID_LIFECYCLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"INVALID_LIFECYCLE_STATUS: Must be one of {sorted(VALID_LIFECYCLE_STATUSES)}",
        )
    if sort_by not in VALID_SORT_BY:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"INVALID_SORT_BY: Must be one of {sorted(VALID_SORT_BY)}",
        )

    candidate_evidence = load_candidate_evidence(session)

    # 1. Fetch postings and their employer subscriptions
    postings_query = (
        select(JobPosting, EmployerSubscription)
        .join(EmployerSubscription, JobPosting.subscription_id == EmployerSubscription.id)
    )
    if lifecycle_status:
        postings_query = postings_query.where(JobPosting.lifecycle_status == lifecycle_status.upper())

    results = list(session.execute(postings_query).all())
    if not results:
        return {
            "items": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
            "candidate_evidence_count": len(candidate_evidence),
            "is_synthetic_fixture": True,
        }

    posting_ids = [p.id for p, _ in results]

    # 2. Fetch latest snapshot for each posting
    snapshots = list(
        session.scalars(
            select(JobPostingSnapshot)
            .where(JobPostingSnapshot.posting_id.in_(posting_ids))
            .order_by(JobPostingSnapshot.captured_at.desc())
        )
    )
    snapshots_by_posting: dict[str, JobPostingSnapshot] = {}
    for snap in snapshots:
        if snap.posting_id not in snapshots_by_posting:
            snapshots_by_posting[snap.posting_id] = snap

    # 3. Build item list with evaluation
    items: list[dict[str, Any]] = []
    has_fixtures = False

    for posting, sub in results:
        snapshot = snapshots_by_posting.get(posting.id)
        if snapshot is None:
            continue

        is_fixture = (sub.source_name in {"synthetic_fixtures", "fixture_source"} or "fixture" in sub.source_name.lower())
        if is_fixture:
            has_fixtures = True

        # Perform deterministic assessment against current candidate profile
        assessment = assess_job_match(
            posting_id=posting.id,
            snapshot_id=snapshot.id,
            lists_json=snapshot.lists_json,
            description_plain=snapshot.description_plain,
            workplace_type=snapshot.workplace_type,
            location=snapshot.location,
            candidate_evidence=candidate_evidence,
        )

        # Filters
        if search:
            s_low = search.strip().lower()
            text_corpus = " ".join([
                snapshot.title,
                sub.employer_handle,
                snapshot.location or "",
                snapshot.team or "",
                snapshot.department or "",
                snapshot.description_plain or "",
            ]).lower()
            if s_low not in text_corpus:
                continue

        if workplace_type:
            wp_val = (snapshot.workplace_type or "").lower()
            if workplace_type.lower() != wp_val:
                continue

        if tier:
            if assessment.fit_tier.value.upper() != tier.strip().upper():
                continue

        pub_iso = snapshot.published_at.isoformat() if snapshot.published_at else None

        items.append({
            "id": posting.id,
            "posting_id": posting.posting_id,
            "employer_handle": sub.employer_handle,
            "source_name": sub.source_name,
            "lifecycle_status": posting.lifecycle_status,
            "title": snapshot.title,
            "location": snapshot.location,
            "workplace_type": snapshot.workplace_type,
            "published_at": pub_iso,
            "publication_date_status": snapshot.publication_date_status,
            "first_observed_at": posting.first_observed_at.isoformat(),
            "last_observed_at": posting.last_observed_at.isoformat(),
            "is_synthetic_fixture": is_fixture,
            "assessment": {
                "fit_tier": assessment.fit_tier.value,
                "overall_score": assessment.overall_score,
                "required_coverage": assessment.scores.required_coverage,
                "preferred_coverage": assessment.scores.preferred_coverage,
                "confidence_level": assessment.confidence_level.value,
                "gaps_count": len(assessment.qualification_gaps),
                "uncertainties_count": len(assessment.uncertainties),
            },
        })

    # Sort
    if sort_by == "score_desc":
        items.sort(
            key=lambda x: (
                x["assessment"]["overall_score"] is not None,
                x["assessment"]["overall_score"] or 0.0,
                x["last_observed_at"],
            ),
            reverse=True,
        )
    elif sort_by == "observed_asc":
        items.sort(key=lambda x: x["last_observed_at"])
    elif sort_by == "title_asc":
        items.sort(key=lambda x: x["title"].lower())
    else:  # default "observed_desc"
        items.sort(key=lambda x: x["last_observed_at"], reverse=True)

    total_count = len(items)
    paginated_items = items[offset : offset + limit]

    return {
        "items": paginated_items,
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "candidate_evidence_count": len(candidate_evidence),
        "is_synthetic_fixture": has_fixtures,
    }


@router.get("/jobs/{posting_id}")
def get_job_detail(
    posting_id: str,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Retrieve full job detail and explainable match assessment."""
    posting = session.get(JobPosting, posting_id)
    if posting is None:
        # Check by posting_id string identity
        posting = session.scalar(
            select(JobPosting).where(JobPosting.posting_id == posting_id).limit(1)
        )
    if posting is None:
        raise HTTPException(status_code=404, detail="POSTING_NOT_FOUND")

    sub = session.get(EmployerSubscription, posting.subscription_id)
    snapshot = session.scalar(
        select(JobPostingSnapshot)
        .where(JobPostingSnapshot.posting_id == posting.id)
        .order_by(JobPostingSnapshot.captured_at.desc())
        .limit(1)
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="SNAPSHOT_NOT_FOUND")

    assessment = evaluate_job_posting_match(session, posting.id)
    is_fixture = (sub.source_name in {"synthetic_fixtures", "fixture_source"} or "fixture" in sub.source_name.lower()) if sub else False

    pub_iso = snapshot.published_at.isoformat() if snapshot.published_at else None

    return {
        "posting": {
            "id": posting.id,
            "posting_id": posting.posting_id,
            "employer_handle": sub.employer_handle if sub else "unknown",
            "source_name": sub.source_name if sub else "unknown",
            "lifecycle_status": posting.lifecycle_status,
            "version": posting.version,
            "first_observed_at": posting.first_observed_at.isoformat(),
            "last_observed_at": posting.last_observed_at.isoformat(),
            "is_synthetic_fixture": is_fixture,
        },
        "snapshot": {
            "id": snapshot.id,
            "title": snapshot.title,
            "location": snapshot.location,
            "commitment": snapshot.commitment,
            "team": snapshot.team,
            "department": snapshot.department,
            "level": snapshot.level,
            "workplace_type": snapshot.workplace_type,
            "published_at": pub_iso,
            "publication_date_status": snapshot.publication_date_status,
            "canonical_url": snapshot.canonical_url,
            "apply_url": snapshot.apply_url,
            "description_plain": snapshot.description_plain,
            "lists_json": snapshot.lists_json,
            "additional_plain": snapshot.additional_plain,
            "captured_at": snapshot.captured_at.isoformat(),
        },
        "assessment": {
            "id": assessment.id,
            "scoring_version": assessment.scoring_version,
            "fit_tier": assessment.fit_tier.value,
            "overall_score": assessment.overall_score,
            "scores": assessment.scores.model_dump(),
            "confidence_level": assessment.confidence_level.value,
            "confidence_reasons": assessment.confidence_reasons,
            "required_evaluations": assessment.required_evaluations,
            "preferred_evaluations": assessment.preferred_evaluations,
            "structural_evaluations": assessment.structural_evaluations,
            "qualification_gaps": assessment.qualification_gaps,
            "uncertainties": assessment.uncertainties,
            "overall_explanation": assessment.overall_explanation,
            "heuristic_notice": assessment.heuristic_notice,
            "assessed_at": assessment.assessed_at.isoformat(),
        },
    }


@router.get("/jobs/{posting_id}/application-draft")
def get_job_application_draft(
    posting_id: str,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Retrieve deterministic evidence-grounded application materials for a job posting."""
    try:
        draft = prepare_application_draft(session, posting_id)
    except ApplicationPreparationError as exc:
        if exc.code in {"POSTING_NOT_FOUND", "SNAPSHOT_NOT_FOUND"}:
            raise HTTPException(status_code=404, detail=exc.code)
        raise HTTPException(status_code=400, detail=exc.message)

    return draft.model_dump()


SAMPLE_JOBS = [
    {
        "posting_id": "syn_py_backend_01",
        "title": "Senior Python Backend Engineer",
        "location": "Worldwide",
        "workplace_type": "remote",
        "commitment": "Full-time",
        "team": "Core Platform",
        "department": "Engineering",
        "level": "Senior",
        "description_plain": (
            "We are seeking an experienced Backend Engineer to design and scale "
            "offline-first systems and deterministic matching pipelines using Python, FastAPI, and PostgreSQL."
        ),
        "lists_json": [
            {
                "title": "Required Qualifications",
                "items": [
                    "4+ years of professional software engineering experience",
                    "Proficiency in Python programming",
                    "Hands-on experience with PostgreSQL or relational databases",
                    "Bachelor's degree in Computer Science or equivalent field",
                ],
            },
            {
                "title": "Preferred Qualifications",
                "items": [
                    "Experience building async APIs with FastAPI",
                    "Containerization with Docker",
                ],
            },
        ],
    },
    {
        "posting_id": "syn_k8s_infra_02",
        "title": "Cloud Infrastructure & Platform Engineer",
        "location": "Frankfurt, Germany",
        "workplace_type": "onsite",
        "commitment": "Full-time",
        "team": "Infrastructure",
        "department": "DevOps",
        "level": "Mid-Senior",
        "description_plain": "Manage mission-critical Kubernetes clusters and cloud infrastructure on AWS.",
        "lists_json": [
            {
                "title": "Required Qualifications",
                "items": [
                    "3+ years experience managing Kubernetes clusters in production",
                    "Proficiency with AWS cloud infrastructure",
                    "Proficiency in Python programming",
                ],
            },
            {
                "title": "Nice to have",
                "items": [
                    "Experience with Terraform and infrastructure as code",
                ],
            },
        ],
    },
    {
        "posting_id": "syn_data_eng_03",
        "title": "Senior Data Platform Engineer",
        "location": "Remote - US/Europe",
        "workplace_type": "remote",
        "commitment": "Full-time",
        "team": "Data Platform",
        "department": "Data",
        "level": "Senior",
        "description_plain": "Build high-throughput streaming and batch data pipelines.",
        "lists_json": [
            {
                "title": "Requirements",
                "items": [
                    "5+ years of software development experience",
                    "Hands-on experience with PostgreSQL",
                    "Experience with Apache Kafka and streaming event architectures",
                ],
            },
            {
                "title": "Bonus",
                "items": [
                    "Experience with Python programming",
                ],
            },
        ],
    },
    {
        "posting_id": "syn_cpp_systems_04",
        "title": "Lead Embedded Systems Architect",
        "location": "Munich, Germany",
        "workplace_type": "onsite",
        "commitment": "Full-time",
        "team": "Hardware & Firmware",
        "department": "Embedded Systems",
        "level": "Lead",
        "description_plain": "Develop low-latency safety-critical firmware for robotics controllers.",
        "lists_json": [
            {
                "title": "Required Qualifications",
                "items": [
                    "7+ years of professional software engineering experience",
                    "Strong proficiency in C++ and embedded systems programming",
                    "Experience with RTOS and Linux kernel drivers",
                ],
            },
            {
                "title": "Preferred Qualifications",
                "items": [
                    "Familiarity with Python for testing automation",
                ],
            },
        ],
    },
]


@router.post("/jobs/seed-fixtures")
def seed_synthetic_fixtures(
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, Any]:
    """Seed synthetic offline fixture data for demonstration and workbench testing."""
    sample_posting_ids = [j["posting_id"] for j in SAMPLE_JOBS]
    existing_postings_count = session.scalar(
        select(func.count(JobPosting.id)).where(
            JobPosting.posting_id.in_(sample_posting_ids)
        )
    ) or 0

    if existing_postings_count == len(SAMPLE_JOBS):
        return {
            "status": "ALREADY_SEEDED",
            "postings_seeded": 0,
            "source": "synthetic_fixtures",
            "message": "Synthetic fixtures are already seeded.",
        }

    now = datetime.now(timezone.utc)

    # 1. Job Source
    source = session.get(JobSource, "synthetic_fixtures")
    if source is None:
        source = JobSource(
            source_name="synthetic_fixtures",
            display_name="Synthetic Offline Fixtures",
            capability_status="VERIFIED_READ_ONLY",
            is_enabled=True,
            terms_reviewed_at=now,
            terms_review_reference="Offline synthetic fixtures for workbench development.",
        )
        session.add(source)
        session.flush()

    # 2. Employer Subscription
    sub = session.scalar(
        select(EmployerSubscription)
        .where(EmployerSubscription.source_name == "synthetic_fixtures")
        .limit(1)
    )
    if sub is None:
        sub = EmployerSubscription(
            id=str(uuid4()),
            source_name="synthetic_fixtures",
            employer_handle="example-tech-corp",
            is_enabled=True,
        )
        session.add(sub)
        session.flush()

        checkpoint = DiscoveryCheckpoint(
            subscription_id=sub.id,
            last_successful_run_at=now,
            consecutive_failure_count=0,
            circuit_breaker_tripped=False,
        )
        session.add(checkpoint)

    # 3. Discovery Run
    run = DiscoveryRun(
        id=str(uuid4()),
        subscription_id=sub.id,
        status="SUCCEEDED",
        started_at=now,
        finished_at=now,
        items_seen_count=len(SAMPLE_JOBS),
        items_new_count=len(SAMPLE_JOBS) - existing_postings_count,
        page_limit=50,
    )
    session.add(run)
    session.flush()

    # 4. Job Postings & Snapshots
    postings_created = 0
    for j in SAMPLE_JOBS:
        existing = session.scalar(
            select(JobPosting).where(JobPosting.posting_id == j["posting_id"]).limit(1)
        )
        if existing is not None:
            continue
            continue

        raw_hash = hashlib.sha256(j["posting_id"].encode("utf-8")).hexdigest()
        posting = JobPosting(
            id=str(uuid4()),
            subscription_id=sub.id,
            posting_id=j["posting_id"],
            current_raw_hash=raw_hash,
            lifecycle_status="ACTIVE",
            last_seen_run_id=run.id,
            first_observed_at=now,
            last_observed_at=now,
        )
        session.add(posting)
        session.flush()

        snapshot = JobPostingSnapshot(
            id=str(uuid4()),
            subscription_id=sub.id,
            posting_id=posting.id,
            run_id=run.id,
            source_raw_hash=raw_hash,
            title=j["title"],
            location=j["location"],
            workplace_type=j["workplace_type"],
            commitment=j["commitment"],
            team=j["team"],
            department=j["department"],
            level=j["level"],
            published_at=now,
            publication_date_status="EXACT",
            description_plain=j["description_plain"],
            lists_json=j["lists_json"],
            canonical_url=f"https://offline-fixtures.local/jobs/{j['posting_id']}",
            apply_url=f"https://offline-fixtures.local/jobs/{j['posting_id']}/apply",
        )
        session.add(snapshot)
        postings_created += 1

    session.commit()

    return {
        "status": "SUCCESS",
        "postings_seeded": postings_created,
        "source": "synthetic_fixtures",
        "message": "Seeded synthetic job postings for offline demonstration.",
    }
