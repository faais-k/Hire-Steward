"""Dataset loader, manifest validator, and integrity verifier for Milestone 8 evaluation.

Enforces:
- Local-first SHA-256 manifest integrity and self-digest verification (Decision 4)
- Zero PII compliance (Decision 5, RFC 2606 reserved domains verification)
- Blinded input segregation (Zero ground-truth label leakage in case fixtures)
- Distinct incomplete fixture coverage and candidate profile validation (Decisions 1, 3, and 4)
- Truth-in-Security disclosure:
    In a local-first single-machine architecture, physical directory segregation
    does not provide operating-system-level access control against a root or
    local administrator. Blinding integrity and answer segregation are maintained
    cryptographically via SHA-256 manifest verification, automated pipeline
    segregation tests, and by strictly forbidding the inference loader from
    reading the ground_truth/ directory.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

FIXTURES_ROOT = (
    Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "real_matching_eval"
)


class DatasetIntegrityError(Exception):
    """Raised when dataset integrity, manifest hash, or blinding verification fails."""


def compute_sha256(path: Path) -> str:
    """Compute the SHA-256 checksum of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def compute_manifest_self_digest(manifest_data: dict[str, Any]) -> str:
    """Compute canonical SHA-256 self-digest with manifest_sha256 key omitted."""
    manifest_copy = {k: v for k, v in manifest_data.items() if k != "manifest_sha256"}
    manifest_bytes = json.dumps(manifest_copy, indent=2, sort_keys=True).encode("utf-8")
    return hashlib.sha256(manifest_bytes).hexdigest()


def load_manifest(fixtures_root: Path | None = None) -> dict[str, Any]:
    """Load the dataset manifest."""
    root = fixtures_root or FIXTURES_ROOT
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise DatasetIntegrityError(f"Dataset manifest missing at {manifest_path}")
    with open(manifest_path, encoding="utf-8") as f:
        return json.load(f)


def verify_dataset_manifest(fixtures_root: Path | None = None) -> dict[str, Any]:
    """Verify all fixture file checksums and the manifest self-digest.

    Returns summary of verified files.
    """
    root = fixtures_root or FIXTURES_ROOT
    manifest = load_manifest(root)

    # 1. Verify manifest self-digest
    expected_self_digest = manifest.get("manifest_sha256")
    if not expected_self_digest:
        raise DatasetIntegrityError("Manifest is missing manifest_sha256 field")
    computed_self_digest = compute_manifest_self_digest(manifest)
    if computed_self_digest != expected_self_digest:
        raise DatasetIntegrityError(
            f"Manifest self-digest verification failed! Expected {expected_self_digest}, got {computed_self_digest}"
        )

    # 2. Verify all individual fixture file checksums
    checksums: dict[str, str] = manifest.get("fixture_checksums", {})
    if not checksums:
        raise DatasetIntegrityError("Manifest contains no fixture checksums")

    verified_count = 0
    mismatches: list[str] = []

    for rel_path_str, expected_hash in checksums.items():
        file_path = root / rel_path_str
        if not file_path.is_file():
            mismatches.append(f"Missing file: {rel_path_str}")
            continue
        actual_hash = compute_sha256(file_path)
        if actual_hash != expected_hash:
            mismatches.append(
                f"Hash mismatch on {rel_path_str}: expected {expected_hash}, got {actual_hash}"
            )
        else:
            verified_count += 1

    if mismatches:
        raise DatasetIntegrityError(
            f"Manifest verification failed with {len(mismatches)} errors:\n"
            + "\n".join(mismatches[:10])
        )

    return {
        "status": "VERIFIED_VALID",
        "verified_file_count": verified_count,
        "manifest_sha256": expected_self_digest,
        "dataset_version": manifest.get("dataset_version"),
        "baseline_source_commit_sha": manifest.get("baseline_source_commit_sha"),
        "tracking_status": manifest.get("tracking_status"),
        "manifest_digest_method": manifest.get("manifest_digest_method"),
    }


def is_valid_offline_phone(phone: Any) -> bool:
    """Offline syntactic format validation for candidate telephone contact.

    Three-level contact validation taxonomy:
    1. Contact info supplied: non-null value present.
    2. Basically formatted / syntactically valid (offline standard):
       - Must be a non-empty, non-whitespace string.
       - Stripped string length must be between 7 and 20 characters inclusive.
       - Permitted characters: optional leading '+', digits (0-9), hyphens (-), dots (.), spaces ( ), parentheses (()).
       - Minimum 7 numeric digits: sum(c.isdigit() for c in phone) >= 7.
       Basic syntax confirms telecom formatting structure, but does NOT prove ITU-T E.164 allocation,
       carrier routing, active subscription, or live device reachability.
    3. Independently verified: Live verification (SMS OTP / carrier HLR lookup).
       Strictly excluded from offline architecture; zero external network requests or APIs.
    """
    if not phone or not isinstance(phone, str):
        return False
    stripped = phone.strip()
    if len(stripped) < 7 or len(stripped) > 20:
        return False
    body = stripped[1:] if stripped.startswith("+") else stripped
    allowed_chars = set("0123456789- .()")
    if not all(c in allowed_chars for c in body):
        return False
    digit_count = sum(c.isdigit() for c in stripped)
    return digit_count >= 7


def is_valid_offline_email(email: Any) -> bool:
    """Offline syntactic format validation for candidate email contact.

    Three-level contact validation taxonomy:
    1. Contact info supplied: non-null value present.
    2. Basically formatted / syntactically valid (offline standard):
       - Must be a non-empty, non-whitespace string.
       - Contains '@' and a domain dot in the domain segment ('user@domain.tld'),
         matching RFC 2606 reserved domains in evaluation fixtures (.invalid, .example).
       Basic syntax confirms structural syntax, but does NOT prove mailbox existence,
       MX record validity, or SMTP handshake deliverability.
    3. Independently verified: Live verification (SMTP / MX handshake / confirmation token).
       Strictly excluded from offline architecture; zero external network requests or APIs.
    """
    if not email or not isinstance(email, str):
        return False
    stripped = email.strip()
    if "@" not in stripped:
        return False
    domain_part = stripped.split("@")[-1]
    return "." in domain_part


def validate_candidate_profile(profile: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate candidate profile completeness and required core information.

    Required core information (strictly 3 elements):
    1. name: non-empty, non-whitespace string.
    2. contact_info: non-empty object containing at least one syntactically valid contact channel
       (email OR phone). Both are not required.
       - Contact Validation Precision (Three Distinct Concepts):
           * Contact information supplied: non-null field value present for email or phone.
           * Basically formatted / syntactically valid contact information (offline standard):
             - Email: Contains '@' and a domain dot ('user@domain.tld'), matching RFC 2606 in evaluation.
               Basic syntax does NOT prove mailbox existence, MX records, or deliverability.
             - Phone: Offline format check — string matching basic telecom formatting: optional leading '+',
               permitted delimiters (hyphens, dots, spaces, parentheses), between 7 and 20 total characters,
               and at least 7 numeric digits (sum(c.isdigit() for c in phone) >= 7).
               Basic syntax does NOT prove ITU-T E.164 allocation, carrier routing, or live reachability.
               A non-empty string is not equated with syntactic validity.
           * Independently verified contact information:
             Live verification (SMS OTP / carrier HLR lookup / SMTP handshake / MX verification) is strictly
             excluded from the offline architecture. Zero external network requests or third-party validation APIs.
             Offline syntactic validity is necessary and sufficient for profile completeness.
    3. education_status: non-empty object with a declared education state. A formal degree is NOT mandatory;
       unverified, self-taught, bootcamp, or explicitly declared no-formal-education (e.g.
       'DECLARED_NO_FORMAL_EDUCATION', 'DECLARED_NONE') is accepted as complete and valid.
       Missing education altogether, or declaration_state == 'ABSENT' / 'MALFORMED', is incomplete.

    Optional information (strictly non-blocking):
    - formal degree: strictly optional.
    - experience: strictly optional (career starters with 0 experience are valid).
    - projects: strictly optional (career starters with 0 projects are valid).
    - skills: strictly optional list (career starters with 0 skills are valid).
    - certifications: strictly optional list.
    - other career information: strictly optional.

    Returns:
        (is_valid, list_of_issues)
    """
    issues: list[str] = []

    # 1. Validate name
    name = profile.get("name")
    if not name or not isinstance(name, str) or not name.strip():
        issues.append("Missing candidate name")

    # 2. Validate contact channels: at least ONE channel (email OR phone) is sufficient
    contact = profile.get("contact_info")
    if not contact or not isinstance(contact, dict):
        issues.append("Missing contact channel (contact_info is absent)")
    else:
        email = contact.get("email")
        phone = contact.get("phone")
        has_email = is_valid_offline_email(email)
        has_phone = is_valid_offline_phone(phone)
        if not (has_email or has_phone):
            issues.append(
                "Missing contact channel (at least one syntactically valid offline channel: email or phone is required)"
            )

    # 3. Validate education declaration
    edu = profile.get("education_status")
    if not edu or not isinstance(edu, dict):
        issues.append("Incomplete or missing education status")
    else:
        decl_state = edu.get("declaration_state")
        valid_states = {
            "DECLARED_VERIFIED",
            "DECLARED_UNVERIFIED",
            "DECLARED_SELF_TAUGHT",
            "DECLARED_NO_FORMAL_EDUCATION",
            "DECLARED_NONE",
        }
        if decl_state not in valid_states:
            issues.append(
                f"Invalid or absent education declaration state: {decl_state!r}"
            )

    # Optional fields (experience, projects, skills, certifications) do not cause validation failure if empty
    return len(issues) == 0, issues


def verify_blinding_and_segregation(fixtures_root: Path | None = None) -> dict[str, int]:
    """Verify that case fixtures contain zero ground truth labels or target tiers."""
    root = fixtures_root or FIXTURES_ROOT
    forbidden_keys = {
        "human_suitability",
        "human_suitability_label",
        "target_system_tier",
        "target_submission_eligible",
        "adjudication_notes",
        "owner_adjudication_notes",
        "expected_fit_tier",
        "expected_required_met",
    }

    scanned_cases = 0
    violations: list[str] = []

    for case_file in root.glob("cases/**/*.json"):
        scanned_cases += 1
        with open(case_file, encoding="utf-8") as f:
            data = json.load(f)
        for key in forbidden_keys:
            if key in data:
                violations.append(f"Leaked ground-truth key '{key}' found in {case_file.name}")

    for adv_file in root.glob("adversarial/*.json"):
        scanned_cases += 1
        with open(adv_file, encoding="utf-8") as f:
            data = json.load(f)
        for key in forbidden_keys:
            if key in data:
                violations.append(f"Leaked ground-truth key '{key}' found in {adv_file.name}")

    if violations:
        raise DatasetIntegrityError(
            f"Blinding violation! Found {len(violations)} leaked ground-truth fields:\n"
            + "\n".join(violations[:10])
        )

    return {"scanned_cases": scanned_cases, "violations": 0}


def verify_zero_pii(fixtures_root: Path | None = None) -> dict[str, int]:
    """Verify that all profiles use RFC 2606 reserved domains (.invalid / .example) and fictitious details."""
    root = fixtures_root or FIXTURES_ROOT
    scanned_profiles = 0
    pii_violations: list[str] = []

    for profile_file in root.glob("profiles/**/*.json"):
        scanned_profiles += 1
        with open(profile_file, encoding="utf-8") as f:
            p = json.load(f)
        contact = p.get("contact_info")
        if contact and isinstance(contact, dict):
            email = contact.get("email")
            if email and email.strip():
                if "@" in email:
                    if not (
                        email.endswith("@example.invalid")
                        or email.endswith("@example.org")
                        or email.endswith("@example.com")
                    ):
                        pii_violations.append(
                            f"Non-RFC2606 email domain detected in {profile_file.name}: {email}"
                        )
                elif email not in {"not-a-valid-email-string", "not-an-email"}:
                    pii_violations.append(
                        f"Unrecognized non-email string in {profile_file.name}: {email}"
                    )

    if pii_violations:
        raise DatasetIntegrityError(
            f"PII compliance violation! Found {len(pii_violations)} real domain exposures:\n"
            + "\n".join(pii_violations[:10])
        )

    return {"scanned_profiles": scanned_profiles, "pii_violations": 0}


def load_unlabeled_case(case_id: str, fixtures_root: Path | None = None) -> dict[str, Any]:
    """Load a single unlabeled evaluation case by ID.

    Architectural Invariant:
    This loader strictly loads from cases/frozen, cases/calibration, or adversarial/.
    It NEVER accesses ground_truth/ to preserve blinding.
    """
    root = fixtures_root or FIXTURES_ROOT
    for sub in ["cases/frozen", "cases/calibration", "adversarial"]:
        target = root / sub / f"{case_id}.json"
        if target.is_file():
            with open(target, encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError(f"Case '{case_id}' not found under {root}")


def load_candidate_profile(profile_id: str, fixtures_root: Path | None = None) -> dict[str, Any]:
    """Load a candidate profile fixture by ID."""
    root = fixtures_root or FIXTURES_ROOT
    for sub in ["profiles/frozen", "profiles/calibration", "profiles/adversarial"]:
        target = root / sub / f"{profile_id}.json"
        if target.is_file():
            with open(target, encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError(f"Profile '{profile_id}' not found under {root}")


def load_job_posting(posting_id: str, fixtures_root: Path | None = None) -> dict[str, Any]:
    """Load a job posting fixture by ID."""
    root = fixtures_root or FIXTURES_ROOT
    for sub in ["postings/frozen", "postings/calibration", "postings/adversarial"]:
        target = root / sub / f"{posting_id}.json"
        if target.is_file():
            with open(target, encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError(f"Job posting '{posting_id}' not found under {root}")
