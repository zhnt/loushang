from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from loushang.agent.types import AgentToolResult
from loushang.coding.tools import (
    ToolDefinitionResolver,
    ToolRenderRuntime,
    render_tool_result_presentation,
)
from loushang.coding.tools.output_preview import (
    collapse_tool_output_preview,
    drop_tool_timing_tail_line,
    prefers_tail_tool_output,
)
from loushang.tui.render import diff_stat

ToolTranscriptStatus = Literal["running", "ok", "error", "cancelled", "timed_out", "terminate"]


@dataclass(frozen=True)
class ToolCallSnapshot:
    tool_name: str
    args: object | None = None
    rendered_call_text: str | None = None


@dataclass(frozen=True)
class ToolTranscriptBlock:
    tool_call_id: str
    tool_name: str
    status: ToolTranscriptStatus
    verb: str
    title: str
    detail: str | None = None
    body: str | None = None


@dataclass
class ToolTranscriptProjector:
    tool_definition_resolver: ToolDefinitionResolver | None = None
    render_runtime: ToolRenderRuntime | None = None
    max_body_lines: int = 8

    def __post_init__(self) -> None:
        if self.render_runtime is None:
            self.render_runtime = ToolRenderRuntime()

    def remember_call(self, event: Mapping[str, Any]) -> ToolCallSnapshot:
        tool_name = _tool_name(event)
        rendered = self._render_event_text(event, expanded=False)
        return ToolCallSnapshot(tool_name=tool_name, args=event.get("args"), rendered_call_text=rendered)

    def project_result(self, event: Mapping[str, Any], snapshot: ToolCallSnapshot | None = None) -> ToolTranscriptBlock:
        tool_call_id = _tool_call_id(event)
        tool_name = snapshot.tool_name if snapshot is not None else _tool_name(event)
        args = snapshot.args if snapshot is not None else event.get("args")
        status = _result_status(event)
        rendered_call = snapshot.rendered_call_text if snapshot is not None else None
        title = _title(tool_name, args, rendered_call)
        detail = _detail(event, tool_name=tool_name, status=status)
        rendered_result = self._render_event_text(event, expanded=False)
        body = _body(
            tool_name,
            event,
            status=status,
            rendered_result=rendered_result,
            max_lines=self.max_body_lines,
        )
        return ToolTranscriptBlock(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            status=status,
            verb=_verb(tool_name, args),
            title=title,
            detail=detail,
            body=body,
        )

    def project_tool_result_message(self, message: object) -> ToolTranscriptBlock:
        tool_name = str(getattr(message, "tool_name", "tool"))
        tool_call_id = str(getattr(message, "tool_call_id", tool_name))
        event = {
            "type": "tool_execution_end",
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "result": AgentToolResult(
                content=getattr(message, "content", None) or [],
                details=getattr(message, "details", None),
                terminate=bool(getattr(message, "terminate", False)),
            ),
            "is_error": bool(getattr(message, "is_error", False)),
        }
        return self.project_result(event)

    def _render_event_text(self, event: Mapping[str, Any], *, expanded: bool) -> str | None:
        if self.tool_definition_resolver is None or self.render_runtime is None:
            return None
        try:
            rendered = self.render_runtime.render_event(
                event,
                self.tool_definition_resolver,
                expanded=expanded,
            )
        except Exception:
            return None
        return _rendered_text(rendered)


def _tool_call_id(event: Mapping[str, Any]) -> str:
    value = event.get("tool_call_id", event.get("toolCallId"))
    if isinstance(value, str) and value:
        return value
    return _tool_name(event) or "tool"


def _tool_name(event: Mapping[str, Any]) -> str:
    value = event.get("tool_name", event.get("toolName"))
    return value if isinstance(value, str) and value else "tool"


def _rendered_text(rendered: object) -> str | None:
    if isinstance(rendered, str):
        return rendered
    if isinstance(rendered, Mapping):
        plain = rendered.get("plainText")
        if isinstance(plain, str):
            return plain
        text = rendered.get("text")
        if isinstance(text, str):
            return text
    return None


def _title(tool_name: str, args: object | None, rendered_call: str | None) -> str:
    if rendered_call:
        first_line = rendered_call.splitlines()[0].strip()
        if first_line.startswith("$ "):
            return f"{tool_name} {first_line[2:].strip()}"
        if first_line:
            return first_line
    detail = _arg_detail(args)
    return f"{tool_name} {detail}" if detail else tool_name


def _arg_detail(args: object | None) -> str | None:
    if isinstance(args, Mapping):
        for key in ("path", "file_path", "pattern", "query", "command"):
            value = args.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _verb(tool_name: str, args: object | None) -> str:
    normalized = tool_name.lower()
    command = _command_from_args(args).lower()
    if any(part in normalized for part in ("read", "grep", "glob", "list", "ls", "search")):
        return "Explored"
    if any(part in normalized for part in ("edit", "write", "patch")):
        return "Edited"
    if any(part in normalized for part in ("test", "lint", "ruff", "pytest")):
        return "Tested"
    if any(part in command for part in ("pytest", "ruff", "mypy", "lint", "test ")):
        return "Tested"
    if any(part in normalized for part in ("bash", "shell", "exec", "run")):
        return "Ran"
    return f"Used {tool_name}"


def _command_from_args(args: object | None) -> str:
    if isinstance(args, Mapping):
        command = args.get("command")
        if isinstance(command, str):
            return command
    return ""


def _result_status(event: Mapping[str, Any]) -> ToolTranscriptStatus:
    result = event.get("partial_result") if event.get("type") == "tool_execution_update" else event.get("result")
    if isinstance(result, AgentToolResult) and isinstance(result.details, Mapping):
        if result.details.get("timed_out") is True or result.details.get("timedOut") is True:
            return "timed_out"
        if result.details.get("cancelled") is True or result.details.get("canceled") is True:
            return "cancelled"
    if bool(event.get("is_error", False)):
        return "error"
    if isinstance(result, AgentToolResult) and result.terminate:
        return "terminate"
    return "ok"


def _detail(event: Mapping[str, Any], *, tool_name: str, status: ToolTranscriptStatus) -> str | None:
    if status == "ok":
        return _ok_detail(event, tool_name=tool_name)
    if status == "error":
        reason = _tool_error_summary(event.get("result"))
        return f"failed: {reason}" if reason else "failed"
    if status == "timed_out":
        return "timed out"
    if status == "cancelled":
        return "cancelled"
    if status == "terminate":
        return "terminated"
    return None


def _ok_detail(event: Mapping[str, Any], *, tool_name: str) -> str | None:
    result = event.get("partial_result") if event.get("type") == "tool_execution_update" else event.get("result")
    details = getattr(result, "details", None)
    if not isinstance(details, Mapping):
        return None
    normalized = tool_name.lower()
    if any(part in normalized for part in ("edit", "patch")):
        return diff_stat(details.get("diff"))
    if "write" in normalized:
        return _write_stat(details)
    return None


def _write_stat(details: Mapping[str, Any]) -> str | None:
    parts: list[str] = []
    operation = details.get("operation")
    if isinstance(operation, str) and operation:
        parts.append(_write_operation_label(operation))
    bytes_written = details.get("bytes_written", details.get("bytesWritten"))
    formatted_size = _format_byte_count(bytes_written)
    if formatted_size:
        parts.append(formatted_size)
    return ", ".join(parts) if parts else None


def _write_operation_label(operation: str) -> str:
    normalized = operation.lower()
    if normalized == "create":
        return "created"
    if normalized == "overwrite":
        return "overwrote"
    return normalized.replace("_", " ")


def _format_byte_count(value: object) -> str | None:
    if not isinstance(value, int) or value < 0:
        return None
    if value < 1024:
        return f"{value} B"
    units = ("KiB", "MiB", "GiB")
    amount = float(value)
    for unit in units:
        amount /= 1024
        if amount < 1024:
            return f"{amount:.1f} {unit}"
    return f"{amount:.1f} TiB"


def _body(
    tool_name: str,
    event: Mapping[str, Any],
    *,
    status: ToolTranscriptStatus,
    rendered_result: str | None,
    max_lines: int,
) -> str | None:
    if max_lines < 1:
        return None
    if not _should_show_body(tool_name, status):
        return None
    text = rendered_result or _fallback_result_text(event, max_lines=max_lines)
    if not text:
        return None
    text = drop_tool_timing_tail_line(text.strip())
    if not text:
        return None
    return collapse_tool_output_preview(
        text,
        max_lines=max_lines,
        tail=prefers_tail_tool_output(tool_name),
    )


def _should_show_body(tool_name: str, status: ToolTranscriptStatus) -> bool:
    if status != "ok":
        return False
    normalized = tool_name.lower()
    return any(part in normalized for part in ("bash", "shell", "exec", "run", "grep", "find", "ls", "test", "lint", "ruff", "pytest"))


def _fallback_result_text(event: Mapping[str, Any], *, max_lines: int) -> str:
    result = event.get("partial_result") if event.get("type") == "tool_execution_update" else event.get("result")
    if not isinstance(result, AgentToolResult):
        return ""
    return render_tool_result_presentation(
        result.content,
        result.details,
        max_collapsed_lines=max_lines,
    ).collapsed


def _tool_error_summary(result: object) -> str | None:
    content = getattr(result, "content", None)
    if not isinstance(content, list):
        return None
    for part in content:
        text = getattr(part, "text", None)
        if not isinstance(text, str):
            continue
        for line in text.splitlines():
            summary = line.strip()
            if summary:
                return summary if len(summary) <= 160 else summary[:157] + "..."
    return None


__all__ = [
    "ToolCallSnapshot",
    "ToolTranscriptBlock",
    "ToolTranscriptProjector",
    "ToolTranscriptStatus",
]
