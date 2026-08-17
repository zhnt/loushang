"""Profile-driven display transforms for neutral transcript records."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from typing import Generic, Protocol, TypeVar

from loushang.tui.transcript import DisplayRecord, ToolExecutionRecord

ContextT = TypeVar("ContextT")
ContextT_contra = TypeVar("ContextT_contra", contravariant=True)


class ToolDisplayNameProjector(Protocol[ContextT_contra]):
    """Project a tool heading using product-prepared display context."""

    def __call__(self, name: str, *, context: ContextT_contra) -> str: ...


class ToolDisplayOutputProjector(Protocol[ContextT_contra]):
    """Apply product-selected output policy after the heading is projected."""

    def __call__(
        self,
        record: ToolExecutionRecord,
        *,
        projected_name: str,
        context: ContextT_contra,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class TranscriptDisplayProjectionProfile(Generic[ContextT]):
    """Project tool records while keeping product display policy injectable."""

    project_tool_name: ToolDisplayNameProjector[ContextT]
    project_tool_output: ToolDisplayOutputProjector[ContextT]
    suppress_duplicate_tool_command: bool
    tool_record_width_inset: int

    def __post_init__(self) -> None:
        if self.tool_record_width_inset < 0:
            raise ValueError("tool_record_width_inset must be non-negative")

    def project_record(
        self,
        record: DisplayRecord,
        *,
        context: ContextT,
    ) -> DisplayRecord:
        if not isinstance(record, ToolExecutionRecord):
            return record
        name = self.project_tool_name(record.name, context=context)
        command = record.command
        if self.suppress_duplicate_tool_command and _command_duplicates_heading(record):
            command = ""
        output = self.project_tool_output(
            record,
            projected_name=name,
            context=context,
        )
        if (
            name == record.name
            and command == record.command
            and output == record.output
        ):
            return record
        return replace(record, name=name, command=command, output=output)

    def record_render_width(self, record: DisplayRecord, *, width: int) -> int:
        if isinstance(record, ToolExecutionRecord):
            return max(1, width - self.tool_record_width_inset)
        return width


_ABSOLUTE_PATH_RE = re.compile(r"(?P<prefix>^|[\s\"'=])(?P<path>/[^\s\"']+)")


def compact_absolute_display_paths(
    text: str,
    *,
    cwd: str = "",
    home: str | None = None,
) -> str:
    """Compact absolute paths under ``cwd`` first, then under ``home``."""

    normalized_cwd = _normalized_path(cwd)
    normalized_home = _normalized_path(
        os.path.expanduser("~") if home is None else home
    )

    def replace_path(match: re.Match[str]) -> str:
        prefix = match.group("prefix")
        path = match.group("path")
        return prefix + _compact_absolute_path(
            path,
            cwd=normalized_cwd,
            home=normalized_home,
        )

    return _ABSOLUTE_PATH_RE.sub(replace_path, text)


def _command_duplicates_heading(record: ToolExecutionRecord) -> bool:
    if not record.command:
        return False
    return _normalize_tool_text(record.command) == _normalize_tool_text(record.name)


def _normalize_tool_text(text: str) -> str:
    return " ".join(text.strip().split())


def _compact_absolute_path(path: str, *, cwd: str, home: str) -> str:
    if cwd and cwd != "/" and (path == cwd or path.startswith(f"{cwd}/")):
        relative = path[len(cwd) :].lstrip("/")
        return relative or "."
    if home and home != "/" and (path == home or path.startswith(f"{home}/")):
        return "~" + path[len(home) :]
    return path


def _normalized_path(path: str) -> str:
    normalized = path.rstrip("/")
    return normalized or path


__all__ = [
    "ToolDisplayNameProjector",
    "ToolDisplayOutputProjector",
    "TranscriptDisplayProjectionProfile",
    "compact_absolute_display_paths",
]
