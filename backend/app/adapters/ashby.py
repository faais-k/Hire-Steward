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

import httpx

from backend.app.adapters.job_sources import JobSourceAdapter
from backend.app.adapters.lever import clean_control_characters, html_to_plain_text
from backend.app.domain.job_posting import (
    EMPLOYER_HANDLE_PATTERN,
    InvalidPaginationBoundsError,
    InvalidPostingPayloadError,
    NormalizedPosting,
    PublicationDateStatus,
    SourceHttpError,
    SourceRateLimitError,
    SourceTimeoutError,
)

ASHBY_SOURCE_NAME = "ashby"
DEFAULT_PAGE_LIMIT = 100


class AshbyAdapter(JobSourceAdapter):
    """Adapter for Ashby Public Job Board API."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    @property
    def source_name(self) -> str:
        return ASHBY_SOURCE_NAME

    def fetch_page(
        self, employer_handle: str, skip: int = 0, limit: int = DEFAULT_PAGE_LIMIT
    ) -> Sequence[Any] | None:
        """Fetch a single page of public job postings from Ashby API."""
        if not EMPLOYER_HANDLE_PATTERN.match(employer_handle):
            raise InvalidPostingPayloadError(
                f"Invalid employer handle '{employer_handle}'", "INVALID_HANDLE"
            )
        if skip < 0 or limit <= 0:
            raise InvalidPaginationBoundsError(
                "skip must be >= 0 and limit must be > 0", "INVALID_PAGINATION_BOUNDS"
            )

        url = f"https://api.ashbyhq.com/posting-api/job-board/{employer_handle}"
        headers = {
            "Accept": "application/json",
            "User-Agent": "Hire-Steward-Discovery/1.0 (+http://127.0.0.1:8000/docs)",
        }

        if self._client is not None:
            try:
                resp = self._client.get(url, headers=headers)
            except httpx.TimeoutException as exc:
                raise SourceTimeoutError(f"Ashby request timed out: {exc}") from exc
            except httpx.RequestError as exc:
                raise SourceHttpError(f"Ashby network error: {exc}", status_code=0) from exc
        else:
            raise NotImplementedError(
                "Live Ashby network requests are not authorized or implemented. "
                "Only mock transport replay is supported in this stage."
            )

        if resp.status_code == 429:
            retry_after = None
            raw_retry = resp.headers.get("Retry-After")
            if raw_retry and raw_retry.isdigit():
                retry_after = int(raw_retry)
            raise SourceRateLimitError(
                f"Ashby rate limit reached (HTTP 429). Retry after {retry_after}s.",
                retry_after_seconds=retry_after,
            )

        if resp.status_code == 404:
            return []

        if resp.status_code >= 400:
            raise SourceHttpError(
                f"Ashby returned HTTP {resp.status_code}: {resp.text[:200]}",
                status_code=resp.status_code,
            )

        try:
            data = resp.json()
        except Exception as exc:
            raise InvalidPostingPayloadError(
                f"Malformed JSON response from Ashby: {exc}", "MALFORMED_JSON"
            ) from exc

        if not isinstance(data, dict) or "jobs" not in data:
            raise InvalidPostingPayloadError(
                "Ashby response missing 'jobs' array", "INVALID_RESPONSE_SHAPE"
            )

        jobs = data["jobs"]
        if not isinstance(jobs, list):
            raise InvalidPostingPayloadError(
                "Ashby 'jobs' field is not a list", "INVALID_JOBS_TYPE"
            )

        if skip >= len(jobs):
            return []

        return jobs[skip : skip + limit]

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

        # Dates
        published_at_str = payload.get("publishedAt")
        published_at: datetime | None = None
        pub_status = PublicationDateStatus.UNKNOWN
        if published_at_str and isinstance(published_at_str, str):
            try:
                published_at = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
                pub_status = PublicationDateStatus.EXACT
            except ValueError:
                pub_status = PublicationDateStatus.INVALID

        # Location & Workplace type
        location = payload.get("location")
        if isinstance(location, dict):
            location = location.get("name")

        workplace_type = None
        is_remote = payload.get("isRemote")
        if is_remote is True:
            workplace_type = "remote"
        elif is_remote is False:
            workplace_type = "on-site"

        # Department / Team
        department = payload.get("department")
        team = payload.get("team")

        # Description
        raw_description = payload.get("descriptionHtml") or payload.get("descriptionPlain") or ""
        description_html = html.unescape(raw_description) if isinstance(raw_description, str) else None
        description_plain = html_to_plain_text(description_html) if description_html else ""

        canonical_url = payload.get("jobUrl") or payload.get("applyUrl")
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
            location=location,
            commitment=payload.get("employmentType"),
            team=team,
            department=department,
            level=None,
            workplace_type=workplace_type,
            description_plain=description_plain,
            description_html=description_html,
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
        """Parse a page of postings from Ashby job array or envelope."""
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
