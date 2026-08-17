from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, TypeVar

from loushang.harness.tools.workspace.output_preview import (
    collapse_tool_output_preview,
    drop_tool_timing_tail_line,
    prefers_tail_tool_output,
)
from loushang.tui.render import diff_stat
from loushang.tui.transcript import ToolExecutionRecord, ToolOutputKind, ToolState

ToolTranscriptStatus = Literal[
    "running", "ok", "error", "cancelled", "timed_out", "terminate"
]
ToolVerbResolver = Callable[[str, object | None], str]
ToolBodyVisibility = Callable[[str, ToolTranscriptStatus], bool]
ToolCommandResolver = Callable[[str, object | None, str], str | None]
ToolEventRenderer = Callable[[Mapping[str, Any], bool], str | None]
ToolResultTextProjector = Callable[[object, int], str]
ToolResultDetailsProjector = Callable[[object], Mapping[str, Any]]
ToolResultTerminationPredicate = Callable[[object], bool]
ToolErrorSummaryProjector = Callable[[object], str | None]
ToolResultMessageEventProjector = Callable[[object], Mapping[str, Any]]
ToolTranscriptEventT = TypeVar("ToolTranscriptEventT")
ToolTranscriptMessageT = TypeVar("ToolTranscriptMessageT")

_EXIT_CODE_RE = re.compile(r"\bexit code\s+(\d+)\b", re.IGNORECASE)


def _default_verb(tool_name: str, args: object | None) -> str:
    del args
    return f"Used {tool_name}"


def _hide_body(tool_name: str, status: ToolTranscriptStatus) -> bool:
    del tool_name, status
    return False


def _hide_command(tool_name: str, args: object | None, title: str) -> str | None:
    del tool_name, args, title
    return None


@dataclass(frozen=True)
class ToolCallView:
    """Product-neutral input for one tool call shown in a conversation."""

    tool_call_id: str
    tool_name: str
    args: object | None = None
    rendered_text: str | None = None


@dataclass(frozen=True)
class ToolResultView:
    """Product-neutral input for one tool result shown in a conversation."""

    tool_call_id: str
    tool_name: str
    status: ToolTranscriptStatus
    args: object | None = None
    result_text: str = ""
    rendered_text: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)
    error_summary: str | None = None


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
    command: str | None = None


@dataclass
class ToolTranscriptProjector:
    """Project neutral tool call/result views into reusable transcript blocks."""

    verb_resolver: ToolVerbResolver = _default_verb
    body_visibility: ToolBodyVisibility = _hide_body
    command_resolver: ToolCommandResolver = _hide_command
    max_body_lines: int = 8

    def remember_call(self, view: ToolCallView) -> ToolCallSnapshot:
        return ToolCallSnapshot(
            tool_name=view.tool_name,
            args=view.args,
            rendered_call_text=view.rendered_text,
        )

    def project_result(
        self,
        view: ToolResultView,
        snapshot: ToolCallSnapshot | None = None,
    ) -> ToolTranscriptBlock:
        tool_name = snapshot.tool_name if snapshot is not None else view.tool_name
        args = snapshot.args if snapshot is not None else view.args
        rendered_call = snapshot.rendered_call_text if snapshot is not None else None
        title = _title(tool_name, args, rendered_call)
        return ToolTranscriptBlock(
            tool_call_id=view.tool_call_id,
            tool_name=tool_name,
            status=view.status,
            verb=self.verb_resolver(tool_name, args),
            title=title,
            detail=_detail(view, tool_name=tool_name),
            body=_body(
                tool_name,
                view,
                visible=self.body_visibility(tool_name, view.status),
                max_lines=self.max_body_lines,
            ),
            command=self.command_resolver(tool_name, args, title),
        )


class ToolTranscriptProjectionBinding(
    Generic[ToolTranscriptEventT, ToolTranscriptMessageT]
):
    """Compose product raw-view adapters with the neutral tool projector."""

    __slots__ = (
        "_call_id",
        "_call_view",
        "_message_id",
        "_result_view",
        "_tool_result_message_view",
        "neutral_projector",
    )

    def __init__(
        self,
        *,
        neutral_projector: ToolTranscriptProjector,
        call_id: Callable[[ToolTranscriptEventT], str],
        message_id: Callable[[ToolTranscriptMessageT], str],
        call_view: Callable[[ToolTranscriptEventT], ToolCallView],
        result_view: Callable[
            [ToolTranscriptEventT, ToolCallSnapshot | None, str | None],
            ToolResultView,
        ],
        tool_result_message_view: Callable[
            [ToolTranscriptMessageT], ToolResultView
        ],
    ) -> None:
        self.neutral_projector = neutral_projector
        self._call_id = call_id
        self._message_id = message_id
        self._call_view = call_view
        self._result_view = result_view
        self._tool_result_message_view = tool_result_message_view

    def call_id(self, event: ToolTranscriptEventT) -> str:
        return self._call_id(event)

    def message_id(self, message: ToolTranscriptMessageT) -> str:
        return self._message_id(message)

    def call_view(self, event: ToolTranscriptEventT) -> ToolCallView:
        return self._call_view(event)

    def remember_call(self, event: ToolTranscriptEventT) -> ToolCallSnapshot:
        return self.neutral_projector.remember_call(self.call_view(event))

    def result_view(
        self,
        event: ToolTranscriptEventT,
        snapshot: ToolCallSnapshot | None = None,
        *,
        tool_call_id: str | None = None,
    ) -> ToolResultView:
        return self._result_view(event, snapshot, tool_call_id)

    def project_result(
        self,
        event: ToolTranscriptEventT,
        snapshot: ToolCallSnapshot | None = None,
    ) -> ToolTranscriptBlock:
        return self.neutral_projector.project_result(
            self.result_view(event, snapshot=snapshot),
            snapshot,
        )

    def tool_result_message_view(
        self,
        message: ToolTranscriptMessageT,
    ) -> ToolResultView:
        return self._tool_result_message_view(message)

    def project_tool_result_message(
        self,
        message: ToolTranscriptMessageT,
    ) -> ToolTranscriptBlock:
        return self.neutral_projector.project_result(
            self.tool_result_message_view(message)
        )


@dataclass
class MappingToolTranscriptViewAdapter:
    """Adapt normalized mapping events through injected result projections."""

    result_text: ToolResultTextProjector
    result_details: ToolResultDetailsProjector
    result_terminated: ToolResultTerminationPredicate
    error_summary: ToolErrorSummaryProjector
    message_event: ToolResultMessageEventProjector
    render_event_text: ToolEventRenderer | None = None
    max_body_lines: int = 8

    def call_id(self, event: Mapping[str, Any]) -> str:
        value = event.get("tool_call_id")
        if isinstance(value, str) and value:
            return value
        return self._tool_name(event)

    def message_id(self, message: object) -> str:
        value = getattr(message, "tool_call_id", None)
        return value if isinstance(value, str) and value else ""

    def call_view(self, event: Mapping[str, Any]) -> ToolCallView:
        return ToolCallView(
            tool_call_id=self.call_id(event),
            tool_name=self._tool_name(event),
            args=event.get("args"),
            rendered_text=self._render(event),
        )

    def result_view(
        self,
        event: Mapping[str, Any],
        snapshot: ToolCallSnapshot | None = None,
        tool_call_id: str | None = None,
    ) -> ToolResultView:
        result = self._event_result(event)
        details = self.result_details(result)
        status = self._result_status(event, result=result, details=details)
        event_tool_name = self._tool_name(event)
        policy_tool_name = (
            snapshot.tool_name if snapshot is not None else event_tool_name
        )
        result_text = ""
        if workspace_tool_body_visibility(policy_tool_name, status):
            result_text = self.result_text(result, self.max_body_lines)
        return ToolResultView(
            tool_call_id=self.call_id(event) if tool_call_id is None else tool_call_id,
            tool_name=event_tool_name,
            status=status,
            args=event.get("args"),
            result_text=result_text,
            rendered_text=self._render(event),
            details=details,
            error_summary=self.error_summary(result),
        )

    def tool_result_message_view(self, message: object) -> ToolResultView:
        event = self.message_event(message)
        return self.result_view(
            event,
            tool_call_id=self.message_id(message) or self._tool_name(event),
        )

    def _render(self, event: Mapping[str, Any]) -> str | None:
        if self.render_event_text is None:
            return None
        return self.render_event_text(event, False)

    @staticmethod
    def _event_result(event: Mapping[str, Any]) -> object:
        if event.get("type") == "tool_execution_update":
            return event.get("partial_result")
        return event.get("result")

    @staticmethod
    def _tool_name(event: Mapping[str, Any]) -> str:
        value = event.get("tool_name")
        return value if isinstance(value, str) and value else "tool"

    def _result_status(
        self,
        event: Mapping[str, Any],
        *,
        result: object,
        details: Mapping[str, Any],
    ) -> ToolTranscriptStatus:
        if details.get("timed_out") is True:
            return "timed_out"
        if details.get("cancelled") is True:
            return "cancelled"
        if bool(event.get("is_error", False)):
            return "error"
        if self.result_terminated(result):
            return "terminate"
        return "ok"


def build_mapping_tool_transcript_projection(
    *,
    result_text: ToolResultTextProjector,
    result_details: ToolResultDetailsProjector,
    result_terminated: ToolResultTerminationPredicate,
    error_summary: ToolErrorSummaryProjector,
    message_event: ToolResultMessageEventProjector,
    render_event_text: ToolEventRenderer | None = None,
    max_body_lines: int = 8,
) -> ToolTranscriptProjectionBinding[Mapping[str, Any], object]:
    """Compose the standard workspace transcript policy with mapping events."""

    adapter = MappingToolTranscriptViewAdapter(
        result_text=result_text,
        result_details=result_details,
        result_terminated=result_terminated,
        error_summary=error_summary,
        message_event=message_event,
        render_event_text=render_event_text,
        max_body_lines=max_body_lines,
    )
    return ToolTranscriptProjectionBinding(
        neutral_projector=ToolTranscriptProjector(
            verb_resolver=workspace_tool_verb,
            body_visibility=workspace_tool_body_visibility,
            command_resolver=workspace_tool_command,
            max_body_lines=max_body_lines,
        ),
        call_id=adapter.call_id,
        message_id=adapter.message_id,
        call_view=adapter.call_view,
        result_view=adapter.result_view,
        tool_result_message_view=adapter.tool_result_message_view,
    )


def workspace_tool_verb(tool_name: str, args: object | None) -> str:
    """Return the standard Agent-workspace transcript verb."""

    normalized = tool_name.lower()
    command = _workspace_command_from_args(args).lower()
    if any(
        part in normalized for part in ("read", "grep", "glob", "list", "ls", "search")
    ):
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


def workspace_tool_body_visibility(
    tool_name: str,
    status: ToolTranscriptStatus,
) -> bool:
    """Choose standard command and inspection bodies for collapsed display."""

    if status != "ok":
        return False
    normalized = tool_name.lower()
    return any(
        part in normalized
        for part in (
            "bash",
            "shell",
            "exec",
            "run",
            "grep",
            "find",
            "ls",
            "test",
            "lint",
            "ruff",
            "pytest",
        )
    )


def workspace_tool_command(
    tool_name: str,
    args: object | None,
    title: str,
) -> str | None:
    """Expose command labels for standard run and test tools."""

    return title if workspace_tool_verb(tool_name, args) in {"Ran", "Tested"} else None


def _workspace_command_from_args(args: object | None) -> str:
    if isinstance(args, Mapping):
        command = args.get("command")
        if isinstance(command, str):
            return command
    return ""


def tool_block_to_record(
    block: ToolTranscriptBlock, *, elapsed_seconds: float = 0.0
) -> ToolExecutionRecord:
    output = block.body or ""
    detail = block.detail or ""
    output_kind = _output_kind(output)
    return ToolExecutionRecord(
        name=block.title or block.tool_name,
        state=_tool_state(block.status),
        elapsed_seconds=elapsed_seconds,
        output=output,
        output_kind=output_kind,
        command=block.command or "",
        stderr=(detail if block.status in {"error", "timed_out", "cancelled"} else ""),
        exit_code=_exit_code(detail),
        show_stats=output_kind == "diff",
    )


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


def _detail(view: ToolResultView, *, tool_name: str) -> str | None:
    if view.status == "ok":
        return _ok_detail(view.details, tool_name=tool_name)
    if view.status == "error":
        return f"failed: {view.error_summary}" if view.error_summary else "failed"
    if view.status == "timed_out":
        return "timed out"
    if view.status == "cancelled":
        return "cancelled"
    if view.status == "terminate":
        return "terminated"
    return None


def _ok_detail(details: Mapping[str, Any], *, tool_name: str) -> str | None:
    if not details:
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
    view: ToolResultView,
    *,
    visible: bool,
    max_lines: int,
) -> str | None:
    if max_lines < 1 or not visible:
        return None
    text = view.rendered_text or view.result_text
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


def _tool_state(status: ToolTranscriptStatus) -> ToolState:
    if status == "ok":
        return "completed"
    if status == "cancelled":
        return "cancelled"
    if status in {"error", "timed_out"}:
        return "failed"
    if status == "terminate":
        return "completed"
    return "running"


def _output_kind(output: str) -> ToolOutputKind:
    stripped = output.lstrip()
    if stripped.startswith("diff --git") or stripped.startswith(("@@", "--- ", "+++ ")):
        return "diff"
    return "text"


def _exit_code(detail: str) -> int | None:
    match = _EXIT_CODE_RE.search(detail)
    if match is None:
        return None
    return int(match.group(1))


__all__ = [
    "MappingToolTranscriptViewAdapter",
    "ToolBodyVisibility",
    "ToolErrorSummaryProjector",
    "ToolEventRenderer",
    "ToolCommandResolver",
    "ToolCallSnapshot",
    "ToolCallView",
    "ToolResultView",
    "ToolTranscriptBlock",
    "ToolTranscriptProjectionBinding",
    "ToolTranscriptProjector",
    "ToolResultDetailsProjector",
    "ToolResultMessageEventProjector",
    "ToolResultTerminationPredicate",
    "ToolResultTextProjector",
    "ToolTranscriptStatus",
    "ToolVerbResolver",
    "build_mapping_tool_transcript_projection",
    "tool_block_to_record",
    "workspace_tool_body_visibility",
    "workspace_tool_command",
    "workspace_tool_verb",
]
