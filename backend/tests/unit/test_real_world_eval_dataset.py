"""Unit and validation tests for Milestone 8 Task 8.1 real-world evaluation dataset."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from backend.app.domain.candidate_evidence import FactType, FactVerificationState
from backend.app.domain.job_matching import (
    CandidateEvidenceItem,
    ConfidenceLevel,
    FitTier,
    JobMatchAssessment,
    assess_job_match,
)
from backend.app.evaluation.real_world_dataset import (
    FIXTURES_ROOT,
    DatasetIntegrityError,
    compute_manifest_self_digest,
    compute_sha256,
    is_valid_offline_email,
    is_valid_offline_phone,
    load_candidate_profile,
    load_job_posting,
    load_manifest,
    load_unlabeled_case,
    validate_candidate_profile,
    verify_blinding_and_segregation,
    verify_dataset_manifest,
    verify_zero_pii,
)


def test_manifest_loads_and_verifies_all_checksums():
    """Verify that all 188 fixture checksums in manifest.json match disk files and self-digest verifies."""
    summary = verify_dataset_manifest(FIXTURES_ROOT)
    assert summary["status"] == "VERIFIED_VALID"
    assert summary["verified_file_count"] == 188
    assert summary["dataset_version"] == "1.0.0-task8.1-frozen"
    assert summary["baseline_source_commit_sha"] == "a517dd4f9dd0e3add7d1b6adbf5797af0dbf4b3e"
    assert summary["tracking_status"] == "LOCAL_UNTRACKED_CATALOGED"
    assert "SHA-256 computed over canonical UTF-8 JSON" in summary["manifest_digest_method"]
    assert len(summary["manifest_sha256"]) == 64


def test_manifest_self_digest_tamper_detection(tmp_path: Path):
    """Verify that tampering with manifest contents trips self-digest verification."""
    manifest = load_manifest(FIXTURES_ROOT)
    tampered = dict(manifest)
    tampered["dataset_version"] = "1.0.0-tampered"

    tampered_path = tmp_path / "manifest.json"
    with open(tampered_path, "w", encoding="utf-8") as f:
        json.dump(tampered, f, indent=2)

    with pytest.raises(DatasetIntegrityError, match="Manifest self-digest verification failed"):
        verify_dataset_manifest(tmp_path)


def test_manifest_fixture_counts_and_partition_reconciliation():
    """Verify exact counts: 60 frozen, 20 calibration, 12 adversarial = 92 cases; 188 total files."""
    manifest = load_manifest(FIXTURES_ROOT)
    partitions = manifest["dataset_partitions"]

    assert partitions["frozen_benchmark_cases"] == 60
    assert partitions["calibration_cases"] == 20
    assert partitions["adversarial_regression_cases"] == 12
    assert partitions["total_evaluation_cases"] == 92

    # Verify physical files on disk
    frozen_files = list((FIXTURES_ROOT / "cases" / "frozen").glob("*.json"))
    calib_files = list((FIXTURES_ROOT / "cases" / "calibration").glob("*.json"))
    adv_files = list((FIXTURES_ROOT / "adversarial").glob("*.json"))

    assert len(frozen_files) == 60
    assert len(calib_files) == 20
    assert len(adv_files) == 12

    # Profiles and postings
    frozen_profiles = list((FIXTURES_ROOT / "profiles" / "frozen").glob("*.json"))
    calib_profiles = list((FIXTURES_ROOT / "profiles" / "calibration").glob("*.json"))
    adv_profiles = list((FIXTURES_ROOT / "profiles" / "adversarial").glob("*.json"))
    assert len(frozen_profiles) == 21
    assert len(calib_profiles) == 8
    assert len(adv_profiles) == 12
    assert len(frozen_profiles) + len(calib_profiles) + len(adv_profiles) == 41

    frozen_postings = list((FIXTURES_ROOT / "postings" / "frozen").glob("*.json"))
    calib_postings = list((FIXTURES_ROOT / "postings" / "calibration").glob("*.json"))
    adv_postings = list((FIXTURES_ROOT / "postings" / "adversarial").glob("*.json"))
    assert len(frozen_postings) == 28
    assert len(calib_postings) == 8
    assert len(adv_postings) == 12
    assert len(frozen_postings) + len(calib_postings) + len(adv_postings) == 48


def test_candidate_profile_validation_rules():
    """Verify validation logic: single contact channel ok, degree optional, empty exp/proj ok."""
    # 1. Complete profile P_froz_01
    p1 = load_candidate_profile("P_froz_01", FIXTURES_ROOT)
    is_valid, issues = validate_candidate_profile(p1)
    assert is_valid is True
    assert issues == []

    # 2. Career starter with 0 experience and 0 projects (P_froz_11)
    p11 = load_candidate_profile("P_froz_11", FIXTURES_ROOT)
    assert p11["contact_info"]["phone"] is None  # only email provided
    assert p11["experience"] == []
    assert p11["projects"] == []
    is_valid, issues = validate_candidate_profile(p11)
    assert is_valid is True
    assert issues == []

    # 3. Only phone provided (email is None) is valid
    p_phone_only = dict(p11)
    p_phone_only["contact_info"] = {
        "email": None,
        "phone": "+1-555-010-9999",
        "location": "Dallas, TX",
    }
    is_valid, issues = validate_candidate_profile(p_phone_only)
    assert is_valid is True
    assert issues == []

    # 4. Self-taught / bootcamp / unverified education declaration is valid
    p_selftaught = dict(p11)
    p_selftaught["education_status"] = {
        "declaration_state": "DECLARED_SELF_TAUGHT",
        "status_stated": "Self-taught software engineering, freeCodeCamp",
        "degree_level": None,
        "field_of_study": "Computer Science",
        "institution": None,
        "is_verified": False,
    }
    is_valid, issues = validate_candidate_profile(p_selftaught)
    assert is_valid is True
    assert issues == []

    # 4b. Declared no formal education with 0 experience and 0 projects is valid
    p_no_formal = dict(p11)
    p_no_formal["education_status"] = {
        "declaration_state": "DECLARED_NO_FORMAL_EDUCATION",
        "status_stated": "No formal degree or higher education; self-taught career starter",
        "degree_level": None,
        "field_of_study": None,
        "institution": None,
        "is_verified": False,
    }
    is_valid, issues = validate_candidate_profile(p_no_formal)
    assert is_valid is True
    assert issues == []

    # 5. Missing name fails
    p_no_name = dict(p11)
    p_no_name["name"] = None
    is_valid, issues = validate_candidate_profile(p_no_name)
    assert is_valid is False
    assert any("Missing candidate name" in msg for msg in issues)

    # 6. Missing both contact channels fails
    p_no_contact = dict(p11)
    p_no_contact["contact_info"] = {"email": None, "phone": None, "location": "NYC"}
    is_valid, issues = validate_candidate_profile(p_no_contact)
    assert is_valid is False
    assert any("Missing contact channel" in msg for msg in issues)

    # 7. Absent education fails
    p_no_edu = dict(p11)
    p_no_edu["education_status"] = {
        "declaration_state": "ABSENT",
        "status_stated": None,
        "degree_level": None,
        "field_of_study": None,
        "institution": None,
        "is_verified": False,
    }
    is_valid, issues = validate_candidate_profile(p_no_edu)
    assert is_valid is False
    assert any("Invalid or absent education declaration state" in msg for msg in issues)


def test_career_starter_zero_experience_zero_projects_zero_skills_is_valid():
    """Verify a career starter with valid name, contact, education declaration, but 0 exp, 0 proj, 0 skills passes."""
    career_starter_profile = {
        "profile_id": "P_career_starter_minimal",
        "name": "Alex Mercer",
        "contact_info": {
            "email": "alex.mercer@example.invalid",
            "phone": None,
            "location": "Bengaluru, India",
        },
        "education_status": {
            "declaration_state": "DECLARED_NO_FORMAL_EDUCATION",
            "status_stated": "No formal degree or university education declared; career starter",
            "degree_level": None,
            "field_of_study": None,
            "institution": None,
            "is_verified": False,
        },
        "is_complete_profile": True,
        "incompleteness_reason": None,
        "experience": [],
        "projects": [],
        "skills": [],
        "certifications": [],
    }

    is_valid, issues = validate_candidate_profile(career_starter_profile)
    assert is_valid is True, f"Career starter validation failed unexpectedly: {issues}"
    assert issues == []


def test_career_starter_enters_ordinary_matching_without_blocking_by_optional_fields():
    """Verify career-starter profile enters ordinary matching entry point without optional-field blocking.

    Owner Requirement (Gate 1):
    A valid career-starter profile with:
    - valid name,
    - valid contact channel,
    - declared education status (including declared no formal degree / self-taught),
    - empty experience [],
    - empty projects [],
    - empty skills [],
    must be admitted into ordinary matching (assess_job_match) without being blocked,
    halted, or rejected by optional-field completeness checks.
    """
    career_starter_profile = {
        "profile_id": "P_career_starter_match",
        "name": "Pooja Patel",
        "contact_info": {
            "email": "pooja.patel@example.invalid",
            "phone": "+91-98765-01001",
            "location": "Bengaluru, Karnataka, India",
        },
        "education_status": {
            "declaration_state": "DECLARED_SELF_TAUGHT",
            "status_stated": "Self-taught programmer; no formal degree",
            "degree_level": None,
            "field_of_study": None,
            "institution": None,
            "is_verified": False,
        },
        "is_complete_profile": True,
        "incompleteness_reason": None,
        "experience": [],
        "projects": [],
        "skills": [],
        "certifications": [],
    }

    # 1. Profile completeness gate accepts career starter
    is_valid, issues = validate_candidate_profile(career_starter_profile)
    assert is_valid is True
    assert issues == []

    # 2. Ingest into ordinary matching entry point (assess_job_match) with empty evidence
    job_lists = [
        {
            "header": "Required Qualifications",
            "items": ["Proficiency in Python programming", "Basic SQL knowledge"],
        },
        {
            "header": "Preferred Qualifications",
            "items": ["Familiarity with FastAPI"],
        },
    ]

    # Candidate has empty evidence (zero experience, zero projects, zero skills)
    empty_evidence: list[CandidateEvidenceItem] = []

    assessment = assess_job_match(
        posting_id="job_career_starter_test",
        snapshot_id="snap_cs_01",
        lists_json=job_lists,
        description_plain="Software Engineer posting for career starter evaluation",
        workplace_type="remote",
        location="Bengaluru, India",
        candidate_evidence=empty_evidence,
    )

    # Assert matching completes deterministically without throwing or halting
    assert isinstance(assessment, JobMatchAssessment)
    assert assessment.id is not None
    assert assessment.fit_tier == FitTier.INSUFFICIENT_DATA
    assert assessment.confidence_level == ConfidenceLevel.LOW
    assert "Candidate evidence profile is empty" in assessment.scores.calculation_basis
    assert len(assessment.qualification_gaps) >= 2

    # 3. Test with declared education represented as evidence item
    edu_evidence = [
        CandidateEvidenceItem(
            fact_id="fact_edu_self_taught",
            fact_type=FactType.EDUCATION.value,
            value={
                "credential": "Self-taught",
                "declaration_state": "DECLARED_SELF_TAUGHT",
            },
            verification_state=FactVerificationState.DOCUMENT_SUPPORTED.value,
            is_active=True,
            is_conflicted=False,
            provenance=[],
        )
    ]
    assessment_with_edu = assess_job_match(
        posting_id="job_career_starter_test",
        snapshot_id="snap_cs_02",
        lists_json=job_lists,
        description_plain="Software Engineer posting for career starter evaluation",
        workplace_type="remote",
        location="Bengaluru, India",
        candidate_evidence=edu_evidence,
    )
    assert isinstance(assessment_with_edu, JobMatchAssessment)
    assert assessment_with_edu.fit_tier in {FitTier.WEAK_MATCH, FitTier.INSUFFICIENT_DATA}
    assert assessment_with_edu.confidence_level in {
        ConfidenceLevel.HIGH,
        ConfidenceLevel.MEDIUM,
        ConfidenceLevel.LOW,
    }


def test_contact_validation_precision_supplied_vs_syntactic_vs_verified():
    """Verify contact validation distinguishes supplied, basic syntactic format, and verified deliverability."""
    # 1. Offline phone validation rule unit checks
    # Valid phone formats (basic telecom formatting: optional +, digits, delimiters, 7-20 chars, >=7 digits)
    assert is_valid_offline_phone("+91-98765-01001") is True
    assert is_valid_offline_phone("+1-555-010-9999") is True
    assert is_valid_offline_phone("(555) 010-9999") is True
    assert is_valid_offline_phone("9876543210") is True
    assert is_valid_offline_phone("+44 20 7946 0991") is True
    assert is_valid_offline_phone("1234567") is True

    # Invalid phone formats (non-empty string is NOT equated with syntactic validity)
    assert is_valid_offline_phone("not-a-phone") is False
    assert is_valid_offline_phone("phone-number-here") is False
    assert is_valid_offline_phone("123") is False  # Too short (< 7 digits)
    assert is_valid_offline_phone("   ") is False  # Whitespace only
    assert is_valid_offline_phone("") is False
    assert is_valid_offline_phone(None) is False
    assert is_valid_offline_phone("123456789012345678901") is False  # Length 21 > 20
    assert is_valid_offline_phone("++1234567890") is False  # Duplicate plus
    assert is_valid_offline_phone("123-456-7890-ext12") is False  # Letters in extension

    # 2. Offline email validation rule unit checks
    assert is_valid_offline_email("candidate@example.invalid") is True
    assert is_valid_offline_email("user.name@sub.domain.example.com") is True
    assert is_valid_offline_email("not-an-email") is False
    assert is_valid_offline_email("missing_at_symbol.com") is False
    assert is_valid_offline_email("user@nodot") is False
    assert is_valid_offline_email("   ") is False
    assert is_valid_offline_email("") is False
    assert is_valid_offline_email(None) is False

    base_profile = {
        "profile_id": "P_test_contact",
        "name": "Test Candidate",
        "education_status": {
            "declaration_state": "DECLARED_SELF_TAUGHT",
            "status_stated": "Self-taught",
            "degree_level": None,
            "field_of_study": None,
            "institution": None,
            "is_verified": False,
        },
        "experience": [],
        "projects": [],
        "skills": [],
        "certifications": [],
    }

    # 3. Syntactically valid email alone passes (no phone required; mailbox existence not verified offline)
    p_email_only = dict(base_profile)
    p_email_only["contact_info"] = {
        "email": "candidate@example.invalid",
        "phone": None,
        "location": "Hyderabad, India",
    }
    is_valid, issues = validate_candidate_profile(p_email_only)
    assert is_valid is True
    assert issues == []

    # 4. Syntactically valid phone alone passes (no email required; reachability not verified offline)
    p_phone_only = dict(base_profile)
    p_phone_only["contact_info"] = {
        "email": None,
        "phone": "+91-98765-01001",
        "location": "Hyderabad, India",
    }
    is_valid, issues = validate_candidate_profile(p_phone_only)
    assert is_valid is True
    assert issues == []

    # 5. Non-empty but syntactically invalid phone fails (not equated with syntactic validity)
    p_junk_phone = dict(base_profile)
    p_junk_phone["contact_info"] = {
        "email": None,
        "phone": "not-a-phone",
        "location": "Hyderabad, India",
    }
    is_valid, issues = validate_candidate_profile(p_junk_phone)
    assert is_valid is False
    assert any("Missing contact channel" in msg for msg in issues)

    # 6. Short digit-only string (< 7 digits) fails phone syntactic check
    p_short_phone = dict(base_profile)
    p_short_phone["contact_info"] = {
        "email": None,
        "phone": "123",
        "location": "Hyderabad, India",
    }
    is_valid, issues = validate_candidate_profile(p_short_phone)
    assert is_valid is False
    assert any("Missing contact channel" in msg for msg in issues)

    # 7. Malformed email string (missing domain dot / @) without phone fails syntactic validation
    p_bad_email = dict(base_profile)
    p_bad_email["contact_info"] = {
        "email": "not-an-email-address",
        "phone": None,
        "location": "Hyderabad, India",
    }
    is_valid, issues = validate_candidate_profile(p_bad_email)
    assert is_valid is False
    assert any("Missing contact channel" in msg for msg in issues)

    # 8. Whitespace-only phone without email fails syntactic validation
    p_blank_phone = dict(base_profile)
    p_blank_phone["contact_info"] = {
        "email": None,
        "phone": "   ",
        "location": "Hyderabad, India",
    }
    is_valid, issues = validate_candidate_profile(p_blank_phone)
    assert is_valid is False
    assert any("Missing contact channel" in msg for msg in issues)


def test_commission_only_vs_unpaid_work_distinction():
    """Verify commission-only role (J_froz_14) is separated from unpaid work (J_froz_05)."""
    commission_job = load_job_posting("J_froz_14", FIXTURES_ROOT)
    comp = commission_job["compensation"]
    assert comp["compensation_structure"] == "COMMISSION_ONLY"
    assert comp["is_explicitly_unpaid"] is False
    assert comp["guaranteed_base"] == 0.0
    assert "NO_GUARANTEED_BASE" in comp["uncertainty_flags"]
    assert "VARIABLE_COMMISSION_STRUCTURE" in comp["uncertainty_flags"]

    unpaid_job = load_job_posting("J_froz_05", FIXTURES_ROOT)
    unpaid_comp = unpaid_job["compensation"]
    assert unpaid_comp["is_explicitly_unpaid"] is True
    assert unpaid_comp["amount_min"] == 0.0

    # Verify case rw_froz_014 tests commission-only handling
    case_14 = load_unlabeled_case("rw_froz_014", FIXTURES_ROOT)
    assert case_14["job_posting"]["posting_id"] == "J_froz_14"
    assert "commission-only" in case_14["intended_evaluation_purpose"]


def test_credential_vs_experience_separation():
    """Verify J_froz_09 separates employer-mandated ISO 13485 certification from 10y experience."""
    job = load_job_posting("J_froz_09", FIXTURES_ROOT)
    reqs = job["requirements"]
    mandatory = reqs["mandatory_constraints"]
    assert any("ISO 13485 Lead Auditor Certification" in c for c in mandatory)
    assert any("Employer Mandated" in c for c in mandatory)
    assert not any("10+" in c for c in mandatory)
    assert reqs["experience_years_requested"] == 10


def test_statutory_license_jurisdiction_accuracy():
    """Verify J_froz_18 in Mumbai mandates SEBI NISM Series VIII specifically for approved users."""
    job = load_job_posting("J_froz_18", FIXTURES_ROOT)
    mandatory = job["requirements"]["mandatory_constraints"]
    assert any("NISM Series VIII" in c and "SEBI" in c for c in mandatory)
    assert any("Approved Users" in c for c in mandatory)
    assert not any("FINRA" in c for c in mandatory)
    # Check that description cites the approved-user scope under SEBI / NISM circular
    assert "associated persons functioning as approved users" in job["description_plain"]


def test_nnmc_act_2023_nursing_licence_framework():
    """Verify J_froz_04 and P_froz_02 reference operative State Nursing Council registration under Gazette S.O. 991(E)."""
    job = load_job_posting("J_froz_04", FIXTURES_ROOT)
    mandatory = job["requirements"]["mandatory_constraints"]
    assert any("State Nursing Council" in c for c in mandatory)
    assert any("S.O. 991(E)" in c for c in mandatory)

    profile = load_candidate_profile("P_froz_02", FIXTURES_ROOT)
    assert any("State Nursing Council Registration" in c for c in profile["certifications"])
    assert any("NNMC Act 2023 Sec 56(5)" in c for c in profile["certifications"])


def test_japan_work_authorization_employer_policy():
    """Verify J_froz_03 distinguishes location preference from employer no-sponsorship policy."""
    job = load_job_posting("J_froz_03", FIXTURES_ROOT)
    mandatory = job["requirements"]["mandatory_constraints"]
    assert any("Employer Location Policy" in c for c in mandatory)
    assert any("Employer No-Visa-Sponsorship Policy" in c for c in mandatory)
    assert "does not provide visa sponsorship or Certificate of Eligibility (COE)" in job["description_plain"]


def test_unsupported_factual_claim_zero_tolerance():
    """Verify zero tolerance for unsupported facts: all evidence facts have explicit statements and verified states."""
    for p_file in FIXTURES_ROOT.glob("profiles/**/*.json"):
        with open(p_file, encoding="utf-8") as f:
            p = json.load(f)
        for fact in p.get("evidence_facts", []):
            assert "statement" in fact and fact["statement"].strip() != ""
            assert fact.get("verification_state") in {
                "VERIFIED_BY_USER",
                "DECLARED_BY_USER",
                "DOCUMENT_EXTRACTED",
                "UNVERIFIED",
            }


def test_decision_1_and_3_incomplete_candidate_profiles_coverage():
    """Verify 10 distinct incomplete candidate profiles testing required fields."""
    incomplete_profile_ids = [f"P_froz_inc_{i:02d}" for i in range(1, 11)]

    for pid in incomplete_profile_ids:
        profile = load_candidate_profile(pid, FIXTURES_ROOT)
        assert profile["is_complete_profile"] is False
        assert profile["incompleteness_reason"] is not None
        assert len(profile["incompleteness_reason"]) > 10

    # P_froz_inc_01 is completely empty
    p1 = load_candidate_profile("P_froz_inc_01", FIXTURES_ROOT)
    assert p1["name"] is None
    assert p1["contact_info"] is None
    assert p1["education_status"] is None

    # P_froz_inc_02 lacks name
    p2 = load_candidate_profile("P_froz_inc_02", FIXTURES_ROOT)
    assert p2["name"] is None
    assert p2["contact_info"] is not None

    # P_froz_inc_03 lacks contact
    p3 = load_candidate_profile("P_froz_inc_03", FIXTURES_ROOT)
    assert p3["name"] is not None
    assert p3["contact_info"] is None

    # P_froz_inc_04 lacks education
    p4 = load_candidate_profile("P_froz_inc_04", FIXTURES_ROOT)
    assert p4["education_status"] is None


def test_decision_1_and_3_incomplete_job_postings_coverage():
    """Verify 10 distinct incomplete/truncated job postings in frozen partition."""
    incomplete_posting_ids = [f"J_froz_{i:02d}" for i in range(19, 29)]
    assert len(incomplete_posting_ids) == 10

    for jid in incomplete_posting_ids:
        posting = load_job_posting(jid, FIXTURES_ROOT)
        assert posting["completeness_status"] in {"INCOMPLETE_STUB", "MALFORMED"}
        assert posting["incompleteness_reason"] is not None


def test_decision_2_and_4_blinding_and_answer_segregation():
    """Verify case fixtures contain zero ground-truth labels or predictions."""
    res = verify_blinding_and_segregation(FIXTURES_ROOT)
    assert res["scanned_cases"] == 92
    assert res["violations"] == 0

    # Verify ground-truth scaffolding is marked pending Task 8.2
    for scaf_name in ["frozen_ground_truth_scaffolding.json", "calibration_ground_truth_scaffolding.json"]:
        scaffolding_path = FIXTURES_ROOT / "ground_truth" / scaf_name
        with open(scaffolding_path, encoding="utf-8") as f:
            scaffolding = json.load(f)

        assert scaffolding["governance_status"] == "PENDING_TASK_8_2_ADJUDICATION"
        for record in scaffolding["records"]:
            assert record["adjudication_status"] == "PENDING_TASK_8_2_ADJUDICATION"
            assert record["human_suitability_label"] is None
            assert record["target_system_tier"] is None
            assert record["target_submission_eligible"] is None


def test_decision_5_zero_real_pii_and_rfc2606_compliance():
    """Verify zero real PII across all 41 profile fixtures."""
    res = verify_zero_pii(FIXTURES_ROOT)
    assert res["scanned_profiles"] == 41
    assert res["pii_violations"] == 0


def test_decision_3_and_5_occupational_diversity():
    """Verify multi-industry representation across non-tech domains."""
    manifest = load_manifest(FIXTURES_ROOT)
    domains = manifest["coverage_summary"]["occupational_domains"]

    expected_domains = {
        "Corporate Finance & Treasury",
        "Healthcare & Clinical Nursing",
        "B2B Enterprise Software Sales",
        "Operations & Supply Chain Logistics",
        "Education & Instructional Design",
        "Mechanical & Manufacturing Engineering",
        "Cloud Software & Systems Engineering",
        "Customer Support & Client Advocacy",
        "Human Resources & Talent Acquisition",
        "Growth Marketing & Analytics",
        "Entry-Level Office Administration",
    }
    assert expected_domains.issubset(set(domains))


def test_partition_isolation_zero_overlap():
    """Verify complete physical and identifier isolation between calibration and frozen sets."""
    calib_cases = [
        load_unlabeled_case(f"rw_calib_{i:03d}", FIXTURES_ROOT) for i in range(1, 21)
    ]
    frozen_cases = [
        load_unlabeled_case(f"rw_froz_{i:03d}", FIXTURES_ROOT) for i in range(1, 61)
    ]

    calib_emps = {c["employer_id"] for c in calib_cases}
    frozen_emps = {c["employer_id"] for c in frozen_cases}
    assert calib_emps.isdisjoint(frozen_emps)

    calib_profiles = {c["candidate_profile_id"] for c in calib_cases}
    frozen_profiles = {c["candidate_profile_id"] for c in frozen_cases}
    assert calib_profiles.isdisjoint(frozen_profiles)

    calib_postings = {c["job_posting"]["posting_id"] for c in calib_cases}
    frozen_postings = {c["job_posting"]["posting_id"] for c in frozen_cases}
    assert calib_postings.isdisjoint(frozen_postings)


def test_case_mapping_consistency_and_profile_completeness_boundaries():
    """Verify machine-readable case mapping matches all 92 disk cases and validates boundaries."""
    mapping_path = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "docs"
        / "real-world-job-quality-evaluation-case-mapping.json"
    )
    assert mapping_path.is_file(), f"Case mapping missing at {mapping_path}"

    with open(mapping_path, encoding="utf-8") as f:
        mapping = json.load(f)

    assert mapping["total_cases"] == 92
    assert mapping["partitions"]["frozen_benchmark_cases"] == 60
    assert mapping["partitions"]["calibration_cases"] == 20
    assert mapping["partitions"]["adversarial_regression_cases"] == 12

    for entry in mapping["cases"]:
        cid = entry["case_id"]
        case = load_unlabeled_case(cid, FIXTURES_ROOT)
        p = case["candidate_profile"]
        j = case["job_posting"]

        assert entry["candidate_profile_id"] == p["profile_id"]
        assert entry["job_posting_id"] == j["posting_id"]

        is_valid, issues = validate_candidate_profile(p)
        if entry["candidate_required_profile_completeness"] == "INCOMPLETE":
            # Incomplete required profile cannot enter ordinary matching
            assert is_valid is False
            assert len(issues) > 0
        else:
            # Complete candidate (including career starter with 0 exp/projects) is valid
            assert is_valid is True

        if entry["job_posting_completeness"] != "COMPLETE":
            assert j["completeness_status"] in {"INCOMPLETE_STUB", "MALFORMED"}
            # Purpose must emphasize cautious assessment / disclosure, not automatic rejection
            purpose = entry["intended_test_purpose"]
            assert any(
                phrase in purpose
                for phrase in [
                    "without automatic candidate rejection",
                    "without asserting candidate failure",
                    "without declaring job ineligible",
                    "rather than fabricating requirements",
                    "rather than candidate failure",
                    "without phantom requirement synthesis",
                    "rather than assuming failure",
                    "without rejecting candidate",
                    "without candidate rejection",
                    "rather than false match or false failure",
                ]
            )
