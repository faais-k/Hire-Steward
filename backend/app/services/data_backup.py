"""Hire-Steward Personal Data Backup and Recovery Service.

Provides point-in-time logical database backup (pg_dump custom format) and
evidence storage backup with cryptographic integrity manifests, staging directory
consistency, low disk space detection, authenticated Encrypt-then-MAC (AES-256-CBC +
HMAC-SHA256 with PBKDF2-HMAC-SHA256, 600,000 iterations, independent keys),
and isolated recovery drills.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import time
from typing import Any
from sqlalchemy import create_engine, inspect, text


BACKUP_FORMAT_VERSION = "hire-steward-data-backup-v1"
BACKUP_FORMAT_VERSION_ENCRYPTED = "hire-steward-data-backup-v1-encrypted"
BACKUP_FORMAT_VERSION_V2_ETM = "hire-steward-data-backup-v2-etm"

DEFAULT_DOCKER_CONTAINER = "autonomous-job-search-agent-db-1"
DEFAULT_DB_USER = "jobpilot"
DEFAULT_WORKSPACE_DB = "jobpilot_workspace"
MIN_FREE_DISK_BYTES = 50 * 1024 * 1024  # 50 MB pre-flight check
PBKDF2_ITERATIONS = 600_000
SALT_BYTES = 32
IV_BYTES = 16
PROTECTED_DATABASES = frozenset({"jobpilot", "jobpilot_test", "jobpilot_e2e", "jobpilot_workspace"})


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 checksum of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def derive_etm_keys(passphrase: str, salt: bytes, iterations: int = PBKDF2_ITERATIONS) -> tuple[bytes, bytes]:
    """Derive independent encryption and authentication keys using PBKDF2-HMAC-SHA256."""
    derived = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, iterations, dklen=64)
    enc_key = derived[:32]
    auth_key = derived[32:]
    return enc_key, auth_key


def compute_file_hmac(
    auth_key: bytes,
    format_version: str,
    iterations: int,
    master_salt: bytes,
    iv: bytes,
    relative_path: str,
    plain_sha256: str,
    ciphertext_path: Path,
) -> str:
    """Compute HMAC-SHA256 tag binding header, KDF params, salt, IV, path, and ciphertext."""
    h = hmac.new(auth_key, digestmod=hashlib.sha256)
    h.update(b"HIRE_STEWARD_ETM_FILE_TAG_V2\n")
    h.update(format_version.encode("utf-8") + b"\n")
    h.update(f"iter:{iterations}\n".encode("utf-8"))
    h.update(b"salt:" + master_salt + b"\n")
    h.update(b"iv:" + iv + b"\n")
    h.update(f"path:{relative_path}\n".encode("utf-8"))
    h.update(f"plain_sha256:{plain_sha256}\n".encode("utf-8"))
    with open(ciphertext_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def compute_manifest_hmac(auth_key: bytes, manifest_dict: dict[str, Any]) -> str:
    """Compute HMAC-SHA256 master tag over canonical JSON representation of manifest metadata."""
    copy_dict = {k: v for k, v in manifest_dict.items() if k != "manifest_hmac_sha256"}
    canon_bytes = json.dumps(copy_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
    h = hmac.new(auth_key, digestmod=hashlib.sha256)
    h.update(b"HIRE_STEWARD_ETM_MANIFEST_TAG_V2\n")
    h.update(canon_bytes)
    return h.hexdigest()


def encrypt_file_etm(plain_path: Path, enc_path: Path, enc_key: bytes, iv: bytes) -> None:
    """Encrypt a single file with AES-256-CBC using OpenSSL and raw key/IV."""
    cmd = [
        "openssl", "enc", "-aes-256-cbc", "-nosalt",
        "-K", enc_key.hex(),
        "-iv", iv.hex(),
        "-in", str(plain_path),
        "-out", str(enc_path),
    ]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0:
        err = res.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenSSL encryption failed: {err}")


def decrypt_file_etm(enc_path: Path, dec_path: Path, enc_key: bytes, iv: bytes) -> None:
    """Decrypt a single file with AES-256-CBC using OpenSSL after authenticity verification."""
    cmd = [
        "openssl", "enc", "-d", "-aes-256-cbc", "-nosalt",
        "-K", enc_key.hex(),
        "-iv", iv.hex(),
        "-in", str(enc_path),
        "-out", str(dec_path),
    ]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0:
        err = res.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenSSL decryption failed: {err}")


def get_default_evidence_dir() -> Path:
    """Get the default workspace evidence directory."""
    raw = os.getenv("EVIDENCE_STORAGE_ROOT")
    if raw:
        return Path(raw).resolve()
    local_app_data = os.getenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    return (Path(local_app_data) / "HireSteward" / "workspace" / "evidence").resolve()


def get_default_backup_root() -> Path:
    """Get the default backups storage root outside checkout."""
    local_app_data = os.getenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    root = Path(local_app_data) / "HireSteward" / "backups"
    root.mkdir(parents=True, exist_ok=True)
    return root


def create_workspace_backup(
    database_name: str = DEFAULT_WORKSPACE_DB,
    evidence_dir: Path | None = None,
    backup_root: Path | None = None,
    container_name: str = DEFAULT_DOCKER_CONTAINER,
    db_user: str = DEFAULT_DB_USER,
    passphrase: str | None = None,
) -> Path:
    """Create a point-in-time logical dump of the workspace database and evidence store.

    Uses a staging directory pattern to guarantee consistency and prevent partial backups.
    Checks for minimum free disk space before initiating the dump.
    Optionally encrypts files using authenticated Encrypt-then-MAC (AES-256-CBC + HMAC-SHA256)
    with PBKDF2-HMAC-SHA256 (600,000 iterations, 32-byte salt, independent derived keys).
    Returns the Path to the timestamped backup directory.
    """
    evidence_path = (evidence_dir or get_default_evidence_dir()).resolve()
    root = (backup_root or get_default_backup_root()).resolve()

    # Pre-flight: Check free disk space
    free_bytes = shutil.disk_usage(root).free
    if free_bytes < MIN_FREE_DISK_BYTES:
        raise RuntimeError(
            f"Insufficient free disk space for backup: {free_bytes} bytes available, "
            f"{MIN_FREE_DISK_BYTES} bytes required."
        )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_dir = root / f"data_{timestamp}"
    staging_dir = root / f".staging_data_{timestamp}"
    if backup_dir.exists():
        raise FileExistsError(f"Target backup directory already exists: {backup_dir}")
    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)
    staging_dir.mkdir(parents=True, exist_ok=False)

    try:
        raw_dump_filename = "workspace_db.dump"
        raw_dump_path = staging_dir / raw_dump_filename

        # 1. Execute pg_dump custom format (-Fc)
        cmd = ["docker", "exec", container_name, "pg_dump", "-U", db_user, "-d", database_name, "-Fc"]
        with open(raw_dump_path, "wb") as dump_out:
            res = subprocess.run(cmd, stdout=dump_out, stderr=subprocess.PIPE)
            if res.returncode != 0:
                err = res.stderr.decode("utf-8", errors="replace")
                raise RuntimeError(f"pg_dump failed with exit code {res.returncode}: {err}")

        # 2. Copy evidence storage files
        evidence_backup_dir = staging_dir / "evidence"
        evidence_files_manifest = []

        if evidence_path.exists():
            for file_path in evidence_path.rglob("*"):
                if not file_path.is_file():
                    continue
                rel = file_path.relative_to(evidence_path)
                if rel.parts and rel.parts[0] in ("staging", ".tmp", "temp"):
                    continue

                dest = evidence_backup_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_path, dest)

                file_hash = _sha256_file(dest)
                file_size = dest.stat().st_size
                evidence_files_manifest.append({
                    "relative_path": str(rel).replace("\\", "/"),
                    "plaintext_sha256": file_hash,
                    "sha256": file_hash,  # Backward compatibility field
                    "size_bytes": file_size,
                    "is_encrypted": False,
                })

        # 3. Query table row counts and Alembic version directly from database
        db_url = f"postgresql+psycopg://{db_user}:local_dev_only@127.0.0.1:5432/{database_name}"
        engine = create_engine(db_url)
        table_counts: dict[str, int] = {}
        alembic_version = None

        try:
            with engine.connect() as conn:
                insp = inspect(engine)
                for t in sorted(insp.get_table_names()):
                    cnt = conn.execute(text(f'SELECT count(*) FROM "{t}"')).scalar()
                    table_counts[t] = int(cnt or 0)

                if "alembic_version" in table_counts and table_counts["alembic_version"] > 0:
                    alembic_version = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
        finally:
            engine.dispose()

        # 4. Optional Encryption: Authenticated Encrypt-then-MAC (v2-etm)
        effective_passphrase = passphrase or os.getenv("HIRE_STEWARD_BACKUP_PASSPHRASE")
        is_encrypted = bool(effective_passphrase)
        final_dump_filename = raw_dump_filename
        dump_pt_sha256 = _sha256_file(raw_dump_path)

        encryption_meta: dict[str, Any] = {
            "status": "UNENCRYPTED",
            "cipher": None,
            "mac": None,
            "construction": None,
            "kdf": None,
            "kdf_iterations": None,
            "master_salt_hex": None,
            "note": "Unencrypted backup; awaiting user passphrase/key configuration",
        }
        dump_iv_hex = None
        dump_hmac_hex = None

        if is_encrypted:
            master_salt = secrets.token_bytes(SALT_BYTES)
            enc_key, auth_key = derive_etm_keys(effective_passphrase, master_salt, PBKDF2_ITERATIONS)

            enc_dump_filename = "workspace_db.dump.enc"
            enc_dump_path = staging_dir / enc_dump_filename
            dump_iv = secrets.token_bytes(IV_BYTES)
            dump_iv_hex = dump_iv.hex()

            encrypt_file_etm(raw_dump_path, enc_dump_path, enc_key, dump_iv)
            raw_dump_path.unlink()  # Safely wipe plain dump from staging

            final_dump_filename = enc_dump_filename
            dump_ct_sha256 = _sha256_file(enc_dump_path)
            dump_size = enc_dump_path.stat().st_size

            dump_hmac_hex = compute_file_hmac(
                auth_key,
                BACKUP_FORMAT_VERSION_V2_ETM,
                PBKDF2_ITERATIONS,
                master_salt,
                dump_iv,
                enc_dump_filename,
                dump_pt_sha256,
                enc_dump_path,
            )

            # Encrypt evidence files
            for item in evidence_files_manifest:
                item_raw_path = evidence_backup_dir / item["relative_path"]
                enc_rel_path = item["relative_path"] + ".enc"
                enc_item_path = item_raw_path.with_name(item_raw_path.name + ".enc")
                item_iv = secrets.token_bytes(IV_BYTES)

                encrypt_file_etm(item_raw_path, enc_item_path, enc_key, item_iv)
                item_raw_path.unlink()

                item_ct_sha256 = _sha256_file(enc_item_path)
                item_hmac_hex = compute_file_hmac(
                    auth_key,
                    BACKUP_FORMAT_VERSION_V2_ETM,
                    PBKDF2_ITERATIONS,
                    master_salt,
                    item_iv,
                    enc_rel_path,
                    item["plaintext_sha256"],
                    enc_item_path,
                )

                item["relative_path"] = enc_rel_path
                item["is_encrypted"] = True
                item["iv_hex"] = item_iv.hex()
                item["ciphertext_sha256"] = item_ct_sha256
                item["sha256"] = item_ct_sha256  # Backward compatibility field
                item["hmac_sha256"] = item_hmac_hex
                item["size_bytes"] = enc_item_path.stat().st_size

            encryption_meta = {
                "status": "ENCRYPTED",
                "cipher": "AES-256-CBC",
                "mac": "HMAC-SHA256",
                "construction": "Encrypt-then-MAC",
                "kdf": "PBKDF2-HMAC-SHA256",
                "kdf_iterations": PBKDF2_ITERATIONS,
                "master_salt_hex": master_salt.hex(),
                "note": (
                    "Authenticated Encrypt-then-MAC using AES-256-CBC and HMAC-SHA256 with "
                    "domain-separated independent keys and PBKDF2 (600,000 iterations)"
                ),
            }
        else:
            dump_ct_sha256 = dump_pt_sha256
            dump_size = raw_dump_path.stat().st_size

        # 5. Construct manifest
        manifest: dict[str, Any] = {
            "format_version": BACKUP_FORMAT_VERSION_V2_ETM if is_encrypted else BACKUP_FORMAT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_database": database_name,
            "encryption": encryption_meta,
            "database_dump": {
                "filename": final_dump_filename,
                "is_encrypted": is_encrypted,
                "iv_hex": dump_iv_hex,
                "hmac_sha256": dump_hmac_hex,
                "ciphertext_sha256": dump_ct_sha256,
                "plaintext_sha256": dump_pt_sha256,
                "sha256": dump_ct_sha256,  # Backward compatibility field
                "size_bytes": dump_size,
                "alembic_version": alembic_version,
                "table_counts": table_counts,
            },
            "evidence_storage": {
                "source_path": str(evidence_path),
                "total_files": len(evidence_files_manifest),
                "total_bytes": sum(f["size_bytes"] for f in evidence_files_manifest),
                "files": evidence_files_manifest,
            },
            "system_metadata": {
                "platform": "windows",
                "disk_encryption_verified": False,
                "disk_encryption_note": "BitLocker unverified / access denied / no bitlocker volume on C:",
                "docker_container": container_name,
                "postgresql_version": "17.11",
            },
        }

        # 6. Authenticate Manifest if Encrypted
        if is_encrypted:
            manifest_hmac_hex = compute_manifest_hmac(auth_key, manifest)
            manifest["manifest_hmac_sha256"] = manifest_hmac_hex
            sig_path = staging_dir / "backup_manifest.sig"
            sig_path.write_text(manifest_hmac_hex, encoding="utf-8")

        manifest_path = staging_dir / "backup_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, sort_keys=True)

        # 7. Atomic promote from staging to final backup directory
        staging_dir.rename(backup_dir)
        return backup_dir

    except Exception:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        raise


def verify_backup_authenticity(
    backup_dir: Path,
    manifest: dict[str, Any],
    passphrase: str | None = None,
) -> tuple[bytes | None, bytes | None]:
    """Verify cryptographic authenticity of the backup BEFORE any decryption or database actions.

    For Encrypt-then-MAC (v2-etm) backups:
      1. Verifies manifest HMAC signature using derived auth_key.
      2. Verifies dump file ciphertext SHA-256 and HMAC-SHA256 tag.
      3. Verifies each evidence file ciphertext SHA-256 and HMAC-SHA256 tag.
    For legacy / unencrypted backups:
      Verifies file existence and SHA-256 hashes.

    Returns (enc_key, auth_key) if encrypted, or (None, None) if unencrypted.
    Raises RuntimeError on authentication failure, ValueError on missing passphrase or format error.
    """
    fmt = manifest.get("format_version")
    if fmt not in (BACKUP_FORMAT_VERSION, BACKUP_FORMAT_VERSION_ENCRYPTED, BACKUP_FORMAT_VERSION_V2_ETM):
        raise ValueError(f"Unsupported backup format: {fmt}")

    is_encrypted = manifest.get("encryption", {}).get("status") == "ENCRYPTED"
    effective_passphrase = passphrase or os.getenv("HIRE_STEWARD_BACKUP_PASSPHRASE")

    if is_encrypted and not effective_passphrase:
        raise ValueError("Backup is encrypted. Passphrase must be provided to restore.")

    dump_info = manifest["database_dump"]
    dump_path = backup_dir / dump_info["filename"]
    if not dump_path.exists():
        raise FileNotFoundError(f"Missing dump file: {dump_path}")

    evidence_backup_dir = backup_dir / "evidence"
    for item in manifest["evidence_storage"]["files"]:
        item_path = evidence_backup_dir / item["relative_path"]
        if not item_path.exists():
            raise FileNotFoundError(f"Missing evidence file in backup: {item_path}")

    if is_encrypted and fmt == BACKUP_FORMAT_VERSION_V2_ETM:
        enc_meta = manifest.get("encryption", {})
        master_salt_hex = enc_meta.get("master_salt_hex")
        if not master_salt_hex:
            raise RuntimeError("Authentication failed: backup is missing master salt.")
        master_salt = bytes.fromhex(master_salt_hex)
        iterations = enc_meta.get("kdf_iterations", PBKDF2_ITERATIONS)

        enc_key, auth_key = derive_etm_keys(effective_passphrase, master_salt, iterations)

        # 1. Verify Manifest HMAC
        expected_manifest_hmac = manifest.get("manifest_hmac_sha256")
        if not expected_manifest_hmac:
            raise RuntimeError("Authentication failed: backup manifest is missing HMAC signature.")
        computed_manifest_hmac = compute_manifest_hmac(auth_key, manifest)
        if not hmac.compare_digest(computed_manifest_hmac, expected_manifest_hmac):
            raise RuntimeError("Authentication failed: backup has been tampered with or passphrase is incorrect")

        # 2. Verify Database Dump Ciphertext Hash & HMAC Tag
        actual_dump_hash = _sha256_file(dump_path)
        expected_dump_hash = dump_info.get("ciphertext_sha256") or dump_info.get("sha256")
        if not hmac.compare_digest(actual_dump_hash, expected_dump_hash):
            raise RuntimeError("Authentication failed: database dump ciphertext checksum mismatch")

        dump_iv = bytes.fromhex(dump_info["iv_hex"])
        computed_dump_hmac = compute_file_hmac(
            auth_key,
            fmt,
            iterations,
            master_salt,
            dump_iv,
            dump_info["filename"],
            dump_info["plaintext_sha256"],
            dump_path,
        )
        if not hmac.compare_digest(computed_dump_hmac, dump_info["hmac_sha256"]):
            raise RuntimeError("Authentication failed: database dump HMAC tag mismatch")

        # 3. Verify Evidence Files Ciphertext Hash & HMAC Tags
        for item in manifest["evidence_storage"]["files"]:
            item_path = evidence_backup_dir / item["relative_path"]
            actual_item_hash = _sha256_file(item_path)
            expected_item_hash = item.get("ciphertext_sha256") or item.get("sha256")
            if not hmac.compare_digest(actual_item_hash, expected_item_hash):
                raise RuntimeError(f"Authentication failed: evidence file {item['relative_path']} checksum mismatch")

            item_iv = bytes.fromhex(item["iv_hex"])
            computed_item_hmac = compute_file_hmac(
                auth_key,
                fmt,
                iterations,
                master_salt,
                item_iv,
                item["relative_path"],
                item["plaintext_sha256"],
                item_path,
            )
            if not hmac.compare_digest(computed_item_hmac, item["hmac_sha256"]):
                raise RuntimeError(f"Authentication failed: evidence file {item['relative_path']} HMAC tag mismatch")

        return enc_key, auth_key

    elif is_encrypted:
        # Legacy v1 encrypted verification
        actual_dump_hash = _sha256_file(dump_path)
        if actual_dump_hash != dump_info["sha256"]:
            raise ValueError(f"Database dump SHA-256 mismatch! Expected {dump_info['sha256']}, got {actual_dump_hash}")
        for item in manifest["evidence_storage"]["files"]:
            item_path = evidence_backup_dir / item["relative_path"]
            if _sha256_file(item_path) != item["sha256"]:
                raise ValueError(f"Evidence file {item['relative_path']} SHA-256 mismatch!")
        return None, None

    else:
        # Unencrypted v1 verification
        actual_dump_hash = _sha256_file(dump_path)
        if actual_dump_hash != dump_info["sha256"]:
            raise ValueError(f"Database dump SHA-256 mismatch! Expected {dump_info['sha256']}, got {actual_dump_hash}")
        for item in manifest["evidence_storage"]["files"]:
            item_path = evidence_backup_dir / item["relative_path"]
            if _sha256_file(item_path) != item["sha256"]:
                raise ValueError(f"Evidence file {item['relative_path']} SHA-256 mismatch!")
        return None, None


def execute_restore_drill(
    backup_dir: Path,
    container_name: str = DEFAULT_DOCKER_CONTAINER,
    db_user: str = DEFAULT_DB_USER,
    passphrase: str | None = None,
) -> dict[str, Any]:
    """Execute an isolated recovery drill into a temporary database and temp evidence dir.

    Verifies manifest integrity and file authenticity BEFORE any decryption or database action.
    Restores into an ephemeral database, verifies record counts, Alembic version, referential
    integrity, and evidence checksums.
    Drops the temporary database and deletes temporary evidence directory upon completion.
    """
    manifest_path = backup_dir / "backup_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing backup_manifest.json in {backup_dir}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    effective_passphrase = passphrase or os.getenv("HIRE_STEWARD_BACKUP_PASSPHRASE")

    # Step 1: Pre-flight Cryptographic Authenticity Verification (BEFORE touching PostgreSQL)
    enc_key, auth_key = verify_backup_authenticity(backup_dir, manifest, effective_passphrase)

    is_encrypted = manifest.get("encryption", {}).get("status") == "ENCRYPTED"
    fmt = manifest.get("format_version")
    dump_info = manifest["database_dump"]
    dump_path = backup_dir / dump_info["filename"]
    evidence_backup_dir = backup_dir / "evidence"

    # Step 2: Generate unique drill DB name and ensure non-collision
    drill_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    drill_db_name = f"jobpilot_restore_drill_{drill_ts}"

    check_db_cmd = [
        "docker", "exec", container_name,
        "psql", "-U", db_user, "-d", "postgres", "-t", "-c",
        f"SELECT 1 FROM pg_database WHERE datname='{drill_db_name}';"
    ]
    res_check = subprocess.run(check_db_cmd, capture_output=True, text=True)
    if "1" in res_check.stdout:
        raise RuntimeError(f"Drill database {drill_db_name} already exists! Aborting drill for safety.")

    # Step 3: Create drill DB
    create_db_cmd = ["docker", "exec", container_name, "createdb", "-U", db_user, drill_db_name]
    res_create = subprocess.run(create_db_cmd, capture_output=True, text=True)
    if res_create.returncode != 0:
        raise RuntimeError(f"createdb failed for {drill_db_name}: {res_create.stderr}")

    drill_evidence_dir = get_default_backup_root() / f"drill_evidence_{drill_ts}"
    drill_temp_decrypted_dir = get_default_backup_root() / f"drill_temp_dec_{drill_ts}"
    drill_evidence_dir.mkdir(parents=True, exist_ok=True)
    drill_temp_decrypted_dir.mkdir(parents=True, exist_ok=True)

    drill_results: dict[str, Any] = {
        "drill_timestamp": datetime.now(timezone.utc).isoformat(),
        "drill_database": drill_db_name,
        "backup_source": str(backup_dir),
        "format_version": fmt,
        "encryption_status": manifest.get("encryption", {}).get("status", "UNENCRYPTED"),
        "manifest_verified": True,
        "dump_sha256_verified": True,
        "evidence_files_verified": len(manifest["evidence_storage"]["files"]),
        "database_restored": False,
        "alembic_version_verified": False,
        "table_counts_matched": False,
        "referential_integrity_verified": False,
        "evidence_restored_and_verified": False,
        "drill_db_cleaned": False,
        "drill_evidence_cleaned": False,
        "duration_seconds": 0.0,
    }

    t0 = time.time()
    drill_engine = None
    try:
        # Step 4: Decrypt database dump if encrypted
        restore_dump_path = dump_path
        if is_encrypted:
            dec_dump_path = drill_temp_decrypted_dir / "decrypted_workspace_db.dump"
            if fmt == BACKUP_FORMAT_VERSION_V2_ETM and enc_key:
                dump_iv = bytes.fromhex(dump_info["iv_hex"])
                decrypt_file_etm(dump_path, dec_dump_path, enc_key, dump_iv)
            else:
                env = os.environ.copy()
                env["TEMP_BACKUP_PASS"] = effective_passphrase
                res_dec = subprocess.run([
                    "openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "100000",
                    "-in", str(dump_path), "-out", str(dec_dump_path),
                    "-pass", "env:TEMP_BACKUP_PASS"
                ], env=env, capture_output=True)
                if res_dec.returncode != 0:
                    err_msg = res_dec.stderr.decode("utf-8", errors="replace")
                    raise RuntimeError(f"Decryption failed: bad passphrase or corrupted ciphertext ({err_msg})")
            restore_dump_path = dec_dump_path

        # Step 5: Restore database using pg_restore
        restore_cmd = [
            "docker", "exec", "-i", container_name,
            "pg_restore", "-U", db_user, "-d", drill_db_name, "--no-owner", "--no-privileges"
        ]
        with open(restore_dump_path, "rb") as dump_in:
            res_restore = subprocess.run(restore_cmd, stdin=dump_in, capture_output=True)
            if res_restore.returncode != 0 and b"errors ignored on restore" not in res_restore.stderr:
                err_msg = res_restore.stderr.decode("utf-8", errors="replace")
                raise RuntimeError(f"pg_restore failed with exit code {res_restore.returncode}: {err_msg}")
        drill_results["database_restored"] = True

        # Step 6: Restore and verify evidence files
        for item in manifest["evidence_storage"]["files"]:
            src_item = evidence_backup_dir / item["relative_path"]
            if is_encrypted and item["relative_path"].endswith(".enc"):
                rel_plain = item["relative_path"][:-4]
                dst_item = drill_evidence_dir / rel_plain
                dst_item.parent.mkdir(parents=True, exist_ok=True)

                if fmt == BACKUP_FORMAT_VERSION_V2_ETM and enc_key:
                    item_iv = bytes.fromhex(item["iv_hex"])
                    decrypt_file_etm(src_item, dst_item, enc_key, item_iv)
                else:
                    env = os.environ.copy()
                    env["TEMP_BACKUP_PASS"] = effective_passphrase
                    res_dec_ev = subprocess.run([
                        "openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "100000",
                        "-in", str(src_item), "-out", str(dst_item),
                        "-pass", "env:TEMP_BACKUP_PASS"
                    ], env=env, capture_output=True)
                    if res_dec_ev.returncode != 0:
                        raise RuntimeError("Failed to decrypt evidence file")

                # Verify plaintext hash of restored file
                exp_pt = item.get("plaintext_sha256")
                if exp_pt and _sha256_file(dst_item) != exp_pt:
                    raise ValueError(f"Restored evidence {dst_item} plaintext hash mismatch!")
            else:
                dst_item = drill_evidence_dir / item["relative_path"]
                dst_item.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_item, dst_item)
                if _sha256_file(dst_item) != item["sha256"]:
                    raise ValueError(f"Restored drill evidence file {dst_item} hash mismatch!")

        drill_results["evidence_restored_and_verified"] = True

        # Step 7: Verify restored database contents
        drill_url = f"postgresql+psycopg://{db_user}:local_dev_only@127.0.0.1:5432/{drill_db_name}"
        drill_engine = create_engine(drill_url)

        with drill_engine.connect() as conn:
            restored_alembic = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
            expected_alembic = dump_info.get("alembic_version")
            if expected_alembic and restored_alembic != expected_alembic:
                raise ValueError(f"Alembic version mismatch! Expected {expected_alembic}, got {restored_alembic}")
            drill_results["alembic_version_verified"] = True
            drill_results["restored_alembic_version"] = restored_alembic

            insp = inspect(drill_engine)
            restored_counts = {}
            for t in sorted(insp.get_table_names()):
                cnt = conn.execute(text(f'SELECT count(*) FROM "{t}"')).scalar()
                restored_counts[t] = int(cnt or 0)

            for t, exp_cnt in dump_info["table_counts"].items():
                act_cnt = restored_counts.get(t, -1)
                if act_cnt != exp_cnt:
                    raise ValueError(f"Table count mismatch for {t}! Expected {exp_cnt}, got {act_cnt}")
            drill_results["table_counts_matched"] = True
            drill_results["restored_table_counts"] = restored_counts

            # Referential integrity checks
            orphans_doc_versions = conn.execute(text(
                "SELECT count(*) FROM candidate_document_versions v "
                "LEFT JOIN candidate_documents d ON v.document_id = d.id "
                "WHERE d.id IS NULL"
            )).scalar()
            orphans_doc_blobs = conn.execute(text(
                "SELECT count(*) FROM candidate_document_versions v "
                "LEFT JOIN candidate_document_blobs b ON v.blob_hash = b.content_hash "
                "WHERE b.content_hash IS NULL"
            )).scalar()
            orphans_superseded = conn.execute(text(
                "SELECT count(*) FROM candidate_facts f "
                "LEFT JOIN candidate_facts s ON f.supersedes_fact_id = s.id "
                "WHERE f.supersedes_fact_id IS NOT NULL AND s.id IS NULL"
            )).scalar()
            orphans_fact_evidence = conn.execute(text(
                "SELECT count(*) FROM candidate_fact_evidence fe "
                "LEFT JOIN candidate_facts f ON fe.fact_id = f.id "
                "WHERE f.id IS NULL"
            )).scalar()
            orphans_evidence_version = conn.execute(text(
                "SELECT count(*) FROM candidate_fact_evidence fe "
                "LEFT JOIN candidate_document_versions v ON fe.document_version_id = v.id "
                "WHERE v.id IS NULL"
            )).scalar()
            orphans_apps = conn.execute(text(
                "SELECT count(*) FROM tracked_applications a "
                "LEFT JOIN job_postings j ON a.job_posting_id = j.id "
                "WHERE j.id IS NULL"
            )).scalar()
            orphans_attempts_app = conn.execute(text(
                "SELECT count(*) FROM application_attempts att "
                "LEFT JOIN tracked_applications a ON att.application_id = a.id "
                "WHERE a.id IS NULL"
            )).scalar()
            orphans_attempts_plan = conn.execute(text(
                "SELECT count(*) FROM application_attempts att "
                "LEFT JOIN submission_plans p ON att.submission_plan_id = p.id "
                "WHERE att.submission_plan_id IS NOT NULL AND p.id IS NULL"
            )).scalar()

            if any([
                (orphans_doc_versions or 0) > 0,
                (orphans_doc_blobs or 0) > 0,
                (orphans_superseded or 0) > 0,
                (orphans_fact_evidence or 0) > 0,
                (orphans_evidence_version or 0) > 0,
                (orphans_apps or 0) > 0,
                (orphans_attempts_app or 0) > 0,
                (orphans_attempts_plan or 0) > 0,
            ]):
                raise ValueError("Referential integrity failure! Found orphan records in drill restore.")
            drill_results["referential_integrity_verified"] = True

    finally:
        # Step 8: Clean up drill DB and temporary directories
        if drill_engine is not None:
            drill_engine.dispose()

        term_cmd = [
            "docker", "exec", container_name,
            "psql", "-U", db_user, "-d", "postgres", "-c",
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{drill_db_name}';"
        ]
        subprocess.run(term_cmd, capture_output=True)

        drop_cmd = ["docker", "exec", container_name, "dropdb", "-U", db_user, drill_db_name]
        res_drop = subprocess.run(drop_cmd, capture_output=True, text=True)
        drill_results["drill_db_cleaned"] = (res_drop.returncode == 0)

        if drill_evidence_dir.exists():
            shutil.rmtree(drill_evidence_dir, ignore_errors=True)
            drill_results["drill_evidence_cleaned"] = True

        if drill_temp_decrypted_dir.exists():
            shutil.rmtree(drill_temp_decrypted_dir, ignore_errors=True)

        drill_results["duration_seconds"] = round(time.time() - t0, 3)

    return drill_results


def restore_to_target_database(
    backup_dir: Path,
    target_database: str,
    container_name: str = DEFAULT_DOCKER_CONTAINER,
    db_user: str = DEFAULT_DB_USER,
    passphrase: str | None = None,
) -> dict[str, Any]:
    """Safely restore a backup into a new, non-existent target database.

    NEVER touches protected databases (jobpilot, jobpilot_test, jobpilot_e2e, jobpilot_workspace).
    Verifies cryptographic authenticity of backup BEFORE creating any database.
    Restores using pg_restore and cleans up all temporary decryption artifacts.
    """
    target_db = target_database.strip()
    if target_db.lower() in PROTECTED_DATABASES:
        raise ValueError(f"Safety violation: Cannot restore over protected database '{target_db}'!")

    manifest_path = backup_dir / "backup_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing backup_manifest.json in {backup_dir}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    effective_passphrase = passphrase or os.getenv("HIRE_STEWARD_BACKUP_PASSPHRASE")

    # Step 1: Pre-flight Cryptographic Authenticity Verification (BEFORE database creation)
    enc_key, auth_key = verify_backup_authenticity(backup_dir, manifest, effective_passphrase)

    # Step 2: Check target DB existence
    res_check = subprocess.run([
        "docker", "exec", container_name,
        "psql", "-U", db_user, "-d", "postgres", "-t", "-c",
        f"SELECT 1 FROM pg_database WHERE datname='{target_db}';"
    ], capture_output=True, text=True)
    if "1" in res_check.stdout:
        raise RuntimeError(f"Target database '{target_db}' already exists. Aborting to protect existing data.")

    # Step 3: Create target database
    subprocess.run(["docker", "exec", container_name, "createdb", "-U", db_user, target_db], check=True)

    fmt = manifest.get("format_version")
    is_encrypted = manifest.get("encryption", {}).get("status") == "ENCRYPTED"
    dump_info = manifest["database_dump"]
    dump_path = backup_dir / dump_info["filename"]

    temp_dec_dir = None
    restore_file = dump_path

    try:
        if is_encrypted:
            temp_dec_dir = get_default_backup_root() / f".temp_restore_dec_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}"
            temp_dec_dir.mkdir(parents=True, exist_ok=True)
            restore_file = temp_dec_dir / "decrypted.dump"

            if fmt == BACKUP_FORMAT_VERSION_V2_ETM and enc_key:
                dump_iv = bytes.fromhex(dump_info["iv_hex"])
                decrypt_file_etm(dump_path, restore_file, enc_key, dump_iv)
            else:
                env = os.environ.copy()
                env["TEMP_BACKUP_PASS"] = effective_passphrase
                res_dec = subprocess.run([
                    "openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "100000",
                    "-in", str(dump_path), "-out", str(restore_file),
                    "-pass", "env:TEMP_BACKUP_PASS"
                ], env=env, capture_output=True)
                if res_dec.returncode != 0:
                    raise RuntimeError("Decryption failed during target database restore.")

        # Step 4: Restore via pg_restore
        with open(restore_file, "rb") as f_in:
            subprocess.run([
                "docker", "exec", "-i", container_name,
                "pg_restore", "-U", db_user, "-d", target_db, "--no-owner", "--no-privileges"
            ], stdin=f_in, check=True)

        return {
            "status": "success",
            "target_database": target_db,
            "backup_source": str(backup_dir),
            "format_version": fmt,
            "restored_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception:
        # Cleanup target database on failure
        subprocess.run(["docker", "exec", container_name, "dropdb", "-U", db_user, target_db], capture_output=True)
        raise
    finally:
        if temp_dec_dir and temp_dec_dir.exists():
            shutil.rmtree(temp_dec_dir, ignore_errors=True)
