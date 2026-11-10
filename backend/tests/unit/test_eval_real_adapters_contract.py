"""Unit and offline contract tests for real provider adapters, credentials, and budget reservation (Task 8.2 Checkpoint B Stage B1).

CRITICAL INVARIANTS:
1. Zero real external network calls (all HTTP calls run through `httpx.MockTransport`).
2. Zero real credentials (test fixtures only use dummy strings).
3. Anthropic contract:
   - Native structured JSON schema via `output_config.format`.
   - Complete omission of `temperature`, `top_p`, `top_k`, and forced `tool_choice`.
   - Parsing from `content[0].text`.
4. OpenAI contract:
   - Chat Completions `response_format` with `strict: true`.
   - Data privacy: `"store": False`.
   - Omission of sampling parameters for reasoning models.
   - Parsing from `choices[0].message.content`.
5. Pre-dispatch budget reservation against worst-case token costs.
6. Ledger state machine:
   - `AMBIGUOUS_IN_FLIGHT` on timeouts (zero automatic retry).
   - `HTTP_5XX_SERVER_ERROR` (zero automatic retry).
   - `HTTP_429_RATE_LIMIT` retries up to 3 total attempts.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from backend.app.evaluation.anthropic_adapter import (
    AnthropicAdapterConfig,
    AnthropicProviderAdapter,
)
from backend.app.evaluation.blinded_serializer import BlindedEvaluationSerializer
from backend.app.evaluation.budget import (
    BudgetExceededError,
    BudgetTracker,
    calculate_actual_cost,
    estimate_call_cost,
)
from backend.app.evaluation.coordinator import OfflineEvaluationCoordinator
from backend.app.evaluation.credentials import (
    ProviderCredentials,
    get_anthropic_api_key,
    get_openai_api_key,
    load_provider_credentials,
)
from backend.app.evaluation.ledger import EvaluationLedger, verify_audit_chain
from backend.app.evaluation.openai_adapter import (
    OpenAIAdapterConfig,
    OpenAIProviderAdapter,
)
from backend.app.evaluation.real_world_dataset import load_unlabeled_case


SAMPLE_EVAL_RESPONSE_JSON: dict[str, Any] = {
    "match_tier": "TIER_1",
    "match_score": 0.92,
    "reasoning": "Candidate demonstrates strong alignment across all core competencies and mandatory constraints.",
    "citations": [
        {
            "source_section": "requirements",
            "quote": "Python",
            "payload_start": 0,
            "payload_end": 6,
        }
    ],
}


# ==============================================================================
# 1. ANTHROPIC CONTRACT TESTS
# ==============================================================================


def test_anthropic_adapter_request_contract_and_clean_payload() -> None:
    """Anthropic adapter must format output_config schema and omit unsupported sampling/tool parameters."""
    captured_requests: list[httpx.Request] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        anthropic_resp = {
            "id": "msg_test_anthropic_123",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-5-5",
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(SAMPLE_EVAL_RESPONSE_JSON),
                }
            ],
            "usage": {
                "input_tokens": 1850,
                "output_tokens": 140,
            },
        }
        return httpx.Response(200, json=anthropic_resp)

    transport = httpx.MockTransport(mock_handler)
    adapter = AnthropicProviderAdapter(
        config=AnthropicAdapterConfig(
            model_alias="claude-sonnet-5-5",
            resolved_checkpoint_id="claude-sonnet-5-5",
        ),
        api_key=SecretStr("test_anthropic_key_secret_dummy"),
        transport=transport,
    )

    raw_case = load_unlabeled_case("rw_calib_001")
    payload = BlindedEvaluationSerializer().serialize(raw_case)

    response = adapter.execute_inference(payload)

    # 1. Verify response normalization
    assert response.success is True
    assert response.http_status == 200
    assert response.match_tier == "TIER_1"
    assert response.match_score == 0.92
    assert response.reported_input_tokens == 1850
    assert response.reported_output_tokens == 140
    assert len(response.citations) == 1
    assert response.citations[0]["quote"] == "Python"
    assert response.resolved_checkpoint_id == "claude-sonnet-5-5"

    # 2. Inspect captured HTTP request
    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req.method == "POST"
    assert req.url.path == "/v1/messages"
    assert req.headers["x-api-key"] == "test_anthropic_key_secret_dummy"
    assert req.headers["anthropic-version"] == "2023-06-01"
    assert req.headers["content-type"] == "application/json"

    body = json.loads(req.content.decode("utf-8"))
    assert body["model"] == "claude-sonnet-5-5"
    assert "output_config" in body
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert "schema" in body["output_config"]["format"]

    # CRITICAL: Verify unsupported parameters are completely omitted
    assert "temperature" not in body, "Sonnet 5.5 rejects temperature with HTTP 400"
    assert "top_p" not in body, "Sonnet 5.5 rejects top_p with HTTP 400"
    assert "top_k" not in body, "Sonnet 5.5 rejects top_k with HTTP 400"
    assert "tool_choice" not in body, "Sonnet 5.5 rejects forced tool_choice with HTTP 400"


def test_anthropic_adapter_rate_limit_429() -> None:
    """HTTP 429 response is classified as HTTP_429_RATE_LIMIT with retry_after_seconds extracted."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"retry-after": "25"},
            json={"error": {"type": "rate_limit_error", "message": "Rate limit exceeded"}},
        )

    transport = httpx.MockTransport(mock_handler)
    adapter = AnthropicProviderAdapter(
        api_key=SecretStr("dummy_key"),
        transport=transport,
    )

    raw_case = load_unlabeled_case("rw_calib_001")
    payload = BlindedEvaluationSerializer().serialize(raw_case)

    response = adapter.execute_inference(payload)
    assert response.success is False
    assert response.http_status == 429
    assert response.error_type == "HTTP_429_RATE_LIMIT"
    assert response.retry_after_seconds == 25


def test_anthropic_adapter_server_error_500() -> None:
    """HTTP 500 response is classified as HTTP_5XX_SERVER_ERROR."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    transport = httpx.MockTransport(mock_handler)
    adapter = AnthropicProviderAdapter(
        api_key=SecretStr("dummy_key"),
        transport=transport,
    )

    payload = BlindedEvaluationSerializer().serialize(load_unlabeled_case("rw_calib_001"))
    response = adapter.execute_inference(payload)

    assert response.success is False
    assert response.http_status == 500
    assert response.error_type == "HTTP_5XX_SERVER_ERROR"


def test_anthropic_adapter_timeout_handling() -> None:
    """Socket timeouts are classified as TIMEOUT_CLIENT with http_status = 0."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Mocked Anthropic read timeout")

    transport = httpx.MockTransport(mock_handler)
    adapter = AnthropicProviderAdapter(
        api_key=SecretStr("dummy_key"),
        transport=transport,
    )

    payload = BlindedEvaluationSerializer().serialize(load_unlabeled_case("rw_calib_001"))
    response = adapter.execute_inference(payload)

    assert response.success is False
    assert response.http_status == 0
    assert response.error_type == "TIMEOUT_CLIENT"
    assert "timed out" in (response.error_message or "").lower()


def test_anthropic_adapter_malformed_json_content() -> None:
    """When model generates non-JSON text in content block, return SCHEMA_VALIDATION_FAILURE."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "msg_bad",
                "role": "assistant",
                "content": [{"type": "text", "text": "Sorry, I cannot produce JSON today."}],
                "usage": {"input_tokens": 100, "output_tokens": 10},
            },
        )

    transport = httpx.MockTransport(mock_handler)
    adapter = AnthropicProviderAdapter(
        api_key=SecretStr("dummy_key"),
        transport=transport,
    )

    payload = BlindedEvaluationSerializer().serialize(load_unlabeled_case("rw_calib_001"))
    response = adapter.execute_inference(payload)

    assert response.success is False
    assert response.http_status == 200
    assert response.error_type == "SCHEMA_VALIDATION_FAILURE"


def test_anthropic_adapter_missing_credentials() -> None:
    """Missing API key returns HTTP_401_AUTH_REVOKED safely without network dispatch."""
    adapter = AnthropicProviderAdapter(api_key=None)
    payload = BlindedEvaluationSerializer().serialize(load_unlabeled_case("rw_calib_001"))
    response = adapter.execute_inference(payload)

    assert response.success is False
    assert response.http_status == 401
    assert response.error_type == "HTTP_401_AUTH_REVOKED"


# ==============================================================================
# 2. OPENAI CONTRACT TESTS
# ==============================================================================


def test_openai_adapter_request_contract_and_clean_payload() -> None:
    """OpenAI adapter must format strict JSON Schema, store=False, and omit sampling parameters."""
    captured_requests: list[httpx.Request] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        openai_resp = {
            "id": "chatcmpl_test_openai_456",
            "object": "chat.completion",
            "model": "gpt-6.1-sol",
            "system_fingerprint": "fp_test_sol_999",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(SAMPLE_EVAL_RESPONSE_JSON),
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 1720,
                "completion_tokens": 165,
                "total_tokens": 1885,
            },
        }
        return httpx.Response(200, json=openai_resp)

    transport = httpx.MockTransport(mock_handler)
    adapter = OpenAIProviderAdapter(
        config=OpenAIAdapterConfig(
            model_alias="gpt-6.1-sol",
            resolved_checkpoint_id="gpt-6.1-sol",
            store=False,
        ),
        api_key=SecretStr("test_openai_key_secret_dummy"),
        transport=transport,
    )

    payload = BlindedEvaluationSerializer().serialize(load_unlabeled_case("rw_calib_001"))
    response = adapter.execute_inference(payload)

    # 1. Verify response normalization
    assert response.success is True
    assert response.http_status == 200
    assert response.match_tier == "TIER_1"
    assert response.match_score == 0.92
    assert response.reported_input_tokens == 1720
    assert response.reported_output_tokens == 165
    assert response.system_fingerprint == "fp_test_sol_999"
    assert response.resolved_checkpoint_id == "gpt-6.1-sol"

    # 2. Inspect captured request
    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req.method == "POST"
    assert req.url.path == "/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer test_openai_key_secret_dummy"
    assert req.headers["content-type"] == "application/json"

    body = json.loads(req.content.decode("utf-8"))
    assert body["model"] == "gpt-6.1-sol"
    assert body["store"] is False, "Zero retention requirement"
    assert "response_format" in body
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert "schema" in body["response_format"]["json_schema"]

    # Verify absence of conflicting sampling parameters
    assert "temperature" not in body
    assert "top_p" not in body


def test_openai_adapter_rate_limit_429() -> None:
    """HTTP 429 response is classified as HTTP_429_RATE_LIMIT with retry_after_seconds extracted."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"retry-after": "18"},
            json={"error": {"message": "Rate limit exceeded"}},
        )

    transport = httpx.MockTransport(mock_handler)
    adapter = OpenAIProviderAdapter(
        api_key=SecretStr("dummy_key"),
        transport=transport,
    )

    payload = BlindedEvaluationSerializer().serialize(load_unlabeled_case("rw_calib_001"))
    response = adapter.execute_inference(payload)

    assert response.success is False
    assert response.http_status == 429
    assert response.error_type == "HTTP_429_RATE_LIMIT"
    assert response.retry_after_seconds == 18


def test_openai_adapter_server_error_503() -> None:
    """HTTP 503 response is classified as HTTP_5XX_SERVER_ERROR."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    transport = httpx.MockTransport(mock_handler)
    adapter = OpenAIProviderAdapter(
        api_key=SecretStr("dummy_key"),
        transport=transport,
    )

    payload = BlindedEvaluationSerializer().serialize(load_unlabeled_case("rw_calib_001"))
    response = adapter.execute_inference(payload)

    assert response.success is False
    assert response.http_status == 503
    assert response.error_type == "HTTP_5XX_SERVER_ERROR"


def test_openai_adapter_timeout_handling() -> None:
    """Connect timeout is classified as TIMEOUT_CLIENT with http_status = 0."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("Mocked OpenAI connection timeout")

    transport = httpx.MockTransport(mock_handler)
    adapter = OpenAIProviderAdapter(
        api_key=SecretStr("dummy_key"),
        transport=transport,
    )

    payload = BlindedEvaluationSerializer().serialize(load_unlabeled_case("rw_calib_001"))
    response = adapter.execute_inference(payload)

    assert response.success is False
    assert response.http_status == 0
    assert response.error_type == "TIMEOUT_CLIENT"


def test_openai_adapter_malformed_json_content() -> None:
    """Truncated or malformed JSON content results in SCHEMA_VALIDATION_FAILURE."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chat_bad",
                "choices": [{"message": {"role": "assistant", "content": '{"match_tier": "TIER_1", <<truncated'}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10},
            },
        )

    transport = httpx.MockTransport(mock_handler)
    adapter = OpenAIProviderAdapter(
        api_key=SecretStr("dummy_key"),
        transport=transport,
    )

    payload = BlindedEvaluationSerializer().serialize(load_unlabeled_case("rw_calib_001"))
    response = adapter.execute_inference(payload)

    assert response.success is False
    assert response.http_status == 200
    assert response.error_type == "SCHEMA_VALIDATION_FAILURE"


def test_openai_adapter_missing_credentials() -> None:
    """Missing OpenAI API key returns HTTP_401_AUTH_REVOKED safely without network dispatch."""
    adapter = OpenAIProviderAdapter(api_key=None)
    payload = BlindedEvaluationSerializer().serialize(load_unlabeled_case("rw_calib_001"))
    response = adapter.execute_inference(payload)

    assert response.success is False
    assert response.http_status == 401
    assert response.error_type == "HTTP_401_AUTH_REVOKED"


# ==============================================================================
# 3. CREDENTIAL SECURITY AND MASKING TESTS
# ==============================================================================


def test_credentials_secret_masking_and_no_leakage() -> None:
    """Credentials must never expose raw API keys in repr, str, or logging."""
    fake_key_anthropic = "sk-ant-live-super-secret-key-12345"
    fake_key_openai = "sk-proj-live-super-secret-key-67890"

    env_map = {
        "HIRE_STEWARD_ANTHROPIC_API_KEY": fake_key_anthropic,
        "HIRE_STEWARD_OPENAI_API_KEY": fake_key_openai,
    }

    creds = load_provider_credentials(env_map)
    assert creds.has_anthropic is True
    assert creds.has_openai is True

    # 1. Verify SecretStr masking in repr and str
    assert fake_key_anthropic not in str(creds)
    assert fake_key_anthropic not in repr(creds)
    assert fake_key_openai not in str(creds)
    assert fake_key_openai not in repr(creds)

    # 2. Verify adapter config repr masking
    cfg_anthropic = AnthropicAdapterConfig(api_key=creds.anthropic_api_key)
    assert fake_key_anthropic not in str(cfg_anthropic)
    assert fake_key_anthropic not in repr(cfg_anthropic)

    cfg_openai = OpenAIAdapterConfig(api_key=creds.openai_api_key)
    assert fake_key_openai not in str(cfg_openai)
    assert fake_key_openai not in repr(cfg_openai)

    # 3. Empty strings treated as None
    empty_env = {
        "HIRE_STEWARD_ANTHROPIC_API_KEY": "   ",
        "HIRE_STEWARD_OPENAI_API_KEY": "",
    }
    empty_creds = load_provider_credentials(empty_env)
    assert empty_creds.anthropic_api_key is None
    assert empty_creds.openai_api_key is None
    assert empty_creds.has_anthropic is False
    assert empty_creds.has_openai is False


# ==============================================================================
# 4. BUDGET RESERVATION AND LIABILITY TESTS
# ==============================================================================


def test_budget_estimation_and_rates() -> None:
    """Verify call cost estimation includes overhead tokens and follows accurate rates."""
    # Anthropic: 1,800 + 300 = 2,100 in tokens ($2/M) + 1,000 out tokens ($10/M)
    # in = 2,100 * 0.000002 = 0.0042
    # out = 1,000 * 0.000010 = 0.0100
    # total = 0.0142
    anthropic_est = estimate_call_cost("claude-sonnet-5-5", estimated_input_tokens=1800, max_output_tokens=1000)
    assert anthropic_est == pytest.approx(0.0142, rel=1e-3)

    # OpenAI: 1,800 in tokens ($2.50/M) + 1,000 out tokens ($10/M)
    # in = 1,800 * 0.0000025 = 0.0045
    # out = 1,000 * 0.000010 = 0.0100
    # total = 0.0145
    openai_est = estimate_call_cost("gpt-6.1-sol", estimated_input_tokens=1800, max_output_tokens=1000)
    assert openai_est == pytest.approx(0.0145, rel=1e-3)

    # Actual cost calculation
    actual_anthropic = calculate_actual_cost("claude-sonnet-5-5", reported_input_tokens=1500, reported_output_tokens=200)
    # 1500 * 2/1M + 200 * 10/1M = 0.0030 + 0.0020 = 0.0050
    assert actual_anthropic == pytest.approx(0.0050, rel=1e-3)


def test_budget_reservation_ceiling_enforcement() -> None:
    """BudgetTracker rejects reservations that would exceed the budget cap."""
    tracker = BudgetTracker(budget_cap_usd=0.02)

    # Reservation 1: $0.0142 -> succeeds (remaining $0.0058)
    assert tracker.can_reserve(0.0142) is True
    tracker.reserve("res_1", 0.0142)

    summary1 = tracker.get_summary()
    assert summary1.active_reservations_usd == pytest.approx(0.0142, rel=1e-3)
    assert summary1.remaining_budget_usd == pytest.approx(0.0058, rel=1e-3)

    # Reservation 2: $0.0145 -> exceeds cap, raises BudgetExceededError
    assert tracker.can_reserve(0.0145) is False
    with pytest.raises(BudgetExceededError) as exc_info:
        tracker.reserve("res_2", 0.0145)
    assert "Budget cap exceeded" in str(exc_info.value)

    # Settle Reservation 1 with actual spend of $0.0050 -> releases reservation, increases remaining to $0.0150
    tracker.reconcile("res_1", actual_spend_usd=0.0050)
    summary2 = tracker.get_summary()
    assert summary2.committed_spend_usd == pytest.approx(0.0050, rel=1e-3)
    assert summary2.active_reservations_usd == 0.0
    assert summary2.remaining_budget_usd == pytest.approx(0.0150, rel=1e-3)

    # Now Reservation 2 ($0.0145) fits within remaining $0.0150!
    assert tracker.can_reserve(0.0145) is True
    tracker.reserve("res_2", 0.0145)


def test_budget_timeout_and_5xx_retains_liability() -> None:
    """On timeout or 5xx, active reservation is converted to committed liability to prevent double-billing."""
    tracker = BudgetTracker(budget_cap_usd=0.03)

    tracker.reserve("res_timeout_call", 0.0142)
    assert tracker.get_summary().committed_spend_usd == 0.0
    assert tracker.get_summary().active_reservations_usd == pytest.approx(0.0142, rel=1e-3)

    # Record unresolved liability
    tracker.record_unresolved_liability("res_timeout_call")

    summary = tracker.get_summary()
    assert summary.active_reservations_usd == 0.0
    assert summary.committed_spend_usd == pytest.approx(0.0142, rel=1e-3)
    assert summary.remaining_budget_usd == pytest.approx(0.0158, rel=1e-3)


# ==============================================================================
# 5. COORDINATOR END-TO-END INTEGRATION TESTS WITH REAL ADAPTERS (MOCKED)
# ==============================================================================


def test_coordinator_end_to_end_with_real_adapters_mocked() -> None:
    """Full offline coordinator evaluation using Anthropic and OpenAI adapters over MockTransport."""
    ledger = EvaluationLedger(db_path=":memory:")
    tracker = BudgetTracker(budget_cap_usd=1.00)

    # Mock Anthropic transport
    def anthropic_handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "msg_anthropic_e2e",
                "role": "assistant",
                "content": [{"type": "text", "text": json.dumps(SAMPLE_EVAL_RESPONSE_JSON)}],
                "usage": {"input_tokens": 1600, "output_tokens": 120},
            },
        )

    # Mock OpenAI transport
    def openai_handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chat_openai_e2e",
                "system_fingerprint": "fp_sol_prod_1",
                "choices": [{"message": {"role": "assistant", "content": json.dumps(SAMPLE_EVAL_RESPONSE_JSON)}}],
                "usage": {"prompt_tokens": 1550, "completion_tokens": 110},
            },
        )

    evaluator_a = AnthropicProviderAdapter(
        config=AnthropicAdapterConfig(
            candidate_id="cand_anthropic_sonnet",
            model_alias="claude-sonnet-5-5",
            resolved_checkpoint_id="claude-sonnet-5-5",
            resolved_family_id="claude-sonnet-5",
            resolved_creator_entity="anthropic",
        ),
        api_key=SecretStr("mock_anthropic_key"),
        transport=httpx.MockTransport(anthropic_handler),
    )

    evaluator_b = OpenAIProviderAdapter(
        config=OpenAIAdapterConfig(
            candidate_id="cand_openai_sol",
            model_alias="gpt-6.1-sol",
            resolved_checkpoint_id="gpt-6.1-sol",
            resolved_family_id="gpt-6.1",
            resolved_creator_entity="openai",
        ),
        api_key=SecretStr("mock_openai_key"),
        transport=httpx.MockTransport(openai_handler),
    )

    coordinator = OfflineEvaluationCoordinator(
        ledger=ledger,
        evaluator_a_adapter=evaluator_a,
        evaluator_b_adapter=evaluator_b,
        budget_tracker=tracker,
    )

    raw_case = load_unlabeled_case("rw_calib_001")
    session_id = "sess_real_adapters_mocked"

    pair_result = coordinator.evaluate_case(session_id=session_id, raw_case=raw_case)

    # 1. Admissibility and provenance
    assert pair_result.pair_status == "ADMISSIBLE_PAIR"
    assert pair_result.provenance_state == "DIFFERENT_KNOWN_FAMILIES"
    assert pair_result.assessment_a.match_tier == "TIER_1"
    assert pair_result.assessment_b.match_tier == "TIER_1"

    # 2. Budget reconciliation
    summary = tracker.get_summary()
    assert summary.active_reservations_usd == 0.0
    assert summary.committed_spend_usd > 0.0
    assert summary.committed_spend_usd < tracker.budget_cap_usd

    # 3. Audit chain verification
    with ledger.connect() as conn:
        assert verify_audit_chain(conn, session_id=session_id) is True


def test_coordinator_handles_timeout_as_ambiguous_in_flight_without_retry() -> None:
    """Timeout transitions attempt to AMBIGUOUS_IN_FLIGHT with zero duplicate retries."""
    ledger = EvaluationLedger(db_path=":memory:")
    tracker = BudgetTracker(budget_cap_usd=1.00)

    def timeout_handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Timeout on provider socket")

    def success_handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chat_openai_success",
                "system_fingerprint": "fp_test_123",
                "choices": [{"message": {"role": "assistant", "content": json.dumps(SAMPLE_EVAL_RESPONSE_JSON)}}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 100},
            },
        )

    evaluator_a = AnthropicProviderAdapter(
        api_key=SecretStr("dummy_key"),
        transport=httpx.MockTransport(timeout_handler),
    )
    evaluator_b = OpenAIProviderAdapter(
        api_key=SecretStr("dummy_key"),
        transport=httpx.MockTransport(success_handler),
    )

    coordinator = OfflineEvaluationCoordinator(
        ledger=ledger,
        evaluator_a_adapter=evaluator_a,
        evaluator_b_adapter=evaluator_b,
        budget_tracker=tracker,
    )

    raw_case = load_unlabeled_case("rw_calib_001")
    session_id = "sess_timeout_test"

    pair_result = coordinator.evaluate_case(session_id=session_id, raw_case=raw_case)

    assert pair_result.pair_status == "FAILED_PAIR_UNILATERAL_EXHAUSTION"
    assert pair_result.assessment_a is None
    assert pair_result.assessment_b is not None

    with ledger.connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT attempt_number, state, terminal_reason
            FROM dispatch_attempts
            WHERE logical_eval_id = ?;
            """,
            (pair_result.evaluator_a_id,),
        )
        attempts = cursor.fetchall()
        # Exactly 1 attempt made (NO duplicate retry on timeout!)
        assert len(attempts) == 1
        assert attempts[0] == (1, "AMBIGUOUS_IN_FLIGHT", "TIMEOUT_CLIENT")

        # Logical eval marked FAILED
        cursor.execute(
            "SELECT status FROM logical_evaluations WHERE logical_eval_id = ?;",
            (pair_result.evaluator_a_id,),
        )
        assert cursor.fetchone()[0] == "FAILED"

        assert verify_audit_chain(conn, session_id=session_id) is True

    # Liability retained in budget tracker
    assert tracker.get_summary().committed_spend_usd > 0.0


def test_coordinator_retries_429_up_to_max_attempts() -> None:
    """HTTP 429 retries with next attempt number and succeeds if second attempt is 200."""
    ledger = EvaluationLedger(db_path=":memory:")
    call_count_a = 0

    def retry_handler_a(req: httpx.Request) -> httpx.Response:
        nonlocal call_count_a
        call_count_a += 1
        if call_count_a == 1:
            return httpx.Response(429, headers={"retry-after": "1"}, json={"error": "rate limit"})
        return httpx.Response(
            200,
            json={
                "id": "msg_retry_success",
                "role": "assistant",
                "content": [{"type": "text", "text": json.dumps(SAMPLE_EVAL_RESPONSE_JSON)}],
                "usage": {"input_tokens": 1200, "output_tokens": 100},
            },
        )

    def success_handler_b(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chat_retry_success",
                "system_fingerprint": "fp_sol_retry",
                "choices": [{"message": {"role": "assistant", "content": json.dumps(SAMPLE_EVAL_RESPONSE_JSON)}}],
                "usage": {"prompt_tokens": 1100, "completion_tokens": 90},
            },
        )

    evaluator_a = AnthropicProviderAdapter(
        api_key=SecretStr("dummy_key"),
        transport=httpx.MockTransport(retry_handler_a),
    )
    evaluator_b = OpenAIProviderAdapter(
        api_key=SecretStr("dummy_key"),
        transport=httpx.MockTransport(success_handler_b),
    )

    coordinator = OfflineEvaluationCoordinator(
        ledger=ledger,
        evaluator_a_adapter=evaluator_a,
        evaluator_b_adapter=evaluator_b,
    )

    raw_case = load_unlabeled_case("rw_calib_001")
    session_id = "sess_retry_429"

    pair_result = coordinator.evaluate_case(session_id=session_id, raw_case=raw_case)

    # Both succeed after retry!
    assert pair_result.pair_status == "ADMISSIBLE_PAIR"
    assert pair_result.assessment_a is not None

    with ledger.connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT attempt_number, attempt_type, state, terminal_reason
            FROM dispatch_attempts
            WHERE logical_eval_id = ?
            ORDER BY attempt_number;
            """,
            (pair_result.evaluator_a_id,),
        )
        attempts = cursor.fetchall()
        assert len(attempts) == 2
        assert attempts[0] == (1, "INITIAL", "FAILED", "HTTP_429_RATE_LIMIT")
        assert attempts[1] == (2, "RETRY", "COMPLETED", "SUCCESS_NORMALIZED")

        assert verify_audit_chain(conn, session_id=session_id) is True


def test_coordinator_pre_socket_budget_rejection() -> None:
    """When budget is exhausted, coordinator rejects dispatch pre-socket without network call."""
    ledger = EvaluationLedger(db_path=":memory:")
    # Tiny budget cap: $0.001 (lower than the worst-case cost of a single call ~$0.0142)
    tracker = BudgetTracker(budget_cap_usd=0.001)

    network_called = False

    def uncalled_handler(req: httpx.Request) -> httpx.Response:
        nonlocal network_called
        network_called = True
        return httpx.Response(200, json={})

    evaluator_a = AnthropicProviderAdapter(
        api_key=SecretStr("dummy_key"),
        transport=httpx.MockTransport(uncalled_handler),
    )
    evaluator_b = OpenAIProviderAdapter(
        api_key=SecretStr("dummy_key"),
        transport=httpx.MockTransport(uncalled_handler),
    )

    coordinator = OfflineEvaluationCoordinator(
        ledger=ledger,
        evaluator_a_adapter=evaluator_a,
        evaluator_b_adapter=evaluator_b,
        budget_tracker=tracker,
    )

    raw_case = load_unlabeled_case("rw_calib_001")
    session_id = "sess_budget_reject"

    pair_result = coordinator.evaluate_case(session_id=session_id, raw_case=raw_case)

    # Dispatch aborted pre-socket!
    assert network_called is False
    assert pair_result.pair_status == "FAILED_PAIR_DUAL_EXHAUSTION"

    with ledger.connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT attempt_number, state, terminal_reason
            FROM dispatch_attempts
            WHERE logical_eval_id = ?;
            """,
            (pair_result.evaluator_a_id,),
        )
        attempt = cursor.fetchone()
        assert attempt == (1, "ABORTED_PRE_SOCKET", "CANDIDATE_INELIGIBLE_PRE_SOCKET")

        cursor.execute(
            "SELECT count(*) FROM evaluation_audit_events WHERE session_id = ? AND event_type = 'ATTEMPT_FAILED';",
            (session_id,),
        )
        assert cursor.fetchone()[0] == 2

        assert verify_audit_chain(conn, session_id=session_id) is True
