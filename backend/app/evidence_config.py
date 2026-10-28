from dataclasses import dataclass
import os
from pathlib import Path


MEBIBYTE = 1024 * 1024
DEFAULT_MAX_VERSION_BYTES = 10 * MEBIBYTE
DEFAULT_MAX_TOTAL_BYTES = 100 * MEBIBYTE


@dataclass(frozen=True)
class EvidenceSettings:
    """Local-only candidate-evidence storage settings.

    The configured root must be outside this checkout. This is a process-local
    admission limit, not an operating-system disk quota.
    """

    storage_root: Path
    max_version_bytes: int = DEFAULT_MAX_VERSION_BYTES
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES
    max_concurrent_uploads: int = 2
    reconciliation_grace_seconds: int = 3600

    def __post_init__(self) -> None:
        if not self.storage_root.is_absolute():
            raise ValueError("evidence storage root must be absolute")
        root = self.storage_root.expanduser().resolve()
        repository_root = Path(__file__).resolve().parents[2]
        try:
            root.relative_to(repository_root)
        except ValueError:
            pass
        else:
            raise ValueError("evidence storage root must be outside the repository")
        if self.max_version_bytes <= 0 or self.max_total_bytes <= 0:
            raise ValueError("evidence storage limits must be positive")
        if self.max_version_bytes > self.max_total_bytes:
            raise ValueError("per-version limit must not exceed total storage limit")
        if self.max_concurrent_uploads < 1:
            raise ValueError("max concurrent uploads must be positive")
        if self.reconciliation_grace_seconds < 0:
            raise ValueError("reconciliation grace period must be non-negative")
        object.__setattr__(self, "storage_root", root)


def evidence_settings_from_environment() -> EvidenceSettings | None:
    raw_root = os.getenv("EVIDENCE_STORAGE_ROOT")
    if not raw_root:
        return None
    return EvidenceSettings(
        storage_root=Path(raw_root),
        max_version_bytes=int(os.getenv("EVIDENCE_MAX_VERSION_BYTES", DEFAULT_MAX_VERSION_BYTES)),
        max_total_bytes=int(os.getenv("EVIDENCE_MAX_TOTAL_BYTES", DEFAULT_MAX_TOTAL_BYTES)),
        max_concurrent_uploads=int(os.getenv("EVIDENCE_MAX_CONCURRENT_UPLOADS", "2")),
        reconciliation_grace_seconds=int(os.getenv("EVIDENCE_RECONCILIATION_GRACE_SECONDS", "3600")),
    )
