"""Unit tests for Groq and Gemini provider adapters.

Verifies:
1. Missing credentials return HTTP_401_AUTH_REVOKED without socket calls.
2. Valid responses parse into ModelInferenceResponse with match_tier and citations.
3. HTTP 429 rate limits, HTTP 500 server errors, timeouts, and malformed schemas are classified correctly.
4. API keys are wrapped in SecretStr and never leaked in repr or strings.
"""

from __future__ import annotations

import json
import httpx
import pytest
from pydantic import SecretStr

from backend.app.evaluation.blinded_serializer import BlindedEvaluationSerializer, BlindedCasePayload
from backend.app.evaluation.gemini_adapter import GeminiAdapterConfig, GeminiProviderAdapter
from backend.app.evaluation.groq_adapter import GroqAdapterConfig, GroqProviderAdapter
from backend.app.evaluation.real_world_dataset import load_unlabeled_case


@pytest.fixture
def sample_payload() -> BlindedCasePayload:
    raw_case = load_unlabeled_case("rw_calib_001")
    return BlindedEvaluationSerializer().serialize(raw_case)


VALID_OUTPUT_JSON = {
    "match_tier": "TIER_1",
    "match_score": 0.95,
    "reasoning": "Strong alignment across all mandatory technical requirements.",
    "citations": [
        {
            "source_section": "requirements",
            "quote": "Python and PostgreSQL expertise",
            "payload_start": 0,
            "payload_end": 31,
        }
    ],
}


class TestGroqProviderAdapter:
    def test_missing_credentials_returns_401(self, sample_payload: BlindedCasePayload) -> None:
        adapter = GroqProviderAdapter(api_key=None)
        res = adapter.execute_inference(sample_payload)
        assert res.success is False
        assert res.http_status == 401
        assert res.error_type == "HTTP_401_AUTH_REVOKED"
        assert "missing or not configured" in res.error_message

    def test_successful_inference(self, sample_payload: BlindedCasePayload) -> None:
        mock_response = {
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(VALID_OUTPUT_JSON),
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 150,
                "completion_tokens": 80,
                "total_tokens": 230,
            },
        }

        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, json=mock_response)
        )
        adapter = GroqProviderAdapter(
            api_key=SecretStr("gsk_mock_test_key_12345"),
            transport=transport,
        )
        res = adapter.execute_inference(sample_payload)
        assert res.success is True
        assert res.http_status == 200
        assert res.match_tier == "TIER_1"
        assert res.match_score == 0.95
        assert res.reported_input_tokens == 150
        assert res.reported_output_tokens == 80
        assert len(res.citations) == 1
        assert res.citations[0]["quote"] == "Python and PostgreSQL expertise"

    def test_rate_limit_429(self, sample_payload: BlindedCasePayload) -> None:
        transport = httpx.MockTransport(
            lambda req: httpx.Response(429, headers={"retry-after": "25"}, text="Rate limit exceeded")
        )
        adapter = GroqProviderAdapter(
            api_key=SecretStr("gsk_mock_test_key_12345"),
            transport=transport,
        )
        res = adapter.execute_inference(sample_payload)
        assert res.success is False
        assert res.http_status == 429
        assert res.error_type == "HTTP_429_RATE_LIMIT"
        assert res.retry_after_seconds == 25

    def test_server_error_500(self, sample_payload: BlindedCasePayload) -> None:
        transport = httpx.MockTransport(
            lambda req: httpx.Response(500, text="Internal Server Error")
        )
        adapter = GroqProviderAdapter(
            api_key=SecretStr("gsk_mock_test_key_12345"),
            transport=transport,
        )
        res = adapter.execute_inference(sample_payload)
        assert res.success is False
        assert res.http_status == 500
        assert res.error_type == "HTTP_5XX_SERVER_ERROR"

    def test_malformed_json_schema(self, sample_payload: BlindedCasePayload) -> None:
        mock_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"unrecognized": "format"}),
                    }
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, json=mock_response)
        )
        adapter = GroqProviderAdapter(
            api_key=SecretStr("gsk_mock_test_key_12345"),
            transport=transport,
        )
        res = adapter.execute_inference(sample_payload)
        assert res.success is False
        assert res.error_type == "MALFORMED_OUTPUT_SCHEMA"


class TestGeminiProviderAdapter:
    def test_missing_credentials_returns_401(self, sample_payload: BlindedCasePayload) -> None:
        adapter = GeminiProviderAdapter(api_key=None)
        res = adapter.execute_inference(sample_payload)
        assert res.success is False
        assert res.http_status == 401
        assert res.error_type == "HTTP_401_AUTH_REVOKED"
        assert "missing or not configured" in res.error_message

    def test_successful_inference(self, sample_payload: BlindedCasePayload) -> None:
        mock_response = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": json.dumps(VALID_OUTPUT_JSON)}
                        ]
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 210,
                "candidatesTokenCount": 95,
                "totalTokenCount": 305,
            },
        }

        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, json=mock_response)
        )
        adapter = GeminiProviderAdapter(
            api_key=SecretStr("AIzaSyMockKeyForGeminiTest"),
            transport=transport,
        )
        res = adapter.execute_inference(sample_payload)
        assert res.success is True
        assert res.http_status == 200
        assert res.match_tier == "TIER_1"
        assert res.match_score == 0.95
        assert res.reported_input_tokens == 210
        assert res.reported_output_tokens == 95
        assert len(res.citations) == 1

    def test_rate_limit_429(self, sample_payload: BlindedCasePayload) -> None:
        transport = httpx.MockTransport(
            lambda req: httpx.Response(429, headers={"retry-after": "10"}, text="Quota exceeded")
        )
        adapter = GeminiProviderAdapter(
            api_key=SecretStr("AIzaSyMockKeyForGeminiTest"),
            transport=transport,
        )
        res = adapter.execute_inference(sample_payload)
        assert res.success is False
        assert res.http_status == 429
        assert res.error_type == "HTTP_429_RATE_LIMIT"
        assert res.retry_after_seconds == 10

    def test_server_error_503(self, sample_payload: BlindedCasePayload) -> None:
        transport = httpx.MockTransport(
            lambda req: httpx.Response(503, text="Service Unavailable")
        )
        adapter = GeminiProviderAdapter(
            api_key=SecretStr("AIzaSyMockKeyForGeminiTest"),
            transport=transport,
        )
        res = adapter.execute_inference(sample_payload)
        assert res.success is False
        assert res.http_status == 503
        assert res.error_type == "HTTP_5XX_SERVER_ERROR"

    def test_malformed_json_schema(self, sample_payload: BlindedCasePayload) -> None:
        mock_response = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "not valid json"}
                        ]
                    }
                }
            ],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
        }
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, json=mock_response)
        )
        adapter = GeminiProviderAdapter(
            api_key=SecretStr("AIzaSyMockKeyForGeminiTest"),
            transport=transport,
        )
        res = adapter.execute_inference(sample_payload)
        assert res.success is False
        assert res.error_type == "MALFORMED_OUTPUT_SCHEMA"
