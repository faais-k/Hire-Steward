"""Anthropic Provider Adapter for Frontier Evaluation (Task 8.2 Checkpoint B Stage B1).

Enforces:
1. Native structured output via `output_config.format` JSON Schema.
2. Complete omission of `temperature`, `top_p`, `top_k`, and forced `tool_choice`
   (preventing HTTP 400 errors on `claude-sonnet-5-5`).
3. Output parsing from `content[0].text`.
4. Strict error classification matching Checkpoint A ledger state invariants
   (HTTP 429, HTTP 5xx, socket timeout, schema validation failure).
5. Secret-safe API key handling preventing secret leakage in repr or logs.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from backend.app.evaluation.adapters import BaseProviderAdapter, ModelInferenceResponse
from backend.app.evaluation.blinded_serializer import BlindedCasePayload
from backend.app.evaluation.credentials import get_anthropic_api_key
from backend.app.evaluation.schema import (
    EVALUATION_OUTPUT_JSON_SCHEMA,
    ParsedEvaluationOutput,
)


class AnthropicAdapterConfig(BaseModel):
    """Configuration for Anthropic provider adapter."""

    model_config = ConfigDict(extra="ignore")

    candidate_id: str = "evaluator_a_anthropic"
    provider_id: str = "anthropic"
    model_alias: str = "claude-sonnet-5-5"
    resolved_checkpoint_id: str = "claude-sonnet-5-5"
    resolved_family_id: str = "claude-sonnet-5"
    resolved_creator_entity: str = "anthropic"
    base_url: str = "https://api.anthropic.com"
    timeout_seconds: float = 30.0
    max_tokens: int = 1024
    api_key: SecretStr | None = Field(default=None, repr=False)
    system_fingerprint: str | None = None


def format_evaluation_prompt(payload: BlindedCasePayload) -> str:
    """Format a deterministic prompt from the blinded case payload."""
    payload_dict = payload.model_dump(mode="json", exclude={"masking_result"})
    serialized_case = json.dumps(payload_dict, indent=2, sort_keys=True)

    return (
        "You are an expert, impartial job-matching evaluation assessor.\n"
        "Your task is to evaluate the match between the provided Job Posting and the Candidate Profile.\n\n"
        "Evaluation Instructions:\n"
        "1. Assess candidate alignment across mandatory constraints, core competencies, and preferred qualifications.\n"
        "2. Assign an overall match tier:\n"
        '   - "TIER_1": Strong match meeting all mandatory constraints and core competencies.\n'
        '   - "TIER_2": Good match with minor gaps in non-critical areas.\n'
        '   - "TIER_3": Marginal match with substantial gaps in core requirements.\n'
        '   - "TIER_4": Poor match or unqualified for the role.\n'
        "3. Assign a continuous normalized match score between 0.00 and 1.00.\n"
        "4. Provide detailed, objective reasoning explaining the evaluation.\n"
        "5. Provide exact verbatim citations from the job posting or candidate profile payload supporting your rating,\n"
        "   including source_section, quote, payload_start character offset, and payload_end character offset.\n\n"
        f"Blinded Evaluation Case Payload:\n{serialized_case}\n"
    )


class AnthropicProviderAdapter(BaseProviderAdapter):
    """Anthropic Messages API adapter supporting native structured output."""

    def __init__(
        self,
        config: AnthropicAdapterConfig | None = None,
        api_key: SecretStr | str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config or AnthropicAdapterConfig()
        if api_key is not None:
            resolved_key = SecretStr(api_key) if isinstance(api_key, str) else api_key
        else:
            resolved_key = self.config.api_key or get_anthropic_api_key()
        self.api_key = resolved_key
        self.transport = transport

    def execute_inference(self, payload: BlindedCasePayload) -> ModelInferenceResponse:
        """Execute Anthropic inference using native structured JSON output."""
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
                error_message="Anthropic API key is missing or not configured.",
                raw_response_body="",
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=family_id,
                resolved_creator_entity=creator,
                system_fingerprint=self.config.system_fingerprint,
            )

        url = f"{self.config.base_url.rstrip('/')}/v1/messages"
        headers = {
            "x-api-key": self.api_key.get_secret_value(),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        # Build request body:
        # Note: Do NOT include 'temperature', 'top_p', 'top_k', or 'tool_choice'
        # Sonnet 5.5 returns HTTP 400 if any of these are specified.
        prompt_content = format_evaluation_prompt(payload)
        request_body = {
            "model": self.config.resolved_checkpoint_id,
            "max_tokens": self.config.max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": prompt_content,
                }
            ],
            "output_config": {
                "format": {
                    "type": "json_schema",
                    "schema": EVALUATION_OUTPUT_JSON_SCHEMA,
                }
            },
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
                error_message=f"Anthropic request timed out after {self.config.timeout_seconds}s: {exc}",
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
                error_message=f"Anthropic transport connection error: {exc}",
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
                error_message="Anthropic rate limit exceeded.",
                retry_after_seconds=retry_after,
                raw_response_body=raw_body,
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=family_id,
                resolved_creator_entity=creator,
                system_fingerprint=self.config.system_fingerprint,
            )

        # 3. Authentication / Access errors
        if resp.status_code == 401:
            return ModelInferenceResponse(
                success=False,
                http_status=401,
                latency_ms=elapsed_ms,
                error_type="HTTP_401_AUTH_REVOKED",
                error_message="Anthropic authentication failed. Invalid API key.",
                raw_response_body=raw_body,
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=family_id,
                resolved_creator_entity=creator,
                system_fingerprint=self.config.system_fingerprint,
            )
        if resp.status_code == 403:
            return ModelInferenceResponse(
                success=False,
                http_status=403,
                latency_ms=elapsed_ms,
                error_type="HTTP_403_ACCESS_RESTRICTED",
                error_message="Anthropic access restricted or forbidden.",
                raw_response_body=raw_body,
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=family_id,
                resolved_creator_entity=creator,
                system_fingerprint=self.config.system_fingerprint,
            )

        # 4. Server errors (HTTP 5xx)
        if resp.status_code >= 500:
            return ModelInferenceResponse(
                success=False,
                http_status=resp.status_code,
                latency_ms=elapsed_ms,
                error_type="HTTP_5XX_SERVER_ERROR",
                error_message=f"Anthropic returned server error {resp.status_code}.",
                raw_response_body=raw_body,
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=family_id,
                resolved_creator_entity=creator,
                system_fingerprint=self.config.system_fingerprint,
            )

        # 5. Client errors (HTTP 4xx other than 401/403/429)
        if resp.status_code != 200:
            return ModelInferenceResponse(
                success=False,
                http_status=resp.status_code,
                latency_ms=elapsed_ms,
                error_type="SCHEMA_VALIDATION_FAILURE",
                error_message=f"Anthropic API returned error HTTP {resp.status_code}: {raw_body[:200]}",
                raw_response_body=raw_body,
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=family_id,
                resolved_creator_entity=creator,
                system_fingerprint=self.config.system_fingerprint,
            )

        # 6. Parse 200 OK response
        try:
            resp_json = resp.json()
        except Exception as exc:
            return ModelInferenceResponse(
                success=False,
                http_status=200,
                latency_ms=elapsed_ms,
                error_type="SCHEMA_VALIDATION_FAILURE",
                error_message=f"Anthropic response body was not valid JSON: {exc}",
                raw_response_body=raw_body,
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=family_id,
                resolved_creator_entity=creator,
                system_fingerprint=self.config.system_fingerprint,
            )

        usage = resp_json.get("usage") or {}
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)

        # Content blocks: Anthropic structured output returns text in content[0].text
        content_blocks = resp_json.get("content") or []
        text_content = ""
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                text_content = block.get("text", "")
                break

        if not text_content:
            return ModelInferenceResponse(
                success=False,
                http_status=200,
                latency_ms=elapsed_ms,
                reported_input_tokens=input_tokens,
                reported_output_tokens=output_tokens,
                error_type="SCHEMA_VALIDATION_FAILURE",
                error_message="No text content block found in Anthropic structured response.",
                raw_response_body=raw_body,
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=family_id,
                resolved_creator_entity=creator,
                system_fingerprint=self.config.system_fingerprint,
            )

        # Parse the structured JSON inside text_content
        try:
            parsed_dict = json.loads(text_content)
            parsed_output = ParsedEvaluationOutput.model_validate(parsed_dict)
        except Exception as exc:
            return ModelInferenceResponse(
                success=False,
                http_status=200,
                latency_ms=elapsed_ms,
                reported_input_tokens=input_tokens,
                reported_output_tokens=output_tokens,
                error_type="SCHEMA_VALIDATION_FAILURE",
                error_message=f"Model output did not conform to evaluation JSON schema: {exc}",
                raw_response_body=raw_body,
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=family_id,
                resolved_creator_entity=creator,
                system_fingerprint=self.config.system_fingerprint,
            )

        citations_list = [c.model_dump() for c in parsed_output.citations]

        return ModelInferenceResponse(
            success=True,
            http_status=200,
            latency_ms=elapsed_ms,
            reported_input_tokens=input_tokens,
            reported_output_tokens=output_tokens,
            match_tier=parsed_output.match_tier,
            match_score=parsed_output.match_score,
            reasoning=parsed_output.reasoning,
            citations=citations_list,
            raw_response_body=raw_body,
            resolved_checkpoint_id=checkpoint_id,
            resolved_family_id=family_id,
            resolved_creator_entity=creator,
            system_fingerprint=self.config.system_fingerprint or resp_json.get("id"),
        )
