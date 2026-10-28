from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.adapters.storage import EvidenceStorage, StagedContent
from backend.app.db.models import (
    CandidateDocument,
    CandidateDocumentBlob,
    CandidateDocumentVersion,
    CandidateEvidenceStorageReservation,
    CandidateEvidenceStorageUsage,
    CandidateFact,
    CandidateFactEvidence,
)
from backend.app.domain.candidate_evidence import (
    CandidateEvidenceError,
    DocumentState,
    FactVerificationState,
    ReservationState,
    canonical_json_and_hash,
)
from backend.app.evidence_config import EvidenceSettings


@dataclass(frozen=True)
class FinalizedVersion:
    version: CandidateDocumentVersion
    created: bool


def _locked_usage(session: Session) -> CandidateEvidenceStorageUsage:
    usage = session.scalar(
        select(CandidateEvidenceStorageUsage)
        .where(CandidateEvidenceStorageUsage.id == 1)
        .with_for_update()
    )
    if usage is None:
        raise CandidateEvidenceError("EVIDENCE_STORAGE_UNAVAILABLE", 503)
    return usage


def create_document(session: Session, display_name: str) -> CandidateDocument:
    document = CandidateDocument(id=str(uuid4()), display_name=display_name, state=DocumentState.ACTIVE.value)
    with session.begin():
        session.add(document)
    return document


def get_document(session: Session, document_id: str) -> CandidateDocument:
    document = session.get(CandidateDocument, document_id)
    if document is None:
        raise CandidateEvidenceError("DOCUMENT_NOT_FOUND", 404)
    return document


def list_documents(session: Session) -> list[CandidateDocument]:
    return list(session.scalars(select(CandidateDocument).order_by(CandidateDocument.created_at.desc())))


def list_document_versions(session: Session, document_id: str) -> list[CandidateDocumentVersion]:
    get_document(session, document_id)
    return list(
        session.scalars(
            select(CandidateDocumentVersion)
            .where(CandidateDocumentVersion.document_id == document_id)
            .order_by(CandidateDocumentVersion.version_number)
        )
    )


def retire_document(session: Session, document_id: str) -> CandidateDocument:
    with session.begin():
        document = session.scalar(
            select(CandidateDocument).where(CandidateDocument.id == document_id).with_for_update()
        )
        if document is None:
            raise CandidateEvidenceError("DOCUMENT_NOT_FOUND", 404)
        if document.state == DocumentState.ACTIVE.value:
            document.state = DocumentState.RETIRED.value
            document.retired_at = datetime.now(timezone.utc)
    return document


def reserve_upload(
    session: Session, document_id: str, storage: EvidenceStorage, settings: EvidenceSettings
) -> CandidateEvidenceStorageReservation:
    if not storage.acquire_upload_slot():
        raise CandidateEvidenceError("EVIDENCE_STORAGE_UNAVAILABLE", 503)
    try:
        reservation = CandidateEvidenceStorageReservation(
            id=str(uuid4()),
            reserved_bytes=settings.max_version_bytes,
            temp_key=storage.temp_key(),
            state=ReservationState.STAGING.value,
        )
        with session.begin():
            document = session.scalar(
                select(CandidateDocument).where(CandidateDocument.id == document_id).with_for_update()
            )
            if document is None:
                raise CandidateEvidenceError("DOCUMENT_NOT_FOUND", 404)
            if document.state != DocumentState.ACTIVE.value:
                raise CandidateEvidenceError("DOCUMENT_RETIRED", 409)
            usage = _locked_usage(session)
            if usage.committed_bytes + usage.reserved_bytes + reservation.reserved_bytes > settings.max_total_bytes:
                raise CandidateEvidenceError("EVIDENCE_STORAGE_UNAVAILABLE", 503)
            usage.reserved_bytes += reservation.reserved_bytes
            usage.version += 1
            session.add(reservation)
        return reservation
    except Exception:
        storage.release_upload_slot()
        raise


def release_failed_reservation(
    session: Session, reservation_id: str, storage: EvidenceStorage
) -> None:
    try:
        with session.begin():
            reservation = session.scalar(
                select(CandidateEvidenceStorageReservation)
                .where(CandidateEvidenceStorageReservation.id == reservation_id)
                .with_for_update()
            )
            if reservation is None:
                return
            usage = _locked_usage(session)
            usage.reserved_bytes -= reservation.reserved_bytes
            usage.version += 1
            session.delete(reservation)
    finally:
        storage.release_upload_slot()


def mark_reservation_ready(
    session: Session, reservation_id: str, staged: StagedContent
) -> CandidateEvidenceStorageReservation:
    with session.begin():
        reservation = session.scalar(
            select(CandidateEvidenceStorageReservation)
            .where(CandidateEvidenceStorageReservation.id == reservation_id)
            .with_for_update()
        )
        if reservation is None or reservation.state != ReservationState.STAGING.value:
            raise CandidateEvidenceError("EVIDENCE_STORAGE_INTEGRITY_ERROR", 503)
        reservation.state = ReservationState.READY_TO_PLACE.value
        reservation.content_hash = staged.content_hash
        reservation.final_key = staged.final_key
        reservation.actual_size = staged.byte_size
    return reservation


def finalize_document_version(
    session: Session,
    document_id: str,
    reservation_id: str,
    staged: StagedContent,
    storage: EvidenceStorage,
    original_filename: str,
) -> FinalizedVersion:
    try:
        with session.begin():
            usage = _locked_usage(session)
            reservation = session.scalar(
                select(CandidateEvidenceStorageReservation)
                .where(CandidateEvidenceStorageReservation.id == reservation_id)
                .with_for_update()
            )
            document = session.scalar(
                select(CandidateDocument).where(CandidateDocument.id == document_id).with_for_update()
            )
            if reservation is None or document is None:
                raise CandidateEvidenceError("EVIDENCE_STORAGE_INTEGRITY_ERROR", 503)
            if document.state != DocumentState.ACTIVE.value:
                raise CandidateEvidenceError("DOCUMENT_RETIRED", 409)
            if (
                reservation.state != ReservationState.READY_TO_PLACE.value
                or reservation.content_hash != staged.content_hash
                or reservation.final_key != staged.final_key
                or reservation.actual_size != staged.byte_size
            ):
                raise CandidateEvidenceError("EVIDENCE_STORAGE_INTEGRITY_ERROR", 503)
            existing = session.scalar(
                select(CandidateDocumentVersion).where(
                    CandidateDocumentVersion.document_id == document_id,
                    CandidateDocumentVersion.blob_hash == staged.content_hash,
                )
            )
            blob = session.get(CandidateDocumentBlob, staged.content_hash)
            if existing is not None:
                if blob is None:
                    raise CandidateEvidenceError("EVIDENCE_STORAGE_INTEGRITY_ERROR", 503)
                storage.verify(blob.storage_key, blob.content_hash, blob.byte_size)
                if not storage.remove(staged.temp_key):
                    raise CandidateEvidenceError("EVIDENCE_STORAGE_PENDING_RECONCILIATION", 503)
                usage.reserved_bytes -= reservation.reserved_bytes
                usage.version += 1
                session.delete(reservation)
                return FinalizedVersion(existing, created=False)
            if blob is None:
                other_reservation = session.scalar(
                    select(CandidateEvidenceStorageReservation).where(
                        CandidateEvidenceStorageReservation.id != reservation.id,
                        CandidateEvidenceStorageReservation.final_key == staged.final_key,
                    )
                )
                if other_reservation is not None:
                    raise CandidateEvidenceError("EVIDENCE_STORAGE_PENDING_RECONCILIATION", 503)
                created_file = storage.place(staged)
                if not created_file:
                    raise CandidateEvidenceError("EVIDENCE_STORAGE_PENDING_RECONCILIATION", 503)
                blob = CandidateDocumentBlob(
                    content_hash=staged.content_hash,
                    storage_key=staged.final_key,
                    media_type="text/plain",
                    byte_size=staged.byte_size,
                )
                session.add(blob)
                usage.committed_bytes += staged.byte_size
            else:
                storage.verify(blob.storage_key, blob.content_hash, blob.byte_size)
                if not storage.remove(staged.temp_key):
                    raise CandidateEvidenceError("EVIDENCE_STORAGE_PENDING_RECONCILIATION", 503)
            version_number = (
                session.scalar(
                    select(func.max(CandidateDocumentVersion.version_number)).where(
                        CandidateDocumentVersion.document_id == document_id
                    )
                )
                or 0
            ) + 1
            version = CandidateDocumentVersion(
                id=str(uuid4()),
                document_id=document_id,
                version_number=version_number,
                blob_hash=staged.content_hash,
                original_filename=original_filename,
                extraction_status="NOT_REQUESTED",
            )
            usage.reserved_bytes -= reservation.reserved_bytes
            usage.version += 1
            session.add(version)
            session.delete(reservation)
            return FinalizedVersion(version, created=True)
    finally:
        storage.release_upload_slot()
def create_fact(session: Session, fact_type: str, value: dict[str, object]) -> CandidateFact:
    canonical_value, value_hash = canonical_json_and_hash(value)
    del canonical_value
    fact = CandidateFact(
        id=str(uuid4()),
        fact_type=fact_type,
        value_json=value,
        value_hash=value_hash,
        verification_state=FactVerificationState.UNREVIEWED.value,
    )
    with session.begin():
        session.add(fact)
    return fact


def get_fact(session: Session, fact_id: str) -> CandidateFact:
    fact = session.get(CandidateFact, fact_id)
    if fact is None:
        raise CandidateEvidenceError("FACT_NOT_FOUND", 404)
    return fact


def list_facts(session: Session) -> list[CandidateFact]:
    return list(session.scalars(select(CandidateFact).order_by(CandidateFact.created_at.desc())))


def attach_provenance(
    session: Session,
    fact_id: str,
    version_id: str,
    start: int,
    end: int,
    excerpt: str | None,
    storage: EvidenceStorage,
) -> CandidateFactEvidence:
    if end - start > 4096:
        raise CandidateEvidenceError("INVALID_PROVENANCE", 422)
    with session.begin():
        fact = session.scalar(select(CandidateFact).where(CandidateFact.id == fact_id).with_for_update())
        version = session.get(CandidateDocumentVersion, version_id)
        if fact is None or version is None:
            raise CandidateEvidenceError("FACT_OR_DOCUMENT_VERSION_NOT_FOUND", 404)
        blob = session.get(CandidateDocumentBlob, version.blob_hash)
        if blob is None:
            raise CandidateEvidenceError("EVIDENCE_STORAGE_INTEGRITY_ERROR", 503)
        storage.verify(blob.storage_key, blob.content_hash, blob.byte_size)
        span = storage.read_span(blob.storage_key, start, end)
        try:
            decoded = span.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise CandidateEvidenceError("INVALID_PROVENANCE", 422) from exc
        if excerpt is not None and excerpt != decoded:
            raise CandidateEvidenceError("INVALID_PROVENANCE", 422)
        duplicate = session.scalar(
            select(CandidateFactEvidence).where(
                CandidateFactEvidence.fact_id == fact_id,
                CandidateFactEvidence.document_version_id == version_id,
                CandidateFactEvidence.byte_start == start,
                CandidateFactEvidence.byte_end == end,
            )
        )
        if duplicate is not None:
            raise CandidateEvidenceError("DUPLICATE_PROVENANCE", 409)
        evidence = CandidateFactEvidence(
            id=str(uuid4()),
            fact_id=fact_id,
            document_version_id=version_id,
            byte_start=start,
            byte_end=end,
            evidence_hash=hashlib.sha256(span).hexdigest(),
            method="LOCAL_API_REPORTED",
        )
        session.add(evidence)
    return evidence


def list_fact_evidence(session: Session, fact_id: str) -> list[CandidateFactEvidence]:
    get_fact(session, fact_id)
    return list(
        session.scalars(
            select(CandidateFactEvidence)
            .where(CandidateFactEvidence.fact_id == fact_id)
            .order_by(CandidateFactEvidence.created_at)
        )
    )


def reconcile_stale_reservations(
    session: Session, storage: EvidenceStorage, settings: EvidenceSettings
) -> dict[str, int]:
    """Operator-only recovery. Unexpected files are reported, never auto-deleted."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.reconciliation_grace_seconds)
    released = 0
    protected = 0
    unexpected_files = 0
    with session.begin():
        usage = _locked_usage(session)
        reservations = list(
            session.scalars(
                select(CandidateEvidenceStorageReservation)
                .where(CandidateEvidenceStorageReservation.created_at <= cutoff)
                .with_for_update()
            )
        )
        all_reservations = list(session.scalars(select(CandidateEvidenceStorageReservation)))
        blobs = list(session.scalars(select(CandidateDocumentBlob)))
        for reservation in reservations:
            blob = (
                session.get(CandidateDocumentBlob, reservation.content_hash)
                if reservation.content_hash is not None
                else None
            )
            if blob is not None:
                protected += 1
                continue
            if not storage.remove(reservation.temp_key):
                protected += 1
                continue
            if reservation.final_key is not None and not storage.remove(reservation.final_key):
                protected += 1
                continue
            usage.reserved_bytes -= reservation.reserved_bytes
            usage.version += 1
            session.delete(reservation)
            released += 1
        expected_keys = {blob.storage_key for blob in blobs}
        for reservation in all_reservations:
            # A reservation owns its generated staging key until the row is
            # committed as deleted.  Include every such key in reporting so a
            # failed deletion is protected rather than mislabeled external.
            expected_keys.add(reservation.temp_key)
            if reservation.final_key is not None:
                expected_keys.add(reservation.final_key)
        unexpected_files = len(storage.managed_file_keys() - expected_keys)
    return {
        "released_reservations": released,
        "protected_reservations": protected,
        "unexpected_files": unexpected_files,
    }
