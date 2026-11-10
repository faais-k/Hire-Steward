"""Unit tests for multi-format document parser and security guardrails (Stage 2)."""

from __future__ import annotations

import io
import zipfile
import zlib
import pytest

from backend.app.services.document_parser import (
    DocumentParserError,
    MAX_DOCUMENT_SIZE_BYTES,
    parse_document_file,
    parse_docx,
    parse_markdown,
    parse_pdf,
    parse_plain_text,
    sanitize_filename_safe,
)


def test_sanitize_filename_safe() -> None:
    assert sanitize_filename_safe("../../../etc/passwd") == "passwd"
    assert sanitize_filename_safe("..\\..\\boot.ini") == "boot.ini"
    assert sanitize_filename_safe("Resume (2026) #1.pdf") == "Resume__2026___1.pdf"
    assert sanitize_filename_safe("") == "unnamed_document.txt"
    assert sanitize_filename_safe(".hidden.txt") == "file_.hidden.txt"


def test_parse_plain_text() -> None:
    text = "First paragraph.\n\nSecond paragraph with multiple sentences.\n\nThird paragraph."
    res = parse_plain_text(text, filename="notes.txt")
    assert res.media_type == "text/plain"
    assert len(res.sections) == 3
    assert res.sections[0].text == "First paragraph."
    assert res.sections[1].text == "Second paragraph with multiple sentences."
    assert res.char_count == len(text)
    assert res.sections[0].start_char == 0


def test_parse_markdown() -> None:
    md = """# Candidate Resume

Software Engineer with 8 years experience.

## Skills
- Python
- PostgreSQL
- Docker

## Experience
Built high-throughput data processing pipelines."""

    res = parse_markdown(md, filename="resume.md")
    assert res.media_type == "text/markdown"
    types = [s.section_type for s in res.sections]
    assert "heading" in types
    assert "list_item" in types
    assert "paragraph" in types

    heading_texts = [s.text for s in res.sections if s.section_type == "heading"]
    assert "Candidate Resume" in heading_texts
    assert "Skills" in heading_texts
    assert "Experience" in heading_texts


def test_parse_docx_synthetic() -> None:
    # Build minimal valid WordprocessingML document in a zip
    xml_content = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
      <w:r><w:t>Curriculum Vitae</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t>Lead AI Engineer with strong distributed systems background.</w:t></w:r>
    </w:p>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Company</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Role</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Acme Corp</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Staff Architect</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
  </w:body>
</w:document>"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", xml_content.encode("utf-8"))

    raw_bytes = buf.getvalue()
    res = parse_docx(raw_bytes, filename="cv.docx")
    assert res.media_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert "Curriculum Vitae" in res.raw_text
    assert "Acme Corp | Staff Architect" in res.raw_text
    assert any(s.section_type == "table_row" for s in res.sections)


def test_parse_pdf_synthetic() -> None:
    # Construct a valid synthetic PDF with FlateDecode compressed stream
    stream_content = b"BT /F1 12 Tf (Jane Doe Resume) Tj ET"
    compressed = zlib.compress(stream_content)

    pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Length " + str(len(compressed)).encode("ascii") + b" /Filter /FlateDecode >>\n"
        b"stream\n" + compressed + b"\nendstream\n"
        b"endobj\n"
        b"%%EOF\n"
    )

    res = parse_pdf(pdf_bytes, filename="jane_doe.pdf")
    assert res.media_type == "application/pdf"
    assert "Jane Doe Resume" in res.raw_text


def test_document_parser_size_limit() -> None:
    huge_bytes = b"A" * (MAX_DOCUMENT_SIZE_BYTES + 1024)
    with pytest.raises(DocumentParserError) as exc_info:
        parse_document_file("huge.txt", huge_bytes)
    assert exc_info.value.code == "FILE_TOO_LARGE"


def test_document_parser_unsupported_format() -> None:
    with pytest.raises(DocumentParserError) as exc_info:
        parse_document_file("script.py", b"print('hello')")
    assert exc_info.value.code == "UNSUPPORTED_EXTENSION"


def test_docx_decompression_bomb_protection() -> None:
    # Construct a docx zip with total uncompressed size > 20MB
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Write large sparse entry
        zf.writestr("word/document.xml", b" " * (21 * 1024 * 1024))

    raw_bytes = buf.getvalue()
    with pytest.raises(DocumentParserError) as exc_info:
        parse_docx(raw_bytes, filename="bomb.docx")
    assert exc_info.value.code == "DECOMPRESSION_BOMB_DETECTED"


def test_pdf_scanned_image_only_ocr_required() -> None:
    # Construct valid PDF header without any text stream content
    empty_pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R >>\nendobj\n"
        b"%%EOF\n"
    )
    with pytest.raises(DocumentParserError) as exc_info:
        parse_pdf(empty_pdf_bytes, filename="scanned.pdf")
    assert exc_info.value.code == "OCR_REQUIRED"


def test_pdf_combined_multi_stream_decompression_bomb():
    """Verify that multiple compressed streams whose cumulative expansion exceeds 20MB are rejected."""
    # Create two streams that each expand to 12MB (total 24MB > 20MB limit)
    single_expand_chunk = b"A" * (12 * 1024 * 1024)
    compressed_chunk = zlib.compress(single_expand_chunk)
    
    pdf_bytes = (
        b"%PDF-1.4\n1 0 obj\n<<>>\nstream\n"
        + compressed_chunk
        + b"\nendstream\nendobj\n"
        b"2 0 obj\n<<>>\nstream\n"
        + compressed_chunk
        + b"\nendstream\nendobj\n"
        b"%%EOF"
    )

    with pytest.raises(DocumentParserError) as exc_info:
        parse_document_file("multi_bomb.pdf", pdf_bytes)
    assert exc_info.value.code == "DECOMPRESSION_BOMB_DETECTED"


def test_pdf_encrypted_rejection():
    """Verify that encrypted PDFs are detected and rejected without fabricating text."""
    encrypted_pdf = (
        b"%PDF-1.7\n"
        b"1 0 obj\n"
        b"<< /Type /Catalog /Pages 2 0 R >>\n"
        b"endobj\n"
        b"3 0 obj\n"
        b"<< /Filter /Standard /V 4 /R 4 /P -1024 /Encrypt 4 0 R >>\n"
        b"endobj\n"
        b"trailer\n"
        b"<< /Root 1 0 R /Encrypt 3 0 R >>\n"
        b"%%EOF"
    )

    with pytest.raises(DocumentParserError) as exc_info:
        parse_document_file("protected.pdf", encrypted_pdf)
    assert exc_info.value.code == "ENCRYPTED_PDF_UNSUPPORTED"


def test_pdf_escaped_and_non_ascii_text():
    """Verify handling of escaped strings and non-ASCII character encoding in PDF streams."""
    stream_content = b"BT /F1 12 Tf (Hello \\(World\\)! Line1\\nLine2 \\101\\102) Tj ET"
    compressed = zlib.compress(stream_content)
    pdf_bytes = (
        b"%PDF-1.4\n1 0 obj\n<<>>\nstream\n"
        + compressed
        + b"\nendstream\nendobj\n%%EOF"
    )

    res = parse_document_file("escaped.pdf", pdf_bytes)
    assert "Hello (World)!" in res.raw_text
    assert "AB" in res.raw_text  # octal \101\102 is 'AB'


def test_extracted_section_utf8_byte_offsets():
    """Verify that ExtractedSection byte offsets match the exact encoded UTF-8 byte span."""
    md_content = "# Profil\n\n- Spezialfähigkeit: Maschinelles Lernen\n- Erfahrung: 5 Jahre"
    res = parse_markdown(md_content, "lebenslauf.md")
    raw_bytes = res.raw_text.encode("utf-8")

    for sec in res.sections:
        assert sec.byte_end > sec.byte_start
        assert raw_bytes[sec.byte_start:sec.byte_end].decode("utf-8") == res.raw_text[sec.start_char:sec.end_char]

