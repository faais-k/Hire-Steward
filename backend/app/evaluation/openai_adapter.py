"""OpenAI Provider Adapter for Frontier Evaluation (Task 8.2 Checkpoint B Stage B1).

Enforces:
1. Strict structured JSON output via Chat Completions `response_format` with `strict: true`.
2. Privacy compliance with `"store": False` to disable server-side logging/retention.
3. Configurable reasoning effort with omission of `temperature`/`top_p` for reasoning models.
4. Output parsing from `choices[0].message.content`.
5. Strict error classification matching Checkpoint A ledger state invariants
   (HTTP 429, HTTP 5xx, socket timeout, schema validation failure).
6. Secret-safe API key handling preventing secret leakage in repr or logs.
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
from backend.app.evaluation.credentials import get_openai_api_key
from backend.app.evaluation.schema import (
    EVALUATION_OUTPUT_JSON_SCHEMA,
    ParsedEvaluationOutput,
)


class OpenAIAdapterConfig(BaseModel):
    """Configuration for OpenAI provider adapter."""

    model_config = ConfigDict(extra="ignore")

    candidate_id: str = "evaluator_b_openai"
    provider_id: str = "openai"
    model_alias: str = "gpt-6.1-sol"
    resolved_checkpoint_id: str = "gpt-6.1-sol"
    resolved_family_id: str = "gpt-6.1"
    resolved_creator_entity: str = "openai"
    base_url: str = "https://api.openai.com"
    timeout_seconds: float = 30.0
    max_tokens: int = 1024
    store: bool = False
    reasoning_effort: str | None = None
    api_key: SecretStr | None = Field(default=None, repr=False)
    system_fingerprint: str | None = None


class OpenAIProviderAdapter(BaseProviderAdapter):
    """OpenAI Chat Completions API adapter supporting strict JSON schema structured output."""

    def __init__(
        self,
        config: OpenAIAdapterConfig | None = None,
        api_key: SecretStr | str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config or OpenAIAdapterConfig()
        if api_key is not None:
            resolved_key = SecretStr(api_key) if isinstance(api_key, str) else api_key
        else:
            resolved_key = self.config.api_key or get_openai_api_key()
        self.api_key = resolved_key
        self.transport = transport

    def execute_inference(self, payload: BlindedCasePayload) -> ModelInferenceResponse:
        """Execute OpenAI inference using Chat Completions with strict structured JSON schema."""
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
                error_message="OpenAI API key is missing or not configured.",
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
                        "Evaluate the candidate alignment and output strictly formatted JSON conforming to the schema."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt_content,
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "record_match_evaluation",
                    "strict": True,
                    "schema": EVALUATION_OUTPUT_JSON_SCHEMA,
                },
            },
            "store": self.config.store,
        }

        if self.config.reasoning_effort is not None:
            request_body["reasoning_effort"] = self.config.reasoning_effort

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
                error_message=f"OpenAI request timed out after {self.config.timeout_seconds}s: {exc}",
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
                error_message=f"OpenAI transport connection error: {exc}",
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
                error_message="OpenAI rate limit exceeded.",
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
                error_message="OpenAI authentication failed. Invalid API key.",
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
                error_message="OpenAI access restricted or forbidden.",
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
                error_message=f"OpenAI returned server error {resp.status_code}.",
                raw_response_body=raw_body,
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=family_id,
                resolved_creator_entity=creator,
                system_fingerprint=self.config.system_fingerprint,
            )

        # 5. Client errors (HTTP 4xx)
        if resp.status_code != 200:
            return ModelInferenceResponse(
                success=False,
                http_status=resp.status_code,
                latency_ms=elapsed_ms,
                error_type="SCHEMA_VALIDATION_FAILURE",
                error_message=f"OpenAI API returned error HTTP {resp.status_code}: {raw_body[:200]}",
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
                error_message=f"OpenAI response body was not valid JSON: {exc}",
                raw_response_body=raw_body,
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=family_id,
                resolved_creator_entity=creator,
                system_fingerprint=self.config.system_fingerprint,
            )

        usage = resp_json.get("usage") or {}
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        sys_fp = resp_json.get("system_fingerprint") or self.config.system_fingerprint

        choices = resp_json.get("choices") or []
        text_content = ""
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") or {}
            text_content = message.get("content") or ""

        if not text_content:
            return ModelInferenceResponse(
                success=False,
                http_status=200,
                latency_ms=elapsed_ms,
                reported_input_tokens=input_tokens,
                reported_output_tokens=output_tokens,
                error_type="SCHEMA_VALIDATION_FAILURE",
                error_message="No message content found in OpenAI choice output.",
                raw_response_body=raw_body,
                resolved_checkpoint_id=checkpoint_id,
                resolved_family_id=family_id,
                resolved_creator_entity=creator,
                system_fingerprint=sys_fp,
            )

        # Parse structured JSON inside text_content
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
                system_fingerprint=sys_fp,
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
            system_fingerprint=sys_fp,
        )
