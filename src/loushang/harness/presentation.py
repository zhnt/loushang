from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from loushang.agent.types import AgentToolResult

_ANSI_ESCAPE_RE = re.compile(
    r"\x1b"
    r"(?:"
    r"\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]"
    r"|\][\s\S]*?(?:\x07|\x1b\\)"
    r"|[PX^_][\s\S]*?(?:\x1b\\)"
    r"|[\x20-\x2f]+[\x30-\x7e]"
    r"|[\x30-\x7e]"
    r")"
    r"|\x9b[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]"
    r"|\x9d[\s\S]*?(?:\x07|\x9c)"
    r"|[\x80-\x9f]",
    re.DOTALL,
)
_HAS_ESCAPE_RE = re.compile(r"[\x1b\x80-\x9f]")


def _noop_invalidate() -> None:
    return None


@dataclass(frozen=True)
class ToolResultPresentation:
    expanded: str
    collapsed: str
    remaining_lines: int = 0
    notices: tuple[str, ...] = ()
    artifact_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolRenderResultOptions:
    expanded: bool = False
    is_partial: bool = False


@dataclass(frozen=True)
class ToolRenderContext:
    args: object | None = None
    tool_call_id: str = ""
    invalidate: Callable[[], None] = _noop_invalidate
    last_rendered: object | None = None
    state: dict[str, Any] = field(default_factory=dict)
    cwd: str = ""
    execution_started: bool = True
    args_complete: bool = True
    is_partial: bool = False
    expanded: bool = False
    show_images: bool = False
    is_error: bool = False


class RenderableToolDefinition(Protocol):
    render_call: Callable[[object, Mapping[str, str], ToolRenderContext], object | None] | None
    render_result: (
        Callable[
            [AgentToolResult[Any], ToolRenderResultOptions, Mapping[str, str], ToolRenderContext],
            object | None,
        ]
        | None
    )


ToolDefinitionResolver = Callable[[str], RenderableToolDefinition | None]


def strip_ansi(text: str) -> str:
    if not text or not _HAS_ESCAPE_RE.search(text):
        return text
    return _ANSI_ESCAPE_RE.sub("", text)


def normalize_line_endings(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "")


def normalize_display_text(text: str) -> str:
    return strip_ansi(normalize_line_endings(text))


def collapse_text(text: str, *, max_lines: int) -> tuple[str, int]:
    if max_lines < 1:
        raise ValueError("max_lines must be >= 1")
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text, 0
    remaining = len(lines) - max_lines
    return "\n".join([*lines[:max_lines], f"... ({remaining} more lines)"]), remaining


class ToolRenderRuntime:
    def __init__(
        self,
        *,
        cwd: str = "",
        theme: Mapping[str, str] | None = None,
        show_images: bool = False,
        on_invalidate: Callable[[str], None] | None = None,
    ) -> None:
        self._cwd = cwd
        self._theme = dict(theme or {})
        self._show_images = show_images
        self._on_invalidate = on_invalidate
        self._args_by_call_id: dict[str, object] = {}
        self._state_by_call_id: dict[str, dict[str, Any]] = {}
        self._last_call_rendered_by_call_id: dict[str, object | None] = {}
        self._last_result_rendered_by_call_id: dict[str, object | None] = {}

    def render_event(
        self,
        event: Mapping[str, Any],
        tool_definition_resolver: ToolDefinitionResolver,
        *,
        expanded: bool = False,
    ) -> object | None:
        event_type = event.get("type")
        if event_type == "tool_execution_start":
            tool_call_id, tool_name = _event_tool_identity(event)
            definition = _resolve_tool_definition(tool_definition_resolver, tool_name)
            if tool_call_id is None or definition is None:
                return None
            return self.render_call(
                definition,
                tool_call_id,
                event.get("args"),
                execution_started=True,
                args_complete=True,
                is_partial=True,
                expanded=expanded,
                is_error=False,
            )
        if event_type == "tool_execution_update":
            tool_call_id, tool_name = _event_tool_identity(event)
            definition = _resolve_tool_definition(tool_definition_resolver, tool_name)
            partial_result = event.get("partial_result")
            if tool_call_id is None or definition is None or not isinstance(partial_result, AgentToolResult):
                return None
            if "args" in event:
                self._args_by_call_id[tool_call_id] = event["args"]
            return self.render_result(
                definition,
                tool_call_id,
                partial_result,
                is_partial=True,
                expanded=expanded,
                is_error=False,
            )
        if event_type == "tool_execution_end":
            tool_call_id, tool_name = _event_tool_identity(event)
            definition = _resolve_tool_definition(tool_definition_resolver, tool_name)
            result = event.get("result")
            if tool_call_id is None or definition is None or not isinstance(result, AgentToolResult):
                return None
            return self.render_result(
                definition,
                tool_call_id,
                result,
                is_partial=False,
                expanded=expanded,
                is_error=bool(event.get("is_error", False)),
            )
        return None

    def render_call(
        self,
        definition: RenderableToolDefinition,
        tool_call_id: str,
        args: object,
        *,
        execution_started: bool = True,
        args_complete: bool = True,
        is_partial: bool = True,
        expanded: bool = False,
        is_error: bool = False,
    ) -> object | None:
        if definition.render_call is None:
            return None
        self._args_by_call_id[tool_call_id] = args
        context = self._context(
            tool_call_id,
            last_rendered=self._last_call_rendered_by_call_id.get(tool_call_id),
            execution_started=execution_started,
            args_complete=args_complete,
            is_partial=is_partial,
            expanded=expanded,
            is_error=is_error,
        )
        try:
            rendered = definition.render_call(args, self._theme, context)
        except Exception:
            return None
        self._last_call_rendered_by_call_id[tool_call_id] = rendered
        return rendered

    def render_result(
        self,
        definition: RenderableToolDefinition,
        tool_call_id: str,
        result: AgentToolResult[Any],
        *,
        is_partial: bool = False,
        expanded: bool = False,
        is_error: bool = False,
        execution_started: bool = True,
        args_complete: bool = True,
    ) -> object | None:
        if definition.render_result is None:
            return None
        try:
            presentation_result = result.for_presentation()
        except Exception:
            return None
        context = self._context(
            tool_call_id,
            last_rendered=self._last_result_rendered_by_call_id.get(tool_call_id),
            execution_started=execution_started,
            args_complete=args_complete,
            is_partial=is_partial,
            expanded=expanded,
            is_error=is_error,
        )
        options = ToolRenderResultOptions(expanded=expanded, is_partial=is_partial)
        try:
            rendered = definition.render_result(
                presentation_result,
                options,
                self._theme,
                context,
            )
        except Exception:
            return None
        self._last_result_rendered_by_call_id[tool_call_id] = rendered
        return rendered

    def _context(
        self,
        tool_call_id: str,
        *,
        last_rendered: object | None,
        execution_started: bool,
        args_complete: bool,
        is_partial: bool,
        expanded: bool,
        is_error: bool,
    ) -> ToolRenderContext:
        return ToolRenderContext(
            args=self._args_by_call_id.get(tool_call_id),
            tool_call_id=tool_call_id,
            invalidate=lambda: self._invalidate(tool_call_id),
            last_rendered=last_rendered,
            state=self._state_for(tool_call_id),
            cwd=self._cwd,
            execution_started=execution_started,
            args_complete=args_complete,
            is_partial=is_partial,
            expanded=expanded,
            show_images=self._show_images,
            is_error=is_error,
        )

    def _state_for(self, tool_call_id: str) -> dict[str, Any]:
        state = self._state_by_call_id.get(tool_call_id)
        if state is None:
            state = {}
            self._state_by_call_id[tool_call_id] = state
        return state

    def _invalidate(self, tool_call_id: str) -> None:
        if self._on_invalidate is not None:
            self._on_invalidate(tool_call_id)


def _event_tool_identity(event: Mapping[str, Any]) -> tuple[str | None, str]:
    tool_call_id = event.get("tool_call_id")
    tool_name = event.get("tool_name")
    return (
        tool_call_id if isinstance(tool_call_id, str) else None,
        tool_name if isinstance(tool_name, str) else "",
    )


def _resolve_tool_definition(
    resolver: ToolDefinitionResolver,
    tool_name: str,
) -> RenderableToolDefinition | None:
    try:
        return resolver(tool_name)
    except Exception:
        return None
