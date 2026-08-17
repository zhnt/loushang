"""Session-scoped diagnostics over Product-bound transcript and extension ports.

The diagnostics service owns durable diagnostic records. This optional session
runtime adds common correlation and Agent/Tool fact projections while keeping
transcript identity and extension ownership in bound Product ports.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from loushang.agent.types import AgentToolResult
from loushang.ai.types import AssistantMessage
from loushang.foundation.json import require_json_value
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.diagnostics.types import (
    DiagnosticDraft,
    DiagnosticLevel,
    DiagnosticPhase,
    DiagnosticRecord,
    DiagnosticSource,
    DiagnosticsQuery,
    DiagnosticSummary,
    ErrorReport,
)
from loushang.harness.extensions.types import ResolvedCommand

_EXTENSION_ERROR_DIAGNOSTIC_CODES: frozenset[str] = frozenset(
    {
        "extension_runtime_bind_failed",
        "extension_resource_refresh_failed",
        "extension_session_start_failed",
        "extension_session_refresh_failed",
        "extension_resources_discover_failed",
    }
)


@dataclass(frozen=True)
class SessionDiagnosticScope:
    """Stable correlation values supplied by the bound Product session."""

    session_id: str
    entry_id: str | None = None


class ExtensionDiagnosticsPort(Protocol):
    """Minimal extension observation required for diagnostic syncing."""

    def get_diagnostics(self) -> Sequence[DiagnosticDraft]: ...


SessionDiagnosticScopeProvider = Callable[[], SessionDiagnosticScope]
ExtensionDiagnosticsProvider = Callable[[], ExtensionDiagnosticsPort | None]


@dataclass
class SessionDiagnosticsRuntime:
    """Record and query common session diagnostics without Product imports."""

    diagnostics_service: DiagnosticsService | None
    get_scope: SessionDiagnosticScopeProvider
    get_extension_diagnostics: ExtensionDiagnosticsProvider
    recorded_extension_diagnostics: int = 0

    def get_last_diagnostics(self, limit: int = 50) -> list[DiagnosticRecord]:
        if self.diagnostics_service is None:
            return []
        return self.diagnostics_service.get_last_diagnostics(limit=limit)

    def get_diagnostics(
        self, query: DiagnosticsQuery | None = None
    ) -> list[DiagnosticRecord]:
        if self.diagnostics_service is None:
            return []
        return self.diagnostics_service.get_diagnostics(query=query)

    def get_session_diagnostics(
        self, query: DiagnosticsQuery | None = None
    ) -> list[DiagnosticRecord]:
        if self.diagnostics_service is None:
            return []
        return self.diagnostics_service.get_diagnostics(
            query=_diagnostics_query_for_scope(query, self.get_scope())
        )

    def get_diagnostics_summary(
        self, query: DiagnosticsQuery | None = None
    ) -> DiagnosticSummary:
        service = self.diagnostics_service or DiagnosticsService()
        return service.get_diagnostics_summary(query=query)

    def get_session_diagnostics_summary(
        self, query: DiagnosticsQuery | None = None
    ) -> DiagnosticSummary:
        service = self.diagnostics_service or DiagnosticsService()
        return service.get_diagnostics_summary(
            query=_diagnostics_query_for_scope(query, self.get_scope())
        )

    def get_last_error_report(self) -> ErrorReport | None:
        if self.diagnostics_service is None:
            return None
        return self.diagnostics_service.get_last_error_report()

    def record_runtime_exception(self, *, code: str, exc: Exception | str) -> None:
        self.capture_failure(code=code, error=exc)

    def capture_failure(
        self,
        *,
        code: str,
        error: Exception | str,
        details: Mapping[str, object] | None = None,
        phase: DiagnosticPhase = "runtime",
        source: DiagnosticSource = "session",
    ) -> None:
        """Capture a session-scoped failure with optional structured details."""

        if self.diagnostics_service is None:
            return
        scope = self.get_scope()
        self.diagnostics_service.capture_failure(
            code=code,
            error=error,
            phase=phase,
            source=source,
            session_id=scope.session_id,
            entry_id=scope.entry_id,
            details=dict(details) if details is not None else None,
        )

    def record_extension_runtime_diagnostic(self, diagnostic: DiagnosticDraft) -> None:
        if self.diagnostics_service is None:
            return
        scope = self.get_scope()
        self.diagnostics_service.record(
            self.diagnostics_service.normalize_diagnostic(
                diagnostic,
                phase="runtime",
                source="extensions",
                session_id=scope.session_id,
                entry_id=scope.entry_id,
                level=_extension_diagnostic_level(diagnostic.code),
            )
        )

    def record_command_not_found(self, invocation_name: str, args: str) -> None:
        """Record a standard unresolved slash-command diagnostic."""

        if self.diagnostics_service is None:
            return
        scope = self.get_scope()
        self.diagnostics_service.capture_failure(
            code="command_not_found",
            error=f"Command not found: /{invocation_name}",
            phase="runtime",
            source="session",
            level="warning",
            session_id=scope.session_id,
            entry_id=scope.entry_id,
            details={"invocation_name": invocation_name, "args": args},
        )

    def record_preflight_diagnostics(
        self, diagnostics: Sequence[DiagnosticDraft]
    ) -> None:
        """Persist resource preflight diagnostics with the current session scope."""

        if self.diagnostics_service is None or not diagnostics:
            return
        scope = self.get_scope()
        self.diagnostics_service.record_many(
            self.diagnostics_service.normalize_diagnostic(
                diagnostic,
                phase="runtime",
                source="session",
                session_id=scope.session_id,
                entry_id=scope.entry_id,
            )
            for diagnostic in diagnostics
        )

    def record_extension_command_error(
        self, *, command: ResolvedCommand, exc: BaseException
    ) -> None:
        """Record a failed extension command without Product-specific shaping."""

        if self.diagnostics_service is None:
            return
        scope = self.get_scope()
        source_info = command.source_info
        self.diagnostics_service.capture_failure(
            code="extension_command_failed",
            error=exc if isinstance(exc, Exception) else str(exc),
            phase="runtime",
            source="extensions",
            session_id=scope.session_id,
            entry_id=scope.entry_id,
            source_path=source_info.path,
            details={
                "invocation_name": command.invocation_name,
                "command_name": command.name,
                "extension_name": command.extension_name,
                "source_info": {
                    "path": source_info.path.as_posix(),
                    "source": source_info.source,
                    "scope": source_info.scope,
                    "origin": source_info.origin,
                    "base_dir": source_info.base_dir.as_posix()
                    if source_info.base_dir is not None
                    else None,
                },
            },
        )

    def sync_extension_diagnostics(self, *, phase: DiagnosticPhase) -> None:
        if self.diagnostics_service is None:
            return
        extension_port = self.get_extension_diagnostics()
        if extension_port is None:
            return
        diagnostics = extension_port.get_diagnostics()
        if self.recorded_extension_diagnostics >= len(diagnostics):
            return
        scope = self.get_scope()
        new_diagnostics = diagnostics[self.recorded_extension_diagnostics :]
        self.diagnostics_service.record_many(
            self.diagnostics_service.normalize_diagnostic(
                diagnostic,
                phase=phase,
                source="extensions",
                session_id=scope.session_id,
                entry_id=scope.entry_id,
                level=_extension_diagnostic_level(diagnostic.code),
            )
            for diagnostic in new_diagnostics
        )
        self.recorded_extension_diagnostics = len(diagnostics)

    def record_assistant_response_error(
        self, assistant_message: AssistantMessage
    ) -> None:
        if self.diagnostics_service is None:
            return
        if (
            assistant_message.stop_reason != "error"
            or not assistant_message.error_message
        ):
            return
        scope = self.get_scope()
        details: dict[str, object] = {
            "provider": assistant_message.provider,
            "model_id": assistant_message.model,
            "api": assistant_message.api,
            "response_id": assistant_message.response_id,
            "stop_reason": assistant_message.stop_reason,
        }
        error_info = assistant_message.error_info
        if isinstance(error_info, Mapping):
            for source_key, target_key in (
                ("code", "error_code"),
                ("source", "error_source"),
                ("retryable", "retryable"),
                ("statusCode", "status_code"),
                ("requestId", "request_id"),
            ):
                value = error_info.get(source_key)
                if isinstance(value, str | int | bool):
                    details[target_key] = value
            typed_details = error_info.get("details")
            if isinstance(typed_details, Mapping):
                exception_type = typed_details.get("exceptionType")
                if isinstance(exception_type, str) and exception_type:
                    details["exception_type"] = exception_type
        self.diagnostics_service.capture_failure(
            code="assistant_response_error",
            error=assistant_message.error_message,
            phase="runtime",
            source="provider",
            session_id=scope.session_id,
            entry_id=scope.entry_id,
            details=details,
        )

    def record_tool_execution_error(self, event: Mapping[str, object]) -> None:
        if self.diagnostics_service is None:
            return
        tool_call_id = event.get("tool_call_id")
        tool_name = event.get("tool_name")
        if not isinstance(tool_call_id, str) or not isinstance(tool_name, str):
            return
        result = event.get("result")
        message = _tool_result_error_message(result)
        result_details = _tool_result_details(result)
        scope = self.get_scope()
        self.diagnostics_service.capture_failure(
            code="tool_execution_failed",
            error=message,
            phase="runtime",
            source="tool",
            session_id=scope.session_id,
            entry_id=scope.entry_id,
            details={
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "is_error": True,
                "result_details": result_details,
            },
        )
        if _is_policy_result_details(result_details):
            self.diagnostics_service.capture_failure(
                code=_policy_result_code(result_details),
                error=message,
                phase="runtime",
                source="policy",
                level="warning",
                session_id=scope.session_id,
                entry_id=scope.entry_id,
                details=_policy_diagnostic_details(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    result_details=result_details,
                ),
            )


def _extension_diagnostic_level(code: str) -> DiagnosticLevel:
    if code in _EXTENSION_ERROR_DIAGNOSTIC_CODES:
        return "error"
    return "warning"


def _diagnostics_query_for_scope(
    query: DiagnosticsQuery | None,
    scope: SessionDiagnosticScope,
) -> DiagnosticsQuery:
    if query is None:
        return DiagnosticsQuery(session_id=scope.session_id)
    return replace(query, session_id=scope.session_id)


def _tool_result_error_message(result: object) -> str:
    content = getattr(result, "content", None)
    if isinstance(content, list):
        texts = [
            part.text
            for part in content
            if getattr(part, "type", None) == "text"
            and isinstance(getattr(part, "text", None), str)
        ]
        if texts:
            return "\n".join(texts)
    return "Tool execution failed."


def _tool_result_details(result: object) -> Mapping[str, object]:
    if isinstance(result, AgentToolResult):
        try:
            details = result.event_details()
        except Exception:
            return {}
    else:
        try:
            details = require_json_value(
                getattr(result, "details", None),
                name="tool_diagnostic.details",
            )
        except TypeError:
            return {}
    return details if isinstance(details, Mapping) else {}


def _is_policy_result_details(details: object) -> bool:
    return isinstance(details, Mapping) and isinstance(
        details.get("policy_disposition"), str
    )


def _policy_result_code(result_details: Mapping[str, object]) -> str:
    code = result_details.get("policy_code")
    return code if isinstance(code, str) and code else "tool_policy_denied"


def _policy_diagnostic_details(
    *,
    tool_call_id: str,
    tool_name: str,
    result_details: Mapping[str, object],
) -> dict[str, object]:
    details: dict[str, object] = {}
    for key, value in result_details.items():
        if (
            isinstance(value, str | bool | int | float | list | tuple | dict)
            or value is None
        ):
            details[key] = value
    details["tool_call_id"] = tool_call_id
    details["tool_name"] = tool_name
    return details


__all__ = [
    "ExtensionDiagnosticsPort",
    "ExtensionDiagnosticsProvider",
    "SessionDiagnosticScope",
    "SessionDiagnosticScopeProvider",
    "SessionDiagnosticsRuntime",
]
