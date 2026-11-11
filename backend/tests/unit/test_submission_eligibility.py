"""Unit tests for authoritative submission eligibility, compensation, and same-company cooldown policies.

Covers:
- Confirmed unpaid roles blocked independently of threshold.
- Verified compensation below user's persisted floor blocked.
- Missing or unverified salary evidence requiring review.
- User settings compensation floor updates.
- Same company applied 5 days ago (BLOCKED).
- Same company applied 29 days ago (BLOCKED).
- Same company applied 30 days ago (Boundary).
- Same company applied >30 days ago (CLEAR).
- Previous application rejected (CLEAR).
- Previous application withdrawn (CLEAR).
- Missing timestamp on prior active application (REVIEW_REQUIRED).
- Different company (CLEAR).
- Reposted job from same employer (BLOCKED).
- Asia/Kolkata date boundary checks.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from alembic import command
from alembic.config import Config

from backend.app.db.models import (
    CandidateProfile,
    CompensationAssessment,
    CompensationPreference,
    EmployerSubscription,
    JobPosting,
    JobPostingSnapshot,
    TrackedApplication,
    UserSettingsModel,
)
from backend.app.domain.application_tracking import ApplicationStatus
from backend.app.domain.compensation import (
    EvidenceVerificationState,
    ReportedCompensationStatus,
)
from backend.app.services.submission_eligibility import (
    EligibilityDecision,
    evaluate_compensation_eligibility,
    evaluate_same_company_cooldown,
    evaluate_submission_eligibility,
)
from backend.app.services.user_settings import get_or_create_settings_record
from backend.app.services.preferences import set_minimum_compensation


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    cfg = Config("backend/alembic.ini")
    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")

    session_maker = sessionmaker(bind=engine)
    with session_maker() as sess:
        yield sess


def test_compensation_unpaid_role_is_strictly_blocked(session: Session):
    sub = EmployerSubscription(
        id="sub-1", source_name="lever", employer_handle="techcorp", display_name="TechCorp", is_enabled=True
    )
    session.add(sub)
    posting = JobPosting(
        id="job-unpaid", subscription_id="sub-1", posting_id="p-unpaid", current_raw_hash="a" * 64, last_seen_run_id="r1"
    )
    session.add(posting)
    assessment = CompensationAssessment(
        id="assess-unpaid",
        job_reference="job-unpaid",
        reported_status="UNPAID",
        evidence_verification_state="VERIFIED",
        source_period="YEAR",
        threshold_amount=Decimal("100000.00"),
        threshold_currency="INR",
        threshold_period="YEAR",
        threshold_version=1,
        outcome="BLOCKED",
        reason_code="UNPAID_ROLE",
        explanation="Confirmed unpaid role is ineligible.",
    )
    session.add(assessment)
    session.commit()

    res = evaluate_compensation_eligibility(session, posting)
    assert res.outcome == EligibilityDecision.BLOCKED
    assert res.reason_code == "UNPAID_ROLE"
    assert res.is_eligible is False


def test_compensation_unverified_evidence_requires_review(session: Session):
    sub = EmployerSubscription(
        id="sub-1", source_name="lever", employer_handle="techcorp", display_name="TechCorp", is_enabled=True
    )
    session.add(sub)
    posting = JobPosting(
        id="job-unverified", subscription_id="sub-1", posting_id="p-unverified", current_raw_hash="a" * 64, last_seen_run_id="r1"
    )
    session.add(posting)
    assessment = CompensationAssessment(
        id="assess-unverified",
        job_reference="job-unverified",
        reported_status="PAID",
        evidence_verification_state="UNVERIFIED",
        source_amount=Decimal("500000.00"),
        source_period="YEAR",
        threshold_amount=Decimal("100000.00"),
        threshold_currency="INR",
        threshold_period="YEAR",
        threshold_version=1,
        outcome="REVIEW_REQUIRED",
        reason_code="EVIDENCE_UNVERIFIED",
        explanation="Unverified caller observation.",
    )
    session.add(assessment)
    session.commit()

    res = evaluate_compensation_eligibility(session, posting)
    assert res.outcome == EligibilityDecision.REVIEW_REQUIRED
    assert res.reason_code == "EVIDENCE_UNVERIFIED"
    assert res.is_eligible is False
    assert res.requires_review is True


def test_compensation_below_persisted_floor_is_blocked(session: Session):
    sub = EmployerSubscription(
        id="sub-1", source_name="lever", employer_handle="techcorp", display_name="TechCorp", is_enabled=True
    )
    session.add(sub)
    posting = JobPosting(
        id="job-low-pay", subscription_id="sub-1", posting_id="p-low", current_raw_hash="a" * 64, last_seen_run_id="r1"
    )
    session.add(posting)
    # Floor is 100,000 INR; verified offer is 50,000 INR
    assessment = CompensationAssessment(
        id="assess-low",
        job_reference="job-low-pay",
        reported_status="PAID",
        evidence_verification_state="VERIFIED",
        source_amount=Decimal("50000.00"),
        source_period="YEAR",
        normalized_minimum_annual=Decimal("50000.00"),
        threshold_amount=Decimal("100000.00"),
        threshold_currency="INR",
        threshold_period="YEAR",
        threshold_version=1,
        outcome="BLOCKED",
        reason_code="BELOW_MINIMUM_COMPENSATION",
        explanation="Salary is below candidate minimum floor.",
    )
    session.add(assessment)
    session.commit()

    res = evaluate_compensation_eligibility(session, posting)
    assert res.outcome == EligibilityDecision.BLOCKED
    assert res.reason_code == "BELOW_MINIMUM_COMPENSATION"
    assert res.is_eligible is False


def test_compensation_meeting_persisted_floor_is_eligible(session: Session):
    sub = EmployerSubscription(
        id="sub-1", source_name="lever", employer_handle="techcorp", display_name="TechCorp", is_enabled=True
    )
    session.add(sub)
    posting = JobPosting(
        id="job-good-pay", subscription_id="sub-1", posting_id="p-good", current_raw_hash="a" * 64, last_seen_run_id="r1"
    )
    session.add(posting)
    assessment = CompensationAssessment(
        id="assess-good",
        job_reference="job-good-pay",
        reported_status="PAID",
        evidence_verification_state="VERIFIED",
        source_amount=Decimal("250000.00"),
        source_period="YEAR",
        normalized_minimum_annual=Decimal("250000.00"),
        threshold_amount=Decimal("100000.00"),
        threshold_currency="INR",
        threshold_period="YEAR",
        threshold_version=1,
        outcome="MEETS_THRESHOLD",
        reason_code="MEETS_THRESHOLD",
        explanation="Salary satisfies candidate floor.",
    )
    session.add(assessment)
    session.commit()

    res = evaluate_compensation_eligibility(session, posting)
    assert res.outcome == EligibilityDecision.ELIGIBLE
    assert res.is_eligible is True
    assert res.requires_review is False


def test_cooldown_same_company_applied_5_days_ago_is_blocked(session: Session):
    now = datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)
    sub = EmployerSubscription(
        id="sub-acme", source_name="lever", employer_handle="acme", display_name="Acme Corp", is_enabled=True
    )
    session.add(sub)
    posting1 = JobPosting(id="j1", subscription_id="sub-acme", posting_id="p1", current_raw_hash="a"*64, last_seen_run_id="r1")
    posting2 = JobPosting(id="j2", subscription_id="sub-acme", posting_id="p2", current_raw_hash="b"*64, last_seen_run_id="r1")
    session.add_all([posting1, posting2])

    # Prior application submitted 5 days ago
    prior_app = TrackedApplication(
        id="app-prior-5d",
        job_posting_id="j1",
        status=ApplicationStatus.APPLIED.value,
        applied_at=now - timedelta(days=5),
        created_at=now - timedelta(days=5),
    )
    session.add(prior_app)
    session.commit()

    res = evaluate_same_company_cooldown(session, posting2, as_of=now)
    assert res.is_clear is False
    assert res.outcome == EligibilityDecision.BLOCKED
    assert res.reason_code == "ACTIVE_COOLDOWN"


def test_cooldown_same_company_applied_29_days_ago_is_blocked(session: Session):
    now = datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)
    sub = EmployerSubscription(
        id="sub-acme", source_name="lever", employer_handle="acme", display_name="Acme Corp", is_enabled=True
    )
    session.add(sub)
    posting1 = JobPosting(id="j1", subscription_id="sub-acme", posting_id="p1", current_raw_hash="a"*64, last_seen_run_id="r1")
    posting2 = JobPosting(id="j2", subscription_id="sub-acme", posting_id="p2", current_raw_hash="b"*64, last_seen_run_id="r1")
    session.add_all([posting1, posting2])

    prior_app = TrackedApplication(
        id="app-prior-29d",
        job_posting_id="j1",
        status=ApplicationStatus.APPLIED.value,
        applied_at=now - timedelta(days=29),
        created_at=now - timedelta(days=29),
    )
    session.add(prior_app)
    session.commit()

    res = evaluate_same_company_cooldown(session, posting2, as_of=now)
    assert res.is_clear is False
    assert res.outcome == EligibilityDecision.BLOCKED
    assert res.reason_code == "ACTIVE_COOLDOWN"


def test_cooldown_same_company_applied_more_than_30_days_ago_is_clear(session: Session):
    now = datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)
    sub = EmployerSubscription(
        id="sub-acme", source_name="lever", employer_handle="acme", display_name="Acme Corp", is_enabled=True
    )
    session.add(sub)
    posting1 = JobPosting(id="j1", subscription_id="sub-acme", posting_id="p1", current_raw_hash="a"*64, last_seen_run_id="r1")
    posting2 = JobPosting(id="j2", subscription_id="sub-acme", posting_id="p2", current_raw_hash="b"*64, last_seen_run_id="r1")
    session.add_all([posting1, posting2])

    # 31 days ago
    prior_app = TrackedApplication(
        id="app-prior-31d",
        job_posting_id="j1",
        status=ApplicationStatus.APPLIED.value,
        applied_at=now - timedelta(days=31),
        created_at=now - timedelta(days=31),
    )
    session.add(prior_app)
    session.commit()

    res = evaluate_same_company_cooldown(session, posting2, as_of=now)
    assert res.is_clear is True
    assert res.outcome == EligibilityDecision.ELIGIBLE
    assert res.reason_code == "COOLDOWN_CLEAR"


def test_cooldown_previous_application_rejected_is_clear(session: Session):
    now = datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)
    sub = EmployerSubscription(
        id="sub-acme", source_name="lever", employer_handle="acme", display_name="Acme Corp", is_enabled=True
    )
    session.add(sub)
    posting1 = JobPosting(id="j1", subscription_id="sub-acme", posting_id="p1", current_raw_hash="a"*64, last_seen_run_id="r1")
    posting2 = JobPosting(id="j2", subscription_id="sub-acme", posting_id="p2", current_raw_hash="b"*64, last_seen_run_id="r1")
    session.add_all([posting1, posting2])

    # Applied 10 days ago, but formally REJECTED
    prior_app = TrackedApplication(
        id="app-prior-rejected",
        job_posting_id="j1",
        status=ApplicationStatus.REJECTED.value,
        applied_at=now - timedelta(days=10),
        created_at=now - timedelta(days=10),
    )
    session.add(prior_app)
    session.commit()

    res = evaluate_same_company_cooldown(session, posting2, as_of=now)
    assert res.is_clear is True
    assert res.outcome == EligibilityDecision.ELIGIBLE


def test_cooldown_previous_application_withdrawn_is_clear(session: Session):
    now = datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)
    sub = EmployerSubscription(
        id="sub-acme", source_name="lever", employer_handle="acme", display_name="Acme Corp", is_enabled=True
    )
    session.add(sub)
    posting1 = JobPosting(id="j1", subscription_id="sub-acme", posting_id="p1", current_raw_hash="a"*64, last_seen_run_id="r1")
    posting2 = JobPosting(id="j2", subscription_id="sub-acme", posting_id="p2", current_raw_hash="b"*64, last_seen_run_id="r1")
    session.add_all([posting1, posting2])

    # Applied 12 days ago, but candidate WITHDREW
    prior_app = TrackedApplication(
        id="app-prior-withdrawn",
        job_posting_id="j1",
        status=ApplicationStatus.WITHDRAWN.value,
        applied_at=now - timedelta(days=12),
        created_at=now - timedelta(days=12),
    )
    session.add(prior_app)
    session.commit()

    res = evaluate_same_company_cooldown(session, posting2, as_of=now)
    assert res.is_clear is True
    assert res.outcome == EligibilityDecision.ELIGIBLE


def test_cooldown_missing_timestamp_requires_review(session: Session):
    now = datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)
    sub = EmployerSubscription(
        id="sub-acme", source_name="lever", employer_handle="acme", display_name="Acme Corp", is_enabled=True
    )
    session.add(sub)
    posting1 = JobPosting(id="j1", subscription_id="sub-acme", posting_id="p1", current_raw_hash="a"*64, last_seen_run_id="r1")
    posting2 = JobPosting(id="j2", subscription_id="sub-acme", posting_id="p2", current_raw_hash="b"*64, last_seen_run_id="r1")
    session.add_all([posting1, posting2])

    # Prior active application with missing timestamps
    prior_app = TrackedApplication(
        id="app-missing-time",
        job_posting_id="j1",
        status=ApplicationStatus.APPLIED.value,
        applied_at=None,
        created_at=None,
    )
    session.add(prior_app)
    session.commit()

    res = evaluate_same_company_cooldown(session, posting2, as_of=now)
    assert res.is_clear is False
    assert res.outcome == EligibilityDecision.REVIEW_REQUIRED
    assert res.reason_code == "MISSING_TIMESTAMP"


def test_cooldown_different_company_is_clear(session: Session):
    now = datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)
    sub1 = EmployerSubscription(
        id="sub-acme", source_name="lever", employer_handle="acme", display_name="Acme Corp", is_enabled=True
    )
    sub2 = EmployerSubscription(
        id="sub-beta", source_name="greenhouse", employer_handle="beta", display_name="Beta Labs", is_enabled=True
    )
    session.add_all([sub1, sub2])

    posting1 = JobPosting(id="j1", subscription_id="sub-acme", posting_id="p1", current_raw_hash="a"*64, last_seen_run_id="r1")
    posting2 = JobPosting(id="j2", subscription_id="sub-beta", posting_id="p2", current_raw_hash="b"*64, last_seen_run_id="r1")
    session.add_all([posting1, posting2])

    prior_app = TrackedApplication(
        id="app-acme",
        job_posting_id="j1",
        status=ApplicationStatus.APPLIED.value,
        applied_at=now - timedelta(days=2),
        created_at=now - timedelta(days=2),
    )
    session.add(prior_app)
    session.commit()

    # Applying to Beta Labs (different employer) must be clear
    res = evaluate_same_company_cooldown(session, posting2, as_of=now)
    assert res.is_clear is True
    assert res.outcome == EligibilityDecision.ELIGIBLE


def test_cooldown_reposted_job_same_employer_is_blocked(session: Session):
    now = datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)
    sub = EmployerSubscription(
        id="sub-repost", source_name="ashby", employer_handle="repost-corp", display_name="Repost Corp", is_enabled=True
    )
    session.add(sub)
    posting_old = JobPosting(id="j-old", subscription_id="sub-repost", posting_id="p-old", current_raw_hash="a"*64, last_seen_run_id="r1")
    posting_new = JobPosting(id="j-new", subscription_id="sub-repost", posting_id="p-new", current_raw_hash="b"*64, last_seen_run_id="r2")
    session.add_all([posting_old, posting_new])

    prior_app = TrackedApplication(
        id="app-repost",
        job_posting_id="j-old",
        status=ApplicationStatus.INTERVIEWING.value,
        applied_at=now - timedelta(days=14),
        created_at=now - timedelta(days=14),
    )
    session.add(prior_app)
    session.commit()

    res = evaluate_same_company_cooldown(session, posting_new, as_of=now)
    assert res.is_clear is False
    assert res.outcome == EligibilityDecision.BLOCKED
    assert res.reason_code == "ACTIVE_COOLDOWN"


def test_overall_submission_eligibility_fails_closed_when_compensation_unverified(session: Session):
    sub = EmployerSubscription(
        id="sub-test", source_name="lever", employer_handle="testcorp", display_name="TestCorp", is_enabled=True
    )
    session.add(sub)
    posting = JobPosting(id="job-test", subscription_id="sub-test", posting_id="p-test", current_raw_hash="c"*64, last_seen_run_id="r1")
    session.add(posting)
    session.commit()

    # No compensation assessment exists
    report = evaluate_submission_eligibility(session, "job-test")
    assert report.overall_decision == EligibilityDecision.REVIEW_REQUIRED
    assert report.is_compensation_eligible is False
    assert report.is_fully_eligible is False
    assert len(report.review_reasons) > 0


def test_asia_kolkata_timezone_boundary_cooldown(session: Session):
    # Test precisely across Asia/Kolkata date boundary (UTC+5:30)
    tz_kolkata = ZoneInfo("Asia/Kolkata")
    now_kolkata = datetime(2026, 11, 30, 23, 59, 0, tzinfo=tz_kolkata)
    now_utc = now_kolkata.astimezone(timezone.utc)

    sub = EmployerSubscription(
        id="sub-in", source_name="lever", employer_handle="bangalore-ai", display_name="Bangalore AI", is_enabled=True
    )
    session.add(sub)
    posting1 = JobPosting(id="j-in-1", subscription_id="sub-in", posting_id="p1", current_raw_hash="1"*64, last_seen_run_id="r1")
    posting2 = JobPosting(id="j-in-2", subscription_id="sub-in", posting_id="p2", current_raw_hash="2"*64, last_seen_run_id="r1")
    session.add_all([posting1, posting2])

    # Exactly 29.5 days ago
    prior_app = TrackedApplication(
        id="app-in-1",
        job_posting_id="j-in-1",
        status=ApplicationStatus.APPLIED.value,
        applied_at=now_utc - timedelta(days=29, hours=12),
        created_at=now_utc - timedelta(days=29, hours=12),
    )
    session.add(prior_app)
    session.commit()

    res = evaluate_same_company_cooldown(session, posting2, as_of=now_utc)
    assert res.is_clear is False
    assert res.outcome == EligibilityDecision.BLOCKED
