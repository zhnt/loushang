"""Stable JSON projection for the shared diagnostics contract."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from loushang.harness.diagnostics.types import (
    DiagnosticRecord,
    DiagnosticSummary,
    ErrorReport,
)


def serialize_diagnostic(record: DiagnosticRecord) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": record.type,
        "code": record.code,
        "message": record.message,
        "phase": record.phase,
        "source": record.source,
        "timestamp": record.timestamp,
        "details": _json_safe(record.details),
        "occurrenceCount": record.occurrence_count,
    }
    if record.session_id is not None:
        payload["sessionId"] = record.session_id
    if record.entry_id is not None:
        payload["entryId"] = record.entry_id
    if record.source_path is not None:
        payload["sourcePath"] = str(record.source_path)
    if record.fingerprint is not None:
        payload["fingerprint"] = record.fingerprint
    tool_call_id = _tool_correlation_value(record.details, "tool_call_id", "toolCallId")
    if tool_call_id is not None:
        payload["toolCallId"] = tool_call_id
    tool_name = _tool_correlation_value(record.details, "tool_name", "toolName")
    if tool_name is not None:
        payload["toolName"] = tool_name
    return payload


def serialize_error_report(report: ErrorReport | None) -> dict[str, object] | None:
    if report is None:
        return None
    return {
        "primary": serialize_diagnostic(report.primary),
        "related": [serialize_diagnostic(record) for record in report.related],
    }


def serialize_diagnostic_summary(summary: DiagnosticSummary) -> dict[str, object]:
    return {
        "totalCount": summary.total_count,
        "errorCount": summary.error_count,
        "warningCount": summary.warning_count,
        "infoCount": summary.info_count,
        "byCode": dict(summary.by_code),
        "bySource": dict(summary.by_source),
        "byPhase": dict(summary.by_phase),
        "latestError": (
            serialize_diagnostic(summary.latest_error)
            if summary.latest_error is not None
            else None
        ),
    }


def _json_safe(value: Any) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    return repr(value)


def _tool_correlation_value(details: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = details.get(key)
        if isinstance(value, str) and value:
            return value
    return None


__all__ = [
    "serialize_diagnostic",
    "serialize_diagnostic_summary",
    "serialize_error_report",
]
