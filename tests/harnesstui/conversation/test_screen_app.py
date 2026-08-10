from __future__ import annotations

import pytest

from loushang.harnesstui.conversation.screen_app import ScreenConversationApp
from loushang.harnesstui.conversation.screen_frame import (
    ScreenFrameCopy,
    ScreenFramePresentation,
)
from loushang.tui import RenderConstraints
from loushang.tui.transcript import (
    AssistantMessageRecord,
    ContextCompactionRecord,
    UserPromptRecord,
)
from loushang.tui.ui_parts.transcript import TranscriptRegion


class _TestScreenConversationApp(ScreenConversationApp):
    def _create_frame_presentation(self) -> ScreenFramePresentation:
        return ScreenFramePresentation(
            ScreenFrameCopy(
                working_label="Running",
                steer_label="Steers",
                steer_hint="interrupt",
                followup_label="Follow-ups",
                followup_hint="edit",
            )
        )


def _app() -> _TestScreenConversationApp:
    return _TestScreenConversationApp(
        model_label="model",
        cwd="/workspace",
        branch="main",
        session_label="session",
        now=lambda: 2.0,
    )


@pytest.mark.tui_render_contract
def test_screen_conversation_app_coordinates_neutral_streaming_state() -> None:
    app = _app()
    app.start_prompt("hello", started_at=1.0)
    app.begin_assistant()
    app.append_assistant_chunk("world")

    result = app.render(RenderConstraints(width=60, max_height=24, visible_height=24))

    assert type(app._transcript_region) is TranscriptRegion
    assert app._transcript_region.records is app.state.records
    assert tuple(line.text for line in result.lines)[:3] == (
        "> hello",
        "",
        "* world",
    )


@pytest.mark.tui_render_contract
def test_screen_conversation_app_keeps_presentation_and_region_instances() -> None:
    app = _app()
    presentation = app._transcript_presentation
    region = app._transcript_region
    app.add_status("ready")

    app.render(RenderConstraints(width=60, max_height=24, visible_height=24))
    app.render(RenderConstraints(width=60, max_height=24, visible_height=24))

    assert app._transcript_presentation is presentation
    assert app._transcript_region is region


def test_screen_conversation_app_reports_window_replacement_reason_once() -> None:
    app = _app()

    app.replace_transcript_window((), reason="test")

    assert app.consume_render_baseline_reset_reason() == (
        "transcript_window_replaced:test"
    )
    assert app.consume_render_baseline_reset_reason() is None


def test_screen_conversation_app_owns_compaction_window_mechanics() -> None:
    app = _app()
    app.state.records.extend(
        [
            UserPromptRecord("old"),
            AssistantMessageRecord("middle"),
            UserPromptRecord("new"),
        ]
    )

    app.compact_transcript_window(summary=" condensed ", max_records=2)

    assert app.state.records == [
        AssistantMessageRecord("condensed"),
        UserPromptRecord("new"),
    ]
    assert app.state.evicted_prefix_record_count == 2
    assert app.consume_render_baseline_reset_reason() == (
        "transcript_window_replaced:compaction"
    )


def test_screen_conversation_app_appends_compaction_fact_without_trimming_records() -> None:
    app = _app()
    app.state.records.extend(UserPromptRecord(str(index)) for index in range(3))

    app.append_context_compaction_record(
        summary="condensed",
        tokens_before=42,
    )

    assert app.state.records == [
        UserPromptRecord("0"),
        UserPromptRecord("1"),
        UserPromptRecord("2"),
        ContextCompactionRecord(summary="condensed", tokens_before=42),
    ]
    assert app.state.evicted_prefix_record_count == 0
    assert app.consume_render_baseline_reset_reason() is None


def test_screen_conversation_app_applies_active_logical_line_budget() -> None:
    app = _app()
    app.active_transcript_line_budget = 2
    app.state.records.extend(
        [
            UserPromptRecord("old"),
            AssistantMessageRecord("new"),
        ]
    )

    app.trim_active_transcript_window()

    assert app.state.records == [AssistantMessageRecord("new")]
    assert app.state.evicted_prefix_record_count == 1
    assert app.consume_render_baseline_reset_reason() == (
        "transcript_window_trimmed:active_line_budget"
    )
