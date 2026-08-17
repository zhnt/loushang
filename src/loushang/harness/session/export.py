"""Session export adapter over Agent transcript exporters."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from loushang.foundation.json import require_json_mapping
from loushang.harness.presentation import RenderableToolDefinition
from loushang.harness.session.composition import SessionComposition
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.transcript import (
    AgentTranscriptContext,
    ProductTranscriptSession,
    TranscriptExportRequest,
    TranscriptHtmlExportProfile,
    TranscriptToolDefinition,
    export_agent_transcript_to_html,
    export_agent_transcript_to_jsonl,
)


class ExportAgentPort(Protocol):
    @property
    def system_prompt(self) -> str: ...


class SessionExportPort(Protocol):
    session_manager: ProductTranscriptSession[Any, Any]

    @property
    def _composition(self) -> SessionComposition: ...

    @property
    def agent(self) -> ExportAgentPort: ...

    @property
    def session_id(self) -> str: ...

    @property
    def session_name(self) -> str | None: ...

    def get_all_tools(self) -> list[ToolDefinition]: ...

    def get_tool_definition(self, name: str) -> RenderableToolDefinition | None: ...

    def get_session_context(self) -> AgentTranscriptContext: ...


def export_session_to_jsonl(
    session: SessionExportPort,
    output_path: str | None = None,
) -> str:
    path = (
        Path(output_path)
        if output_path is not None
        else _default_jsonl_export_path(session)
    )
    return export_agent_transcript_to_jsonl(
        session.session_manager.get_header(),
        session.session_manager.get_branch(),
        path,
    )


def export_session_to_html(
    session: SessionExportPort,
    output_path: str | None = None,
) -> str:
    path = (
        Path(output_path)
        if output_path is not None
        else _default_html_export_path(session)
    )
    return export_agent_transcript_to_html(
        _build_export_request(session),
        path,
        profile=TranscriptHtmlExportProfile(
            theme=_export_theme(session),
            custom_message_renderer=_custom_message_renderer(session),
            tool_definition_resolver=session.get_tool_definition,
        ),
    )


def _build_export_request(session: SessionExportPort) -> TranscriptExportRequest:
    stats = session._composition.session_inspector.build_session_stats()
    context_usage = stats.context_usage
    entries = session.session_manager.get_entries()
    tools = tuple(
        TranscriptToolDefinition(
            name=definition.name,
            description=definition.description,
            parameters=require_json_mapping(
                definition.parameters,
                name=f"tool definition {definition.name!r} parameters",
            ),
        )
        for definition in session.get_all_tools()
    )
    return TranscriptExportRequest(
        header=session.session_manager.get_header(),
        conversation_name=session.session_name,
        entries=entries,
        branch_entries=session.session_manager.get_branch(),
        leaf_id=session.session_manager.get_leaf_id(),
        messages=session.get_session_context().messages,
        stats=require_json_mapping(asdict(stats), name="coding session export stats"),
        entry_count=stats.entry_count,
        message_count=stats.message_count,
        active_tool_count=stats.active_tool_count,
        estimated_context_tokens=(
            context_usage.estimated_context_tokens
            if context_usage is not None
            and context_usage.estimated_context_tokens is not None
            else 0
        ),
        system_prompt=session.agent.system_prompt,
        tool_definitions=tools,
        cwd=session.session_manager.get_cwd(),
    )


def _default_jsonl_export_path(session: SessionExportPort) -> Path:
    cwd = Path(session.session_manager.get_cwd()).expanduser().resolve()
    timestamp = (
        datetime.now(UTC)
        .isoformat()
        .replace("+00:00", "Z")
        .replace(":", "-")
        .replace(".", "-")
    )
    return cwd / f"session-{timestamp}.jsonl"


def _default_html_export_path(session: SessionExportPort) -> Path:
    return (
        session.session_manager.get_session_dir() / f"{session.session_id}-export.html"
    )


def _custom_message_renderer(session: SessionExportPort):
    runner = getattr(session, "extension_runner", None)
    getter = (
        getattr(runner, "get_message_renderer", None) if runner is not None else None
    )
    return getter if callable(getter) else None


def _export_theme(session: SessionExportPort) -> dict[str, str]:
    theme = getattr(session, "export_theme", None)
    if isinstance(theme, dict):
        return {str(key): str(value) for key, value in theme.items()}
    return {}


__all__ = ["export_session_to_html", "export_session_to_jsonl"]
