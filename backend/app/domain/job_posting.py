"""Domain models and contracts for normalized job postings and deduplication."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


EMPLOYER_HANDLE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}\Z")
POSTING_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
SOURCE_NAME_PATTERN = re.compile(r"^[a-z0-9_]{1,32}\Z")
SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}\Z")
MAX_POSTING_TITLE_LENGTH = 500
MAX_DESCRIPTION_LENGTH = 1_000_000


class JobDiscoveryError(Exception):
    """Base class for job discovery domain errors."""

    def __init__(self, message: str, code: str) -> None:
        self.message = message
        self.code = code
        super().__init__(f"[{code}] {message}")


class InvalidPostingPayloadError(JobDiscoveryError):
    """Raised when an incoming posting payload is malformed or invalid."""


class InvalidPaginationBoundsError(JobDiscoveryError):
    """Raised when pagination parameters or boundaries are invalid."""


class PaginationLoopError(JobDiscoveryError):
    """Raised when pagination encounters an infinite cycle or repeated page."""


class SourceNotApprovedError(JobDiscoveryError):
    """Raised when a job source is not approved (e.g. capability_status != 'VERIFIED_READ_ONLY')."""

    def __init__(self, message: str, code: str = "SOURCE_NOT_APPROVED") -> None:
        super().__init__(message, code)


class SourceGloballyDisabledError(JobDiscoveryError):
    """Raised when a job source is globally disabled."""

    def __init__(self, message: str, code: str = "SOURCE_GLOBALLY_DISABLED") -> None:
        super().__init__(message, code)


class SourceTermsReviewStaleError(JobDiscoveryError):
    """Raised when a job source's terms review timestamp is stale or missing."""

    def __init__(self, message: str, code: str = "SOURCE_TERMS_REVIEW_STALE") -> None:
        super().__init__(message, code)


class SubscriptionDisabledError(JobDiscoveryError):
    """Raised when an employer subscription is disabled."""

    def __init__(self, message: str, code: str = "SUBSCRIPTION_DISABLED") -> None:
        super().__init__(message, code)


class CircuitBreakerTrippedError(JobDiscoveryError):
    """Raised when an employer subscription or source circuit breaker is tripped."""

    def __init__(self, message: str, code: str = "CIRCUIT_BREAKER_TRIPPED") -> None:
        super().__init__(message, code)


class LeaseFencingError(JobDiscoveryError):
    """Raised when a lease token is invalid, expired, or superseded by another runner."""

    def __init__(self, message: str, code: str = "LEASE_FENCING_ERROR") -> None:
        super().__init__(message, code)


class ConcurrentLeaseError(JobDiscoveryError):
    """Raised when attempting to acquire a lease that is currently held by an active runner."""

    def __init__(self, message: str, code: str = "CONCURRENT_LEASE_ACTIVE") -> None:
        super().__init__(message, code)


class ClosedPostingReappearedError(JobDiscoveryError):
    """Raised when a posting previously marked closed or removed reappears in discovery."""

    def __init__(self, message: str, code: str = "CLOSED_POSTING_REAPPEARED") -> None:
        super().__init__(message, code)


class SnapshotIntegrityError(JobDiscoveryError):
    """Raised when snapshot immutability or payload hash validation fails."""

    def __init__(self, message: str, code: str = "SNAPSHOT_INTEGRITY_ERROR") -> None:
        super().__init__(message, code)


class PostingLifecycleStatus(StrEnum):
    """Lifecycle status of a canonical job posting."""

    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    CLOSED_CONFIRMED = "CLOSED_CONFIRMED"


class SourceCapabilityStatus(StrEnum):
    """Capability and approval status of a job source."""

    NEEDS_REVIEW = "NEEDS_REVIEW"
    VERIFIED_READ_ONLY = "VERIFIED_READ_ONLY"
    MANUAL_ONLY = "MANUAL_ONLY"
    BLOCKED = "BLOCKED"
    DISABLED_BY_USER = "DISABLED_BY_USER"


class DiscoveryRunStatus(StrEnum):
    """Status of a discovery run execution."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    SKIPPED_CONCURRENT_LEASE = "SKIPPED_CONCURRENT_LEASE"


class PublicationDateStatus(StrEnum):
    """Status of the publication timestamp on a job posting."""

    EXACT = "EXACT"
    UNKNOWN = "UNKNOWN"
    INVALID = "INVALID"


def validate_safe_https_url(url: object, field_name: str) -> str | None:
    """Validate that a URL is a secure, well-formed HTTPS URL."""
    if url is None:
        return None
    if not isinstance(url, str):
        raise InvalidPostingPayloadError(
            f"{field_name} must be a string", "INVALID_URL_TYPE"
        )
    stripped = url.strip()
    if not stripped:
        return None

    if any(ord(c) <= 32 or ord(c) == 127 for c in stripped):
        raise InvalidPostingPayloadError(
            f"{field_name} must not contain whitespace or control characters",
            "INVALID_URL_CHARACTERS",
        )
    if any(c in {"<", ">", '"', "'"} for c in stripped):
        raise InvalidPostingPayloadError(
            f"{field_name} contains invalid characters", "INVALID_URL_CHARACTERS"
        )

    try:
        parts = urlsplit(stripped)
    except ValueError as exc:
        raise InvalidPostingPayloadError(
            f"{field_name} is malformed", "MALFORMED_URL"
        ) from exc

    if parts.scheme != "https":
        raise InvalidPostingPayloadError(
            f"{field_name} must use the https scheme, got '{parts.scheme}'",
            "INSECURE_URL_SCHEME",
        )
    if not parts.netloc or not parts.hostname:
        raise InvalidPostingPayloadError(
            f"{field_name} must have a valid hostname", "MISSING_HOSTNAME"
        )
    if parts.username or parts.password:
        raise InvalidPostingPayloadError(
            f"{field_name} must not contain user credentials", "CREDENTIALS_IN_URL"
        )

    return stripped


class PostingListSection(BaseModel):
    """A structured list section within a job posting (e.g. Requirements, Responsibilities)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str
    items: list[str] = Field(default_factory=list)


class NormalizedPosting(BaseModel):
    """Canonical normalized representation of a job posting discovered from a source.

    Guarantees:
    - Compensation is never inferred from missing data.
    - Sponsorship, seniority, and publication dates are never inferred.
    - Preserves source identifiers and source payload provenance.
    - All string fields are normalized and bounded.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    employer_handle: str
    posting_id: str
    title: str

    published_at: datetime | None = None
    publication_date_status: PublicationDateStatus = PublicationDateStatus.UNKNOWN
    raw_created_at_ms: int | None = None

    location: str | None = None
    commitment: str | None = None
    team: str | None = None
    department: str | None = None
    level: str | None = None
    workplace_type: str | None = None

    description_plain: str
    description_html: str | None = None  # Raw source HTML, explicitly UNTRUSTED. Must never be rendered directly in a browser without strict frontend sanitization.
    lists: list[PostingListSection] = Field(default_factory=list)
    additional_plain: str | None = None

    canonical_url: str | None = None
    apply_url: str | None = None

    source_raw_hash: str

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        if not isinstance(value, str):
            raise InvalidPostingPayloadError(
                "Source name must be a string", "INVALID_SOURCE_NAME_TYPE"
            )
        stripped = value.strip()
        if not SOURCE_NAME_PATTERN.fullmatch(stripped):
            raise InvalidPostingPayloadError(
                f"Invalid source name: '{value}'", "INVALID_SOURCE_NAME"
            )
        return stripped

    @field_validator("employer_handle")
    @classmethod
    def validate_handle(cls, value: str) -> str:
        if not isinstance(value, str) or not EMPLOYER_HANDLE_PATTERN.fullmatch(value) or value in {".", ".."}:
            raise InvalidPostingPayloadError(
                f"Invalid employer handle: '{value}'", "INVALID_EMPLOYER_HANDLE"
            )
        return value

    @field_validator("posting_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not isinstance(value, str):
            raise InvalidPostingPayloadError(
                "Posting id must be a string", "INVALID_POSTING_ID_TYPE"
            )
        stripped = value.strip()
        if not POSTING_ID_PATTERN.fullmatch(stripped):
            raise InvalidPostingPayloadError(
                f"Invalid posting id: '{value}'", "INVALID_POSTING_ID"
            )
        return stripped

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        if not isinstance(value, str):
            raise InvalidPostingPayloadError(
                "Posting title must be a string", "INVALID_JOB_TITLE_TYPE"
            )
        stripped = value.strip()
        if not stripped:
            raise InvalidPostingPayloadError(
                "Posting title cannot be empty", "EMPTY_JOB_TITLE"
            )
        if len(stripped) > MAX_POSTING_TITLE_LENGTH:
            raise InvalidPostingPayloadError(
                f"Posting title exceeds {MAX_POSTING_TITLE_LENGTH} characters",
                "JOB_TITLE_TOO_LONG",
            )
        return stripped

    @field_validator("source_raw_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if not isinstance(value, str) or not SHA256_HEX_PATTERN.fullmatch(value):
            raise InvalidPostingPayloadError(
                "Source raw hash must be a 64-character lowercase hexadecimal SHA-256 string",
                "INVALID_RAW_HASH",
            )
        return value

    @field_validator("canonical_url", mode="before")
    @classmethod
    def validate_canonical_url(cls, value: object) -> str | None:
        return validate_safe_https_url(value, "canonical_url")

    @field_validator("apply_url", mode="before")
    @classmethod
    def validate_apply_url(cls, value: object) -> str | None:
        return validate_safe_https_url(value, "apply_url")


PostingKey = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class PostingConflict:
    """Records conflicting data observed for the same posting identifier."""

    key: PostingKey
    existing: NormalizedPosting
    incoming: NormalizedPosting
    reason: str


@dataclass(frozen=True, slots=True)
class DeduplicationResult:
    """Result of deduplicating a sequence of postings."""

    unique_postings: list[NormalizedPosting]
    duplicates_count: int
    conflicts: list[PostingConflict]


def deduplicate_postings(postings: Sequence[NormalizedPosting]) -> DeduplicationResult:
    """Deduplicate postings by (source, employer_handle, posting_id).

    Preserves the first valid observation. If an incoming posting with the same
    key has a different payload hash or conflicting content, the conflict is
    recorded rather than silently discarded or overwritten.
    """
    seen: dict[PostingKey, NormalizedPosting] = {}
    unique_list: list[NormalizedPosting] = []
    conflicts: list[PostingConflict] = []
    duplicates_count = 0

    for posting in postings:
        key: PostingKey = (posting.source, posting.employer_handle, posting.posting_id)
        if key not in seen:
            seen[key] = posting
            unique_list.append(posting)
        else:
            existing = seen[key]
            if existing.source_raw_hash == posting.source_raw_hash:
                duplicates_count += 1
            else:
                conflicts.append(
                    PostingConflict(
                        key=key,
                        existing=existing,
                        incoming=posting,
                        reason="PAYLOAD_CONTENT_MISMATCH",
                    )
                )

    return DeduplicationResult(
        unique_postings=unique_list,
        duplicates_count=duplicates_count,
        conflicts=conflicts,
    )
