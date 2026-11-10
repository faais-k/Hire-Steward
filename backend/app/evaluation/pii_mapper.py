"""PII Coordinate Mapping and Coordinate Displacement Service (Task 8.2 Checkpoint A).

Enforces:
1. Unicode NFC canonical composition for all text representations.
2. Case-scoped pseudonymization of candidate personal identifying information
   (email, phone, URLs, candidate names).
3. Non-bijective segment detection rejecting citations cutting across replaced tokens.
4. Three-tier citation verification: EXACT_MATCH, FUZZY_RECOVERED, and REJECTED_UNRESOLVED.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

RE_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
RE_PHONE = re.compile(
    r"(?:\+?\d{1,4}[-.\s]*)?(?:\(?\d{2,4}\)?[-.\s]*)?\d{3,4}[-.\s]*\d{3,4}\b"
)
RE_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"']+")


@dataclass(frozen=True)
class PIISegment:
    """A segment of text in original coordinates replaced by a pseudonym token."""

    orig_start: int
    orig_end: int
    payload_start: int
    payload_end: int
    entity_type: str
    orig_text: str
    replacement: str


@dataclass(frozen=True)
class CitationResolution:
    """Outcome of resolving model citation coordinates back to source text."""

    status: Literal["EXACT_MATCH", "FUZZY_RECOVERED", "REJECTED_UNRESOLVED"]
    resolved_text: str | None
    orig_start: int | None
    orig_end: int | None
    confidence: Literal["HIGH", "LOWER_CONFIDENCE", "ZERO"]
    reason: str | None = None


@dataclass
class MaskingResult:
    """Result of PII masking containing sanitized text and segment displacement map."""

    orig_text: str
    sanitized_text: str
    segments: list[PIISegment] = field(default_factory=list)

    def map_payload_to_orig(
        self, payload_start: int, payload_end: int
    ) -> tuple[int | None, int | None, bool]:
        """Map payload coordinates back to original Unicode code-point coordinates.

        Returns:
            (orig_start, orig_end, is_ambiguous)
            If the coordinates cut strictly inside a replaced segment (partial crossing),
            is_ambiguous is True and coordinates are (None, None).
        """
        if payload_start < 0 or payload_end > len(self.sanitized_text) or payload_start > payload_end:
            return None, None, True

        # Check for partial non-bijective segment crossings
        for seg in self.segments:
            # Check if start cuts strictly inside a replaced token
            if seg.payload_start < payload_start < seg.payload_end:
                return None, None, True
            # Check if end cuts strictly inside a replaced token
            if seg.payload_start < payload_end < seg.payload_end:
                return None, None, True

        # Convert payload_start to orig_start
        orig_start = self._point_payload_to_orig(payload_start, is_end=False)
        orig_end = self._point_payload_to_orig(payload_end, is_end=True)

        return orig_start, orig_end, False

    def _point_payload_to_orig(self, pt: int, is_end: bool) -> int:
        """Map a single payload index to an original text index."""
        delta = 0
        for seg in self.segments:
            if pt < seg.payload_start:
                break
            if pt == seg.payload_start:
                return seg.orig_start
            if seg.payload_start < pt < seg.payload_end:
                # Strictly inside token
                return seg.orig_end if is_end else seg.orig_start
            if pt == seg.payload_end:
                return seg.orig_end
            # pt is after seg.payload_end
            delta += (seg.payload_end - seg.payload_start) - (seg.orig_end - seg.orig_start)

        return pt - delta

    def resolve_citation(
        self,
        citation_text: str,
        payload_start: int,
        payload_end: int,
        window_slack: int = 50,
    ) -> CitationResolution:
        """Verify model citation coordinates and text against source text."""
        norm_citation = unicodedata.normalize("NFC", citation_text).strip()
        if not norm_citation:
            return CitationResolution(
                status="REJECTED_UNRESOLVED",
                resolved_text=None,
                orig_start=None,
                orig_end=None,
                confidence="ZERO",
                reason="Empty or whitespace citation text",
            )

        # 1. Check exact mapping via displacement table
        orig_start, orig_end, is_ambiguous = self.map_payload_to_orig(payload_start, payload_end)
        if not is_ambiguous and orig_start is not None and orig_end is not None:
            # Extract source slice
            orig_slice = self.orig_text[orig_start:orig_end]
            payload_slice = self.sanitized_text[payload_start:payload_end]
            if orig_slice == norm_citation or payload_slice == norm_citation:
                return CitationResolution(
                    status="EXACT_MATCH",
                    resolved_text=orig_slice,
                    orig_start=orig_start,
                    orig_end=orig_end,
                    confidence="HIGH",
                    reason="Exact coordinate and text match verified",
                )

        # 2. Local bounded search (window slack +- 50 code points)
        search_start = max(0, (orig_start if orig_start is not None else payload_start) - window_slack)
        search_end = min(
            len(self.orig_text),
            (orig_end if orig_end is not None else payload_end) + window_slack,
        )
        local_window = self.orig_text[search_start:search_end]

        matches = [m.start() for m in re.finditer(re.escape(norm_citation), local_window)]
        if len(matches) == 1:
            rec_orig_start = search_start + matches[0]
            rec_orig_end = rec_orig_start + len(norm_citation)
            return CitationResolution(
                status="FUZZY_RECOVERED",
                resolved_text=norm_citation,
                orig_start=rec_orig_start,
                orig_end=rec_orig_end,
                confidence="LOWER_CONFIDENCE",
                reason=f"Unique match recovered within +- {window_slack} code-point window",
            )

        # 3. Citation could not be uniquely resolved
        return CitationResolution(
            status="REJECTED_UNRESOLVED",
            resolved_text=None,
            orig_start=None,
            orig_end=None,
            confidence="ZERO",
            reason="Citation text not found or ambiguous in source text window",
        )


@dataclass
class SectionMaskingRegistry:
    """Registry maintaining per-section text, coordinate displacement mappings, and citation resolution."""

    sections: dict[str, MaskingResult] = field(default_factory=dict)

    def register_section(
        self,
        section_id: str,
        masking_result: MaskingResult,
        aliases: list[str] | None = None,
    ) -> None:
        """Register a section's MaskingResult under its primary identifier and optional aliases."""
        self.sections[section_id] = masking_result
        if aliases:
            for alias in aliases:
                self.sections[alias] = masking_result

    def get_section(self, section_id: str | None) -> MaskingResult | None:
        """Retrieve the MaskingResult for a section or alias, if registered."""
        if not section_id:
            return None
        return self.sections.get(section_id)

    def resolve_citation(
        self,
        citation_text: str,
        payload_start: int,
        payload_end: int,
        source_section: str | None = None,
        window_slack: int = 50,
    ) -> CitationResolution:
        """Resolve citation strictly against the specified source_section."""
        if not source_section or source_section not in self.sections:
            return CitationResolution(
                status="REJECTED_UNRESOLVED",
                resolved_text=None,
                orig_start=None,
                orig_end=None,
                confidence="ZERO",
                reason=f"Unknown or missing source_section: '{source_section}'",
            )

        masking_result = self.sections[source_section]
        return masking_result.resolve_citation(
            citation_text=citation_text,
            payload_start=payload_start,
            payload_end=payload_end,
            window_slack=window_slack,
        )


class PIICoordinateMapper:
    """Performs NFC normalization, PII pseudonymization, and displacement tracking."""

    def mask_text(
        self,
        text: str,
        candidate_name: str | None = None,
    ) -> MaskingResult:
        """Mask PII entities in text and record coordinate displacement segments."""
        norm_text = unicodedata.normalize("NFC", text or "")
        segments_raw: list[tuple[int, int, str, str]] = []

        # 1. Detect candidate name if provided
        if candidate_name and candidate_name.strip():
            norm_name = unicodedata.normalize("NFC", candidate_name.strip())
            for m in re.finditer(re.escape(norm_name), norm_text, re.IGNORECASE):
                segments_raw.append((m.start(), m.end(), "NAME", "[CANDIDATE_NAME]"))

        # 2. Detect email addresses
        for m in RE_EMAIL.finditer(norm_text):
            segments_raw.append((m.start(), m.end(), "EMAIL", "[EMAIL_REDACTED]"))

        # 3. Detect phone numbers (only if contains at least 7 digits)
        for m in RE_PHONE.finditer(norm_text):
            body = m.group(0)
            if sum(c.isdigit() for c in body) >= 7:
                segments_raw.append((m.start(), m.end(), "PHONE", "[PHONE_REDACTED]"))

        # 4. Detect URLs
        for m in RE_URL.finditer(norm_text):
            segments_raw.append((m.start(), m.end(), "URL", "[URL_REDACTED]"))

        # Sort segments by start position, resolving overlaps by keeping earliest/longest
        segments_raw.sort(key=lambda x: (x[0], -(x[1] - x[0])))

        non_overlapping: list[tuple[int, int, str, str]] = []
        last_end = -1
        for start, end, entity_type, repl in segments_raw:
            if start >= last_end:
                non_overlapping.append((start, end, entity_type, repl))
                last_end = end

        # Construct sanitized string and PIISegments
        sanitized_parts: list[str] = []
        recorded_segments: list[PIISegment] = []
        curr_orig = 0
        curr_payload = 0

        for orig_start, orig_end, entity_type, repl in non_overlapping:
            # Append preceding clean text
            if orig_start > curr_orig:
                prefix = norm_text[curr_orig:orig_start]
                sanitized_parts.append(prefix)
                curr_payload += len(prefix)

            # Append replacement
            payload_start = curr_payload
            sanitized_parts.append(repl)
            curr_payload += len(repl)
            payload_end = curr_payload

            recorded_segments.append(
                PIISegment(
                    orig_start=orig_start,
                    orig_end=orig_end,
                    payload_start=payload_start,
                    payload_end=payload_end,
                    entity_type=entity_type,
                    orig_text=norm_text[orig_start:orig_end],
                    replacement=repl,
                )
            )
            curr_orig = orig_end

        # Append trailing clean text
        if curr_orig < len(norm_text):
            suffix = norm_text[curr_orig:]
            sanitized_parts.append(suffix)

        sanitized_text = "".join(sanitized_parts)

        return MaskingResult(
            orig_text=norm_text,
            sanitized_text=sanitized_text,
            segments=recorded_segments,
        )
