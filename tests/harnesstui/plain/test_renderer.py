from __future__ import annotations

from dataclasses import FrozenInstanceError
from io import StringIO

import pytest

from loushang.harnesstui.conversation.tool_transcript import ToolTranscriptBlock
from loushang.harnesstui.plain.renderer import (
    PlainConversationGlyphs,
    PlainConversationProfile,
    PlainConversationRenderer,
)
from loushang.tui import InfoPanel, RenderConstraints, TranscriptBuffer
from loushang.tui.cell_width import strip_control_sequences
from loushang.tui.transcript import (
    AssistantMessageRecord,
    ErrorRecord,
    StatusRecord,
    ThinkingRecord,
    ThinkingVisibility,
    UserPromptRecord,
    WorkedDividerRecord,
)


class _FlushCountingStream(StringIO):
    flush_count = 0

    def flush(self) -> None:
        self.flush_count += 1
        super().flush()


def test_plain_conversation_renderer_has_neutral_defaults_and_flushes_lines() -> None:
    stdout = _FlushCountingStream()
    renderer = PlainConversationRenderer(stdout=stdout)

    renderer.render_header(
        project_label="Demo",
        cwd="/repo",
        branch="main",
        session_label="session-1",
        model_label="provider/model",
    )
    renderer.render_user("hello")
    renderer.render_assistant("**answer**")
    renderer.render_error("boom")
    renderer.render_interruption()

    assert stdout.getvalue() == (
        "Demo\n"
        "model=provider/model | cwd=/repo | branch=main | session=session-1\n"
        "\n"
        "> hello\n"
        "* answer\n"
        "! Error: boom\n"
        "! Conversation interrupted.\n"
    )
    assert stdout.flush_count == 7
    assert "Loushang" not in stdout.getvalue()
    assert "/feedback" not in stdout.getvalue()


def test_plain_conversation_profile_injects_presentation_without_mutation() -> None:
    profile = PlainConversationProfile(
        title="Product",
        interruption_message="Stopped",
        glyphs=PlainConversationGlyphs(
            user_prompt="U ",
            assistant="A ",
            item="I ",
            error="E ",
            interruption="X ",
            rule="=",
        ),
        terminal_columns=lambda: 24,
    )
    stdout = StringIO()
    renderer = PlainConversationRenderer(stdout=stdout, profile=profile)

    renderer.render_header(
        project_label="ignored",
        cwd="/repo",
        branch=None,
        session_label=None,
        model_label=None,
    )
    renderer.render_user("prompt")
    renderer.render_assistant("answer")
    renderer.render_tool_summary("tool")
    renderer.render_error("error")
    renderer.render_interruption()
    renderer.render_worked(1.25)

    assert stdout.getvalue() == (
        "Product\n"
        "cwd=/repo\n"
        "\n"
        "U prompt\n"
        "A answer\n"
        "I tool\n"
        "E error\n"
        "X Stopped\n"
        "\n"
        "= Worked for 1.2s ======\n"
        "\n"
    )
    with pytest.raises(FrozenInstanceError):
        setattr(profile, "title", "Changed")


def test_plain_conversation_renderer_injects_tool_record_projection() -> None:
    projected = StatusRecord("projected")
    seen: list[ToolTranscriptBlock] = []

    def project(block: ToolTranscriptBlock) -> StatusRecord:
        seen.append(block)
        return projected

    profile = PlainConversationProfile(tool_block_projector=project)
    buffer = TranscriptBuffer()
    renderer = PlainConversationRenderer(
        stdout=StringIO(),
        transcript_buffer=buffer,
        profile=profile,
    )
    block = ToolTranscriptBlock(
        tool_call_id="tc1",
        tool_name="shell",
        status="ok",
        verb="Used",
        title="shell command",
    )

    renderer.render_tool_block(block)

    assert seen == [block]
    assert buffer.records == (projected,)


def test_plain_conversation_renderer_preserves_tool_block_body_and_detail() -> None:
    stdout = StringIO()
    renderer = PlainConversationRenderer(stdout=stdout)

    renderer.render_tool_block(
        ToolTranscriptBlock(
            tool_call_id="tc1",
            tool_name="shell",
            status="ok",
            verb="Used",
            title="shell command",
            body="first\nsecond",
            detail="finished",
        )
    )

    assert stdout.getvalue() == (
        "- Used shell command\n  first\n  second\n  finished\n"
    )


def test_plain_conversation_renderer_maps_transcript_lines_and_drafts() -> None:
    profile = PlainConversationProfile(
        line_mapper=lambda line, record: f"mapped:{strip_control_sequences(line)}"
    )
    buffer = TranscriptBuffer()
    stdout = StringIO()
    renderer = PlainConversationRenderer(
        stdout=stdout,
        transcript_buffer=buffer,
        profile=profile,
    )

    renderer.render_user("hello")
    renderer.begin_assistant()
    renderer.write_assistant_delta("draft")

    renderable = renderer.transcript_renderable()
    assert renderable is not None
    output = renderable.render(RenderConstraints(width=40, max_height=20))

    assert stdout.getvalue() == ""
    assert [line.text for line in output.lines] == [
        "mapped:> hello",
        "mapped:* draft",
    ]


def test_plain_conversation_renderer_empty_and_bounded_transcript_views() -> None:
    renderer = PlainConversationRenderer(stdout=StringIO())

    assert renderer.transcript_renderable() is None
    assert (
        renderer.render_transcript(RenderConstraints(width=40, max_height=2)).lines
        == ()
    )

    buffer = TranscriptBuffer()
    buffer.append(UserPromptRecord("first"))
    buffer.append(UserPromptRecord("second"))
    bounded = PlainConversationRenderer(
        stdout=StringIO(),
        transcript_buffer=buffer,
    ).render_transcript(RenderConstraints(width=40, max_height=1))

    assert len(bounded.lines) == 1


def test_plain_conversation_renderer_commits_final_assistant_and_buffer_records() -> (
    None
):
    buffer = TranscriptBuffer()
    stdout = StringIO()
    renderer = PlainConversationRenderer(
        stdout=stdout,
        transcript_buffer=buffer,
    )

    renderer.begin_assistant()
    renderer.write_assistant_delta("draft")
    renderer.end_assistant("final")
    renderer.render_status("working")
    renderer.render_info_panel(InfoPanel("Info", "details"))
    renderer.render_tool_summary("Explored", "files")
    renderer.render_error("failed")
    renderer.render_interruption()
    renderer.render_worked(1.5)

    assert stdout.getvalue() == ""
    assert buffer.assistant_draft is None
    assert buffer.records == (
        AssistantMessageRecord("final"),
        StatusRecord("working"),
        StatusRecord("Info\ndetails"),
        ThinkingRecord("Explored files", ThinkingVisibility.VISIBLE),
        ErrorRecord("failed"),
        ErrorRecord("Conversation interrupted."),
        WorkedDividerRecord(1.5),
    )


def test_plain_conversation_renderer_preserves_legacy_tool_lifecycle_output() -> None:
    stdout = StringIO()
    renderer = PlainConversationRenderer(stdout=stdout, max_payload_chars=12)

    renderer.render_tool_start("read", {"path": "long-name"})
    renderer.render_tool_update("read", "partial result")
    renderer.render_tool_update("read", "")
    renderer.render_tool_end("read", "done", is_error=False)
    renderer.render_tool_end("write", "failed", is_error=True)

    assert stdout.getvalue() == (
        '[tool:start] read {"path": ...\n'
        "[tool:update] read partial r...\n"
        "[tool:done] read done\n"
        "[tool:error] write failed\n"
    )
