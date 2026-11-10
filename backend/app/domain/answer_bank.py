"""Domain logic and models for Answer Bank (Stage 2 & Stage 5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

VALID_CATEGORIES = {
    "behavioral",
    "technical",
    "compensation",
    "logistics",
    "work_authorization",
    "general",
    "experience",
}


class AnswerBankError(Exception):
    """Raised when answer bank validation fails."""

    def __init__(self, message: str, code: str = "INVALID_ANSWER_BANK_DATA") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class AnswerBankEntry:
    id: str
    question: str
    answer: str
    category: str = "general"
    fact_ids: list[str] = field(default_factory=list)
    reuse_consent: bool = False
    version: int = 1
    is_revoked: bool = False
    created_at: str | None = None
    updated_at: str | None = None

    def validate(self) -> None:
        if not self.question or not self.question.strip():
            raise AnswerBankError("Question text cannot be empty", code="EMPTY_QUESTION")
        if not self.answer or not self.answer.strip():
            raise AnswerBankError("Answer text cannot be empty", code="EMPTY_ANSWER")
        if self.category not in VALID_CATEGORIES:
            raise AnswerBankError(
                f"Invalid category '{self.category}'. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}",
                code="INVALID_CATEGORY",
            )
        if self.is_revoked and self.reuse_consent:
            raise AnswerBankError(
                "Cannot grant reuse consent to a revoked answer",
                code="REVOKED_ANSWER_CONSENT_FORBIDDEN",
            )
