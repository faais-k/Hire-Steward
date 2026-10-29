import hashlib
import json
import re
import unicodedata
from enum import StrEnum


FILENAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,127}\Z")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
MAX_EVIDENCE_SPAN_BYTES = 4096


class CandidateEvidenceError(Exception):
    def __init__(self, code: str, status_code: int) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)


class DocumentState(StrEnum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class FactType(StrEnum):
    SKILL = "SKILL"
    EDUCATION = "EDUCATION"
    EMPLOYMENT = "EMPLOYMENT"
    PROJECT = "PROJECT"
    CERTIFICATION = "CERTIFICATION"


class FactVerificationState(StrEnum):
    UNREVIEWED = "UNREVIEWED"
    DOCUMENT_SUPPORTED = "DOCUMENT_SUPPORTED"
    USER_VERIFIED = "USER_VERIFIED"
    CONFLICTED = "CONFLICTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ReservationState(StrEnum):
    STAGING = "STAGING"
    READY_TO_PLACE = "READY_TO_PLACE"
    PLACED = "PLACED"


def sanitize_filename(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    if (
        not FILENAME_PATTERN.fullmatch(normalized)
        or normalized in {".", ".."}
        or "/" in normalized
        or "\\" in normalized
        or any(ord(char) < 32 or ord(char) == 127 for char in normalized)
    ):
        raise CandidateEvidenceError("INVALID_DOCUMENT_CONTENT", 422)
    return normalized


def canonical_json_and_hash(value: dict[str, object]) -> tuple[str, str]:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def storage_key_for_hash(content_hash: str) -> str:
    if not SHA256_PATTERN.fullmatch(content_hash):
        raise ValueError("content hash must be lowercase SHA-256")
    return f"sha256/{content_hash[:2]}/{content_hash}"
