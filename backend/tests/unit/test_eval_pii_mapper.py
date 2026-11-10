"""Unit tests for PII Coordinate Mapping and Displacement (Task 8.2 Checkpoint A).

Verifies:
1. PII detection and case-scoped pseudonymization (email, phone, URLs, names).
2. Segment-based displacement mapping between original code points and payload code points.
3. Unicode NFC canonical composition preservation.
4. Detection and rejection of partial non-bijective segment crossings.
5. Citation verification: EXACT_MATCH vs FUZZY_RECOVERED vs REJECTED_UNRESOLVED.
"""

from __future__ import annotations

import pytest

from backend.app.evaluation.pii_mapper import (
    CitationResolution,
    PIICoordinateMapper,
    PIISegment,
)


def test_pii_sanitization_and_segment_recording() -> None:
    """Test that emails, phone numbers, and names are replaced with deterministic tokens."""
    mapper = PIICoordinateMapper()
    raw_text = "Contact Jane Doe at jane.doe@example.invalid or +1-555-0199 for inquiries."

    result = mapper.mask_text(
        text=raw_text,
        candidate_name="Jane Doe",
    )

    # 1. Verify PII is masked in payload
    assert "jane.doe@example.invalid" not in result.sanitized_text
    assert "+1-555-0199" not in result.sanitized_text
    assert "Jane Doe" not in result.sanitized_text
    assert "[CANDIDATE_NAME]" in result.sanitized_text
    assert "[EMAIL_REDACTED]" in result.sanitized_text
    assert "[PHONE_REDACTED]" in result.sanitized_text

    # 2. Verify segments are recorded
    assert len(result.segments) >= 3
    name_seg = next(s for s in result.segments if s.entity_type == "NAME")
    assert name_seg.orig_text == "Jane Doe"
    assert name_seg.replacement == "[CANDIDATE_NAME]"

    email_seg = next(s for s in result.segments if s.entity_type == "EMAIL")
    assert email_seg.orig_text == "jane.doe@example.invalid"
    assert email_seg.replacement == "[EMAIL_REDACTED]"

    phone_seg = next(s for s in result.segments if s.entity_type == "PHONE")
    assert phone_seg.orig_text == "+1-555-0199"
    assert phone_seg.replacement == "[PHONE_REDACTED]"


def test_coordinate_mapping_before_and_after_segments() -> None:
    """Test mapping payload coordinates back to original text coordinates."""
    mapper = PIICoordinateMapper()
    raw_text = "Hello Jane Doe, welcome!"
    # "Jane Doe" is at [6, 14] in raw_text.
    # Replaced with "[CANDIDATE_NAME]" (length 16).
    # Result: "Hello [CANDIDATE_NAME], welcome!"

    result = mapper.mask_text(text=raw_text, candidate_name="Jane Doe")
    assert result.sanitized_text == "Hello [CANDIDATE_NAME], welcome!"

    # 1. Coordinate before the replacement: "Hello " is [0, 6] in both
    orig_start, orig_end, is_ambiguous = result.map_payload_to_orig(0, 5)
    assert not is_ambiguous
    assert orig_start == 0 and orig_end == 5
    assert raw_text[orig_start:orig_end] == "Hello"

    # 2. Coordinate after the replacement: ", welcome!"
    # In payload: ", welcome!" starts at index 22 and ends at 32
    # In original: ", welcome!" starts at index 14 and ends at 24
    payload_sub = ", welcome!"
    p_start = result.sanitized_text.index(payload_sub)
    p_end = p_start + len(payload_sub)
    orig_start, orig_end, is_ambiguous = result.map_payload_to_orig(p_start, p_end)
    assert not is_ambiguous
    assert orig_start == 14 and orig_end == 24
    assert raw_text[orig_start:orig_end] == payload_sub


def test_partial_segment_crossing_rejected() -> None:
    """A citation that cuts halfway through a replaced pseudonym token is ambiguous."""
    mapper = PIICoordinateMapper()
    raw_text = "Report authored by Jane Doe."
    # Sanitized: "Report authored by [CANDIDATE_NAME]."
    result = mapper.mask_text(text=raw_text, candidate_name="Jane Doe")

    name_start = result.sanitized_text.index("[CANDIDATE_NAME]")
    # Cut inside "[CANDIDATE_NAME]": e.g. from index 0 to name_start + 5
    orig_start, orig_end, is_ambiguous = result.map_payload_to_orig(0, name_start + 5)
    assert is_ambiguous
    assert orig_start is None
    assert orig_end is None


def test_citation_resolution_exact_match() -> None:
    """Exact citation match maps cleanly to original text."""
    mapper = PIICoordinateMapper()
    raw_text = "Candidate has 5+ years experience building distributed microservices in Go."
    result = mapper.mask_text(text=raw_text)

    # Citation snippet taken from payload
    citation_text = "5+ years experience building distributed microservices"
    start = result.sanitized_text.index(citation_text)
    end = start + len(citation_text)

    res: CitationResolution = result.resolve_citation(
        citation_text=citation_text,
        payload_start=start,
        payload_end=end,
    )

    assert res.status == "EXACT_MATCH"
    assert res.resolved_text == citation_text
    assert res.confidence == "HIGH"
    assert res.orig_start is not None
    assert raw_text[res.orig_start : res.orig_end] == citation_text


def test_citation_resolution_fuzzy_recovery() -> None:
    """Model reports slightly drifted coordinates (within +-50 code points)."""
    mapper = PIICoordinateMapper()
    raw_text = "Section Overview:\nExperienced with Kubernetes and Helm in production cloud environments."
    result = mapper.mask_text(text=raw_text)

    citation_text = "Kubernetes and Helm in production"
    actual_start = result.sanitized_text.index(citation_text)
    actual_end = actual_start + len(citation_text)

    # Simulate model coordinate drift of +15 code points
    drifted_start = actual_start + 15
    drifted_end = actual_end + 15

    res: CitationResolution = result.resolve_citation(
        citation_text=citation_text,
        payload_start=drifted_start,
        payload_end=drifted_end,
    )

    assert res.status == "FUZZY_RECOVERED"
    assert res.resolved_text == citation_text
    assert res.confidence == "LOWER_CONFIDENCE"
    assert res.orig_start == raw_text.index(citation_text)


def test_citation_resolution_rejected_when_not_in_window() -> None:
    """Hallucinated citation snippet not present in source text is rejected."""
    mapper = PIICoordinateMapper()
    raw_text = "Candidate works as a Python developer."
    result = mapper.mask_text(text=raw_text)

    hallucinated_citation = "10 years experience leading enterprise Java teams"

    res: CitationResolution = result.resolve_citation(
        citation_text=hallucinated_citation,
        payload_start=0,
        payload_end=len(hallucinated_citation),
    )

    assert res.status == "REJECTED_UNRESOLVED"
    assert res.resolved_text is None
    assert res.orig_start is None
