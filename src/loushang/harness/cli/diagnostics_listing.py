"""Shared CLI diagnostics listing operation and projection."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from loushang.harness.diagnostics.serialization import serialize_diagnostic
from loushang.harness.diagnostics.types import DiagnosticRecord


class DiagnosticsListingError(RuntimeError):
    """Raised when a session cannot provide diagnostics for listing."""


@dataclass(frozen=True, slots=True)
class DiagnosticsListingRequest:
    limit: int = 50


def _serialize_diagnostic(record: object) -> Mapping[str, object]:
    return serialize_diagnostic(cast(DiagnosticRecord, record))


def list_diagnostic_records(
    session: object,
    request: DiagnosticsListingRequest,
    *,
    serializer: Callable[[object], Mapping[str, object]] = _serialize_diagnostic,
) -> list[dict[str, object]]:
    """Collect and safely serialize diagnostics from an injected session."""

    if request.limit <= 0:
        raise DiagnosticsListingError("diagnostics limit must be greater than zero.")
    getter = getattr(session, "get_last_diagnostics", None)
    if not callable(getter):
        raise DiagnosticsListingError("diagnostics are not available.")
    try:
        diagnostics = getter(limit=request.limit)
    except Exception as error:
        raise DiagnosticsListingError(str(error)) from error
    if not isinstance(diagnostics, list):
        raise DiagnosticsListingError("diagnostics returned an invalid response.")
    normalized: list[dict[str, object]] = []
    for record in diagnostics:
        try:
            normalized.append(dict(serializer(record)))
        except Exception:
            continue
    return normalized


def format_diagnostic_records(
    records: Sequence[Mapping[str, object]],
    output_format: str,
) -> str:
    if output_format == "json":
        return json.dumps(records, ensure_ascii=False) + "\n"
    return "".join(
        f"{record['type']}\t{record['phase']}\t{record['source']}\t"
        f"{record['code']}\t{record['occurrenceCount']}\t{record['message']}\n"
        for record in records
    )


__all__ = [
    "DiagnosticsListingError",
    "DiagnosticsListingRequest",
    "format_diagnostic_records",
    "list_diagnostic_records",
]
