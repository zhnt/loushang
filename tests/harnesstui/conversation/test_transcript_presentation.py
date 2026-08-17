from __future__ import annotations

from dataclasses import replace

from loushang.harnesstui.conversation.screen_frame import ScreenFrameCopy
from loushang.harnesstui.conversation.transcript_presentation import (
    ConversationTranscriptCopy,
    ConversationTranscriptPresentationProfile,
    ProfiledConversationTranscriptPresentation,
    ProfiledScreenConversationApp,
    ScreenConversationPresentationProfile,
)
from loushang.tui.theme import ThemeResolver
from loushang.tui.transcript import (
    AssistantMessageRecord,
    ContextCompactionRecord,
    DisplayRecord,
    ErrorRecord,
    ToolExecutionRecord,
    UserPromptRecord,
    WorkedDividerRecord,
)


def _project_record(record: DisplayRecord, *, context: str) -> DisplayRecord:
    if isinstance(record, ToolExecutionRecord):
        return replace(record, name=f"{context}:{record.name}")
    return record


def _record_width(record: DisplayRecord, *, width: int) -> int:
    return width - 3 if isinstance(record, ToolExecutionRecord) else width


def _style_line(
    line: str,
    _record: DisplayRecord,
    *,
    theme: ThemeResolver | None,
    capabilities: object | None,
) -> str:
    del theme, capabilities
    return f"[{line}]"


_COPY = ConversationTranscriptCopy(
    user_prompt_prefix="USER ",
    assistant_prefix="ASSISTANT ",
    error_prefix="ERROR ",
    context_compaction_prefix="COMPACT ",
    tool_success_prefix="TOOL ",
    tool_error_prefix="TOOL-ERROR ",
    worked_divider="=",
    tool_command_prefix="COMMAND ",
    tool_first_output_prefix="OUTPUT ",
    tool_continuation_prefix="       ",
)
_TRANSCRIPT_PROFILE = ConversationTranscriptPresentationProfile[str](
    copy=_COPY,
    project_record=_project_record,
    record_render_width=_record_width,
    style_line=_style_line,
)


def test_profiled_transcript_presentation_applies_product_copy_and_style() -> None:
    presentation = ProfiledConversationTranscriptPresentation(
        profile=_TRANSCRIPT_PROFILE,
        context="workspace",
    )

    cases = (
        (UserPromptRecord("hello"), ("> hello",), ("[USER hello]",)),
        (AssistantMessageRecord("hello"), ("* hello",), ("[ASSISTANT hello]",)),
        (ErrorRecord("bad"), ("! Error: bad",), ("[ERROR bad]",)),
        (
            ContextCompactionRecord("short"),
            ("* Context compacted",),
            ("[COMPACT Context compacted]",),
        ),
        (
            WorkedDividerRecord(1.0),
            ("- Worked for 1.00s -",),
            ("[= Worked for 1.00s =]",),
        ),
    )
    for record, lines, expected in cases:
        assert (
            presentation.present_lines(
                lines,
                record,
                theme=None,
                capabilities=None,
            )
            == expected
        )


def test_profiled_transcript_presentation_structures_tool_body_once() -> None:
    presentation = ProfiledConversationTranscriptPresentation(
        profile=_TRANSCRIPT_PROFILE,
        context="workspace",
    )
    record = ToolExecutionRecord(
        name="shell",
        state="completed",
        elapsed_seconds=0.0,
    )

    assert presentation.present_lines(
        (
            "- Ran shell",
            "  $ echo hello",
            "  first line",
            "  second line",
        ),
        record,
        theme=None,
        capabilities=None,
    ) == (
        "[TOOL shell]",
        "[COMMAND $ echo hello]",
        "[OUTPUT first line]",
        "[       second line]",
    )
    assert presentation.present_lines(
        ("! Ran shell",),
        record,
        theme=None,
        capabilities=None,
    ) == ("[TOOL-ERROR shell]",)


def test_profiled_transcript_presentation_context_is_its_cache_token() -> None:
    presentation = ProfiledConversationTranscriptPresentation(
        profile=_TRANSCRIPT_PROFILE,
        context="first",
    )
    record = ToolExecutionRecord(
        name="read",
        state="completed",
        elapsed_seconds=0.0,
    )

    assert presentation.cache_token == "first"
    assert presentation.project_record(record).name == "first:read"
    assert presentation.record_render_width(record, width=80) == 77

    presentation.context = "second"

    assert presentation.cache_token == "second"
    assert presentation.project_record(record).name == "second:read"


_FRAME_COPY = ScreenFrameCopy(
    working_label="Running",
    steer_label="Steers",
    steer_hint="interrupt",
    followup_label="Follow-ups",
    followup_hint="edit",
)
_SCREEN_PROFILE = ScreenConversationPresentationProfile[str](
    transcript=_TRANSCRIPT_PROFILE,
    transcript_context=lambda state: state.cwd,
    frame_copy=_FRAME_COPY,
    welcome_panel=lambda state, *, theme: (state.cwd, state.session_label, theme),
)


class _ProfiledApp(ProfiledScreenConversationApp):
    screen_presentation_profile = _SCREEN_PROFILE


def test_profiled_screen_app_reuses_presentation_and_refreshes_context() -> None:
    app = _ProfiledApp(
        model_label="model",
        cwd="/first",
        branch="main",
        session_label="session",
    )
    presentation = app._transcript_presentation

    assert presentation.cache_token == "/first"
    assert app.startup_welcome_panel() == ("/first", "session", None)

    app.state.cwd = "/second"
    app._prepare_transcript_presentation()

    assert app._transcript_presentation is presentation
    assert presentation.cache_token == "/second"
