"""Source-adapter contracts and protocols for job discovery."""

from collections.abc import Sequence
import json
from pathlib import Path
from typing import Any, Protocol

from backend.app.domain.job_posting import InvalidPostingPayloadError, NormalizedPosting


class JobSourceAdapter(Protocol):
    """Protocol defining the interface for a job board source adapter."""

    @property
    def source_name(self) -> str:
        """Machine-safe unique identifier for this source (e.g. 'lever')."""
        ...

    def fetch_page(
        self, employer_handle: str, skip: int, limit: int
    ) -> Sequence[Any] | None:
        """Fetch a single raw page of job postings for the employer handle.

        Returns None or empty sequence if no more pages are available.
        For offline or fixture adapters, this yields from synthetic fixture data.
        For live adapters without authorization, raises NotImplementedError.
        """
        ...

    def parse_posting_payload(
        self, employer_handle: str, payload: Any
    ) -> NormalizedPosting:
        """Parse and normalize a single raw posting JSON object."""
        ...

    def parse_listing_page(
        self, employer_handle: str, payload: Any, skip: int, limit: int
    ) -> list[NormalizedPosting]:
        """Parse and validate a page of job postings returned by the listing endpoint."""
        ...


class FixtureJobSourceAdapter:
    """Deterministic offline fixture adapter for job discovery testing and verification.

    Feeds pre-loaded or JSON-file fixture records through the standard adapter
    interface without making any HTTP requests or touching external job boards.

    Guarantees:
    - Strictly preserves source identity; delegate adapter source must match fixture adapter source.
    - Prohibits silent source relabeling or provenance spoofing.
    - Preserves delegate parser validation and payload bounds.
    - Robust pagination semantics handling different page limits, short/empty pages,
      nonzero offsets, and end-of-data.
    """

    def __init__(
        self,
        source_name: str,
        pages: Sequence[Any] | None = None,
        delegate_adapter: JobSourceAdapter | None = None,
        *,
        records: Sequence[Any] | None = None,
    ) -> None:
        if not source_name or not isinstance(source_name, str):
            raise ValueError("source_name must be a non-empty string")

        self._source_name = source_name
        self._delegate = delegate_adapter

        if delegate_adapter is not None:
            if delegate_adapter.source_name != source_name:
                raise ValueError(
                    f"Delegate adapter source '{delegate_adapter.source_name}' does not match "
                    f"fixture adapter source '{source_name}'. Silent source relabeling is prohibited."
                )

        if pages is not None and records is not None:
            raise ValueError("Specify either 'pages' or 'records', not both")

        self._pages: list[Any] | None = list(pages) if pages is not None else None
        self._records: list[Any] | None = list(records) if records is not None else None

        # Build flattened records for arbitrary offset slicing
        if self._records is not None:
            self._flat_records: list[Any] = self._records
        elif self._pages is not None:
            flat: list[Any] = []
            for p in self._pages:
                if isinstance(p, (list, tuple)):
                    flat.extend(p)
                else:
                    flat.append(p)
            self._flat_records = flat
        else:
            self._flat_records = []

    @property
    def source_name(self) -> str:
        return self._source_name

    def fetch_page(
        self, employer_handle: str, skip: int, limit: int
    ) -> Sequence[Any] | None:
        """Return the fixture page corresponding to skip and limit.

        Pagination semantics:
        - If skip < 0 or limit <= 0: returns None.
        - If skip >= total records: returns [].
        - Returns records sliced continuously from the record stream:
          records[skip : skip + limit].
        """
        if limit <= 0 or skip < 0:
            return None

        if skip >= len(self._flat_records):
            return []

        return self._flat_records[skip : skip + limit]

    def parse_posting_payload(
        self, employer_handle: str, payload: Any
    ) -> NormalizedPosting:
        if self._delegate is not None:
            posting = self._delegate.parse_posting_payload(employer_handle, payload)
            if posting.source != self._source_name:
                raise InvalidPostingPayloadError(
                    f"Parsed posting source '{posting.source}' does not match "
                    f"fixture adapter source '{self._source_name}'",
                    "SOURCE_MISMATCH",
                )
            return posting
        raise NotImplementedError("No delegate parser provided for parse_posting_payload")

    def parse_listing_page(
        self, employer_handle: str, payload: Any, skip: int, limit: int
    ) -> list[NormalizedPosting]:
        if self._delegate is not None:
            postings = self._delegate.parse_listing_page(
                employer_handle, payload, skip=skip, limit=limit
            )
            for posting in postings:
                if posting.source != self._source_name:
                    raise InvalidPostingPayloadError(
                        f"Parsed posting source '{posting.source}' does not match "
                        f"fixture adapter source '{self._source_name}'",
                        "SOURCE_MISMATCH",
                    )
            return postings
        raise NotImplementedError("No delegate parser provided for parse_listing_page")

    @classmethod
    def from_json_files(
        cls,
        source_name: str,
        file_paths: Sequence[str | Path],
        delegate_adapter: JobSourceAdapter | None = None,
    ) -> "FixtureJobSourceAdapter":
        """Load fixture pages from JSON files."""
        pages: list[Any] = []
        for path in file_paths:
            p = Path(path)
            if not p.exists():
                raise FileNotFoundError(f"Fixture file not found: {p}")
            with open(p, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError as err:
                    raise InvalidPostingPayloadError(
                        f"Failed to parse fixture file '{p}': {err}",
                        "INVALID_FIXTURE_JSON",
                    ) from err
                if not isinstance(data, list):
                    data = [data]
                pages.append(data)
        return cls(
            source_name=source_name,
            pages=pages,
            delegate_adapter=delegate_adapter,
        )
