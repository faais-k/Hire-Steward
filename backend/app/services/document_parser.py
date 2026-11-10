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

import io
import os
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib
from dataclasses import dataclass
from typing import Any

MAX_DOCUMENT_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_UNCOMPRESSED_DOCX_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_DECOMPRESSED_PDF_BYTES = 20 * 1024 * 1024  # 20 MB

ALLOWED_EXTENSIONS = {".txt", ".md", ".docx", ".pdf"}
ALLOWED_MEDIA_TYPES = {
    "text/plain",
    "text/markdown",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
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

    raise DocumentParserError("Unsupported document format", code="UNSUPPORTED_FORMAT")
