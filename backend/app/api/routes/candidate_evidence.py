from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.app.adapters.storage import EvidenceStorage
from backend.app.api.dependencies import get_session, require_local_same_origin
from backend.app.api.schemas import CandidateFactInput, DocumentCreateInput, ProvenanceInput
from backend.app.db.models import (
    CandidateDocument,
    CandidateDocumentBlob,
    CandidateDocumentVersion,
    CandidateFact,
    CandidateFactEvidence,
)
from backend.app.domain.candidate_evidence import CandidateEvidenceError, sanitize_filename
from backend.app.evidence_config import EvidenceSettings
from backend.app.services import candidate_evidence as service


router = APIRouter(prefix="/api/v1")


def _raise_safe(error: CandidateEvidenceError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.code) from error


def _storage(request: Request) -> EvidenceStorage:
    storage: EvidenceStorage | None = getattr(request.app.state, "evidence_storage", None)
    if storage is None:
        raise HTTPException(status_code=503, detail="EVIDENCE_STORAGE_UNAVAILABLE")
    return storage


def _settings(request: Request) -> EvidenceSettings:
    settings: EvidenceSettings | None = getattr(request.app.state, "evidence_settings", None)
    if settings is None:
        raise HTTPException(status_code=503, detail="EVIDENCE_STORAGE_UNAVAILABLE")
    return settings


def _document_view(document: CandidateDocument) -> dict[str, object]:
    return {
        "document_id": document.id,
        "display_name": document.display_name,
        "state": document.state,
        "created_at": document.created_at.isoformat(),
        "retired_at": None if document.retired_at is None else document.retired_at.isoformat(),
    }


def _version_view(
    version: CandidateDocumentVersion, *, byte_size: int, media_type: str = "text/plain"
) -> dict[str, object]:
    result: dict[str, object] = {
        "document_version_id": version.id,
        "document_id": version.document_id,
        "version_number": version.version_number,
        "blob_hash": version.blob_hash,
        "filename": version.original_filename,
        "media_type": media_type,
        "byte_size": byte_size,
        "ingested_at": version.ingested_at.isoformat(),
        "extraction_status": version.extraction_status,
    }
    if byte_size is not None:
        result["byte_size"] = byte_size
    return result


def _version_view_from_database(
    session: Session, version: CandidateDocumentVersion
) -> dict[str, object]:
    blob = session.get(CandidateDocumentBlob, version.blob_hash)
    if blob is None:
        raise HTTPException(status_code=503, detail="EVIDENCE_STORAGE_INTEGRITY_ERROR")
    return _version_view(version, byte_size=blob.byte_size, media_type=blob.media_type)


def _fact_view(fact: CandidateFact) -> dict[str, object]:
    return {
        "fact_id": fact.id,
        "fact_type": fact.fact_type,
        "value": fact.value_json,
        "verification_state": fact.verification_state,
        "created_at": fact.created_at.isoformat(),
    }


def _evidence_view(evidence: CandidateFactEvidence, fact: CandidateFact) -> dict[str, object]:
    return {
        "provenance_id": evidence.id,
        "fact_id": evidence.fact_id,
        "document_version_id": evidence.document_version_id,
        "byte_start": evidence.byte_start,
        "byte_end": evidence.byte_end,
        "evidence_hash": evidence.evidence_hash,
        "method": evidence.method,
        "verification_state": fact.verification_state,
        "created_at": evidence.created_at.isoformat(),
    }


@router.post("/documents", status_code=status.HTTP_201_CREATED)
def create_document(
    payload: DocumentCreateInput,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, object]:
    return _document_view(service.create_document(session, payload.display_name))


@router.get("/documents")
def get_documents(session: Session = Depends(get_session)) -> list[dict[str, object]]:
    return [_document_view(item) for item in service.list_documents(session)]


@router.get("/documents/{document_id}")
def get_document(document_id: str, session: Session = Depends(get_session)) -> dict[str, object]:
    try:
        return _document_view(service.get_document(session, document_id))
    except CandidateEvidenceError as exc:
        _raise_safe(exc)


@router.post("/documents/{document_id}/retire")
def retire_document(
    document_id: str,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, object]:
    try:
        return _document_view(service.retire_document(session, document_id))
    except CandidateEvidenceError as exc:
        _raise_safe(exc)


@router.get("/documents/{document_id}/versions")
def get_document_versions(
    document_id: str, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    try:
        return [
            _version_view_from_database(session, item)
            for item in service.list_document_versions(session, document_id)
        ]
    except CandidateEvidenceError as exc:
        _raise_safe(exc)


@router.post("/documents/{document_id}/versions")
async def create_document_version(
    document_id: str,
    request: Request,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
):
    content_type = request.headers.get("content-type", "").lower()
    allowed_types = {"text/plain", "text/plain; charset=utf-8"}
    if content_type not in allowed_types:
        raise HTTPException(status_code=415, detail="UNSUPPORTED_MEDIA_TYPE")
    try:
        declared_length = request.headers.get("content-length")
        if declared_length is not None and int(declared_length) > _settings(request).max_version_bytes:
            raise HTTPException(status_code=413, detail="DOCUMENT_TOO_LARGE")
        if declared_length is not None and int(declared_length) < 0:
            raise ValueError
        filename = sanitize_filename(request.headers.get("x-original-filename", ""))
    except (ValueError, CandidateEvidenceError) as exc:
        raise HTTPException(status_code=422, detail="INVALID_DOCUMENT_CONTENT") from exc
    storage = _storage(request)
    settings = _settings(request)
    try:
        reservation = service.reserve_upload(session, document_id, storage, settings)
    except CandidateEvidenceError as exc:
        _raise_safe(exc)
    upload_slot_held = True
    try:
        try:
            staged = await storage.stage_stream(reservation.temp_key, request.stream())
        except CandidateEvidenceError as exc:
            if exc.code != "EVIDENCE_STORAGE_PENDING_RECONCILIATION":
                try:
                    service.release_failed_reservation(session, reservation.id, storage)
                finally:
                    upload_slot_held = False
            raise
        except OSError as exc:
            # Preserve durable reservation. It accounts for any partial file until
            # operator reconciliation can inspect this request-owned key.
            raise HTTPException(status_code=503, detail="EVIDENCE_STORAGE_UNAVAILABLE") from exc

        service.mark_reservation_ready(session, reservation.id, staged)
        try:
            finalized = service.finalize_document_version(
                session, document_id, reservation.id, staged, storage, filename
            )
        finally:
            # finalize_document_version owns its success/failure release path.
            upload_slot_held = False
        return JSONResponse(
            status_code=201 if finalized.created else 200,
            content=_version_view(finalized.version, byte_size=staged.byte_size),
        )
    except CandidateEvidenceError as exc:
        _raise_safe(exc)
    finally:
        # Any unexpected failure before finalization must not exhaust the
        # process-local stream limiter; reservation bytes remain durable.
        if upload_slot_held:
            storage.release_upload_slot()


@router.post("/facts", status_code=status.HTTP_201_CREATED)
def create_fact(
    payload: CandidateFactInput,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, object]:
    return _fact_view(service.create_fact(session, payload.fact_type, payload.value))


@router.get("/facts")
def get_facts(session: Session = Depends(get_session)) -> list[dict[str, object]]:
    return [_fact_view(item) for item in service.list_facts(session)]


@router.get("/facts/{fact_id}")
def get_fact(fact_id: str, session: Session = Depends(get_session)) -> dict[str, object]:
    try:
        return _fact_view(service.get_fact(session, fact_id))
    except CandidateEvidenceError as exc:
        _raise_safe(exc)


@router.post("/facts/{fact_id}/provenance", status_code=status.HTTP_201_CREATED)
def create_provenance(
    fact_id: str,
    payload: ProvenanceInput,
    request: Request,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, object]:
    try:
        evidence = service.attach_provenance(
            session,
            fact_id,
            str(payload.document_version_id),
            payload.byte_start,
            payload.byte_end,
            payload.excerpt,
            _storage(request),
        )
        fact = service.get_fact(session, fact_id)
        return _evidence_view(evidence, fact)
    except CandidateEvidenceError as exc:
        _raise_safe(exc)


@router.get("/facts/{fact_id}/provenance")
def get_provenance(
    fact_id: str, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    try:
        fact = service.get_fact(session, fact_id)
        return [_evidence_view(item, fact) for item in service.list_fact_evidence(session, fact_id)]
    except CandidateEvidenceError as exc:
        _raise_safe(exc)
