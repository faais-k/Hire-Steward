"""Comprehensive regression tests for Section-Scoped Citation Resolution (Task 8.2 Checkpoint A).

Covers all 10 required regression cases using actual synthetic fixtures (rw_calib_001):
1. Job-description citation beginning at offset zero.
2. Candidate-evidence citation beginning at offset zero.
3. Experience-description citation.
4. Identical phrase appearing in two different sections.
5. Identical phrase appearing multiple times in one section.
6. Ambiguous short citations.
7. Citation coordinates crossing a section boundary.
8. Citation referencing an unknown section.
9. Unicode text and displacement after PII masking.
10. Exact, fuzzy and unresolved citation confidence.
"""

from __future__ import annotations

import json
from backend.app.evaluation.blinded_serializer import BlindedEvaluationSerializer
from backend.app.evaluation.real_world_dataset import load_unlabeled_case
from backend.app.evaluation.pii_mapper import PIICoordinateMapper, SectionMaskingRegistry


def test_1_job_description_citation_beginning_at_offset_zero() -> None:
    """Job-description citation beginning at offset zero resolves cleanly against description_plain."""
    serializer = BlindedEvaluationSerializer()
    raw_case = load_unlabeled_case("rw_calib_001")
    payload = serializer.serialize(raw_case)

    # In rw_calib_001, description_plain begins with:
    # "Supervise stock reconciliation, point-of-sale inventory audits..."
    desc = payload.job_posting.description_plain
    quote = "Supervise stock reconciliation"
    assert desc.startswith(quote)

    res = payload.masking_result.resolve_citation(
        citation_text=quote,
        payload_start=0,
        payload_end=len(quote),
        source_section="job_posting.description_plain",
    )

    assert res.status == "EXACT_MATCH"
    assert res.confidence == "HIGH"
    assert res.orig_start == 0
    assert res.orig_end == len(quote)
    assert res.resolved_text == quote


def test_2_candidate_evidence_citation_beginning_at_offset_zero() -> None:
    """Candidate-evidence citation beginning at offset zero resolves against candidate evidence."""
    serializer = BlindedEvaluationSerializer()
    raw_case = load_unlabeled_case("rw_calib_001")
    payload = serializer.serialize(raw_case)

    # In rw_calib_001, evidence_facts[0].statement is:
    # "[CANDIDATE_NAME] exhibits verified background in Retail Inventory."
    fact_stmt = payload.candidate_profile.evidence_facts[0].statement
    # Quote from offset zero of this statement
    quote = "[CANDIDATE_NAME] exhibits verified background"
    assert fact_stmt.startswith(quote)

    res = payload.masking_result.resolve_citation(
        citation_text=quote,
        payload_start=0,
        payload_end=len(quote),
        source_section="candidate_profile.evidence_facts[0].statement",
    )

    assert res.status == "EXACT_MATCH"
    assert res.confidence == "HIGH"
    assert res.orig_start == 0
    # Original unmasked statement starts with "Rohit Malviya exhibits verified background"
    raw_fact = raw_case["candidate_profile"]["evidence_facts"][0]["statement"]
    expected_orig_slice = "Rohit Malviya exhibits verified background"
    assert raw_fact.startswith(expected_orig_slice)
    assert res.resolved_text == expected_orig_slice
    assert res.orig_end == len(expected_orig_slice)


def test_3_experience_description_citation() -> None:
    """Experience-description citation resolves against candidate_profile.experience."""
    serializer = BlindedEvaluationSerializer()
    raw_case = load_unlabeled_case("rw_calib_001")
    payload = serializer.serialize(raw_case)

    # In rw_calib_001, experience[0].description is:
    # "Maintained point-of-sale inventory and supplier delivery logs."
    exp_desc = payload.candidate_profile.experience[0].description
    assert exp_desc is not None
    quote = "point-of-sale inventory and supplier delivery logs"
    start = exp_desc.index(quote)
    end = start + len(quote)

    res = payload.masking_result.resolve_citation(
        citation_text=quote,
        payload_start=start,
        payload_end=end,
        source_section="candidate_profile.experience[0].description",
    )

    assert res.status == "EXACT_MATCH"
    assert res.confidence == "HIGH"
    assert res.resolved_text == quote
    assert exp_desc[res.orig_start : res.orig_end] == quote


def test_4_identical_phrase_in_two_different_sections_does_not_leak() -> None:
    """Phrase 'Retail Inventory' exists in both requirements and evidence_facts; scoping isolates matches."""
    serializer = BlindedEvaluationSerializer()
    raw_case = load_unlabeled_case("rw_calib_001")
    payload = serializer.serialize(raw_case)

    target_phrase = "Retail Inventory"

    # 1. Resolve against requirements
    req_res = payload.masking_result.resolve_citation(
        citation_text=target_phrase,
        payload_start=0,
        payload_end=len(target_phrase),
        source_section="job_posting.requirements.core_competencies",
    )
    # In core_competencies (sorted: POS Systems\nRetail Inventory\nStock Reconciliation)
    # Retail Inventory starts at index 12
    # With payload_start=0, it is within window_slack=50 of index 12, so it fuzzy recovers within requirements:
    assert req_res.status == "FUZZY_RECOVERED"
    assert req_res.confidence == "LOWER_CONFIDENCE"
    assert req_res.orig_start == 12  # Position within requirements!

    # 2. Resolve against candidate evidence fact statement
    fact_stmt = payload.candidate_profile.evidence_facts[0].statement
    fact_start = fact_stmt.index(target_phrase)
    fact_end = fact_start + len(target_phrase)

    fact_res = payload.masking_result.resolve_citation(
        citation_text=target_phrase,
        payload_start=fact_start,
        payload_end=fact_end,
        source_section="candidate_profile.evidence_facts[0].statement",
    )
    assert fact_res.status == "EXACT_MATCH"
    assert fact_res.confidence == "HIGH"
    # Points to position within raw statement
    raw_stmt = raw_case["candidate_profile"]["evidence_facts"][0]["statement"]
    assert raw_stmt[fact_res.orig_start : fact_res.orig_end] == target_phrase

    # 3. If model asks for fact_start in requirements section, it is outside requirements window and rejected!
    cross_res = payload.masking_result.resolve_citation(
        citation_text=target_phrase,
        payload_start=fact_start + 200,  # Far outside requirements
        payload_end=fact_end + 200,
        source_section="job_posting.requirements.core_competencies",
    )
    assert cross_res.status == "REJECTED_UNRESOLVED"
    assert cross_res.confidence == "ZERO"


def test_5_identical_phrase_multiple_times_in_one_section() -> None:
    """Multiple occurrences in one section disambiguate by coordinates; drifted ambiguous matches reject."""
    mapper = PIICoordinateMapper()
    text = "Audit inventory procedures. Daily inventory checks ensure accurate inventory records."
    # 'inventory' appears 3 times: indices 6, 34, 69
    mask_res = mapper.mask_text(text)

    reg = SectionMaskingRegistry()
    reg.register_section("test_section", mask_res)

    # Exact match for occurrence 1 (index 6..15)
    r1 = reg.resolve_citation("inventory", 6, 15, source_section="test_section")
    assert r1.status == "EXACT_MATCH"
    assert r1.confidence == "HIGH"
    assert r1.orig_start == 6

    # Exact match for occurrence 2 (index 34..43)
    r2 = reg.resolve_citation("inventory", 34, 43, source_section="test_section")
    assert r2.status == "EXACT_MATCH"
    assert r2.confidence == "HIGH"
    assert r2.orig_start == 34

    # Drifted coordinate equidistant between occurrence 1 and 2 (e.g. index 20) where both appear in +-50 window
    r_ambig = reg.resolve_citation("inventory", 20, 29, source_section="test_section", window_slack=50)
    # Because multiple occurrences fall inside +-50 window, it cannot be uniquely resolved
    assert r_ambig.status == "REJECTED_UNRESOLVED"
    assert r_ambig.confidence == "ZERO"


def test_6_ambiguous_short_citations_rejected() -> None:
    """Short ubiquitous words with multiple nearby occurrences reject rather than guessing."""
    mapper = PIICoordinateMapper()
    text = "In an effort to be in an agile environment in tech."
    mask_res = mapper.mask_text(text)
    reg = SectionMaskingRegistry()
    reg.register_section("body", mask_res)

    # Word 'in' at index 0..2
    r_exact = reg.resolve_citation("In", 0, 2, source_section="body")
    assert r_exact.status == "EXACT_MATCH"
    assert r_exact.confidence == "HIGH"

    # Drifted coordinate to offset 10 where 'in' appears again at index 19 and 43 within +-50 window:
    r_short = reg.resolve_citation("in", 10, 12, source_section="body", window_slack=50)
    assert r_short.status == "REJECTED_UNRESOLVED"
    assert r_short.confidence == "ZERO"


def test_7_citation_coordinates_crossing_section_boundaries_rejected() -> None:
    """Citation with coordinates outside the section's length cannot match text from other sections."""
    serializer = BlindedEvaluationSerializer()
    raw_case = load_unlabeled_case("rw_calib_001")
    payload = serializer.serialize(raw_case)

    # Attempt to cite text with coordinates way past the length of requirements
    req_len = len("\n".join(payload.job_posting.requirements.core_competencies))
    res = payload.masking_result.resolve_citation(
        citation_text="Supervise stock reconciliation",
        payload_start=req_len + 500,
        payload_end=req_len + 530,
        source_section="job_posting.requirements.core_competencies",
    )
    assert res.status == "REJECTED_UNRESOLVED"
    assert res.confidence == "ZERO"


def test_8_citation_referencing_unknown_section_rejected() -> None:
    """Citations with missing, None, or unrecognized source_section reject immediately."""
    serializer = BlindedEvaluationSerializer()
    raw_case = load_unlabeled_case("rw_calib_001")
    payload = serializer.serialize(raw_case)

    # 1. Missing / None source_section
    r_none = payload.masking_result.resolve_citation(
        citation_text="POS Systems",
        payload_start=0,
        payload_end=11,
        source_section=None,
    )
    assert r_none.status == "REJECTED_UNRESOLVED"
    assert r_none.confidence == "ZERO"
    assert "Unknown or missing source_section" in (r_none.reason or "")

    # 2. Unknown section identifier
    r_unknown = payload.masking_result.resolve_citation(
        citation_text="POS Systems",
        payload_start=0,
        payload_end=11,
        source_section="job_posting.salary_notes_external",
    )
    assert r_unknown.status == "REJECTED_UNRESOLVED"
    assert r_unknown.confidence == "ZERO"
    assert "Unknown or missing source_section" in (r_unknown.reason or "")


def test_9_unicode_normalization_and_displacement_after_pii_masking() -> None:
    """Unicode text with precomposed vs decomposed forms and PII displacement resolves accurately."""
    mapper = PIICoordinateMapper()
    # Decomposed e + combining acute: 'e\u0301'
    raw_text = "Re\u0301sume\u0301 of Rohit Malviya: 5+ years expe\u0301rience."
    mask_res = mapper.mask_text(raw_text, candidate_name="Rohit Malviya")

    reg = SectionMaskingRegistry()
    reg.register_section("cv_summary", mask_res)

    # In payload: "Résumé of [CANDIDATE_NAME]: 5+ years expérience."
    quote = "5+ years expe\u0301rience"
    p_start = mask_res.sanitized_text.index("5+ years")
    p_end = p_start + len("5+ years expérience")

    res = reg.resolve_citation(quote, p_start, p_end, source_section="cv_summary")
    assert res.status == "EXACT_MATCH"
    assert res.confidence == "HIGH"
    # Orig coordinates must point after 'Rohit Malviya' in normalized original text
    orig_slice = mask_res.orig_text[res.orig_start : res.orig_end]
    assert "5+ years" in orig_slice


def test_10_exact_fuzzy_and_unresolved_citation_confidence_enforced() -> None:
    """Enforces strict confidence tiers: EXACT_MATCH -> HIGH, FUZZY_RECOVERED -> LOWER_CONFIDENCE, REJECTED -> ZERO."""
    serializer = BlindedEvaluationSerializer()
    raw_case = load_unlabeled_case("rw_calib_001")
    payload = serializer.serialize(raw_case)

    # 1. Exact match -> HIGH
    r_exact = payload.masking_result.resolve_citation(
        citation_text="POS Systems",
        payload_start=0,
        payload_end=11,
        source_section="job_posting.requirements.core_competencies",
    )
    assert r_exact.status == "EXACT_MATCH"
    assert r_exact.confidence == "HIGH"

    # 2. Fuzzy recovered -> LOWER_CONFIDENCE (never HIGH)
    r_fuzzy = payload.masking_result.resolve_citation(
        citation_text="POS Systems",
        payload_start=20,  # drifted by 20 positions
        payload_end=31,
        source_section="job_posting.requirements.core_competencies",
        window_slack=50,
    )
    assert r_fuzzy.status == "FUZZY_RECOVERED"
    assert r_fuzzy.confidence == "LOWER_CONFIDENCE"
    assert r_fuzzy.confidence != "HIGH"

    # 3. Unresolved -> ZERO
    r_unresolved = payload.masking_result.resolve_citation(
        citation_text="NonExistentHallucinationText999",
        payload_start=0,
        payload_end=30,
        source_section="job_posting.requirements.core_competencies",
    )
    assert r_unresolved.status == "REJECTED_UNRESOLVED"
    assert r_unresolved.confidence == "ZERO"
    assert r_unresolved.confidence != "HIGH"
    assert r_unresolved.confidence != "LOWER_CONFIDENCE"
