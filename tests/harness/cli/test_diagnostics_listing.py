from __future__ import annotations

import pytest

from loushang.harness.cli import (
    DiagnosticsListingError,
    DiagnosticsListingRequest,
    format_diagnostic_records,
    list_diagnostic_records,
)


class _Session:
    def get_last_diagnostics(self, *, limit: int) -> list[dict[str, object]]:
        return [
            {
                "type": "error",
                "phase": "runtime",
                "source": "tool",
                "code": "failed",
                "occurrenceCount": limit,
                "message": "failed",
            }
        ]


def test_diagnostics_listing_uses_injected_serializer_and_formats_json() -> None:
    records = list_diagnostic_records(
        _Session(),
        DiagnosticsListingRequest(limit=3),
        serializer=lambda value: value,  # type: ignore[arg-type]
    )

    assert records[0]["occurrenceCount"] == 3
    assert '"code": "failed"' in format_diagnostic_records(records, "json")


def test_diagnostics_listing_rejects_invalid_limit() -> None:
    with pytest.raises(DiagnosticsListingError, match="greater than zero"):
        list_diagnostic_records(_Session(), DiagnosticsListingRequest(limit=0))
