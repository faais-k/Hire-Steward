"""Provider credentials management for offline evaluation (Task 8.2 Checkpoint B Stage B1).

Guarantees:
1. Environment-based credential loading for HIRE_STEWARD_ANTHROPIC_API_KEY, HIRE_STEWARD_OPENAI_API_KEY,
   HIRE_STEWARD_GROQ_API_KEY, and HIRE_STEWARD_GEMINI_API_KEY.
2. Secure secret wrapping using Pydantic SecretStr to prevent credential leakage in logs, __repr__, or stack traces.
3. Explicit validation methods distinguishing missing credentials from populated credentials.
4. Zero plaintext leakage in any representation or formatting.
"""

from __future__ import annotations

import os
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class ProviderCredentials(BaseModel):
    """Holds optional secret keys and configurations for evaluation and inference providers."""

    model_config = ConfigDict(frozen=True)

    anthropic_api_key: SecretStr | None = Field(default=None, repr=False)
    openai_api_key: SecretStr | None = Field(default=None, repr=False)
    groq_api_key: SecretStr | None = Field(default=None, repr=False)
    gemini_api_key: SecretStr | None = Field(default=None, repr=False)
    ollama_base_url: str = Field(default="http://127.0.0.1:11434")

    @property
    def has_anthropic(self) -> bool:
        return self.anthropic_api_key is not None and bool(self.anthropic_api_key.get_secret_value())

    @property
    def has_openai(self) -> bool:
        return self.openai_api_key is not None and bool(self.openai_api_key.get_secret_value())

    @property
    def has_groq(self) -> bool:
        return self.groq_api_key is not None and bool(self.groq_api_key.get_secret_value())

    @property
    def has_gemini(self) -> bool:
        return self.gemini_api_key is not None and bool(self.gemini_api_key.get_secret_value())

    @property
    def has_ollama(self) -> bool:
        return bool(self.ollama_base_url)


def get_anthropic_api_key(env: Mapping[str, str] | None = None) -> SecretStr | None:
    """Retrieve Anthropic API key from environment if present and non-empty."""
    source = env if env is not None else os.environ
    raw = source.get("HIRE_STEWARD_ANTHROPIC_API_KEY")
    if raw is None or not raw.strip():
        return None
    return SecretStr(raw.strip())


def get_openai_api_key(env: Mapping[str, str] | None = None) -> SecretStr | None:
    """Retrieve OpenAI API key from environment if present and non-empty."""
    source = env if env is not None else os.environ
    raw = source.get("HIRE_STEWARD_OPENAI_API_KEY")
    if raw is None or not raw.strip():
        return None
    return SecretStr(raw.strip())


def get_groq_api_key(env: Mapping[str, str] | None = None) -> SecretStr | None:
    """Retrieve Groq API key from environment if present and non-empty."""
    source = env if env is not None else os.environ
    raw = source.get("HIRE_STEWARD_GROQ_API_KEY")
    if raw is None or not raw.strip():
        return None
    return SecretStr(raw.strip())


def get_gemini_api_key(env: Mapping[str, str] | None = None) -> SecretStr | None:
    """Retrieve Google Gemini API key from environment if present and non-empty."""
    source = env if env is not None else os.environ
    raw = source.get("HIRE_STEWARD_GEMINI_API_KEY")
    if raw is None or not raw.strip():
        return None
    return SecretStr(raw.strip())


def get_ollama_base_url(env: Mapping[str, str] | None = None) -> str:
    """Retrieve Ollama base URL from environment or default to local."""
    source = env if env is not None else os.environ
    raw = source.get("HIRE_STEWARD_OLLAMA_BASE_URL")
    if raw is None or not raw.strip():
        return "http://127.0.0.1:11434"
    return raw.strip().rstrip("/")


def load_provider_credentials(env: Mapping[str, str] | None = None) -> ProviderCredentials:
    """Load all configured provider credentials from environment variables."""
    return ProviderCredentials(
        anthropic_api_key=get_anthropic_api_key(env),
        openai_api_key=get_openai_api_key(env),
        groq_api_key=get_groq_api_key(env),
        gemini_api_key=get_gemini_api_key(env),
        ollama_base_url=get_ollama_base_url(env),
    )
