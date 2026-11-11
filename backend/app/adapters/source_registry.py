"""Job Source Adapter Registry.

Maps machine-safe source names to adapter factories.
Supports:
- lever: Lever public postings API
- greenhouse: Greenhouse public boards API
- ashby: Ashby public job-board API
"""

from __future__ import annotations

from typing import Any
import httpx

from backend.app.adapters.ashby import AshbyAdapter, ASHBY_SOURCE_NAME
from backend.app.adapters.greenhouse import GreenhouseAdapter, GREENHOUSE_SOURCE_NAME
from backend.app.adapters.job_sources import JobSourceAdapter
from backend.app.adapters.lever import LeverAdapter, LEVER_SOURCE_NAME
from backend.app.domain.job_posting import SourceNotApprovedError

_ADAPTER_FACTORIES: dict[str, Any] = {
    LEVER_SOURCE_NAME: LeverAdapter,
    GREENHOUSE_SOURCE_NAME: GreenhouseAdapter,
    ASHBY_SOURCE_NAME: AshbyAdapter,
}


def get_source_adapter(
    source_name: str,
    client: httpx.Client | None = None,
) -> JobSourceAdapter:
    """Retrieve an initialized JobSourceAdapter instance for the given source name."""
    factory = _ADAPTER_FACTORIES.get(source_name.lower().strip())
    if factory is None:
        supported = ", ".join(sorted(_ADAPTER_FACTORIES.keys()))
        raise SourceNotApprovedError(
            f"Unsupported or unapproved job source '{source_name}'. Supported sources: {supported}"
        )
    return factory(client=client)


def list_registered_sources() -> list[str]:
    """List all registered and supported source names."""
    return sorted(_ADAPTER_FACTORIES.keys())
