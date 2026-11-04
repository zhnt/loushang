from __future__ import annotations

DEFAULT_TOOL_OUTPUT_PREVIEW_LINES = 8
TOOL_OUTPUT_HEAD_LINES = 3
TOOL_OUTPUT_TAIL_LINES = 3
_LINE_BREAKS = "\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029"


def collapse_tool_output_preview(
    text: str, *, max_lines: int, tail: bool = False
) -> str:
    lines = text.splitlines()
    if max_lines < 1 or len(lines) <= max_lines:
        return text

    if tail and max_lines >= TOOL_OUTPUT_HEAD_LINES + TOOL_OUTPUT_TAIL_LINES + 1:
        omitted = len(lines) - TOOL_OUTPUT_HEAD_LINES - TOOL_OUTPUT_TAIL_LINES
        return "\n".join(
            [
                *lines[:TOOL_OUTPUT_HEAD_LINES],
                f"... ({omitted} hidden lines)",
                *lines[-TOOL_OUTPUT_TAIL_LINES:],
            ]
        )

    remaining = len(lines) - max_lines
    if tail:
        return "\n".join([f"... ({remaining} earlier lines)", *lines[-max_lines:]])
    return "\n".join([*lines[:max_lines], f"... ({remaining} more lines)"])


def prefers_tail_tool_output(tool_name: str) -> bool:
    normalized = tool_name.lower()
    return any(
        part in normalized
        for part in ("bash", "shell", "exec", "run", "test", "lint", "ruff", "pytest")
    )


def drop_tool_timing_tail_line(output: str) -> str:
    if not output:
        return output
    # The common case has no timing suffix. Inspect its bounded last line
    # before allocating a list for every line of a large tool result.
    cutoff = max(0, len(output) - 1024)
    end = len(output)
    while end > cutoff and output[end - 1] in _LINE_BREAKS:
        end -= 1
    start = end
    while start > cutoff and output[start - 1] not in _LINE_BREAKS:
        start -= 1
    if (
        (end > cutoff or cutoff == 0)
        and (start > cutoff or cutoff == 0)
        and not _is_tool_timing_line(output[start:end].strip())
    ):
        return output
    lines = output.splitlines()
    if not lines or not _is_tool_timing_line(lines[-1].strip()):
        return output
    return "\n".join(lines[:-1])


def _is_tool_timing_line(line: str) -> bool:
    parts = line.split()
    if len(parts) != 2 or parts[0] not in {"Took", "Elapsed"}:
        return False
    return _looks_like_duration(parts[1])


def _looks_like_duration(value: str) -> bool:
    if value.endswith("ms"):
        value = value[:-2]
    elif value.endswith(("s", "m", "h")):
        value = value[:-1]
    if not value:
        return False
    try:
        float(value)
    except ValueError:
        return False
    return True


__all__ = [
    "DEFAULT_TOOL_OUTPUT_PREVIEW_LINES",
    "collapse_tool_output_preview",
    "drop_tool_timing_tail_line",
    "prefers_tail_tool_output",
]
