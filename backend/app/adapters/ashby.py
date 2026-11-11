"""Ashby Job Board API parser and adapter (Area C).

Supports public read-only postings from Ashby job board API:
https://api.ashbyhq.com/posting-api/job-board/{organization}
"""

from __future__ import annotations

import hashlib
import html
import json
from datetime import datetime, timezone
from typing import Any, Sequence

from backend.app.adapters.job_sources import JobSourceAdapter
from backend.app.adapters.lever import clean_control_characters, html_to_plain_text
from backend.app.domain.job_posting import (
    EMPLOYER_HANDLE_PATTERN,
    InvalidPostingPayloadError,
    NormalizedPosting,
    PublicationDateStatus,
)

ASHBY_SOURCE_NAME = "ashby"
DEFAULT_PAGE_LIMIT = 100


class AshbyAdapter(JobSourceAdapter):
    """Adapter for Ashby Public Job Board API."""

    @property
    def source_name(self) -> str:
        return ASHBY_SOURCE_NAME

    def fetch_page(
        self, employer_handle: str, skip: int, limit: int
    ) -> Sequence[Any] | None:
        """Offline-safe fetch. Live external network calls require explicit user configuration."""
        raise NotImplementedError(
            "Live network fetching is disabled by default for Ashby. Use FixtureJobSourceAdapter or supply verified source credentials."
        )

    def parse_posting_payload(
        self, employer_handle: str, payload: Any
    ) -> NormalizedPosting:
        """Parse and normalize a single Ashby job posting JSON object."""
        if not EMPLOYER_HANDLE_PATTERN.match(employer_handle):
            raise InvalidPostingPayloadError(
                f"Invalid employer handle '{employer_handle}'", "INVALID_HANDLE"
            )

        if not isinstance(payload, dict):
            raise InvalidPostingPayloadError(
                f"Payload must be a dict, got {type(payload).__name__}",
                "INVALID_PAYLOAD_TYPE",
            )

        raw_id = payload.get("id")
        if raw_id is None:
            raise InvalidPostingPayloadError("Missing required 'id' field", "MISSING_ID")
        posting_id = str(raw_id).strip()
        if not posting_id:
            raise InvalidPostingPayloadError("Empty 'id' field", "EMPTY_ID")

        title = payload.get("title")
        if not title or not isinstance(title, str) or not title.strip():
            raise InvalidPostingPayloadError("Missing or invalid 'title'", "INVALID_TITLE")
        title = clean_control_characters(title.strip())

        # Published date
        published_at_str = payload.get("publishedAt")
        published_at: datetime | None = None
        pub_status = PublicationDateStatus.UNKNOWN
        if published_at_str and isinstance(published_at_str, str):
            try:
                published_at = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
                pub_status = PublicationDateStatus.EXACT
            except ValueError:
                pub_status = PublicationDateStatus.INVALID

        # Descriptions
        desc_plain = payload.get("descriptionPlain") or ""
        desc_html = payload.get("descriptionHtml")
        if not desc_plain and desc_html:
            desc_plain = html_to_plain_text(desc_html)

        canonical_url = payload.get("jobUrl")
        apply_url = payload.get("applyUrl") or canonical_url

        canonical_json = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        source_raw_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

        return NormalizedPosting(
            source=self.source_name,
            employer_handle=employer_handle,
            posting_id=posting_id,
            title=title,
            published_at=published_at,
            publication_date_status=pub_status,
            raw_created_at_ms=int(published_at.timestamp() * 1000) if published_at else None,
            location=payload.get("location"),
            commitment=payload.get("employmentType"),
            team=payload.get("team"),
            department=payload.get("department"),
            level=None,
            workplace_type=payload.get("workplaceType"),
            description_plain=desc_plain,
            description_html=desc_html,
            lists=[],
            additional_plain=None,
            canonical_url=canonical_url,
            apply_url=apply_url,
            source_raw_hash=source_raw_hash,
        )

    def parse_listing_page(
        self,
        employer_handle: str,
        payload: Any,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> list[NormalizedPosting]:
        """Parse a page of postings from Ashby job-board response."""
        if isinstance(payload, dict) and "jobs" in payload:
            items = payload["jobs"]
        elif isinstance(payload, list):
            items = payload
        else:
            raise InvalidPostingPayloadError(
                f"Page payload must be a list or dict with 'jobs', got {type(payload).__name__}",
                "INVALID_PAGE_SHAPE",
            )

        sliced = items[skip : skip + limit] if skip > 0 else items[:limit]
        return [self.parse_posting_payload(employer_handle, p) for p in sliced]
