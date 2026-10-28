"""Operator-only recovery for stale candidate-evidence upload reservations.

This command never serves HTTP and must be run locally with a configured
database and evidence storage root. It only removes files owned by a stale,
unreferenced reservation; unexpected root files are intentionally untouched.
"""

import argparse
import os

from backend.app.adapters.storage import EvidenceStorage
from backend.app.evidence_config import evidence_settings_from_environment
from backend.app.db.session import make_session_factory
from backend.app.services.candidate_evidence import reconcile_stale_reservations


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile stale candidate-evidence reservations")
    parser.add_argument("--apply", action="store_true", help="perform destructive reconciliation")
    arguments = parser.parse_args()
    if not arguments.apply:
        parser.error("refusing to alter evidence storage without --apply")
    database_url = os.getenv("DATABASE_URL")
    settings = evidence_settings_from_environment()
    if not database_url or settings is None:
        parser.error("DATABASE_URL and EVIDENCE_STORAGE_ROOT are required")
    storage = EvidenceStorage(settings)
    with make_session_factory(database_url)() as session:
        result = reconcile_stale_reservations(session, storage, settings)
    print(
        "reconciliation complete: "
        f"released_reservations={result['released_reservations']} "
        f"protected_reservations={result['protected_reservations']} "
        f"unexpected_files={result['unexpected_files']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
