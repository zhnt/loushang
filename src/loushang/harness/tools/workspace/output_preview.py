"""Compatibility entrypoint for shared tool output preview helpers."""

from loushang.harness.tools.output_preview import (
    DEFAULT_TOOL_OUTPUT_PREVIEW_LINES,
    collapse_tool_output_preview,
    drop_tool_timing_tail_line,
    prefers_tail_tool_output,
)
from loushang.harness.tools.output_preview import (
    TOOL_OUTPUT_HEAD_LINES as TOOL_OUTPUT_HEAD_LINES,
)
from loushang.harness.tools.output_preview import (
    TOOL_OUTPUT_TAIL_LINES as TOOL_OUTPUT_TAIL_LINES,
)

__all__ = [
    "DEFAULT_TOOL_OUTPUT_PREVIEW_LINES",
    "collapse_tool_output_preview",
    "drop_tool_timing_tail_line",
    "prefers_tail_tool_output",
]
