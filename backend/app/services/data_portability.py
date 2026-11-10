"""Service layer for export bundle creation, dry-run preview, and atomic restore (Stage 8).

Covers all application entities:
1. Candidate Profile
2. User Settings
3. Job Sources
4. Employer Subscriptions
5. Discovery Runs
6. Job Postings
7. Job Posting Snapshots
8. Compensation Preferences
9. Compensation Preference Audits
10. Compensation Assessments
11. Candidate Documents
12. Candidate Document Blobs
13. Candidate Document Versions
14. Candidate Facts
15. Candidate Fact Evidence
16. Answer Bank Items
17. Tracked Applications
18. Application Status History
19. Submission Plans
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from decimal import Decimal
import os
from pathlib import Path
from typing import Any
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from backend.app.db.models import (
    AnswerBankItem,
    ApplicationAttempt,
    ApplicationStatusHistory,
    AuditEvent,
    CandidateDocument,
    CandidateDocumentBlob,
    CandidateDocumentVersion,
    CandidateEvidenceStorageUsage,
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
from backend.app.domain.candidate_evidence import canonical_json_and_hash
from backend.app.domain.data_portability import (
    EXPORT_FORMAT_VERSION,
    DataPortabilityError,
    compute_bundle_checksum,
    compute_preview_token,
    sanitize_bundle_dictionary,
    validate_import_bundle_manifest,
)
from backend.app.evidence_config import evidence_settings_from_environment
from backend.app.services import answer_bank as answer_service
from backend.app.services import candidate_profile as profile_service
from backend.app.services import user_settings as settings_service


def _get_existing_tables(session: Session) -> set[str]:
    """Retrieve table names directly within session's active connection without resetting transaction state."""
    try:
        bind = session.get_bind()
        if bind is None:
            return set()
        if bind.dialect.name == "sqlite":
            rows = session.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' UNION ALL SELECT name FROM sqlite_temp_master WHERE type='table'")
            ).scalars().all()
            return set(rows)
        elif bind.dialect.name == "postgresql":
            rows = session.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")
            ).scalars().all()
            return set(rows)
        else:
            return set(inspect(bind).get_table_names())
    except Exception:
        return set()


def _safe_query_all(session: Session, model_cls: Any, existing_tables: set[str]) -> list[Any]:
    if model_cls.__tablename__ not in existing_tables:
        return []
    try:
        return list(session.scalars(select(model_cls)).all())
    except Exception:
        return []


def _parse_dt(val: Any) -> datetime | None:
    if val is None or isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(str(val))
    except Exception:
        return None


def _parse_dec(val: Any) -> Decimal | None:
    if val is None or isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except Exception:
        return None


def export_dataset(session: Session, storage_root: Path | None = None) -> dict[str, Any]:
    """Assemble complete application state, strip secrets, and package with signed manifest."""
    # Resolve evidence storage root if available
    resolved_storage_root: Path | None = storage_root
    if resolved_storage_root is None:
        env_settings = evidence_settings_from_environment()
        if env_settings is not None:
            resolved_storage_root = env_settings.storage_root

    existing_tables = _get_existing_tables(session)

    # 1. Candidate Profile
    prof_dict = None
    if "candidate_profiles" in existing_tables:
        profile = profile_service.get_or_create_profile(session)
        prof_dict = {
            "id": profile.id,
            "name": profile.name,
            "headline": profile.headline,
            "summary": profile.summary,
            "contact_info": profile.contact_info,
            "education": profile.education,
            "employment": profile.employment,
            "projects": profile.projects,
            "skills": profile.skills,
            "certifications": profile.certifications,
            "completeness_score": profile.completeness_score,
            "created_at": profile.created_at.isoformat() if profile.created_at else None,
            "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
        }

    # 2. User Settings
    settings_dict = None
    if "user_settings" in existing_tables:
        settings_dict = settings_service.get_user_settings(session)

    # 3. Job Sources
    job_sources_rows = _safe_query_all(session, JobSource, existing_tables)
    job_sources = [
        {
            "source_name": s.source_name,
            "display_name": s.display_name,
            "capability_status": s.capability_status,
            "is_enabled": s.is_enabled,
            "terms_reviewed_at": s.terms_reviewed_at.isoformat() if s.terms_reviewed_at else None,
            "terms_review_reference": s.terms_review_reference,
            "rate_limit_requests_per_minute": s.rate_limit_requests_per_minute,
            "min_poll_interval_seconds": s.min_poll_interval_seconds,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }
        for s in job_sources_rows
    ]

    # 4. Employer Subscriptions (scrubbing lease_token and lease_expires_at)
    subs_rows = _safe_query_all(session, EmployerSubscription, existing_tables)
    subscriptions = [
        {
            "id": sub.id,
            "source_name": sub.source_name,
            "employer_handle": sub.employer_handle,
            "display_name": sub.display_name,
            "is_enabled": sub.is_enabled,
            "created_at": sub.created_at.isoformat() if sub.created_at else None,
            "updated_at": sub.updated_at.isoformat() if sub.updated_at else None,
        }
        for sub in subs_rows
    ]

    # 5. Discovery Runs
    runs_rows = _safe_query_all(session, DiscoveryRun, existing_tables)
    runs = [
        {
            "id": r.id,
            "subscription_id": r.subscription_id,
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "current_skip": r.current_skip,
            "current_page_index": r.current_page_index,
            "page_limit": r.page_limit,
            "items_seen_count": r.items_seen_count,
            "items_new_count": r.items_new_count,
            "items_updated_count": r.items_updated_count,
            "items_duplicate_count": r.items_duplicate_count,
            "error_code": r.error_code,
            "error_message_redacted": r.error_message_redacted,
        }
        for r in runs_rows
    ]

    # 6. Job Postings
    postings_rows = _safe_query_all(session, JobPosting, existing_tables)
    postings = [
        {
            "id": p.id,
            "subscription_id": p.subscription_id,
            "posting_id": p.posting_id,
            "current_raw_hash": p.current_raw_hash,
            "lifecycle_status": p.lifecycle_status,
            "consecutive_misses_count": p.consecutive_misses_count,
            "version": p.version,
            "first_observed_at": p.first_observed_at.isoformat() if p.first_observed_at else None,
            "last_observed_at": p.last_observed_at.isoformat() if p.last_observed_at else None,
            "last_seen_run_id": p.last_seen_run_id,
        }
        for p in postings_rows
    ]

    # 7. Job Posting Snapshots
    snapshots_rows = _safe_query_all(session, JobPostingSnapshot, existing_tables)
    snapshots = [
        {
            "id": sn.id,
            "subscription_id": sn.subscription_id,
            "posting_id": sn.posting_id,
            "run_id": sn.run_id,
            "source_raw_hash": sn.source_raw_hash,
            "title": sn.title,
            "location": sn.location,
            "commitment": sn.commitment,
            "team": sn.team,
            "department": sn.department,
            "level": sn.level,
            "workplace_type": sn.workplace_type,
            "published_at": sn.published_at.isoformat() if sn.published_at else None,
            "publication_date_status": sn.publication_date_status,
            "raw_created_at_ms": sn.raw_created_at_ms,
            "canonical_url": sn.canonical_url,
            "apply_url": sn.apply_url,
            "description_plain": sn.description_plain,
            "description_html": sn.description_html,
            "lists_json": sn.lists_json,
            "additional_plain": sn.additional_plain,
            "captured_at": sn.captured_at.isoformat() if sn.captured_at else None,
        }
        for sn in snapshots_rows
    ]

    # 8. Compensation Preferences
    comp_prefs = []
    if "compensation_preferences" in existing_tables:
        comp_pref = session.get(CompensationPreference, 1)
        if comp_pref:
            comp_prefs.append({
                "id": comp_pref.id,
                "amount": str(comp_pref.amount),
                "currency": comp_pref.currency,
                "period": comp_pref.period,
                "version": comp_pref.version,
                "updated_at": comp_pref.updated_at.isoformat() if comp_pref.updated_at else None,
            })

    # 9. Compensation Preference Audits
    comp_audits_rows = _safe_query_all(session, CompensationPreferenceAudit, existing_tables)
    comp_audits = [
        {
            "id": a.id,
            "preference_id": a.preference_id,
            "previous_amount": str(a.previous_amount),
            "new_amount": str(a.new_amount),
            "currency": a.currency,
            "period": a.period,
            "settings_version": a.settings_version,
            "actor_type": a.actor_type,
            "actor_id": a.actor_id,
            "changed_at": a.changed_at.isoformat() if a.changed_at else None,
        }
        for a in comp_audits_rows
    ]

    # 10. Compensation Assessments
    comp_assessments_rows = _safe_query_all(session, CompensationAssessment, existing_tables)
    comp_assessments = [
        {
            "id": ca.id,
            "job_reference": ca.job_reference,
            "source_status": ca.reported_status,
            "evidence_verification_state": ca.evidence_verification_state,
            "source_amount": str(ca.source_amount) if ca.source_amount is not None else None,
            "source_minimum": str(ca.source_minimum) if ca.source_minimum is not None else None,
            "source_maximum": str(ca.source_maximum) if ca.source_maximum is not None else None,
            "source_currency": ca.source_currency,
            "source_period": ca.source_period,
            "source_recurring": ca.source_recurring,
            "evidence_reference": ca.evidence_reference,
            "threshold_amount": str(ca.threshold_amount),
            "threshold_currency": ca.threshold_currency,
            "threshold_period": ca.threshold_period,
            "threshold_version": ca.threshold_version,
            "normalized_minimum_annual": str(ca.normalized_minimum_annual) if ca.normalized_minimum_annual is not None else None,
            "normalized_maximum_annual": str(ca.normalized_maximum_annual) if ca.normalized_maximum_annual is not None else None,
            "conversion_basis": ca.conversion_basis,
            "outcome": ca.outcome,
            "reason_code": ca.reason_code,
            "explanation": ca.explanation,
            "created_at": ca.created_at.isoformat() if ca.created_at else None,
        }
        for ca in comp_assessments_rows
    ]

    # 11. Candidate Documents
    docs_rows = _safe_query_all(session, CandidateDocument, existing_tables)
    candidate_documents = [
        {
            "id": d.id,
            "display_name": d.display_name,
            "state": d.state,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "retired_at": d.retired_at.isoformat() if d.retired_at else None,
        }
        for d in docs_rows
    ]

    # 12. Candidate Document Blobs
    blobs_rows = _safe_query_all(session, CandidateDocumentBlob, existing_tables)
    candidate_document_blobs = []
    for b in blobs_rows:
        blob_entry: dict[str, Any] = {
            "content_hash": b.content_hash,
            "storage_key": b.storage_key,
            "media_type": b.media_type,
            "byte_size": b.byte_size,
            "created_at": b.created_at.isoformat() if b.created_at else None,
        }
        if resolved_storage_root:
            blob_path = resolved_storage_root / b.storage_key
            if blob_path.exists():
                try:
                    raw_blob_bytes = blob_path.read_bytes()
                    blob_entry["content_base64"] = base64.b64encode(raw_blob_bytes).decode("ascii")
                    try:
                        blob_entry["content_text"] = raw_blob_bytes.decode("utf-8")
                    except Exception:
                        pass
                except Exception:
                    pass
        candidate_document_blobs.append(blob_entry)

    # 13. Candidate Document Versions
    versions_rows = _safe_query_all(session, CandidateDocumentVersion, existing_tables)
    candidate_document_versions = [
        {
            "id": v.id,
            "document_id": v.document_id,
            "version_number": v.version_number,
            "blob_hash": v.blob_hash,
            "text_artifact_hash": getattr(v, "text_artifact_hash", None) or v.blob_hash,
            "original_filename": v.original_filename,
            "ingested_at": v.ingested_at.isoformat() if v.ingested_at else None,
            "extraction_status": v.extraction_status,
            "extraction_error_code": v.extraction_error_code,
            "extractor_version": v.extractor_version,
        }
        for v in versions_rows
    ]

    # 14. Candidate Facts
    facts_rows = _safe_query_all(session, CandidateFact, existing_tables)
    candidate_facts = [
        {
            "id": f.id,
            "fact_type": f.fact_type,
            "value_json": f.value_json,
            "value": f.value_json,
            "value_hash": f.value_hash,
            "verification_state": f.verification_state,
            "supersedes_fact_id": f.supersedes_fact_id,
            "created_at": f.created_at.isoformat() if f.created_at else None,
        }
        for f in facts_rows
    ]

    # 15. Candidate Fact Evidence
    evidence_rows = _safe_query_all(session, CandidateFactEvidence, existing_tables)
    candidate_fact_evidence = [
        {
            "id": ev.id,
            "fact_id": ev.fact_id,
            "document_version_id": ev.document_version_id,
            "byte_start": ev.byte_start,
            "byte_end": ev.byte_end,
            "evidence_hash": ev.evidence_hash,
            "method": ev.method,
            "created_at": ev.created_at.isoformat() if ev.created_at else None,
        }
        for ev in evidence_rows
    ]

    # 16. Answer Bank Items
    answers = []
    if "answer_bank_items" in existing_tables:
        answers_rows = answer_service.list_answer_items(session, include_revoked=True)
        answers = [
            {
                "id": a.id,
                "question": a.question,
                "answer": a.answer,
                "category": a.category,
                "fact_ids": a.fact_ids,
                "reuse_consent": a.reuse_consent,
                "version": a.version,
                "is_revoked": a.is_revoked,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "updated_at": a.updated_at.isoformat() if a.updated_at else None,
            }
            for a in answers_rows
        ]

    # 17. Tracked Applications
    apps_rows = _safe_query_all(session, TrackedApplication, existing_tables)
    apps = [
        {
            "id": app.id,
            "job_posting_id": app.job_posting_id,
            "status": app.status,
            "notes": app.notes,
            "follow_up_deadline": app.follow_up_deadline.isoformat() if app.follow_up_deadline else None,
            "next_interview_at": app.next_interview_at.isoformat() if app.next_interview_at else None,
            "applied_at": app.applied_at.isoformat() if app.applied_at else None,
            "last_status_change_at": app.last_status_change_at.isoformat() if app.last_status_change_at else None,
            "submitted_resume_snapshot": app.submitted_resume_snapshot,
            "submitted_cover_letter_snapshot": app.submitted_cover_letter_snapshot,
            "submitted_resume_sha256": app.submitted_resume_sha256,
            "submitted_cover_letter_sha256": app.submitted_cover_letter_sha256,
            "reviewed_resume_markdown": app.reviewed_resume_markdown,
            "reviewed_cover_letter_markdown": app.reviewed_cover_letter_markdown,
            "reviewed_at": app.reviewed_at.isoformat() if app.reviewed_at else None,
            "version": app.version,
            "created_at": app.created_at.isoformat() if app.created_at else None,
            "updated_at": app.updated_at.isoformat() if app.updated_at else None,
        }
        for app in apps_rows
    ]

    # 18. Application Status History
    history_rows = _safe_query_all(session, ApplicationStatusHistory, existing_tables)
    app_history = [
        {
            "id": h.id,
            "application_id": h.application_id,
            "from_status": h.from_status,
            "to_status": h.to_status,
            "transition_reason": h.transition_reason,
            "created_at": h.created_at.isoformat() if h.created_at else None,
        }
        for h in history_rows
    ]

    # 19. Submission Plans
    plans_rows = _safe_query_all(session, SubmissionPlanModel, existing_tables)
    submission_plans = [
        {
            "id": sp.id,
            "application_id": sp.application_id,
            "job_posting_id": sp.job_posting_id,
            "employer_handle": sp.employer_handle,
            "target_role": sp.target_role,
            "resume_sha256": sp.resume_sha256,
            "cover_letter_sha256": sp.cover_letter_sha256,
            "packet_sha256": sp.packet_sha256,
            "answers_json": sp.answers_json,
            "is_compensation_eligible": sp.is_compensation_eligible,
            "is_cooldown_clear": sp.is_cooldown_clear,
            "compensation_threshold_version": sp.compensation_threshold_version,
            "status": sp.status,
            "created_at": sp.created_at.isoformat() if sp.created_at else None,
        }
        for sp in plans_rows
    ]

    # 20. Application Attempts
    attempts_rows = _safe_query_all(session, ApplicationAttempt, existing_tables)
    application_attempts = [
        {
            "id": att.id,
            "application_id": att.application_id,
            "submission_plan_id": att.submission_plan_id,
            "attempt_number": att.attempt_number,
            "idempotency_key": att.idempotency_key,
            "simulation_mode": att.simulation_mode,
            "plan_sha256": att.plan_sha256,
            "status": att.status,
            "outcome": att.outcome,
            "error_code": att.error_code,
            "error_message": att.error_message,
            "simulated_receipt": att.simulated_receipt,
            "metadata_json": att.metadata_json,
            "started_at": att.started_at.isoformat() if att.started_at else None,
            "completed_at": att.completed_at.isoformat() if att.completed_at else None,
        }
        for att in attempts_rows
    ]

    # 21. Audit Events
    audit_rows = _safe_query_all(session, AuditEvent, existing_tables)
    audit_events = [
        {
            "id": a.id,
            "event_type": a.event_type,
            "entity_type": a.entity_type,
            "entity_id": a.entity_id,
            "actor_type": a.actor_type,
            "actor_id": a.actor_id,
            "payload_json": a.payload_json,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in audit_rows
    ]

    bundle_body: dict[str, Any] = {
        "candidate_profile": prof_dict,
        "user_settings": settings_dict,
        "job_sources": job_sources,
        "employer_subscriptions": subscriptions,
        "discovery_runs": runs,
        "job_postings": postings,
        "job_posting_snapshots": snapshots,
        "compensation_preferences": comp_prefs,
        "compensation_preference_audits": comp_audits,
        "compensation_assessments": comp_assessments,
        "candidate_documents": candidate_documents,
        "candidate_document_blobs": candidate_document_blobs,
        "candidate_document_versions": candidate_document_versions,
        "candidate_facts": candidate_facts,
        "candidate_fact_evidence": candidate_fact_evidence,
        "answer_bank_items": answers,
        "tracked_applications": apps,
        "application_status_history": app_history,
        "submission_plans": submission_plans,
        "application_attempts": application_attempts,
        "audit_events": audit_events,
    }

    # Scrub any secrets
    cleaned_body = sanitize_bundle_dictionary(bundle_body)

    # Compute checksum
    checksum = compute_bundle_checksum(cleaned_body)

    # Assemble manifest
    now_iso = datetime.now(timezone.utc).isoformat()
    record_counts = {
        "candidate_profile": 1 if prof_dict else 0,
        "user_settings": 1 if settings_dict else 0,
        "job_sources": len(job_sources),
        "employer_subscriptions": len(subscriptions),
        "discovery_runs": len(runs),
        "job_postings": len(postings),
        "job_posting_snapshots": len(snapshots),
        "compensation_preferences": len(comp_prefs),
        "compensation_preference_audits": len(comp_audits),
        "compensation_assessments": len(comp_assessments),
        "candidate_documents": len(candidate_documents),
        "candidate_document_blobs": len(candidate_document_blobs),
        "candidate_document_versions": len(candidate_document_versions),
        "candidate_facts": len(candidate_facts),
        "candidate_fact_evidence": len(candidate_fact_evidence),
        "answer_bank_items": len(answers),
        "tracked_applications": len(apps),
        "application_status_history": len(app_history),
        "submission_plans": len(submission_plans),
        "application_attempts": len(application_attempts),
        "audit_events": len(audit_events),
    }

    manifest = {
        "format_version": EXPORT_FORMAT_VERSION,
        "product": "hire-steward",
        "exported_at": now_iso,
        "checksum_sha256": checksum,
        "record_counts": record_counts,
    }

    cleaned_body["manifest"] = manifest
    return cleaned_body


def preview_import_dataset(session: Session, bundle: dict[str, Any]) -> dict[str, Any]:
    """Validate manifest and evaluate collision counts against current database."""
    preview = validate_import_bundle_manifest(bundle)
    existing_tables = _get_existing_tables(session)

    collisions: dict[str, int] = {
        "candidate_profile": 0,
        "user_settings": 0,
        "job_sources": 0,
        "employer_subscriptions": 0,
        "discovery_runs": 0,
        "job_postings": 0,
        "job_posting_snapshots": 0,
        "compensation_preferences": 0,
        "compensation_preference_audits": 0,
        "compensation_assessments": 0,
        "candidate_documents": 0,
        "candidate_document_blobs": 0,
        "candidate_document_versions": 0,
        "candidate_facts": 0,
        "candidate_fact_evidence": 0,
        "answer_bank_items": 0,
        "tracked_applications": 0,
        "application_status_history": 0,
        "submission_plans": 0,
        "application_attempts": 0,
        "audit_events": 0,
    }

    if "candidate_profiles" in existing_tables:
        existing_profile = session.get(CandidateProfile, "default")
        if existing_profile and bundle.get("candidate_profile"):
            collisions["candidate_profile"] = 1

    if "user_settings" in existing_tables:
        existing_settings = session.get(UserSettingsModel, "default")
        if existing_settings and bundle.get("user_settings"):
            collisions["user_settings"] = 1

    if "compensation_preferences" in existing_tables:
        existing_comp_pref = session.get(CompensationPreference, 1)
        if existing_comp_pref and bundle.get("compensation_preferences"):
            collisions["compensation_preferences"] = 1

    # Check list collections
    collection_model_map = [
        ("job_sources", JobSource, "source_name"),
        ("employer_subscriptions", EmployerSubscription, "id"),
        ("discovery_runs", DiscoveryRun, "id"),
        ("job_postings", JobPosting, "id"),
        ("job_posting_snapshots", JobPostingSnapshot, "id"),
        ("compensation_preference_audits", CompensationPreferenceAudit, "id"),
        ("compensation_assessments", CompensationAssessment, "id"),
        ("candidate_documents", CandidateDocument, "id"),
        ("candidate_document_blobs", CandidateDocumentBlob, "content_hash"),
        ("candidate_document_versions", CandidateDocumentVersion, "id"),
        ("candidate_facts", CandidateFact, "id"),
        ("candidate_fact_evidence", CandidateFactEvidence, "id"),
        ("answer_bank_items", AnswerBankItem, "id"),
        ("tracked_applications", TrackedApplication, "id"),
        ("application_status_history", ApplicationStatusHistory, "id"),
        ("submission_plans", SubmissionPlanModel, "id"),
        ("application_attempts", ApplicationAttempt, "id"),
        ("audit_events", AuditEvent, "id"),
    ]

    for key, model_cls, id_field in collection_model_map:
        if model_cls.__tablename__ not in existing_tables:
            continue
        items = bundle.get(key) or []
        for item in items:
            if isinstance(item, dict):
                pk = item.get(id_field)
                if pk is not None and session.get(model_cls, pk):
                    collisions[key] += 1

    # Compute deterministic preview token
    manifest = bundle.get("manifest") or {}
    actual_checksum = manifest.get("checksum_sha256") or ""
    preview_token = compute_preview_token(actual_checksum, collisions, preview.new_counts)

    return {
        "is_valid": preview.is_valid,
        "format_version": preview.format_version,
        "checksum_verified": preview.checksum_verified,
        "new_counts": preview.new_counts,
        "collision_counts": collisions,
        "warnings": preview.warnings,
        "preview_token": preview_token,
    }


def commit_import_dataset(
    session: Session,
    bundle: dict[str, Any],
    preview_token: str | None = None,
    overwrite_existing: bool = False,
    storage_root: Path | None = None,
) -> dict[str, Any]:
    """Commit validated import bundle atomically within database transaction.

    Defaults to overwrite_existing = False to protect user state.
    Binds preview_token to guarantee no unexpected state changes.
    Restores entities in strict topological dependency order.
    """
    preview = preview_import_dataset(session, bundle)
    if not preview["is_valid"]:
        msg = "; ".join(preview["warnings"]) if preview["warnings"] else "Invalid import bundle"
        raise DataPortabilityError(f"IMPORT_VALIDATION_FAILED: {msg}", "INVALID_BUNDLE")
    if not preview["checksum_verified"]:
        raise DataPortabilityError("CHECKSUM_MISMATCH: Bundle checksum verification failed", "CHECKSUM_MISMATCH")

    # Preview token verification
    if preview_token is not None and preview_token != preview["preview_token"]:
        raise DataPortabilityError(
            "PREVIEW_TOKEN_MISMATCH: The import payload or database state has changed since preview.",
            "PREVIEW_TOKEN_MISMATCH",
        )

    resolved_storage_root: Path | None = storage_root
    if resolved_storage_root is None:
        env_settings = evidence_settings_from_environment()
        if env_settings is not None:
            resolved_storage_root = env_settings.storage_root

    # Discover tables prior to entering nested savepoint/transaction
    existing_tables = _get_existing_tables(session)

    restored_counts: dict[str, int] = {
        "candidate_profile": 0,
        "user_settings": 0,
        "job_sources": 0,
        "employer_subscriptions": 0,
        "discovery_runs": 0,
        "job_postings": 0,
        "job_posting_snapshots": 0,
        "compensation_preferences": 0,
        "compensation_preference_audits": 0,
        "compensation_assessments": 0,
        "candidate_documents": 0,
        "candidate_document_blobs": 0,
        "candidate_document_versions": 0,
        "candidate_facts": 0,
        "candidate_fact_evidence": 0,
        "answer_bank_items": 0,
        "tracked_applications": 0,
        "application_status_history": 0,
        "submission_plans": 0,
        "application_attempts": 0,
        "audit_events": 0,
    }

    try:
        with session.begin_nested() if session.in_transaction() else session.begin():
            # 1. Job Sources
            if "job_sources" in existing_tables:
                incoming_sources = bundle.get("job_sources") or []
                for s in incoming_sources:
                    if not isinstance(s, dict) or not s.get("source_name"):
                        continue
                    existing_src = session.get(JobSource, s["source_name"])
                    if existing_src is not None:
                        if overwrite_existing:
                            existing_src.display_name = s.get("display_name", existing_src.display_name)
                            existing_src.capability_status = s.get("capability_status", existing_src.capability_status)
                            existing_src.is_enabled = s.get("is_enabled", existing_src.is_enabled)
                            existing_src.terms_reviewed_at = _parse_dt(s.get("terms_reviewed_at")) or existing_src.terms_reviewed_at
                            existing_src.terms_review_reference = s.get("terms_review_reference", existing_src.terms_review_reference)
                            existing_src.rate_limit_requests_per_minute = s.get("rate_limit_requests_per_minute", existing_src.rate_limit_requests_per_minute)
                            existing_src.min_poll_interval_seconds = s.get("min_poll_interval_seconds", existing_src.min_poll_interval_seconds)
                            restored_counts["job_sources"] += 1
                    else:
                        new_src = JobSource(
                            source_name=s["source_name"],
                            display_name=s.get("display_name", s["source_name"]),
                            capability_status=s.get("capability_status", "NEEDS_REVIEW"),
                            is_enabled=s.get("is_enabled", False),
                            terms_reviewed_at=_parse_dt(s.get("terms_reviewed_at")),
                            terms_review_reference=s.get("terms_review_reference"),
                            rate_limit_requests_per_minute=s.get("rate_limit_requests_per_minute", 10),
                            min_poll_interval_seconds=s.get("min_poll_interval_seconds", 43200),
                        )
                        session.add(new_src)
                        restored_counts["job_sources"] += 1

            # 2. Employer Subscriptions
            if "employer_subscriptions" in existing_tables:
                incoming_subs = bundle.get("employer_subscriptions") or []
                for sub in incoming_subs:
                    if not isinstance(sub, dict) or not sub.get("id"):
                        continue
                    existing_sub = session.get(EmployerSubscription, sub["id"])
                    if existing_sub is not None:
                        if overwrite_existing:
                            existing_sub.source_name = sub.get("source_name", existing_sub.source_name)
                            existing_sub.employer_handle = sub.get("employer_handle", existing_sub.employer_handle)
                            existing_sub.display_name = sub.get("display_name", existing_sub.display_name)
                            existing_sub.is_enabled = sub.get("is_enabled", existing_sub.is_enabled)
                            restored_counts["employer_subscriptions"] += 1
                    else:
                        new_sub = EmployerSubscription(
                            id=sub["id"],
                            source_name=sub["source_name"],
                            employer_handle=sub["employer_handle"],
                            display_name=sub.get("display_name"),
                            is_enabled=sub.get("is_enabled", True),
                        )
                        session.add(new_sub)
                        restored_counts["employer_subscriptions"] += 1

            # 3. Discovery Runs
            if "discovery_runs" in existing_tables:
                incoming_runs = bundle.get("discovery_runs") or []
                for r in incoming_runs:
                    if not isinstance(r, dict) or not r.get("id"):
                        continue
                    existing_run = session.get(DiscoveryRun, r["id"])
                    if existing_run is not None:
                        if overwrite_existing:
                            existing_run.status = r.get("status", existing_run.status)
                            existing_run.started_at = _parse_dt(r.get("started_at")) or existing_run.started_at
                            existing_run.finished_at = _parse_dt(r.get("finished_at"))
                            existing_run.current_skip = r.get("current_skip", existing_run.current_skip)
                            existing_run.current_page_index = r.get("current_page_index", existing_run.current_page_index)
                            existing_run.page_limit = r.get("page_limit", existing_run.page_limit)
                            existing_run.items_seen_count = r.get("items_seen_count", existing_run.items_seen_count)
                            existing_run.items_new_count = r.get("items_new_count", existing_run.items_new_count)
                            existing_run.items_updated_count = r.get("items_updated_count", existing_run.items_updated_count)
                            existing_run.items_duplicate_count = r.get("items_duplicate_count", existing_run.items_duplicate_count)
                            existing_run.error_code = r.get("error_code", existing_run.error_code)
                            existing_run.error_message_redacted = r.get("error_message_redacted", existing_run.error_message_redacted)
                            restored_counts["discovery_runs"] += 1
                    else:
                        new_run = DiscoveryRun(
                            id=r["id"],
                            subscription_id=r["subscription_id"],
                            status=r.get("status", "PENDING"),
                            started_at=_parse_dt(r.get("started_at")) or datetime.now(timezone.utc),
                            finished_at=_parse_dt(r.get("finished_at")),
                            current_skip=r.get("current_skip", 0),
                            current_page_index=r.get("current_page_index", 0),
                            page_limit=r.get("page_limit", 100),
                            items_seen_count=r.get("items_seen_count", 0),
                            items_new_count=r.get("items_new_count", 0),
                            items_updated_count=r.get("items_updated_count", 0),
                            items_duplicate_count=r.get("items_duplicate_count", 0),
                            error_code=r.get("error_code"),
                            error_message_redacted=r.get("error_message_redacted"),
                        )
                        session.add(new_run)
                        restored_counts["discovery_runs"] += 1

            # 4. Job Postings
            if "job_postings" in existing_tables:
                incoming_postings = bundle.get("job_postings") or []
                for p in incoming_postings:
                    if not isinstance(p, dict) or not p.get("id"):
                        continue
                    existing_posting = session.get(JobPosting, p["id"])
                    if existing_posting is not None:
                        if overwrite_existing:
                            existing_posting.subscription_id = p.get("subscription_id", existing_posting.subscription_id)
                            existing_posting.posting_id = p.get("posting_id", existing_posting.posting_id)
                            existing_posting.current_raw_hash = p.get("current_raw_hash", existing_posting.current_raw_hash)
                            existing_posting.lifecycle_status = p.get("lifecycle_status", existing_posting.lifecycle_status)
                            existing_posting.consecutive_misses_count = p.get("consecutive_misses_count", existing_posting.consecutive_misses_count)
                            existing_posting.version = p.get("version", existing_posting.version)
                            existing_posting.last_observed_at = _parse_dt(p.get("last_observed_at")) or existing_posting.last_observed_at
                            existing_posting.last_seen_run_id = p.get("last_seen_run_id", existing_posting.last_seen_run_id)
                            restored_counts["job_postings"] += 1
                    else:
                        new_posting = JobPosting(
                            id=p["id"],
                            subscription_id=p["subscription_id"],
                            posting_id=p["posting_id"],
                            current_raw_hash=p["current_raw_hash"],
                            lifecycle_status=p.get("lifecycle_status", "ACTIVE"),
                            consecutive_misses_count=p.get("consecutive_misses_count", 0),
                            version=p.get("version", 1),
                            first_observed_at=_parse_dt(p.get("first_observed_at")) or datetime.now(timezone.utc),
                            last_observed_at=_parse_dt(p.get("last_observed_at")) or datetime.now(timezone.utc),
                            last_seen_run_id=p["last_seen_run_id"],
                        )
                        session.add(new_posting)
                        restored_counts["job_postings"] += 1

            # 5. Job Posting Snapshots
            if "job_posting_snapshots" in existing_tables:
                incoming_snapshots = bundle.get("job_posting_snapshots") or []
                for sn in incoming_snapshots:
                    if not isinstance(sn, dict) or not sn.get("id"):
                        continue
                    existing_sn = session.get(JobPostingSnapshot, sn["id"])
                    if existing_sn is not None:
                        if overwrite_existing:
                            existing_sn.title = sn.get("title", existing_sn.title)
                            existing_sn.location = sn.get("location", existing_sn.location)
                            existing_sn.commitment = sn.get("commitment", existing_sn.commitment)
                            existing_sn.team = sn.get("team", existing_sn.team)
                            existing_sn.department = sn.get("department", existing_sn.department)
                            existing_sn.level = sn.get("level", existing_sn.level)
                            existing_sn.workplace_type = sn.get("workplace_type", existing_sn.workplace_type)
                            existing_sn.published_at = _parse_dt(sn.get("published_at"))
                            existing_sn.publication_date_status = sn.get("publication_date_status", existing_sn.publication_date_status)
                            existing_sn.raw_created_at_ms = sn.get("raw_created_at_ms", existing_sn.raw_created_at_ms)
                            existing_sn.canonical_url = sn.get("canonical_url", existing_sn.canonical_url)
                            existing_sn.apply_url = sn.get("apply_url", existing_sn.apply_url)
                            existing_sn.description_plain = sn.get("description_plain", existing_sn.description_plain)
                            existing_sn.description_html = sn.get("description_html", existing_sn.description_html)
                            existing_sn.lists_json = sn.get("lists_json", existing_sn.lists_json)
                            existing_sn.additional_plain = sn.get("additional_plain", existing_sn.additional_plain)
                            restored_counts["job_posting_snapshots"] += 1
                    else:
                        new_sn = JobPostingSnapshot(
                            id=sn["id"],
                            subscription_id=sn["subscription_id"],
                            posting_id=sn["posting_id"],
                            run_id=sn["run_id"],
                            source_raw_hash=sn["source_raw_hash"],
                            title=sn["title"],
                            location=sn.get("location"),
                            commitment=sn.get("commitment"),
                            team=sn.get("team"),
                            department=sn.get("department"),
                            level=sn.get("level"),
                            workplace_type=sn.get("workplace_type"),
                            published_at=_parse_dt(sn.get("published_at")),
                            publication_date_status=sn.get("publication_date_status", "UNKNOWN"),
                            raw_created_at_ms=sn.get("raw_created_at_ms"),
                            canonical_url=sn.get("canonical_url"),
                            apply_url=sn.get("apply_url"),
                            description_plain=sn.get("description_plain", ""),
                            description_html=sn.get("description_html"),
                            lists_json=sn.get("lists_json", []),
                            additional_plain=sn.get("additional_plain"),
                            captured_at=_parse_dt(sn.get("captured_at")) or datetime.now(timezone.utc),
                        )
                        session.add(new_sn)
                        restored_counts["job_posting_snapshots"] += 1

            # 6. Compensation Preferences
            if "compensation_preferences" in existing_tables:
                incoming_comp = bundle.get("compensation_preferences") or []
                if incoming_comp and isinstance(incoming_comp, list):
                    pref_data = incoming_comp[0]
                    existing_cp = session.get(CompensationPreference, 1)
                    if existing_cp is not None:
                        if overwrite_existing:
                            existing_cp.amount = _parse_dec(pref_data.get("amount")) or existing_cp.amount
                            existing_cp.currency = pref_data.get("currency", existing_cp.currency)
                            existing_cp.period = pref_data.get("period", existing_cp.period)
                            existing_cp.version = pref_data.get("version", existing_cp.version)
                            restored_counts["compensation_preferences"] = 1
                    else:
                        new_cp = CompensationPreference(
                            id=1,
                            amount=_parse_dec(pref_data.get("amount")) or Decimal("0.00"),
                            currency=pref_data.get("currency", "INR"),
                            period=pref_data.get("period", "YEAR"),
                            version=pref_data.get("version", 1),
                        )
                        session.add(new_cp)
                        restored_counts["compensation_preferences"] = 1

            # 7. Compensation Preference Audits
            if "compensation_preference_audits" in existing_tables:
                incoming_audits = bundle.get("compensation_preference_audits") or []
                for a in incoming_audits:
                    if not isinstance(a, dict) or not a.get("id"):
                        continue
                    existing_audit = session.get(CompensationPreferenceAudit, a["id"])
                    if existing_audit is not None:
                        if overwrite_existing:
                            existing_audit.previous_amount = _parse_dec(a.get("previous_amount")) or existing_audit.previous_amount
                            existing_audit.new_amount = _parse_dec(a.get("new_amount")) or existing_audit.new_amount
                            existing_audit.currency = a.get("currency", existing_audit.currency)
                            existing_audit.period = a.get("period", existing_audit.period)
                            existing_audit.settings_version = a.get("settings_version", existing_audit.settings_version)
                            existing_audit.actor_type = a.get("actor_type", existing_audit.actor_type)
                            existing_audit.actor_id = a.get("actor_id", existing_audit.actor_id)
                            restored_counts["compensation_preference_audits"] += 1
                    else:
                        new_audit = CompensationPreferenceAudit(
                            id=a["id"],
                            preference_id=a.get("preference_id", 1),
                            previous_amount=_parse_dec(a.get("previous_amount")) or Decimal("0.00"),
                            new_amount=_parse_dec(a.get("new_amount")) or Decimal("0.00"),
                            currency=a.get("currency", "INR"),
                            period=a.get("period", "YEAR"),
                            settings_version=a.get("settings_version", 2),
                            actor_type=a.get("actor_type", "USER"),
                            actor_id=a.get("actor_id", "default"),
                            changed_at=_parse_dt(a.get("changed_at")) or datetime.now(timezone.utc),
                        )
                        session.add(new_audit)
                        restored_counts["compensation_preference_audits"] += 1

            # 8. Compensation Assessments
            if "compensation_assessments" in existing_tables:
                incoming_assessments = bundle.get("compensation_assessments") or []
                for ca in incoming_assessments:
                    if not isinstance(ca, dict) or not ca.get("id"):
                        continue
                    existing_ca = session.get(CompensationAssessment, ca["id"])
                    if existing_ca is not None:
                        if overwrite_existing:
                            existing_ca.job_reference = ca.get("job_reference", existing_ca.job_reference)
                            existing_ca.reported_status = ca.get("source_status", existing_ca.reported_status)
                            existing_ca.evidence_verification_state = ca.get("evidence_verification_state", existing_ca.evidence_verification_state)
                            existing_ca.source_amount = _parse_dec(ca.get("source_amount"))
                            existing_ca.source_minimum = _parse_dec(ca.get("source_minimum"))
                            existing_ca.source_maximum = _parse_dec(ca.get("source_maximum"))
                            existing_ca.source_currency = ca.get("source_currency")
                            existing_ca.source_period = ca.get("source_period", existing_ca.source_period)
                            existing_ca.source_recurring = ca.get("source_recurring")
                            existing_ca.evidence_reference = ca.get("evidence_reference")
                            existing_ca.threshold_amount = _parse_dec(ca.get("threshold_amount")) or existing_ca.threshold_amount
                            existing_ca.threshold_currency = ca.get("threshold_currency", existing_ca.threshold_currency)
                            existing_ca.threshold_period = ca.get("threshold_period", existing_ca.threshold_period)
                            existing_ca.threshold_version = ca.get("threshold_version", existing_ca.threshold_version)
                            existing_ca.normalized_minimum_annual = _parse_dec(ca.get("normalized_minimum_annual"))
                            existing_ca.normalized_maximum_annual = _parse_dec(ca.get("normalized_maximum_annual"))
                            existing_ca.conversion_basis = ca.get("conversion_basis")
                            existing_ca.outcome = ca.get("outcome", existing_ca.outcome)
                            existing_ca.reason_code = ca.get("reason_code", existing_ca.reason_code)
                            existing_ca.explanation = ca.get("explanation", existing_ca.explanation)
                            restored_counts["compensation_assessments"] += 1
                    else:
                        new_ca = CompensationAssessment(
                            id=ca["id"],
                            job_reference=ca["job_reference"],
                            reported_status=ca.get("source_status", "UNKNOWN"),
                            evidence_verification_state=ca.get("evidence_verification_state", "UNVERIFIED"),
                            source_amount=_parse_dec(ca.get("source_amount")),
                            source_minimum=_parse_dec(ca.get("source_minimum")),
                            source_maximum=_parse_dec(ca.get("source_maximum")),
                            source_currency=ca.get("source_currency"),
                            source_period=ca.get("source_period", "UNKNOWN"),
                            source_recurring=ca.get("source_recurring"),
                            evidence_reference=ca.get("evidence_reference"),
                            threshold_amount=_parse_dec(ca.get("threshold_amount")) or Decimal("0.00"),
                            threshold_currency=ca.get("threshold_currency", "INR"),
                            threshold_period=ca.get("threshold_period", "YEAR"),
                            threshold_version=ca.get("threshold_version", 1),
                            normalized_minimum_annual=_parse_dec(ca.get("normalized_minimum_annual")),
                            normalized_maximum_annual=_parse_dec(ca.get("normalized_maximum_annual")),
                            conversion_basis=ca.get("conversion_basis"),
                            outcome=ca.get("outcome", "REVIEW_REQUIRED"),
                            reason_code=ca.get("reason_code", "ASSESSMENT_IMPORTED"),
                            explanation=ca.get("explanation", ""),
                            created_at=_parse_dt(ca.get("created_at")) or datetime.now(timezone.utc),
                        )
                        session.add(new_ca)
                        restored_counts["compensation_assessments"] += 1

            # 9. Candidate Documents
            if "candidate_documents" in existing_tables:
                incoming_docs = bundle.get("candidate_documents") or []
                for d in incoming_docs:
                    if not isinstance(d, dict) or not d.get("id"):
                        continue
                    existing_d = session.get(CandidateDocument, d["id"])
                    if existing_d is not None:
                        if overwrite_existing:
                            existing_d.display_name = d.get("display_name", existing_d.display_name)
                            existing_d.state = d.get("state", existing_d.state)
                            existing_d.retired_at = _parse_dt(d.get("retired_at"))
                            restored_counts["candidate_documents"] += 1
                    else:
                        new_doc = CandidateDocument(
                            id=d["id"],
                            display_name=d.get("display_name", "Document"),
                            state=d.get("state", "ACTIVE"),
                            created_at=_parse_dt(d.get("created_at")) or datetime.now(timezone.utc),
                            retired_at=_parse_dt(d.get("retired_at")),
                        )
                        session.add(new_doc)
                        restored_counts["candidate_documents"] += 1

            # 10. Candidate Document Blobs
            if "candidate_document_blobs" in existing_tables:
                incoming_blobs = bundle.get("candidate_document_blobs") or []
                total_blob_bytes = 0
                for b in incoming_blobs:
                    if not isinstance(b, dict) or not b.get("content_hash"):
                        continue
                    h = b["content_hash"]
                    existing_blob = session.get(CandidateDocumentBlob, h)
                    byte_sz = b.get("byte_size", 0)
                    total_blob_bytes += byte_sz
                    if existing_blob is not None:
                        if overwrite_existing:
                            existing_blob.storage_key = b.get("storage_key", existing_blob.storage_key)
                            existing_blob.media_type = b.get("media_type", existing_blob.media_type)
                            existing_blob.byte_size = byte_sz
                            restored_counts["candidate_document_blobs"] += 1
                    else:
                        new_blob = CandidateDocumentBlob(
                            content_hash=h,
                            storage_key=b.get("storage_key", f"blobs/{h[:2]}/{h[2:4]}/{h}.txt"),
                            media_type=b.get("media_type", "text/plain"),
                            byte_size=byte_sz,
                            created_at=_parse_dt(b.get("created_at")) or datetime.now(timezone.utc),
                        )
                        session.add(new_blob)
                        restored_counts["candidate_document_blobs"] += 1

                    # If physical content was packaged and storage root exists, restore on disk
                    if resolved_storage_root:
                        target_path = resolved_storage_root / b.get("storage_key", f"blobs/{h[:2]}/{h[2:4]}/{h}.txt")
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        if "content_base64" in b:
                            if not target_path.exists() or overwrite_existing:
                                raw_bytes = base64.b64decode(b["content_base64"])
                                target_path.write_bytes(raw_bytes)
                        elif "content_text" in b:
                            if not target_path.exists() or overwrite_existing:
                                target_path.write_text(b["content_text"], encoding="utf-8")

                # Update CandidateEvidenceStorageUsage if usage table exists
                if "candidate_evidence_storage_usage" in existing_tables:
                    usage = session.get(CandidateEvidenceStorageUsage, 1)
                    if usage is not None:
                        usage.committed_bytes = total_blob_bytes
                    elif total_blob_bytes > 0:
                        try:
                            session.add(
                                CandidateEvidenceStorageUsage(
                                    id=1,
                                    committed_bytes=total_blob_bytes,
                                    reserved_bytes=0,
                                    version=1,
                                )
                            )
                        except Exception:
                            pass

            # 11. Candidate Document Versions
            if "candidate_document_versions" in existing_tables:
                incoming_versions = bundle.get("candidate_document_versions") or []
                for v in incoming_versions:
                    if not isinstance(v, dict) or not v.get("id"):
                        continue
                    existing_v = session.get(CandidateDocumentVersion, v["id"])
                    if existing_v is not None:
                        if overwrite_existing:
                            existing_v.document_id = v.get("document_id", existing_v.document_id)
                            existing_v.version_number = v.get("version_number", existing_v.version_number)
                            existing_v.blob_hash = v.get("blob_hash", existing_v.blob_hash)
                            existing_v.text_artifact_hash = v.get("text_artifact_hash", existing_v.text_artifact_hash)
                            existing_v.original_filename = v.get("original_filename", existing_v.original_filename)
                            existing_v.extraction_status = v.get("extraction_status", existing_v.extraction_status)
                            existing_v.extraction_error_code = v.get("extraction_error_code", existing_v.extraction_error_code)
                            existing_v.extractor_version = v.get("extractor_version", existing_v.extractor_version)
                            restored_counts["candidate_document_versions"] += 1
                    else:
                        new_v = CandidateDocumentVersion(
                            id=v["id"],
                            document_id=v["document_id"],
                            version_number=v.get("version_number", 1),
                            blob_hash=v["blob_hash"],
                            text_artifact_hash=v.get("text_artifact_hash"),
                            original_filename=v.get("original_filename", "uploaded_document.txt"),
                            ingested_at=_parse_dt(v.get("ingested_at")) or datetime.now(timezone.utc),
                            extraction_status=v.get("extraction_status", "NOT_REQUESTED"),
                            extraction_error_code=v.get("extraction_error_code"),
                            extractor_version=v.get("extractor_version"),
                        )
                        session.add(new_v)
                        restored_counts["candidate_document_versions"] += 1

            # 12. Candidate Facts (insert first pass with supersedes_fact_id=None to satisfy self-referential FK)
            if "candidate_facts" in existing_tables:
                incoming_facts = bundle.get("candidate_facts") or []
                supersedes_mapping: dict[str, str | None] = {}
                for f in incoming_facts:
                    if not isinstance(f, dict) or not f.get("id"):
                        continue
                    v_hash = f.get("value_hash")
                    val = f.get("value_json") if f.get("value_json") is not None else f.get("value", {})
                    if not v_hash:
                        _, v_hash = canonical_json_and_hash(val or {})
                    existing_f = session.get(CandidateFact, f["id"])
                    supersedes_mapping[f["id"]] = f.get("supersedes_fact_id")
                    if existing_f is not None:
                        if overwrite_existing:
                            existing_f.fact_type = f.get("fact_type", existing_f.fact_type)
                            existing_f.value_json = val
                            existing_f.value_hash = v_hash
                            existing_f.verification_state = f.get("verification_state", existing_f.verification_state)
                            restored_counts["candidate_facts"] += 1
                    else:
                        new_fact = CandidateFact(
                            id=f["id"],
                            fact_type=f["fact_type"],
                            value_json=val,
                            value_hash=v_hash,
                            verification_state=f.get("verification_state", "UNREVIEWED"),
                            supersedes_fact_id=None,
                            created_at=_parse_dt(f.get("created_at")) or datetime.now(timezone.utc),
                        )
                        session.add(new_fact)
                        restored_counts["candidate_facts"] += 1

                # Second pass: wire supersedes_fact_id
                for fid, super_id in supersedes_mapping.items():
                    if super_id:
                        fact_obj = session.get(CandidateFact, fid)
                        if fact_obj:
                            fact_obj.supersedes_fact_id = super_id

            # 13. Candidate Fact Evidence
            if "candidate_fact_evidence" in existing_tables:
                incoming_evidence = bundle.get("candidate_fact_evidence") or []
                for ev in incoming_evidence:
                    if not isinstance(ev, dict) or not ev.get("id"):
                        continue
                    existing_ev = session.get(CandidateFactEvidence, ev["id"])
                    if existing_ev is not None:
                        if overwrite_existing:
                            existing_ev.fact_id = ev.get("fact_id", existing_ev.fact_id)
                            existing_ev.document_version_id = ev.get("document_version_id", existing_ev.document_version_id)
                            existing_ev.byte_start = ev.get("byte_start", existing_ev.byte_start)
                            existing_ev.byte_end = ev.get("byte_end", existing_ev.byte_end)
                            existing_ev.evidence_hash = ev.get("evidence_hash", existing_ev.evidence_hash)
                            existing_ev.method = ev.get("method", existing_ev.method)
                            restored_counts["candidate_fact_evidence"] += 1
                    else:
                        new_ev = CandidateFactEvidence(
                            id=ev["id"],
                            fact_id=ev["fact_id"],
                            document_version_id=ev["document_version_id"],
                            byte_start=ev.get("byte_start", 0),
                            byte_end=ev.get("byte_end", 0),
                            evidence_hash=ev.get("evidence_hash", ""),
                            method=ev.get("method", "LOCAL_API_REPORTED"),
                            created_at=_parse_dt(ev.get("created_at")) or datetime.now(timezone.utc),
                        )
                        session.add(new_ev)
                        restored_counts["candidate_fact_evidence"] += 1

            # 14. Answer Bank Items (consent defaults to False)
            if "answer_bank_items" in existing_tables:
                incoming_answers = bundle.get("answer_bank_items") or []
                for a in incoming_answers:
                    if not isinstance(a, dict) or not a.get("id"):
                        continue
                    existing_a = session.get(AnswerBankItem, a["id"])
                    if existing_a is not None:
                        if overwrite_existing:
                            existing_a.question = a.get("question", existing_a.question)
                            existing_a.answer = a.get("answer", existing_a.answer)
                            existing_a.category = a.get("category", existing_a.category)
                            existing_a.fact_ids = a.get("fact_ids", existing_a.fact_ids)
                            existing_a.reuse_consent = a.get("reuse_consent", False)
                            existing_a.is_revoked = a.get("is_revoked", existing_a.is_revoked)
                            existing_a.version = a.get("version", existing_a.version)
                            restored_counts["answer_bank_items"] += 1
                    else:
                        new_item = AnswerBankItem(
                            id=a["id"],
                            question=a["question"],
                            answer=a["answer"],
                            category=a.get("category", "general"),
                            fact_ids=a.get("fact_ids", []),
                            reuse_consent=a.get("reuse_consent", False),
                            version=a.get("version", 1),
                            is_revoked=a.get("is_revoked", False),
                            created_at=_parse_dt(a.get("created_at")) or datetime.now(timezone.utc),
                        )
                        session.add(new_item)
                        restored_counts["answer_bank_items"] += 1

            # 15. Candidate Profile (strictly respect overwrite_existing)
            if "candidate_profiles" in existing_tables:
                prof_data = bundle.get("candidate_profile")
                if prof_data and isinstance(prof_data, dict):
                    existing_p = session.get(CandidateProfile, "default")
                    if existing_p is None:
                        # Clean instance with no default profile
                        profile_service.update_profile(session, prof_data)
                        restored_counts["candidate_profile"] = 1
                    elif overwrite_existing:
                        profile_service.update_profile(session, prof_data)
                        restored_counts["candidate_profile"] = 1
                    else:
                        # Destination has profile and overwrite_existing is False: do not mutate!
                        pass

            # 16. User Settings (strictly respect overwrite_existing)
            if "user_settings" in existing_tables:
                settings_data = bundle.get("user_settings")
                if settings_data and isinstance(settings_data, dict):
                    existing_s = session.get(UserSettingsModel, "default")
                    if existing_s is None:
                        # Clean instance with no settings row
                        existing_s = UserSettingsModel(id="default")
                        session.add(existing_s)
                        existing_s.target_roles = settings_data.get("target_roles", [])
                        existing_s.target_locations = settings_data.get("target_locations", [])
                        existing_s.workplace_arrangements = settings_data.get("workplace_arrangements", [])
                        existing_s.sponsorship_requirement = settings_data.get("sponsorship_requirement", "not_required")
                        existing_s.same_company_cooldown_days = settings_data.get("same_company_cooldown_days", 90)
                        existing_s.daily_application_cap = settings_data.get("daily_application_cap", 5)
                        existing_s.auto_tailor_resume = settings_data.get("auto_tailor_resume", False)
                        existing_s.dry_run_simulation_mode = settings_data.get("dry_run_simulation_mode", True)
                        existing_s.ai_provider_mode = settings_data.get("ai_provider_mode", "disabled")
                        existing_s.ai_budget_limit_usd = settings_data.get("ai_budget_limit_usd", 5.0)
                        restored_counts["user_settings"] = 1
                    elif overwrite_existing:
                        existing_s.target_roles = settings_data.get("target_roles", existing_s.target_roles)
                        existing_s.target_locations = settings_data.get("target_locations", existing_s.target_locations)
                        existing_s.workplace_arrangements = settings_data.get("workplace_arrangements", existing_s.workplace_arrangements)
                        existing_s.sponsorship_requirement = settings_data.get("sponsorship_requirement", existing_s.sponsorship_requirement)
                        existing_s.same_company_cooldown_days = settings_data.get("same_company_cooldown_days", existing_s.same_company_cooldown_days)
                        existing_s.daily_application_cap = settings_data.get("daily_application_cap", existing_s.daily_application_cap)
                        existing_s.auto_tailor_resume = settings_data.get("auto_tailor_resume", existing_s.auto_tailor_resume)
                        existing_s.dry_run_simulation_mode = settings_data.get("dry_run_simulation_mode", existing_s.dry_run_simulation_mode)
                        existing_s.ai_provider_mode = settings_data.get("ai_provider_mode", existing_s.ai_provider_mode)
                        existing_s.ai_budget_limit_usd = settings_data.get("ai_budget_limit_usd", existing_s.ai_budget_limit_usd)
                        restored_counts["user_settings"] = 1
                    else:
                        # Destination has settings and overwrite_existing is False: do not mutate!
                        pass

            # 17. Tracked Applications
            if "tracked_applications" in existing_tables:
                incoming_apps = bundle.get("tracked_applications") or []
                for app_data in incoming_apps:
                    if not isinstance(app_data, dict) or not app_data.get("id"):
                        continue
                    existing_app = session.get(TrackedApplication, app_data["id"])
                    if existing_app is not None:
                        if overwrite_existing:
                            existing_app.status = app_data.get("status", existing_app.status)
                            existing_app.notes = app_data.get("notes", existing_app.notes)
                            existing_app.follow_up_deadline = _parse_dt(app_data.get("follow_up_deadline"))
                            existing_app.next_interview_at = _parse_dt(app_data.get("next_interview_at"))
                            existing_app.applied_at = _parse_dt(app_data.get("applied_at"))
                            existing_app.last_status_change_at = _parse_dt(app_data.get("last_status_change_at")) or existing_app.last_status_change_at
                            existing_app.submitted_resume_snapshot = app_data.get("submitted_resume_snapshot", existing_app.submitted_resume_snapshot)
                            existing_app.submitted_cover_letter_snapshot = app_data.get("submitted_cover_letter_snapshot", existing_app.submitted_cover_letter_snapshot)
                            existing_app.submitted_resume_sha256 = app_data.get("submitted_resume_sha256", existing_app.submitted_resume_sha256)
                            existing_app.submitted_cover_letter_sha256 = app_data.get("submitted_cover_letter_sha256", existing_app.submitted_cover_letter_sha256)
                            existing_app.reviewed_resume_markdown = app_data.get("reviewed_resume_markdown", existing_app.reviewed_resume_markdown)
                            existing_app.reviewed_cover_letter_markdown = app_data.get("reviewed_cover_letter_markdown", existing_app.reviewed_cover_letter_markdown)
                            existing_app.reviewed_at = _parse_dt(app_data.get("reviewed_at"))
                            existing_app.version = app_data.get("version", existing_app.version)
                            restored_counts["tracked_applications"] += 1
                    else:
                        new_app = TrackedApplication(
                            id=app_data["id"],
                            job_posting_id=app_data["job_posting_id"],
                            status=app_data.get("status", "SAVED"),
                            notes=app_data.get("notes"),
                            follow_up_deadline=_parse_dt(app_data.get("follow_up_deadline")),
                            next_interview_at=_parse_dt(app_data.get("next_interview_at")),
                            applied_at=_parse_dt(app_data.get("applied_at")),
                            last_status_change_at=_parse_dt(app_data.get("last_status_change_at")) or datetime.now(timezone.utc),
                            submitted_resume_snapshot=app_data.get("submitted_resume_snapshot"),
                            submitted_cover_letter_snapshot=app_data.get("submitted_cover_letter_snapshot"),
                            submitted_resume_sha256=app_data.get("submitted_resume_sha256"),
                            submitted_cover_letter_sha256=app_data.get("submitted_cover_letter_sha256"),
                            reviewed_resume_markdown=app_data.get("reviewed_resume_markdown"),
                            reviewed_cover_letter_markdown=app_data.get("reviewed_cover_letter_markdown"),
                            reviewed_at=_parse_dt(app_data.get("reviewed_at")),
                            version=app_data.get("version", 1),
                            created_at=_parse_dt(app_data.get("created_at")) or datetime.now(timezone.utc),
                        )
                        session.add(new_app)
                        restored_counts["tracked_applications"] += 1

            # 18. Application Status History
            if "application_status_history" in existing_tables:
                incoming_history = bundle.get("application_status_history") or []
                for h in incoming_history:
                    if not isinstance(h, dict) or not h.get("id"):
                        continue
                    existing_h = session.get(ApplicationStatusHistory, h["id"])
                    if existing_h is not None:
                        if overwrite_existing:
                            existing_h.from_status = h.get("from_status", existing_h.from_status)
                            existing_h.to_status = h.get("to_status", existing_h.to_status)
                            existing_h.transition_reason = h.get("transition_reason", existing_h.transition_reason)
                            restored_counts["application_status_history"] += 1
                    else:
                        new_h = ApplicationStatusHistory(
                            id=h["id"],
                            application_id=h["application_id"],
                            from_status=h.get("from_status"),
                            to_status=h.get("to_status", "SAVED"),
                            transition_reason=h.get("transition_reason"),
                            created_at=_parse_dt(h.get("created_at")) or datetime.now(timezone.utc),
                        )
                        session.add(new_h)
                        restored_counts["application_status_history"] += 1

            # 19. Submission Plans
            if "submission_plans" in existing_tables:
                incoming_plans = bundle.get("submission_plans") or []
                for pl in incoming_plans:
                    if not isinstance(pl, dict) or not pl.get("id"):
                        continue
                    existing_pl = session.get(SubmissionPlanModel, pl["id"])
                    if existing_pl is not None:
                        if overwrite_existing:
                            existing_pl.employer_handle = pl.get("employer_handle", existing_pl.employer_handle)
                            existing_pl.target_role = pl.get("target_role", existing_pl.target_role)
                            existing_pl.resume_sha256 = pl.get("resume_sha256", existing_pl.resume_sha256)
                            existing_pl.cover_letter_sha256 = pl.get("cover_letter_sha256", existing_pl.cover_letter_sha256)
                            existing_pl.packet_sha256 = pl.get("packet_sha256", existing_pl.packet_sha256)
                            existing_pl.answers_json = pl.get("answers_json", existing_pl.answers_json)
                            existing_pl.is_compensation_eligible = pl.get("is_compensation_eligible", False)
                            existing_pl.is_cooldown_clear = pl.get("is_cooldown_clear", False)
                            existing_pl.compensation_threshold_version = pl.get("compensation_threshold_version", 1)
                            existing_pl.status = pl.get("status", existing_pl.status)
                            restored_counts["submission_plans"] += 1
                    else:
                        new_pl = SubmissionPlanModel(
                            id=pl["id"],
                            application_id=pl["application_id"],
                            job_posting_id=pl["job_posting_id"],
                            employer_handle=pl.get("employer_handle", "default"),
                            target_role=pl.get("target_role", "Role"),
                            resume_sha256=pl.get("resume_sha256", ""),
                            cover_letter_sha256=pl.get("cover_letter_sha256", ""),
                            packet_sha256=pl.get("packet_sha256", ""),
                            answers_json=pl.get("answers_json", []),
                            is_compensation_eligible=pl.get("is_compensation_eligible", False),
                            is_cooldown_clear=pl.get("is_cooldown_clear", False),
                            compensation_threshold_version=pl.get("compensation_threshold_version", 1),
                            status=pl.get("status", "PREPARED"),
                            created_at=_parse_dt(pl.get("created_at")) or datetime.now(timezone.utc),
                        )
                        session.add(new_pl)
                        restored_counts["submission_plans"] += 1

            # 20. Application Attempts
            if "application_attempts" in existing_tables:
                incoming_attempts = bundle.get("application_attempts") or []
                for att in incoming_attempts:
                    if not isinstance(att, dict) or not att.get("id"):
                        continue
                    existing_att = session.get(ApplicationAttempt, att["id"])
                    if existing_att is not None:
                        if overwrite_existing:
                            existing_att.attempt_number = att.get("attempt_number", existing_att.attempt_number)
                            existing_att.status = att.get("status", existing_att.status)
                            existing_att.outcome = att.get("outcome", existing_att.outcome)
                            existing_att.error_code = att.get("error_code", existing_att.error_code)
                            existing_att.error_message = att.get("error_message", existing_att.error_message)
                            existing_att.simulated_receipt = att.get("simulated_receipt", existing_att.simulated_receipt)
                            existing_att.plan_sha256 = att.get("plan_sha256", existing_att.plan_sha256)
                            existing_att.metadata_json = att.get("metadata_json", existing_att.metadata_json)
                            existing_att.completed_at = _parse_dt(att.get("completed_at"))
                            restored_counts["application_attempts"] += 1
                    else:
                        new_att = ApplicationAttempt(
                            id=att["id"],
                            application_id=att["application_id"],
                            submission_plan_id=att.get("submission_plan_id", ""),
                            attempt_number=att.get("attempt_number", 1),
                            idempotency_key=att.get("idempotency_key", att["id"]),
                            simulation_mode=att.get("simulation_mode", "SUCCESS"),
                            plan_sha256=att.get("plan_sha256", ""),
                            status=att.get("status", "NOT_DISPATCHED"),
                            outcome=att.get("outcome", "PENDING"),
                            error_code=att.get("error_code"),
                            error_message=att.get("error_message"),
                            simulated_receipt=att.get("simulated_receipt"),
                            metadata_json=att.get("metadata_json", {}),
                            started_at=_parse_dt(att.get("started_at")) or datetime.now(timezone.utc),
                            completed_at=_parse_dt(att.get("completed_at")),
                        )
                        session.add(new_att)
                        restored_counts["application_attempts"] += 1

            # 21. Audit Events
            if "audit_events" in existing_tables:
                incoming_events = bundle.get("audit_events") or []
                for ev_data in incoming_events:
                    if not isinstance(ev_data, dict) or not ev_data.get("id"):
                        continue
                    existing_ev = session.get(AuditEvent, ev_data["id"])
                    if existing_ev is not None:
                        if overwrite_existing:
                            existing_ev.event_type = ev_data.get("event_type", existing_ev.event_type)
                            existing_ev.entity_type = ev_data.get("entity_type", existing_ev.entity_type)
                            existing_ev.entity_id = ev_data.get("entity_id", existing_ev.entity_id)
                            existing_ev.actor_type = ev_data.get("actor_type", existing_ev.actor_type)
                            existing_ev.actor_id = ev_data.get("actor_id", existing_ev.actor_id)
                            existing_ev.payload_json = ev_data.get("payload_json", existing_ev.payload_json)
                            restored_counts["audit_events"] += 1
                    else:
                        new_ev = AuditEvent(
                            id=ev_data["id"],
                            event_type=ev_data["event_type"],
                            entity_type=ev_data.get("entity_type", "SYSTEM"),
                            entity_id=ev_data.get("entity_id", "default"),
                            actor_type=ev_data.get("actor_type", "USER"),
                            actor_id=ev_data.get("actor_id", "default"),
                            payload_json=ev_data.get("payload_json", {}),
                            created_at=_parse_dt(ev_data.get("created_at")) or datetime.now(timezone.utc),
                        )
                        session.add(new_ev)
                        restored_counts["audit_events"] += 1

        session.commit()
    except Exception as exc:
        session.rollback()
        raise DataPortabilityError(f"IMPORT_FAILED: Database transaction rolled back: {exc}", "IMPORT_FAILED") from exc

    return {
        "status": "COMPLETED",
        "restored_counts": restored_counts,
        "imported_at": datetime.now(timezone.utc).isoformat(),
    }
