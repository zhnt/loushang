"""Optional Agent binding over the product-neutral conversation components."""

from __future__ import annotations

import base64
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any, Literal, Protocol, TextIO, TypeAlias

from loushang.agent.types import AgentToolResult, ImagePart
from loushang.harness.events import normalize_event_select
from loushang.harness.host.mode import ModeConfig
from loushang.harness.host.rpc import run_rpc_host
from loushang.harness.presentation import ToolDefinitionResolver, ToolRenderRuntime
from loushang.harness.session import (
    SUPPORTED_JSON_EVENT_VIEWS,
    project_runtime_event_to_json_views,
    project_session_event,
    should_emit_projected_event,
    should_emit_runtime_event_view,
)
from loushang.harness.tools.workspace.presentation import (
    render_tool_result_presentation,
)
from loushang.harness.transcript import (
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
from loushang.harnesstui.conversation.attachments import PromptImageAttachment
from loushang.harnesstui.conversation.history import (
    ConversationHistoryProjector,
    HistoryRecordDisposition,
    ToolMessageProjector,
    project_agent_message_payload,
    project_command_execution_payload,
    project_context_branch_summary_payload,
    project_context_compaction_payload,
)
from loushang.harnesstui.conversation.plain_mode import (
    PlainEventProjection,
    PlainHost,
    PlainWorkPort,
)
from loushang.harnesstui.conversation.plain_prompt_host import (
    PlainPlanTurnHook,
    PlainPromptHostPorts,
    PlainPromptPlanHostPorts,
    PreparedPlainPromptPlanRun,
    PreparedPlainPromptRun,
    dispose_runtime_or_session,
    last_assistant_failure_message,
    run_plain_prompt_host,
    run_plain_prompt_plan_host,
)
from loushang.harnesstui.conversation.plain_target import (
    PlainConversationProjectionPort,
    build_plain_conversation_projection,
)
from loushang.harnesstui.conversation.projection import (
    ConversationProjectionBinding,
    SessionConversationEventAdapter,
)
from loushang.harnesstui.conversation.runtime_view import StringQueueReader
from loushang.harnesstui.conversation.screen_target import (
    ScreenConversationProjectionPort,
    ScreenProjectionStatusCopy,
    StandardScreenProjectionStatusCopy,
    build_screen_conversation_projection,
)
from loushang.harnesstui.conversation.tool_transcript import (
    ToolCallSnapshot,
    ToolTranscriptBlock,
    ToolTranscriptProjectionBinding,
    build_mapping_tool_transcript_projection,
    tool_block_to_record,
)
from loushang.tui.transcript import DisplayRecord, ToolExecutionRecord

AgentToolTranscriptProjection: TypeAlias = ToolTranscriptProjectionBinding[
    Mapping[str, Any], object
]


def agent_image_parts_from_prompt_attachments(
    attachments: tuple[PromptImageAttachment, ...],
) -> tuple[ImagePart, ...] | None:
    """Convert neutral TUI attachments at the standard Agent boundary."""

    if not attachments:
        return None
    return tuple(
        ImagePart(
            type="image",
            data=base64.b64encode(attachment.bytes).decode("ascii"),
            mime_type=attachment.mime_type,
        )
        for attachment in attachments
    )


class AgentPlainPromptRenderer(PlainConversationProjectionPort, Protocol):
    """Renderer effects required by the standard Agent prompt binding."""

    def render_worked(self, elapsed_seconds: float) -> None: ...


class AgentPlainPromptSession(Protocol):
    """Session effects required by the standard Agent prompt binding."""

    def subscribe(
        self,
        listener: Callable[[dict[str, Any]], None],
    ) -> Callable[[], None]: ...


STANDARD_AGENT_HISTORY_DISPOSITIONS: dict[str, HistoryRecordDisposition] = {
    AGENT_MESSAGE_KIND: "render",
    THINKING_SELECTION_KIND: "state-only",
    MODEL_SELECTION_KIND: "state-only",
    COMMAND_EXECUTION_KIND: "render",
    CONTEXT_COMPACTION_CHECKPOINT_KIND: "render",
    CONTEXT_BRANCH_SUMMARY_KIND: "render",
    APPLICATION_MESSAGE_KIND: "render",
    EXTENSION_DATA_KIND: "hidden",
    RECORD_ANNOTATION_PATCH_KIND: "metadata-only",
    CONVERSATION_METADATA_PATCH_KIND: "metadata-only",
    MODEL_CALL_OUTCOME_KIND: "hidden",
    MODEL_INPUT_COMPONENT_KIND: "hidden",
    MODEL_INPUT_PREPARED_KIND: "hidden",
}
if set(STANDARD_AGENT_HISTORY_DISPOSITIONS) != set(STANDARD_AGENT_TRANSCRIPT_KINDS):
    raise RuntimeError("Agent history dispositions must cover every standard kind")


def build_agent_tool_transcript_projection(
    tool_definition_resolver: ToolDefinitionResolver | None = None,
    render_runtime: ToolRenderRuntime | None = None,
    max_body_lines: int = 8,
) -> AgentToolTranscriptProjection:
    """Bind standard Agent tool results to the workspace transcript policy."""

    resolved_runtime = render_runtime or ToolRenderRuntime()
    render_event = (
        None
        if tool_definition_resolver is None
        else lambda event, expanded: _render_agent_tool_event(
            event,
            expanded=expanded,
            tool_definition_resolver=tool_definition_resolver,
            render_runtime=resolved_runtime,
        )
    )
    return build_mapping_tool_transcript_projection(
        result_text=_agent_result_text,
        result_details=_agent_result_details,
        result_terminated=lambda result: (
            isinstance(result, AgentToolResult) and result.terminate
        ),
        error_summary=_agent_error_summary,
        message_event=_agent_tool_result_message_event,
        render_event_text=render_event,
        max_body_lines=max_body_lines,
    )


def agent_tool_block_to_record(
    block: ToolTranscriptBlock,
    *,
    elapsed_seconds: float = 0.0,
) -> ToolExecutionRecord:
    """Apply the standard Agent workspace command-label policy."""

    if block.command is None and block.verb in {"Ran", "Tested"}:
        block = replace(block, command=block.title)
    return tool_block_to_record(block, elapsed_seconds=elapsed_seconds)


def project_agent_conversation_history(
    items: Iterable[object],
    *,
    tool_result_projector: ToolMessageProjector,
) -> tuple[DisplayRecord, ...]:
    """Project a standard Agent transcript branch into display records."""

    message_projector = partial(
        project_agent_message_payload,
        tool_result_projector=tool_result_projector,
    )
    return ConversationHistoryProjector(
        dispositions=STANDARD_AGENT_HISTORY_DISPOSITIONS,
        payload_projectors={
            AGENT_MESSAGE_KIND: message_projector,
            COMMAND_EXECUTION_KIND: project_command_execution_payload,
            CONTEXT_COMPACTION_CHECKPOINT_KIND: project_context_compaction_payload,
            CONTEXT_BRANCH_SUMMARY_KIND: project_context_branch_summary_payload,
            APPLICATION_MESSAGE_KIND: message_projector,
        },
        fallback_projector=message_projector,
    ).project_items(items)


def agent_session_history_records(
    branch_items: Iterable[object],
    *,
    tool_definition_resolver: ToolDefinitionResolver | None = None,
    max_tool_body_lines: int = 8,
) -> tuple[DisplayRecord, ...]:
    """Project a materialized Agent transcript branch for terminal history."""

    transcript_items = tuple(branch_items)
    if not transcript_items:
        return ()
    tool_projector = build_agent_tool_transcript_projection(
        tool_definition_resolver=tool_definition_resolver,
        max_body_lines=max_tool_body_lines,
    )
    return project_agent_conversation_history(
        transcript_items,
        tool_result_projector=lambda message: agent_tool_block_to_record(
            tool_projector.project_tool_result_message(message)
        ),
    )


async def load_agent_session_history_records(
    session_file: str | Path,
    *,
    load_session: Callable[[Path], Awaitable[object]],
    tool_definition_resolver: ToolDefinitionResolver | None = None,
) -> tuple[DisplayRecord, ...]:
    """Load a Product transcript session and project its active Agent branch."""

    session = await load_session(Path(session_file).expanduser().resolve())
    get_branch = getattr(session, "get_branch", None)
    if not callable(get_branch):
        raise TypeError("loaded Agent transcript session must expose get_branch()")
    return agent_session_history_records(
        get_branch(),
        tool_definition_resolver=tool_definition_resolver,
    )


def build_agent_plain_conversation_projection(
    renderer: PlainConversationProjectionPort,
    tool_definition_resolver: ToolDefinitionResolver | None = None,
    max_tool_body_lines: int = 8,
    tool_calls: dict[str, ToolCallSnapshot] | None = None,
    rendered_tool_results: set[str] | None = None,
    rendered_assistant_errors: set[int | str] | None = None,
    last_error_message: str | None = None,
    render_user_messages: bool = True,
) -> ConversationProjectionBinding[dict[str, Any]]:
    """Build the standard Agent event adapter for a plain conversation."""

    tool_projection = build_agent_tool_transcript_projection(
        tool_definition_resolver=tool_definition_resolver,
        max_body_lines=max_tool_body_lines,
    )
    return build_plain_conversation_projection(
        renderer,
        tool_projector=tool_projection.neutral_projector,
        event_handler_factory=lambda projection: (
            SessionConversationEventAdapter(
                projection,
                tool_projection,
                recover_tool_updates=False,
                require_assistant_message_for_delta=False,
                project_run_starts=False,
                project_queue_updates=False,
                project_user_messages=render_user_messages,
                project_assistant_error_text=False,
                project_compaction_details=False,
            ).handle
        ),
        tool_calls=tool_calls,
        rendered_tool_results=rendered_tool_results,
        rendered_assistant_errors=rendered_assistant_errors,
        last_error_message=last_error_message,
    )


def build_agent_plain_event_projection() -> PlainEventProjection:
    """Bind the standard Agent JSON views to the shared plain host."""

    return PlainEventProjection(
        supported_views=SUPPORTED_JSON_EVENT_VIEWS,
        normalize_select=normalize_event_select,
        project_session_event=project_session_event,
        should_emit_projected_event=should_emit_projected_event,
        project_runtime_event_to_json_views=project_runtime_event_to_json_views,
        should_emit_runtime_event_view=should_emit_runtime_event_view,
    )


class AgentPlainHost(PlainHost):
    """Standard Agent event profile over the shared plain conversation host."""

    def __init__(
        self,
        *,
        runtime: object,
        session: object,
        stdout: TextIO,
        stderr: TextIO | None = None,
        output_mode: Literal["text", "json"] = "text",
        event_view: str = "full",
        event_select: Sequence[str] | str | None = None,
        render_tool_events: bool = False,
        work_event_log: object | None = None,
        work_port: PlainWorkPort | None = None,
        method_id: str | None = None,
        plan_id: str | None = None,
        step_id: str | None = None,
        step_index: int | None = None,
        step_title: str | None = None,
        planned_constraint: Mapping[str, object] | None = None,
        audit_policy: Mapping[str, object] | None = None,
        plan_facts: Mapping[str, object] | None = None,
        step_facts: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(
            runtime=runtime,
            session=session,
            stdout=stdout,
            stderr=stderr,
            output_mode=output_mode,
            event_view=event_view,
            event_select=event_select,
            render_tool_events=render_tool_events,
            work_event_log=work_event_log,
            work_port=work_port,
            event_projection=build_agent_plain_event_projection(),
            method_id=method_id,
            plan_id=plan_id,
            step_id=step_id,
            step_index=step_index,
            step_title=step_title,
            planned_constraint=planned_constraint,
            audit_policy=audit_policy,
            plan_facts=plan_facts,
            step_facts=step_facts,
        )


async def run_agent_plain_mode(
    *,
    runtime: object,
    session: object,
    user_input: str,
    stdout: TextIO,
    stderr: TextIO | None = None,
    images: list[object] | None = None,
    follow_up_messages: Sequence[str] = (),
    output_mode: Literal["text", "json"] = "text",
    event_view: str = "full",
    event_select: Sequence[str] | str | None = None,
    render_tool_events: bool = False,
    work_event_log: object | None = None,
    work_port: PlainWorkPort | None = None,
    method_id: str | None = None,
    plan_id: str | None = None,
    step_id: str | None = None,
    step_index: int | None = None,
    step_title: str | None = None,
    planned_constraint: Mapping[str, object] | None = None,
    audit_policy: Mapping[str, object] | None = None,
    plan_facts: Mapping[str, object] | None = None,
    step_facts: Mapping[str, object] | None = None,
    dispose: bool = True,
) -> int:
    """Run one standard Agent turn through the existing plain host."""

    host = AgentPlainHost(
        runtime=runtime,
        session=session,
        stdout=stdout,
        stderr=stderr,
        output_mode=output_mode,
        event_view=event_view,
        event_select=event_select,
        render_tool_events=render_tool_events,
        work_event_log=work_event_log,
        work_port=work_port,
        method_id=method_id,
        plan_id=plan_id,
        step_id=step_id,
        step_index=step_index,
        step_title=step_title,
        planned_constraint=planned_constraint,
        audit_policy=audit_policy,
        plan_facts=plan_facts,
        step_facts=step_facts,
    )
    return await host.run_once(
        user_input,
        images=images,
        follow_up_messages=follow_up_messages,
        dispose=dispose,
    )


async def run_agent_plain_plan_mode(
    *,
    runtime: object,
    session: object,
    turns: Sequence[object],
    stdout: TextIO,
    work_event_log: object,
    work_port: PlainWorkPort,
    stderr: TextIO | None = None,
    output_mode: Literal["text", "json"] = "text",
    event_view: str = "full",
    event_select: Sequence[str] | str | None = None,
    render_tool_events: bool = False,
    dispose: bool = True,
) -> int:
    """Run one standard Agent plan through the existing plain host."""

    host = AgentPlainHost(
        runtime=runtime,
        session=session,
        stdout=stdout,
        stderr=stderr,
        output_mode=output_mode,
        event_view=event_view,
        event_select=event_select,
        render_tool_events=render_tool_events,
        work_event_log=work_event_log,
        work_port=work_port,
    )
    return await host.run_plan(turns, dispose=dispose)


async def run_agent_mode(
    config: ModeConfig,
    *,
    runtime: object,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO | None = None,
    session: object | None = None,
    user_input: str | None = None,
    images: list[object] | None = None,
    follow_up_messages: Sequence[str] = (),
    work_event_log: object | None = None,
    work_port: PlainWorkPort | None = None,
    method_id: str | None = None,
    plan_id: str | None = None,
    step_id: str | None = None,
    step_index: int | None = None,
    step_title: str | None = None,
    planned_constraint: Mapping[str, object] | None = None,
    audit_policy: Mapping[str, object] | None = None,
    plan_facts: Mapping[str, object] | None = None,
    step_facts: Mapping[str, object] | None = None,
    dispose: bool = True,
) -> int:
    """Dispatch the standard Agent RPC or plain host without Product facades."""

    if config.mode == "rpc":
        return await run_rpc_host(
            runtime=runtime,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            event_view=config.event_view,
            event_select=config.event_select,
            render_tool_events=config.render_tool_events,
        )
    if session is None:
        raise ValueError(f"{config.mode} mode requires a session")
    if user_input is None:
        raise ValueError("Print mode requires a user input")
    return await run_agent_plain_mode(
        runtime=runtime,
        session=session,
        user_input=user_input,
        stdout=stdout,
        stderr=stderr,
        images=images,
        follow_up_messages=follow_up_messages,
        output_mode="text" if config.mode == "print" else config.mode,
        event_view=config.event_view,
        event_select=config.event_select,
        render_tool_events=config.render_tool_events,
        work_event_log=work_event_log,
        work_port=work_port,
        method_id=method_id,
        plan_id=plan_id,
        step_id=step_id,
        step_index=step_index,
        step_title=step_title,
        planned_constraint=planned_constraint,
        audit_policy=audit_policy,
        plan_facts=plan_facts,
        step_facts=step_facts,
        dispose=dispose,
    )


async def run_agent_plain_prompt(
    *,
    runtime: object,
    session: AgentPlainPromptSession,
    prompts: Sequence[str],
    renderer: AgentPlainPromptRenderer,
    prepare: Callable[[], Awaitable[object]],
    submit: Callable[[str, int, int], Awaitable[None]],
    stderr: TextIO,
    verbose: bool = False,
    dispose: bool = True,
) -> int:
    """Run standard Agent prompt turns through the shared plain host."""

    event_projection = build_agent_plain_conversation_projection(
        renderer,
        render_user_messages=False,
    )

    def resolve_failure(previous_error: str | None) -> str | None:
        assistant_failure = last_assistant_failure_message(session)
        if (
            assistant_failure is None
            and event_projection.last_error_message != previous_error
        ):
            return event_projection.last_error_message
        return assistant_failure

    return await run_plain_prompt_host(
        PreparedPlainPromptRun(
            prompts=tuple(prompts),
            ports=PlainPromptHostPorts[str | None](
                prepare=prepare,
                subscribe=lambda: session.subscribe(event_projection.handle),
                submit=submit,
                capture_failure_state=lambda: event_projection.last_error_message,
                resolve_failure=resolve_failure,
                render_user=renderer.render_user,
                render_worked=renderer.render_worked,
                render_error=renderer.render_error,
                dispose=lambda: dispose_runtime_or_session(runtime, session),
            ),
            stderr=stderr,
            verbose=verbose,
            dispose=dispose,
        )
    )


async def run_agent_plain_prompt_plan(
    *,
    runtime: object,
    session: AgentPlainPromptSession,
    turns: Sequence[object],
    renderer: AgentPlainPromptRenderer,
    prepare: Callable[[], Awaitable[object]],
    submit_plan: Callable[
        [
            Sequence[object],
            PlainPlanTurnHook[object],
            PlainPlanTurnHook[object],
        ],
        Awaitable[None],
    ],
    turn_text: Callable[[object], str],
    stderr: TextIO,
    verbose: bool = False,
    dispose: bool = True,
) -> int:
    """Run one Work-owned Agent prompt plan through the shared plain host."""

    event_projection = build_agent_plain_conversation_projection(
        renderer,
        render_user_messages=False,
    )

    def resolve_failure(previous_error: str | None) -> str | None:
        assistant_failure = last_assistant_failure_message(session)
        if (
            assistant_failure is None
            and event_projection.last_error_message != previous_error
        ):
            return event_projection.last_error_message
        return assistant_failure

    return await run_plain_prompt_plan_host(
        PreparedPlainPromptPlanRun(
            turns=tuple(turns),
            ports=PlainPromptPlanHostPorts[object, str | None](
                prepare=prepare,
                subscribe=lambda: session.subscribe(event_projection.handle),
                submit_plan=submit_plan,
                turn_text=turn_text,
                capture_failure_state=lambda: event_projection.last_error_message,
                resolve_failure=resolve_failure,
                render_user=renderer.render_user,
                render_worked=renderer.render_worked,
                render_error=renderer.render_error,
                dispose=lambda: dispose_runtime_or_session(runtime, session),
            ),
            stderr=stderr,
            verbose=verbose,
            dispose=dispose,
        )
    )


def build_agent_screen_conversation_projection(
    app: ScreenConversationProjectionPort,
    tool_definition_resolver: ToolDefinitionResolver | None = None,
    max_tool_body_lines: int = 8,
    read_pending_steers: StringQueueReader = tuple,
    read_pending_followups: StringQueueReader = tuple,
    on_session_info_changed: Callable[[], None] | None = None,
    status_copy: ScreenProjectionStatusCopy | None = None,
    now: Callable[[], float] = time.monotonic,
) -> ConversationProjectionBinding[dict[str, Any]]:
    """Build the standard Agent event adapter for a screen conversation."""

    tool_projection = build_agent_tool_transcript_projection(
        tool_definition_resolver=tool_definition_resolver,
        max_body_lines=max_tool_body_lines,
    )
    return build_screen_conversation_projection(
        app,
        tool_projector=tool_projection.neutral_projector,
        tool_title_resolver=_standard_tool_title,
        tool_record_projector=agent_tool_block_to_record,
        status_copy=status_copy or StandardScreenProjectionStatusCopy(),
        event_handler_factory=lambda projection: (
            SessionConversationEventAdapter(
                projection,
                tool_projection,
                read_pending_steers=read_pending_steers,
                read_pending_followups=read_pending_followups,
                on_session_info_changed=on_session_info_changed,
                project_tool_result_messages=False,
            ).handle
        ),
        now=now,
    )


def _agent_tool_result_message_event(message: object) -> Mapping[str, Any]:
    tool_name = str(getattr(message, "tool_name", "tool"))
    tool_call_id = getattr(message, "tool_call_id", None)
    return {
        "type": "tool_execution_end",
        "tool_call_id": (
            tool_call_id
            if isinstance(tool_call_id, str) and tool_call_id
            else tool_name
        ),
        "tool_name": tool_name,
        "result": AgentToolResult(
            content=getattr(message, "content", None) or [],
            details=getattr(message, "details", None),
            terminate=bool(getattr(message, "terminate", False)),
        ),
        "is_error": bool(getattr(message, "is_error", False)),
    }


def _agent_result_text(result: object, max_lines: int) -> str:
    if not isinstance(result, AgentToolResult):
        return ""
    return render_tool_result_presentation(
        result.content,
        _agent_result_details(result),
        max_collapsed_lines=max_lines,
    ).collapsed


def _agent_result_details(result: object) -> Mapping[str, Any]:
    if not isinstance(result, AgentToolResult):
        return {}
    try:
        details = result.transcript_details()
    except Exception:
        return {}
    return details if isinstance(details, Mapping) else {}


def _agent_error_summary(result: object) -> str | None:
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


def _render_agent_tool_event(
    event: Mapping[str, Any],
    *,
    expanded: bool,
    tool_definition_resolver: ToolDefinitionResolver,
    render_runtime: ToolRenderRuntime,
) -> str | None:
    try:
        rendered = render_runtime.render_event(
            event,
            tool_definition_resolver,
            expanded=expanded,
        )
    except Exception:
        return None
    if isinstance(rendered, str):
        return rendered
    if isinstance(rendered, Mapping):
        plain = rendered.get("plain_text")
        if isinstance(plain, str):
            return plain
        text = rendered.get("text")
        if isinstance(text, str):
            return text
    return None


def _standard_tool_title(snapshot: ToolCallSnapshot) -> str:
    if snapshot.rendered_call_text:
        return snapshot.rendered_call_text.splitlines()[0].strip()
    return snapshot.tool_name


__all__ = [
    "AgentPlainHost",
    "AgentToolTranscriptProjection",
    "AgentPlainPromptRenderer",
    "AgentPlainPromptSession",
    "STANDARD_AGENT_HISTORY_DISPOSITIONS",
    "agent_image_parts_from_prompt_attachments",
    "agent_tool_block_to_record",
    "build_agent_plain_conversation_projection",
    "build_agent_plain_event_projection",
    "build_agent_screen_conversation_projection",
    "build_agent_tool_transcript_projection",
    "project_agent_conversation_history",
    "run_agent_plain_prompt",
    "run_agent_plain_prompt_plan",
    "run_agent_plain_mode",
    "run_agent_plain_plan_mode",
    "run_agent_mode",
]
