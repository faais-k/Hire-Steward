"""Integration tests for resume parser and candidate evidence workflow (P0 Remediation)."""

import io
from pathlib import Path
import shutil
import tempfile
from uuid import uuid4
import zipfile

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.evidence_config import EvidenceSettings
from backend.app.main import create_app
from backend.tests.unit.test_document_parser import _build_synthetic_xlsx


def local_headers() -> dict[str, str]:
    return {"host": "localhost", "origin": "http://localhost"}


@pytest.fixture
def client(tmp_path: Path):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False, "autocommit": False},
        poolclass=StaticPool,
    )
    config = Config("backend/alembic.ini")
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage_root = Path(tempfile.gettempdir()) / "hire-steward-parser-tests" / uuid4().hex
    settings = EvidenceSettings(storage_root=storage_root)
    with TestClient(create_app(session_factory=factory, evidence_settings=settings)) as client:
        yield client
    engine.dispose()
    shutil.rmtree(storage_root, ignore_errors=True)


def test_resume_parser_creates_document_and_extracts_sections_without_auto_facts(client: TestClient):
    content = "# Skills\nPython, FastAPI, SQLite\n\n# Experience\nSenior Backend Engineer at Acme Corp"
    resp = client.post(
        "/api/v1/profile/parse-document",
        headers={**local_headers(), "x-filename": "my_resume.md"},
        content=content.encode("utf-8"),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["document_id"] is not None
    assert data["document_version_id"] is not None
    assert data["sections_count"] >= 2
    # Verify no facts were automatically created
    facts_resp = client.get("/api/v1/facts", headers=local_headers())
    assert facts_resp.status_code == 200
    assert len(facts_resp.json()) == 0

    # Verify sections have byte offsets and suggestions
    skills_sec = next(s for s in data["sections"] if s.get("heading") == "Skills")
    assert skills_sec["suggested_fact_type"] == "SKILL"
    assert skills_sec["byte_start"] >= 0
    assert skills_sec["byte_end"] > skills_sec["byte_start"]

    exp_sec = next(s for s in data["sections"] if s.get("heading") == "Experience")
    assert exp_sec["suggested_fact_type"] == "EMPLOYMENT"


def test_streaming_body_size_limit_enforced(client: TestClient):
    # Empty body
    resp_empty = client.post(
        "/api/v1/profile/parse-document",
        headers={**local_headers(), "x-filename": "empty.txt"},
        content=b"",
    )
    assert resp_empty.status_code == 400
    assert "EMPTY_DOCUMENT_BODY" in resp_empty.text

    # Too large body (> 10MB)
    large_body = b"A" * (10 * 1024 * 1024 + 1024)
    resp_large = client.post(
        "/api/v1/profile/parse-document",
        headers={**local_headers(), "x-filename": "huge.txt"},
        content=large_body,
    )
    assert resp_large.status_code == 413
    assert "DOCUMENT_TOO_LARGE" in resp_large.text


def test_map_fact_validates_fact_type_and_attaches_provenance(client: TestClient):
    content = "# Skills\nPython, SQL, PyTest"
    resp = client.post(
        "/api/v1/profile/parse-document",
        headers={**local_headers(), "x-filename": "skills.md"},
        content=content.encode("utf-8"),
    )
    assert resp.status_code == 200
    doc_ver_id = resp.json()["document_version_id"]
    skills_sec = resp.json()["sections"][0]

    # 1. Invalid fact type is rejected with 422
    bad_map = client.post(
        "/api/v1/profile/map-fact",
        headers=local_headers(),
        json={
            "document_version_id": doc_ver_id,
            "fact_type": "PARAGRAPH",  # Not a valid FactType
            "value": {"skill": "Python"},
        },
    )
    assert bad_map.status_code == 422
    assert "INVALID_FACT_TYPE" in bad_map.text

    # 2. Valid mapping creates fact in UNREVIEWED state with provenance
    good_map = client.post(
        "/api/v1/profile/map-fact",
        headers=local_headers(),
        json={
            "document_version_id": doc_ver_id,
            "fact_type": "SKILL",
            "value": {"skill": "Python", "category": "Backend"},
            "byte_start": skills_sec["byte_start"],
            "byte_end": skills_sec["byte_end"],
            "excerpt": skills_sec["text"],
        },
    )
    assert good_map.status_code == 201, good_map.text
    fact_data = good_map.json()
    assert fact_data["verification_state"] == "UNREVIEWED"
    assert fact_data["provenance_id"] is not None

    fact_id = fact_data["fact_id"]

    # 3. Explicit verification transitions state to USER_VERIFIED
    verify_resp = client.post(f"/api/v1/facts/{fact_id}/verify", headers=local_headers())
    assert verify_resp.status_code == 200
    assert verify_resp.json()["verification_state"] == "USER_VERIFIED"


def test_map_fact_rolls_back_on_invalid_provenance_excerpt(client: TestClient):
    content = "# Projects\nAutonomous Job Search Agent"
    resp = client.post(
        "/api/v1/profile/parse-document",
        headers={**local_headers(), "x-filename": "proj.md"},
        content=content.encode("utf-8"),
    )
    assert resp.status_code == 200
    doc_ver_id = resp.json()["document_version_id"]
    sec = resp.json()["sections"][0]

    # Pass mismatched excerpt -> attach_provenance will fail with INVALID_PROVENANCE
    bad_prov = client.post(
        "/api/v1/profile/map-fact",
        headers=local_headers(),
        json={
            "document_version_id": doc_ver_id,
            "fact_type": "PROJECT",
            "value": {"title": "Autonomous Agent"},
            "byte_start": sec["byte_start"],
            "byte_end": sec["byte_end"],
            "excerpt": "This does not match the actual text in the span",
        },
    )
    assert bad_prov.status_code == 422
    assert "INVALID_PROVENANCE" in bad_prov.text

    # Verify no fact was persisted due to rollback
    facts = client.get("/api/v1/facts", headers=local_headers()).json()
    assert len(facts) == 0


def test_csv_upload_dual_blob_storage_and_fact_mapping_unreviewed(client: TestClient):
    csv_content = (
        "Skill,Proficiency,Category,Years\n"
        "Python,Expert,Backend,8\n"
        "PostgreSQL,Advanced,Database,6\n"
    )
    resp = client.post(
        "/api/v1/profile/parse-document",
        headers={**local_headers(), "x-filename": "skills.csv"},
        content=csv_content.encode("utf-8"),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["media_type"] == "text/csv"
    assert data["metadata"]["format"] == "csv"
    assert data["metadata"]["row_count"] == 3
    doc_id = data["document_id"]
    doc_ver_id = data["document_version_id"]
    assert doc_id is not None
    assert doc_ver_id is not None

    # Check suggested fact types from column headers
    skill_sec = data["sections"][1]
    assert skill_sec["suggested_fact_type"] == "SKILL"
    assert "Skill: Python" in skill_sec["text"]

    # Verify dual-blob storage endpoints:
    # 1. Original CSV blob
    orig_resp = client.get(
        f"/api/v1/profile/documents/{doc_id}/versions/{doc_ver_id}/original",
        headers=local_headers(),
    )
    assert orig_resp.status_code == 200
    assert orig_resp.headers["content-type"].startswith("text/csv")
    assert orig_resp.content == csv_content.encode("utf-8")

    # 2. UTF-8 text artifact blob
    text_resp = client.get(
        f"/api/v1/profile/documents/{doc_id}/versions/{doc_ver_id}/text-artifact",
        headers=local_headers(),
    )
    assert text_resp.status_code == 200
    assert "text/plain" in text_resp.headers["content-type"]
    assert text_resp.content == data["raw_text"].encode("utf-8")

    # Map fact and verify UNREVIEWED state
    map_resp = client.post(
        "/api/v1/profile/map-fact",
        headers=local_headers(),
        json={
            "document_version_id": doc_ver_id,
            "fact_type": "SKILL",
            "value": {"skill": "Python", "category": "Backend"},
            "byte_start": skill_sec["byte_start"],
            "byte_end": skill_sec["byte_end"],
            "excerpt": skill_sec["text"],
        },
    )
    assert map_resp.status_code == 201, map_resp.text
    fact_data = map_resp.json()
    assert fact_data["verification_state"] == "UNREVIEWED"
    assert fact_data["provenance_id"] is not None

    # Verify fact transitions to USER_VERIFIED only upon deliberate user action
    fact_id = fact_data["fact_id"]
    verify_resp = client.post(f"/api/v1/facts/{fact_id}/verify", headers=local_headers())
    assert verify_resp.status_code == 200
    assert verify_resp.json()["verification_state"] == "USER_VERIFIED"


def test_xlsx_upload_dual_blob_storage_and_fact_mapping_unreviewed(client: TestClient):
    sheets = {
        "Experience": [
            [("Company", "inlineStr", "A1"), ("Role", "inlineStr", "B1"), ("Years", "inlineStr", "C1")],
            [("Acme Corp", "inlineStr", "A2"), ("Principal Engineer", "inlineStr", "B2"), ("5", "inlineStr", "C2")],
        ]
    }
    xlsx_bytes = _build_synthetic_xlsx(sheets=sheets)

    resp = client.post(
        "/api/v1/profile/parse-document",
        headers={**local_headers(), "x-filename": "history.xlsx"},
        content=xlsx_bytes,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["media_type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert data["metadata"]["format"] == "xlsx"
    doc_id = data["document_id"]
    doc_ver_id = data["document_version_id"]

    # Verify section and fact inference: Company/Role headers suggest EMPLOYMENT
    emp_sec = next(s for s in data["sections"] if s["type"] == "table_row")
    assert emp_sec["suggested_fact_type"] == "EMPLOYMENT"
    assert "Company: Acme Corp" in emp_sec["text"]

    # Verify original blob retrieval
    orig_resp = client.get(
        f"/api/v1/profile/documents/{doc_id}/versions/{doc_ver_id}/original",
        headers=local_headers(),
    )
    assert orig_resp.status_code == 200
    assert "openxmlformats-officedocument.spreadsheetml.sheet" in orig_resp.headers["content-type"]
    assert orig_resp.content == xlsx_bytes

    # Verify text artifact retrieval
    text_resp = client.get(
        f"/api/v1/profile/documents/{doc_id}/versions/{doc_ver_id}/text-artifact",
        headers=local_headers(),
    )
    assert text_resp.status_code == 200
    assert text_resp.content == data["raw_text"].encode("utf-8")

    # Map fact and verify UNREVIEWED state
    map_resp = client.post(
        "/api/v1/profile/map-fact",
        headers=local_headers(),
        json={
            "document_version_id": doc_ver_id,
            "fact_type": "EMPLOYMENT",
            "value": {"company": "Acme Corp", "role": "Principal Engineer"},
            "byte_start": emp_sec["byte_start"],
            "byte_end": emp_sec["byte_end"],
            "excerpt": emp_sec["text"],
        },
    )
    assert map_resp.status_code == 201, map_resp.text
    assert map_resp.json()["verification_state"] == "UNREVIEWED"


def test_csv_and_xlsx_parse_error_transaction_rollback(client: TestClient):
    # 1. Malformed CSV with null bytes
    bad_csv = b"Col1,Col2\x00\nVal1,Val2"
    resp_csv = client.post(
        "/api/v1/profile/parse-document",
        headers={**local_headers(), "x-filename": "bad.csv"},
        content=bad_csv,
    )
    assert resp_csv.status_code == 422
    assert "PARSE_ERROR" in resp_csv.text

    # 2. Corrupt XLSX archive
    resp_xlsx = client.post(
        "/api/v1/profile/parse-document",
        headers={**local_headers(), "x-filename": "corrupt.xlsx"},
        content=b"PK\x03\x04not a valid xlsx",
    )
    assert resp_xlsx.status_code == 422
    assert "PARSE_ERROR" in resp_xlsx.text

    # 3. Decompression bomb XLSX (>20MB)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/worksheets/sheet1.xml", b" " * (21 * 1024 * 1024))
    bomb_bytes = buf.getvalue()

    resp_bomb = client.post(
        "/api/v1/profile/parse-document",
        headers={**local_headers(), "x-filename": "bomb.xlsx"},
        content=bomb_bytes,
    )
    assert resp_bomb.status_code == 422
    assert "DECOMPRESSION_BOMB_DETECTED" in resp_bomb.text or "PARSE_ERROR" in resp_bomb.text

    # Verify zero documents or facts exist in database
    docs_resp = client.get("/api/v1/documents", headers=local_headers())
    assert docs_resp.status_code == 200
    assert len(docs_resp.json()) == 0

    facts_resp = client.get("/api/v1/facts", headers=local_headers())
    assert facts_resp.status_code == 200
    assert len(facts_resp.json()) == 0
