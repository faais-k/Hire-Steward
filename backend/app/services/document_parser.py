"""Multi-format document parser for candidate evidence (Stage 2).

Supports structured text extraction, section segmentation, and offset tracking for:
- Plain text (.txt)
- Markdown (.md)
- Word documents (.docx) via native zipfile/XML parsing
- PDF (.pdf) via native stream and FlateDecode parsing

Guarantees:
- 10MB maximum file size limit enforcement.
- Strict filename sanitization and path traversal prevention.
- Offset tracking (start_char, end_char) for provenance citations.
- Clean text normalization with preserved structural boundaries.
"""

from __future__ import annotations

import csv
import io
import os
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib
from dataclasses import dataclass
from typing import Any

MAX_DOCUMENT_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_FILE_BYTES = MAX_DOCUMENT_SIZE_BYTES  # Specification alias
MAX_UNCOMPRESSED_DOCX_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_DECOMPRESSED_PDF_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_UNCOMPRESSED_XLSX_BYTES = 20 * 1024 * 1024  # 20 MB

MAX_CSV_ROWS = 10_000
MAX_CSV_COLUMNS = 100
MAX_CELL_LENGTH = 4096

MAX_XLSX_SHEETS = 10
MAX_XLSX_ROWS = 10_000
MAX_XLSX_COLUMNS = 100

ALLOWED_EXTENSIONS = {".txt", ".md", ".docx", ".pdf", ".csv", ".xlsx"}
ALLOWED_MEDIA_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/csv",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/octet-stream",  # Fallback for some browsers
}


class DocumentParserError(Exception):
    """Raised when parsing or validating document content fails."""

    def __init__(self, message: str, code: str = "INVALID_DOCUMENT_FORMAT") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(frozen=True)
class ExtractedSection:
    heading: str | None
    section_type: str  # "heading", "paragraph", "list_item", "table_row"
    text: str
    start_char: int
    end_char: int
    byte_start: int = 0
    byte_end: int = 0


@dataclass(frozen=True)
class ParsedDocumentResult:
    filename: str
    media_type: str
    raw_text: str
    sections: list[ExtractedSection]
    metadata: dict[str, Any]
    char_count: int

    @property
    def text_content(self) -> str:
        return self.raw_text

    @property
    def extracted_metadata(self) -> dict[str, Any]:
        return self.metadata


ParsedDocument = ParsedDocumentResult


def sanitize_filename_safe(filename: str) -> str:
    """Sanitize filename to prevent path traversal and shell exploits."""
    if not filename:
        return "unnamed_document.txt"
    cleaned = os.path.basename(filename.strip().replace("\\", "/"))
    cleaned = re.sub(r"[^\w\.\-\_]", "_", cleaned)
    if not cleaned or cleaned.startswith("."):
        cleaned = f"file_{cleaned}"
    return cleaned


def parse_plain_text(content: str, filename: str = "document.txt") -> ParsedDocumentResult:
    """Parse plain text, identifying paragraphs and line offsets."""
    raw_text = content.replace("\r\n", "\n").replace("\r", "\n")
    sections: list[ExtractedSection] = []

    paragraphs = raw_text.split("\n\n")
    current_char = 0
    for para in paragraphs:
        stripped = para.strip()
        if stripped:
            start = raw_text.find(para, current_char)
            end = start + len(para)
            byte_start = len(raw_text[:start].encode("utf-8"))
            byte_end = len(raw_text[:end].encode("utf-8"))
            sections.append(
                ExtractedSection(
                    heading=None,
                    section_type="paragraph",
                    text=stripped,
                    start_char=start,
                    end_char=end,
                    byte_start=byte_start,
                    byte_end=byte_end,
                )
            )
            current_char = end

    return ParsedDocumentResult(
        filename=filename,
        media_type="text/plain",
        raw_text=raw_text,
        sections=sections,
        metadata={"format": "plain_text"},
        char_count=len(raw_text),
    )


def parse_markdown(content: str, filename: str = "document.md") -> ParsedDocumentResult:
    """Parse markdown, identifying headers (#, ##), bullet points, and paragraphs."""
    raw_text = content.replace("\r\n", "\n").replace("\r", "\n")
    sections: list[ExtractedSection] = []
    lines = raw_text.split("\n")

    current_char = 0
    current_heading: str | None = None

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            current_char += len(line) + 1
            i += 1
            continue

        start_char = current_char
        end_char = start_char + len(line)

        if stripped.startswith("#"):
            match = re.match(r"^(#+\s*)(.*)$", stripped)
            if match:
                current_heading = match.group(2).strip()
                prefix_len = line.find(current_heading)
                text_start = start_char + prefix_len
                text_end = text_start + len(current_heading)
                byte_start = len(raw_text[:text_start].encode("utf-8"))
                byte_end = len(raw_text[:text_end].encode("utf-8"))
                sections.append(
                    ExtractedSection(
                        heading=current_heading,
                        section_type="heading",
                        text=current_heading,
                        start_char=text_start,
                        end_char=text_end,
                        byte_start=byte_start,
                        byte_end=byte_end,
                    )
                )
        elif stripped.startswith(("-", "*", "+", "1.", "2.", "3.", "4.", "5.")):
            text = re.sub(r"^[-*+]\s+|\d+\.\s+", "", stripped)
            prefix_len = line.find(text)
            text_start = start_char + prefix_len
            text_end = text_start + len(text)
            byte_start = len(raw_text[:text_start].encode("utf-8"))
            byte_end = len(raw_text[:text_end].encode("utf-8"))
            sections.append(
                ExtractedSection(
                    heading=current_heading,
                    section_type="list_item",
                    text=text,
                    start_char=text_start,
                    end_char=text_end,
                    byte_start=byte_start,
                    byte_end=byte_end,
                )
            )
        else:
            prefix_len = line.find(stripped)
            text_start = start_char + prefix_len
            text_end = text_start + len(stripped)
            byte_start = len(raw_text[:text_start].encode("utf-8"))
            byte_end = len(raw_text[:text_end].encode("utf-8"))
            sections.append(
                ExtractedSection(
                    heading=current_heading,
                    section_type="paragraph",
                    text=stripped,
                    start_char=text_start,
                    end_char=text_end,
                    byte_start=byte_start,
                    byte_end=byte_end,
                )
            )

        current_char = end_char + 1
        i += 1

    return ParsedDocumentResult(
        filename=filename,
        media_type="text/markdown",
        raw_text=raw_text,
        sections=sections,
        metadata={"format": "markdown"},
        char_count=len(raw_text),
    )


def parse_docx(content_bytes: bytes, filename: str = "document.docx") -> ParsedDocumentResult:
    """Parse DOCX XML structure via zipfile, extracting paragraphs, tables, and styles."""
    if len(content_bytes) > MAX_DOCUMENT_SIZE_BYTES:
        raise DocumentParserError("File exceeds 10MB limit", code="FILE_TOO_LARGE")

    try:
        with zipfile.ZipFile(io.BytesIO(content_bytes)) as docx_zip:
            total_uncompressed = sum(info.file_size for info in docx_zip.infolist())
            if total_uncompressed > MAX_UNCOMPRESSED_DOCX_BYTES:
                raise DocumentParserError(
                    "DOCX uncompressed size exceeds 20MB limit (decompression bomb protection)",
                    code="DECOMPRESSION_BOMB_DETECTED",
                )
            xml_content = docx_zip.read("word/document.xml")
    except DocumentParserError:
        raise
    except Exception as exc:
        raise DocumentParserError(f"Corrupt or invalid DOCX file: {exc}", code="INVALID_DOCX") from exc

    namespaces = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    try:
        tree = ET.fromstring(xml_content)
    except Exception as exc:
        raise DocumentParserError(f"Invalid XML in DOCX: {exc}", code="INVALID_DOCX_XML") from exc

    raw_paragraphs: list[tuple[str, str, str | None]] = []  # (text, section_type, heading)
    current_heading: str | None = None

    for elem in tree.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag == "p":
            texts = [node.text for node in elem.iter() if (node.tag.endswith("t") and node.text)]
            para_text = "".join(texts).strip()
            if not para_text:
                continue

            style_node = elem.find(".//w:pStyle", namespaces)
            style_val = style_node.attrib.get(f"{{{namespaces['w']}}}val", "") if style_node is not None else ""
            if "Heading" in style_val or "heading" in style_val.lower():
                current_heading = para_text
                raw_paragraphs.append((para_text, "heading", current_heading))
            else:
                raw_paragraphs.append((para_text, "paragraph", current_heading))
        elif tag == "tbl":
            # Table extraction
            for row in elem.findall(".//w:tr", namespaces):
                cells = []
                for cell in row.findall(".//w:tc", namespaces):
                    cell_text = "".join([t.text for t in cell.iter() if t.tag.endswith("t") and t.text]).strip()
                    if cell_text:
                        cells.append(cell_text)
                if cells:
                    row_text = " | ".join(cells)
                    raw_paragraphs.append((row_text, "table_row", current_heading))

    full_text = "\n\n".join(text for text, _, _ in raw_paragraphs)
    sections: list[ExtractedSection] = []
    current_char = 0

    for text, stype, head in raw_paragraphs:
        start_char = full_text.find(text, current_char)
        if start_char == -1:
            start_char = current_char
        end_char = start_char + len(text)
        byte_start = len(full_text[:start_char].encode("utf-8"))
        byte_end = len(full_text[:end_char].encode("utf-8"))
        sections.append(
            ExtractedSection(
                heading=head,
                section_type=stype,
                text=text,
                start_char=start_char,
                end_char=end_char,
                byte_start=byte_start,
                byte_end=byte_end,
            )
        )
        current_char = end_char

    return ParsedDocumentResult(
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        raw_text=full_text,
        sections=sections,
        metadata={"format": "docx"},
        char_count=len(full_text),
    )


def _unescape_pdf_string(data: bytes) -> str:
    """Unescape PDF literal string octal escapes and standard escape characters."""
    def _oct_replace(m: re.Match[bytes]) -> bytes:
        return bytes([int(m.group(1), 8)])

    unescaped = re.sub(rb"\\([0-7]{1,3})", _oct_replace, data)
    unescaped = unescaped.replace(b"\\\\", b"\x00SLASH\x00")
    unescaped = unescaped.replace(b"\\(", b"(")
    unescaped = unescaped.replace(b"\\)", b")")
    unescaped = unescaped.replace(b"\\n", b"\n")
    unescaped = unescaped.replace(b"\\r", b"\r")
    unescaped = unescaped.replace(b"\\t", b"\t")
    unescaped = unescaped.replace(b"\\b", b"\b")
    unescaped = unescaped.replace(b"\\f", b"\f")
    unescaped = unescaped.replace(b"\x00SLASH\x00", b"\\")
    try:
        if unescaped.startswith(b"\xfe\xff"):
            return unescaped[2:].decode("utf-16-be", errors="replace")
        return unescaped.decode("utf-8")
    except UnicodeDecodeError:
        return unescaped.decode("latin1", errors="replace")


def _extract_pdf_stream_text(stream_data: bytes) -> str:
    """Extract readable text tokens from a decoded PDF content stream."""
    text_chunks: list[str] = []

    # 1. Standard string show: (hello) Tj
    for m in re.finditer(rb"\((.*?)(?<!\\)\)\s*Tj", stream_data):
        txt = _unescape_pdf_string(m.group(1)).strip()
        if txt:
            text_chunks.append(txt)

    # 2. Text array show: [(hello) 20 (world)] TJ
    for arr in re.finditer(rb"\[(.*?)\]\s*TJ", stream_data):
        sub_strings = re.findall(rb"\((.*?)(?<!\\)\)", arr.group(1))
        sub_text = " ".join(_unescape_pdf_string(s).strip() for s in sub_strings if s)
        if sub_text:
            text_chunks.append(sub_text)

    # 3. Next line and show string: (hello) '
    for m in re.finditer(rb"\((.*?)(?<!\\)\)\s*'", stream_data):
        txt = _unescape_pdf_string(m.group(1)).strip()
        if txt:
            text_chunks.append(txt)

    # 4. Spacing, next line and show string: c w (hello) "
    for m in re.finditer(rb"\((.*?)(?<!\\)\)\s*\"", stream_data):
        txt = _unescape_pdf_string(m.group(1)).strip()
        if txt:
            text_chunks.append(txt)

    return " ".join(text_chunks).strip()


def parse_pdf(content_bytes: bytes, filename: str = "document.pdf") -> ParsedDocumentResult:
    """Parse PDF document streams, extracting text sections and offsets."""
    if len(content_bytes) > MAX_DOCUMENT_SIZE_BYTES:
        raise DocumentParserError("File exceeds 10MB limit", code="FILE_TOO_LARGE")

    if not content_bytes.startswith(b"%PDF-"):
        raise DocumentParserError("Invalid PDF header", code="INVALID_PDF_HEADER")

    # Reject encrypted PDFs
    if re.search(rb"/Encrypt\s+(\d+\s+\d+\s+R|<<)", content_bytes):
        raise DocumentParserError(
            "Encrypted PDFs are not supported without credentials",
            code="ENCRYPTED_PDF_UNSUPPORTED",
        )

    extracted_blocks: list[str] = []
    total_decompressed_bytes = 0

    pattern = re.compile(rb"stream[\r\n]+(.*?)[\r\n]+endstream", re.DOTALL)
    for match in pattern.finditer(content_bytes):
        stream_bytes = match.group(1)
        remaining_budget = MAX_DECOMPRESSED_PDF_BYTES - total_decompressed_bytes
        if remaining_budget <= 0:
            raise DocumentParserError(
                "Combined PDF streams exceed decompression limit (possible decompression bomb)",
                code="DECOMPRESSION_BOMB_DETECTED",
            )
        decompressed: bytes | None = None
        try:
            decompress_obj = zlib.decompressobj()
            decompressed = decompress_obj.decompress(stream_bytes, remaining_budget + 1)
            if len(decompressed) > remaining_budget or decompress_obj.unconsumed_tail:
                raise DocumentParserError(
                    "Combined PDF streams exceed decompression limit (possible decompression bomb)",
                    code="DECOMPRESSION_BOMB_DETECTED",
                )
            total_decompressed_bytes += len(decompressed)
        except DocumentParserError:
            raise
        except Exception:
            decompressed = stream_bytes

        if decompressed:
            block_text = _extract_pdf_stream_text(decompressed)
            if block_text and len(block_text) > 2:
                extracted_blocks.append(block_text)

    # Fallback for simple ASCII uncompressed PDFs without stream wrapper
    if not extracted_blocks:
        ascii_matches = re.findall(rb"\(([A-Za-z0-9\s.,!?:;@_/\-+=]{3,})\)", content_bytes)
        for m in ascii_matches:
            extracted_blocks.append(_unescape_pdf_string(m))

    full_text = "\n\n".join(extracted_blocks)
    if not full_text.strip():
        raise DocumentParserError(
            "Scanned or image-only PDF detected. OCR is required to extract text.",
            code="OCR_REQUIRED",
        )

    sections: list[ExtractedSection] = []
    current_char = 0

    for block in extracted_blocks:
        start_char = full_text.find(block, current_char)
        if start_char == -1:
            start_char = current_char
        end_char = start_char + len(block)
        byte_start = len(full_text[:start_char].encode("utf-8"))
        byte_end = len(full_text[:end_char].encode("utf-8"))
        sections.append(
            ExtractedSection(
                heading=None,
                section_type="paragraph",
                text=block,
                start_char=start_char,
                end_char=end_char,
                byte_start=byte_start,
                byte_end=byte_end,
            )
        )
        current_char = end_char

    return ParsedDocumentResult(
        filename=filename,
        media_type="application/pdf",
        raw_text=full_text,
        sections=sections,
        metadata={"format": "pdf"},
        char_count=len(full_text),
    )


def _col_idx_to_letters(col_idx: int) -> str:
    """Convert 0-based column index to spreadsheet column letter (0 -> A, 25 -> Z, 26 -> AA)."""
    result: list[str] = []
    n = col_idx + 1
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result.append(chr(65 + remainder))
    return "".join(reversed(result))


def _col_letters_to_idx(letters: str) -> int:
    """Convert spreadsheet column letters ('A', 'B', 'AA') to 0-based index."""
    idx = 0
    for char in letters.upper():
        if "A" <= char <= "Z":
            idx = idx * 26 + (ord(char) - ord("A") + 1)
    return max(0, idx - 1)


def parse_csv(content_bytes: bytes, filename: str = "document.csv") -> ParsedDocumentResult:
    """Parse CSV tabular data with size caps, encoding fallback, and cell/row provenance."""
    if len(content_bytes) > MAX_DOCUMENT_SIZE_BYTES:
        raise DocumentParserError("File exceeds 10MB limit", code="FILE_TOO_LARGE")

    # 1. Encoding handling: UTF-8 with fallback to Latin-1
    try:
        text_content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text_content = content_bytes.decode("latin-1")
        except Exception as exc:
            raise DocumentParserError(f"Unable to decode CSV text: {exc}", code="DECODE_ERROR") from exc

    # Strip UTF-8 BOM if present
    if text_content.startswith("\ufeff"):
        text_content = text_content[1:]

    if not text_content.strip():
        raise DocumentParserError("CSV document is empty", code="EMPTY_DOCUMENT")

    if "\x00" in text_content:
        raise DocumentParserError("CSV file contains null bytes", code="INVALID_CSV")

    # 2. Delimiter detection via csv.Sniffer with fallback to comma
    sample = text_content[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
    except Exception:
        dialect = csv.excel

    try:
        reader = csv.reader(io.StringIO(text_content), dialect=dialect)
        all_raw_rows = list(reader)
    except Exception as exc:
        raise DocumentParserError(f"Malformed CSV content: {exc}", code="INVALID_CSV") from exc

    # 3. Clean and bound rows
    non_empty_rows: list[list[str]] = []
    for r in all_raw_rows:
        cleaned_row = [re.sub(r"[\r\n]+", " ", c).strip()[:MAX_CELL_LENGTH] for c in r[:MAX_CSV_COLUMNS]]
        if any(cleaned_row):
            non_empty_rows.append(cleaned_row)
        if len(non_empty_rows) >= MAX_CSV_ROWS:
            break

    if not non_empty_rows:
        raise DocumentParserError("CSV document contains no tabular data", code="EMPTY_DOCUMENT")

    # 4. Resolve column headers
    raw_headers = non_empty_rows[0]
    columns: list[str] = [
        raw_headers[i] if raw_headers[i] else f"Col_{i+1}"
        for i in range(len(raw_headers))
    ]
    max_cols = max(len(r) for r in non_empty_rows)
    if max_cols > len(columns):
        columns.extend([f"Col_{i+1}" for i in range(len(columns), max_cols)])

    full_text = ""
    sections: list[ExtractedSection] = []
    provenance_cells: list[dict[str, Any]] = []

    # 5. Row 1: Header section and provenance cells
    header_row_text = " | ".join(columns)
    row_start_char = 0
    full_text = header_row_text
    row_end_char = len(full_text)

    sections.append(
        ExtractedSection(
            heading="CSV Headers",
            section_type="table_header",
            text=header_row_text,
            start_char=row_start_char,
            end_char=row_end_char,
            byte_start=len(full_text[:row_start_char].encode("utf-8")),
            byte_end=len(full_text[:row_end_char].encode("utf-8")),
        )
    )

    for col_idx, col_name in enumerate(columns):
        col_start_in_row = sum(len(columns[k]) + 3 for k in range(col_idx))
        col_end_in_row = col_start_in_row + len(col_name)
        cell_start_char = row_start_char + col_start_in_row
        cell_end_char = row_start_char + col_end_in_row
        col_letter = _col_idx_to_letters(col_idx)
        coord = f"{col_letter}1"
        b_start = len(full_text[:cell_start_char].encode("utf-8"))
        b_end = len(full_text[:cell_end_char].encode("utf-8"))
        provenance_cells.append({
            "row": 1,
            "row_index": 1,
            "column": col_letter,
            "column_header": col_name,
            "coordinate": coord,
            "value": col_name,
            "cell_value": col_name,
            "byte_start": b_start,
            "byte_end": b_end,
            "start_char": cell_start_char,
            "end_char": cell_end_char,
        })

    # 6. Data rows (Row 2, 3, ...)
    for row_idx, row_cells in enumerate(non_empty_rows[1:], start=2):
        row_items: list[tuple[int, str, str]] = []
        for col_idx in range(max(len(columns), len(row_cells))):
            col_header = columns[col_idx] if col_idx < len(columns) else f"Col_{col_idx+1}"
            val = row_cells[col_idx] if col_idx < len(row_cells) else ""
            if val:
                row_items.append((col_idx, col_header, val))

        if not row_items:
            continue

        data_row_text = " | ".join(f"{h}: {v}" for _, h, v in row_items)
        row_start_char = len(full_text) + 2  # account for "\n\n" separator
        full_text += "\n\n" + data_row_text
        row_end_char = len(full_text)

        first_val = row_cells[0] if len(row_cells) > 0 and row_cells[0] else ""
        heading = f"Row {row_idx} ({first_val})" if first_val else f"Row {row_idx}"

        sections.append(
            ExtractedSection(
                heading=heading,
                section_type="table_row",
                text=data_row_text,
                start_char=row_start_char,
                end_char=row_end_char,
                byte_start=len(full_text[:row_start_char].encode("utf-8")),
                byte_end=len(full_text[:row_end_char].encode("utf-8")),
            )
        )

        current_offset_in_row = 0
        for m, (col_idx, col_header, val) in enumerate(row_items):
            prefix = f"{col_header}: "
            if m > 0:
                current_offset_in_row += 3  # len(" | ")
            val_start = current_offset_in_row + len(prefix)
            val_end = val_start + len(val)
            c_start = row_start_char + val_start
            c_end = row_start_char + val_end
            current_offset_in_row += len(prefix) + len(val)
            col_letter = _col_idx_to_letters(col_idx)
            coord = f"{col_letter}{row_idx}"
            b_start = len(full_text[:c_start].encode("utf-8"))
            b_end = len(full_text[:c_end].encode("utf-8"))

            provenance_cells.append({
                "row": row_idx,
                "row_index": row_idx,
                "column": col_letter,
                "column_header": col_header,
                "coordinate": coord,
                "value": val,
                "cell_value": val,
                "byte_start": b_start,
                "byte_end": b_end,
                "start_char": c_start,
                "end_char": c_end,
            })

    metadata = {
        "format": "csv",
        "row_count": len(non_empty_rows),
        "column_count": len(columns),
        "columns": columns,
        "provenance_cells": provenance_cells,
    }

    return ParsedDocumentResult(
        filename=filename,
        media_type="text/csv",
        raw_text=full_text,
        sections=sections,
        metadata=metadata,
        char_count=len(full_text),
    )


def _safe_read_zip_entry(zf: zipfile.ZipFile, name: str, max_bytes: int) -> bytes:
    """Read a ZIP entry with bounded streaming to prevent decompression bombs."""
    try:
        with zf.open(name) as f:
            data = f.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise DocumentParserError(
                    f"Entry '{name}' exceeds decompression limit (decompression bomb protection)",
                    code="DECOMPRESSION_BOMB_DETECTED",
                )
            return data
    except DocumentParserError:
        raise
    except Exception as exc:
        raise DocumentParserError(f"Failed to read ZIP entry '{name}': {exc}", code="INVALID_XLSX") from exc


def _extract_cell_value(cell_elem: ET.Element, cell_type: str, shared_strings: list[str]) -> str:
    """Extract string value from OpenXML cell element based on type attribute."""
    # 1. Shared String
    if cell_type == "s":
        for child in cell_elem.iter():
            ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if ctag == "v" and child.text:
                try:
                    s_idx = int(child.text.strip())
                    if 0 <= s_idx < len(shared_strings):
                        return shared_strings[s_idx]
                except (ValueError, IndexError):
                    return ""
        return ""

    # 2. Inline String
    if cell_type == "inlineStr":
        for child in cell_elem.iter():
            ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if ctag == "is":
                parts = [
                    t.text for t in child.iter()
                    if (t.tag.split("}")[-1] if "}" in t.tag else t.tag) == "t" and t.text
                ]
                return "".join(parts).strip()
        return ""

    # 3. Boolean
    if cell_type == "b":
        for child in cell_elem.iter():
            ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if ctag == "v" and child.text:
                b_val = child.text.strip()
                return "TRUE" if b_val in ("1", "true", "TRUE") else "FALSE"
        return ""

    # 4. Numeric / Date / Formula Cached Value
    for child in cell_elem.iter():
        ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if ctag == "v" and child.text:
            return child.text.strip()

    # 5. Fallback for formula without cached <v>
    for child in cell_elem.iter():
        ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if ctag == "f" and child.text:
            return child.text.strip()

    return ""


def parse_xlsx(content_bytes: bytes, filename: str = "document.xlsx") -> ParsedDocumentResult:
    """Parse XLSX workbook via native zipfile and xml.etree with provenance tracking."""
    if len(content_bytes) > MAX_DOCUMENT_SIZE_BYTES:
        raise DocumentParserError("File exceeds 10MB limit", code="FILE_TOO_LARGE")

    try:
        zf = zipfile.ZipFile(io.BytesIO(content_bytes))
    except Exception as exc:
        raise DocumentParserError(f"Corrupt or invalid XLSX file: {exc}", code="INVALID_XLSX") from exc

    with zf:
        infolist = zf.infolist()
        total_uncompressed = sum(info.file_size for info in infolist)
        if total_uncompressed > MAX_UNCOMPRESSED_XLSX_BYTES:
            raise DocumentParserError(
                "XLSX uncompressed size exceeds 20MB limit (decompression bomb protection)",
                code="DECOMPRESSION_BOMB_DETECTED",
            )

        namelist = set(zf.namelist())

        # 1. Parse shared strings table if present
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in namelist:
            try:
                sst_data = _safe_read_zip_entry(zf, "xl/sharedStrings.xml", MAX_UNCOMPRESSED_XLSX_BYTES)
                sst_root = ET.fromstring(sst_data)
                for elem in sst_root.iter():
                    tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                    if tag == "si":
                        parts = [
                            node.text
                            for node in elem.iter()
                            if (node.tag.split("}")[-1] if "}" in node.tag else node.tag) == "t" and node.text
                        ]
                        shared_strings.append("".join(parts)[:MAX_CELL_LENGTH])
            except DocumentParserError:
                raise
            except Exception as exc:
                raise DocumentParserError(f"Invalid sharedStrings XML in XLSX: {exc}", code="INVALID_XLSX_XML") from exc

        # 2. Discover worksheets via workbook.xml + rels, or fallback
        sheet_targets: list[tuple[str, str]] = []  # (display_name, zip_path)
        if "xl/workbook.xml" in namelist and "xl/_rels/workbook.xml.rels" in namelist:
            try:
                wb_rels_data = _safe_read_zip_entry(zf, "xl/_rels/workbook.xml.rels", MAX_UNCOMPRESSED_XLSX_BYTES)
                wb_rels_root = ET.fromstring(wb_rels_data)
                rid_to_target: dict[str, str] = {}
                for rel in wb_rels_root.iter():
                    rtag = rel.tag.split("}")[-1] if "}" in rel.tag else rel.tag
                    if rtag == "Relationship":
                        rid = rel.attrib.get("Id", "")
                        target = rel.attrib.get("Target", "")
                        if rid and target:
                            clean_target = target.lstrip("/")
                            if not clean_target.startswith("xl/"):
                                clean_target = f"xl/{clean_target}"
                            rid_to_target[rid] = clean_target

                wb_data = _safe_read_zip_entry(zf, "xl/workbook.xml", MAX_UNCOMPRESSED_XLSX_BYTES)
                wb_root = ET.fromstring(wb_data)
                for sheet_elem in wb_root.iter():
                    stag = sheet_elem.tag.split("}")[-1] if "}" in sheet_elem.tag else sheet_elem.tag
                    if stag == "sheet":
                        name = sheet_elem.attrib.get("name", "Sheet")
                        rid = ""
                        for attr_name, attr_val in sheet_elem.attrib.items():
                            if attr_name.endswith("id"):
                                rid = attr_val
                                break
                        if rid and rid in rid_to_target and rid_to_target[rid] in namelist:
                            sheet_targets.append((name, rid_to_target[rid]))
            except Exception:
                sheet_targets = []

        if not sheet_targets:
            ws_files = [n for n in namelist if re.match(r"^xl/worksheets/sheet\d+\.xml$", n)]
            ws_files.sort(key=lambda s: int(re.search(r"\d+", s).group(0)) if re.search(r"\d+", s) else s)
            for idx, wf in enumerate(ws_files, 1):
                sheet_targets.append((f"Sheet{idx}", wf))

        if not sheet_targets:
            raise DocumentParserError("No worksheets found in XLSX archive", code="INVALID_XLSX")

        # 3. Process worksheets and rows
        raw_sections_data: list[tuple[str, str, str | None, dict[str, Any]]] = []
        total_rows_count = 0
        all_column_names: list[str] = []

        for sheet_name, sheet_path in sheet_targets[:MAX_XLSX_SHEETS]:
            try:
                ws_data = _safe_read_zip_entry(zf, sheet_path, MAX_UNCOMPRESSED_XLSX_BYTES)
                ws_root = ET.fromstring(ws_data)
            except DocumentParserError:
                raise
            except Exception as exc:
                raise DocumentParserError(f"Invalid worksheet XML in '{sheet_path}': {exc}", code="INVALID_XLSX_XML") from exc

            raw_sections_data.append((
                f"Sheet: {sheet_name}",
                "heading",
                sheet_name,
                {"sheet": sheet_name, "type": "sheet_title"},
            ))

            sheet_headers: list[str] = []
            sheet_row_idx = 0

            for elem in ws_root.iter():
                tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                if tag != "row":
                    continue

                sheet_row_idx += 1
                if sheet_row_idx > MAX_XLSX_ROWS:
                    break
                total_rows_count += 1

                row_attr_r = elem.attrib.get("r", "")
                current_row_num = int(row_attr_r) if row_attr_r.isdigit() else sheet_row_idx

                cells_in_row: list[dict[str, Any]] = []
                col_counter = 0

                for cell_elem in elem.iter():
                    ctag = cell_elem.tag.split("}")[-1] if "}" in cell_elem.tag else cell_elem.tag
                    if ctag != "c":
                        continue

                    col_counter += 1
                    if col_counter > MAX_XLSX_COLUMNS:
                        break

                    coord = cell_elem.attrib.get("r", "")
                    if coord:
                        m = re.match(r"^([A-Z]+)(\d+)$", coord.upper())
                        if m:
                            col_letter = m.group(1)
                            row_num = int(m.group(2))
                            col_idx = _col_letters_to_idx(col_letter)
                        else:
                            col_letter = _col_idx_to_letters(col_counter - 1)
                            row_num = current_row_num
                            col_idx = col_counter - 1
                    else:
                        col_letter = _col_idx_to_letters(col_counter - 1)
                        row_num = current_row_num
                        col_idx = col_counter - 1

                    cell_type = cell_elem.attrib.get("t", "")
                    val = _extract_cell_value(cell_elem, cell_type, shared_strings)
                    if val:
                        cells_in_row.append({
                            "col_idx": col_idx,
                            "col_letter": col_letter,
                            "row": row_num,
                            "coordinate": f"{col_letter}{row_num}",
                            "value": val[:MAX_CELL_LENGTH],
                        })

                if not cells_in_row:
                    continue

                cells_in_row.sort(key=lambda c: c["col_idx"])

                # First non-empty row serves as header
                if not sheet_headers:
                    max_col = max(c["col_idx"] for c in cells_in_row)
                    hdr_map = {c["col_idx"]: c["value"] for c in cells_in_row}
                    sheet_headers = [hdr_map.get(i, f"Col_{_col_idx_to_letters(i)}") for i in range(max_col + 1)]
                    if not all_column_names:
                        all_column_names = list(sheet_headers)

                    header_text = " | ".join(sheet_headers)
                    hdr_placements: list[tuple[dict[str, Any], int, int]] = []
                    cur_hdr_char = 0
                    for h_idx, h_name in enumerate(sheet_headers):
                        if h_idx > 0:
                            cur_hdr_char += 3  # " | "
                        v_start = cur_hdr_char
                        v_end = cur_hdr_char + len(h_name)
                        cur_hdr_char = v_end
                        col_letter = _col_idx_to_letters(h_idx)
                        coord = f"{col_letter}{current_row_num}"
                        c_info = {
                            "col_idx": h_idx,
                            "col_letter": col_letter,
                            "row": current_row_num,
                            "coordinate": coord,
                            "value": h_name,
                        }
                        hdr_placements.append((c_info, v_start, v_end))

                    raw_sections_data.append((
                        header_text,
                        "table_header",
                        f"{sheet_name} Headers",
                        {
                            "sheet": sheet_name,
                            "row": current_row_num,
                            "cells": cells_in_row,
                            "cell_placements": hdr_placements,
                        },
                    ))
                    continue

                row_parts: list[str] = []
                cell_placements: list[tuple[dict[str, Any], int, int]] = []
                cur_row_char = 0

                for c in cells_in_row:
                    c_idx = c["col_idx"]
                    header_label = sheet_headers[c_idx] if c_idx < len(sheet_headers) and sheet_headers[c_idx] else c["col_letter"]
                    c_val = c["value"]

                    prefix = f"{header_label}: "
                    part_str = f"{prefix}{c_val}"

                    if row_parts:
                        sep = " | "
                        cur_row_char += len(sep)

                    val_start_in_row = cur_row_char + len(prefix)
                    val_end_in_row = val_start_in_row + len(c_val)

                    row_parts.append(part_str)
                    cur_row_char = val_end_in_row
                    cell_placements.append((c, val_start_in_row, val_end_in_row))

                row_text = " | ".join(row_parts)
                heading = f"{sheet_name} Row {current_row_num}"
                raw_sections_data.append((
                    row_text,
                    "table_row",
                    heading,
                    {
                        "sheet": sheet_name,
                        "row": current_row_num,
                        "cells": cells_in_row,
                        "cell_placements": cell_placements,
                    },
                ))

    # 4. Construct normalized text artifact and map exact global byte spans
    full_text = ""
    sections: list[ExtractedSection] = []
    provenance_cells: list[dict[str, Any]] = []

    for i, (text, stype, head, meta) in enumerate(raw_sections_data):
        if i == 0:
            start_char = 0
            full_text = text
        else:
            start_char = len(full_text) + 2
            full_text += "\n\n" + text
        end_char = len(full_text)
        byte_start = len(full_text[:start_char].encode("utf-8"))
        byte_end = len(full_text[:end_char].encode("utf-8"))

        sections.append(
            ExtractedSection(
                heading=head,
                section_type=stype,
                text=text,
                start_char=start_char,
                end_char=end_char,
                byte_start=byte_start,
                byte_end=byte_end,
            )
        )

        if "cell_placements" in meta:
            for c_info, val_start_in_row, val_end_in_row in meta["cell_placements"]:
                c_char_start = start_char + val_start_in_row
                c_char_end = start_char + val_end_in_row
                c_byte_start = len(full_text[:c_char_start].encode("utf-8"))
                c_byte_end = len(full_text[:c_char_end].encode("utf-8"))
                provenance_cells.append({
                    "sheet": meta.get("sheet", "Sheet"),
                    "row": c_info["row"],
                    "column": c_info["col_letter"],
                    "coordinate": c_info["coordinate"],
                    "value": c_info["value"],
                    "cell_value": c_info["value"],
                    "start_char": c_char_start,
                    "end_char": c_char_end,
                    "byte_start": c_byte_start,
                    "byte_end": c_byte_end,
                })

    metadata = {
        "format": "xlsx",
        "sheet_count": len(sheet_targets),
        "row_count": total_rows_count,
        "column_names": all_column_names,
        "sheet_names": [name for name, _ in sheet_targets],
        "provenance_cells": provenance_cells,
    }

    return ParsedDocumentResult(
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        raw_text=full_text,
        sections=sections,
        metadata=metadata,
        char_count=len(full_text),
    )


def parse_document_file(
    filename: str, content_bytes: bytes, media_type: str | None = None
) -> ParsedDocumentResult:
    """Unified entry point to safely parse documents based on filename/media type."""
    clean_name = sanitize_filename_safe(filename)
    if len(content_bytes) > MAX_DOCUMENT_SIZE_BYTES:
        raise DocumentParserError("File exceeds 10MB limit", code="FILE_TOO_LARGE")

    ext = os.path.splitext(clean_name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise DocumentParserError(
            f"Unsupported file extension '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            code="UNSUPPORTED_EXTENSION",
        )

    if ext in (".txt", ".md"):
        try:
            text = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = content_bytes.decode("latin-1")
            except Exception as exc:
                raise DocumentParserError("Unable to decode text file", code="DECODE_ERROR") from exc

        if ext == ".md":
            return parse_markdown(text, filename=clean_name)
        return parse_plain_text(text, filename=clean_name)

    if ext == ".docx":
        return parse_docx(content_bytes, filename=clean_name)

    if ext == ".pdf":
        return parse_pdf(content_bytes, filename=clean_name)

    if ext == ".csv":
        return parse_csv(content_bytes, filename=clean_name)

    if ext == ".xlsx":
        return parse_xlsx(content_bytes, filename=clean_name)

    raise DocumentParserError("Unsupported document format", code="UNSUPPORTED_FORMAT")


def parse_document(
    *args: Any,
    filename: str | None = None,
    content_bytes: bytes | None = None,
    file_content: bytes | None = None,
    media_type: str | None = None,
    content_type: str | None = None,
    **kwargs: Any,
) -> ParsedDocumentResult:
    """Convenience alias matching PROJECT.md interface contract."""
    target_filename = filename
    target_bytes = file_content if file_content is not None else content_bytes
    target_media_type = media_type if media_type is not None else content_type

    if args:
        if isinstance(args[0], bytes):
            target_bytes = args[0]
            if len(args) > 1 and isinstance(args[1], str):
                target_filename = args[1]
        elif isinstance(args[0], str):
            target_filename = args[0]
            if len(args) > 1 and isinstance(args[1], bytes):
                target_bytes = args[1]
            if len(args) > 2 and isinstance(args[2], (str, type(None))):
                target_media_type = args[2]

    if target_bytes is None:
        target_bytes = b""
    if target_filename is None:
        target_filename = "document.bin"

    return parse_document_file(filename=target_filename, content_bytes=target_bytes, media_type=target_media_type)
