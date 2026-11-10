"""Candidate Profile API endpoints (Stage 2 & Stage 7 Screen 3)."""

from __future__ import annotations

import hashlib
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.adapters.storage import EvidenceStorage
from backend.app.api.dependencies import get_session, require_local_same_origin
from backend.app.domain.candidate_evidence import CandidateEvidenceError, FactType
from backend.app.domain.candidate_profile import calculate_profile_completeness
from backend.app.evidence_config import EvidenceSettings
from backend.app.services import candidate_evidence
from backend.app.services import candidate_profile as profile_service
from backend.app.services.document_parser import (
    DocumentParserError,
    parse_document_file,
    sanitize_filename_safe,
)

router = APIRouter(prefix="/api/v1/profile", tags=["Candidate Profile"])


class ProfileUpdateRequest(BaseModel):
    name: str | None = None
    headline: str | None = None
    summary: str | None = None
    contact_info: dict[str, Any] | None = None
    education: list[dict[str, Any]] | None = None
    employment: list[dict[str, Any]] | None = None
    projects: list[dict[str, Any]] | None = None
    skills: list[dict[str, Any]] | None = None
    certifications: list[dict[str, Any]] | None = None


def _profile_to_dict(profile: Any) -> dict[str, Any]:
    return {
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
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


@router.get("")
def get_profile(
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Retrieve candidate profile and completeness assessment."""
    profile = profile_service.get_or_create_profile(session)
    report = profile_service.get_profile_report(session)
    return {
        "profile": _profile_to_dict(profile),
        "completeness": {
            "score": report.score,
            "percentage": report.percentage,
            "missing_elements": report.missing_elements,
            "strengths": report.strengths,
        },
    }


@router.put("")
def update_profile(
    payload: ProfileUpdateRequest,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, Any]:
    """Update profile fields, persist changes, and refresh completeness."""
    update_data = {k: v for k, v in payload.model_dump().items() if v is not None}
    with session.begin():
        profile = profile_service.update_profile(session, update_data)
        report = profile_service.get_profile_report(session)

    return {
        "profile": _profile_to_dict(profile),
        "completeness": {
            "score": report.score,
            "percentage": report.percentage,
            "missing_elements": report.missing_elements,
            "strengths": report.strengths,
        },
    }


@router.post("/completeness")
def assess_completeness(
    payload: ProfileUpdateRequest,
) -> dict[str, Any]:
    """Assess completeness report for given profile payload without saving."""
    data = payload.model_dump()
    report = calculate_profile_completeness(data)
    return {
        "score": report.score,
        "percentage": report.percentage,
        "missing_elements": report.missing_elements,
        "strengths": report.strengths,
    }


class MapFactRequest(BaseModel):
    document_version_id: str | None = None
    fact_type: str
    value: dict[str, Any] = Field(default_factory=dict)
    section_heading: str | None = None
    section_text: str | None = None
    byte_start: int | None = None
    byte_end: int | None = None
    excerpt: str | None = None


def infer_suggested_fact_type(heading: str | None, text: str) -> str | None:
    target = f"{heading or ''} {text}".lower()
    if any(k in target for k in ["certificat", "license", "credential"]):
        return FactType.CERTIFICATION.value
    if any(k in target for k in ["project", "portfolio"]):
        return FactType.PROJECT.value
    if any(k in target for k in ["education", "degree", "university", "college", "bachelor", "master", "phd", "academic"]):
        return FactType.EDUCATION.value
    if any(k in target for k in ["experience", "employment", "work history", "job history"]):
        return FactType.EMPLOYMENT.value
    if any(k in target for k in ["skill", "technolog", "proficienc", "programming", "languages"]):
        return FactType.SKILL.value
    return None


@router.post("/parse-document")
async def parse_uploaded_resume(
    request: Request,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, Any]:
    """Parse raw text, markdown, docx, or pdf bytes and return extracted sections."""
    max_bytes = 10 * 1024 * 1024  # 10 MB limit
    chunks: list[bytes] = []
    total_bytes = 0
    async for chunk in request.stream():
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise HTTPException(status_code=413, detail="DOCUMENT_TOO_LARGE")
        chunks.append(chunk)

    body = b"".join(chunks)
    if not body:
        raise HTTPException(status_code=400, detail="EMPTY_DOCUMENT_BODY")

    filename = sanitize_filename_safe(request.headers.get("x-filename", "resume.txt"))
    try:
        parsed = parse_document_file(filename, body)
    except DocumentParserError as exc:
        raise HTTPException(status_code=422, detail=f"PARSE_ERROR: {exc.message}") from exc

    storage: EvidenceStorage | None = getattr(request.app.state, "evidence_storage", None)
    settings: EvidenceSettings | None = getattr(request.app.state, "evidence_settings", None)
    document_id: str | None = None
    document_version_id: str | None = None

    if storage is not None and settings is not None:
        try:
            doc = candidate_evidence.create_document(session, display_name=filename)
            document_id = doc.id
            reservation = candidate_evidence.reserve_upload(session, document_id, storage, settings)
            upload_slot_held = True
            try:
                # Stage original binary file
                staged_original = storage.stage_binary(reservation.temp_key, body)
                candidate_evidence.mark_reservation_ready(session, reservation.id, staged_original)

                # Stage extracted text artifact
                text_bytes = parsed.raw_text.encode("utf-8")
                staged_text = storage.stage_binary(storage.temp_key(), text_bytes)

                # Transfer upload slot release responsibility to finalize_document_version
                upload_slot_held = False
                finalized = candidate_evidence.finalize_document_version(
                    session,
                    document_id=document_id,
                    reservation_id=reservation.id,
                    staged=staged_original,
                    storage=storage,
                    original_filename=filename,
                    media_type=parsed.media_type,
                    text_staged=staged_text,
                    extraction_status="EXTRACTED",
                    extractor_version="hire-steward-doc-parser-v1",
                )
                document_version_id = finalized.version.id
            finally:
                if upload_slot_held:
                    storage.release_upload_slot()
        except CandidateEvidenceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=f"EVIDENCE_ERROR: {exc.code}") from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"STORAGE_PERSISTENCE_FAILED: {str(exc)}") from exc

    return {
        "document_id": document_id,
        "document_version_id": document_version_id,
        "filename": parsed.filename,
        "media_type": parsed.media_type,
        "original_sha256": hashlib.sha256(body).hexdigest(),
        "char_count": parsed.char_count,
        "sections_count": len(parsed.sections),
        "sections": [
            {
                "heading": s.heading,
                "type": s.section_type,
                "text": s.text,
                "start": s.start_char,
                "end": s.end_char,
                "byte_start": s.byte_start,
                "byte_end": s.byte_end,
                "suggested_fact_type": infer_suggested_fact_type(s.heading, s.text),
            }
            for s in parsed.sections
        ],
        "raw_text": parsed.raw_text,
    }


@router.post("/map-fact", status_code=status.HTTP_201_CREATED)
def map_fact(
    payload: MapFactRequest,
    request: Request,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, Any]:
    """Map an extracted section to a CandidateFact and optionally attach provenance."""
    fact_type_str = payload.fact_type.strip().upper()
    try:
        fact_type_enum = FactType(fact_type_str)
    except ValueError:
        valid_types = ", ".join(f.value for f in FactType)
        raise HTTPException(
            status_code=422,
            detail=f"INVALID_FACT_TYPE: '{payload.fact_type}'. Allowed: {valid_types}",
        )

    try:
        with session.begin_nested() if session.in_transaction() else session.begin():
            fact_val = dict(payload.value) if payload.value else {}
            if not fact_val and (payload.section_text or payload.section_heading):
                fact_val = {
                    "text": payload.section_text or "",
                    "heading": payload.section_heading or "",
                    "source": "Document Extraction",
                }
            if not fact_val:
                fact_val = {"text": payload.excerpt or "Extracted Section", "source": "Document Extraction"}

            if fact_type_enum == FactType.SKILL:
                fact_val["name"] = fact_val.get("name") or payload.section_text or fact_val.get("text") or fact_val.get("skill") or ""

            fact = candidate_evidence.create_fact(
                session, fact_type=fact_type_enum.value, value=fact_val
            )
            provenance_id = None
            if (
                payload.document_version_id
                and payload.byte_start is not None
                and payload.byte_end is not None
            ):
                storage: EvidenceStorage | None = getattr(request.app.state, "evidence_storage", None)
                if storage is None:
                    raise HTTPException(status_code=503, detail="EVIDENCE_STORAGE_UNAVAILABLE")
                doc_excerpt = payload.excerpt or (payload.section_text[:500] if payload.section_text else None)
                evidence = candidate_evidence.attach_provenance(
                    session=session,
                    fact_id=fact.id,
                    version_id=payload.document_version_id,
                    start=payload.byte_start,
                    end=payload.byte_end,
                    excerpt=payload.excerpt,
                    storage=storage,
                )
                provenance_id = evidence.id
    except CandidateEvidenceError as exc:
        session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=f"EVIDENCE_ERROR: {exc.code}") from exc
    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"FACT_MAPPING_FAILED: {str(exc)}") from exc

    return {
        "fact_id": fact.id,
        "fact_type": fact.fact_type,
        "value": fact.value_json,
        "verification_state": fact.verification_state,
        "provenance_id": provenance_id,
        "document_version_id": payload.document_version_id,
    }


@router.get("/documents/{document_id}/versions/{version_id}/original")
def get_original_binary_document(
    document_id: str,
    version_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> Response:
    """Download the preserved original binary file (PDF/DOCX/TXT/MD)."""
    from backend.app.db.models import CandidateDocumentVersion, CandidateDocumentBlob

    version = session.get(CandidateDocumentVersion, version_id)
    if version is None or version.document_id != document_id:
        raise HTTPException(status_code=404, detail="DOCUMENT_VERSION_NOT_FOUND")

    blob = session.get(CandidateDocumentBlob, version.blob_hash)
    if blob is None:
        raise HTTPException(status_code=404, detail="DOCUMENT_BLOB_NOT_FOUND")

    storage: EvidenceStorage | None = getattr(request.app.state, "evidence_storage", None)
    if storage is None:
        raise HTTPException(status_code=503, detail="EVIDENCE_STORAGE_UNAVAILABLE")

    try:
        raw_bytes = storage.read_bytes(blob.storage_key)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"STORAGE_READ_FAILED: {exc}") from exc

    return Response(
        content=raw_bytes,
        media_type=blob.media_type,
        headers={"Content-Disposition": f'attachment; filename="{version.original_filename}"'},
    )


@router.get("/documents/{document_id}/versions/{version_id}/text-artifact")
def get_extracted_text_artifact(
    document_id: str,
    version_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> Response:
    """Download the extracted normalized UTF-8 text artifact."""
    from backend.app.db.models import CandidateDocumentVersion, CandidateDocumentBlob

    version = session.get(CandidateDocumentVersion, version_id)
    if version is None or version.document_id != document_id:
        raise HTTPException(status_code=404, detail="DOCUMENT_VERSION_NOT_FOUND")

    target_hash = getattr(version, "text_artifact_hash", None) or version.blob_hash
    blob = session.get(CandidateDocumentBlob, target_hash)
    if blob is None:
        raise HTTPException(status_code=404, detail="TEXT_ARTIFACT_BLOB_NOT_FOUND")

    storage: EvidenceStorage | None = getattr(request.app.state, "evidence_storage", None)
    if storage is None:
        raise HTTPException(status_code=503, detail="EVIDENCE_STORAGE_UNAVAILABLE")

    try:
        raw_bytes = storage.read_bytes(blob.storage_key)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"STORAGE_READ_FAILED: {exc}") from exc

    return Response(
        content=raw_bytes,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{version.original_filename}.txt"'},
    )

