"""Command-line interface for Hire-Steward personal data backup and restore drills."""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import sys

from backend.app.services.data_backup import (
    DEFAULT_WORKSPACE_DB,
    create_workspace_backup,
    execute_restore_drill,
    get_default_backup_root,
    restore_to_target_database,
)


def _resolve_passphrase(
    env_name: str | None,
    prompt_if_missing: bool = False,
    prompt_text: str = "Enter passphrase (hidden): ",
) -> str | None:
    """Safely resolve passphrase from environment variable or secure interactive prompt without CLI exposure."""
    val = None
    if env_name:
        val = os.getenv(env_name)
    if not val:
        val = os.getenv("HIRE_STEWARD_BACKUP_PASSPHRASE")
    if not val and prompt_if_missing:
        try:
            if sys.stdin.isatty():
                val = getpass.getpass(prompt_text)
        except Exception:
            val = None
    return val


def cmd_backup(args: argparse.Namespace) -> int:
    passphrase = _resolve_passphrase(
        args.passphrase_env,
        prompt_if_missing=args.encrypt,
        prompt_text="Enter passphrase for backup encryption (hidden): ",
    )
    print(f"Starting data backup for database: {args.database} (Encrypted: {bool(passphrase)})...")
    backup_dir = create_workspace_backup(database_name=args.database, passphrase=passphrase)
    print(f"[PASS] Backup created at: {backup_dir}")

    manifest_path = backup_dir / "backup_manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    db_dump = manifest["database_dump"]
    ev_storage = manifest["evidence_storage"]
    enc_info = manifest.get("encryption", {})

    print(f"  Format: {manifest.get('format_version')}")
    print(f"  Encryption Status: {enc_info.get('status')}")
    if enc_info.get("status") == "ENCRYPTED":
        print(f"  Cipher: {enc_info.get('cipher')} + {enc_info.get('mac')} ({enc_info.get('kdf')})")
        print(f"  Iterations: {enc_info.get('kdf_iterations')}")
    print(f"  Timestamp: {manifest.get('created_at')}")
    print(f"  Database Dump: {db_dump['filename']} ({db_dump['size_bytes']} bytes)")
    print(f"  Dump Hash: {db_dump.get('ciphertext_sha256') or db_dump.get('sha256')}")
    print(f"  Alembic Head: {db_dump['alembic_version']}")
    print(f"  Evidence Files: {ev_storage['total_files']} files ({ev_storage['total_bytes']} bytes)")

    if args.drill:
        print("\nExecuting immediate recovery drill...")
        drill_report = execute_restore_drill(backup_dir, passphrase=passphrase)
        print(json.dumps(drill_report, indent=2))
        if (
            drill_report.get("alembic_version_verified")
            and drill_report.get("table_counts_matched")
            and drill_report.get("referential_integrity_verified")
            and drill_report.get("drill_db_cleaned")
        ):
            print(f"[PASS] Recovery drill succeeded in {drill_report['duration_seconds']}s.")
            return 0
        else:
            print("[FAIL] Recovery drill failed verification checks.")
            return 1
    return 0


def cmd_restore_drill(args: argparse.Namespace) -> int:
    backup_path = args.backup_dir
    if not backup_path:
        root = get_default_backup_root()
        data_backups = sorted([p for p in root.glob("data_*") if p.is_dir()])
        if not data_backups:
            print(f"[FAIL] No data backups found in: {root}")
            return 1
        backup_path = data_backups[-1]
        print(f"Using latest backup: {backup_path}")
    else:
        backup_path = Path(backup_path)
        if not backup_path.exists():
            print(f"[FAIL] Backup directory does not exist: {backup_path}")
            return 1

    passphrase = _resolve_passphrase(args.passphrase_env)
    manifest_file = backup_path / "backup_manifest.json"
    if manifest_file.exists() and not passphrase:
        try:
            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
            if manifest_data.get("encryption", {}).get("status") == "ENCRYPTED":
                passphrase = _resolve_passphrase(
                    args.passphrase_env,
                    prompt_if_missing=True,
                    prompt_text="Backup is encrypted. Enter passphrase (hidden): ",
                )
        except Exception:
            pass

    print(f"Executing restore drill from: {backup_path}")
    report = execute_restore_drill(backup_path, passphrase=passphrase)
    print(json.dumps(report, indent=2))
    if (
        report.get("manifest_verified")
        and report.get("dump_sha256_verified")
        and report.get("database_restored")
        and report.get("alembic_version_verified")
        and report.get("table_counts_matched")
        and report.get("referential_integrity_verified")
        and report.get("drill_db_cleaned")
    ):
        print("\n[SUCCESS] Restore drill passed all verification checks!")
        return 0
    else:
        print("\n[FAILURE] Restore drill failed verification checks.")
        return 1


def cmd_restore_target(args: argparse.Namespace) -> int:
    target_db = args.target_database.strip()
    backup_path = args.backup_dir
    if not backup_path:
        root = get_default_backup_root()
        data_backups = sorted([p for p in root.glob("data_*") if p.is_dir()])
        if not data_backups:
            print(f"[FAIL] No data backups found in: {root}")
            return 1
        backup_path = data_backups[-1]
    else:
        backup_path = Path(backup_path)

    passphrase = _resolve_passphrase(args.passphrase_env)
    manifest_file = backup_path / "backup_manifest.json"
    if manifest_file.exists() and not passphrase:
        try:
            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
            if manifest_data.get("encryption", {}).get("status") == "ENCRYPTED":
                passphrase = _resolve_passphrase(
                    args.passphrase_env,
                    prompt_if_missing=True,
                    prompt_text="Backup is encrypted. Enter passphrase (hidden): ",
                )
        except Exception:
            pass

    print(f"Restoring backup {backup_path} into separate target database: {target_db}...")
    try:
        res = restore_to_target_database(
            backup_dir=backup_path,
            target_database=target_db,
            passphrase=passphrase,
        )
        print(f"[SUCCESS] Successfully restored backup into new database: {target_db}")
        print(json.dumps(res, indent=2))
        return 0
    except Exception as e:
        print(f"[FAIL] Restore failed: {e}")
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Hire-Steward Data Backup and Restore CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_backup = subparsers.add_parser("backup", help="Create a workspace backup")
    p_backup.add_argument("--database", default=DEFAULT_WORKSPACE_DB, help="Target database name")
    p_backup.add_argument("--drill", action="store_true", help="Run immediate recovery drill")
    p_backup.add_argument("--encrypt", action="store_true", help="Prompt for encryption passphrase if not in environment")
    p_backup.add_argument("--passphrase-env", default=None, help="Environment variable name holding passphrase")

    p_drill = subparsers.add_parser("drill", help="Run recovery drill on a backup")
    p_drill.add_argument("--backup-dir", default=None, help="Path to backup directory (defaults to latest)")
    p_drill.add_argument("--passphrase-env", default=None, help="Environment variable name holding passphrase")

    p_restore = subparsers.add_parser("restore", help="Restore backup into a new separate database")
    p_restore.add_argument("--target-database", required=True, help="New target database name (must not exist)")
    p_restore.add_argument("--backup-dir", default=None, help="Path to backup directory (defaults to latest)")
    p_restore.add_argument("--passphrase-env", default=None, help="Environment variable name holding passphrase")

    args = parser.parse_args()
    if args.command == "backup":
        sys.exit(cmd_backup(args))
    elif args.command == "drill":
        sys.exit(cmd_restore_drill(args))
    elif args.command == "restore":
        sys.exit(cmd_restore_target(args))


if __name__ == "__main__":
    main()
