"""Provider Adapters and Deterministic Offline Mock Adapters (Task 8.2 Checkpoint A).

Enforces:
1. Common BaseProviderAdapter abstraction.
2. Deterministic offline responses without network access.
3. Realistic error simulation: HTTP 429 rate limits, HTTP 500 errors, socket timeouts,
   and JSON schema validation failures.
4. Accurate reporting of resolved checkpoint, family, creator, and token metrics.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.evaluation.blinded_serializer import BlindedCasePayload
from backend.app.evaluation.schema import (
    EVALUATION_OUTPUT_JSON_SCHEMA,
    ParsedEvaluationOutput,
)


class ModelInferenceResponse(BaseModel):
    """Normalized response from a model evaluation attempt."""

    success: bool
    http_status: int
    latency_ms: int
    reported_input_tokens: int = 0
    reported_output_tokens: int = 0
    match_tier: Literal["TIER_1", "TIER_2", "TIER_3", "TIER_4"] | None = None
    match_score: float | None = None
    reasoning: str | None = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None
    retry_after_seconds: int | None = None
    raw_response_body: str = ""
    resolved_checkpoint_id: str
    resolved_family_id: str
    resolved_creator_entity: str
    system_fingerprint: str | None = None


class BaseProviderAdapter(ABC):
    """Abstract interface for multi-model evaluation adapters."""

    @abstractmethod
    def execute_inference(self, payload: BlindedCasePayload) -> ModelInferenceResponse:
        """Execute model assessment on a blinded case payload."""


class MockAdapterConfig(BaseModel):
    """Configuration for deterministic offline mock provider adapter."""

    candidate_id: str
    provider_id: str
    model_alias: str
    resolved_checkpoint_id: str
    resolved_family_id: str
    resolved_creator_entity: str
    behavior_mode: Literal[
        "SUCCESS",
        "RATE_LIMIT_429",
        "SERVER_ERROR_500",
        "TIMEOUT",
        "MALFORMED_JSON",
        "UNKNOWN_CHECKPOINT",
    ] = "SUCCESS"
    retry_after_seconds: int | None = None
    system_fingerprint: str | None = "fp_mock_v1"


class MockProviderAdapter(BaseProviderAdapter):
    """Deterministic offline adapter simulating frontier provider inference without external network calls."""

    def __init__(self, config: MockAdapterConfig) -> None:
        self.config = config

    def execute_inference(self, payload: BlindedCasePayload) -> ModelInferenceResponse:
        """Generate a deterministic response based on the case ID and configured behavior."""
        checkpoint_id = (
            "undisclosed_checkpoint_unknown"
            if self.config.behavior_mode == "UNKNOWN_CHECKPOINT"
            else self.config.resolved_checkpoint_id
        )

        # 1. Simulate 429 Rate Limit
        if self.config.behavior_mode == "RATE_LIMIT_429":
            retry_sec = self.config.retry_after_seconds or 15
            return ModelInferenceResponse(
                success=False,
                http_status=429,
                latency_ms=120,
                error_type="HTTP_429_RATE_LIMIT",
                error_message=f"Rate limit exceeded. Retry after {retry_sec} seconds.",
                retry_after_seconds=retry_sec,
                raw_response_body=json.dumps({"error": {"code": 429, "message": "Rate limit exceeded"}}),
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=self.config.resolved_family_id,
                resolved_creator_entity=self.config.resolved_creator_entity,
                system_fingerprint=self.config.system_fingerprint,
            )

        # 2. Simulate 500 Server Error
        if self.config.behavior_mode == "SERVER_ERROR_500":
            return ModelInferenceResponse(
                success=False,
                http_status=500,
                latency_ms=350,
                error_type="HTTP_5XX_SERVER_ERROR",
                error_message="Internal server error encountered by provider backend.",
                raw_response_body=json.dumps({"error": {"code": 500, "message": "Internal error"}}),
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=self.config.resolved_family_id,
                resolved_creator_entity=self.config.resolved_creator_entity,
                system_fingerprint=self.config.system_fingerprint,
            )

        # 3. Simulate Socket Timeout
        if self.config.behavior_mode == "TIMEOUT":
            return ModelInferenceResponse(
                success=False,
                http_status=0,
                latency_ms=30000,
                error_type="TIMEOUT_CLIENT",
                error_message="Client socket timeout after 30000ms waiting for provider response.",
                raw_response_body="",
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=self.config.resolved_family_id,
                resolved_creator_entity=self.config.resolved_creator_entity,
                system_fingerprint=self.config.system_fingerprint,
            )

        # 4. Simulate Malformed JSON / Schema Failure
        if self.config.behavior_mode == "MALFORMED_JSON":
            return ModelInferenceResponse(
                success=False,
                http_status=200,
                latency_ms=280,
                error_type="SCHEMA_VALIDATION_FAILURE",
                error_message="Failed to parse model output into required JSON schema.",
                raw_response_body="INVALID_RESPONSE_NOT_JSON: <<EOF truncated",
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=self.config.resolved_family_id,
                resolved_creator_entity=self.config.resolved_creator_entity,
                system_fingerprint=self.config.system_fingerprint,
            )

        # 5. Deterministic Success Mode
        hash_seed = f"{payload.case_id}:{self.config.candidate_id}"
        h_val = int(hashlib.sha256(hash_seed.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF

        if h_val >= 0.70:
            tier: Literal["TIER_1", "TIER_2", "TIER_3", "TIER_4"] = "TIER_1"
            score = round(0.85 + (h_val - 0.70) * 0.5, 2)
        elif h_val >= 0.45:
            tier = "TIER_2"
            score = round(0.65 + (h_val - 0.45) * 0.7, 2)
        elif h_val >= 0.20:
            tier = "TIER_3"
            score = round(0.40 + (h_val - 0.20) * 0.9, 2)
        else:
            tier = "TIER_4"
            score = round(0.10 + h_val * 1.4, 2)

        score = min(1.0, max(0.0, score))

        top_comp = (
            payload.job_posting.requirements.core_competencies[0]
            if payload.job_posting.requirements.core_competencies
            else "Experience"
        )
        body_dict = {
            "match_tier": tier,
            "match_score": score,
            "reasoning": (
                f"Offline evaluation for case '{payload.case_id}' assessed by model '{self.config.model_alias}'. "
                f"Candidate exhibits alignment with stated requirements: {payload.job_posting.requirements.core_competencies[:2]}."
            ),
            "citations": [
                {
                    "source_section": "requirements",
                    "quote": top_comp,
                    "payload_start": 0,
                    "payload_end": len(top_comp),
                }
            ],
        }

        # Estimate realistic token counts
        input_tokens = len(payload.job_posting.description_plain.split()) + 350
        output_tokens = 160

        return ModelInferenceResponse(
            success=True,
            http_status=200,
            latency_ms=450,
            reported_input_tokens=input_tokens,
            reported_output_tokens=output_tokens,
            match_tier=tier,
            match_score=score,
            reasoning=body_dict["reasoning"],
            citations=body_dict["citations"],
            raw_response_body=json.dumps(body_dict, sort_keys=True),
            resolved_checkpoint_id=checkpoint_id,
            resolved_family_id=self.config.resolved_family_id,
            resolved_creator_entity=self.config.resolved_creator_entity,
            system_fingerprint=self.config.system_fingerprint,
        )


from backend.app.evaluation.anthropic_adapter import (
    AnthropicAdapterConfig,
    AnthropicProviderAdapter,
)
from backend.app.evaluation.openai_adapter import (
    OpenAIAdapterConfig,
    OpenAIProviderAdapter,
)


__all__ = [
    "BaseProviderAdapter",
    "ModelInferenceResponse",
    "MockAdapterConfig",
    "MockProviderAdapter",
    "AnthropicAdapterConfig",
    "AnthropicProviderAdapter",
    "OpenAIAdapterConfig",
    "OpenAIProviderAdapter",
    "EVALUATION_OUTPUT_JSON_SCHEMA",
    "ParsedEvaluationOutput",
]
