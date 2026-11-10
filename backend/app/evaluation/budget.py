"""Pre-dispatch Budget Reservation and Cost Tracking (Task 8.2 Checkpoint B Stage B1).

Enforces:
1. Pre-dispatch budget reservation against worst-case token liabilities.
2. Hard ceiling enforcement: dispatches exceeding remaining budget are rejected pre-socket.
3. Model-specific pricing structures with token overhead accounting.
4. Post-response reconciliation adjusting active reservations to actual measured spend.
5. Strict handling of unresolved/ambiguous calls (timeouts and 5xx errors retain liability).
"""

from __future__ import annotations

import threading
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field


class BudgetExceededError(Exception):
    """Raised when an evaluation attempt exceeds the authorized budget cap."""

    pass


class ModelPricing(BaseModel):
    """Pricing rates and overheads for a specific model candidate."""

    model_config = ConfigDict(frozen=True)

    model_alias: str
    input_rate_per_million: float
    output_rate_per_million: float
    injected_overhead_tokens: int = 0


DEFAULT_PRICING_TABLE: dict[str, ModelPricing] = {
    "claude-sonnet-5-5": ModelPricing(
        model_alias="claude-sonnet-5-5",
        input_rate_per_million=2.00,
        output_rate_per_million=10.00,
        injected_overhead_tokens=300,  # Structured output schema overhead injected by Anthropic
    ),
    "gpt-6.1-sol": ModelPricing(
        model_alias="gpt-6.1-sol",
        input_rate_per_million=2.50,
        output_rate_per_million=10.00,
        injected_overhead_tokens=0,
    ),
}


class BudgetSummary(BaseModel):
    """Snapshot of budget tracker financial status."""

    model_config = ConfigDict(frozen=True)

    budget_cap_usd: float
    committed_spend_usd: float
    active_reservations_usd: float
    total_liability_usd: float
    remaining_budget_usd: float
    is_exhausted: bool


def estimate_call_cost(
    model_alias: str,
    estimated_input_tokens: int = 1800,
    max_output_tokens: int = 1000,
    pricing_table: Mapping[str, ModelPricing] | None = None,
) -> float:
    """Calculate worst-case dispatch cost for a model call."""
    table = pricing_table or DEFAULT_PRICING_TABLE
    pricing = table.get(model_alias)
    if pricing is None:
        # Conservative fallback pricing
        pricing = ModelPricing(
            model_alias=model_alias,
            input_rate_per_million=3.00,
            output_rate_per_million=15.00,
            injected_overhead_tokens=300,
        )

    effective_input_tokens = estimated_input_tokens + pricing.injected_overhead_tokens
    in_cost = (effective_input_tokens / 1_000_000.0) * pricing.input_rate_per_million
    out_cost = (max_output_tokens / 1_000_000.0) * pricing.output_rate_per_million
    return round(in_cost + out_cost, 6)


def calculate_actual_cost(
    model_alias: str,
    reported_input_tokens: int,
    reported_output_tokens: int,
    pricing_table: Mapping[str, ModelPricing] | None = None,
) -> float:
    """Calculate actual cost incurred from reported provider usage tokens."""
    table = pricing_table or DEFAULT_PRICING_TABLE
    pricing = table.get(model_alias)
    if pricing is None:
        pricing = ModelPricing(
            model_alias=model_alias,
            input_rate_per_million=3.00,
            output_rate_per_million=15.00,
            injected_overhead_tokens=0,
        )

    in_cost = (reported_input_tokens / 1_000_000.0) * pricing.input_rate_per_million
    out_cost = (reported_output_tokens / 1_000_000.0) * pricing.output_rate_per_million
    return round(in_cost + out_cost, 6)


class BudgetTracker:
    """Thread-safe budget reservation and expenditure tracker."""

    def __init__(
        self,
        budget_cap_usd: float = 5.0,
        pricing_table: Mapping[str, ModelPricing] | None = None,
    ) -> None:
        self.budget_cap_usd = float(budget_cap_usd)
        self.pricing_table = dict(pricing_table or DEFAULT_PRICING_TABLE)
        self._committed_spend_usd: float = 0.0
        self._active_reservations: dict[str, float] = {}
        self._lock = threading.Lock()

    def can_reserve(self, amount_usd: float) -> bool:
        """Check if an additional reservation fits within the budget cap."""
        with self._lock:
            total_active = sum(self._active_reservations.values())
            projected = self._committed_spend_usd + total_active + amount_usd
            return projected <= (self.budget_cap_usd + 1e-9)

    def reserve(self, reservation_id: str, amount_usd: float) -> float:
        """Reserve funds prior to dispatching an API call. Raises BudgetExceededError if limit breached."""
        with self._lock:
            if reservation_id in self._active_reservations:
                return self._active_reservations[reservation_id]

            total_active = sum(self._active_reservations.values())
            projected = self._committed_spend_usd + total_active + amount_usd
            if projected > (self.budget_cap_usd + 1e-9):
                remaining = max(0.0, self.budget_cap_usd - (self._committed_spend_usd + total_active))
                raise BudgetExceededError(
                    f"Budget cap exceeded. Required: ${amount_usd:.4f}, "
                    f"Remaining: ${remaining:.4f}, Cap: ${self.budget_cap_usd:.2f}"
                )

            self._active_reservations[reservation_id] = amount_usd
            return amount_usd

    def reconcile(self, reservation_id: str, actual_spend_usd: float) -> None:
        """Settle an active reservation with actual reported spend."""
        with self._lock:
            self._active_reservations.pop(reservation_id, None)
            self._committed_spend_usd += actual_spend_usd

    def record_unresolved_liability(self, reservation_id: str) -> None:
        """Handle timeouts and ambiguous failures: convert active reservation to committed liability."""
        with self._lock:
            reserved = self._active_reservations.pop(reservation_id, None)
            if reserved is not None:
                self._committed_spend_usd += reserved

    def release(self, reservation_id: str) -> None:
        """Release reservation without charging committed spend (e.g., pre-socket abort)."""
        with self._lock:
            self._active_reservations.pop(reservation_id, None)

    def get_summary(self) -> BudgetSummary:
        """Return snapshot summary of the budget tracker state."""
        with self._lock:
            total_active = sum(self._active_reservations.values())
            total_liability = self._committed_spend_usd + total_active
            remaining = max(0.0, self.budget_cap_usd - total_liability)
            return BudgetSummary(
                budget_cap_usd=self.budget_cap_usd,
                committed_spend_usd=round(self._committed_spend_usd, 6),
                active_reservations_usd=round(total_active, 6),
                total_liability_usd=round(total_liability, 6),
                remaining_budget_usd=round(remaining, 6),
                is_exhausted=remaining <= 1e-6,
            )
