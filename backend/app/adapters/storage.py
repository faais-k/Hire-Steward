import codecs
from collections.abc import AsyncIterable
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import secrets
from threading import BoundedSemaphore

from backend.app.domain.candidate_evidence import CandidateEvidenceError, storage_key_for_hash
from backend.app.evidence_config import EvidenceSettings


@dataclass(frozen=True)
class StagedContent:
    temp_key: str
    content_hash: str
    byte_size: int
    final_key: str


class EvidenceStorage:
    def __init__(self, settings: EvidenceSettings) -> None:
        self.settings = settings
        self._semaphore = BoundedSemaphore(settings.max_concurrent_uploads)

    def initialize(self) -> None:
        self.settings.storage_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(self.settings.storage_root, 0o700)

    def acquire_upload_slot(self) -> bool:
        return self._semaphore.acquire(blocking=False)

    def release_upload_slot(self) -> None:
        self._semaphore.release()

    def temp_key(self) -> str:
        return f"staging/{secrets.token_hex(24)}.tmp"

    def _path(self, key: str) -> Path:
        candidate = (self.settings.storage_root / key).resolve()
        try:
            candidate.relative_to(self.settings.storage_root)
        except ValueError as exc:
            raise CandidateEvidenceError("EVIDENCE_STORAGE_INTEGRITY_ERROR", 503) from exc
        return candidate

    async def stage_stream(self, temp_key: str, stream: AsyncIterable[bytes]) -> StagedContent:
        self.initialize()
        path = self._path(temp_key)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        digest = hashlib.sha256()
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        received = 0
        try:
            with path.open("xb") as target:
                if os.name != "nt":
                    os.chmod(path, 0o600)
                async for chunk in stream:
                    if not isinstance(chunk, bytes):
                        raise CandidateEvidenceError("INVALID_DOCUMENT_CONTENT", 422)
                    received += len(chunk)
                    if received > self.settings.max_version_bytes:
                        raise CandidateEvidenceError("DOCUMENT_TOO_LARGE", 413)
                    if b"\x00" in chunk:
                        raise CandidateEvidenceError("INVALID_DOCUMENT_CONTENT", 422)
                    try:
                        decoder.decode(chunk, final=False)
                    except UnicodeDecodeError as exc:
                        raise CandidateEvidenceError("INVALID_DOCUMENT_CONTENT", 422) from exc
                    digest.update(chunk)
                    target.write(chunk)
                try:
                    decoder.decode(b"", final=True)
                except UnicodeDecodeError as exc:
                    raise CandidateEvidenceError("INVALID_DOCUMENT_CONTENT", 422) from exc
                if received == 0:
                    raise CandidateEvidenceError("INVALID_DOCUMENT_CONTENT", 422)
        except Exception as exc:
            if not self.remove(temp_key):
                raise CandidateEvidenceError(
                    "EVIDENCE_STORAGE_PENDING_RECONCILIATION", 503
                ) from exc
            raise
        content_hash = digest.hexdigest()
        return StagedContent(
            temp_key=temp_key,
            content_hash=content_hash,
            byte_size=received,
            final_key=storage_key_for_hash(content_hash),
        )

    def remove(self, key: str) -> bool:
        try:
            self._path(key).unlink(missing_ok=True)
            return True
        except OSError:
            return False

    def place(self, staged: StagedContent) -> bool:
        source = self._path(staged.temp_key)
        destination = self._path(staged.final_key)
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Re-read the staged bytes immediately before the irreversible move.
        # The digest captured while streaming is not sufficient if a crash,
        # corruption, or local storage-root tampering happened afterward.
        self.verify(staged.temp_key, staged.content_hash, staged.byte_size)
        if destination.exists():
            self.verify(staged.final_key, staged.content_hash, staged.byte_size)
            if not self.remove(staged.temp_key):
                raise CandidateEvidenceError("EVIDENCE_STORAGE_PENDING_RECONCILIATION", 503)
            return False
        try:
            os.replace(source, destination)
        except FileNotFoundError as exc:
            raise CandidateEvidenceError("EVIDENCE_STORAGE_INTEGRITY_ERROR", 503) from exc
        if os.name != "nt":
            os.chmod(destination, 0o600)
        return True

    def verify(self, key: str, expected_hash: str, expected_size: int) -> None:
        path = self._path(key)
        digest = hashlib.sha256()
        total = 0
        try:
            with path.open("rb") as source:
                while chunk := source.read(64 * 1024):
                    total += len(chunk)
                    digest.update(chunk)
        except OSError as exc:
            raise CandidateEvidenceError("EVIDENCE_STORAGE_INTEGRITY_ERROR", 503) from exc
        if total != expected_size or digest.hexdigest() != expected_hash:
            raise CandidateEvidenceError("EVIDENCE_STORAGE_INTEGRITY_ERROR", 503)

    def read_span(self, key: str, start: int, end: int) -> bytes:
        if start < 0 or end <= start:
            raise CandidateEvidenceError("INVALID_PROVENANCE", 422)
        try:
            with self._path(key).open("rb") as source:
                source.seek(start)
                result = source.read(end - start)
        except OSError as exc:
            raise CandidateEvidenceError("EVIDENCE_STORAGE_INTEGRITY_ERROR", 503) from exc
        if len(result) != end - start:
            raise CandidateEvidenceError("INVALID_PROVENANCE", 422)
        return result

    def managed_file_keys(self) -> set[str]:
        """Return relative regular-file keys beneath root for operator reporting."""
        if not self.settings.storage_root.exists():
            return set()
        return {
            path.relative_to(self.settings.storage_root).as_posix()
            for path in self.settings.storage_root.rglob("*")
            if path.is_file()
        }
