"""Structured JSON Output Schemas for Frontier Evaluator Inference (Task 8.2 Checkpoint B).

Defines the exact schema contract shared across Anthropic and OpenAI adapters.
Complies with OpenAI `strict: true` requirements (all properties required, additionalProperties: false)
and Anthropic `output_config.format` JSON schema specifications.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

EVALUATION_OUTPUT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "match_tier": {
            "type": "string",
            "enum": ["TIER_1", "TIER_2", "TIER_3", "TIER_4"],
            "description": "Deterministic fit tier classification for the candidate against the role requirements.",
        },
        "match_score": {
            "type": "number",
            "description": "Continuous match score between 0.00 and 1.00 indicating fit intensity.",
        },
        "reasoning": {
            "type": "string",
            "description": "Comprehensive justification and synthesis of evidence supporting the rating.",
        },
        "citations": {
            "type": "array",
            "description": "Verbatim citations from the job posting or candidate profile payload.",
            "items": {
                "type": "object",
                "properties": {
                    "source_section": {
                        "type": "string",
                        "description": "Section from which quote is extracted (e.g. requirements, job_description, experience).",
                    },
                    "quote": {
                        "type": "string",
                        "description": "Exact verbatim string extracted from the blinded payload.",
                    },
                    "payload_start": {
                        "type": "integer",
                        "description": "Zero-based start character offset of quote within that section.",
                    },
                    "payload_end": {
                        "type": "integer",
                        "description": "Zero-based end character offset of quote within that section.",
                    },
                },
                "required": ["source_section", "quote", "payload_start", "payload_end"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["match_tier", "match_score", "reasoning", "citations"],
    "additionalProperties": False,
}


class ParsedCitation(BaseModel):
    """Citation extracted from model output."""

    model_config = ConfigDict(extra="ignore")

    source_section: str
    quote: str
    payload_start: int
    payload_end: int


class ParsedEvaluationOutput(BaseModel):
    """Parsed and validated evaluation model output."""

    model_config = ConfigDict(extra="ignore")

    match_tier: Literal["TIER_1", "TIER_2", "TIER_3", "TIER_4"]
    match_score: float = Field(ge=0.0, le=1.0)
    reasoning: str
    citations: list[ParsedCitation] = Field(default_factory=list)
