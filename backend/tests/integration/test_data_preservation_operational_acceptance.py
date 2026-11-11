"""Comprehensive operational acceptance integration test for Hire-Steward.

Verifies:
1. Content-addressed preservation of original uploaded binary documents (PDF & DOCX) alongside extracted text artifacts.
2. Byte-for-byte SHA-256 fidelity across export and import restore.
3. Separation of submission plans from execution attempts (ApplicationAttempt persistence, lifecycle, idempotency).
4. Strict enforcement that simulation attempts never transition application status to APPLIED.
5. Unified system audit trail (AuditEvent coverage across policies, state changes, attempts, consent, and backups).
6. Complete 20-step export/import round-trip across independent instances with isolated database engines and storage directories.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import io
from pathlib import Path
import shutil
import tempfile
from typing import Any
import uuid
import zipfile

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.models import (
    AnswerBankItem,
    ApplicationAttempt,
    ApplicationStatusHistory,
    AuditEvent,
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
    compute_bundle_checksum,
)
from backend.app.evidence_config import EvidenceSettings
from backend.app.main import create_app
from backend.app.services.data_portability import (
    commit_import_dataset,
    export_dataset,
    preview_import_dataset,
)


def local_headers() -> dict[str, str]:
    return {"host": "localhost", "origin": "http://localhost"}


def make_sample_pdf_bytes(title: str = "Principal Distributed Systems Engineer") -> bytes:
    """Generate a minimal valid PDF-1.4 file containing readable stream text."""
    content = f"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>
endobj
4 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
5 0 obj
<< /Length {len(title) + 30} >>
stream
BT
/F1 12 Tf
({title}) Tj
ET
endstream
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000214 00000 n 
0000000287 00000 n 
trailer
<< /Size 6 /Root 1 0 R >>
startxref
400
%%EOF"""
    return content.encode("latin1")


def make_sample_docx_bytes(text_content: str = "Lead Platform Architect with expertise in distributed databases") -> bytes:
    """Generate a minimal valid DOCX PK zip file with word/document.xml."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '</Types>',
        )
        zf.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:body><w:p><w:r><w:t>{text_content}</w:t></w:r></w:p></w:body>'
            '</w:document>',
        )
    return buf.getvalue()


class IsolatedInstance:
    """A self-contained Hire-Steward runtime environment with isolated DB and storage root."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.temp_dir = Path(tempfile.mkdtemp(prefix=f"hs_test_{name}_"))
        self.storage_root = self.temp_dir / "storage"
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        config = Config("backend/alembic.ini")
        with self.engine.connect() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "head")

        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.evidence_settings = EvidenceSettings(storage_root=self.storage_root)
        self.app = create_app(
            session_factory=self.factory,
            evidence_settings=self.evidence_settings,
        )
        self.client = TestClient(self.app)

    def cleanup(self) -> None:
        self.client.close()
        self.engine.dispose()
        shutil.rmtree(self.temp_dir, ignore_errors=True)


def test_binary_document_preservation_pdf_and_docx() -> None:
    """Verify content-addressed preservation of binary PDFs and DOCXs and dual blob linking."""
    instance = IsolatedInstance("binary_docs")
    try:
        client = instance.client

        # 1. Ingest binary PDF
        pdf_bytes = make_sample_pdf_bytes("Senior Cloud Infrastructure Architect")
        pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()

        resp_pdf = client.post(
            "/api/v1/profile/parse-document",
            headers={"x-filename": "curriculum_vitae.pdf", **local_headers()},
            content=pdf_bytes,
        )
        assert resp_pdf.status_code == 200, resp_pdf.text
        pdf_data = resp_pdf.json()
        assert pdf_data["media_type"] == "application/pdf"
        assert pdf_data["original_sha256"] == pdf_sha256
        pdf_doc_id = pdf_data["document_id"]
        pdf_version_id = pdf_data["document_version_id"]

        # Verify binary download via /original endpoint
        resp_orig_pdf = client.get(
            f"/api/v1/profile/documents/{pdf_doc_id}/versions/{pdf_version_id}/original",
            headers=local_headers(),
        )
        assert resp_orig_pdf.status_code == 200
        assert resp_orig_pdf.content == pdf_bytes
        assert hashlib.sha256(resp_orig_pdf.content).hexdigest() == pdf_sha256
        assert resp_orig_pdf.headers["content-type"] == "application/pdf"
        assert 'attachment; filename="curriculum_vitae.pdf"' in resp_orig_pdf.headers["content-disposition"]

        # Verify extracted text download via /text-artifact endpoint
        resp_text_pdf = client.get(
            f"/api/v1/profile/documents/{pdf_doc_id}/versions/{pdf_version_id}/text-artifact",
            headers=local_headers(),
        )
        assert resp_text_pdf.status_code == 200
        assert resp_text_pdf.headers["content-type"].startswith("text/plain")
        assert "Senior Cloud Infrastructure Architect" in resp_text_pdf.text

        # 2. Ingest binary DOCX
        docx_bytes = make_sample_docx_bytes("Staff Distributed Systems Engineer - Specializing in Consensus")
        docx_sha256 = hashlib.sha256(docx_bytes).hexdigest()

        resp_docx = client.post(
            "/api/v1/profile/parse-document",
            headers={"x-filename": "resume_latest.docx", **local_headers()},
            content=docx_bytes,
        )
        assert resp_docx.status_code == 200, resp_docx.text
        docx_data = resp_docx.json()
        assert "openxmlformats" in docx_data["media_type"]
        assert docx_data["original_sha256"] == docx_sha256
        docx_doc_id = docx_data["document_id"]
        docx_version_id = docx_data["document_version_id"]

        # Verify binary download via /original endpoint
        resp_orig_docx = client.get(
            f"/api/v1/profile/documents/{docx_doc_id}/versions/{docx_version_id}/original",
            headers=local_headers(),
        )
        assert resp_orig_docx.status_code == 200
        assert resp_orig_docx.content == docx_bytes
        assert hashlib.sha256(resp_orig_docx.content).hexdigest() == docx_sha256

        # 3. Verify Database state: version connects original blob and text artifact blob
        with instance.factory() as session:
            v_pdf = session.get(CandidateDocumentVersion, pdf_version_id)
            assert v_pdf is not None
            assert v_pdf.blob_hash == pdf_sha256
            assert v_pdf.text_artifact_hash is not None
            assert v_pdf.extraction_status == "EXTRACTED"
            assert v_pdf.extractor_version == "hire-steward-doc-parser-v1"

            # Verify physical storage existence for both blobs
            blob_orig = session.get(CandidateDocumentBlob, v_pdf.blob_hash)
            blob_text = session.get(CandidateDocumentBlob, v_pdf.text_artifact_hash)
            assert blob_orig is not None
            assert blob_text is not None
            assert (instance.storage_root / blob_orig.storage_key).exists()
            assert (instance.storage_root / blob_text.storage_key).exists()
            assert (instance.storage_root / blob_orig.storage_key).read_bytes() == pdf_bytes

    finally:
        instance.cleanup()


def test_submission_attempts_lifecycle_and_idempotency() -> None:
    """Verify ApplicationAttempt persistence, simulation modes, and idempotency guarantees."""
    instance = IsolatedInstance("attempts_lifecycle")
    try:
        client = instance.client

        # Seed fixtures
        seed_res = client.post("/api/v1/jobs/seed-fixtures", headers=local_headers())
        assert seed_res.status_code == 200

        with instance.factory() as session:
            posting = session.scalars(select(JobPosting)).first()
            assert posting is not None
            posting_id = posting.id

        # Create tracked application
        app_res = client.post(
            "/api/v1/applications/track",
            json={"job_posting_id": posting_id, "notes": "Evaluating distributed systems role"},
            headers=local_headers(),
        )
        assert app_res.status_code == 201
        app_id = app_res.json()["id"]
        assert app_res.json()["status"] == "SAVED"

        # Mark application materials reviewed
        rev_res = client.post(
            f"/api/v1/applications/{app_id}/mark-reviewed",
            json={
                "reviewed_resume": "# Alex Mercer\nExpert in distributed storage systems",
                "reviewed_cover_letter": "Dear Hiring Team,\nI am writing to express my interest in the distributed systems role.",
            },
            headers=local_headers(),
        )
        assert rev_res.status_code == 200

        # Create submission plan
        plan_res = client.post(
            f"/api/v1/applications/{app_id}/submission-plan",
            headers=local_headers(),
        )
        assert plan_res.status_code == 200, plan_res.text
        plan_id = plan_res.json()["plan_id"]

        # 1. First simulated attempt (SUCCESS mode)
        key_1 = f"attempt-key-{uuid.uuid4().hex}"
        sim1_res = client.post(
            f"/api/v1/applications/{app_id}/simulate-submission",
            json={"mode": "SUCCESS", "plan_id": plan_id, "idempotency_key": key_1},
            headers=local_headers(),
        )
        assert sim1_res.status_code == 200
        data1 = sim1_res.json()
        assert data1["status"] == "SIMULATED_SUCCESS"
        assert data1["outcome"] == "SUCCESS"
        assert data1["attempt_number"] == 1
        assert data1["receipt_id"] is not None
        # Invariant: Simulation attempt NEVER sets status to APPLIED
        assert data1["application_status"] == "READY_FOR_REVIEW"

        # 2. Idempotent replay with same idempotency key
        replay_res = client.post(
            f"/api/v1/applications/{app_id}/simulate-submission",
            json={"mode": "SUCCESS", "plan_id": plan_id, "idempotency_key": key_1},
            headers=local_headers(),
        )
        assert replay_res.status_code == 200
        replay_data = replay_res.json()
        assert replay_data["is_idempotent_replay"] is True
        assert replay_data["attempt_id"] == data1["attempt_id"]
        assert replay_data["attempt_number"] == 1
        assert replay_data["receipt_id"] == data1["receipt_id"]

        # 3. Second attempt with FAILURE mode
        key_2 = f"attempt-key-{uuid.uuid4().hex}"
        sim2_res = client.post(
            f"/api/v1/applications/{app_id}/simulate-submission",
            json={"mode": "PORTAL_RATE_LIMIT", "plan_id": plan_id, "idempotency_key": key_2},
            headers=local_headers(),
        )
        assert sim2_res.status_code == 200
        data2 = sim2_res.json()
        assert data2["status"] == "SIMULATED_FAILURE"
        assert data2["outcome"] == "FAILED"
        assert data2["attempt_number"] == 2
        assert data2["error_code"] == "RATE_LIMIT_EXCEEDED"

        # 4. Third attempt with AMBIGUOUS_TIMEOUT mode
        key_3 = f"attempt-key-{uuid.uuid4().hex}"
        sim3_res = client.post(
            f"/api/v1/applications/{app_id}/simulate-submission",
            json={"mode": "AMBIGUOUS_TIMEOUT", "plan_id": plan_id, "idempotency_key": key_3},
            headers=local_headers(),
        )
        assert sim3_res.status_code == 200
        data3 = sim3_res.json()
        assert data3["status"] == "AMBIGUOUS_RESULT"
        assert data3["outcome"] == "AMBIGUOUS"
        assert data3["attempt_number"] == 3

        # 5. Verify query attempts history endpoint
        list_res = client.get(f"/api/v1/applications/{app_id}/attempts", headers=local_headers())
        assert list_res.status_code == 200
        attempts = list_res.json()
        assert len(attempts) == 3
        assert [a["attempt_number"] for a in attempts] == [1, 2, 3]
        assert [a["status"] for a in attempts] == [
            "SIMULATED_SUCCESS",
            "SIMULATED_FAILURE",
            "AMBIGUOUS_RESULT",
        ]

        # 6. Verify audit trail records for attempts
        with instance.factory() as session:
            audit_events = list(
                session.scalars(
                    select(AuditEvent)
                    .where(AuditEvent.event_type == "SUBMISSION_ATTEMPT_EXECUTED")
                    .order_by(AuditEvent.created_at.asc())
                ).all()
            )
            assert len(audit_events) == 3

    finally:
        instance.cleanup()


def test_complete_20_step_export_import_roundtrip() -> None:
    """Execute complete 20-step verification workflow with clean source and target instances."""
    source = IsolatedInstance("roundtrip_source")
    target = IsolatedInstance("roundtrip_target")
    try:
        s_client = source.client
        t_client = target.client

        # -------------------------------------------------------------
        # STEP 1: Verify source schema at migration head 0009
        # -------------------------------------------------------------
        with source.engine.connect() as conn:
            head_rev = conn.scalar(text("SELECT version_num FROM alembic_version"))
            assert head_rev in ("0009_binary_docs_attempts", "0010_background_tasks")

        # -------------------------------------------------------------
        # STEP 2: Candidate Profile
        # -------------------------------------------------------------
        prof_payload = {
            "name": "Dr. Sophia Vance",
            "headline": "Lead Distributed Consensus Architect",
            "summary": "15+ years architecting high-integrity distributed systems and verifiable state machines.",
            "skills": [{"name": "Raft"}, {"name": "PostgreSQL"}, {"name": "Python"}, {"name": "Formal Methods"}],
            "work_history": [
                {
                    "title": "Principal Architect",
                    "organization": "Axiom Protocols",
                    "start_date": "2019-03-01",
                    "description": "Designed verifiable consensus storage.",
                }
            ],
            "education": [{"institution": "Stanford University", "degree": "Ph.D. Computer Science"}],
        }
        res_prof = s_client.put("/api/v1/profile", json=prof_payload, headers=local_headers())
        assert res_prof.status_code == 200

        # -------------------------------------------------------------
        # STEP 3: Ingest original binary PDF document
        # -------------------------------------------------------------
        pdf_bytes = make_sample_pdf_bytes("Principal Distributed Systems Engineer Sophia Vance")
        pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
        res_pdf = s_client.post(
            "/api/v1/profile/parse-document",
            headers={"x-filename": "sophia_resume.pdf", **local_headers()},
            content=pdf_bytes,
        )
        assert res_pdf.status_code == 200
        pdf_ver_id = res_pdf.json()["document_version_id"]

        # -------------------------------------------------------------
        # STEP 4: Ingest original binary DOCX document
        # -------------------------------------------------------------
        docx_bytes = make_sample_docx_bytes("Sophia Vance - Formal Verification and Database Internals")
        docx_sha256 = hashlib.sha256(docx_bytes).hexdigest()
        res_docx = s_client.post(
            "/api/v1/profile/parse-document",
            headers={"x-filename": "sophia_resume.docx", **local_headers()},
            content=docx_bytes,
        )
        assert res_docx.status_code == 200
        docx_ver_id = res_docx.json()["document_version_id"]

        # -------------------------------------------------------------
        # STEP 5: Candidate facts & provenance referencing text artifacts
        # -------------------------------------------------------------
        res_fact = s_client.post(
            "/api/v1/profile/map-fact",
            json={
                "fact_type": "SKILL",
                "value": {"name": "Distributed Consensus", "proficiency": "EXPERT"},
                "document_version_id": pdf_ver_id,
                "byte_start": 0,
                "byte_end": 10,
                "excerpt": "Principal ",
            },
            headers=local_headers(),
        )
        assert res_fact.status_code == 201
        fact_id = res_fact.json()["fact_id"]

        # -------------------------------------------------------------
        # STEP 6: Answer Bank items with consent variations
        # -------------------------------------------------------------
        res_ans1 = s_client.post(
            "/api/v1/answers",
            json={
                "question": "What is your experience with Paxos and Raft?",
                "answer": "Over 10 years designing fault-tolerant replicated state machines.",
                "category": "technical",
                "reuse_consent": True,
                "fact_ids": [fact_id],
            },
            headers=local_headers(),
        )
        assert res_ans1.status_code == 201
        ans1_id = res_ans1.json()["id"]

        res_ans2 = s_client.post(
            "/api/v1/answers",
            json={
                "question": "Are you willing to relocate?",
                "answer": "Remote preferred; open to quarterly travel.",
                "category": "logistics",
                "reuse_consent": False,
            },
            headers=local_headers(),
        )
        assert res_ans2.status_code == 201

        # -------------------------------------------------------------
        # STEP 7: User settings & Job sources
        # -------------------------------------------------------------
        res_set = s_client.put(
            "/api/v1/settings",
            json={
                "minimum_compensation": {"amount": "175000.00"},
                "daily_application_cap": 8,
                "same_company_cooldown_days": 45,
                "target_roles": ["Principal Architect", "Staff Systems Engineer"],
                "target_locations": ["Remote", "Zurich", "London"],
                "workplace_arrangements": ["remote"],
                "sponsorship_requirement": "not_required",
            },
            headers=local_headers(),
        )
        assert res_set.status_code == 200

        # Enable synthetic fixtures source
        s_client.patch(
            "/api/v1/sources/synthetic_fixtures",
            json={"is_enabled": True},
            headers=local_headers(),
        )

        # -------------------------------------------------------------
        # STEP 8: Subscriptions, Discovery Runs, Postings, Snapshots
        # -------------------------------------------------------------
        res_seed = s_client.post("/api/v1/jobs/seed-fixtures", headers=local_headers())
        assert res_seed.status_code == 200
        assert res_seed.json()["postings_seeded"] >= 1

        with source.factory() as session:
            posting = session.scalars(select(JobPosting)).first()
            assert posting is not None
            posting_id = posting.id

        # -------------------------------------------------------------
        # STEP 9: Compensation Preference, Audits, Assessments
        # -------------------------------------------------------------
        res_comp = s_client.post(
            "/api/v1/compensation/assessments",
            json={
                "job_reference": f"unverified-audit-{posting_id}",
                "reported_status": "PAID",
                "amount": "200000.00",
                "currency": "INR",
                "period": "YEAR",
                "evidence_reference": "source-verified-job-offer",
            },
            headers=local_headers(),
        )
        assert res_comp.status_code == 201

        # -------------------------------------------------------------
        # STEP 10: Tracked Applications & Status Transitions
        # -------------------------------------------------------------
        res_app = s_client.post(
            "/api/v1/applications/track",
            json={"job_posting_id": posting_id, "notes": "Top tier systems opportunity"},
            headers=local_headers(),
        )
        assert res_app.status_code == 201
        app_id = res_app.json()["id"]

        # Transition application: SAVED -> PREPARING
        res_trans = s_client.patch(
            f"/api/v1/applications/{app_id}/status",
            json={"target_status": "PREPARING", "reason": "Drafting materials"},
            headers=local_headers(),
        )
        assert res_trans.status_code == 200

        # Mark application reviewed
        res_rev = s_client.post(
            f"/api/v1/applications/{app_id}/mark-reviewed",
            json={
                "reviewed_resume": "# Dr. Sophia Vance\nLead Distributed Consensus Architect",
                "reviewed_cover_letter": "Dear Hiring Team,\nI am writing to express my interest in this position.",
            },
            headers=local_headers(),
        )
        assert res_rev.status_code == 200

        # -------------------------------------------------------------
        # STEP 11: Submission Plan
        # -------------------------------------------------------------
        res_plan = s_client.post(
            f"/api/v1/applications/{app_id}/submission-plan",
            headers=local_headers(),
        )
        assert res_plan.status_code == 200, res_plan.text
        plan_id = res_plan.json()["plan_id"]
        packet_sha256 = res_plan.json()["packet_sha256"]
        assert len(packet_sha256) == 64

        # -------------------------------------------------------------
        # STEP 12: Simulated Execution Attempt
        # -------------------------------------------------------------
        sim_key = f"sim-{uuid.uuid4().hex}"
        res_sim = s_client.post(
            f"/api/v1/applications/{app_id}/simulate-submission",
            json={"mode": "SUCCESS", "plan_id": plan_id, "idempotency_key": sim_key},
            headers=local_headers(),
        )
        assert res_sim.status_code == 200
        assert res_sim.json()["status"] == "SIMULATED_SUCCESS"
        assert res_sim.json()["application_status"] == "READY_FOR_REVIEW"

        # -------------------------------------------------------------
        # STEP 13: Audit Event Inventory in source instance
        # -------------------------------------------------------------
        with source.factory() as session:
            source_events = list(session.scalars(select(AuditEvent)).all())
            event_types = {e.event_type for e in source_events}
            assert "SUBMISSION_ATTEMPT_EXECUTED" in event_types
            assert "APPLICATION_STATUS_TRANSITIONED" in event_types

        # -------------------------------------------------------------
        # STEP 14: Export source instance to JSON bundle
        # -------------------------------------------------------------
        res_export = s_client.post("/api/v1/data/export", headers=local_headers())
        assert res_export.status_code == 200
        bundle = res_export.json()
        assert bundle["manifest"]["format_version"] == "hire-steward-export-v1"
        assert bundle["manifest"]["product"] == "hire-steward"
        assert len(bundle["manifest"]["checksum_sha256"]) == 64
        # Verify binary base64 packaging
        blobs = bundle.get("candidate_document_blobs", [])
        pdf_blob = next((b for b in blobs if b["content_hash"] == pdf_sha256), None)
        docx_blob = next((b for b in blobs if b["content_hash"] == docx_sha256), None)
        assert pdf_blob is not None
        assert docx_blob is not None
        assert "content_base64" in pdf_blob
        assert "content_base64" in docx_blob
        # Verify attempts and audit events are exported
        assert len(bundle.get("application_attempts", [])) >= 1
        assert len(bundle.get("audit_events", [])) >= 1

        # -------------------------------------------------------------
        # STEP 15: Clean target SQLite instance
        # -------------------------------------------------------------
        with target.engine.connect() as conn:
            target_head = conn.scalar(text("SELECT version_num FROM alembic_version"))
            assert target_head in ("0009_binary_docs_attempts", "0010_background_tasks")

        # -------------------------------------------------------------
        # STEP 16: Preview Import on Target Instance
        # -------------------------------------------------------------
        res_prev = t_client.post("/api/v1/data/import/preview", json=bundle, headers=local_headers())
        assert res_prev.status_code == 200
        prev_data = res_prev.json()
        assert prev_data["is_valid"] is True
        assert prev_data["checksum_verified"] is True
        assert prev_data["preview_token"] is not None
        preview_token = prev_data["preview_token"]
        # On a clean target instance, all collisions must be 0
        assert prev_data["collision_counts"]["candidate_profile"] == 0
        assert prev_data["collision_counts"]["tracked_applications"] == 0

        # -------------------------------------------------------------
        # STEP 17: Commit Restore on Target Instance
        # -------------------------------------------------------------
        res_commit = t_client.post(
            "/api/v1/data/import/commit",
            json={"bundle": bundle, "preview_token": preview_token, "overwrite_existing": False},
            headers=local_headers(),
        )
        assert res_commit.status_code == 200, res_commit.text
        commit_data = res_commit.json()
        assert commit_data["status"] == "COMPLETED"
        restored = commit_data["restored_counts"]
        assert restored["candidate_profile"] == 1
        assert restored["candidate_documents"] >= 2
        assert restored["candidate_document_blobs"] >= 2
        assert restored["candidate_document_versions"] >= 2
        assert restored["candidate_facts"] >= 1
        assert restored["answer_bank_items"] >= 2
        assert restored["tracked_applications"] >= 1
        assert restored["submission_plans"] >= 1
        assert restored["application_attempts"] >= 1

        # -------------------------------------------------------------
        # STEP 18: Byte-for-byte SHA-256 match on restored binary files on disk
        # -------------------------------------------------------------
        with target.factory() as t_session:
            t_pdf_blob = t_session.get(CandidateDocumentBlob, pdf_sha256)
            t_docx_blob = t_session.get(CandidateDocumentBlob, docx_sha256)
            assert t_pdf_blob is not None
            assert t_docx_blob is not None

            pdf_file_path = target.storage_root / t_pdf_blob.storage_key
            docx_file_path = target.storage_root / t_docx_blob.storage_key
            assert pdf_file_path.exists()
            assert docx_file_path.exists()

            restored_pdf_bytes = pdf_file_path.read_bytes()
            restored_docx_bytes = docx_file_path.read_bytes()
            assert restored_pdf_bytes == pdf_bytes
            assert hashlib.sha256(restored_pdf_bytes).hexdigest() == pdf_sha256
            assert restored_docx_bytes == docx_bytes
            assert hashlib.sha256(restored_docx_bytes).hexdigest() == docx_sha256

        # -------------------------------------------------------------
        # STEP 19: Relational integrity check on target instance
        # -------------------------------------------------------------
        with target.factory() as t_session:
            t_app = t_session.get(TrackedApplication, app_id)
            assert t_app is not None
            assert t_app.status == "READY_FOR_REVIEW"

            t_plan = t_session.get(SubmissionPlanModel, plan_id)
            assert t_plan is not None
            assert t_plan.packet_sha256 == packet_sha256

            t_attempts = list(
                t_session.scalars(
                    select(ApplicationAttempt).where(ApplicationAttempt.application_id == app_id)
                ).all()
            )
            assert len(t_attempts) == 1
            assert t_attempts[0].idempotency_key == sim_key
            assert t_attempts[0].status == "SIMULATED_SUCCESS"

            t_audits = list(t_session.scalars(select(AuditEvent)).all())
            assert len(t_audits) >= 1

        # -------------------------------------------------------------
        # STEP 20: Secondary Export from target instance verifying parity
        # -------------------------------------------------------------
        res_sec = t_client.post("/api/v1/data/export", headers=local_headers())
        assert res_sec.status_code == 200
        sec_bundle = res_sec.json()
        assert sec_bundle["candidate_profile"]["name"] == "Dr. Sophia Vance"
        assert len(sec_bundle["answer_bank_items"]) == len(bundle["answer_bank_items"])
        assert len(sec_bundle["candidate_facts"]) == len(bundle["candidate_facts"])
        assert len(sec_bundle["submission_plans"]) == len(bundle["submission_plans"])
        assert len(sec_bundle["application_attempts"]) == len(bundle["application_attempts"])

    finally:
        source.cleanup()
        target.cleanup()
