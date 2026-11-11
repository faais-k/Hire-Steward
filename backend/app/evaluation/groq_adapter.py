"""Groq Provider Adapter for Frontier Evaluation and Inference.

Enforces:
1. Structured JSON output via Chat Completions JSON Mode / Schema.
2. Low-latency inference over Llama 3.3 and open-weights models.
3. Strict error classification matching Evaluation Ledger invariants
   (HTTP 429, HTTP 5xx, socket timeout, schema validation failure).
4. Secret-safe API key handling preventing secret leakage in repr or logs.
5. Pluggable HTTP transport allowing deterministic offline testing without external network egress.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from backend.app.evaluation.adapters import BaseProviderAdapter, ModelInferenceResponse
from backend.app.evaluation.anthropic_adapter import format_evaluation_prompt
from backend.app.evaluation.blinded_serializer import BlindedCasePayload
from backend.app.evaluation.credentials import get_groq_api_key
from backend.app.evaluation.schema import (
    EVALUATION_OUTPUT_JSON_SCHEMA,
    ParsedEvaluationOutput,
)


class GroqAdapterConfig(BaseModel):
    """Configuration for Groq provider adapter."""

    model_config = ConfigDict(extra="ignore")

    candidate_id: str = "evaluator_groq"
    provider_id: str = "groq"
    model_alias: str = "llama-3.3-70b-versatile"
    resolved_checkpoint_id: str = "llama-3.3-70b-versatile"
    resolved_family_id: str = "llama-3.3"
    resolved_creator_entity: str = "meta"
    base_url: str = "https://api.groq.com/openai"
    timeout_seconds: float = 30.0
    max_tokens: int = 1024
    temperature: float = 0.0
    api_key: SecretStr | None = Field(default=None, repr=False)
    system_fingerprint: str | None = None


class GroqProviderAdapter(BaseProviderAdapter):
    """Groq API adapter supporting OpenAI-compatible chat completions and structured JSON."""

    def __init__(
        self,
        config: GroqAdapterConfig | None = None,
        api_key: SecretStr | str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config or GroqAdapterConfig()
        if api_key is not None:
            resolved_key = SecretStr(api_key) if isinstance(api_key, str) else api_key
        else:
            resolved_key = self.config.api_key or get_groq_api_key()
        self.api_key = resolved_key
        self.transport = transport

    def execute_inference(self, payload: BlindedCasePayload) -> ModelInferenceResponse:
        """Execute Groq inference using Chat Completions with JSON mode."""
        checkpoint_id = self.config.resolved_checkpoint_id
        family_id = self.config.resolved_family_id
        creator = self.config.resolved_creator_entity

        # 1. Pre-flight credential check
        if self.api_key is None or not self.api_key.get_secret_value():
            return ModelInferenceResponse(
                success=False,
                http_status=401,
                latency_ms=0,
                error_type="HTTP_401_AUTH_REVOKED",
                error_message="Groq API key is missing or not configured.",
                raw_response_body="",
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=family_id,
                resolved_creator_entity=creator,
                system_fingerprint=self.config.system_fingerprint,
            )

        url = f"{self.config.base_url.rstrip('/')}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }

        prompt_content = format_evaluation_prompt(payload)
        request_body: dict[str, Any] = {
            "model": self.config.resolved_checkpoint_id,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an expert, impartial job-matching evaluation assessor. "
                        "Evaluate the candidate alignment and output strictly formatted JSON conforming to the schema:\n"
                        f"{json.dumps(EVALUATION_OUTPUT_JSON_SCHEMA)}"
                    ),
                },
                {
                    "role": "user",
                    "content": prompt_content,
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }

        start_time = time.perf_counter()
        try:
            with httpx.Client(
                transport=self.transport,
                timeout=self.config.timeout_seconds,
            ) as client:
                resp = client.post(url, headers=headers, json=request_body)
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)

        except httpx.TimeoutException as exc:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            return ModelInferenceResponse(
                success=False,
                http_status=0,
                latency_ms=elapsed_ms,
                error_type="TIMEOUT_CLIENT",
                error_message=f"Groq request timed out after {self.config.timeout_seconds}s: {exc}",
                raw_response_body="",
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=family_id,
                resolved_creator_entity=creator,
                system_fingerprint=self.config.system_fingerprint,
            )
        except httpx.RequestError as exc:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            return ModelInferenceResponse(
                success=False,
                http_status=0,
                latency_ms=elapsed_ms,
                error_type="HTTP_5XX_SERVER_ERROR",
                error_message=f"Groq transport connection error: {exc}",
                raw_response_body="",
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=family_id,
                resolved_creator_entity=creator,
                system_fingerprint=self.config.system_fingerprint,
            )

        raw_body = resp.text

        # 2. Rate limit (HTTP 429)
        if resp.status_code == 429:
            retry_after = 15
            retry_header = resp.headers.get("retry-after")
            if retry_header and retry_header.isdigit():
                retry_after = int(retry_header)
            return ModelInferenceResponse(
                success=False,
                http_status=429,
                latency_ms=elapsed_ms,
                error_type="HTTP_429_RATE_LIMIT",
                error_message="Groq rate limit exceeded.",
                retry_after_seconds=retry_after,
                raw_response_body=raw_body,
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=family_id,
                resolved_creator_entity=creator,
                system_fingerprint=self.config.system_fingerprint,
            )

        # 3. Server errors (HTTP 5xx)
        if resp.status_code >= 500:
            return ModelInferenceResponse(
                success=False,
                http_status=resp.status_code,
                latency_ms=elapsed_ms,
                error_type="HTTP_5XX_SERVER_ERROR",
                error_message=f"Groq server error: HTTP {resp.status_code}",
                raw_response_body=raw_body,
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=family_id,
                resolved_creator_entity=creator,
                system_fingerprint=self.config.system_fingerprint,
            )

        # 4. Authentication / Client errors
        if resp.status_code != 200:
            return ModelInferenceResponse(
                success=False,
                http_status=resp.status_code,
                latency_ms=elapsed_ms,
                error_type="HTTP_401_AUTH_REVOKED" if resp.status_code in (401, 403) else f"HTTP_{resp.status_code}_CLIENT_ERROR",
                error_message=f"Groq returned HTTP {resp.status_code}: {raw_body[:200]}",
                raw_response_body=raw_body,
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=family_id,
                resolved_creator_entity=creator,
                system_fingerprint=self.config.system_fingerprint,
            )

        # 5. Parse response body and usage
        try:
            resp_json = resp.json()
        except Exception as exc:
            return ModelInferenceResponse(
                success=False,
                http_status=200,
                latency_ms=elapsed_ms,
                error_type="MALFORMED_OUTPUT_SCHEMA",
                error_message=f"Failed to parse Groq response JSON: {exc}",
                raw_response_body=raw_body,
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=family_id,
                resolved_creator_entity=creator,
                system_fingerprint=self.config.system_fingerprint,
            )

        usage = resp_json.get("usage", {})
        input_tokens = int(usage.get("prompt_tokens", 0))
        output_tokens = int(usage.get("completion_tokens", 0))
        fp = resp_json.get("system_fingerprint") or self.config.system_fingerprint

        choices = resp_json.get("choices", [])
        if not choices:
            return ModelInferenceResponse(
                success=False,
                http_status=200,
                latency_ms=elapsed_ms,
                reported_input_tokens=input_tokens,
                reported_output_tokens=output_tokens,
                error_type="MALFORMED_OUTPUT_SCHEMA",
                error_message="Groq response contained no choices.",
                raw_response_body=raw_body,
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=family_id,
                resolved_creator_entity=creator,
                system_fingerprint=fp,
            )

        msg_content = choices[0].get("message", {}).get("content", "")
        if not msg_content:
            return ModelInferenceResponse(
                success=False,
                http_status=200,
                latency_ms=elapsed_ms,
                reported_input_tokens=input_tokens,
                reported_output_tokens=output_tokens,
                error_type="MALFORMED_OUTPUT_SCHEMA",
                error_message="Groq response choice content was empty.",
                raw_response_body=raw_body,
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=family_id,
                resolved_creator_entity=creator,
                system_fingerprint=fp,
            )

        # 6. Parse structured schema output
        try:
            parsed = ParsedEvaluationOutput.model_validate_json(msg_content)
        except Exception as exc:
            return ModelInferenceResponse(
                success=False,
                http_status=200,
                latency_ms=elapsed_ms,
                reported_input_tokens=input_tokens,
                reported_output_tokens=output_tokens,
                error_type="MALFORMED_OUTPUT_SCHEMA",
                error_message=f"Groq structured output schema validation failed: {exc}",
                raw_response_body=raw_body,
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=family_id,
                resolved_creator_entity=creator,
                system_fingerprint=fp,
            )

        return ModelInferenceResponse(
            success=True,
            http_status=200,
            latency_ms=elapsed_ms,
            reported_input_tokens=input_tokens,
            reported_output_tokens=output_tokens,
            match_tier=parsed.match_tier,
            match_score=parsed.match_score,
            reasoning=parsed.reasoning,
            citations=[c.model_dump() for c in parsed.citations],
            raw_response_body=raw_body,
            resolved_checkpoint_id=checkpoint_id,
            resolved_family_id=family_id,
            resolved_creator_entity=creator,
            system_fingerprint=fp,
        )
