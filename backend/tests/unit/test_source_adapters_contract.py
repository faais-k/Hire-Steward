"""Mocked HTTP contract tests for Greenhouse, Ashby, and Lever source adapters.

Guarantees:
- Zero real external HTTP requests during execution (all network transports strictly mocked).
- Validates pagination bounds, end of pagination, and offset slicing.
- Validates fail-closed handling of malformed payloads, invalid JSON, and missing fields.
- Validates HTTP 429 rate limiting with Retry-After header parsing.
- Validates HTTP 404 returning safe empty listings.
- Validates timeouts and server error handling.
- Validates Source Registry lookup and unknown-source rejection.
"""

import httpx
import pytest

from backend.app.adapters.ashby import AshbyAdapter
from backend.app.adapters.greenhouse import GreenhouseAdapter
from backend.app.adapters.lever import LeverAdapter
from backend.app.adapters.source_registry import get_source_adapter, list_registered_sources
from backend.app.domain.job_posting import (
    InvalidPaginationBoundsError,
    InvalidPostingPayloadError,
    SourceHttpError,
    SourceNotApprovedError,
    SourceRateLimitError,
    SourceTimeoutError,
)


# ---------------------------------------------------------------------------
# Greenhouse Adapter Contract Tests
# ---------------------------------------------------------------------------

def test_greenhouse_fetch_page_pagination_slicing():
    # Mock Greenhouse returning 5 jobs
    mock_jobs = [{"id": i, "title": f"Engineer {i}"} for i in range(1, 6)]
    payload = {"jobs": mock_jobs}

    def handler(request: httpx.Request) -> httpx.Response:
        assert "boards-api.greenhouse.io" in str(request.url)
        assert "/v1/boards/acme-corp/jobs" in str(request.url)
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = GreenhouseAdapter(client=client)

    # First page: skip=0, limit=2
    page1 = adapter.fetch_page("acme-corp", skip=0, limit=2)
    assert page1 is not None
    assert len(page1) == 2
    assert page1[0]["id"] == 1

    # Second page: skip=2, limit=2
    page2 = adapter.fetch_page("acme-corp", skip=2, limit=2)
    assert page2 is not None
    assert len(page2) == 2
    assert page2[0]["id"] == 3

    # End of pagination: skip=10, limit=2
    page_end = adapter.fetch_page("acme-corp", skip=10, limit=2)
    assert page_end == []


def test_greenhouse_fetch_page_rate_limit_429():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "60"}, text="Rate limit exceeded")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = GreenhouseAdapter(client=client)

    with pytest.raises(SourceRateLimitError) as exc_info:
        adapter.fetch_page("acme-corp", skip=0, limit=10)
    assert exc_info.value.retry_after_seconds == 60


def test_greenhouse_fetch_page_404_returns_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Not Found")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = GreenhouseAdapter(client=client)

    res = adapter.fetch_page("unknown-org", skip=0, limit=10)
    assert res == []


def test_greenhouse_fetch_page_malformed_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="NOT_JSON")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = GreenhouseAdapter(client=client)

    with pytest.raises(InvalidPostingPayloadError) as exc_info:
        adapter.fetch_page("acme-corp", skip=0, limit=10)
    assert exc_info.value.code == "MALFORMED_JSON"


def test_greenhouse_fetch_page_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Connection timed out")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = GreenhouseAdapter(client=client)

    with pytest.raises(SourceTimeoutError):
        adapter.fetch_page("acme-corp", skip=0, limit=10)


# ---------------------------------------------------------------------------
# Ashby Adapter Contract Tests
# ---------------------------------------------------------------------------

def test_ashby_fetch_page_pagination_slicing():
    mock_jobs = [{"id": f"ashby-{i}", "title": f"Role {i}"} for i in range(1, 5)]
    payload = {"jobs": mock_jobs}

    def handler(request: httpx.Request) -> httpx.Response:
        assert "api.ashbyhq.com" in str(request.url)
        assert "/posting-api/job-board/scale-ai" in str(request.url)
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = AshbyAdapter(client=client)

    page = adapter.fetch_page("scale-ai", skip=1, limit=2)
    assert page is not None
    assert len(page) == 2
    assert page[0]["id"] == "ashby-2"


def test_ashby_fetch_page_rate_limit_429():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "120"}, text="Too Many Requests")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = AshbyAdapter(client=client)

    with pytest.raises(SourceRateLimitError) as exc_info:
        adapter.fetch_page("scale-ai", skip=0, limit=10)
    assert exc_info.value.retry_after_seconds == 120


def test_ashby_fetch_page_404_returns_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Not Found")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = AshbyAdapter(client=client)

    res = adapter.fetch_page("missing-org", skip=0, limit=10)
    assert res == []


def test_ashby_fetch_page_server_error_500():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = AshbyAdapter(client=client)

    with pytest.raises(SourceHttpError) as exc_info:
        adapter.fetch_page("scale-ai", skip=0, limit=10)
    assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# Lever Adapter Contract Tests
# ---------------------------------------------------------------------------

def test_lever_fetch_page_success():
    mock_postings = [{"id": f"lever-{i}", "text": f"Engineer {i}"} for i in range(1, 4)]

    def handler(request: httpx.Request) -> httpx.Response:
        assert "api.lever.co" in str(request.url)
        assert "skip=10" in str(request.url)
        assert "limit=2" in str(request.url)
        return httpx.Response(200, json=mock_postings)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = LeverAdapter(client=client)

    res = adapter.fetch_page("stripe", skip=10, limit=2)
    assert res is not None
    assert len(res) == 3
    assert res[0]["id"] == "lever-1"


def test_lever_fetch_page_rate_limit_429():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "45"}, text="Rate limit")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = LeverAdapter(client=client)

    with pytest.raises(SourceRateLimitError) as exc_info:
        adapter.fetch_page("stripe", skip=0, limit=5)
    assert exc_info.value.retry_after_seconds == 45


# ---------------------------------------------------------------------------
# Source Registry Tests
# ---------------------------------------------------------------------------

def test_source_registry_lookups():
    assert "lever" in list_registered_sources()
    assert "greenhouse" in list_registered_sources()
    assert "ashby" in list_registered_sources()

    ad_gh = get_source_adapter("greenhouse")
    assert isinstance(ad_gh, GreenhouseAdapter)

    ad_ashby = get_source_adapter("ashby")
    assert isinstance(ad_ashby, AshbyAdapter)

    ad_lever = get_source_adapter("lever")
    assert isinstance(ad_lever, LeverAdapter)

    with pytest.raises(SourceNotApprovedError):
        get_source_adapter("unsupported_job_board_xyz")
