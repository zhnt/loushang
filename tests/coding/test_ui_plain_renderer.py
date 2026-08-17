from __future__ import annotations

from io import StringIO
from os import terminal_size
from typing import Literal

from loushang.agent import AgentToolResult
from loushang.ai import (
    AssistantMessage,
    TextPart,
    ToolResultMessage,
    Usage,
    UserMessage,
)
from loushang.harness.tools.execution import direct_execution


def _usage() -> Usage:
    return Usage(
        input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
    )


def _assistant(
    text: str = "",
    *,
    stop_reason: Literal["stop", "length", "toolUse", "error", "aborted"] = "stop",
    error_message: str | None = None,
) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api="anthropic-messages",
        provider="moonshot",
        model="kimi-for-coding",
        response_id=None,
        usage=_usage(),
        stop_reason=stop_reason,
        error_message=error_message,
        timestamp=0.0,
    )


def test_plain_renderer_uses_shared_core_with_compatible_constructor() -> None:
    from inspect import signature

    from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer
    from loushang.harnesstui.plain.renderer import PlainConversationRenderer

    assert issubclass(PlainCodingUiRenderer, PlainConversationRenderer)
    assert tuple(signature(PlainCodingUiRenderer).parameters) == (
        "stdout",
        "stderr",
        "max_payload_chars",
        "verbose",
        "use_transcript_view",
        "transcript_theme",
        "transcript_capabilities",
        "code_highlighter",
        "transcript_buffer",
        "_assistant_deltas",
    )


def test_plain_renderer_prints_header_and_user_message() -> None:
    from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer

    stdout = StringIO()
    renderer = PlainCodingUiRenderer(stdout=stdout)

    renderer.render_header(
        project_label="loushang",
        cwd="/repo",
        branch="main",
        session_label="254d6156",
        model_label="moonshot/kimi",
    )
    renderer.render_user("hello")

    assert stdout.getvalue() == (
        "Loushang TUI\n"
        "model=moonshot/kimi | cwd=/repo | branch=main | session=254d6156\n"
        "\n"
        "› hello\n"
    )


def test_event_renderer_buffers_assistant_deltas_until_final_block() -> None:
    from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_plain_conversation_projection,
    )

    stdout = StringIO()
    event_renderer = build_agent_plain_conversation_projection(
        PlainCodingUiRenderer(stdout=stdout)
    )

    event_renderer.handle({"type": "message_start", "message": _assistant("")})
    event_renderer.handle(
        {
            "type": "message_update",
            "message": _assistant("hi"),
            "assistant_message_event": {
                "type": "text_delta",
                "content_index": 0,
                "delta": "hi",
            },
        }
    )
    assert stdout.getvalue() == ""

    event_renderer.handle(
        {
            "type": "message_update",
            "message": _assistant("hi there"),
            "assistant_message_event": {
                "type": "text_delta",
                "content_index": 0,
                "delta": " there",
            },
        }
    )
    event_renderer.handle({"type": "message_end", "message": _assistant("hi there")})

    assert stdout.getvalue() == "• hi there\n"


def test_event_renderer_accepts_legacy_delta_without_message() -> None:
    from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_plain_conversation_projection,
    )

    stdout = StringIO()
    event_renderer = build_agent_plain_conversation_projection(
        PlainCodingUiRenderer(stdout=stdout)
    )

    event_renderer.handle({"type": "message_start", "message": _assistant("")})
    event_renderer.handle(
        {
            "type": "message_update",
            "assistant_message_event": {"type": "text_delta", "delta": "legacy"},
        }
    )
    event_renderer.handle({"type": "message_end", "message": _assistant("legacy")})

    assert stdout.getvalue() == "• legacy\n"


def test_plain_projection_builder_preserves_injected_state() -> None:
    from inspect import signature

    from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_plain_conversation_projection,
    )
    from loushang.harnesstui.conversation.tool_transcript import ToolCallSnapshot

    assert tuple(signature(build_agent_plain_conversation_projection).parameters) == (
        "renderer",
        "tool_definition_resolver",
        "max_tool_body_lines",
        "tool_calls",
        "rendered_tool_results",
        "rendered_assistant_errors",
        "last_error_message",
        "render_user_messages",
    )

    tool_calls = {"tc-pending": ToolCallSnapshot(tool_name="read")}
    rendered_tool_results = {"tc-done"}
    rendered_assistant_errors = {123}
    event_renderer = build_agent_plain_conversation_projection(
        PlainCodingUiRenderer(stdout=StringIO()),
        None,
        4,
        tool_calls,
        rendered_tool_results,
        rendered_assistant_errors,
        "old error",
        False,
    )

    assert event_renderer.tool_calls is tool_calls
    assert event_renderer.rendered_tool_results is rendered_tool_results
    assert event_renderer.rendered_assistant_errors is rendered_assistant_errors
    assert event_renderer.last_error_message == "old error"
    event_renderer.last_error_message = "new error"
    assert event_renderer.last_error_message == "new error"

    event_renderer.handle({"type": "agent_start"})
    event_renderer.handle({"type": "queue_update"})

    assert event_renderer.tool_calls is tool_calls
    assert event_renderer.tool_calls == {
        "tc-pending": ToolCallSnapshot(tool_name="read")
    }


def test_event_renderer_renders_completed_assistant_markdown_without_raw_markers() -> (
    None
):
    from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_plain_conversation_projection,
    )

    stdout = StringIO()
    event_renderer = build_agent_plain_conversation_projection(
        PlainCodingUiRenderer(stdout=stdout)
    )

    event_renderer.handle({"type": "message_start", "message": _assistant("")})
    event_renderer.handle(
        {
            "type": "message_end",
            "message": _assistant("**Important**\n\n- first\n- second"),
        }
    )

    output = stdout.getvalue()
    assert "• Important" in output
    assert "first" in output
    assert "second" in output
    assert "**" not in output


def test_plain_renderer_can_render_generic_terminal_blocks() -> None:
    from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer
    from loushang.tui.render import MarkdownBlock, RuleBlock, TextBlock

    stdout = StringIO()
    renderer = PlainCodingUiRenderer(stdout=stdout)

    renderer.render_terminal_blocks(
        [
            RuleBlock("Summary", char="-"),
            MarkdownBlock("**Done**"),
            TextBlock("Plain footer"),
        ],
        width=16,
    )

    assert stdout.getvalue() == "- Summary -----\n\nDone\n\nPlain footer\n"


def test_event_renderer_prints_assistant_error_from_message_end() -> None:
    from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_plain_conversation_projection,
    )

    stdout = StringIO()
    event_renderer = build_agent_plain_conversation_projection(
        PlainCodingUiRenderer(stdout=stdout)
    )

    event_renderer.handle(
        {
            "type": "message_end",
            "message": _assistant(
                "", stop_reason="error", error_message="provider failure"
            ),
        }
    )

    assert stdout.getvalue() == "■ Error: provider failure\n"


def test_event_renderer_prints_assistant_error_from_agent_end() -> None:
    from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_plain_conversation_projection,
    )

    stdout = StringIO()
    event_renderer = build_agent_plain_conversation_projection(
        PlainCodingUiRenderer(stdout=stdout)
    )

    event_renderer.handle(
        {
            "type": "agent_end",
            "messages": [
                _assistant("", stop_reason="error", error_message="provider failure")
            ],
        }
    )

    assert stdout.getvalue() == "■ Error: provider failure\n"


def test_event_renderer_deduplicates_assistant_error_and_keeps_last_error() -> None:
    from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_plain_conversation_projection,
    )

    stdout = StringIO()
    event_renderer = build_agent_plain_conversation_projection(
        PlainCodingUiRenderer(stdout=stdout)
    )
    message = _assistant(
        "partial answer",
        stop_reason="error",
        error_message="provider failure",
    )

    event_renderer.handle({"type": "message_start", "message": message})
    event_renderer.handle({"type": "message_end", "message": message})
    event_renderer.handle({"type": "agent_end", "messages": [message]})

    assert stdout.getvalue() == "■ Error: provider failure\n"
    assert event_renderer.last_error_message == "provider failure"


def test_event_renderer_suppresses_intentional_abort_without_committing_draft() -> None:
    from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_plain_conversation_projection,
    )

    stdout = StringIO()
    event_renderer = build_agent_plain_conversation_projection(
        PlainCodingUiRenderer(stdout=stdout)
    )
    message = _assistant(
        "partial answer",
        stop_reason="aborted",
        error_message="Request aborted by user",
    )

    event_renderer.handle({"type": "message_start", "message": message})
    event_renderer.handle({"type": "message_end", "message": message})

    assert stdout.getvalue() == ""
    assert event_renderer.last_error_message == "Request aborted by user"


def test_event_renderer_prints_user_message_start() -> None:
    from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_plain_conversation_projection,
    )

    stdout = StringIO()
    event_renderer = build_agent_plain_conversation_projection(
        PlainCodingUiRenderer(stdout=stdout)
    )

    event_renderer.handle(
        {
            "type": "message_start",
            "message": UserMessage(
                role="user",
                content=[TextPart(type="text", text="hello")],
                timestamp=0.0,
            ),
        }
    )

    assert stdout.getvalue() == "› hello\n"


def test_event_renderer_can_suppress_user_messages() -> None:
    from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_plain_conversation_projection,
    )

    stdout = StringIO()
    event_renderer = build_agent_plain_conversation_projection(
        PlainCodingUiRenderer(stdout=stdout),
        render_user_messages=False,
    )

    event_renderer.handle(
        {
            "type": "message_start",
            "message": UserMessage(
                role="user",
                content=[TextPart(type="text", text="hidden")],
                timestamp=0.0,
            ),
        }
    )

    assert stdout.getvalue() == ""


def test_event_renderer_aggregates_tool_lifecycle() -> None:
    from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_plain_conversation_projection,
    )

    stdout = StringIO()
    event_renderer = build_agent_plain_conversation_projection(
        PlainCodingUiRenderer(stdout=stdout)
    )
    result: AgentToolResult[dict[str, object]] = AgentToolResult(
        content=[TextPart(type="text", text="ok")], details={}
    )

    event_renderer.handle(
        {
            "type": "tool_execution_start",
            "tool_call_id": "tc1",
            "tool_name": "read",
            "args": {"path": "README.md"},
        }
    )
    event_renderer.handle(
        {
            "type": "tool_execution_update",
            "tool_call_id": "tc1",
            "tool_name": "read",
            "partial_result": result,
        }
    )
    assert stdout.getvalue() == ""

    event_renderer.handle(
        {
            "type": "tool_execution_end",
            "tool_call_id": "tc1",
            "tool_name": "read",
            "result": result,
            "is_error": False,
        }
    )

    assert stdout.getvalue() == "• Explored read README.md\n"


def test_event_renderer_does_not_duplicate_tool_result_message_after_tool_end() -> None:
    from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_plain_conversation_projection,
    )

    stdout = StringIO()
    event_renderer = build_agent_plain_conversation_projection(
        PlainCodingUiRenderer(stdout=stdout)
    )
    result: AgentToolResult[dict[str, object]] = AgentToolResult(
        content=[TextPart(type="text", text="ok")], details={}
    )
    tool_result = ToolResultMessage(
        role="toolResult",
        tool_call_id="tc1",
        tool_name="read",
        content=result.content,
        details=result.details,
        is_error=False,
        timestamp=0.0,
    )

    event_renderer.handle(
        {
            "type": "tool_execution_start",
            "tool_call_id": "tc1",
            "tool_name": "read",
            "args": {"path": "README.md"},
        }
    )
    event_renderer.handle(
        {
            "type": "tool_execution_end",
            "tool_call_id": "tc1",
            "tool_name": "read",
            "result": result,
            "is_error": False,
        }
    )
    event_renderer.handle({"type": "message_end", "message": tool_result})

    assert stdout.getvalue() == "• Explored read README.md\n"


def test_event_renderer_renders_tool_block_with_bounded_result_preview() -> None:
    from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer
    from loushang.harness.presentation import (
        ToolRenderContext,
        ToolRenderResultOptions,
    )
    from loushang.harness.tools.workspace import ToolDefinition
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_plain_conversation_projection,
    )

    async def execute(*args, **kwargs):  # pragma: no cover - renderer-only test helper
        raise AssertionError("not used")

    def render_call(args: object, theme: object, context: ToolRenderContext) -> str:
        return "bash printf lines"

    def render_result(
        result: AgentToolResult[object],
        options: ToolRenderResultOptions,
        theme: object,
        context: ToolRenderContext,
    ) -> str:
        return "\n".join([f"line {index}" for index in range(1, 8)])

    definition = ToolDefinition(
        name="bash",
        label="Bash",
        description="Run a command",
        parameters={},
        execution=direct_execution(execute),
        render_call=render_call,
        render_result=render_result,
    )
    stdout = StringIO()
    event_renderer = build_agent_plain_conversation_projection(
        PlainCodingUiRenderer(stdout=stdout),
        tool_definition_resolver=lambda name: definition if name == "bash" else None,
        max_tool_body_lines=3,
    )
    result: AgentToolResult[dict[str, object]] = AgentToolResult(
        content=[TextPart(type="text", text="ignored")], details={}
    )

    event_renderer.handle(
        {
            "type": "tool_execution_start",
            "tool_call_id": "tc1",
            "tool_name": "bash",
            "args": {"command": "printf lines"},
        }
    )
    event_renderer.handle(
        {
            "type": "tool_execution_end",
            "tool_call_id": "tc1",
            "tool_name": "bash",
            "result": result,
            "is_error": False,
        }
    )

    assert stdout.getvalue() == (
        "• Ran bash printf lines\n"
        "  ... (4 earlier lines)\n"
        "  line 5\n"
        "  line 6\n"
        "  line 7\n"
    )


def test_event_renderer_includes_failed_tool_error_summary() -> None:
    from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_plain_conversation_projection,
    )

    stdout = StringIO()
    event_renderer = build_agent_plain_conversation_projection(
        PlainCodingUiRenderer(stdout=stdout)
    )
    result: AgentToolResult[dict[str, object]] = AgentToolResult(
        content=[
            TextPart(
                type="text",
                text='Validation failed for tool "write":\n  - path: is required',
            )
        ],
        details={},
    )

    event_renderer.handle(
        {
            "type": "tool_execution_start",
            "tool_call_id": "tc1",
            "tool_name": "write",
            "args": {},
        }
    )
    event_renderer.handle(
        {
            "type": "tool_execution_end",
            "tool_call_id": "tc1",
            "tool_name": "write",
            "result": result,
            "is_error": True,
        }
    )

    assert (
        stdout.getvalue()
        == '• Edited write failed: Validation failed for tool "write":\n'
    )


def test_plain_renderer_prints_worked_divider_to_terminal_width(monkeypatch) -> None:
    from loushang.coding.presentation.tui import plain as renderer_module
    from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer

    monkeypatch.setattr(
        renderer_module.shutil,
        "get_terminal_size",
        lambda fallback: terminal_size((24, 24)),
    )
    stdout = StringIO()
    renderer = PlainCodingUiRenderer(stdout=stdout)

    renderer.render_worked(1.25)

    assert stdout.getvalue() == "\n─ Worked for 1.2s ──────\n\n"


def test_plain_renderer_prints_interruption_and_concise_error_without_traceback() -> (
    None
):
    from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer

    stdout = StringIO()
    stderr = StringIO()
    renderer = PlainCodingUiRenderer(stdout=stdout, stderr=stderr, verbose=False)

    renderer.render_interruption()
    renderer.render_error("boom")

    assert stdout.getvalue() == (
        "■ Conversation interrupted - tell the model what to do differently. "
        "Something went wrong? Hit `/feedback` to report the issue.\n"
        "■ Error: boom\n"
    )
    assert stderr.getvalue() == ""


def test_event_renderer_prints_retry_status() -> None:
    from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer
    from loushang.harnesstui.conversation.agent_binding import (
        build_agent_plain_conversation_projection,
    )

    stdout = StringIO()
    event_renderer = build_agent_plain_conversation_projection(
        PlainCodingUiRenderer(stdout=stdout)
    )

    event_renderer.handle(
        {
            "type": "auto_retry_start",
            "attempt": 2,
            "max_attempts": 3,
            "delay_ms": 1000,
            "error_message": "rate limit",
        }
    )

    assert stdout.getvalue() == "[retry] attempt 2/3 in 1000ms: rate limit\n"


def test_plain_renderer_can_project_assistant_markdown_through_transcript_view() -> (
    None
):
    from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer
    from loushang.tui.theme import ThemeResolver

    stdout = StringIO()
    renderer = PlainCodingUiRenderer(
        stdout=stdout,
        use_transcript_view=True,
        transcript_theme=ThemeResolver(
            defaults={"markdown.heading.level2": {"bold": True}}
        ),
    )

    renderer.render_assistant("## Result\n\nUse `pytest`.")

    output = stdout.getvalue()
    assert "• Result" in output
    assert "pytest" in output
    assert "##" not in output


def test_plain_renderer_can_project_tool_blocks_through_transcript_view() -> None:
    from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer
    from loushang.harnesstui.conversation.tool_transcript import ToolTranscriptBlock

    stdout = StringIO()
    renderer = PlainCodingUiRenderer(stdout=stdout, use_transcript_view=True)

    renderer.render_tool_block(
        ToolTranscriptBlock(
            tool_call_id="tc1",
            tool_name="bash",
            status="ok",
            verb="Ran",
            title="uv run pytest",
            body="2 passed",
        )
    )

    assert (
        stdout.getvalue()
        == "• Ran uv run pytest took 0.00s\n  $ uv run pytest\n  2 passed\n"
    )


def test_plain_renderer_buffers_deltas_then_projects_final_assistant_record() -> None:
    from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer
    from loushang.tui.theme import ThemeResolver

    stdout = StringIO()
    renderer = PlainCodingUiRenderer(
        stdout=stdout,
        use_transcript_view=True,
        transcript_theme=ThemeResolver(
            defaults={"markdown.heading.level2": {"bold": True}}
        ),
    )

    renderer.begin_assistant()
    renderer.write_assistant_delta("## Res")
    renderer.write_assistant_delta("ult")
    assert stdout.getvalue() == ""

    renderer.end_assistant()

    assert "• Result" in stdout.getvalue()


def test_plain_renderer_collects_screen_transcript_without_stdout_writes() -> None:
    from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer
    from loushang.tui import (
        RenderConstraints,
        TranscriptBuffer,
        strip_control_sequences,
    )

    stdout = StringIO()
    buffer = TranscriptBuffer()
    renderer = PlainCodingUiRenderer(stdout=stdout, transcript_buffer=buffer)

    renderer.render_user("你好")
    renderer.begin_assistant()
    renderer.write_assistant_delta("## Res")
    renderer.write_assistant_delta("ult")

    assert stdout.getvalue() == ""
    draft = strip_control_sequences(
        renderer.render_transcript(RenderConstraints(width=40, max_height=20))
        .lines[-1]
        .text
    )
    assert "Result" in draft

    renderer.end_assistant()

    rendered = renderer.render_transcript(RenderConstraints(width=40, max_height=20))
    output = "\n".join(strip_control_sequences(line.text) for line in rendered.lines)
    assert stdout.getvalue() == ""
    assert "› 你好" in output
    assert "• Result" in output
