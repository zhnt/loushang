"""Shared CLI transcript export operation and result projection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

ExportFormat = Literal["html", "jsonl"]
ExportResultFormat = Literal["text", "json"]


class ExportOperationError(RuntimeError):
    """Raised when a transcript export cannot be completed."""


@dataclass(frozen=True, slots=True)
class ExportRequest:
    format: ExportFormat = "html"
    output: str | None = None


@dataclass(frozen=True, slots=True)
class ExportResult:
    path: object
    format: ExportFormat


def export_session(session: object, request: ExportRequest) -> ExportResult:
    method_name = (
        "export_to_jsonl" if request.format == "jsonl" else "export_to_html"
    )
    exporter = getattr(session, method_name, None)
    if not callable(exporter):
        raise ExportOperationError(
            f"{request.format} export is not available."
        )
    output = request.output if request.output != "" else None
    try:
        path = exporter(output)
    except Exception as error:
        raise ExportOperationError(str(error)) from error
    return ExportResult(path=path, format=request.format)


def format_export_result(
    result: ExportResult,
    output_format: ExportResultFormat,
) -> str:
    if output_format == "json":
        return (
            json.dumps(
                {"path": result.path, "format": result.format},
                ensure_ascii=False,
            )
            + "\n"
        )
    return f"Exported to: {result.path}\n"


__all__ = [
    "ExportFormat",
    "ExportOperationError",
    "ExportRequest",
    "ExportResult",
    "ExportResultFormat",
    "export_session",
    "format_export_result",
]
