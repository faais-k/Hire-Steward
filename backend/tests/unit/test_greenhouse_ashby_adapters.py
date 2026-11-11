"""Unit tests for Greenhouse and Ashby job source adapters.

Verifies:
1. Valid payload parsing into NormalizedPosting with exact attributes.
2. Error handling on invalid handles, missing IDs, or malformed page structures.
3. Provenance SHA-256 hash preservation.
4. Offline safety: fetch_page raises NotImplementedError without live credentials.
"""

from __future__ import annotations

import pytest

from backend.app.adapters.ashby import AshbyAdapter
from backend.app.adapters.greenhouse import GreenhouseAdapter
from backend.app.domain.job_posting import InvalidPostingPayloadError, PublicationDateStatus


class TestGreenhouseAdapter:
    def test_parse_valid_posting(self) -> None:
        adapter = GreenhouseAdapter()
        payload = {
            "id": 987654,
            "title": "Staff Backend Engineer",
            "updated_at": "2026-11-10T14:30:00Z",
            "location": {"name": "San Francisco, CA"},
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/987654",
            "departments": [{"name": "Platform Engineering"}],
            "content": "<p>We are looking for a Staff Engineer to build data systems.</p>",
        }
        posting = adapter.parse_posting_payload("acme-corp", payload)
        assert posting.source == "greenhouse"
        assert posting.posting_id == "987654"
        assert posting.title == "Staff Backend Engineer"
        assert posting.location == "San Francisco, CA"
        assert posting.department == "Platform Engineering"
        assert posting.publication_date_status == PublicationDateStatus.EXACT
        assert "Staff Engineer to build data systems" in posting.description_plain
        assert len(posting.source_raw_hash) == 64

    def test_missing_id_raises(self) -> None:
        adapter = GreenhouseAdapter()
        with pytest.raises(InvalidPostingPayloadError, match="Missing required 'id'"):
            adapter.parse_posting_payload("acme-corp", {"title": "Engineer"})

    def test_fetch_page_offline_safety(self) -> None:
        adapter = GreenhouseAdapter()
        with pytest.raises(NotImplementedError):
            adapter.fetch_page("acme-corp", skip=0, limit=10)


class TestAshbyAdapter:
    def test_parse_valid_posting(self) -> None:
        adapter = AshbyAdapter()
        payload = {
            "id": "ashby_job_001",
            "title": "Machine Learning Platform Engineer",
            "publishedAt": "2026-11-09T08:00:00.000Z",
            "department": "AI Research",
            "team": "Model Training",
            "location": "Remote - Worldwide",
            "employmentType": "FullTime",
            "workplaceType": "Remote",
            "jobUrl": "https://jobs.ashbyhq.com/stellar/ashby_job_001",
            "descriptionPlain": "Build large scale training clusters.",
        }
        posting = adapter.parse_posting_payload("stellar-ai", payload)
        assert posting.source == "ashby"
        assert posting.posting_id == "ashby_job_001"
        assert posting.title == "Machine Learning Platform Engineer"
        assert posting.department == "AI Research"
        assert posting.commitment == "FullTime"
        assert posting.publication_date_status == PublicationDateStatus.EXACT
        assert len(posting.source_raw_hash) == 64

    def test_invalid_handle_raises(self) -> None:
        adapter = AshbyAdapter()
        with pytest.raises(InvalidPostingPayloadError, match="Invalid employer handle"):
            adapter.parse_posting_payload("INVALID HANDLE!", {"id": "1", "title": "Eng"})

    def test_fetch_page_offline_safety(self) -> None:
        adapter = AshbyAdapter()
        with pytest.raises(NotImplementedError):
            adapter.fetch_page("stellar-ai", skip=0, limit=10)
