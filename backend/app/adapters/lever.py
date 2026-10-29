"""Lever Postings API (v0) response parser and offline paginator."""

from collections.abc import Sequence
from datetime import datetime, timezone
import hashlib
import html
import json
import re
from typing import Any
import unicodedata

from backend.app.adapters.job_sources import JobSourceAdapter
from backend.app.domain.job_posting import (
    EMPLOYER_HANDLE_PATTERN,
    InvalidPaginationBoundsError,
    InvalidPostingPayloadError,
    NormalizedPosting,
    PaginationLoopError,
    PostingListSection,
    PublicationDateStatus,
)


LEVER_SOURCE_NAME = "lever"
DEFAULT_PAGE_LIMIT = 100
MAX_PAGE_LIMIT = 100
MIN_VALID_TIMESTAMP_MS = 946684800000  # 2000-01-01T00:00:00Z
MAX_VALID_TIMESTAMP_MS = 4102444800000  # 2100-01-01T00:00:00Z

# In standard HTML parsing, <script> and <style> are non-void elements. A trailing
# slash (e.g. <script ... />) does NOT self-close them. Any start tag consumes
# everything until the matching end tag (</script> or </style>), or to EOF (\Z) if unclosed.
SCRIPT_STYLE_PATTERN = re.compile(
    r"<(script|style)[^>]*>(?:.*?</\1>|.*?\Z)",
    re.IGNORECASE | re.DOTALL,
)
TAG_BREAK_PATTERN = re.compile(r"<\s*/?\s*(?:p|br|div|li|h[1-6]|tr)[^>]*>", re.IGNORECASE)
TAG_ANY_PATTERN = re.compile(r"<[^>]+>")
LI_ITEM_PATTERN = re.compile(
    r"<\s*li[^>]*>(.*?)<\s*/\s*li\s*>", re.IGNORECASE | re.DOTALL
)


def clean_control_characters(text: str) -> str:
    """Strip ASCII control characters except tab, newline, and carriage return, and normalize NFC."""
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return unicodedata.normalize("NFC", cleaned)


def html_to_plain_text(html_content: str) -> str:
    """Convert HTML into formatted plain text, stripping scripts and tags.

    Note: This derives safe plain text for matching and display. The original
    HTML (description_html) remains untrusted raw data and must not be rendered
    directly in a browser without strict frontend-specific sanitization.
    """
    if not html_content:
        return ""
    cleaned_input = clean_control_characters(html_content)
    without_scripts = SCRIPT_STYLE_PATTERN.sub("", cleaned_input)
    with_breaks = TAG_BREAK_PATTERN.sub("\n", without_scripts)
    without_tags = TAG_ANY_PATTERN.sub("", with_breaks)
    unescaped = html.unescape(without_tags)
    cleaned = clean_control_characters(unescaped)
    collapsed = re.sub(r"\n{3,}", "\n\n", cleaned)
    return collapsed.strip()


def extract_bullet_items(content_html: str) -> list[str]:
    """Extract bullet items from an HTML list section."""
    if not content_html:
        return []
    matches = LI_ITEM_PATTERN.findall(content_html)
    if matches:
        items: list[str] = []
        for match in matches:
            text = html_to_plain_text(match)
            if text:
                items.append(text)
        return items

    plain = html_to_plain_text(content_html)
    return [line.strip() for line in plain.splitlines() if line.strip()]


def validate_pagination_bounds(
    skip: int, limit: int, max_limit: int = MAX_PAGE_LIMIT
) -> tuple[int, int]:
    """Validate that skip and limit parameters meet documented pagination boundaries."""
    if type(skip) is not int or skip < 0:
        raise InvalidPaginationBoundsError(
            f"skip must be an integer >= 0, got {skip!r}", "INVALID_SKIP"
        )
    if type(limit) is not int or limit <= 0 or limit > max_limit:
        raise InvalidPaginationBoundsError(
            f"limit must be an integer between 1 and {max_limit}, got {limit!r}",
            "INVALID_LIMIT",
        )
    return skip, limit


class LeverPostingsAdapter:
    """Source adapter for Lever Postings API v0 public feeds."""

    def __init__(self, source_name: str = LEVER_SOURCE_NAME) -> None:
        self._source_name = source_name

    @property
    def source_name(self) -> str:
        return self._source_name

    def fetch_page(
        self, employer_handle: str, skip: int, limit: int
    ) -> Sequence[Any] | None:
        """Live fetching is prohibited and disabled under Phase 0 exit gates.

        Raises NotImplementedError directing callers to use FixtureJobSourceAdapter.
        """
        raise NotImplementedError(
            f"Live fetching for source '{self.source_name}' is not authorized or implemented. "
            "Lever remains in NEEDS_REVIEW status. Use FixtureJobSourceAdapter with synthetic fixtures."
        )

    def parse_posting_payload(
        self, employer_handle: str, payload: Any
    ) -> NormalizedPosting:
        """Parse and normalize a single raw posting JSON object from Lever.

        Guarantees:
        - Rejects invalid payload types, malformed required fields, and unexpected types.
        - Preserves unknown or invalid timestamps as unknown rather than inventing dates.
        - Cleans text and strips hostile HTML/scripts.
        - Calculates canonical SHA-256 payload hash for exact provenance tracking.
        - Never infers compensation, sponsorship, or seniority.
        """
        if not isinstance(employer_handle, str) or not EMPLOYER_HANDLE_PATTERN.fullmatch(
            employer_handle
        ):
            raise InvalidPostingPayloadError(
                f"Invalid employer handle: {employer_handle!r}",
                "INVALID_EMPLOYER_HANDLE",
            )

        if not isinstance(payload, dict):
            raise InvalidPostingPayloadError(
                f"Posting payload must be a JSON object, got {type(payload).__name__}",
                "INVALID_PAYLOAD_TYPE",
            )

        # 1. Posting ID (Required string)
        raw_id = payload.get("id")
        if raw_id is None:
            raise InvalidPostingPayloadError(
                "Missing required field 'id'", "MISSING_POSTING_ID"
            )
        if not isinstance(raw_id, str):
            raise InvalidPostingPayloadError(
                f"'id' must be a string, got {type(raw_id).__name__}",
                "INVALID_POSTING_ID_TYPE",
            )
        posting_id = raw_id.strip()
        if not posting_id:
            raise InvalidPostingPayloadError(
                "'id' cannot be blank or whitespace", "EMPTY_POSTING_ID"
            )

        # 2. Title / text (Required string)
        raw_title = payload.get("text")
        if raw_title is None:
            raise InvalidPostingPayloadError(
                "Missing required field 'text'", "MISSING_JOB_TITLE"
            )
        if not isinstance(raw_title, str):
            raise InvalidPostingPayloadError(
                f"'text' must be a string, got {type(raw_title).__name__}",
                "INVALID_JOB_TITLE_TYPE",
            )
        title = clean_control_characters(raw_title).strip()
        if not title:
            raise InvalidPostingPayloadError(
                "'text' cannot be blank or whitespace", "EMPTY_JOB_TITLE"
            )

        # 3. Publication timestamp (createdAt in epoch milliseconds)
        raw_created_at = payload.get("createdAt")
        published_at: datetime | None = None
        publication_date_status: PublicationDateStatus = (
            PublicationDateStatus.UNKNOWN
        )
        raw_created_at_ms: int | None = None

        if raw_created_at is None:
            publication_date_status = PublicationDateStatus.UNKNOWN
        elif type(raw_created_at) is int:
            raw_created_at_ms = raw_created_at
            if (
                MIN_VALID_TIMESTAMP_MS
                <= raw_created_at
                <= MAX_VALID_TIMESTAMP_MS
            ):
                published_at = datetime.fromtimestamp(
                    raw_created_at / 1000.0, tz=timezone.utc
                )
                publication_date_status = PublicationDateStatus.EXACT
            else:
                publication_date_status = PublicationDateStatus.INVALID
        else:
            publication_date_status = PublicationDateStatus.INVALID

        # 4. Descriptions
        raw_desc_plain = payload.get("descriptionPlain")
        raw_desc_html = payload.get("description")

        if raw_desc_plain is not None and not isinstance(raw_desc_plain, str):
            raise InvalidPostingPayloadError(
                f"'descriptionPlain' must be a string if provided, got {type(raw_desc_plain).__name__}",
                "INVALID_FIELD_TYPE",
            )
        if raw_desc_html is not None and not isinstance(raw_desc_html, str):
            raise InvalidPostingPayloadError(
                f"'description' must be a string if provided, got {type(raw_desc_html).__name__}",
                "INVALID_FIELD_TYPE",
            )

        if raw_desc_plain and raw_desc_plain.strip():
            description_plain = clean_control_characters(raw_desc_plain).strip()
        elif raw_desc_html and raw_desc_html.strip():
            description_plain = html_to_plain_text(raw_desc_html)
        else:
            description_plain = ""

        description_html = (
            clean_control_characters(raw_desc_html)
            if raw_desc_html is not None
            else None
        )

        # 5. Additional closing text
        raw_additional_plain = payload.get("additionalPlain")
        raw_additional = payload.get("additional")

        if raw_additional_plain is not None and not isinstance(
            raw_additional_plain, str
        ):
            raise InvalidPostingPayloadError(
                f"'additionalPlain' must be a string if provided, got {type(raw_additional_plain).__name__}",
                "INVALID_FIELD_TYPE",
            )
        if raw_additional is not None and not isinstance(raw_additional, str):
            raise InvalidPostingPayloadError(
                f"'additional' must be a string if provided, got {type(raw_additional).__name__}",
                "INVALID_FIELD_TYPE",
            )

        if raw_additional_plain and raw_additional_plain.strip():
            additional_plain = clean_control_characters(
                raw_additional_plain
            ).strip()
        elif raw_additional and raw_additional.strip():
            additional_plain = html_to_plain_text(raw_additional)
        else:
            additional_plain = None

        # 6. Categories (metadata object)
        raw_categories = payload.get("categories")
        location: str | None = None
        commitment: str | None = None
        team: str | None = None
        department: str | None = None
        level: str | None = None

        if raw_categories is not None:
            if not isinstance(raw_categories, dict):
                raise InvalidPostingPayloadError(
                    f"'categories' must be an object if provided, got {type(raw_categories).__name__}",
                    "INVALID_CATEGORIES_TYPE",
                )

            for key in ["location", "commitment", "team", "department", "level"]:
                val = raw_categories.get(key)
                if val is not None:
                    if not isinstance(val, str):
                        raise InvalidPostingPayloadError(
                            f"'categories.{key}' must be a string, got {type(val).__name__}",
                            "INVALID_FIELD_TYPE",
                        )
                    cleaned_val = clean_control_characters(val).strip()
                    if cleaned_val:
                        if key == "location":
                            location = cleaned_val
                        elif key == "commitment":
                            commitment = cleaned_val
                        elif key == "team":
                            team = cleaned_val
                        elif key == "department":
                            department = cleaned_val
                        elif key == "level":
                            level = cleaned_val

        # 7. Workplace type
        raw_workplace = payload.get("workplaceType")
        workplace_type: str | None = None
        if raw_workplace is not None:
            if not isinstance(raw_workplace, str):
                raise InvalidPostingPayloadError(
                    f"'workplaceType' must be a string, got {type(raw_workplace).__name__}",
                    "INVALID_FIELD_TYPE",
                )
            cleaned_wp = clean_control_characters(raw_workplace).strip()
            if cleaned_wp:
                workplace_type = cleaned_wp

        # 8. Structured Lists
        raw_lists = payload.get("lists")
        parsed_lists: list[PostingListSection] = []
        if raw_lists is not None:
            if not isinstance(raw_lists, list):
                raise InvalidPostingPayloadError(
                    f"'lists' must be an array if provided, got {type(raw_lists).__name__}",
                    "INVALID_LISTS_TYPE",
                )
            for idx, item in enumerate(raw_lists):
                if not isinstance(item, dict):
                    raise InvalidPostingPayloadError(
                        f"'lists[{idx}]' must be an object, got {type(item).__name__}",
                        "INVALID_LIST_ITEM_TYPE",
                    )
                list_title = item.get("text")
                if list_title is None or not isinstance(list_title, str):
                    raise InvalidPostingPayloadError(
                        f"'lists[{idx}].text' must be a string",
                        "INVALID_LIST_TITLE",
                    )
                cleaned_title = clean_control_characters(list_title).strip()
                if not cleaned_title:
                    raise InvalidPostingPayloadError(
                        f"'lists[{idx}].text' cannot be empty",
                        "EMPTY_LIST_TITLE",
                    )

                list_content = item.get("content")
                if list_content is not None and not isinstance(list_content, str):
                    raise InvalidPostingPayloadError(
                        f"'lists[{idx}].content' must be a string if provided",
                        "INVALID_LIST_CONTENT",
                    )
                bullet_items = (
                    extract_bullet_items(list_content) if list_content else []
                )
                parsed_lists.append(
                    PostingListSection(title=cleaned_title, items=bullet_items)
                )

        # 9. URLs (hostedUrl, applyUrl)
        canonical_url = payload.get("hostedUrl")
        apply_url = payload.get("applyUrl")

        if canonical_url is not None and not isinstance(canonical_url, str):
            raise InvalidPostingPayloadError(
                f"'hostedUrl' must be a string, got {type(canonical_url).__name__}",
                "INVALID_URL_TYPE",
            )
        if apply_url is not None and not isinstance(apply_url, str):
            raise InvalidPostingPayloadError(
                f"'applyUrl' must be a string, got {type(apply_url).__name__}",
                "INVALID_URL_TYPE",
            )

        # 10. Canonical payload hash for source provenance
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
            publication_date_status=publication_date_status,
            raw_created_at_ms=raw_created_at_ms,
            location=location,
            commitment=commitment,
            team=team,
            department=department,
            level=level,
            workplace_type=workplace_type,
            description_plain=description_plain,
            description_html=description_html,
            lists=parsed_lists,
            additional_plain=additional_plain,
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
        """Parse a page of postings returned by the Lever listing endpoint."""
        validate_pagination_bounds(skip, limit)

        if not isinstance(payload, list):
            raise InvalidPostingPayloadError(
                f"Page payload must be a JSON array, got {type(payload).__name__}",
                "INVALID_PAGE_SHAPE",
            )

        if len(payload) > limit:
            raise InvalidPostingPayloadError(
                f"Page returned {len(payload)} items, exceeding requested limit {limit}",
                "PAGE_LIMIT_EXCEEDED",
            )

        return [
            self.parse_posting_payload(employer_handle, item)
            for item in payload
        ]

    def consume_synthetic_feed(
        self,
        employer_handle: str,
        pages: Sequence[Any],
        limit: int = DEFAULT_PAGE_LIMIT,
        max_pages: int = 50,
    ) -> list[NormalizedPosting]:
        """Consume an offline sequence of paginated pages with loop detection and boundary checks.

        Guarantees:
        - Detects cycles / repeated postings across pages to prevent infinite loops.
        - Respects page count bounds.
        - Halts on empty pages or pages with fewer items than limit.
        - Does not prematurely halt on duplicate postings within an ordinary page or
          ordinary offset shifts across pages.
        """
        all_postings: list[NormalizedPosting] = []
        seen_posting_ids: set[str] = set()
        seen_page_signatures: set[tuple[str, ...]] = set()
        terminated_early = False

        for page_idx, page_payload in enumerate(pages):
            if page_idx >= max_pages:
                raise InvalidPaginationBoundsError(
                    f"Exceeded maximum page count of {max_pages}",
                    "MAX_PAGES_EXCEEDED",
                )

            skip = page_idx * limit
            postings = self.parse_listing_page(
                employer_handle, page_payload, skip=skip, limit=limit
            )

            if terminated_early and postings:
                raise InvalidPaginationBoundsError(
                    f"Received non-empty page at index {page_idx} after previous page signaled termination",
                    "UNEXPECTED_PAGE_AFTER_TERMINATION",
                )

            if not postings:
                terminated_early = True
                continue

            page_signature = tuple(p.posting_id for p in postings)
            if page_signature in seen_page_signatures:
                raise PaginationLoopError(
                    f"Detected cycle in pagination: page {page_idx} repeated a previously seen page signature",
                    "PAGINATION_CYCLE_DETECTED",
                )
            seen_page_signatures.add(page_signature)

            # Check if this page introduces ANY new postings not seen in prior pages.
            # If all postings on page_idx > 0 were already seen in prior pages,
            # pagination is cycling without making any forward progress.
            new_ids_on_page = {p.posting_id for p in postings} - seen_posting_ids
            if page_idx > 0 and not new_ids_on_page:
                raise PaginationLoopError(
                    f"Detected cycle in pagination: page {page_idx} produced zero new postings",
                    "PAGINATION_CYCLE_DETECTED",
                )

            for posting in postings:
                seen_posting_ids.add(posting.posting_id)
                all_postings.append(posting)

            if len(postings) < limit:
                terminated_early = True

        return all_postings

LeverJobSourceAdapter = LeverPostingsAdapter
