"""Comprehensive integration tests for end-to-end Data Portability (all 18 entities).

Verifies:
1. Complete export coverage across all 18 tables.
2. Complete absence of credentials, tokens, or private secrets in backup.
3. Deterministic preview-to-commit token binding and rejection of mismatched tokens.
4. Default overwrite_existing=False preserving existing candidate profile & settings.
5. Fresh instance full round-trip restore verifying topological integrity and subsequent export.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import os
import uuid
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.models import (
    AnswerBankItem,
    ApplicationStatusHistory,
    CandidateDocument,
    CandidateDocumentBlob,
    CandidateDocumentVersion,
    CandidateFact,
    CandidateFactEvidence,
    CandidateProfile,
    CompensationAssessment,
    CompensationPreference,
    CompensationPreferenceAudit,
    DiscoveryRun,
    EmployerSubscription,
    JobPosting,
    JobPostingSnapshot,
    JobSource,
    SubmissionPlanModel,
    TrackedApplication,
    UserSettingsModel,
)
from backend.app.domain.data_portability import (
    EXPORT_FORMAT_VERSION,
    DataPortabilityError,
    compute_bundle_checksum,
)
from backend.app.main import create_app
from backend.app.services import candidate_profile as profile_service
from backend.app.services import user_settings as settings_service
from backend.app.services.data_portability import (
    commit_import_dataset,
    export_dataset,
    preview_import_dataset,
)


def local_headers() -> dict[str, str]:
    return {"host": "localhost", "origin": "http://localhost"}


@pytest.fixture
def populated_engine():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    config = Config("backend/alembic.ini")
    with engine.connect() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "head")

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        # 1. Candidate Profile
        p = profile_service.get_or_create_profile(session)
        p.name = "Elena Rostova"
        p.headline = "Principal Distributed Systems Architect"
        p.summary = "Extensive experience in resilient consensus protocols and distributed databases."
        p.skills = [{"name": "Rust"}, {"name": "Raft"}, {"name": "PostgreSQL"}]

        # 2. User Settings
        s = settings_service.get_or_create_settings_record(session)
        s.target_roles = ["Principal Architect", "Staff Engineer"]
        s.same_company_cooldown_days = 30
        s.daily_application_cap = 6
        s.dry_run_simulation_mode = True

        # 3. Job Sources
        js = session.get(JobSource, "lever")
        if js is None:
            js = JobSource(
                source_name="lever",
                display_name="Lever",
                capability_status="VERIFIED_READ_ONLY",
                is_enabled=True,
            )
            session.add(js)

        # 4. Employer Subscriptions
        sub_id = str(uuid.uuid4())
        sub = EmployerSubscription(
            id=sub_id,
            source_name="lever",
            employer_handle="canonical",
            display_name="Canonical Ltd",
            is_enabled=True,
            lease_token="SECRET_LEASE_TOKEN_DO_NOT_EXPORT",
            lease_expires_at=datetime.now(timezone.utc),
        )
        session.add(sub)

        # 5. Discovery Runs
        run_id = str(uuid.uuid4())
        run = DiscoveryRun(
            id=run_id,
            subscription_id=sub_id,
            status="SUCCEEDED",
            finished_at=datetime.now(timezone.utc),
            items_seen_count=1,
            items_new_count=1,
        )
        session.add(run)

        # 6. Job Postings
        posting_pk = str(uuid.uuid4())
        job_hash = "a" * 64
        job = JobPosting(
            id=posting_pk,
            subscription_id=sub_id,
            posting_id="dist-sys-eng-01",
            current_raw_hash=job_hash,
            lifecycle_status="ACTIVE",
            last_seen_run_id=run_id,
        )
        session.add(job)

        # 7. Job Posting Snapshots
        snap_id = str(uuid.uuid4())
        snap = JobPostingSnapshot(
            id=snap_id,
            subscription_id=sub_id,
            posting_id=posting_pk,
            run_id=run_id,
            source_raw_hash=job_hash,
            title="Principal Systems Engineer",
            description_plain="Work on high-concurrency consensus systems.",
            published_at=datetime.now(timezone.utc),
            publication_date_status="EXACT",
        )
        session.add(snap)

        # 8. Compensation Preferences
        cp = session.get(CompensationPreference, 1)
        cp.amount = Decimal("3000000.00")
        cp.currency = "INR"
        cp.period = "YEAR"

        # 9. Compensation Preference Audits
        audit = CompensationPreferenceAudit(
            preference_id=1,
            previous_amount=Decimal("2500000.00"),
            new_amount=Decimal("3000000.00"),
            currency="INR",
            period="YEAR",
            settings_version=2,
            actor_type="USER",
            actor_id="default",
        )
        session.add(audit)

        # 10. Compensation Assessments
        ca_id = str(uuid.uuid4())
        ca = CompensationAssessment(
            id=ca_id,
            job_reference="canonical:dist-sys-eng-01",
            reported_status="PAID",
            evidence_verification_state="VERIFIED",
            source_amount=Decimal("3500000.00"),
            source_currency="INR",
            source_period="YEAR",
            threshold_amount=Decimal("3000000.00"),
            threshold_currency="INR",
            threshold_period="YEAR",
            threshold_version=1,
            outcome="MEETS_THRESHOLD",
            reason_code="VERIFIED_SATISFIES_THRESHOLD",
            explanation="Compensation satisfies minimum threshold.",
        )
        session.add(ca)

        # 11. Candidate Documents & Blobs & Versions
        doc_id = str(uuid.uuid4())
        doc = CandidateDocument(id=doc_id, display_name="Elena Resume 2026.pdf", state="ACTIVE")
        session.add(doc)

        blob_hash = "b" * 64
        blob = CandidateDocumentBlob(
            content_hash=blob_hash,
            storage_key=f"blobs/{blob_hash[:2]}/{blob_hash[2:4]}/{blob_hash}.txt",
            media_type="text/plain",
            byte_size=1024,
        )
        session.add(blob)

        ver_id = str(uuid.uuid4())
        ver = CandidateDocumentVersion(
            id=ver_id,
            document_id=doc_id,
            version_number=1,
            blob_hash=blob_hash,
            original_filename="resume.txt",
        )
        session.add(ver)

        # 14. Candidate Facts
        fact_id = str(uuid.uuid4())
        fact = CandidateFact(
            id=fact_id,
            fact_type="SKILL",
            value_json={"name": "Rust", "experience_years": 8},
            value_hash="c" * 64,
            verification_state="USER_VERIFIED",
        )
        session.add(fact)

        # 15. Candidate Fact Evidence
        ev_id = str(uuid.uuid4())
        ev = CandidateFactEvidence(
            id=ev_id,
            fact_id=fact_id,
            document_version_id=ver_id,
            byte_start=0,
            byte_end=50,
            evidence_hash="d" * 64,
        )
        session.add(ev)

        # 16. Answer Bank Items
        ans_id = str(uuid.uuid4())
        ans = AnswerBankItem(
            id=ans_id,
            question="What is your experience with distributed consensus?",
            answer="Over 8 years implementing Raft and Paxos protocols in production.",
            category="technical",
            fact_ids=[fact_id],
            reuse_consent=False,
            version=1,
        )
        session.add(ans)

        # 17. Tracked Applications
        app_id = str(uuid.uuid4())
        app_model = TrackedApplication(
            id=app_id,
            job_posting_id=posting_pk,
            status="PREPARING",
            notes="Targeting Q4 opening",
            reviewed_resume_markdown="# Elena Rostova\nStaff Systems Engineer",
            reviewed_cover_letter_markdown="Dear Hiring Manager,\nI am writing to apply...",
            version=1,
        )
        session.add(app_model)

        # 18. Application Status History
        hist = ApplicationStatusHistory(
            application_id=app_id,
            from_status="SAVED",
            to_status="PREPARING",
            transition_reason="Draft generated by candidate",
        )
        session.add(hist)

        # 19. Submission Plans
        plan_id = str(uuid.uuid4())
        plan = SubmissionPlanModel(
            id=plan_id,
            application_id=app_id,
            job_posting_id=posting_pk,
            employer_handle="canonical",
            target_role="Principal Systems Engineer",
            resume_sha256="e" * 64,
            cover_letter_sha256="f" * 64,
            packet_sha256="1" * 64,
            is_compensation_eligible=True,
            is_cooldown_clear=True,
            status="PREPARED",
        )
        session.add(plan)

        session.commit()

    return engine


def test_export_contains_all_entities_without_secrets(populated_engine):
    factory = sessionmaker(bind=populated_engine, expire_on_commit=False)
    with factory() as session:
        bundle = export_dataset(session)

    manifest = bundle["manifest"]
    assert manifest["format_version"] == EXPORT_FORMAT_VERSION
    assert manifest["product"] == "hire-steward"
    assert manifest["checksum_sha256"] == compute_bundle_checksum(bundle)

    # All 18 entities must be present
    counts = manifest["record_counts"]
    assert counts["candidate_profile"] == 1
    assert counts["user_settings"] == 1
    assert counts["job_sources"] >= 1
    assert counts["employer_subscriptions"] >= 1
    assert counts["discovery_runs"] >= 1
    assert counts["job_postings"] >= 1
    assert counts["job_posting_snapshots"] >= 1
    assert counts["compensation_preferences"] == 1
    assert counts["compensation_preference_audits"] >= 1
    assert counts["compensation_assessments"] >= 1
    assert counts["candidate_documents"] >= 1
    assert counts["candidate_document_blobs"] >= 1
    assert counts["candidate_document_versions"] >= 1
    assert counts["candidate_facts"] >= 1
    assert counts["candidate_fact_evidence"] >= 1
    assert counts["answer_bank_items"] >= 1
    assert counts["tracked_applications"] >= 1
    assert counts["application_status_history"] >= 1
    assert counts["submission_plans"] >= 1

    # Security check: secret token scrubbed from subscriptions
    sub_exported = bundle["employer_subscriptions"][0]
    assert "lease_token" not in sub_exported
    assert "lease_expires_at" not in sub_exported
    raw_json = str(bundle)
    assert "SECRET_LEASE_TOKEN_DO_NOT_EXPORT" not in raw_json


def test_preview_binds_preview_token(populated_engine):
    factory = sessionmaker(bind=populated_engine, expire_on_commit=False)
    with factory() as session:
        bundle = export_dataset(session)
        preview = preview_import_dataset(session, bundle)

    assert preview["is_valid"] is True
    assert preview["checksum_verified"] is True
    assert preview["preview_token"] is not None
    assert len(preview["preview_token"]) == 64
    assert preview["collision_counts"]["candidate_profile"] == 1
    assert preview["collision_counts"]["submission_plans"] >= 1


def test_commit_rejects_preview_token_mismatch(populated_engine):
    factory = sessionmaker(bind=populated_engine, expire_on_commit=False)
    with factory() as session:
        bundle = export_dataset(session)
        with pytest.raises(DataPortabilityError) as exc_info:
            commit_import_dataset(session, bundle, preview_token="0" * 64)
        assert "PREVIEW_TOKEN_MISMATCH" in str(exc_info.value)


def test_commit_overwrite_existing_false_preserves_destination_data(populated_engine):
    factory = sessionmaker(bind=populated_engine, expire_on_commit=False)
    with factory() as session:
        bundle = export_dataset(session)

    # Modify the bundle candidate profile
    bundle_copy = dict(bundle)
    bundle_copy["candidate_profile"] = dict(bundle["candidate_profile"])
    bundle_copy["candidate_profile"]["headline"] = "OVERWRITTEN HEADLINE"
    bundle_copy["manifest"] = dict(bundle["manifest"])
    bundle_copy["manifest"]["checksum_sha256"] = compute_bundle_checksum(bundle_copy)

    with factory() as session:
        # Commit with overwrite_existing=False (default)
        result = commit_import_dataset(session, bundle_copy, overwrite_existing=False)
        assert result["status"] == "COMPLETED"

        # Verify destination headline was NOT overwritten
        p = session.get(CandidateProfile, "default")
        assert p.headline == "Principal Distributed Systems Architect"


def test_fresh_instance_full_round_trip_restore(populated_engine):
    factory = sessionmaker(bind=populated_engine, expire_on_commit=False)
    with factory() as session:
        bundle = export_dataset(session)

    # Create completely clean destination database
    clean_engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    config = Config("backend/alembic.ini")
    with clean_engine.connect() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "head")

    clean_factory = sessionmaker(bind=clean_engine, expire_on_commit=False)
    with clean_factory() as clean_session:
        # Preview into clean instance
        preview = preview_import_dataset(clean_session, bundle)
        assert preview["is_valid"] is True
        assert preview["checksum_verified"] is True
        token = preview["preview_token"]

        # Commit into clean instance with overwrite_existing=True to populate clean singleton defaults
        commit_result = commit_import_dataset(
            clean_session,
            bundle,
            preview_token=token,
            overwrite_existing=True,
        )
        assert commit_result["status"] == "COMPLETED"

        # Verify all restored records in clean database
        p = clean_session.get(CandidateProfile, "default")
        assert p.name == "Elena Rostova"
        assert p.headline == "Principal Distributed Systems Architect"

        s = clean_session.get(UserSettingsModel, "default")
        assert s.same_company_cooldown_days == 30
        assert s.daily_application_cap == 6

        cp = clean_session.get(CompensationPreference, 1)
        assert cp.amount == Decimal("3000000.00")

        app = clean_session.query(TrackedApplication).first()
        assert app.status == "PREPARING"
        assert "Elena Rostova" in app.reviewed_resume_markdown

        plan = clean_session.query(SubmissionPlanModel).first()
        assert plan.employer_handle == "canonical"
        assert plan.is_compensation_eligible is True
        assert plan.is_cooldown_clear is True

        fact = clean_session.query(CandidateFact).first()
        assert fact.fact_type == "SKILL"
        assert fact.verification_state == "USER_VERIFIED"

        ans = clean_session.query(AnswerBankItem).first()
        assert "distributed consensus" in ans.question
        assert ans.reuse_consent is False  # Explicit consent default preserved

        # Verify subsequent export on the restored instance produces matching record counts
        restored_bundle = export_dataset(clean_session)
        orig_counts = bundle["manifest"]["record_counts"]
        restored_counts = restored_bundle["manifest"]["record_counts"]
        assert orig_counts == restored_counts
