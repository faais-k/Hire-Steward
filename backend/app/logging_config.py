"""Operational logging, correlation IDs, and secret/PII redaction (Stage 1).

Guarantees:
1. Contextual correlation ID tracking across async request lifecycles.
2. Automated redaction of sensitive credentials, API keys, and candidate contact PII in log records.
3. Structured log formatting suitable for local-first operational visibility.
"""

from __future__ import annotations

import contextvars
import logging
import re
from typing import Any

# Context variable for request correlation ID
correlation_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)

# Regex patterns for sensitive credentials and contact PII
SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9_\-]{20,}", re.IGNORECASE),
    re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]{20,}", re.IGNORECASE),
    re.compile(r"HIRE_STEWARD_[A-Z0-9_]+=[^\s]+", re.IGNORECASE),
    re.compile(r"x-api-key['\"]?:\s*['\"][^'\"]+['\"]", re.IGNORECASE),
]

PII_PATTERNS = [
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
]


class RedactingFormatter(logging.Formatter):
    """Custom formatter redacting secrets, API keys, and personal candidate contact info."""

    def format(self, record: logging.LogRecord) -> str:
        # Inject correlation ID if available
        cid = correlation_id_ctx.get()
        if not hasattr(record, "correlation_id") or not record.correlation_id:
            record.correlation_id = cid or "-"

        original_msg = super().format(record)
        redacted = original_msg

        # Redact secrets
        for pattern in SECRET_PATTERNS:
            redacted = pattern.sub("[REDACTED_SECRET]", redacted)

        # Redact candidate contact PII
        for pattern in PII_PATTERNS:
            redacted = pattern.sub("[REDACTED_PII]", redacted)

        return redacted


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logger with redacting formatter and correlation tracking."""
    handler = logging.StreamHandler()
    formatter = RedactingFormatter(
        "[%(asctime)s] [%(correlation_id)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    # Avoid duplicate handlers if reconfigured
    root_logger.handlers = [handler]
    root_logger.setLevel(level)
