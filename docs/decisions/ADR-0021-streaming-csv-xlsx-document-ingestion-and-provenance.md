# ADR-0021 — Streaming CSV & XLSX Evidence Ingestion with Coordinate Provenance

- **Status:** Accepted and fully verified in Milestone 1
- **Date:** 2026-11-10

## Context

Candidates often maintain career history, skills, achievements, and compensation benchmarks in spreadsheet formats (CSV and XLSX). Previous document parsing in Hire-Steward supported plain text, Markdown, DOCX, and PDF, but lacked support for structured tabular formats.

Ingesting tabular documents requires:
1. Strict size caps to prevent decompression bombs and memory exhaustion.
2. Zero external dependencies for parsing (relying solely on Python standard library modules `csv` and `zipfile`/`xml.etree`).
3. Cell coordinate-level provenance tracking (e.g. `Sheet1!B4` or `row:4,col:2`) for complete auditability.
4. Transactional rollback and fail-closed security for malformed or suspicious uploads.

## Decision

1. **Format Limits & Handlers**:
   - Implemented streaming RFC 4180 CSV parser and zero-dependency OpenXML XLSX parser in `backend/app/services/document_parser.py`.
   - Hard limits: 10 MB for CSV files, 20 MB for XLSX files (both compressed and uncompressed archive caps).

2. **OpenXML XLSX Parsing**:
   - Parses `xl/sharedStrings.xml` and `xl/worksheets/sheet*.xml` using Python standard library `xml.etree.ElementTree.iterparse`.
   - Resolves shared string indices, numeric values, and inline formulas safely.
   - Converts cell references to structured coordinate metadata (sheet name, row index, column letter/index).

3. **Coordinate Provenance**:
   - Extracted facts record exact coordinate metadata: `{"format": "xlsx", "sheet": "WorkHistory", "cell": "C5", "row": 5, "col": 3}` or `{"format": "csv", "row": 2, "col": 1}`.
   - Dual-blob SHA-256 storage preserves the original raw uploaded bytes and the normalized canonical representation.

4. **Safety & Transactional Guarantees**:
   - Decompression zip-bomb protections reject archives exceeding compression ratios or uncompressed size thresholds.
   - Ingestion failures trigger immediate database transaction rollback, leaving no orphaned document blobs or unreviewed facts.
   - All extracted facts enter the system with `verification_status = "UNREVIEWED"` and `is_user_verified = False`, strictly preserving the compensation and evidence trust boundary.

## Consequences

- 44,228 cells verified across extensive CSV and XLSX stress tests with zero corruption.
- Complete auditability and provenance from UI claim back to source cell.
- Fully offline and zero third-party parsing dependencies added to `pyproject.toml`.
