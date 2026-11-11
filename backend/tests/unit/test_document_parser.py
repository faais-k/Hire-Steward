"""Unit tests for multi-format document parser and security guardrails (Stage 2)."""

from __future__ import annotations

import io
import zipfile
import zlib
import pytest

from backend.app.services.document_parser import (
    DocumentParserError,
    MAX_DOCUMENT_SIZE_BYTES,
    MAX_CSV_COLUMNS,
    MAX_CSV_ROWS,
    MAX_UNCOMPRESSED_XLSX_BYTES,
    ParsedDocument,
    ParsedDocumentResult,
    parse_csv,
    parse_document,
    parse_document_file,
    parse_docx,
    parse_markdown,
    parse_pdf,
    parse_plain_text,
    parse_xlsx,
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


# ===========================================================================
# CSV Parser Unit Tests
# ===========================================================================

def test_parse_csv_valid_basic() -> None:
    csv_text = "Skill,Category,Proficiency,Years\nPython,Backend,Expert,8\nPostgreSQL,Database,Advanced,6\n"
    csv_bytes = csv_text.encode("utf-8")

    res = parse_csv(csv_bytes, filename="skills.csv")
    assert res.media_type == "text/csv"
    assert res.filename == "skills.csv"
    assert res.metadata["format"] == "csv"
    assert res.metadata["row_count"] == 3
    assert res.metadata["column_count"] == 4
    assert res.metadata["columns"] == ["Skill", "Category", "Proficiency", "Years"]

    # Check sections
    assert len(res.sections) == 3
    assert res.sections[0].section_type == "table_header"
    assert res.sections[0].text == "Skill | Category | Proficiency | Years"
    assert res.sections[1].section_type == "table_row"
    assert "Skill: Python | Category: Backend | Proficiency: Expert | Years: 8" in res.sections[1].text
    assert res.sections[2].section_type == "table_row"
    assert "Skill: PostgreSQL | Category: Database | Proficiency: Advanced | Years: 6" in res.sections[2].text

    # Check provenance cells
    prov_cells = res.metadata["provenance_cells"]
    assert len(prov_cells) == 4 + 8  # 4 header cells + 8 data cells
    raw_bytes = res.raw_text.encode("utf-8")

    for c in prov_cells:
        assert c["byte_end"] > c["byte_start"]
        assert raw_bytes[c["byte_start"]:c["byte_end"]].decode("utf-8") == c["cell_value"]

    # Check routing through parse_document_file
    res_unified = parse_document_file("skills.csv", csv_bytes)
    assert res_unified.media_type == "text/csv"
    assert res_unified.raw_text == res.raw_text


def test_parse_csv_quotes_commas_and_multiline() -> None:
    csv_text = (
        'Role,Description,Company\n'
        '"Senior Architect","Designed distributed, multi-region database","Acme, Inc."\n'
        '"AI Engineer","Built agents with\nprovenance tracking","DeepTech"\n'
    )
    res = parse_csv(csv_text.encode("utf-8"), filename="experience.csv")
    assert res.metadata["row_count"] == 3
    assert "Designed distributed, multi-region database" in res.raw_text
    assert "Acme, Inc." in res.raw_text
    assert "Built agents with provenance tracking" in res.raw_text

    raw_bytes = res.raw_text.encode("utf-8")
    for sec in res.sections:
        assert raw_bytes[sec.byte_start:sec.byte_end].decode("utf-8") == sec.text


def test_parse_csv_empty_rows_and_whitespace() -> None:
    csv_text = "\n\nSkill,Level\n\nPython,Expert\n   \n\nDocker,Intermediate\n\n\n"
    res = parse_csv(csv_text.encode("utf-8"), filename="sparse.csv")
    assert res.metadata["row_count"] == 3
    assert len(res.sections) == 3


def test_parse_csv_encoding_fallback_latin1() -> None:
    csv_latin1 = "Rôle,Compétence,Années\nDéveloppeur,Sécurité,5\n".encode("latin-1")
    res = parse_csv(csv_latin1, filename="french.csv")
    assert "Développeur" in res.raw_text
    assert "Sécurité" in res.raw_text
    raw_bytes = res.raw_text.encode("utf-8")
    for sec in res.sections:
        assert raw_bytes[sec.byte_start:sec.byte_end].decode("utf-8") == sec.text


def test_parse_csv_malformed_null_bytes() -> None:
    bad_bytes = b"Skill,Years\x00\nPython,5"
    with pytest.raises(DocumentParserError) as exc_info:
        parse_csv(bad_bytes, filename="binary.csv")
    assert exc_info.value.code == "INVALID_CSV"


def test_parse_csv_file_size_limit() -> None:
    oversized = b"A" * (MAX_DOCUMENT_SIZE_BYTES + 1024)
    with pytest.raises(DocumentParserError) as exc_info:
        parse_csv(oversized, filename="huge.csv")
    assert exc_info.value.code == "FILE_TOO_LARGE"


def test_parse_csv_empty_rejection() -> None:
    with pytest.raises(DocumentParserError) as exc_info:
        parse_csv(b"", filename="empty.csv")
    assert exc_info.value.code == "EMPTY_DOCUMENT"

    with pytest.raises(DocumentParserError) as exc_info:
        parse_csv(b"   \n\t\n  ", filename="whitespace.csv")
    assert exc_info.value.code == "EMPTY_DOCUMENT"

    with pytest.raises(DocumentParserError) as exc_info:
        parse_csv(b",,,,\n,,,,\n", filename="all_empty_cells.csv")
    assert exc_info.value.code == "EMPTY_DOCUMENT"


def test_parse_csv_row_and_column_bounds() -> None:
    # 120 columns (exceeding MAX_CSV_COLUMNS = 100)
    cols = [f"Col{i}" for i in range(120)]
    row1 = [f"Val{i}" for i in range(120)]
    csv_text = ",".join(cols) + "\n" + ",".join(row1) + "\n"

    res = parse_csv(csv_text.encode("utf-8"), filename="wide.csv")
    assert res.metadata["column_count"] == MAX_CSV_COLUMNS


# ===========================================================================
# XLSX Helper & Unit Tests
# ===========================================================================

def _build_synthetic_xlsx(
    shared_strings: list[str] | None = None,
    sheets: dict[str, list[list[tuple[str, str | None, str | None]]]] | None = None,
) -> bytes:
    """Assemble a valid synthetic in-memory XLSX ZIP archive.
    
    sheets: dict of sheet_name -> rows, where each row is a list of (val, cell_type, coord)
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>""",
        )

        zf.writestr(
            "_rels/.rels",
            b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
        )

        sheet_dict = sheets or {"Sheet1": []}
        wb_rels_xml = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
        for idx, _ in enumerate(sheet_dict.keys(), 1):
            wb_rels_xml.append(f'<Relationship Id="rId{idx}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{idx}.xml"/>')
        wb_rels_xml.append('</Relationships>')
        zf.writestr("xl/_rels/workbook.xml.rels", "".join(wb_rels_xml).encode("utf-8"))

        wb_xml = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">', '<sheets>']
        for idx, sname in enumerate(sheet_dict.keys(), 1):
            wb_xml.append(f'<sheet name="{sname}" sheetId="{idx}" r:id="rId{idx}"/>')
        wb_xml.append('</sheets></workbook>')
        zf.writestr("xl/workbook.xml", "".join(wb_xml).encode("utf-8"))

        if shared_strings is not None:
            sst_xml = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">']
            for s in shared_strings:
                sst_xml.append(f'<si><t>{s}</t></si>')
            sst_xml.append('</sst>')
            zf.writestr("xl/sharedStrings.xml", "".join(sst_xml).encode("utf-8"))

        for idx, (_, rows) in enumerate(sheet_dict.items(), 1):
            ws_xml = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">', '<sheetData>']
            for r_idx, row in enumerate(rows, 1):
                ws_xml.append(f'<row r="{r_idx}">')
                for c_val, c_type, coord in row:
                    c_attr = f' r="{coord}"' if coord else ""
                    if c_type:
                        c_attr += f' t="{c_type}"'
                    if c_type == "inlineStr":
                        ws_xml.append(f'<c{c_attr}><is><t>{c_val}</t></is></c>')
                    else:
                        ws_xml.append(f'<c{c_attr}><v>{c_val}</v></c>')
                ws_xml.append('</row>')
            ws_xml.append('</sheetData></worksheet>')
            zf.writestr(f"xl/worksheets/sheet{idx}.xml", "".join(ws_xml).encode("utf-8"))

    return buf.getvalue()


def test_parse_xlsx_valid_shared_strings() -> None:
    shared_strings = ["Skill", "Category", "Years", "Python", "Backend", "8", "Rust", "Systems", "4"]
    sheets = {
        "Skills": [
            [("0", "s", "A1"), ("1", "s", "B1"), ("2", "s", "C1")],
            [("3", "s", "A2"), ("4", "s", "B2"), ("5", "s", "C2")],
            [("6", "s", "A3"), ("7", "s", "B3"), ("8", "s", "C3")],
        ]
    }
    xlsx_bytes = _build_synthetic_xlsx(shared_strings=shared_strings, sheets=sheets)

    res = parse_xlsx(xlsx_bytes, filename="candidate.xlsx")
    assert res.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert res.metadata["format"] == "xlsx"
    assert res.metadata["sheet_count"] == 1
    assert res.metadata["row_count"] == 3
    assert "Skills" in res.metadata["sheet_names"]
    assert "Skill | Category | Years" in res.raw_text
    assert "Skill: Python | Category: Backend | Years: 8" in res.raw_text
    assert "Skill: Rust | Category: Systems | Years: 4" in res.raw_text

    # Check routing through parse_document_file
    res_unified = parse_document_file("candidate.xlsx", xlsx_bytes)
    assert res_unified.media_type == res.media_type
    assert res_unified.raw_text == res.raw_text


def test_parse_xlsx_rich_text_and_inline_strings() -> None:
    # Build custom archive with rich text shared strings and mixed cell types
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>""",
        )
        zf.writestr(
            "_rels/.rels",
            b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""",
        )
        zf.writestr(
            "xl/workbook.xml",
            b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Details" sheetId="1" r:id="rId1"/></sheets>
</workbook>""",
        )
        # Shared strings with rich text runs: <si><r><t>Distributed </t></r><r><t>Systems</t></r></si>
        zf.writestr(
            "xl/sharedStrings.xml",
            b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="2" uniqueCount="2">
  <si><t>Expertise</t></si>
  <si><r><t>Distributed </t></r><r><t>Systems</t></r></si>
</sst>""",
        )
        # Sheet with inlineStr, boolean, and numeric
        zf.writestr(
            "xl/worksheets/sheet1.xml",
            b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="s"><v>0</v></c>
      <c r="B1" t="inlineStr"><is><t>Status</t></is></c>
      <c r="C1"><v>Score</v></c>
    </row>
    <row r="2">
      <c r="A2" t="s"><v>1</v></c>
      <c r="B2" t="b"><v>1</v></c>
      <c r="C2"><v>98.5</v></c>
    </row>
  </sheetData>
</worksheet>""",
        )

    res = parse_xlsx(buf.getvalue(), filename="rich.xlsx")
    assert "Expertise | Status | Score" in res.raw_text
    assert "Distributed Systems" in res.raw_text
    assert "TRUE" in res.raw_text
    assert "98.5" in res.raw_text


def test_parse_xlsx_multiple_worksheets() -> None:
    sheets = {
        "Summary": [
            [("Name", "inlineStr", "A1"), ("Title", "inlineStr", "B1")],
            [("Alice", "inlineStr", "A2"), ("Staff Engineer", "inlineStr", "B2")],
        ],
        "Certifications": [
            [("Certification", "inlineStr", "A1"), ("Year", "inlineStr", "B1")],
            [("AWS Solutions Architect", "inlineStr", "A2"), ("2024", "inlineStr", "B2")],
        ],
    }
    xlsx_bytes = _build_synthetic_xlsx(sheets=sheets)
    res = parse_xlsx(xlsx_bytes, filename="multi_sheet.xlsx")

    assert res.metadata["sheet_count"] == 2
    assert "Summary" in res.metadata["sheet_names"]
    assert "Certifications" in res.metadata["sheet_names"]
    assert "Sheet: Summary" in res.raw_text
    assert "Sheet: Certifications" in res.raw_text
    assert "Alice" in res.raw_text
    assert "AWS Solutions Architect" in res.raw_text


def test_parse_xlsx_corrupted_zip() -> None:
    bad_bytes = b"PK\x03\x04corrupted non-zip payload"
    with pytest.raises(DocumentParserError) as exc_info:
        parse_xlsx(bad_bytes, filename="corrupt.xlsx")
    assert exc_info.value.code == "INVALID_XLSX"


def test_parse_xlsx_missing_sheets() -> None:
    # Valid ZIP but missing worksheet entries
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("dummy.txt", b"nothing here")
    with pytest.raises(DocumentParserError) as exc_info:
        parse_xlsx(buf.getvalue(), filename="empty.xlsx")
    assert exc_info.value.code == "INVALID_XLSX"


def test_parse_xlsx_decompression_bomb_uncompressed_bytes() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Write large sparse entry exceeding 20MB limit
        zf.writestr("xl/worksheets/sheet1.xml", b" " * (MAX_UNCOMPRESSED_XLSX_BYTES + 1024))
    raw_bytes = buf.getvalue()
    with pytest.raises(DocumentParserError) as exc_info:
        parse_xlsx(raw_bytes, filename="bomb.xlsx")
    assert exc_info.value.code == "DECOMPRESSION_BOMB_DETECTED"


def test_parse_xlsx_file_size_limit() -> None:
    oversized = b"A" * (MAX_DOCUMENT_SIZE_BYTES + 1024)
    with pytest.raises(DocumentParserError) as exc_info:
        parse_xlsx(oversized, filename="huge.xlsx")
    assert exc_info.value.code == "FILE_TOO_LARGE"


def test_parse_xlsx_corrupted_xml() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/worksheets/sheet1.xml", b"<worksheet><sheetData><truncated")
    with pytest.raises(DocumentParserError) as exc_info:
        parse_xlsx(buf.getvalue(), filename="bad_xml.xlsx")
    assert exc_info.value.code in ("INVALID_XLSX_XML", "INVALID_XLSX")


def test_csv_and_xlsx_utf8_byte_span_accuracy() -> None:
    # 1. Test CSV with multi-byte characters
    csv_text = "Fähigkeit,Kategorie,Niveau\nMaschinelles Lernen,Künstliche Intelligenz,Experte\n日本語,Sprache,C1\n"
    res_csv = parse_csv(csv_text.encode("utf-8"), filename="multibyte.csv")
    csv_bytes = res_csv.raw_text.encode("utf-8")

    for sec in res_csv.sections:
        assert sec.byte_end > sec.byte_start
        assert csv_bytes[sec.byte_start:sec.byte_end].decode("utf-8") == res_csv.raw_text[sec.start_char:sec.end_char]
        assert sec.text == res_csv.raw_text[sec.start_char:sec.end_char]

    for c in res_csv.metadata["provenance_cells"]:
        assert c["byte_end"] > c["byte_start"]
        assert csv_bytes[c["byte_start"]:c["byte_end"]].decode("utf-8") == c["cell_value"]

    # 2. Test XLSX with multi-byte characters
    sheets = {
        "Skills": [
            [("Fähigkeit", "inlineStr", "A1"), ("Kategorie", "inlineStr", "B1")],
            [("Maschinelles Lernen", "inlineStr", "A2"), ("KI", "inlineStr", "B2")],
            [("日本語", "inlineStr", "A3"), ("Sprache", "inlineStr", "B3")],
        ]
    }
    xlsx_bytes = _build_synthetic_xlsx(sheets=sheets)
    res_xlsx = parse_xlsx(xlsx_bytes, filename="multibyte.xlsx")
    xlsx_raw_bytes = res_xlsx.raw_text.encode("utf-8")

    for sec in res_xlsx.sections:
        assert sec.byte_end > sec.byte_start
        assert xlsx_raw_bytes[sec.byte_start:sec.byte_end].decode("utf-8") == res_xlsx.raw_text[sec.start_char:sec.end_char]
        assert sec.text == res_xlsx.raw_text[sec.start_char:sec.end_char]

    for c in res_xlsx.metadata["provenance_cells"]:
        assert c["byte_end"] > c["byte_start"]
        assert xlsx_raw_bytes[c["byte_start"]:c["byte_end"]].decode("utf-8") == c["cell_value"]


def test_parsed_document_aliases() -> None:
    csv_bytes = b"A,B\n1,2"
    res = parse_document(file_content=csv_bytes, filename="aliases.csv")

    assert isinstance(res, ParsedDocument)
    assert isinstance(res, ParsedDocumentResult)
    assert res.text_content == res.raw_text
    assert res.extracted_metadata == res.metadata
    assert res.extracted_metadata["format"] == "csv"


