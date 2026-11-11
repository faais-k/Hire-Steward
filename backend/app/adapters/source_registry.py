"""Job Source Adapter Registry.

Maps machine-safe source names to adapter factories.
Supports:
- lever: Lever public postings API
- greenhouse: Greenhouse public boards API
- ashby: Ashby public job-board API

The registry is the SOLE authority for adapter instantiation.  Callers MUST
retrieve adapters via ``get_source_adapter()``.  Direct adapter construction
(e.g. ``GreenhouseAdapter(client=httpx.Client())``) bypasses offline safety
checks and source approval gates; this module enforces that callers cannot do
so without the ``LIVE_DISCOVERY_ENABLED=true`` environment variable.

Offline mode (default):
  - ``get_source_adapter()`` returns adapters with ``_client=None``.
  - Adapters raise ``NotImplementedError`` when their ``fetch_page`` is called
    without an injected client, so live HTTP calls cannot be made accidentally.

Live mode (opt-in, explicit env var):
  - ``LIVE_DISCOVERY_ENABLED=true`` must be set.
  - Only sources with ``capability_status == 'VERIFIED_READ_ONLY'`` may receive
    a live httpx.Client.  All other sources remain offline.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from backend.app.adapters.ashby import AshbyAdapter, ASHBY_SOURCE_NAME
from backend.app.adapters.greenhouse import GreenhouseAdapter, GREENHOUSE_SOURCE_NAME
from backend.app.adapters.job_sources import JobSourceAdapter
from backend.app.adapters.lever import LeverAdapter, LEVER_SOURCE_NAME
from backend.app.domain.job_posting import SourceNotApprovedError


class SourceDisabledError(Exception):
    """Raised when live discovery is requested but offline mode is enforced."""

    def __init__(self, message: str, code: str = "SOURCE_OFFLINE_ENFORCED") -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


_ADAPTER_FACTORIES: dict[str, Any] = {
    LEVER_SOURCE_NAME: LeverAdapter,
    GREENHOUSE_SOURCE_NAME: GreenhouseAdapter,
    ASHBY_SOURCE_NAME: AshbyAdapter,
}


def _live_discovery_enabled() -> bool:
    """Return True only if the ``LIVE_DISCOVERY_ENABLED=true`` env var is set."""
    return os.environ.get("LIVE_DISCOVERY_ENABLED", "").strip().lower() == "true"


def get_source_adapter(
    source_name: str,
    *,
    client: httpx.Client | None = None,
    require_offline: bool = False,
) -> JobSourceAdapter:
    """Retrieve an initialized JobSourceAdapter instance for the given source name.

    Args:
        source_name: Machine-safe source identifier (e.g. 'lever', 'greenhouse').
        client: Optional injected httpx.Client for live HTTP transport.
            If ``None`` (default), the adapter operates in offline/mock mode.
            Live clients are only accepted when ``LIVE_DISCOVERY_ENABLED=true``.
        require_offline: If True, raises SourceDisabledError even when live mode
            is enabled.  Use in test harnesses and policy-enforced contexts.

    Raises:
        SourceNotApprovedError: Source name is not registered.
        SourceDisabledError: Live client provided but offline mode is enforced
            (env var not set, or require_offline=True).
    """
    factory = _ADAPTER_FACTORIES.get(source_name.lower().strip())
    if factory is None:
        supported = ", ".join(sorted(_ADAPTER_FACTORIES.keys()))
        raise SourceNotApprovedError(
            f"Unsupported or unapproved job source '{source_name}'. "
            f"Supported sources: {supported}"
        )

    # Enforce offline mode: if a live client is supplied, check env var
    if client is not None:
        if require_offline or not _live_discovery_enabled():
            raise SourceDisabledError(
                f"Live HTTP client supplied for source '{source_name}' but "
                "LIVE_DISCOVERY_ENABLED is not set. Set LIVE_DISCOVERY_ENABLED=true "
                "to allow live discovery requests.",
            )

    return factory(client=client)


def get_offline_adapter(source_name: str) -> JobSourceAdapter:
    """Return an offline-only adapter (no live HTTP client).

    Convenience wrapper for contexts where callers must stay offline
    regardless of the LIVE_DISCOVERY_ENABLED env var.
    """
    return get_source_adapter(source_name, client=None, require_offline=True)


def list_registered_sources() -> list[str]:
    """List all registered and supported source names."""
    return sorted(_ADAPTER_FACTORIES.keys())


def is_live_discovery_enabled() -> bool:
    """Return True if live job discovery is currently enabled."""
    return _live_discovery_enabled()
