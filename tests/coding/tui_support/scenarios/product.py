from __future__ import annotations

from collections.abc import Callable

from loushang.harnesstui.testing.performance import (
    build_synthetic_long_transcript_records,
)
from loushang.tui import (
    PlaybackEvent,
    PlaybackFrameBudget,
    SearchableList,
    SearchableListItem,
    strip_control_sequences,
)
from loushang.tui.playback_suite import (
    PlaybackScenarioSpec as ScreenPlaybackScenarioSpec,
)
from tests.coding.tui_support.playback import (
    ScreenTuiInputPlaybackResult,
    ScreenTuiInputScenario,
)

PRODUCT_COMPOSED_FRAME_BUDGET = PlaybackFrameBudget(
    disallowed_operation_classes=("baseline_repaint", "recovery_repaint"),
    max_operations=64,
    max_serialized_output_bytes=3_000,
    max_changed_visible_lines=20,
    require_synchronized=True,
)

PRODUCT_STREAMING_CONTROL_FRAME_BUDGET = PlaybackFrameBudget(
    disallowed_operation_classes=("baseline_repaint", "recovery_repaint"),
    max_operations=1_500,
    max_serialized_output_bytes=90_000,
    max_changed_visible_lines=18,
    require_synchronized=True,
)


def _run_product_composed_interaction() -> ScreenTuiInputPlaybackResult:
    scenario = (
        ScreenTuiInputScenario(width=100, height=18)
        .with_records(
            build_synthetic_long_transcript_records(
                turns=24, tail_tool_output_lines=120
            )
        )
        .with_running_prompt("investigate product playback")
        .with_completion_items("/model", "/models")
    )

    scenario.playback.play(
        (
            PlaybackEvent("render"),
            PlaybackEvent.input("follow one"),
            PlaybackEvent.input("\x1b\r"),
        )
    )
    assert scenario.app.state.pending_followups == ["follow one"]
    _assert_visible_contains(scenario, "Queued follow-up inputs")
    _assert_visible_contains(scenario, "follow one")

    scenario.app.active_surface = SearchableList(
        (
            SearchableListItem("memory", "Memory", "on"),
            SearchableListItem("model", "Model", "kimi"),
        ),
        focused=True,
        placeholder="Search settings...",
        detail_column=24,
    )
    scenario.playback.play(
        (
            PlaybackEvent("render"),
            PlaybackEvent.input("mo\x1b[Dx"),
        )
    )
    _assert_visible_contains(scenario, "mxo")
    _assert_visible_contains(scenario, "No matching items")

    scenario.app.active_surface = None
    scenario.playback.play(
        (
            PlaybackEvent("render"),
            PlaybackEvent.input("/mod"),
            PlaybackEvent.input("\t"),
            PlaybackEvent.input("gpt"),
            PlaybackEvent.input("\x1b[1;2D"),
            PlaybackEvent.input("x"),
        )
    )

    result = _result_from_scenario(scenario)
    assert result.app.state.pending_followups == ["follow one"]
    result.assert_composer_text("/model gpx")
    result.assert_visible_contains("› /model gpx")
    result.assert_last_cursor_on_visible_line("› /model gpx", column=12)
    result.assert_visible_contains("queued=1 steer=0")
    result.assert_no_clear_screen()
    _assert_with_review_artifacts(
        result,
        lambda: PRODUCT_COMPOSED_FRAME_BUDGET.assert_result(result, skip_first=True),
    )
    return result


def _run_product_streaming_control_flow() -> ScreenTuiInputPlaybackResult:
    scenario = (
        ScreenTuiInputScenario(width=104, height=20)
        .with_records(
            build_synthetic_long_transcript_records(
                turns=36,
                tail_tool_output_lines=180,
            )
        )
        .with_running_prompt("investigate live product controls")
    )
    scenario.app.begin_assistant()
    scenario.app.append_assistant_chunk("streaming answer chunk one")

    scenario.playback.play(
        (
            PlaybackEvent("render"),
            PlaybackEvent.input("follow after current run"),
            PlaybackEvent.input("\x1b\r"),
        )
    )
    assert scenario.app.state.pending_followups == ["follow after current run"]
    _assert_visible_contains(scenario, "streaming answer chunk one")
    _assert_visible_contains(scenario, "Queued follow-up inputs")

    scenario.app.append_assistant_chunk(" and chunk two")
    scenario.playback.play(
        (
            PlaybackEvent("render"),
            PlaybackEvent.resize(columns=72, rows=12),
            PlaybackEvent.input("steer before next tool"),
            PlaybackEvent.input("\r"),
        )
    )
    assert scenario.app.state.pending_steers == ["steer before next tool"]
    _assert_visible_contains(scenario, "Messages to be submitted after next tool call")
    _assert_visible_contains(scenario, "steer before next tool")

    scenario.app.active_surface = SearchableList(
        (
            SearchableListItem("memory", "Memory", "on"),
            SearchableListItem("model", "Model", "kimi"),
            SearchableListItem("theme", "Theme", "system"),
        ),
        focused=True,
        placeholder="Search settings...",
        detail_column=24,
    )
    scenario.playback.play(
        (
            PlaybackEvent("render"),
            PlaybackEvent.input("mem"),
        )
    )
    _assert_visible_contains(scenario, "mem")
    _assert_visible_contains(scenario, "Memory")

    scenario.app.active_surface = None
    scenario.playback.play(
        (
            PlaybackEvent("render"),
            PlaybackEvent.input("\x1b"),
        )
    )

    result = _result_from_scenario(scenario)
    result.assert_abort_requested()
    result.assert_pending_steers("steer before next tool")
    assert result.app.state.pending_followups == ["follow after current run"]
    draft = result.app.state.assistant_draft
    assert draft is not None
    assert draft.text == "streaming answer chunk one and chunk two"
    result.assert_visible_contains("queued=1 steer=1")
    result.assert_no_clear_scrollback()
    _assert_with_review_artifacts(
        result,
        lambda: PRODUCT_STREAMING_CONTROL_FRAME_BUDGET.assert_result(
            result,
            skip_first=True,
        ),
    )
    return result


def _result_from_scenario(
    scenario: ScreenTuiInputScenario,
) -> ScreenTuiInputPlaybackResult:
    return scenario.playback.result()


def _assert_visible_contains(scenario: ScreenTuiInputScenario, expected: str) -> None:
    visible = strip_control_sequences(
        "\n".join(scenario.playback.port.screen.visible_lines)
    )
    assert expected in visible


def _assert_with_review_artifacts(
    result: ScreenTuiInputPlaybackResult,
    assertion: Callable[[], None],
) -> None:
    try:
        assertion()
    except AssertionError as error:
        setattr(error, "playback_result", result)
        raise


PRODUCT_SCENARIOS = (
    ScreenPlaybackScenarioSpec(
        name="product-composed-interaction",
        description="Exercise long transcript, running queue, settings search, completion, and selection in one playback.",
        run=_run_product_composed_interaction,
        tags=(
            "product",
            "transcript",
            "lifecycle",
            "surface",
            "completion",
            "selection",
        ),
    ),
    ScreenPlaybackScenarioSpec(
        name="product-streaming-control-flow",
        description="Exercise long streaming transcript controls with follow-up, steer, settings page, resize, and abort.",
        run=_run_product_streaming_control_flow,
        tags=(
            "product",
            "transcript",
            "streaming",
            "lifecycle",
            "surface",
            "resize",
        ),
    ),
)


__all__ = ["PRODUCT_SCENARIOS"]
