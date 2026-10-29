"""Unit tests for offline Lever job discovery adapter and domain models."""

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from backend.app.adapters.lever import (
    LeverPostingsAdapter,
    clean_control_characters,
    html_to_plain_text,
    validate_pagination_bounds,
)
from backend.app.domain.job_posting import (
    InvalidPaginationBoundsError,
    InvalidPostingPayloadError,
    NormalizedPosting,
    PaginationLoopError,
    PublicationDateStatus,
    deduplicate_postings,
)


FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "lever"


def load_fixture(name: str):
    with open(FIXTURES_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def adapter() -> LeverPostingsAdapter:
    return LeverPostingsAdapter()


# -----------------------------------------------------------------------------
# 1. Valid listing and detail fixtures
# -----------------------------------------------------------------------------


def test_parse_valid_listing_fixture(adapter: LeverPostingsAdapter):
    raw_data = load_fixture("valid_listing.json")
    postings = adapter.parse_listing_page("example-corp", raw_data, skip=0, limit=10)

    assert len(postings) == 2

    first = postings[0]
    assert first.source == "lever"
    assert first.employer_handle == "example-corp"
    assert first.posting_id == "lever-job-001"
    assert first.title == "Senior Backend Engineer"
    assert first.publication_date_status == PublicationDateStatus.EXACT
    assert first.raw_created_at_ms == 1700000000000
    assert first.published_at == datetime.fromtimestamp(1700000000, tz=timezone.utc)
    assert first.location == "Remote - India"
    assert first.commitment == "Full-time"
    assert first.team == "Platform Engineering"
    assert first.department == "Engineering"
    assert first.level == "Senior"
    assert first.workplace_type == "remote"
    assert "Senior Backend Engineer" in first.description_plain
    assert first.canonical_url == "https://jobs.lever.co/example-corp/lever-job-001"
    assert first.apply_url == "https://jobs.lever.co/example-corp/lever-job-001/apply"
    assert len(first.lists) == 2
    assert first.lists[0].title == "Requirements"
    assert "5+ years Python experience" in first.lists[0].items
    assert len(first.source_raw_hash) == 64

    second = postings[1]
    assert second.posting_id == "lever-job-002"
    assert second.title == "Staff Data Engineer"
    assert second.workplace_type == "hybrid"
    assert second.department is None
    assert second.lists == []


def test_parse_valid_detail_fixture(adapter: LeverPostingsAdapter):
    raw_data = load_fixture("valid_detail.json")
    posting = adapter.parse_posting_payload("example-corp", raw_data)

    assert posting.posting_id == "lever-detail-999"
    assert posting.title == "Principal Systems Architect"
    assert posting.level == "Principal"
    assert len(posting.lists) == 1
    assert posting.lists[0].title == "Core Responsibilities"
    assert "Set technical standards" in posting.lists[0].items[0]
    assert posting.canonical_url == "https://jobs.lever.co/example-corp/lever-detail-999"


# -----------------------------------------------------------------------------
# 2. Missing optional fields and malformed required fields
# -----------------------------------------------------------------------------


def test_missing_optional_fields_preserves_unknown_state(adapter: LeverPostingsAdapter):
    raw_data = load_fixture("missing_optional.json")
    posting = adapter.parse_posting_payload("example-corp", raw_data)

    assert posting.posting_id == "lever-job-minimal"
    assert posting.title == "Junior QA Specialist"
    assert posting.published_at is None
    assert posting.publication_date_status == PublicationDateStatus.UNKNOWN
    assert posting.raw_created_at_ms is None
    assert posting.location is None
    assert posting.commitment is None
    assert posting.team is None
    assert posting.department is None
    assert posting.level is None
    assert posting.workplace_type is None
    assert posting.canonical_url is None
    assert posting.apply_url is None
    assert posting.lists == []
    assert posting.additional_plain is None
    assert "Review testing plans" in posting.description_plain


@pytest.mark.parametrize(
    ("bad_payload", "expected_code"),
    [
        ({}, "MISSING_POSTING_ID"),
        ({"id": None, "text": "Engineer"}, "MISSING_POSTING_ID"),
        ({"id": 12345, "text": "Engineer"}, "INVALID_POSTING_ID_TYPE"),
        ({"id": "", "text": "Engineer"}, "EMPTY_POSTING_ID"),
        ({"id": "   ", "text": "Engineer"}, "EMPTY_POSTING_ID"),
        ({"id": "job-1"}, "MISSING_JOB_TITLE"),
        ({"id": "job-1", "text": None}, "MISSING_JOB_TITLE"),
        ({"id": "job-1", "text": 999}, "INVALID_JOB_TITLE_TYPE"),
        ({"id": "job-1", "text": ""}, "EMPTY_JOB_TITLE"),
        ({"id": "job-1", "text": "   "}, "EMPTY_JOB_TITLE"),
    ],
)
def test_malformed_required_fields_raise_error(
    adapter: LeverPostingsAdapter, bad_payload: dict, expected_code: str
):
    with pytest.raises(InvalidPostingPayloadError) as exc_info:
        adapter.parse_posting_payload("example-corp", bad_payload)
    assert exc_info.value.code == expected_code


@pytest.mark.parametrize(
    "bad_handle",
    ["", "   ", "INVALID/HANDLE", "handle..corp", "../escape", "example corp", "127.0.0.1/evil"],
)
def test_invalid_employer_handle_raises_error(adapter: LeverPostingsAdapter, bad_handle: str):
    with pytest.raises(InvalidPostingPayloadError) as exc_info:
        adapter.parse_posting_payload(bad_handle, {"id": "1", "text": "Job"})
    assert exc_info.value.code == "INVALID_EMPLOYER_HANDLE"


# -----------------------------------------------------------------------------
# 3. Empty results and unexpected response shapes
# -----------------------------------------------------------------------------


def test_empty_results_returns_empty_list(adapter: LeverPostingsAdapter):
    assert adapter.parse_listing_page("example-corp", [], skip=0, limit=10) == []


@pytest.mark.parametrize(
    "bad_page_shape",
    [
        {"error": "not found"},
        "invalid string response",
        12345,
        None,
    ],
)
def test_unexpected_page_shape_raises_error(adapter: LeverPostingsAdapter, bad_page_shape):
    with pytest.raises(InvalidPostingPayloadError) as exc_info:
        adapter.parse_listing_page("example-corp", bad_page_shape, skip=0, limit=10)
    assert exc_info.value.code == "INVALID_PAGE_SHAPE"


def test_non_dict_posting_payload_raises_error(adapter: LeverPostingsAdapter):
    with pytest.raises(InvalidPostingPayloadError) as exc_info:
        adapter.parse_posting_payload("example-corp", "not a json object")
    assert exc_info.value.code == "INVALID_PAYLOAD_TYPE"


# -----------------------------------------------------------------------------
# 4. Invalid, missing, or out-of-range timestamps
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw_timestamp", "expected_status", "expected_dt", "expected_ms"),
    [
        (None, PublicationDateStatus.UNKNOWN, None, None),
        (1700000000000, PublicationDateStatus.EXACT, datetime.fromtimestamp(1700000000, tz=timezone.utc), 1700000000000),
        (-5000, PublicationDateStatus.INVALID, None, -5000),
        (0, PublicationDateStatus.INVALID, None, 0),
        (100, PublicationDateStatus.INVALID, None, 100),
        (9999999999999999, PublicationDateStatus.INVALID, None, 9999999999999999),
        ("2026-10-28", PublicationDateStatus.INVALID, None, None),
        (True, PublicationDateStatus.INVALID, None, None),
        ({"ms": 1700000000000}, PublicationDateStatus.INVALID, None, None),
    ],
)
def test_timestamps_handling(
    adapter: LeverPostingsAdapter, raw_timestamp, expected_status, expected_dt, expected_ms
):
    payload = {"id": "ts-job", "text": "Timestamp Job", "createdAt": raw_timestamp}
    posting = adapter.parse_posting_payload("example-corp", payload)

    assert posting.publication_date_status == expected_status
    assert posting.published_at == expected_dt
    assert posting.raw_created_at_ms == expected_ms


# -----------------------------------------------------------------------------
# 5. Invalid URLs and unexpected field types
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bad_url", "expected_code"),
    [
        ("http://insecure.example.com/job", "INSECURE_URL_SCHEME"),
        ("javascript:alert(1)", "INSECURE_URL_SCHEME"),
        ("data:text/html,evil", "INSECURE_URL_SCHEME"),
        ("file:///etc/passwd", "INSECURE_URL_SCHEME"),
        ("https://user:password@example.com/job", "CREDENTIALS_IN_URL"),
        ("https:///missing-host", "MISSING_HOSTNAME"),
        (12345, "INVALID_URL_TYPE"),
    ],
)
def test_insecure_or_malformed_urls_rejected(
    adapter: LeverPostingsAdapter, bad_url, expected_code
):
    payload = {
        "id": "url-job",
        "text": "URL Test Job",
        "hostedUrl": bad_url,
    }
    with pytest.raises(InvalidPostingPayloadError) as exc_info:
        adapter.parse_posting_payload("example-corp", payload)
    assert exc_info.value.code == expected_code


@pytest.mark.parametrize(
    ("bad_field_payload", "expected_code"),
    [
        ({"id": "j1", "text": "Job", "categories": "string-not-dict"}, "INVALID_CATEGORIES_TYPE"),
        ({"id": "j1", "text": "Job", "categories": {"location": 123}}, "INVALID_FIELD_TYPE"),
        ({"id": "j1", "text": "Job", "categories": {"team": ["list", "not", "str"]}}, "INVALID_FIELD_TYPE"),
        ({"id": "j1", "text": "Job", "workplaceType": 999}, "INVALID_FIELD_TYPE"),
        ({"id": "j1", "text": "Job", "descriptionPlain": 456}, "INVALID_FIELD_TYPE"),
        ({"id": "j1", "text": "Job", "lists": "not a list"}, "INVALID_LISTS_TYPE"),
        ({"id": "j1", "text": "Job", "lists": ["not an object"]}, "INVALID_LIST_ITEM_TYPE"),
        ({"id": "j1", "text": "Job", "lists": [{"content": "no text title"}]}, "INVALID_LIST_TITLE"),
    ],
)
def test_unexpected_field_types_rejected(
    adapter: LeverPostingsAdapter, bad_field_payload: dict, expected_code: str
):
    with pytest.raises(InvalidPostingPayloadError) as exc_info:
        adapter.parse_posting_payload("example-corp", bad_field_payload)
    assert exc_info.value.code == expected_code


# -----------------------------------------------------------------------------
# 6. Description normalization and safe handling of hostile content
# -----------------------------------------------------------------------------


def test_description_normalization_preserves_content_and_structure():
    html_input = (
        "<div><p>Hello &amp; welcome to <strong>Company</strong>!</p>"
        "<p>Responsibilities:</p>"
        "<ul><li>First task &lt;important&gt;</li><li>Second task &quot;quoted&quot;</li></ul></div>"
    )
    plain = html_to_plain_text(html_input)

    assert "Hello & welcome to Company!" in plain
    assert "Responsibilities:" in plain
    assert "First task <important>" in plain
    assert 'Second task "quoted"' in plain
    assert "<div>" not in plain
    assert "<strong>" not in plain
    assert "<ul>" not in plain
    assert "<li>" not in plain


def test_hostile_content_safe_handling(adapter: LeverPostingsAdapter):
    raw_data = load_fixture("hostile_content.json")
    posting = adapter.parse_posting_payload("example-corp", raw_data)

    # Title is stripped of control characters; script tag in title remains literal text or sanitized
    assert "Security Analyst" in posting.title

    # In HTML description: <script> and <style> blocks are stripped completely
    assert "evilCode" not in posting.description_plain
    assert ".hidden" not in posting.description_plain
    assert "Legitimate job intro." in posting.description_plain

    # Prompt injection is treated as plain data, not interpreted
    assert "SYSTEM PROMPT:" in posting.description_plain

    # Null bytes and unprintable control characters in categories.location stripped
    assert "\x00" not in posting.location
    assert "\x07" not in posting.location
    assert posting.location == "Remote"


# -----------------------------------------------------------------------------
# 7. Deduplication and conflict preservation
# -----------------------------------------------------------------------------


def test_deduplicate_identical_postings(adapter: LeverPostingsAdapter):
    payload = load_fixture("valid_detail.json")
    p1 = adapter.parse_posting_payload("example-corp", payload)
    p2 = adapter.parse_posting_payload("example-corp", payload)

    result = deduplicate_postings([p1, p2])

    assert len(result.unique_postings) == 1
    assert result.duplicates_count == 1
    assert result.conflicts == []


def test_deduplicate_conflicting_observations_preserves_both(adapter: LeverPostingsAdapter):
    payload1 = load_fixture("valid_detail.json")
    payload2 = dict(payload1)
    payload2["text"] = "Modified Architect Title"

    p1 = adapter.parse_posting_payload("example-corp", payload1)
    p2 = adapter.parse_posting_payload("example-corp", payload2)

    result = deduplicate_postings([p1, p2])

    assert len(result.unique_postings) == 1
    assert result.unique_postings[0].title == "Principal Systems Architect"  # First retained
    assert result.duplicates_count == 0
    assert len(result.conflicts) == 1
    assert result.conflicts[0].key == ("lever", "example-corp", "lever-detail-999")
    assert result.conflicts[0].existing.title == "Principal Systems Architect"
    assert result.conflicts[0].incoming.title == "Modified Architect Title"
    assert result.conflicts[0].reason == "PAYLOAD_CONTENT_MISMATCH"


def test_no_cross_source_or_cross_employer_deduplication(adapter: LeverPostingsAdapter):
    payload = load_fixture("valid_detail.json")
    p_corp1 = adapter.parse_posting_payload("corp-one", payload)
    p_corp2 = adapter.parse_posting_payload("corp-two", payload)

    result = deduplicate_postings([p_corp1, p_corp2])

    # Different employers with the same posting ID are NOT deduplicated or merged
    assert len(result.unique_postings) == 2
    assert result.duplicates_count == 0
    assert result.conflicts == []


# -----------------------------------------------------------------------------
# 8. Pagination boundaries, limits, and loop detection
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("skip", "limit", "expected_code"),
    [
        (-1, 50, "INVALID_SKIP"),
        (0, 0, "INVALID_LIMIT"),
        (0, -5, "INVALID_LIMIT"),
        (0, 101, "INVALID_LIMIT"),
        ("0", 50, "INVALID_SKIP"),
        (0, "50", "INVALID_LIMIT"),
        (True, 50, "INVALID_SKIP"),
        (0, False, "INVALID_LIMIT"),
    ],
)
def test_pagination_bounds_validation(skip, limit, expected_code):
    with pytest.raises(InvalidPaginationBoundsError) as exc_info:
        validate_pagination_bounds(skip, limit)
    assert exc_info.value.code == expected_code


def test_page_limit_exceeded_raises_error(adapter: LeverPostingsAdapter):
    raw_data = load_fixture("valid_listing.json")  # has 2 items
    with pytest.raises(InvalidPostingPayloadError) as exc_info:
        adapter.parse_listing_page("example-corp", raw_data, skip=0, limit=1)  # limit=1 but got 2
    assert exc_info.value.code == "PAGE_LIMIT_EXCEEDED"


def test_consume_synthetic_feed_multi_page(adapter: LeverPostingsAdapter):
    raw_data = load_fixture("valid_listing.json")  # 2 items
    page1 = [raw_data[0]]  # limit 1
    page2 = [raw_data[1]]  # limit 1
    page3 = []             # empty terminating page

    postings = adapter.consume_synthetic_feed(
        "example-corp", [page1, page2, page3], limit=1
    )

    assert len(postings) == 2
    assert postings[0].posting_id == "lever-job-001"
    assert postings[1].posting_id == "lever-job-002"


def test_consume_synthetic_feed_detects_infinite_loop(adapter: LeverPostingsAdapter):
    raw_data = load_fixture("valid_listing.json")
    page1 = [raw_data[0]]
    page2 = [raw_data[0]]  # Repeats item from page 1!

    with pytest.raises(PaginationLoopError) as exc_info:
        adapter.consume_synthetic_feed("example-corp", [page1, page2], limit=1)
    assert exc_info.value.code == "PAGINATION_CYCLE_DETECTED"


def test_consume_synthetic_feed_detects_unexpected_page_after_termination(
    adapter: LeverPostingsAdapter,
):
    raw_data = load_fixture("valid_listing.json")
    page1 = []             # Early empty page signals termination
    page2 = [raw_data[0]]  # Non-empty page follows

    with pytest.raises(InvalidPaginationBoundsError) as exc_info:
        adapter.consume_synthetic_feed("example-corp", [page1, page2], limit=10)
    assert exc_info.value.code == "UNEXPECTED_PAGE_AFTER_TERMINATION"


def test_consume_synthetic_feed_with_duplicate_postings_on_same_page(
    adapter: LeverPostingsAdapter,
):
    raw_data = load_fixture("valid_listing.json")
    # Ordinary page that contains duplicates within the page
    page1 = [raw_data[0], raw_data[1], raw_data[0]]  # 3 items, limit=3

    # Should NOT raise PaginationLoopError or stop prematurely
    postings = adapter.consume_synthetic_feed(
        "example-corp", [page1], limit=3
    )
    assert len(postings) == 3

    # Deduplication properly cleans the feed
    deduped = deduplicate_postings(postings)
    assert len(deduped.unique_postings) == 2
    assert deduped.duplicates_count == 1
    assert deduped.conflicts == []


def test_consume_synthetic_feed_with_overlapping_postings_across_pages(
    adapter: LeverPostingsAdapter,
):
    raw_data = load_fixture("valid_listing.json")
    item1 = raw_data[0]
    item2 = raw_data[1]
    item3 = dict(raw_data[0])
    item3["id"] = "lever-job-003"
    item3["text"] = "Third Job"

    # Due to offset shift, item2 appears on both page 1 and page 2
    page1 = [item1, item2]
    page2 = [item2, item3]
    page3 = []

    postings = adapter.consume_synthetic_feed(
        "example-corp", [page1, page2, page3], limit=2
    )
    assert len(postings) == 4  # Raw observations collected

    deduped = deduplicate_postings(postings)
    assert len(deduped.unique_postings) == 3
    assert deduped.duplicates_count == 1
    assert deduped.conflicts == []


@pytest.mark.parametrize(
    ("bad_url", "expected_code"),
    [
        ("https://example.com/job\x00evil", "INVALID_URL_CHARACTERS"),
        ("https://example.com/job evil", "INVALID_URL_CHARACTERS"),
        ("https://example.com/job\tpath", "INVALID_URL_CHARACTERS"),
        ("https://example.com/job<script>", "INVALID_URL_CHARACTERS"),
        ('https://example.com/job"evil', "INVALID_URL_CHARACTERS"),
    ],
)
def test_url_whitespace_and_invalid_characters(
    adapter: LeverPostingsAdapter, bad_url: str, expected_code: str
):
    payload = {"id": "url-test", "text": "URL Test", "hostedUrl": bad_url}
    with pytest.raises(InvalidPostingPayloadError) as exc_info:
        adapter.parse_posting_payload("example-corp", payload)
    assert exc_info.value.code == expected_code


def test_html_obfuscation_and_unclosed_tags(adapter: LeverPostingsAdapter):
    # Null byte inside script tag, closed script, SVG, iframe, event handlers
    html_input = (
        "<div>"
        "<\x00script>alert('null-byte-xss')</script>"
        "<script src='https://evil.example.com/xss.js'></script>"
        "<svg onload=\"alert('svg')\">SVG Diagram</svg>"
        "<iframe src='javascript:alert(1)'>iFrame Text</iframe>"
        "<img src=x onerror=\"alert('img')\">"
        "<p>Safe description text.</p>"
        "</div>"
    )
    plain = html_to_plain_text(html_input)

    assert "alert" not in plain
    assert "evil.example.com" not in plain
    assert "Safe description text." in plain
    assert "SVG Diagram" in plain


def test_untrusted_html_is_retained_as_untrusted(adapter: LeverPostingsAdapter):
    raw_payload = {
        "id": "untrusted-html-job",
        "text": "Frontend Security Engineer",
        "description": "<p>We build web apps.</p><script>alert('raw')</script>",
        "hostedUrl": "https://jobs.lever.co/example-corp/untrusted-html-job",
    }
    posting = adapter.parse_posting_payload("example-corp", raw_payload)

    # description_plain strips the script
    assert "alert" not in posting.description_plain
    assert "We build web apps." in posting.description_plain

    # description_html preserves raw source HTML (with null bytes stripped)
    # and is explicitly untrusted
    assert posting.description_html is not None
    assert "<script>alert('raw')</script>" in posting.description_html


@pytest.mark.parametrize(
    ("html_input", "expected_plain", "should_not_contain"),
    [
        # 1. Complete script block
        (
            "<p>Intro</p><script>alert('complete-script');</script><p>Outro</p>",
            "Intro\n\nOutro",
            "alert",
        ),
        # 2. Complete style block
        (
            "<style>body { color: red; }</style><p>Content text</p>",
            "Content text",
            "color: red",
        ),
        # 3. Slash-terminated script WITHOUT closing tag.
        # In HTML, <script> is a non-void element. A trailing slash does NOT self-close it;
        # the unclosed start tag consumes all following content until </script> or EOF (\Z).
        (
            "<script src='x.js' /><p>Text</p>",
            "",
            "Text",
        ),
        # 4. Slash-terminated script WITH explicit closing </script> tag.
        # The script element correctly terminates at </script>, allowing following text to render.
        (
            "<script src='x.js' /></script><p>Text</p>",
            "Text",
            "x.js",
        ),
        # 5. Slash-terminated script with inner text and explicit closing </script> tag.
        (
            "<p>Intro</p><script src='x.js' /><p>Inner</p></script><p>Outro</p>",
            "Intro\n\nOutro",
            "Inner",
        ),
        # 6. Slash-terminated style WITHOUT closing tag.
        # In HTML, <style> is a non-void element; trailing slash does NOT self-close.
        (
            "<style href='x.css' /><p>Text</p>",
            "",
            "Text",
        ),
        # 7. Slash-terminated style WITH explicit closing </style> tag.
        (
            "<style href='x.css' /></style><p>Text</p>",
            "Text",
            "x.css",
        ),
        # 8. Slash-terminated style with inner text and explicit closing </style> tag.
        (
            "<p>Intro</p><style href='x.css' /><p>Inner</p></style><p>Outro</p>",
            "Intro\n\nOutro",
            "Inner",
        ),
        # 9. Unclosed script block at end
        (
            "<p>Job opening</p><script>alert('unclosed'); console.log('payload');",
            "Job opening",
            "alert",
        ),
        # 10. Unclosed style block at end
        (
            "<p>Job opening</p><style>body { background: black; font-size: 14px;",
            "Job opening",
            "background: black",
        ),
        # 11. Null-byte-obfuscated script tag
        (
            "<p>Before</p><\x00script>alert('null-byte');</script><p>After</p>",
            "Before\n\nAfter",
            "alert",
        ),
        # 12. HTML entities that decode into tag-looking plain text
        (
            "<p>Requirements: &lt;script&gt;alert(1)&lt;/script&gt; knowledge</p>",
            "Requirements: <script>alert(1)</script> knowledge",
            "&lt;",
        ),
    ],
)
def test_html_to_plain_text_script_and_style_matrix(
    html_input: str, expected_plain: str, should_not_contain: str
):
    result = html_to_plain_text(html_input)
    assert result == expected_plain
    if should_not_contain:
        assert should_not_contain not in result
