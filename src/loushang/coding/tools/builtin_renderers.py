from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from loushang.agent.types import AgentToolResult

from .output_preview import (
    DEFAULT_TOOL_OUTPUT_PREVIEW_LINES,
    collapse_tool_output_preview,
)
from .presentation import (
    get_tool_text_output,
    normalize_display_text,
    render_tool_result_presentation,
)
from .types import ToolRenderContext, ToolRenderOutput, ToolRenderResultOptions


def render_bash_call(args: object, theme: Mapping[str, str], context: ToolRenderContext) -> ToolRenderOutput:
    del theme
    if context.execution_started and context.state.get("started_at") is None:
        context.state["started_at"] = time.monotonic()
        context.state["ended_at"] = None
    mapping = _mapping(args)
    command = _command_text(mapping.get("command"))
    timeout = _number_arg(mapping, "timeout", "timeout_seconds", "timeoutSeconds")
    timeout_suffix = f" (timeout {_format_number(timeout)}s)" if timeout is not None else ""
    return f"$ {command}{timeout_suffix}"


def render_read_call(args: object, theme: Mapping[str, str], context: ToolRenderContext) -> ToolRenderOutput:
    del theme, context
    path = _path_arg(args)
    offset = _number_arg(_mapping(args), "offset")
    limit = _number_arg(_mapping(args), "limit")
    suffix = _line_range_suffix(offset=offset, limit=limit)
    return f"read {path}{suffix}"


def render_grep_call(args: object, theme: Mapping[str, str], context: ToolRenderContext) -> ToolRenderOutput:
    del theme, context
    mapping = _mapping(args)
    pattern = _string_arg(mapping, "pattern", fallback="[invalid arg]")
    path = _string_arg(mapping, "path", "file_path", fallback=".")
    glob = _string_arg(mapping, "glob", fallback="")
    limit = _number_arg(mapping, "limit")
    parts = [f"grep /{pattern}/ in {path}"]
    if glob:
        parts.append(f"({glob})")
    if limit is not None:
        parts.append(f"limit {_format_number(limit)}")
    return " ".join(parts)


def render_find_call(args: object, theme: Mapping[str, str], context: ToolRenderContext) -> ToolRenderOutput:
    del theme, context
    mapping = _mapping(args)
    pattern = _string_arg(mapping, "pattern", fallback="[invalid arg]")
    path = _string_arg(mapping, "path", "file_path", fallback=".")
    limit = _number_arg(mapping, "limit")
    suffix = f" (limit {_format_number(limit)})" if limit is not None else ""
    return f"find {pattern} in {path}{suffix}"


def render_ls_call(args: object, theme: Mapping[str, str], context: ToolRenderContext) -> ToolRenderOutput:
    del theme, context
    mapping = _mapping(args)
    path = _string_arg(mapping, "path", "file_path", fallback=".")
    limit = _number_arg(mapping, "limit")
    suffix = f" (limit {_format_number(limit)})" if limit is not None else ""
    return f"ls {path}{suffix}"


def render_write_call(args: object, theme: Mapping[str, str], context: ToolRenderContext) -> ToolRenderOutput:
    del theme, context
    mapping = _mapping(args)
    text = f"write {_path_arg(args)}"
    content = mapping.get("content")
    if isinstance(content, str) and content:
        rendered_content = _collapse_body(
            normalize_display_text(content),
            max_lines=10,
            expanded=False,
            remaining_suffix=", {total} total",
        )
        if rendered_content:
            text = f"{text}\n\n{rendered_content}"
    elif "content" in mapping and not isinstance(content, str):
        text = f"{text}\n\n[invalid content arg - expected string]"
    return text


def render_edit_call(args: object, theme: Mapping[str, str], context: ToolRenderContext) -> ToolRenderOutput:
    del theme, context
    mapping = _mapping(args)
    path = _path_arg(args)
    edit_count = _edit_count(mapping)
    suffix = ""
    if edit_count is not None:
        suffix = f" ({edit_count} {'edit' if edit_count == 1 else 'edits'})"
    return f"edit {path}{suffix}"


def render_default_tool_result(
    result: AgentToolResult[Any],
    options: ToolRenderResultOptions,
    theme: Mapping[str, str],
    context: ToolRenderContext,
) -> ToolRenderOutput:
    del theme
    return _render_result_with_limit(result, options, context, max_collapsed_lines=15)


def render_bash_result(
    result: AgentToolResult[Any],
    options: ToolRenderResultOptions,
    theme: Mapping[str, str],
    context: ToolRenderContext,
) -> ToolRenderOutput:
    del theme
    rendered = _render_result_with_limit(
        result,
        options,
        context,
        max_collapsed_lines=5 if options.is_partial else DEFAULT_TOOL_OUTPUT_PREVIEW_LINES,
        tail=True,
    )
    started_at = context.state.get("started_at")
    if isinstance(started_at, int | float):
        if not options.is_partial or context.is_error:
            context.state["ended_at"] = context.state.get("ended_at") or time.monotonic()
        end_at = time.monotonic() if options.is_partial else context.state.get("ended_at")
        if isinstance(end_at, int | float):
            label = "Elapsed" if options.is_partial else "Took"
            rendered = _join_non_empty(rendered, f"{label} {_format_duration(end_at - started_at)}")
    return rendered


def render_read_result(
    result: AgentToolResult[Any],
    options: ToolRenderResultOptions,
    theme: Mapping[str, str],
    context: ToolRenderContext,
) -> ToolRenderOutput:
    del theme
    return _render_result_with_limit(result, options, context, max_collapsed_lines=10)


def render_grep_result(
    result: AgentToolResult[Any],
    options: ToolRenderResultOptions,
    theme: Mapping[str, str],
    context: ToolRenderContext,
) -> ToolRenderOutput:
    del theme
    return _render_result_with_limit(result, options, context, max_collapsed_lines=15)


def render_find_or_ls_result(
    result: AgentToolResult[Any],
    options: ToolRenderResultOptions,
    theme: Mapping[str, str],
    context: ToolRenderContext,
) -> ToolRenderOutput:
    del theme
    return _render_result_with_limit(result, options, context, max_collapsed_lines=20)


def render_edit_result(
    result: AgentToolResult[Any],
    options: ToolRenderResultOptions,
    theme: Mapping[str, str],
    context: ToolRenderContext,
) -> ToolRenderOutput:
    del options, theme
    details = result.details
    if not context.is_error and isinstance(details, Mapping):
        diff = details.get("diff")
        if isinstance(diff, str) and diff:
            return diff
    return render_default_tool_result(
        result,
        ToolRenderResultOptions(expanded=context.expanded, is_partial=context.is_partial),
        {},
        context,
    )


def render_write_result(
    result: AgentToolResult[Any],
    options: ToolRenderResultOptions,
    theme: Mapping[str, str],
    context: ToolRenderContext,
) -> ToolRenderOutput:
    del theme
    if not context.is_error:
        return None
    return _render_result_with_limit(result, options, context, max_collapsed_lines=15)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _path_arg(args: object) -> str:
    mapping = _mapping(args)
    return _string_arg(mapping, "path", "file_path", fallback="[invalid arg]")


def _string_arg(mapping: Mapping[str, Any], *keys: str, fallback: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str):
            return value
    return fallback


def _number_arg(mapping: Mapping[str, Any], *keys: str) -> int | float | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            return value
    return None


def _command_text(value: object) -> str:
    if isinstance(value, str):
        return value or "..."
    if isinstance(value, (list, tuple)) and value and all(isinstance(part, str) for part in value):
        return " ".join(value)
    if value is None:
        return "..."
    return "[invalid arg]"


def _format_number(value: int | float) -> str:
    return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)


def _line_range_suffix(*, offset: int | float | None, limit: int | float | None) -> str:
    if offset is None and limit is None:
        return ""
    start = int(offset) if offset is not None else 1
    if limit is None:
        return f":{start}"
    end = start + int(limit) - 1
    return f":{start}-{end}"


def _edit_count(mapping: Mapping[str, Any]) -> int | None:
    edits = mapping.get("edits")
    if isinstance(edits, list):
        return len(edits)
    if isinstance(mapping.get("oldText"), str) and isinstance(mapping.get("newText"), str):
        return 1
    return None


def _render_result_with_limit(
    result: AgentToolResult[Any],
    options: ToolRenderResultOptions,
    context: ToolRenderContext,
    *,
    max_collapsed_lines: int,
    tail: bool = False,
) -> str:
    body = get_tool_text_output(result.content, show_images=context.show_images).strip()
    collapsed = _collapse_body(
        body,
        max_lines=max_collapsed_lines,
        expanded=options.expanded,
        tail=tail,
    )
    presentation = render_tool_result_presentation(
        (),
        result.details,
        show_images=context.show_images,
    )
    extras = [*presentation.notices, *(f"[Full output: {path}]" for path in presentation.artifact_paths)]
    return _join_non_empty(collapsed, *extras)


def _collapse_body(
    text: str,
    *,
    max_lines: int,
    expanded: bool,
    tail: bool = False,
    remaining_suffix: str = "",
) -> str:
    lines = _trim_trailing_empty_lines(text.splitlines())
    if expanded or len(lines) <= max_lines:
        return "\n".join(lines)
    if tail:
        return collapse_tool_output_preview("\n".join(lines), max_lines=max_lines, tail=True)
    remaining = len(lines) - max_lines
    suffix = remaining_suffix.format(total=len(lines)) if remaining_suffix else ""
    return "\n".join([*lines[:max_lines], f"... ({remaining} more lines{suffix})"])


def _trim_trailing_empty_lines(lines: list[str]) -> list[str]:
    end = len(lines)
    while end > 0 and lines[end - 1] == "":
        end -= 1
    return lines[:end]


def _format_duration(seconds: float) -> str:
    return f"{max(seconds, 0.0):.1f}s"


def _join_non_empty(*parts: object) -> str:
    return "\n".join(part for part in (str(part) for part in parts) if part)
