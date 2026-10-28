import asyncio
from pathlib import Path
import tempfile

import pytest

from backend.app.evidence_config import EvidenceSettings
from backend.app.adapters.storage import EvidenceStorage
from backend.app.domain.candidate_evidence import CandidateEvidenceError
from backend.app.db.models import CandidateFactEvidence


def test_evidence_settings_rejects_repository_storage_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outside the repository"):
        EvidenceSettings(storage_root=Path.cwd() / "data")


def test_evidence_settings_rejects_relative_storage_root() -> None:
    with pytest.raises(ValueError, match="absolute"):
        EvidenceSettings(storage_root=Path("candidate-evidence"))


def test_evidence_settings_requires_positive_bounded_limits(tmp_path: Path) -> None:
    outside_root = Path(tempfile.gettempdir()) / "hire-steward-evidence-unit"
    with pytest.raises(ValueError, match="positive"):
        EvidenceSettings(storage_root=outside_root, max_version_bytes=0)
    with pytest.raises(ValueError, match="must not exceed"):
        EvidenceSettings(
            storage_root=outside_root,
            max_version_bytes=11,
            max_total_bytes=10,
        )


def test_candidate_evidence_revision_is_short_and_has_expected_parent() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config("backend/alembic.ini"))
    revision = script.get_revision("0003_candidate_evidence")
    assert revision is not None
    assert revision.revision == "0003_candidate_evidence"
    assert len(revision.revision) <= 32
    assert revision.down_revision == "0002_comp_evidence_trust"


def test_failed_storage_delete_is_reported_not_silently_ignored(monkeypatch, tmp_path: Path) -> None:
    storage = EvidenceStorage(
        EvidenceSettings(storage_root=Path(tempfile.gettempdir()) / "hire-steward-evidence-delete")
    )
    monkeypatch.setattr(storage, "_path", lambda _key: tmp_path / "owned.tmp")
    monkeypatch.setattr(Path, "unlink", lambda _self, missing_ok=True: (_ for _ in ()).throw(OSError()))
    assert storage.remove("staging/owned.tmp") is False


def test_placement_rechecks_staged_content_before_atomic_move(tmp_path: Path) -> None:
    """A post-staging mutation must not be committed under stale SHA-256 metadata."""
    storage = EvidenceStorage(EvidenceSettings(storage_root=tmp_path / "evidence"))

    async def chunks():
        yield b"original candidate evidence"

    staged = asyncio.run(storage.stage_stream(storage.temp_key(), chunks()))
    storage._path(staged.temp_key).write_bytes(b"tampered candidate evidence")

    with pytest.raises(CandidateEvidenceError) as error:
        storage.place(staged)

    assert error.value.code == "EVIDENCE_STORAGE_INTEGRITY_ERROR"
    assert not storage._path(staged.final_key).exists()


def test_provenance_model_declares_database_duplicate_span_constraint() -> None:
    unique_column_sets = {
        tuple(column.name for column in constraint.columns)
        for constraint in CandidateFactEvidence.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("fact_id", "document_version_id", "byte_start", "byte_end") in unique_column_sets
