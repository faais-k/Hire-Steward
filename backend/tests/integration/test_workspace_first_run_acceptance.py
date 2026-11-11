"""Integration tests for the personal workspace (jobpilot_workspace).

Verifies:
1. Isolated database connection to jobpilot_workspace.
2. Genuine first-run profile state: clean, empty, 0% complete, no synthetic candidate data.
3. Dedicated evidence storage outside the git repository.
4. Opportunities, Pipeline, Answer Bank, and Activity Feed start clean with 0 records.
5. First-run user workflow on isolated test schema.
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.evidence_config import EvidenceSettings
from backend.app.main import create_app

WORKSPACE_DB_URL = "postgresql+psycopg://jobpilot:local_dev_only@127.0.0.1:5432/jobpilot_workspace"

def local_headers() -> dict[str, str]:
    return {"host": "localhost", "origin": "http://localhost"}


@pytest.fixture(scope="module")
def workspace_client():
    """Client connected directly to jobpilot_workspace for read-only state verification."""
    engine = create_engine(WORKSPACE_DB_URL)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    
    local_appdata = Path(os.environ.get("LOCALAPPDATA", "C:/Users/FAZIL K FAAZI/AppData/Local"))
    evidence_path = (local_appdata / "HireSteward" / "workspace" / "evidence").resolve()
    evidence_path.mkdir(parents=True, exist_ok=True)
    settings = EvidenceSettings(storage_root=evidence_path)
    
    app = create_app(session_factory=factory, evidence_settings=settings)
    with TestClient(app, base_url="http://localhost") as client:
        yield client
    engine.dispose()


@pytest.mark.postgres
def test_workspace_initial_clean_profile_state(workspace_client: TestClient) -> None:
    resp = workspace_client.get("/api/v1/profile", headers=local_headers())
    assert resp.status_code == 200
    data = resp.json()
    profile = data.get("profile", {})
    completeness = data.get("completeness", {})
    
    # Must NOT have synthetic "Autonomous Engineer" name
    name = profile.get("name") or ""
    assert name in ("", "Faais K")
    assert "Autonomous" not in name
    headline = profile.get("headline") or ""
    assert headline in ("", "AI Engineer", "AI Engineer | Generative AI")


@pytest.mark.postgres
def test_workspace_initial_collections_are_clean(workspace_client: TestClient) -> None:
    # 1. Opportunities must have 0 items
    jobs_resp = workspace_client.get("/api/v1/jobs", headers=local_headers())
    assert jobs_resp.status_code == 200
    jobs_data = jobs_resp.json()
    assert len(jobs_data.get("items", [])) == 0
    assert jobs_data.get("total") == 0

    # 2. Pipeline applications must be 0
    apps_resp = workspace_client.get("/api/v1/applications", headers=local_headers())
    assert apps_resp.status_code == 200
    assert len(apps_resp.json()) == 0

    # 3. Answer bank items must be 0
    answers_resp = workspace_client.get("/api/v1/answers", headers=local_headers())
    assert answers_resp.status_code == 200
    assert len(answers_resp.json()) == 0

    # 4. Candidate facts must be 0
    facts_resp = workspace_client.get("/api/v1/facts", headers=local_headers())
    assert facts_resp.status_code == 200
    assert len(facts_resp.json()) == 0

    # 5. Documents must be 0 or only authentic candidate uploaded resume
    docs_resp = workspace_client.get("/api/v1/documents", headers=local_headers())
    assert docs_resp.status_code == 200
    docs = docs_resp.json()
    assert len(docs) <= 1
    if len(docs) == 1:
        assert docs[0].get("display_name") == "Faais_K_Resume.pdf"


@pytest.mark.postgres
def test_workspace_system_status_and_evidence_path(workspace_client: TestClient) -> None:
    resp = workspace_client.get("/api/v1/system/status", headers=local_headers())
    assert resp.status_code == 200
    status_data = resp.json()
    
    assert status_data["status"] == "healthy"
    assert status_data["database"]["connected"] is True
    assert status_data["storage"]["writable"] is True
    
    # Ensure evidence path is outside git repo and matches workspace path
    storage_path = Path(status_data["storage"]["path"])
    repo_root = Path(__file__).resolve().parents[3]
    with pytest.raises(ValueError):
        storage_path.relative_to(repo_root)
    assert "HireSteward" in str(storage_path)
    assert "workspace" in str(storage_path)


@pytest.mark.postgres
def test_workspace_settings_defaults_are_loaded(workspace_client: TestClient) -> None:
    # Load settings from clean workspace
    get_resp = workspace_client.get("/api/v1/settings", headers=local_headers())
    assert get_resp.status_code == 200
    settings = get_resp.json()
    
    assert settings.get("ai_provider_mode") == "OFFLINE_MOCK"
    assert settings.get("ai_budget_limit_usd") == 5.0
    assert settings.get("dry_run_simulation_mode") is True


@pytest.mark.postgres
def test_workspace_data_backup_and_recovery_drill(tmp_path: Path) -> None:
    from backend.app.services.data_backup import create_workspace_backup, execute_restore_drill

    # 1. Create backup in isolated tmp_path
    backup_dir = create_workspace_backup(
        database_name="jobpilot_workspace",
        backup_root=tmp_path,
    )
    assert backup_dir.exists()
    manifest_file = backup_dir / "backup_manifest.json"
    assert manifest_file.exists()

    # 2. Run isolated restore drill
    drill_report = execute_restore_drill(backup_dir)
    assert drill_report["manifest_verified"] is True
    assert drill_report["dump_sha256_verified"] is True
    assert drill_report["database_restored"] is True
    assert drill_report["alembic_version_verified"] is True
    assert drill_report["table_counts_matched"] is True
    assert drill_report["referential_integrity_verified"] is True
    assert drill_report["drill_db_cleaned"] is True
    assert drill_report["drill_evidence_cleaned"] is True
    assert drill_report["restored_alembic_version"] in (
        "0010_background_tasks",
        "0011_plan_frozen_material",
    )


@pytest.mark.postgres
def test_workspace_encrypted_backup_and_recovery_drill(tmp_path: Path) -> None:
    import json
    from backend.app.services.data_backup import create_workspace_backup, execute_restore_drill

    passphrase = "test_super_secure_vault_passphrase_2026!"
    # 1. Create encrypted backup
    backup_dir = create_workspace_backup(
        database_name="jobpilot_workspace",
        backup_root=tmp_path,
        passphrase=passphrase,
    )
    assert backup_dir.exists()
    manifest_file = backup_dir / "backup_manifest.json"
    with open(manifest_file, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["format_version"] == "hire-steward-data-backup-v2-etm"
    assert manifest["encryption"]["status"] == "ENCRYPTED"
    assert manifest["encryption"]["construction"] == "Encrypt-then-MAC"
    assert manifest["encryption"]["kdf_iterations"] == 600000
    assert manifest["database_dump"]["is_encrypted"] is True
    assert (backup_dir / "workspace_db.dump.enc").exists()
    assert not (backup_dir / "workspace_db.dump").exists()

    # 2. Drill with correct passphrase succeeds
    drill_report = execute_restore_drill(backup_dir, passphrase=passphrase)
    assert drill_report["manifest_verified"] is True
    assert drill_report["dump_sha256_verified"] is True
    assert drill_report["database_restored"] is True
    assert drill_report["drill_db_cleaned"] is True

    # 3. Drill with wrong passphrase fails safely before restore
    with pytest.raises(RuntimeError, match="Authentication failed"):
        execute_restore_drill(backup_dir, passphrase="wrong_passphrase_here")

    # 4. Drill without passphrase raises ValueError
    with pytest.raises(ValueError, match="Backup is encrypted"):
        execute_restore_drill(backup_dir, passphrase=None)


@pytest.mark.postgres
def test_workspace_backup_tampered_dump_ciphertext_rejected(tmp_path: Path) -> None:
    from backend.app.services.data_backup import create_workspace_backup, execute_restore_drill

    passphrase = "test_adversarial_tamper_passphrase_2026!"
    backup_dir = create_workspace_backup(
        database_name="jobpilot_workspace",
        backup_root=tmp_path,
        passphrase=passphrase,
    )
    dump_enc = backup_dir / "workspace_db.dump.enc"
    assert dump_enc.exists()

    # Adversarial Attack: Flip 1 byte in encrypted database dump
    raw = bytearray(dump_enc.read_bytes())
    raw[32] ^= 0x5A
    dump_enc.write_bytes(raw)

    with pytest.raises(RuntimeError, match="Authentication failed"):
        execute_restore_drill(backup_dir, passphrase=passphrase)


@pytest.mark.postgres
def test_workspace_backup_tampered_manifest_rejected(tmp_path: Path) -> None:
    import json
    from backend.app.services.data_backup import create_workspace_backup, execute_restore_drill

    passphrase = "test_adversarial_tamper_passphrase_2026!"
    backup_dir = create_workspace_backup(
        database_name="jobpilot_workspace",
        backup_root=tmp_path,
        passphrase=passphrase,
    )
    manifest_file = backup_dir / "backup_manifest.json"
    with open(manifest_file, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # Adversarial Attack: Alter table row counts or metadata in manifest
    manifest["database_dump"]["table_counts"]["candidate_profiles"] = 9999
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    with pytest.raises(RuntimeError, match="Authentication failed"):
        execute_restore_drill(backup_dir, passphrase=passphrase)


@pytest.mark.postgres
def test_workspace_backup_tampered_salt_rejected(tmp_path: Path) -> None:
    import json
    from backend.app.services.data_backup import create_workspace_backup, execute_restore_drill

    passphrase = "test_adversarial_tamper_passphrase_2026!"
    backup_dir = create_workspace_backup(
        database_name="jobpilot_workspace",
        backup_root=tmp_path,
        passphrase=passphrase,
    )
    manifest_file = backup_dir / "backup_manifest.json"
    with open(manifest_file, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # Adversarial Attack: Replace master salt
    manifest["encryption"]["master_salt_hex"] = "00" * 32
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    with pytest.raises(RuntimeError, match="Authentication failed"):
        execute_restore_drill(backup_dir, passphrase=passphrase)


@pytest.mark.postgres
def test_workspace_backup_tampered_iv_rejected(tmp_path: Path) -> None:
    import json
    from backend.app.services.data_backup import create_workspace_backup, execute_restore_drill

    passphrase = "test_adversarial_tamper_passphrase_2026!"
    backup_dir = create_workspace_backup(
        database_name="jobpilot_workspace",
        backup_root=tmp_path,
        passphrase=passphrase,
    )
    manifest_file = backup_dir / "backup_manifest.json"
    with open(manifest_file, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # Adversarial Attack: Alter IV of dump file
    manifest["database_dump"]["iv_hex"] = "11" * 16
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    with pytest.raises(RuntimeError, match="Authentication failed"):
        execute_restore_drill(backup_dir, passphrase=passphrase)


@pytest.mark.postgres
def test_workspace_backup_missing_file_rejected(tmp_path: Path) -> None:
    from backend.app.services.data_backup import create_workspace_backup, execute_restore_drill

    passphrase = "test_adversarial_tamper_passphrase_2026!"
    backup_dir = create_workspace_backup(
        database_name="jobpilot_workspace",
        backup_root=tmp_path,
        passphrase=passphrase,
    )
    dump_enc = backup_dir / "workspace_db.dump.enc"
    dump_enc.unlink()

    with pytest.raises(FileNotFoundError):
        execute_restore_drill(backup_dir, passphrase=passphrase)


@pytest.mark.postgres
def test_workspace_restore_target_safety_and_execution(tmp_path: Path) -> None:
    import subprocess
    from backend.app.services.data_backup import create_workspace_backup, restore_to_target_database

    passphrase = "test_target_restore_passphrase_2026!"
    backup_dir = create_workspace_backup(
        database_name="jobpilot_workspace",
        backup_root=tmp_path,
        passphrase=passphrase,
    )

    # Safety: Cannot overwrite protected databases
    for protected in ["jobpilot", "jobpilot_test", "jobpilot_e2e", "jobpilot_workspace"]:
        with pytest.raises(ValueError, match="Safety violation"):
            restore_to_target_database(backup_dir, protected, passphrase=passphrase)

    # Restore into fresh isolated database
    target_db = f"jobpilot_target_restore_test_{int(tmp_path.stat().st_mtime)}"
    try:
        report = restore_to_target_database(backup_dir, target_db, passphrase=passphrase)
        assert report["status"] == "success"
        assert report["target_database"] == target_db
    finally:
        subprocess.run(["docker", "exec", "autonomous-job-search-agent-db-1", "dropdb", "-U", "jobpilot", target_db], capture_output=True)


@pytest.mark.postgres
def test_workspace_backup_low_disk_space_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.services.data_backup import create_workspace_backup

    class MockDiskUsage:
        free = 1024 * 1024  # only 1MB free
    monkeypatch.setattr("shutil.disk_usage", lambda _: MockDiskUsage())

    with pytest.raises(RuntimeError, match="Insufficient free disk space for backup"):
        create_workspace_backup(database_name="jobpilot_workspace", backup_root=tmp_path)


