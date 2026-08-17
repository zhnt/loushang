from __future__ import annotations

import json

import pytest

from loushang.harnesstui.testing.performance import (
    build_synthetic_long_transcript_records,
)
from loushang.harnesstui.testing.screen_loop_playback import (
    BlockingPromptController,
)
from loushang.tui import (
    PLAYBACK_ARTIFACTS_ENV,
    PlaybackFrameBudget,
    SelectionSurface,
    SelectItem,
    strip_control_sequences,
)
from loushang.tui.transcript import AssistantMessageRecord
from tests.coding.tui_support.playback import (
    ScreenTuiInputScenario,
    ScreenTuiLoopScenario,
    ScreenTuiScenario,
)

INTERACTION_FRAME_BUDGET = PlaybackFrameBudget(
    disallowed_operation_classes=("baseline_repaint", "recovery_repaint"),
    max_operations=32,
    max_serialized_output_bytes=768,
    max_changed_visible_lines=8,
    require_synchronized=True,
)

LONG_TRANSCRIPT_FRAME_BUDGET = PlaybackFrameBudget(
    disallowed_operation_classes=("baseline_repaint", "recovery_repaint"),
    max_operations=12,
    max_serialized_output_bytes=2_000,
    max_changed_visible_lines=3,
    require_synchronized=True,
)


def _assert_interaction_frame_budget(result, basename: str) -> None:
    with result.write_artifacts_on_failure_from_env(
        basename=basename, include_frames=True
    ):
        INTERACTION_FRAME_BUDGET.assert_result(result, skip_first=True)


def test_screen_tui_scenario_renders_composer_input_without_screen_clear() -> None:
    scenario = ScreenTuiScenario(width=80, height=18)
    scenario.render()

    step = scenario.type_text("hello").render()

    scenario.assert_operation_class(step, "changed_range_update")
    scenario.assert_no_clear(step)
    scenario.assert_visible_contains("› hello")
    scenario.assert_cursor_matches_diagnostics(step)


def test_screen_tui_input_scenario_scripts_input_without_screen_clear() -> None:
    result = (
        ScreenTuiInputScenario(width=80, height=12)
        .type_text("hello")
        .type_text(" world")
        .run()
    )

    result.assert_all_flush_succeeded()
    result.assert_visible_contains("› hello world")
    result.assert_composer_text("hello world")
    result.assert_no_clear_screen()
    result.assert_cursor_matches_diagnostics()


def test_screen_tui_input_scenario_scripts_resize_without_scrollback_or_cursor_drift() -> (
    None
):
    result = (
        ScreenTuiInputScenario(width=80, height=12)
        .type_text("hello")
        .resize(width=42, height=8)
        .type_text(" world")
        .run()
    )

    result.assert_all_flush_succeeded()
    result.assert_visible_contains("› hello world")
    result.assert_composer_text("hello world")
    result.assert_no_clear_scrollback()
    result.assert_cursor_matches_diagnostics()


def test_screen_tui_input_scenario_captures_prompt_submission_without_screen_clear() -> (
    None
):
    result = (
        ScreenTuiInputScenario(width=80, height=12).type_text("hello").enter().run()
    )

    result.assert_prompt_texts("hello")
    result.assert_composer_text("")
    result.assert_visible_contains("› hello")
    result.assert_no_clear_screen()
    result.assert_cursor_matches_diagnostics()


def test_screen_tui_input_scenario_writes_neutral_jsonl_for_manual_inspection(
    tmp_path,
) -> None:
    result = (
        ScreenTuiInputScenario(width=80, height=12)
        .with_running_prompt("old")
        .type_text("change")
        .enter()
        .run()
    )
    path = tmp_path / "screen-playback.jsonl"

    result.write_jsonl(path)

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["conversation"]["state"]["composer_text"] == "change"
    assert rows[0]["conversation"]["state"]["pending_steers"] == []
    assert rows[-1]["conversation"] == {
        "state": {
            "composer_text": "",
            "running": True,
            "pending_steers": ["change"],
            "pending_followups": [],
        },
        "input_results": [
            {
                "prompt_text": None,
                "prompt_attachment_count": 0,
                "local_text": None,
                "steer_text": "change",
                "steer_attachment_count": 0,
                "followup_text": None,
                "followup_attachment_count": 0,
                "surface_intent": None,
                "abort_requested": False,
                "exit_code": None,
                "render_requested": True,
            }
        ],
    }


@pytest.mark.tui_render_contract
def test_screen_tui_input_scenario_applies_tab_completion_without_screen_clear() -> (
    None
):
    result = (
        ScreenTuiInputScenario(width=80, height=12)
        .with_completion_items("/model", "/models")
        .render()
        .type_text("/mod")
        .tab()
        .run()
    )

    with result.write_artifacts_on_failure_from_env(
        basename="screen-input-tab-completion", include_frames=True
    ):
        result.assert_composer_text("/model ")
        result.assert_visible_contains("› /model")
        result.assert_no_clear_screen()
        result.assert_cursor_matches_diagnostics()
    _assert_interaction_frame_budget(result, "screen-input-tab-completion")


@pytest.mark.tui_render_contract
def test_screen_tui_input_scenario_captures_local_command_without_prompt_echo() -> None:
    result = (
        ScreenTuiInputScenario(width=80, height=12)
        .with_local_commands("/local")
        .render()
        .type_text("/local")
        .enter()
        .run()
    )

    with result.write_artifacts_on_failure_from_env(
        basename="screen-input-local-command", include_frames=True
    ):
        result.assert_local_texts("/local")
        result.assert_prompt_texts()
        result.assert_composer_text("")
        result.assert_visible_not_contains("› /local")
        result.assert_no_clear_screen()
        result.assert_cursor_matches_diagnostics()
    _assert_interaction_frame_budget(result, "screen-input-local-command")


@pytest.mark.tui_render_contract
def test_screen_tui_input_scenario_routes_active_surface_before_composer() -> None:
    result = (
        ScreenTuiInputScenario(width=80, height=12)
        .with_active_surface(
            SelectionSurface([SelectItem("Choose me", value="chosen")])
        )
        .with_composer_text("draft")
        .render()
        .enter()
        .run()
    )

    with result.write_artifacts_on_failure_from_env(
        basename="screen-input-active-surface", include_frames=True
    ):
        result.assert_surface_intents(("select", "chosen"))
        result.assert_composer_text("draft")
        result.assert_visible_contains("Choose me")
        result.assert_no_clear_screen()
        result.assert_cursor_matches_diagnostics()
    _assert_interaction_frame_budget(result, "screen-input-active-surface")


@pytest.mark.tui_render_contract
def test_screen_tui_input_scenario_captures_running_steer_without_screen_clear() -> (
    None
):
    result = (
        ScreenTuiInputScenario(width=80, height=12)
        .with_running_prompt("old")
        .render()
        .type_text("change")
        .enter()
        .run()
    )

    with result.write_artifacts_on_failure_from_env(
        basename="screen-input-running-steer", include_frames=True
    ):
        result.assert_steer_texts("change")
        result.assert_pending_steers("change")
        result.assert_composer_text("")
        result.assert_visible_contains("Messages to be submitted after next tool call")
        result.assert_visible_contains("change")
        result.assert_no_clear_screen()
        result.assert_cursor_matches_diagnostics()
    _assert_interaction_frame_budget(result, "screen-input-running-steer")


@pytest.mark.tui_render_contract
def test_screen_tui_input_scenario_escape_abort_does_not_pop_pending_steer() -> None:
    result = (
        ScreenTuiInputScenario(width=80, height=12)
        .with_running_prompt("old")
        .with_pending_steers("queued")
        .render()
        .escape()
        .run()
    )

    with result.write_artifacts_on_failure_from_env(
        basename="screen-input-escape-abort", include_frames=True
    ):
        result.assert_abort_requested()
        result.assert_pending_steers("queued")
        result.assert_visible_contains("Messages to be submitted after next tool call")
        result.assert_visible_contains("queued")
        result.assert_no_clear_screen()
        result.assert_cursor_matches_diagnostics()
    _assert_interaction_frame_budget(result, "screen-input-escape-abort")


@pytest.mark.tui_render_contract
def test_screen_tui_input_scenario_idle_escape_pops_pending_steer() -> None:
    result = (
        ScreenTuiInputScenario(width=80, height=12)
        .with_pending_steers("queued")
        .render()
        .escape()
        .run()
    )

    with result.write_artifacts_on_failure_from_env(
        basename="screen-input-idle-escape-steer", include_frames=True
    ):
        result.assert_steer_texts("queued")
        result.assert_pending_steers()
        result.assert_visible_not_contains(
            "Messages to be submitted after next tool call"
        )
        result.assert_no_clear_screen()
        result.assert_cursor_matches_diagnostics()
    _assert_interaction_frame_budget(result, "screen-input-idle-escape-steer")


@pytest.mark.tui_render_contract
def test_screen_tui_input_scenario_echoes_input_after_long_transcript_without_repaint() -> (
    None
):
    result = (
        ScreenTuiInputScenario(width=100, height=18)
        .with_records(
            build_synthetic_long_transcript_records(
                turns=40, tail_tool_output_lines=300
            )
        )
        .render()
        .type_chars("fresh input")
        .run()
    )

    with result.write_artifacts_on_failure_from_env(
        basename="screen-input-long-transcript", include_frames=True
    ):
        result.assert_composer_text("fresh input")
        result.assert_visible_contains("› fresh input")
        result.assert_no_clear_screen()
        LONG_TRANSCRIPT_FRAME_BUDGET.assert_result(result, skip_first=True)
        result.assert_screen_anchor_stable("›", occurrence="last")


def test_screen_tui_input_scenario_reader_short_content_restores_bottom_frame() -> None:
    result = (
        ScreenTuiInputScenario(width=72, height=8)
        .with_records((AssistantMessageRecord("short answer"),))
        .with_composer_text("draft")
        .render()
        .key("\x0f")
        .ctrl_c()
        .run()
    )

    open_screen = _step_visible_text(result, 1)
    close_screen = _step_visible_text(result, 2)

    assert (
        open_screen.splitlines()[-1]
        == "Ctrl+O/q/Esc close   / search   n/N next   d detail   r raw"
    )
    assert "› draft" not in open_screen
    assert "› draft" in close_screen
    assert "kimi | repo | main | abcd | idle" in close_screen
    result.assert_cursor_matches_diagnostics()


def test_screen_tui_loop_playback_drives_running_steer_then_escape() -> None:
    scenario = ScreenTuiLoopScenario()
    prompts: list[str] = []
    steers: list[tuple[str, str]] = []
    blocking_prompt = BlockingPromptController()

    async def handle_prompt(text: str) -> None:
        prompts.append(text)
        if text == "change":
            scenario.app.begin_assistant()
            scenario.app.append_assistant_chunk("fresh change")
            return
        scenario.app.begin_assistant()
        scenario.app.append_assistant_chunk("working")
        await blocking_prompt.wait_until_settled()

    async def handle_steer(text: str) -> None:
        steers.append(("queue" if scenario.app.state.running else "execute", text))

    with blocking_prompt:
        result = (
            scenario.type_text("go")
            .enter()
            .wait(0.01)
            .type_text("change")
            .enter()
            .wait(0.01)
            .escape()
            .wait(0.04)
            .end_input()
            .run(
                handle_prompt=handle_prompt,
                handle_steer=handle_steer,
                on_abort=blocking_prompt.settle_on_abort,
            )
        )

    with result.write_artifacts_on_failure_from_env(
        basename="screen-loop-running-steer-escape"
    ):
        result.assert_exit_code(0)
        assert prompts == ["go", "change"]
        assert steers == [("queue", "change")]
        result.assert_text_contains("› go")
        result.assert_text_contains("› change")
        result.assert_text_contains("fresh change")
        result.assert_text_contains("Conversation interrupted")
        result.assert_no_clear_screen()


def _step_visible_text(result, step_index: int) -> str:
    step = result.steps[step_index]
    assert step.frame is not None
    return strip_control_sequences("\n".join(step.frame.screen_after.visible_lines))


def test_screen_tui_loop_playback_writes_artifacts_for_manual_inspection(
    tmp_path,
) -> None:
    prompts: list[str] = []

    async def handle_prompt(text: str) -> None:
        prompts.append(text)

    result = (
        ScreenTuiLoopScenario()
        .type_text("hello")
        .enter()
        .end_input()
        .run(handle_prompt=handle_prompt)
    )

    artifacts = result.write_artifacts(
        tmp_path / "loop-artifacts", basename="basic-loop"
    )

    assert prompts == ["hello"]
    assert artifacts.raw == tmp_path / "loop-artifacts" / "basic-loop-raw.txt"
    assert artifacts.text == tmp_path / "loop-artifacts" / "basic-loop-text.txt"
    assert artifacts.state == tmp_path / "loop-artifacts" / "basic-loop-state.json"
    assert "› hello" in artifacts.text.read_text(encoding="utf-8")
    assert json.loads(artifacts.state.read_text(encoding="utf-8")) == {
        "exit_code": 0,
        "conversation": {
            "composer_text": "",
            "running": False,
            "pending_steers": [],
            "pending_followups": [],
        },
    }


def test_screen_tui_loop_playback_writes_artifacts_when_wrapped_assertion_fails(
    tmp_path,
) -> None:
    result = ScreenTuiLoopScenario().type_text("hello").enter().end_input().run()

    with pytest.raises(AssertionError):
        with result.write_artifacts_on_failure(
            tmp_path / "loop-failures", basename="missing-text"
        ):
            result.assert_text_contains("missing")

    assert (tmp_path / "loop-failures" / "missing-text-raw.txt").exists()
    text = tmp_path / "loop-failures" / "missing-text-text.txt"
    state = tmp_path / "loop-failures" / "missing-text-state.json"
    assert "› hello" in text.read_text(encoding="utf-8")
    assert json.loads(state.read_text(encoding="utf-8"))["exit_code"] == 0


def test_screen_tui_loop_playback_writes_failure_artifacts_to_env_directory(
    tmp_path,
) -> None:
    result = ScreenTuiLoopScenario().type_text("hello").enter().end_input().run()
    artifact_root = tmp_path / "loop-env-artifacts"

    with pytest.raises(AssertionError):
        with result.write_artifacts_on_failure_from_env(
            basename="loop-missing-text",
            env={PLAYBACK_ARTIFACTS_ENV: str(artifact_root)},
        ):
            result.assert_text_contains("missing")

    text = artifact_root / "loop-missing-text-text.txt"
    state = artifact_root / "loop-missing-text-state.json"
    assert "› hello" in text.read_text(encoding="utf-8")
    assert json.loads(state.read_text(encoding="utf-8"))["exit_code"] == 0


def test_screen_tui_loop_scenario_scripts_character_input() -> None:
    prompts: list[str] = []

    async def handle_prompt(text: str) -> None:
        prompts.append(text)

    result = (
        ScreenTuiLoopScenario()
        .type_chars("hello")
        .enter()
        .end_input()
        .run(handle_prompt=handle_prompt)
    )

    result.assert_exit_code(0)
    assert prompts == ["hello"]
    result.assert_text_contains("› hello")


def test_screen_tui_loop_scenario_drives_escape_pending_steer_flow() -> None:
    scenario = ScreenTuiLoopScenario()
    prompts: list[str] = []
    steers: list[str] = []
    blocking_prompt = BlockingPromptController()

    async def handle_prompt(text: str) -> None:
        prompts.append(text)
        if text == "fresh":
            scenario.app.begin_assistant()
            scenario.app.append_assistant_chunk("fresh response")
            return
        scenario.app.begin_assistant()
        scenario.app.append_assistant_chunk("old response")
        await blocking_prompt.wait_until_settled()

    async def handle_steer(text: str) -> None:
        steers.append(text)

    with blocking_prompt:
        result = (
            scenario.type_text("old")
            .enter()
            .wait(0.01)
            .type_text("fresh")
            .enter()
            .wait(0.01)
            .escape()
            .wait(0.04)
            .end_input()
            .run(
                handle_prompt=handle_prompt,
                handle_steer=handle_steer,
                on_abort=blocking_prompt.settle_on_abort,
            )
        )

    with result.write_artifacts_on_failure_from_env(
        basename="screen-loop-escape-pending-steer"
    ):
        result.assert_exit_code(0)
        result.assert_text_contains("› old")
        result.assert_text_contains("› fresh")
        result.assert_text_contains("fresh response")
        result.assert_text_not_contains("Request cancelled")
        result.assert_no_clear_screen()
        result.assert_idle()
        result.assert_pending_steers()
        result.assert_composer_text("")
        assert prompts == ["old", "fresh"]
        assert steers == ["fresh"]


def test_screen_tui_loop_scenario_keeps_pending_steer_fifo_on_escape() -> None:
    scenario = ScreenTuiLoopScenario().with_pending_steers("prequeued")
    prompts: list[str] = []
    steers: list[str] = []
    blocking_prompt = BlockingPromptController()

    async def handle_prompt(text: str) -> None:
        if text == "prequeued":
            prompts.append(text)
            return
        scenario.app.begin_assistant()
        scenario.app.append_assistant_chunk("working")
        await blocking_prompt.wait_until_settled()

    async def handle_steer(text: str) -> None:
        steers.append(text)

    with blocking_prompt:
        result = (
            scenario.type_text("start")
            .enter()
            .wait(0.01)
            .type_text("running steer")
            .enter()
            .wait(0.01)
            .escape()
            .wait(0.04)
            .end_input()
            .run(
                handle_prompt=handle_prompt,
                handle_steer=handle_steer,
                on_abort=blocking_prompt.settle_on_abort,
            )
        )

    with result.write_artifacts_on_failure_from_env(
        basename="screen-loop-escape-pending-fifo"
    ):
        result.assert_exit_code(0)
        assert steers == ["running steer"]
        assert prompts == ["prequeued"]
        result.assert_pending_steers("running steer")


def test_screen_tui_loop_scenario_preserves_composer_draft_when_escape_runs_pending_steer() -> (
    None
):
    scenario = ScreenTuiLoopScenario().with_pending_steers("queued")
    prompts: list[str] = []
    blocking_prompt = BlockingPromptController()

    async def handle_prompt(text: str) -> None:
        if text == "queued":
            prompts.append(text)
            return
        await blocking_prompt.wait_until_settled()

    with blocking_prompt:
        result = (
            scenario.type_text("start")
            .enter()
            .wait(0.01)
            .type_text("draft")
            .wait(0.01)
            .escape()
            .wait(0.04)
            .end_input()
            .run(
                handle_prompt=handle_prompt,
                on_abort=blocking_prompt.settle_on_abort,
            )
        )

    with result.write_artifacts_on_failure_from_env(
        basename="screen-loop-escape-preserves-draft"
    ):
        result.assert_exit_code(0)
        assert prompts == ["queued"]
        result.assert_composer_text("draft")
        result.assert_pending_steers()
