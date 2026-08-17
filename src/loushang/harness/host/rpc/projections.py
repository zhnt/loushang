"""Injected Product projections used by the product-neutral RPC runtime."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from loushang.harness.diagnostics.serialization import (
    serialize_diagnostic,
    serialize_diagnostic_summary,
    serialize_error_report,
)
from loushang.harness.diagnostics.types import (
    DiagnosticRecord,
    DiagnosticSummary,
    ErrorReport,
)
from loushang.harness.events import RuntimeEventView, normalize_event_select
from loushang.harness.session import (
    SUPPORTED_JSON_EVENT_VIEWS,
    project_runtime_event_to_json_views,
    project_session_event,
    shape_runtime_event_view,
    shape_stream_event,
    should_emit_projected_event,
    should_emit_runtime_event_view,
)

RuntimeEventViewT = TypeVar("RuntimeEventViewT")
DiagnosticRecordT = TypeVar("DiagnosticRecordT")
DiagnosticSummaryT = TypeVar("DiagnosticSummaryT")
ErrorReportT = TypeVar("ErrorReportT")


@dataclass(frozen=True)
class RpcEventProjection(Generic[RuntimeEventViewT]):
    """Product-injected event projection for the shared RPC host."""

    supported_views: Sequence[str]
    normalize_select: Callable[[str | Sequence[str] | None], Sequence[str]]
    project_session_event: Callable[..., Sequence[dict[str, Any]]]
    should_emit_projected_event: Callable[[dict[str, Any], Sequence[str]], bool]
    shape_stream_event: Callable[..., dict[str, Any]]
    project_runtime_event_to_json_views: Callable[..., Sequence[RuntimeEventViewT]]
    should_emit_runtime_event_view: Callable[[RuntimeEventViewT, Sequence[str]], bool]
    shape_runtime_event_view: Callable[[RuntimeEventViewT], dict[str, Any]]


@dataclass(frozen=True)
class RpcDiagnosticsProjection(
    Generic[DiagnosticRecordT, DiagnosticSummaryT, ErrorReportT]
):
    """Product-injected diagnostics wire projection."""

    serialize_diagnostic: Callable[[DiagnosticRecordT], dict[str, object]]
    serialize_diagnostic_summary: Callable[[DiagnosticSummaryT], dict[str, object]]
    serialize_error_report: Callable[[ErrorReportT], dict[str, object] | None]


STANDARD_AGENT_RPC_EVENT_PROJECTION: RpcEventProjection[RuntimeEventView] = (
    RpcEventProjection(
        supported_views=SUPPORTED_JSON_EVENT_VIEWS,
        normalize_select=normalize_event_select,
        project_session_event=project_session_event,
        should_emit_projected_event=should_emit_projected_event,
        shape_stream_event=shape_stream_event,
        project_runtime_event_to_json_views=project_runtime_event_to_json_views,
        should_emit_runtime_event_view=should_emit_runtime_event_view,
        shape_runtime_event_view=shape_runtime_event_view,
    )
)

STANDARD_RPC_DIAGNOSTICS_PROJECTION: RpcDiagnosticsProjection[
    DiagnosticRecord, DiagnosticSummary, ErrorReport | None
] = RpcDiagnosticsProjection(
    serialize_diagnostic=serialize_diagnostic,
    serialize_diagnostic_summary=serialize_diagnostic_summary,
    serialize_error_report=serialize_error_report,
)


__all__ = [
    "RpcDiagnosticsProjection",
    "RpcEventProjection",
    "STANDARD_AGENT_RPC_EVENT_PROJECTION",
    "STANDARD_RPC_DIAGNOSTICS_PROJECTION",
]
