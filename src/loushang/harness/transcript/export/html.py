"""Self-contained HTML export for a Conversation JSONL Agent transcript.

The runtime owns the standard transcript document and default renderers. A
Product supplies only its presentation profile: identity, optional custom
message renderer, tool-definition resolver, theme, and output destination.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import TypeAlias

from loushang.agent.types import AgentToolResult
from loushang.ai.types import (
    AssistantMessage,
    TextPart,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from loushang.foundation.json import JSONValue, require_json_mapping
from loushang.harness.conversation import (
    CommandExecutionRecord,
    ConversationHeader,
    ConversationJsonlHeaderCodec,
    ConversationJsonlRecordCodec,
    ConversationRecord,
)
from loushang.harness.presentation import ToolDefinitionResolver, ToolRenderRuntime
from loushang.harness.tools.workspace.presentation import render_tool_result_text
from loushang.harness.transcript.kinds import (
    AGENT_MESSAGE_KIND,
    APPLICATION_MESSAGE_KIND,
    COMMAND_EXECUTION_KIND,
    CONTEXT_BRANCH_SUMMARY_KIND,
    CONTEXT_COMPACTION_CHECKPOINT_KIND,
    CONVERSATION_METADATA_PATCH_KIND,
    EXTENSION_DATA_KIND,
    MODEL_CALL_OUTCOME_KIND,
    MODEL_INPUT_COMPONENT_KIND,
    MODEL_INPUT_PREPARED_KIND,
    MODEL_SELECTION_KIND,
    RECORD_ANNOTATION_PATCH_KIND,
    STANDARD_AGENT_TRANSCRIPT_KINDS,
    THINKING_SELECTION_KIND,
)
from loushang.harness.transcript.profile import AgentTranscriptProfile
from loushang.harness.transcript.types import (
    AgentTranscriptRecord,
    ApplicationMessage,
    BranchContextSummary,
    ContextCompactionCheckpoint,
    RecordAnnotationPatch,
)

from .ansi import render_ansi_pre
from .markdown import render_markdown

CustomMessageRenderer: TypeAlias = Callable[[str], Callable[..., object] | None]

HTML_TRANSCRIPT_DISPOSITIONS = {
    AGENT_MESSAGE_KIND: "render",
    THINKING_SELECTION_KIND: "state-only",
    MODEL_SELECTION_KIND: "state-only",
    COMMAND_EXECUTION_KIND: "render",
    CONTEXT_COMPACTION_CHECKPOINT_KIND: "render",
    CONTEXT_BRANCH_SUMMARY_KIND: "render",
    APPLICATION_MESSAGE_KIND: "render",
    EXTENSION_DATA_KIND: "hidden",
    RECORD_ANNOTATION_PATCH_KIND: "tree-only",
    CONVERSATION_METADATA_PATCH_KIND: "metadata-only",
    MODEL_CALL_OUTCOME_KIND: "hidden",
    MODEL_INPUT_COMPONENT_KIND: "hidden",
    MODEL_INPUT_PREPARED_KIND: "hidden",
}
if set(HTML_TRANSCRIPT_DISPOSITIONS) != set(STANDARD_AGENT_TRANSCRIPT_KINDS):
    raise RuntimeError("HTML transcript dispositions must cover every standard kind")

_PROFILE = AgentTranscriptProfile.default()
_HEADER_CODEC = ConversationJsonlHeaderCodec()
_RECORD_CODEC = ConversationJsonlRecordCodec(_PROFILE.payload_codecs)


@dataclass(frozen=True)
class TranscriptToolDefinition:
    """Serializable tool metadata displayed by an exported transcript."""

    name: str
    description: str
    parameters: Mapping[str, JSONValue]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("exported tool name must be a non-empty string")
        if not isinstance(self.description, str):
            raise TypeError("exported tool description must be a string")
        object.__setattr__(
            self,
            "parameters",
            require_json_mapping(
                dict(self.parameters),
                name=f"exported tool {self.name!r} parameters",
            ),
        )


@dataclass(frozen=True)
class TranscriptExportRequest:
    """A product-neutral snapshot required to export one transcript branch."""

    header: ConversationHeader
    conversation_name: str | None
    entries: Sequence[AgentTranscriptRecord]
    branch_entries: Sequence[AgentTranscriptRecord]
    leaf_id: str | None
    messages: Sequence[object]
    stats: Mapping[str, JSONValue]
    entry_count: int
    message_count: int
    active_tool_count: int
    estimated_context_tokens: int
    system_prompt: str
    tool_definitions: Sequence[TranscriptToolDefinition] = ()
    cwd: str = ""

    def __post_init__(self) -> None:
        if self.conversation_name is not None and not isinstance(
            self.conversation_name, str
        ):
            raise TypeError("conversation_name must be a string or None")
        for name, value in (
            ("entry_count", self.entry_count),
            ("message_count", self.message_count),
            ("active_tool_count", self.active_tool_count),
            ("estimated_context_tokens", self.estimated_context_tokens),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if value < 0:
                raise ValueError(f"{name} must not be negative")
        if not isinstance(self.system_prompt, str):
            raise TypeError("system_prompt must be a string")
        if not isinstance(self.cwd, str):
            raise TypeError("cwd must be a string")
        object.__setattr__(self, "entries", tuple(self.entries))
        object.__setattr__(self, "branch_entries", tuple(self.branch_entries))
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "tool_definitions", tuple(self.tool_definitions))
        object.__setattr__(
            self,
            "stats",
            require_json_mapping(dict(self.stats), name="transcript export stats"),
        )


@dataclass(frozen=True)
class TranscriptHtmlExportProfile:
    """Product-owned visual and custom-record hooks for the shared document."""

    title: str = "Session Export"
    theme: Mapping[str, str] = field(default_factory=dict)
    custom_message_renderer: CustomMessageRenderer | None = None
    tool_definition_resolver: ToolDefinitionResolver | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.title, str) or not self.title:
            raise ValueError("HTML export title must be a non-empty string")
        if not isinstance(self.theme, Mapping):
            raise TypeError("HTML export theme must be a mapping")
        normalized_theme: dict[str, str] = {}
        for key, value in self.theme.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise TypeError("HTML export theme keys and values must be strings")
            normalized_theme[key] = value
        object.__setattr__(self, "theme", normalized_theme)


def export_agent_transcript_to_html(
    request: TranscriptExportRequest,
    output_path: str | Path,
    *,
    profile: TranscriptHtmlExportProfile | None = None,
) -> str:
    """Write a self-contained HTML document for the supplied transcript snapshot."""

    profile = profile or TranscriptHtmlExportProfile()
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    template = _read_asset("template.html")
    css = _read_asset("template.css")
    script = _read_asset("template.js")
    data = _encode_transcript_data(request)
    title = request.conversation_name or request.header.conversation_id

    html_output = (
        template.replace("{{TITLE}}", html.escape(title))
        .replace("{{EXPORT_TITLE}}", html.escape(profile.title))
        .replace("{{STYLE}}", _apply_theme(css, profile.theme))
        .replace("{{SCRIPT}}", script)
        .replace("{{SESSION_ID}}", html.escape(request.header.conversation_id))
        .replace("{{SESSION_NAME}}", html.escape(request.conversation_name or ""))
        .replace("{{ENTRY_COUNT}}", str(request.entry_count))
        .replace("{{MESSAGE_COUNT}}", str(request.message_count))
        .replace("{{ACTIVE_TOOL_COUNT}}", str(request.active_tool_count))
        .replace("{{ESTIMATED_CONTEXT_TOKENS}}", str(request.estimated_context_tokens))
        .replace(
            "{{SESSION_TREE}}",
            render_entry_tree(request.entries, leaf_id=request.leaf_id),
        )
        .replace(
            "{{TRANSCRIPT}}",
            render_transcript(
                request.branch_entries,
                custom_renderer=profile.custom_message_renderer,
                theme=profile.theme,
            ),
        )
        .replace(
            "{{TOOL_SECTIONS}}",
            render_tool_sections(
                request.messages,
                tool_definition_resolver=profile.tool_definition_resolver,
                theme=profile.theme,
                cwd=request.cwd,
            ),
        )
        .replace("{{SESSION_DATA}}", data)
    )
    path.write_text(html_output, encoding="utf-8")
    return str(path)


def render_transcript(
    messages: Sequence[object],
    *,
    custom_renderer: CustomMessageRenderer | None = None,
    theme: Mapping[str, str] | None = None,
) -> str:
    items: list[str] = []
    for index, message in enumerate(messages, start=1):
        rendered = _render_message(
            message,
            custom_renderer=custom_renderer,
            theme=theme or {},
            message_id=f"message-{index}",
        )
        if rendered is not None:
            items.append(rendered)
    return "\n".join(items)


def render_tool_sections(
    messages: Sequence[object],
    *,
    tool_definition_resolver: ToolDefinitionResolver | None = None,
    theme: Mapping[str, str] | None = None,
    cwd: str = "",
) -> str:
    calls: list[str] = []
    results: list[str] = []
    render_runtime = ToolRenderRuntime(
        cwd=cwd, theme=dict(theme or {}), show_images=False
    )

    for message in messages:
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolCall):
                    rendered = _render_tool_call_with_renderer(
                        render_runtime, tool_definition_resolver, block
                    )
                    body = rendered or (
                        "<strong>"
                        + html.escape(block.name)
                        + "</strong><pre>"
                        + html.escape(
                            json.dumps(block.arguments, indent=2, sort_keys=True)
                        )
                        + "</pre>"
                    )
                    calls.append(_tool_list_item("tool-call-item", block.name, body))
        elif isinstance(message, ToolResultMessage):
            result_flags = []
            if getattr(message, "is_error", False):
                result_flags.append("error")
            if getattr(message, "terminate", False):
                result_flags.append("terminate")
            rendered = _render_tool_result_with_renderer(
                render_runtime, tool_definition_resolver, message
            )
            if rendered is None:
                text = render_tool_result_text(
                    message.content, message.details, preserve_ansi=True
                )
                rendered = (
                    "<strong>"
                    + html.escape(message.tool_name)
                    + "</strong>"
                    + (
                        ' <span class="tool-status">'
                        + html.escape(", ".join(result_flags))
                        + "</span>"
                        if result_flags
                        else ""
                    )
                    + render_ansi_pre(text)
                )
            results.append(
                '<li class="tool-result-item" data-tool-name="'
                + html.escape(message.tool_name)
                + '" data-tool-status="'
                + html.escape(",".join(result_flags) or "ok")
                + '">'
                + rendered
                + "</li>"
            )

    return (
        '<section><h2 id="tool-calls">Tool Calls</h2><ul>'
        + ("".join(calls) or "<li>None</li>")
        + "</ul></section>"
        + '<section><h2 id="tool-results">Tool Results</h2><ul>'
        + ("".join(results) or "<li>None</li>")
        + "</ul></section>"
    )


def render_entry_tree(
    entries: Sequence[AgentTranscriptRecord], *, leaf_id: str | None
) -> str:
    if not entries:
        return "<p>No entries</p>"
    label_by_target = {
        entry.payload.target_record_id: entry.payload.value
        for entry in entries
        if entry.kind == RECORD_ANNOTATION_PATCH_KIND
        and isinstance(entry.payload, RecordAnnotationPatch)
        and entry.payload.namespace == "display.label"
        and entry.payload.operation == "set"
        and isinstance(entry.payload.value, str)
    }
    rows = []
    for entry in entries:
        label = label_by_target.get(entry.record_id)
        label_html = (
            f' <span class="entry-label">{html.escape(label)}</span>' if label else ""
        )
        active = " active" if entry.record_id == leaf_id else ""
        rows.append(
            f'<li id="entry-{html.escape(entry.record_id)}" class="tree-entry{active}">'
            f'<a href="#entry-{html.escape(entry.record_id)}">'
            f"<code>{html.escape(entry.kind)}</code> "
            f'<span class="entry-id">{html.escape(entry.record_id)}</span>'
            "</a>"
            f"{label_html}"
            "</li>"
        )
    return "<ul>" + "".join(rows) + "</ul>"


def _read_asset(name: str) -> str:
    return resources.files(__package__).joinpath(name).read_text(encoding="utf-8")


def _encode_transcript_data(request: TranscriptExportRequest) -> str:
    data: dict[str, object] = {
        "header": dict(_HEADER_CODEC.encode_header(request.header)),
        "entries": [
            dict(_RECORD_CODEC.encode_record(entry)) for entry in request.entries
        ],
        "leafId": request.leaf_id,
        "stats": request.stats,
        "tree": {"entryCount": len(request.entries), "leafId": request.leaf_id},
        "systemPrompt": request.system_prompt,
        "tools": [
            {
                "name": definition.name,
                "description": definition.description,
                "parameters": dict(definition.parameters),
            }
            for definition in request.tool_definitions
        ],
    }
    serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return base64.b64encode(serialized.encode("utf-8")).decode("ascii")


def _apply_theme(css: str, theme: Mapping[str, str]) -> str:
    if not theme:
        return css
    variables = "\n".join(
        f"  --{html.escape(key)}: {html.escape(value)};"
        for key, value in sorted(theme.items())
    )
    return ":root {\n" + variables + "\n}\n" + css


def _tool_list_item(css_class: str, tool_name: str, body: str) -> str:
    return (
        f'<li class="{html.escape(css_class)}" data-tool-name="{html.escape(tool_name)}">'
        + body
        + "</li>"
    )


def _render_tool_call_with_renderer(
    render_runtime: ToolRenderRuntime,
    resolver: ToolDefinitionResolver | None,
    block: ToolCall,
) -> str | None:
    if resolver is None:
        return None
    try:
        return _render_tool_renderer_output(
            render_runtime.render_event(
                {
                    "type": "tool_execution_start",
                    "tool_call_id": block.id,
                    "tool_name": block.name,
                    "args": block.arguments,
                },
                resolver,
            )
        )
    except Exception:
        return None


def _render_tool_result_with_renderer(
    render_runtime: ToolRenderRuntime,
    resolver: ToolDefinitionResolver | None,
    message: ToolResultMessage,
) -> str | None:
    if resolver is None:
        return None
    result = AgentToolResult(
        content=message.content,
        details=message.details,
        terminate=getattr(message, "terminate", False),
    )
    try:
        event = {
            "type": "tool_execution_end",
            "tool_call_id": message.tool_call_id,
            "tool_name": message.tool_name,
            "result": result,
            "is_error": bool(getattr(message, "is_error", False)),
        }
        collapsed = _render_tool_renderer_output(
            render_runtime.render_event(event, resolver, expanded=False)
        )
        expanded = _render_tool_renderer_output(
            render_runtime.render_event(event, resolver, expanded=True)
        )
        status = _rendered_tool_result_status(message)
        if collapsed is None and expanded is None:
            return None
        if expanded is None or expanded == collapsed:
            return _rendered_result_container(
                collapsed or "", expanded=False, status=status
            )
        if collapsed is None:
            return _rendered_result_container(expanded, expanded=True, status=status)
        return _rendered_result_container(
            collapsed, expanded=False, status=status
        ) + _rendered_result_container(expanded, expanded=True, status=status)
    except Exception:
        return None


def _render_tool_renderer_output(rendered: object) -> str | None:
    if rendered is None:
        return None
    if isinstance(rendered, str):
        return render_ansi_pre(rendered)
    if isinstance(rendered, dict):
        html_output = rendered.get("html")
        if isinstance(html_output, str):
            return html_output
        text = rendered.get("text")
        if isinstance(text, str):
            return render_ansi_pre(text)
    return None


def _rendered_result_container(rendered: str, *, expanded: bool, status: str) -> str:
    return (
        '<div class="tool-rendered-result'
        + (" expanded" if expanded else "")
        + '" data-render-contract-version="1" data-render-status="'
        + html.escape(status)
        + '" data-expanded="'
        + ("true" if expanded else "false")
        + '">'
        + rendered
        + "</div>"
    )


def _rendered_tool_result_status(message: ToolResultMessage) -> str:
    if getattr(message, "is_error", False):
        return "error"
    if getattr(message, "terminate", False):
        return "terminate"
    return "ok"


def _render_message(
    message: object,
    *,
    custom_renderer: CustomMessageRenderer | None,
    theme: Mapping[str, str],
    message_id: str | None = None,
) -> str | None:
    if isinstance(message, ConversationRecord):
        disposition = HTML_TRANSCRIPT_DISPOSITIONS.get(message.kind)
        if disposition is not None and disposition != "render":
            return None
        if message.kind == AGENT_MESSAGE_KIND:
            return _render_message(
                message.payload,
                custom_renderer=custom_renderer,
                theme=theme,
                message_id=message.record_id,
            )
        if message.kind == COMMAND_EXECUTION_KIND and isinstance(
            message.payload, CommandExecutionRecord
        ):
            command = message.payload
            return _wrap(
                "command-execution",
                f"Command: {command.command}",
                command.output or "(no output)",
                message_id=message.record_id,
                body_format="ansi",
            )
        if message.kind == CONTEXT_BRANCH_SUMMARY_KIND and isinstance(
            message.payload, BranchContextSummary
        ):
            return _wrap(
                "branch-summary",
                "Branch Summary",
                message.payload.summary,
                message_id=message.record_id,
            )
        if message.kind == CONTEXT_COMPACTION_CHECKPOINT_KIND and isinstance(
            message.payload, ContextCompactionCheckpoint
        ):
            return _wrap(
                "compaction-summary",
                f"Compaction Summary: {message.payload.tokens_before} tokens",
                message.payload.summary,
                message_id=message.record_id,
            )
        if message.kind == APPLICATION_MESSAGE_KIND and isinstance(
            message.payload, ApplicationMessage
        ):
            return _render_message(
                message.payload,
                custom_renderer=custom_renderer,
                theme=theme,
                message_id=message.record_id,
            )
        return None
    if isinstance(message, UserMessage):
        body = (
            message.content
            if isinstance(message.content, str)
            else "\n".join(
                block.text for block in message.content if isinstance(block, TextPart)
            )
        )
        return _wrap("user", "User", body, message_id=message_id)
    if isinstance(message, AssistantMessage):
        parts: list[str] = []
        for block in message.content:
            if isinstance(block, TextPart):
                parts.append(block.text)
            elif isinstance(block, ToolCall):
                parts.append(
                    f"[tool call] {block.name} {json.dumps(block.arguments, sort_keys=True)}"
                )
        return _wrap("assistant", "Assistant", "\n".join(parts), message_id=message_id)
    if isinstance(message, ToolResultMessage):
        body = render_tool_result_text(
            message.content, message.details, preserve_ansi=True
        )
        return _wrap(
            "tool-result",
            f"Tool Result: {message.tool_name}",
            body,
            message_id=message_id,
            body_format="ansi",
        )
    if isinstance(message, ApplicationMessage):
        rendered = _render_custom_message_with_renderer(
            message,
            custom_renderer=custom_renderer,
            theme=theme,
            message_id=message_id,
        )
        if rendered is not None:
            return rendered
        body = (
            message.content
            if isinstance(message.content, str)
            else "\n".join(
                block.text for block in message.content if isinstance(block, TextPart)
            )
        )
        return _wrap(
            "custom", f"Custom: {message.custom_type}", body, message_id=message_id
        )
    return _wrap("unknown", "Unknown", repr(message), message_id=message_id)


def _render_custom_message_with_renderer(
    message: ApplicationMessage,
    *,
    custom_renderer: CustomMessageRenderer | None,
    theme: Mapping[str, str],
    message_id: str | None,
) -> str | None:
    if not callable(custom_renderer):
        return None
    renderer = custom_renderer(message.custom_type)
    if renderer is None:
        return None
    try:
        rendered = renderer(message, {"format": "html_export"}, dict(theme))
    except Exception as exc:
        return _wrap(
            "custom-render-error",
            f"Custom Renderer Error: {message.custom_type}",
            str(exc),
            message_id=message_id,
        )
    if isinstance(rendered, str):
        return _wrap_html(
            "custom rendered", rendered, message.custom_type, message_id=message_id
        )
    if isinstance(rendered, dict):
        html_output = rendered.get("html")
        if isinstance(html_output, str):
            css_class = rendered.get(
                "className", rendered.get("class_name", "custom rendered")
            )
            return _wrap_html(
                str(css_class), html_output, message.custom_type, message_id=message_id
            )
        text = rendered.get("text")
        title = rendered.get("title", f"Custom: {message.custom_type}")
        css_class = rendered.get(
            "className", rendered.get("class_name", "custom rendered")
        )
        if isinstance(text, str):
            return _wrap(str(css_class), str(title), text, message_id=message_id)
    return None


def _wrap(
    css_class: str,
    title: str,
    body: str,
    *,
    message_id: str | None = None,
    body_format: str = "markdown",
) -> str:
    search_text = " ".join((title, _searchable_body_text(body))).lower()
    resolved_message_id = message_id or _stable_message_id(css_class, title, body)
    body_html = (
        render_ansi_pre(body) if body_format == "ansi" else render_markdown(body)
    )
    return (
        f'<article id="{html.escape(resolved_message_id)}" class="message {css_class}" data-message-type="{html.escape(css_class)}" '
        f'data-search="{html.escape(search_text)}">'
        f"<h3>{html.escape(title)}</h3>"
        f"{body_html}"
        "</article>"
    )


def _wrap_html(
    css_class: str, body_html: str, custom_type: str, *, message_id: str | None = None
) -> str:
    search_text = html.escape(custom_type.lower())
    resolved_message_id = message_id or _stable_message_id(
        css_class, custom_type, body_html
    )
    return (
        f'<article id="{html.escape(resolved_message_id)}" class="message {html.escape(css_class)}" data-message-type="custom" '
        f'data-search="{search_text}">' + body_html + "</article>"
    )


def _stable_message_id(css_class: str, title: str, body: str) -> str:
    digest = hashlib.sha1(f"{css_class}\0{title}\0{body}".encode("utf-8")).hexdigest()[
        :12
    ]
    return f"message-{digest}"


def _searchable_body_text(body: str) -> str:
    return re.sub(r"```[A-Za-z0-9_+.#-]*[^\n]*\n(.*?)```", r"\1", body, flags=re.DOTALL)
