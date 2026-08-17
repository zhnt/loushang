from __future__ import annotations

from dataclasses import dataclass

from loushang.harnesstui.conversation.screen_frame import (
    ScreenFrameCopy,
    ScreenFramePresentation,
)
from loushang.harnesstui.conversation.screen_state import ScreenConversationState
from loushang.harnesstui.status.line import StatusLinePreviewSnapshot
from loushang.tui import BottomFrame, Composer


def _presentation() -> ScreenFramePresentation:
    return ScreenFramePresentation(
        ScreenFrameCopy(
            working_label="Working",
            steer_label="Steers",
            steer_hint="interrupt hint",
            followup_label="Follow-ups",
            followup_hint="edit hint",
        )
    )


def _state() -> ScreenConversationState:
    return ScreenConversationState(
        model_label="openai:gpt-test",
        cwd="/workspace/demo",
        branch="main",
        session_label="session-1",
    )


def test_screen_frame_snapshot_projects_live_conversation_facts() -> None:
    state = _state()
    state.begin_run(started_at=1.0)
    state.pending_steers[:] = ["steer"]
    state.pending_followups[:] = ["follow"]
    state.set_status("running")

    assert _presentation().statusline_preview_snapshot(state) == (
        StatusLinePreviewSnapshot(
            model_label="openai:gpt-test",
            cwd="/workspace/demo",
            branch="main",
            session_label="session-1",
            running=True,
            permission_profile="standard",
            pending_followups=1,
            pending_steers=1,
            status_message="running",
        )
    )


def test_screen_frame_populates_existing_component_with_injected_copy() -> None:
    state = _state()
    state.begin_run(started_at=1.0)
    state.interruption_message = "Interrupted"
    state.pending_steers[:] = ["steer"]
    state.pending_followups[:] = ["follow"]
    composer = Composer()
    component = BottomFrame(composer=composer)

    result = _presentation().populate_bottom_frame(
        component,
        composer=composer,
        state=state,
        active_surface=None,
        elapsed_seconds=2.5,
    )

    assert result is component
    assert result.working_line is not None
    assert result.working_line.label == "Working"
    assert result.working_line.elapsed_seconds == 2.5
    assert result.pending_queue is not None
    assert tuple(
        (
            section.label,
            section.items,
            section.hint,
            section.marker,
            section.hint_placement,
        )
        for section in result.pending_queue.sections
    ) == (
        ("Interrupted", (), None, "■", "footer"),
        ("Steers", ("steer",), "interrupt hint", "•", "header"),
        ("Follow-ups", ("follow",), "edit hint", "•", "footer"),
    )

    state.complete_run(elapsed_seconds=2.5)
    state.interruption_message = None
    state.pending_steers.clear()
    state.pending_followups.clear()
    presentation = _presentation()
    presentation.populate_bottom_frame(
        component,
        composer=composer,
        state=state,
        active_surface=None,
        elapsed_seconds=0.0,
    )
    assert component.working_line is None
    assert component.pending_queue is None


def test_screen_frame_height_honors_surface_preference_and_visible_cap() -> None:
    @dataclass
    class Surface:
        preferred_height: int

    state = _state()
    presentation = _presentation()

    assert (
        presentation.bottom_frame_height(
            state,
            active_surface=None,
            visible_height=40,
        )
        == 12
    )
    assert (
        presentation.bottom_frame_height(
            state,
            active_surface=Surface(preferred_height=24),
            visible_height=20,
        )
        == 20
    )
