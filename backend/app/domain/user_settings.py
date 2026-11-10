"""Domain model and validation for user settings and search policies (Stage 3)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

VALID_WORKPLACE_ARRANGEMENTS = {"remote", "hybrid", "onsite"}
VALID_SPONSORSHIP_REQUIREMENTS = {"not_required", "required", "will_sponsor_only"}
VALID_AI_MODES = {"OFFLINE_MOCK", "ANTHROPIC", "OPENAI", "DISABLED"}


@dataclass
class UserSettings:
    target_roles: list[str] = field(default_factory=lambda: [
        "Software Engineer",
        "Staff Software Engineer",
        "Backend Architect",
        "AI/ML Engineer",
    ])
    target_locations: list[str] = field(default_factory=lambda: [
        "Remote",
        "Bengaluru",
        "India",
    ])
    workplace_arrangements: list[str] = field(default_factory=lambda: ["remote", "hybrid"])
    sponsorship_requirement: str = "not_required"
    same_company_cooldown_days: int = 30
    daily_application_cap: int = 5
    auto_tailor_resume: bool = True
    dry_run_simulation_mode: bool = True
    ai_provider_mode: str = "OFFLINE_MOCK"
    ai_budget_limit_usd: float = 5.0

    def validate(self) -> None:
        if self.same_company_cooldown_days < 0 or self.same_company_cooldown_days > 730:
            raise ValueError("same_company_cooldown_days must be between 0 and 730")
        if self.daily_application_cap < 1 or self.daily_application_cap > 100:
            raise ValueError("daily_application_cap must be between 1 and 100")
        if self.sponsorship_requirement not in VALID_SPONSORSHIP_REQUIREMENTS:
            raise ValueError(f"Invalid sponsorship_requirement. Must be one of: {sorted(VALID_SPONSORSHIP_REQUIREMENTS)}")
        if self.ai_provider_mode not in VALID_AI_MODES:
            raise ValueError(f"Invalid ai_provider_mode. Must be one of: {sorted(VALID_AI_MODES)}")
        if self.ai_budget_limit_usd < 0.0 or self.ai_budget_limit_usd > 1000.0:
            raise ValueError("ai_budget_limit_usd must be between 0.0 and 1000.0")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class UserSettingsError(Exception):
    """Raised when user settings cannot be reliably read or persisted."""

    def __init__(self, message: str, code: str = "SETTINGS_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.code = code

