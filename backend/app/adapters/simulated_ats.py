"""Simulated ATS Adapter for offline dry-run testing and failure rehearsals (Stage 6).

Guarantees:
1. Zero live outbound network traffic (pure local in-memory simulation).
2. Deterministic fault injection for reliability testing.
3. Realistic simulated ATS receipt generation for end-to-end dry-run verification.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

VALID_SIMULATION_MODES = {
    "SUCCESS",
    "PRE_SOCKET_ABORT",
    "POST_RECEIPT_ERROR",
    "TIMEOUT",
    "AMBIGUOUS_TIMEOUT",
    "DUPLICATE",
    "PORTAL_RATE_LIMIT",
}


@dataclass(frozen=True)
class SimulatedSubmissionResult:
    success: bool
    mode_used: str
    simulated_receipt_id: str | None
    error_code: str | None
    error_message: str | None
    duration_ms: int


class SimulatedAtsAdapter:
    """Local simulation adapter for ATS portals."""

    def __init__(self, default_mode: str = "SUCCESS") -> None:
        if default_mode not in VALID_SIMULATION_MODES:
            raise ValueError(f"Unknown simulation mode: {default_mode}")
        self.default_mode = default_mode

    def simulate_dispatch(
        self,
        submission_packet: dict[str, Any],
        mode: str | None = None,
    ) -> SimulatedSubmissionResult:
        """Simulate an ATS application submission packet dispatch."""
        active_mode = mode or self.default_mode
        if active_mode not in VALID_SIMULATION_MODES:
            raise ValueError(
                f"Invalid simulation mode '{active_mode}'. Valid modes: {sorted(VALID_SIMULATION_MODES)}"
            )

        start_time = time.monotonic()

        # Gate dispatch on policy eligibility
        if not submission_packet.get("is_compensation_eligible", False):
            return SimulatedSubmissionResult(
                success=False,
                mode_used=active_mode,
                simulated_receipt_id=None,
                error_code="INELIGIBLE_COMPENSATION",
                error_message="Submission blocked: job compensation policy is unverified or ineligible",
                duration_ms=1,
            )

        if not submission_packet.get("is_cooldown_clear", False):
            return SimulatedSubmissionResult(
                success=False,
                mode_used=active_mode,
                simulated_receipt_id=None,
                error_code="ACTIVE_COOLDOWN",
                error_message="Submission blocked: same employer cooldown is currently active",
                duration_ms=1,
            )

        if active_mode == "PRE_SOCKET_ABORT":
            return SimulatedSubmissionResult(
                success=False,
                mode_used=active_mode,
                simulated_receipt_id=None,
                error_code="CLIENT_SOCKET_ABORT",
                error_message="Simulated connection failure prior to TCP handshake",
                duration_ms=5,
            )

        if active_mode in ("TIMEOUT", "AMBIGUOUS_TIMEOUT"):
            return SimulatedSubmissionResult(
                success=False,
                mode_used=active_mode,
                simulated_receipt_id=None,
                error_code="GATEWAY_TIMEOUT",
                error_message="Simulated upstream ATS timeout (HTTP 504)",
                duration_ms=15,
            )

        if active_mode == "PORTAL_RATE_LIMIT":
            return SimulatedSubmissionResult(
                success=False,
                mode_used=active_mode,
                simulated_receipt_id=None,
                error_code="RATE_LIMIT_EXCEEDED",
                error_message="Simulated ATS rate limit reached (HTTP 429)",
                duration_ms=5,
            )

        if active_mode == "DUPLICATE":
            return SimulatedSubmissionResult(
                success=False,
                mode_used=active_mode,
                simulated_receipt_id=None,
                error_code="DUPLICATE_APPLICATION",
                error_message="Simulated duplicate application detected for this posting (HTTP 409)",
                duration_ms=10,
            )

        if active_mode == "POST_RECEIPT_ERROR":
            return SimulatedSubmissionResult(
                success=False,
                mode_used=active_mode,
                simulated_receipt_id=None,
                error_code="ATS_INTERNAL_SERVER_ERROR",
                error_message="Simulated unexpected server error during submission processing (HTTP 500)",
                duration_ms=20,
            )

        # Default SUCCESS path
        duration_ms = max(1, int((time.monotonic() - start_time) * 1000))
        receipt_id = f"sim_rec_{uuid.uuid4().hex[:16]}"
        return SimulatedSubmissionResult(
            success=True,
            mode_used=active_mode,
            simulated_receipt_id=receipt_id,
            error_code=None,
            error_message=None,
            duration_ms=duration_ms,
        )
