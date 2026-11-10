"""Domain models, manifest schema, and security validation for Data Portability (Stage 8).

Guarantees:
1. Strict exclusion of secrets, credentials, tokens, and internal private keys.
2. Canonical checksum calculation for tamper detection.
3. Version compatibility checking ('hire-steward-export-v1').
4. Schema validation and structural verification prior to import.
5. Deterministic preview-to-commit token binding.
6. Coverage of all 17+ supported application entities.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

EXPORT_FORMAT_VERSION = "hire-steward-export-v1"
MAX_IMPORT_PAYLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

# Keys that must never be exported
FORBIDDEN_EXPORT_KEYS = {
    "api_key",
    "secret",
    "token",
    "password",
    "anthropic_api_key",
    "openai_api_key",
    "lease_token",
}

SUPPORTED_COLLECTIONS = (
    "candidate_documents",
    "candidate_document_blobs",
    "candidate_document_versions",
    "candidate_facts",
    "candidate_fact_evidence",
    "job_sources",
    "employer_subscriptions",
    "discovery_runs",
    "job_postings",
    "job_posting_snapshots",
    "compensation_preferences",
    "compensation_preference_audits",
    "compensation_assessments",
    "answer_bank_items",
    "tracked_applications",
    "application_status_history",
    "submission_plans",
    "application_attempts",
    "audit_events",
)

VALID_FACT_TYPES = {"SKILL", "EDUCATION", "EMPLOYMENT", "PROJECT", "CERTIFICATION"}
VALID_FACT_STATES = {"UNREVIEWED", "DOCUMENT_SUPPORTED", "USER_VERIFIED", "CONFLICTED", "REJECTED", "SUPERSEDED"}
VALID_APP_STATUSES = {
    "SAVED",
    "PREPARING",
    "READY_FOR_REVIEW",
    "APPLIED",
    "INTERVIEWING",
    "OFFER_RECEIVED",
    "REJECTED",
    "WITHDRAWN",
    "ARCHIVED",
}
VALID_POSTING_STATUSES = {"ACTIVE", "REMOVED", "STALE", "UNKNOWN", "CLOSED_CONFIRMED"}


class DataPortabilityError(Exception):
    """Base exception for export/import domain failures."""

    def __init__(self, message: str, code: str = "DATA_PORTABILITY_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def sanitize_bundle_dictionary(obj: Any) -> Any:
    """Recursively scrub any sensitive keys or credential patterns from export bundle."""
    if isinstance(obj, dict):
        cleaned: dict[str, Any] = {}
        for k, v in obj.items():
            k_lower = k.lower()
            if k_lower in FORBIDDEN_EXPORT_KEYS or "secret" in k_lower or "token" in k_lower or "password" in k_lower:
                continue
            cleaned[k] = sanitize_bundle_dictionary(v)
        return cleaned
    if isinstance(obj, list):
        return [sanitize_bundle_dictionary(item) for item in obj]
    if isinstance(obj, str):
        # Double check for raw API key patterns
        if re.match(r"^sk-[a-zA-Z0-9_\-]{20,}", obj):
            return "[REDACTED_SECRET]"
    return obj


def _normalize_numbers(data: Any) -> Any:
    """Normalize numeric representations (e.g. float 5.0 vs int 5) for cross-language JSON canonicalization."""
    if isinstance(data, dict):
        return {k: _normalize_numbers(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_normalize_numbers(item) for item in data]
    if isinstance(data, float) and data.is_integer():
        return int(data)
    return data


def compute_bundle_checksum(payload: dict[str, Any]) -> str:
    """Compute deterministic SHA-256 checksum over the payload content excluding manifest."""
    data_to_hash = {k: v for k, v in payload.items() if k != "manifest"}
    canonical = json.dumps(_normalize_numbers(data_to_hash), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_preview_token(checksum: str, collisions: dict[str, int], new_counts: dict[str, int]) -> str:
    """Generate deterministic SHA-256 token binding the validated bundle checksum to the collision assessment."""
    token_seed = {
        "checksum": checksum,
        "collisions": sorted(collisions.items()),
        "new_counts": sorted(new_counts.items()),
    }
    canonical = json.dumps(token_seed, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ExportManifest:
    format_version: str
    product: str
    exported_at: str
    checksum_sha256: str
    record_counts: dict[str, int]


@dataclass(frozen=True)
class ImportPreviewResult:
    is_valid: bool
    format_version: str
    checksum_verified: bool
    new_counts: dict[str, int]
    collision_counts: dict[str, int]
    warnings: list[str]
    preview_token: str | None = None


def validate_bundle_entity_records(bundle: dict[str, Any]) -> list[str]:
    """Validate internal field types, required keys, and reference integrity in bundle."""
    warnings: list[str] = []

    # 1. Candidate facts validation
    facts = bundle.get("candidate_facts")
    fact_ids: set[str] = set()
    if isinstance(facts, list):
        for idx, f in enumerate(facts):
            if not isinstance(f, dict):
                warnings.append(f"candidate_facts[{idx}] must be a JSON object.")
                continue
            fid = f.get("id")
            if not fid or not isinstance(fid, str):
                warnings.append(f"candidate_facts[{idx}] missing valid 'id'.")
            else:
                fact_ids.add(fid)
            ft = f.get("fact_type")
            if ft and ft not in VALID_FACT_TYPES:
                warnings.append(f"candidate_facts[{idx}] has invalid fact_type '{ft}'.")
            st = f.get("verification_state")
            if st and st not in VALID_FACT_STATES:
                warnings.append(f"candidate_facts[{idx}] has invalid verification_state '{st}'.")

    # 2. Candidate documents & versions
    docs = bundle.get("candidate_documents")
    doc_ids: set[str] = set()
    if isinstance(docs, list):
        for idx, d in enumerate(docs):
            if isinstance(d, dict) and d.get("id"):
                doc_ids.add(d["id"])

    versions = bundle.get("candidate_document_versions")
    version_ids: set[str] = set()
    if isinstance(versions, list):
        for idx, v in enumerate(versions):
            if isinstance(v, dict):
                vid = v.get("id")
                if vid:
                    version_ids.add(vid)
                doc_ref = v.get("document_id")
                if doc_ref and doc_ids and doc_ref not in doc_ids:
                    warnings.append(f"candidate_document_versions[{idx}] references unknown document_id '{doc_ref}'.")

    # 3. Provenance evidence links
    evidence = bundle.get("candidate_fact_evidence")
    if isinstance(evidence, list):
        for idx, ev in enumerate(evidence):
            if isinstance(ev, dict):
                f_ref = ev.get("fact_id")
                if f_ref and fact_ids and f_ref not in fact_ids:
                    warnings.append(f"candidate_fact_evidence[{idx}] references unknown fact_id '{f_ref}'.")
                v_ref = ev.get("document_version_id")
                if v_ref and version_ids and v_ref not in version_ids:
                    warnings.append(f"candidate_fact_evidence[{idx}] references unknown document_version_id '{v_ref}'.")

    # 4. Job postings and applications
    postings = bundle.get("job_postings")
    posting_ids: set[str] = set()
    if isinstance(postings, list):
        for idx, p in enumerate(postings):
            if isinstance(p, dict):
                pid = p.get("id")
                if pid:
                    posting_ids.add(pid)
                st = p.get("lifecycle_status")
                if st and st not in VALID_POSTING_STATUSES:
                    warnings.append(f"job_postings[{idx}] has invalid lifecycle_status '{st}'.")

    apps = bundle.get("tracked_applications")
    app_ids: set[str] = set()
    if isinstance(apps, list):
        for idx, app in enumerate(apps):
            if isinstance(app, dict):
                aid = app.get("id")
                if aid:
                    app_ids.add(aid)
                st = app.get("status")
                if st and st not in VALID_APP_STATUSES:
                    warnings.append(f"tracked_applications[{idx}] has invalid status '{st}'.")
                p_ref = app.get("job_posting_id")
                if p_ref and posting_ids and p_ref not in posting_ids:
                    warnings.append(f"tracked_applications[{idx}] references unknown job_posting_id '{p_ref}'.")

    # 5. Submission plans
    plans = bundle.get("submission_plans")
    plan_ids: set[str] = set()
    if isinstance(plans, list):
        for idx, pl in enumerate(plans):
            if isinstance(pl, dict):
                pl_id = pl.get("id")
                if pl_id:
                    plan_ids.add(pl_id)
                a_ref = pl.get("application_id")
                if a_ref and app_ids and a_ref not in app_ids:
                    warnings.append(f"submission_plans[{idx}] references unknown application_id '{a_ref}'.")
                p_ref = pl.get("job_posting_id")
                if p_ref and posting_ids and p_ref not in posting_ids:
                    warnings.append(f"submission_plans[{idx}] references unknown job_posting_id '{p_ref}'.")

    # 6. Application attempts
    attempts = bundle.get("application_attempts")
    if isinstance(attempts, list):
        for idx, att in enumerate(attempts):
            if isinstance(att, dict):
                a_ref = att.get("application_id")
                if a_ref and app_ids and a_ref not in app_ids:
                    warnings.append(f"application_attempts[{idx}] references unknown application_id '{a_ref}'.")
                pl_ref = att.get("submission_plan_id")
                if pl_ref and plan_ids and pl_ref not in plan_ids:
                    warnings.append(f"application_attempts[{idx}] references unknown submission_plan_id '{pl_ref}'.")

    return warnings


def validate_import_bundle_manifest(bundle: dict[str, Any]) -> ImportPreviewResult:
    """Validate structure, format version, integrity checksum, and schemas of incoming bundle."""
    if not isinstance(bundle, dict):
        raise DataPortabilityError("Import payload must be a JSON object", "INVALID_BUNDLE_STRUCTURE")

    manifest = bundle.get("manifest")
    if not manifest or not isinstance(manifest, dict):
        raise DataPortabilityError("Missing or invalid 'manifest' header", "MISSING_MANIFEST")

    fmt = manifest.get("format_version")
    if fmt != EXPORT_FORMAT_VERSION:
        raise DataPortabilityError(
            f"Unsupported format version '{fmt}'. Required: '{EXPORT_FORMAT_VERSION}'",
            "UNSUPPORTED_FORMAT_VERSION",
        )

    expected_checksum = manifest.get("checksum_sha256")
    actual_checksum = compute_bundle_checksum(bundle)

    warnings: list[str] = []
    is_valid = True
    checksum_ok = False

    if not expected_checksum or not isinstance(expected_checksum, str) or not SHA256_PATTERN.match(expected_checksum):
        warnings.append("Missing or invalid checksum_sha256 in manifest header.")
        is_valid = False
    elif expected_checksum != actual_checksum:
        warnings.append("Bundle checksum does not match contents. Payload may have been modified or corrupted.")
        is_valid = False
    else:
        checksum_ok = True

    # Validate structural types for singletons
    prof = bundle.get("candidate_profile")
    if prof is not None and not isinstance(prof, dict):
        warnings.append("Invalid 'candidate_profile': expected JSON object.")
        is_valid = False

    settings = bundle.get("user_settings")
    if settings is not None and not isinstance(settings, dict):
        warnings.append("Invalid 'user_settings': expected JSON object.")
        is_valid = False

    # Validate structural types for collections
    new_counts: dict[str, int] = {
        "candidate_profile": 1 if isinstance(prof, dict) else 0,
        "user_settings": 1 if isinstance(settings, dict) else 0,
    }

    for col in SUPPORTED_COLLECTIONS:
        items = bundle.get(col)
        if items is not None:
            if not isinstance(items, list):
                warnings.append(f"Invalid '{col}': expected list.")
                is_valid = False
                new_counts[col] = 0
            else:
                new_counts[col] = len(items)
        else:
            new_counts[col] = 0

    # Semantic & foreign key integrity checks (recorded in warnings for operator visibility)
    record_warnings = validate_bundle_entity_records(bundle)
    if record_warnings:
        warnings.extend(record_warnings)

    return ImportPreviewResult(
        is_valid=is_valid,
        format_version=str(fmt),
        checksum_verified=checksum_ok,
        new_counts=new_counts,
        collision_counts={},
        warnings=warnings,
    )
