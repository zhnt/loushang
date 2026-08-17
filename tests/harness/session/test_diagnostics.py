from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from loushang.ai.types import AssistantMessage, TextPart, Usage
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.diagnostics.types import DiagnosticDraft, DiagnosticsQuery
from loushang.harness.extensions.types import ResolvedCommand
from loushang.harness.resources.source import SourceInfo
from loushang.harness.session import (
    SessionDiagnosticScope,
    SessionDiagnosticsRuntime,
)


@dataclass
class _ExtensionDiagnostics:
    diagnostics: list[DiagnosticDraft] = field(default_factory=list)

    def get_diagnostics(self) -> list[DiagnosticDraft]:
        return list(self.diagnostics)


async def _async_handler(_args: str, _context: object) -> None:
    return None


def _source_info(path: str) -> SourceInfo[Path]:
    source_path = Path(path)
    return SourceInfo(path=source_path, base_dir=source_path.parent)


def _runtime(
    diagnostics: DiagnosticsService,
    extension: _ExtensionDiagnostics | None = None,
    *,
    recorded_extension_diagnostics: int = 0,
) -> SessionDiagnosticsRuntime:
    return SessionDiagnosticsRuntime(
        diagnostics_service=diagnostics,
        get_scope=lambda: SessionDiagnosticScope("session-1", "entry-1"),
        get_extension_diagnostics=lambda: extension,
        recorded_extension_diagnostics=recorded_extension_diagnostics,
    )


def test_session_diagnostics_scopes_queries_and_syncs_extensions_once() -> None:
    diagnostics = DiagnosticsService()
    extension = _ExtensionDiagnostics(
        diagnostics=[
            DiagnosticDraft(code="already_seen", message="old"),
            DiagnosticDraft(
                code="extension_session_refresh_failed",
                message="refresh failed",
                source_path=Path("/tmp/extensions/demo.py"),
            ),
        ]
    )
    runtime = _runtime(diagnostics, extension, recorded_extension_diagnostics=1)
    diagnostics.capture_failure(
        code="current_session_error",
        error="boom",
        phase="runtime",
        source="session",
        session_id="session-1",
    )
    diagnostics.capture_failure(
        code="other_session_error",
        error="other",
        phase="runtime",
        source="session",
        session_id="other-session",
    )

    runtime.sync_extension_diagnostics(phase="runtime")
    runtime.sync_extension_diagnostics(phase="runtime")

    records = runtime.get_session_diagnostics()
    assert [record.code for record in records] == [
        "current_session_error",
        "extension_session_refresh_failed",
    ]
    assert runtime.get_session_diagnostics(
        DiagnosticsQuery(code="current_session_error")
    ) == [records[0]]
    assert runtime.get_session_diagnostics_summary().total_count == 2
    assert records[1].type == "error"
    assert records[1].source == "extensions"
    assert records[1].entry_id == "entry-1"


def test_session_diagnostics_records_agent_and_policy_tool_failures() -> None:
    diagnostics = DiagnosticsService()
    runtime = _runtime(diagnostics)
    assistant_message = AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[],
        api="responses",
        provider="demo",
        model="demo-model",
        response_id="resp_1",
        usage=Usage(
            input=0,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=0,
            cost={},
        ),
        stop_reason="error",
        error_message="provider failed",
        timestamp=0.0,
        error_info={
            "code": "rate_limit",
            "message": "Provider rate limit exceeded.",
            "source": "responses",
            "retryable": True,
            "provider": "demo",
            "endpoint": "test-endpoint",
            "model": "demo-model",
            "statusCode": 429,
            "requestId": "req_123",
            "details": {"exceptionType": "HTTPStatusError"},
        },
    )

    runtime.record_runtime_exception(code="runtime_failed", exc="runtime boom")
    runtime.record_assistant_response_error(assistant_message)
    runtime.record_tool_execution_error(
        {
            "tool_call_id": "tc-policy-1",
            "tool_name": "write",
            "result": SimpleNamespace(
                content=[TextPart(type="text", text="Tool write is blocked by policy")],
                details={
                    "policy_disposition": "deny",
                    "policy_code": "tool_blocked",
                    "policy_reason": "Tool write is blocked by policy",
                    "path": "/tmp/project/blocked.txt",
                },
            ),
        }
    )

    records = diagnostics.get_diagnostics()
    assert [record.code for record in records] == [
        "runtime_failed",
        "assistant_response_error",
        "tool_execution_failed",
        "tool_blocked",
    ]
    assert {record.session_id for record in records} == {"session-1"}
    assert records[1].details["response_id"] == "resp_1"
    assert records[1].details["error_code"] == "rate_limit"
    assert records[1].details["status_code"] == 429
    assert records[1].details["request_id"] == "req_123"
    assert records[1].details["exception_type"] == "HTTPStatusError"
    assert records[2].details["tool_call_id"] == "tc-policy-1"
    assert records[3].type == "warning"
    assert records[3].details["path"] == "/tmp/project/blocked.txt"


def test_session_diagnostics_records_standard_command_failures() -> None:
    diagnostics = DiagnosticsService()
    runtime = _runtime(diagnostics)
    command = ResolvedCommand(
        name="deploy",
        handler=_async_handler,
        invocation_name="deploy",
        extension_name="deploy-ext",
        source_info=_source_info("/tmp/project/extensions/deploy.py"),
    )

    runtime.record_command_not_found("missing", "args")
    runtime.record_preflight_diagnostics(
        (DiagnosticDraft(code="unresolved_prompt_reference", message="missing"),)
    )
    runtime.record_extension_command_error(command=command, exc=RuntimeError("boom"))

    records = diagnostics.get_diagnostics()
    assert [record.code for record in records] == [
        "command_not_found",
        "unresolved_prompt_reference",
        "extension_command_failed",
    ]
    assert {record.session_id for record in records} == {"session-1"}
    assert records[0].type == "warning"
    assert records[2].source == "extensions"
    assert records[2].source_path == Path("/tmp/project/extensions/deploy.py")
    assert records[2].details["extension_name"] == "deploy-ext"


def test_session_diagnostics_uses_tool_event_projection_and_rejects_unsafe_details() -> (
    None
):
    from loushang.agent import AgentToolResult, FunctionalToolOutputProjector

    diagnostics = DiagnosticsService()
    runtime = _runtime(diagnostics)
    raw_details = object()
    projected = AgentToolResult(
        content=[TextPart(type="text", text="tool failed")],
        details=raw_details,
        projector=FunctionalToolOutputProjector(
            transcript=lambda details: {"surface": "transcript"},
            event=lambda details: {
                "surface": "event",
                "policy_disposition": "deny",
                "policy_code": "tool_blocked",
            },
        ),
    )
    runtime.record_tool_execution_error(
        {"tool_call_id": "tc-rich", "tool_name": "write", "result": projected}
    )
    runtime.record_tool_execution_error(
        {
            "tool_call_id": "tc-unsafe",
            "tool_name": "legacy",
            "result": SimpleNamespace(
                content=[TextPart(type="text", text="tool failed")],
                details={"path": Path("notes.txt")},
            ),
        }
    )

    records = diagnostics.get_diagnostics()
    assert records[0].details["result_details"] == {
        "surface": "event",
        "policy_disposition": "deny",
        "policy_code": "tool_blocked",
    }
    assert records[1].details["surface"] == "event"
    assert repr(raw_details) not in repr(records[0].details)
    assert records[2].details["result_details"] == {}
    assert "notes.txt" not in repr(records[2].details)
