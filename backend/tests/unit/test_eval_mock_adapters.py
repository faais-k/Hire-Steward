"""Unit tests for Mock Provider Adapters (Task 8.2 Checkpoint A).

Verifies:
1. Mock provider adapter satisfies common provider protocol.
2. Deterministic offline success responses with schema compliance.
3. Predictable error simulation: 429 rate limit, 500 server error, timeout, malformed JSON.
4. Resolved checkpoint, family, and creator provenance metadata reporting.
5. Zero external network calls.
"""

from __future__ import annotations

import pytest

from backend.app.evaluation.adapters import (
    BaseProviderAdapter,
    MockAdapterConfig,
    MockProviderAdapter,
    ModelInferenceResponse,
)
from backend.app.evaluation.blinded_serializer import (
    BlindedEvaluationSerializer,
)
from backend.app.evaluation.real_world_dataset import load_unlabeled_case


def test_mock_adapter_satisfies_protocol() -> None:
    """MockProviderAdapter must implement BaseProviderAdapter protocol."""
    adapter = MockProviderAdapter(
        config=MockAdapterConfig(
            candidate_id="cand_mock_gpt4",
            provider_id="mock_openai",
            model_alias="mock-gpt-4o",
            resolved_checkpoint_id="gpt-4o-2024-08-06",
            resolved_family_id="gpt-4o",
            resolved_creator_entity="openai",
        )
    )
    assert isinstance(adapter, BaseProviderAdapter)


def test_mock_adapter_deterministic_success_inference() -> None:
    """Mock adapter generates deterministic offline evaluations with valid tier and score."""
    adapter = MockProviderAdapter(
        config=MockAdapterConfig(
            candidate_id="cand_mock_gpt4",
            provider_id="mock_openai",
            model_alias="mock-gpt-4o",
            resolved_checkpoint_id="gpt-4o-2024-08-06",
            resolved_family_id="gpt-4o",
            resolved_creator_entity="openai",
            behavior_mode="SUCCESS",
        )
    )

    raw_case = load_unlabeled_case("rw_calib_001")
    serializer = BlindedEvaluationSerializer()
    payload = serializer.serialize(raw_case)

    resp1: ModelInferenceResponse = adapter.execute_inference(payload)
    resp2: ModelInferenceResponse = adapter.execute_inference(payload)

    # 1. Success validation
    assert resp1.success is True
    assert resp1.http_status == 200
    assert resp1.match_tier in ("TIER_1", "TIER_2", "TIER_3", "TIER_4")
    assert 0.0 <= resp1.match_score <= 1.0
    assert resp1.reasoning
    assert resp1.reported_input_tokens > 0
    assert resp1.reported_output_tokens > 0

    # 2. Metadata provenance reporting
    assert resp1.resolved_checkpoint_id == "gpt-4o-2024-08-06"
    assert resp1.resolved_family_id == "gpt-4o"
    assert resp1.resolved_creator_entity == "openai"

    # 3. Determinism check
    assert resp1.match_tier == resp2.match_tier
    assert resp1.match_score == resp2.match_score
    assert resp1.raw_response_body == resp2.raw_response_body


def test_mock_adapter_simulates_http_429_rate_limit() -> None:
    """Mock adapter simulates transient 429 rate limit with retry-after header."""
    adapter = MockProviderAdapter(
        config=MockAdapterConfig(
            candidate_id="cand_mock_rate_limited",
            provider_id="mock_anthropic",
            model_alias="mock-claude-3-5-sonnet",
            resolved_checkpoint_id="claude-3-5-sonnet-20241022",
            resolved_family_id="claude-3-5",
            resolved_creator_entity="anthropic",
            behavior_mode="RATE_LIMIT_429",
            retry_after_seconds=15,
        )
    )

    raw_case = load_unlabeled_case("rw_calib_001")
    serializer = BlindedEvaluationSerializer()
    payload = serializer.serialize(raw_case)

    resp = adapter.execute_inference(payload)
    assert resp.success is False
    assert resp.http_status == 429
    assert resp.error_type == "HTTP_429_RATE_LIMIT"
    assert resp.retry_after_seconds == 15
    assert resp.match_tier is None


def test_mock_adapter_simulates_http_500_server_error() -> None:
    """Mock adapter simulates upstream 500 server error."""
    adapter = MockProviderAdapter(
        config=MockAdapterConfig(
            candidate_id="cand_mock_err",
            provider_id="mock_gemini",
            model_alias="mock-gemini-1.5-pro",
            resolved_checkpoint_id="gemini-1.5-pro-002",
            resolved_family_id="gemini-1.5",
            resolved_creator_entity="google",
            behavior_mode="SERVER_ERROR_500",
        )
    )

    raw_case = load_unlabeled_case("rw_calib_001")
    serializer = BlindedEvaluationSerializer()
    payload = serializer.serialize(raw_case)

    resp = adapter.execute_inference(payload)
    assert resp.success is False
    assert resp.http_status == 500
    assert resp.error_type == "HTTP_5XX_SERVER_ERROR"


def test_mock_adapter_simulates_socket_timeout() -> None:
    """Mock adapter simulates client socket timeout (30.0s)."""
    adapter = MockProviderAdapter(
        config=MockAdapterConfig(
            candidate_id="cand_mock_timeout",
            provider_id="mock_openai",
            model_alias="mock-gpt-4o",
            resolved_checkpoint_id="gpt-4o-2024-08-06",
            resolved_family_id="gpt-4o",
            resolved_creator_entity="openai",
            behavior_mode="TIMEOUT",
        )
    )

    raw_case = load_unlabeled_case("rw_calib_001")
    serializer = BlindedEvaluationSerializer()
    payload = serializer.serialize(raw_case)

    resp = adapter.execute_inference(payload)
    assert resp.success is False
    assert resp.error_type == "TIMEOUT_CLIENT"


def test_mock_adapter_simulates_malformed_json() -> None:
    """Mock adapter simulates 200 response with malformed JSON / schema error."""
    adapter = MockProviderAdapter(
        config=MockAdapterConfig(
            candidate_id="cand_mock_malformed",
            provider_id="mock_provider",
            model_alias="mock-model",
            resolved_checkpoint_id="chk_1",
            resolved_family_id="fam_1",
            resolved_creator_entity="lab_1",
            behavior_mode="MALFORMED_JSON",
        )
    )

    raw_case = load_unlabeled_case("rw_calib_001")
    serializer = BlindedEvaluationSerializer()
    payload = serializer.serialize(raw_case)

    resp = adapter.execute_inference(payload)
    assert resp.success is False
    assert resp.error_type == "SCHEMA_VALIDATION_FAILURE"
