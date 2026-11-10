"""Unit tests for the Blinded Evaluation Serializer (Task 8.2 Checkpoint A).

Verifies:
1. Strict field allowlist enforcement (zero leakage of prohibited ground-truth or internal keys).
2. Deterministic, reproducible output (canonical ordering of lists and dictionaries).
3. Rejection / dropping of un-whitelisted attributes.
4. Exclusion of raw PII contact channels from the model-facing payload.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from backend.app.evaluation.blinded_serializer import (
    BlindedCasePayload,
    BlindedEvaluationSerializer,
    PROHIBITED_LEAKAGE_KEYS,
)
from backend.app.evaluation.real_world_dataset import load_unlabeled_case


def test_prohibited_keys_are_strictly_defined() -> None:
    """Ensure standard ground-truth, matching score, and label keys are in prohibited set."""
    expected_prohibited = {
        "human_suitability",
        "human_suitability_label",
        "target_system_tier",
        "target_submission_eligible",
        "adjudication_notes",
        "owner_adjudication_notes",
        "expected_fit_tier",
        "expected_required_met",
        "match_score",
        "fit_score",
        "evaluator_role",
    }
    assert expected_prohibited.issubset(PROHIBITED_LEAKAGE_KEYS)


def test_blinded_serializer_calibration_fixture() -> None:
    """Test serialization of a real calibration case fixture."""
    raw_case = load_unlabeled_case("rw_calib_001")
    serializer = BlindedEvaluationSerializer()

    payload: BlindedCasePayload = serializer.serialize(raw_case)
    payload_dict = payload.model_dump()

    # 1. Verify case_id is preserved
    assert payload.case_id == "rw_calib_001"

    # 2. Verify allowed job posting fields
    assert payload.job_posting.title == "Retail Inventory Supervisor"
    assert payload.job_posting.workplace_type == "on_site"
    assert payload.job_posting.location == "Indore, India"
    assert payload.job_posting.compensation is not None
    assert payload.job_posting.compensation.currency == "INR"

    # 3. Verify allowed candidate profile fields (with candidate name pseudonymized)
    assert payload.candidate_profile.name == "[CANDIDATE_NAME]"
    assert payload.candidate_profile.education_status.declaration_state == "DECLARED_VERIFIED"
    assert len(payload.candidate_profile.experience) >= 1
    assert "Retail Inventory" in payload.candidate_profile.skills

    # 4. Verify no prohibited keys or cleartext candidate name leak anywhere into the payload dictionary
    serialized_str = json.dumps(payload_dict)
    assert "Rohit Malviya" not in serialized_str
    for key in PROHIBITED_LEAKAGE_KEYS:
        assert f'"{key}"' not in serialized_str, f"Prohibited key '{key}' found in serialized payload!"

    # 5. Verify internal identifiers and contact channels are excluded
    assert "employer_id" not in payload_dict["job_posting"]
    assert "candidate_profile_id" not in payload_dict
    assert "contact_info" not in payload_dict["candidate_profile"]


def test_blinded_serializer_drops_arbitrary_unwhitelisted_keys() -> None:
    """Ensure arbitrary injected fields (e.g. leaked scores or labels) are strictly ignored."""
    raw_case: dict[str, Any] = {
        "case_id": "test_case_999",
        "target_system_tier": "TIER_1",  # Prohibited
        "human_suitability": "GOOD_FIT",  # Prohibited
        "unauthorized_secret": "do_not_leak",  # Un-whitelisted
        "job_posting": {
            "title": "Software Engineer",
            "workplace_type": "remote",
            "location": "Remote",
            "description_plain": "Build clean backend systems in Python.",
            "secret_score": 0.99,  # Un-whitelisted
            "requirements": {
                "mandatory_constraints": ["Python 3.12"],
                "core_competencies": ["FastAPI", "PostgreSQL", "Docker"],
                "preferred_qualifications": ["AWS"],
                "experience_years_requested": 4,
            },
            "compensation": {
                "currency": "USD",
                "amount_min": 120000.0,
                "amount_max": 140000.0,
                "period": "YEAR",
                "compensation_structure": "SALARIED",
                "guaranteed_base": 120000.0,
                "is_disclosed": True,
                "is_explicitly_unpaid": False,
            },
        },
        "candidate_profile": {
            "name": "Alex Taylor",
            "contact_info": {
                "email": "alex@example.invalid",
                "phone": "+1-555-0199",
            },
            "education_status": {
                "declaration_state": "DECLARED_VERIFIED",
                "status_stated": "B.S. Computer Science",
                "degree_level": "Bachelor",
                "field_of_study": "Computer Science",
            },
            "experience": [
                {
                    "title": "Backend Dev",
                    "employer": "Tech Corp",
                    "years": 4.0,
                    "description": "Developed APIs.",
                }
            ],
            "skills": ["PostgreSQL", "Docker", "FastAPI"],
            "certifications": [],
            "evidence_facts": [],
        },
    }

    serializer = BlindedEvaluationSerializer()
    payload = serializer.serialize(raw_case)
    payload_dict = payload.model_dump()
    serialized_str = json.dumps(payload_dict)

    assert "target_system_tier" not in serialized_str
    assert "human_suitability" not in serialized_str
    assert "unauthorized_secret" not in serialized_str
    assert "secret_score" not in serialized_str
    assert "alex@example.invalid" not in serialized_str


def test_blinded_serializer_deterministic_ordering() -> None:
    """Verify deterministic ordering of lists (e.g. skills, competencies)."""
    raw_case_1: dict[str, Any] = {
        "case_id": "det_case_001",
        "job_posting": {
            "title": "Engineer",
            "workplace_type": "remote",
            "location": "Global",
            "description_plain": "Test determinism",
            "requirements": {
                "mandatory_constraints": ["Constraint B", "Constraint A"],
                "core_competencies": ["Skill Z", "Skill A", "Skill M"],
                "preferred_qualifications": ["Pref 2", "Pref 1"],
                "experience_years_requested": 2,
            },
        },
        "candidate_profile": {
            "name": "Jane Doe",
            "education_status": {"declaration_state": "DECLARED_NONE"},
            "skills": ["Zsh", "Bash", "Python", "Awk"],
            "experience": [],
            "certifications": [],
            "evidence_facts": [],
        },
    }

    raw_case_2: dict[str, Any] = {
        "case_id": "det_case_001",
        "job_posting": {
            "title": "Engineer",
            "workplace_type": "remote",
            "location": "Global",
            "description_plain": "Test determinism",
            "requirements": {
                "mandatory_constraints": ["Constraint A", "Constraint B"],
                "core_competencies": ["Skill M", "Skill Z", "Skill A"],
                "preferred_qualifications": ["Pref 1", "Pref 2"],
                "experience_years_requested": 2,
            },
        },
        "candidate_profile": {
            "name": "Jane Doe",
            "education_status": {"declaration_state": "DECLARED_NONE"},
            "skills": ["Python", "Awk", "Zsh", "Bash"],
            "experience": [],
            "certifications": [],
            "evidence_facts": [],
        },
    }

    serializer = BlindedEvaluationSerializer()
    json1 = serializer.to_canonical_json(raw_case_1)
    json2 = serializer.to_canonical_json(raw_case_2)

    assert json1 == json2
    # Verify sorted items in output
    parsed = json.loads(json1)
    assert parsed["candidate_profile"]["skills"] == ["Awk", "Bash", "Python", "Zsh"]
    assert parsed["job_posting"]["requirements"]["core_competencies"] == ["Skill A", "Skill M", "Skill Z"]


def test_blinded_serializer_all_92_dataset_fixtures() -> None:
    """Verify that all 92 cases (frozen, calibration, adversarial) serialize cleanly."""
    from backend.app.evaluation.real_world_dataset import FIXTURES_ROOT

    serializer = BlindedEvaluationSerializer()
    count = 0

    for case_file in FIXTURES_ROOT.glob("cases/**/*.json"):
        with open(case_file, encoding="utf-8") as f:
            raw = json.load(f)
        payload = serializer.serialize(raw)
        assert payload.case_id == raw["case_id"]
        assert payload.job_posting.title
        count += 1

    for adv_file in FIXTURES_ROOT.glob("adversarial/*.json"):
        with open(adv_file, encoding="utf-8") as f:
            raw = json.load(f)
        payload = serializer.serialize(raw)
        assert payload.case_id == raw["case_id"]
        assert payload.job_posting.title
        count += 1

    assert count == 92, f"Expected 92 fixtures serialized, got {count}"

