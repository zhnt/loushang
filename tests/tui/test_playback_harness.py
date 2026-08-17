from __future__ import annotations

import json

import pytest

from loushang.tui import (
    PLAYBACK_ARTIFACTS_ENV,
    FakeTerminalPort,
    MarkdownRenderer,
    PlaybackEvent,
    PlaybackFrameBudget,
    PlaybackHarness,
    PlaybackResult,
    PlaybackScenario,
    RenderConstraints,
    RenderDiagnostics,
    TerminalFrame,
    TerminalOperation,
    TerminalSize,
    ThemeResolver,
    playback_artifacts_directory_from_env,
)


def test_fake_terminal_port_records_successful_and_failed_flushes() -> None:
    port = FakeTerminalPort(size=TerminalSize(columns=80, rows=24))
    write = TerminalOperation.write("hello")

    port.flush([write])
    port.fail_next_flush(RuntimeError("boom"))
    try:
        port.flush([TerminalOperation.clear_line()])
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("expected flush failure")

    assert port.size() == TerminalSize(columns=80, rows=24)
    assert port.flushes == ((write,),)
    assert port.failed_flushes == ((TerminalOperation.clear_line(),),)


def test_fake_terminal_port_can_bound_recorded_history() -> None:
    port = FakeTerminalPort(
        size=TerminalSize(columns=80, rows=24),
        flush_history_limit=1,
        frame_history_limit=1,
    )

    port.flush([TerminalOperation.write("first")])
    port.flush([TerminalOperation.write("second")])

    assert port.flushes == ((TerminalOperation.write("second"),),)
    assert len(port.frames) == 1
    assert port.frames[0].serialized_output == "second"
    assert port.screen.visible_lines[0].startswith("firstsecond")


def test_playback_harness_records_diagnostics_for_scripted_events() -> None:
    def render(
        event: PlaybackEvent, size: TerminalSize, previous: RenderDiagnostics | None
    ) -> RenderDiagnostics:
        previous_lines = previous.current_logical_lines if previous is not None else ()
        text = f"{event.kind}:{event.payload}@{size.columns}x{size.rows}"
        return RenderDiagnostics(
            current_logical_lines=(text,),
            previous_rendered_lines=previous_lines,
            changed_line_range=(0, 0),
            logical_cursor_row=0,
            hardware_cursor_row=0,
            operations=(TerminalOperation.write(text),),
        )

    harness = PlaybackHarness(
        render=render, port=FakeTerminalPort(size=TerminalSize(columns=40, rows=10))
    )

    steps = harness.play([PlaybackEvent("key", "a"), PlaybackEvent("stream", "chunk")])

    assert [step.event.kind for step in steps] == ["key", "stream"]
    assert steps[0].diagnostics.current_logical_lines == ("key:a@40x10",)
    assert steps[1].diagnostics.previous_rendered_lines == ("key:a@40x10",)
    assert harness.port.flushes == (
        (TerminalOperation.write("key:a@40x10"),),
        (TerminalOperation.write("stream:chunk@40x10"),),
    )


def test_playback_harness_resize_event_updates_terminal_size_before_render() -> None:
    seen_sizes: list[TerminalSize] = []

    def render(
        event: PlaybackEvent, size: TerminalSize, previous: RenderDiagnostics | None
    ) -> RenderDiagnostics:
        seen_sizes.append(size)
        return RenderDiagnostics(
            current_logical_lines=(event.kind,),
            previous_rendered_lines=previous.current_logical_lines
            if previous is not None
            else (),
        )

    harness = PlaybackHarness(
        render=render, port=FakeTerminalPort(size=TerminalSize(columns=80, rows=24))
    )

    steps = harness.play([PlaybackEvent.resize(columns=100, rows=40)])

    assert seen_sizes == [TerminalSize(columns=100, rows=40)]
    assert steps[0].size == TerminalSize(columns=100, rows=40)


def test_playback_event_input_carries_raw_terminal_input_chunk() -> None:
    event = PlaybackEvent.input("/model gpt\t")

    assert event.kind == "input"
    assert event.payload == "/model gpt\t"


def test_playback_scenario_scripts_common_terminal_events() -> None:
    scenario = (
        PlaybackScenario()
        .type_text("hello")
        .enter()
        .tab()
        .escape()
        .resize(width=42, height=8)
        .render()
    )

    assert scenario.events == (
        PlaybackEvent.input("hello"),
        PlaybackEvent.input("\r"),
        PlaybackEvent.input("\t"),
        PlaybackEvent.input("\x1b"),
        PlaybackEvent.resize(columns=42, rows=8),
        PlaybackEvent("render"),
    )


def test_playback_scenario_can_script_character_by_character_input() -> None:
    scenario = PlaybackScenario().type_chars("abc")

    assert scenario.events == (
        PlaybackEvent.input("a"),
        PlaybackEvent.input("b"),
        PlaybackEvent.input("c"),
    )


def test_playback_result_asserts_visible_text_and_flush_policy() -> None:
    harness = PlaybackHarness(
        render=lambda _event, _size, _previous: RenderDiagnostics(
            current_logical_lines=("hello",),
            operations=(TerminalOperation.write("hello"),),
        ),
        port=FakeTerminalPort(size=TerminalSize(columns=20, rows=5)),
    )

    result = PlaybackResult(
        steps=harness.play([PlaybackEvent("render")]), port=harness.port
    )

    result.assert_all_flush_succeeded()
    result.assert_visible_contains("hello")
    result.assert_visible_not_contains("missing")
    result.assert_no_clear_screen()


def test_playback_result_asserts_frame_output_contains_ansi_style_sequence() -> None:
    harness = PlaybackHarness(
        render=lambda _event, _size, _previous: RenderDiagnostics(
            current_logical_lines=("selected",),
            operations=(TerminalOperation.write("a\x1b[7mb\x1b[27mc"),),
        ),
        port=FakeTerminalPort(size=TerminalSize(columns=20, rows=5)),
    )
    result = PlaybackResult(
        steps=harness.play([PlaybackEvent.input("select")]), port=harness.port
    )

    result.assert_frame_output_contains(0, "\x1b[7mb\x1b[27m")
    result.assert_any_frame_output_contains("\x1b[7mb\x1b[27m")

    with pytest.raises(AssertionError, match="expected step 0 frame output"):
        result.assert_frame_output_contains(0, "\x1b[1;36m")


def test_playback_result_writes_jsonl_for_manual_inspection(tmp_path) -> None:
    harness = PlaybackHarness(
        render=lambda _event, _size, _previous: RenderDiagnostics(
            current_logical_lines=("hello",),
            operation_class="changed_range_update",
            hardware_cursor_row=0,
            hardware_cursor_column=5,
            operations=(TerminalOperation.write("hello"),),
        ),
        port=FakeTerminalPort(size=TerminalSize(columns=20, rows=5)),
    )
    result = PlaybackResult(
        steps=harness.play([PlaybackEvent.input("hello")]), port=harness.port
    )
    path = tmp_path / "playback.jsonl"

    result.write_jsonl(path)

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows == [
        {
            "index": 0,
            "event": {"kind": "input", "payload": "hello"},
            "size": {"columns": 20, "rows": 5},
            "operation_class": "changed_range_update",
            "changed_line_range": None,
            "logical_cursor": {"row": 0, "column": 0},
            "viewport": {"top": 0, "previous_top": 0},
            "hardware_cursor": {"row": 0, "column": 5},
            "screen_cursor": {"row": 0, "column": 5},
            "flush_succeeded": True,
            "flush_error": None,
            "operation_count": 1,
            "operations": ["write"],
            "serialized_output_bytes": 5,
            "changed_visible_lines": 1,
            "synchronized": False,
            "clear_scrollback_emitted": False,
            "visible_lines": ["hello", "", "", "", ""],
            "scrollback_lines": [],
        }
    ]
    assert "serialized_output" not in rows[0]


def test_playback_result_asserts_last_cursor_on_visible_line() -> None:
    harness = PlaybackHarness(
        render=lambda _event, _size, _previous: RenderDiagnostics(
            current_logical_lines=("status", "› hello"),
            logical_cursor_row=1,
            logical_cursor_column=7,
            hardware_cursor_row=1,
            hardware_cursor_column=7,
            operations=(
                TerminalOperation.write("status"),
                TerminalOperation.newline(),
                TerminalOperation.write("› hello"),
                TerminalOperation.move_column(column=7),
            ),
        ),
        port=FakeTerminalPort(size=TerminalSize(columns=20, rows=5)),
    )
    result = PlaybackResult(
        steps=harness.play([PlaybackEvent.input("hello")]), port=harness.port
    )

    result.assert_last_cursor_on_visible_line("› hello", column=7)

    with pytest.raises(AssertionError, match="expected cursor row"):
        result.assert_last_cursor_on_visible_line("status", column=7)
    with pytest.raises(AssertionError, match="expected cursor column"):
        result.assert_last_cursor_on_visible_line("› hello", column=6)


def test_playback_result_can_include_raw_frame_output_in_jsonl(tmp_path) -> None:
    harness = PlaybackHarness(
        render=lambda _event, _size, _previous: RenderDiagnostics(
            current_logical_lines=("hello",),
            operations=(TerminalOperation.write("hello"),),
        ),
        port=FakeTerminalPort(size=TerminalSize(columns=20, rows=5)),
    )
    result = PlaybackResult(
        steps=harness.play([PlaybackEvent("render")]), port=harness.port
    )
    path = tmp_path / "playback.jsonl"

    result.write_jsonl(path, include_frames=True)

    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["serialized_output"] == "hello"


def test_playback_result_writes_trace_and_final_screen_artifacts(tmp_path) -> None:
    harness = PlaybackHarness(
        render=lambda _event, _size, _previous: RenderDiagnostics(
            current_logical_lines=("hello",),
            operation_class="changed_range_update",
            operations=(TerminalOperation.write("hello"),),
        ),
        port=FakeTerminalPort(size=TerminalSize(columns=20, rows=5)),
    )
    result = PlaybackResult(
        steps=harness.play([PlaybackEvent.input("hello")]), port=harness.port
    )

    artifacts = result.write_artifacts(
        tmp_path / "artifacts", basename="long-transcript", include_frames=True
    )

    assert artifacts.trace == tmp_path / "artifacts" / "long-transcript.jsonl"
    assert artifacts.screen == tmp_path / "artifacts" / "long-transcript-screen.txt"
    assert (
        artifacts.terminal
        == tmp_path / "artifacts" / "long-transcript-terminal.txt"
    )
    trace_row = json.loads(artifacts.trace.read_text(encoding="utf-8"))
    assert trace_row["operation_class"] == "changed_range_update"
    assert trace_row["serialized_output"] == "hello"
    assert artifacts.screen.read_text(encoding="utf-8") == "hello\n\n\n\n"
    assert artifacts.terminal.read_text(encoding="utf-8") == "hello\n\n\n\n"


def test_playback_result_writes_artifacts_when_wrapped_assertion_fails(
    tmp_path,
) -> None:
    harness = PlaybackHarness(
        render=lambda _event, _size, _previous: RenderDiagnostics(
            current_logical_lines=("hello",),
            operations=(TerminalOperation.write("hello"),),
        ),
        port=FakeTerminalPort(size=TerminalSize(columns=20, rows=5)),
    )
    result = PlaybackResult(
        steps=harness.play([PlaybackEvent.input("hello")]), port=harness.port
    )

    with pytest.raises(AssertionError):
        with result.write_artifacts_on_failure(
            tmp_path / "failures", basename="missing-text", include_frames=True
        ):
            result.assert_visible_contains("missing")

    trace = tmp_path / "failures" / "missing-text.jsonl"
    screen = tmp_path / "failures" / "missing-text-screen.txt"
    assert trace.exists()
    assert screen.exists()
    assert json.loads(trace.read_text(encoding="utf-8"))["serialized_output"] == "hello"
    assert screen.read_text(encoding="utf-8") == "hello\n\n\n\n"


def test_playback_result_does_not_write_artifacts_when_wrapped_assertion_passes(
    tmp_path,
) -> None:
    harness = PlaybackHarness(
        render=lambda _event, _size, _previous: RenderDiagnostics(
            current_logical_lines=("hello",),
            operations=(TerminalOperation.write("hello"),),
        ),
        port=FakeTerminalPort(size=TerminalSize(columns=20, rows=5)),
    )
    result = PlaybackResult(
        steps=harness.play([PlaybackEvent.input("hello")]), port=harness.port
    )

    with result.write_artifacts_on_failure(tmp_path / "failures", basename="passing"):
        result.assert_visible_contains("hello")

    assert not (tmp_path / "failures").exists()


def test_playback_result_writes_failure_artifacts_to_env_directory(tmp_path) -> None:
    harness = PlaybackHarness(
        render=lambda _event, _size, _previous: RenderDiagnostics(
            current_logical_lines=("hello",),
            operations=(TerminalOperation.write("hello"),),
        ),
        port=FakeTerminalPort(size=TerminalSize(columns=20, rows=5)),
    )
    result = PlaybackResult(
        steps=harness.play([PlaybackEvent.input("hello")]), port=harness.port
    )
    artifact_root = tmp_path / "env-artifacts"

    with pytest.raises(AssertionError):
        with result.write_artifacts_on_failure_from_env(
            basename="env-missing-text",
            include_frames=True,
            env={PLAYBACK_ARTIFACTS_ENV: str(artifact_root)},
        ):
            result.assert_visible_contains("missing")

    trace = artifact_root / "env-missing-text.jsonl"
    screen = artifact_root / "env-missing-text-screen.txt"
    assert json.loads(trace.read_text(encoding="utf-8"))["serialized_output"] == "hello"
    assert screen.read_text(encoding="utf-8") == "hello\n\n\n\n"


def test_playback_result_skips_env_artifacts_when_env_directory_is_unset(
    tmp_path,
) -> None:
    harness = PlaybackHarness(
        render=lambda _event, _size, _previous: RenderDiagnostics(
            current_logical_lines=("hello",),
            operations=(TerminalOperation.write("hello"),),
        ),
        port=FakeTerminalPort(size=TerminalSize(columns=20, rows=5)),
    )
    result = PlaybackResult(
        steps=harness.play([PlaybackEvent.input("hello")]), port=harness.port
    )

    with pytest.raises(AssertionError):
        with result.write_artifacts_on_failure_from_env(basename="missing", env={}):
            result.assert_visible_contains("missing")

    assert not (tmp_path / "missing.jsonl").exists()


def test_playback_artifacts_directory_from_env_respects_explicit_empty_env(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv(PLAYBACK_ARTIFACTS_ENV, str(tmp_path / "ambient"))

    assert playback_artifacts_directory_from_env({}) is None


def test_playback_result_asserts_operation_class_budget_after_initial_frame() -> None:
    operation_classes = iter(
        ("first_render", "changed_range_update", "baseline_repaint")
    )

    def render(
        _event: PlaybackEvent, _size: TerminalSize, _previous: RenderDiagnostics | None
    ) -> RenderDiagnostics:
        return RenderDiagnostics(
            current_logical_lines=("hello",),
            operation_class=next(operation_classes),
            operations=(TerminalOperation.write("hello"),),
        )

    harness = PlaybackHarness(
        render=render, port=FakeTerminalPort(size=TerminalSize(columns=20, rows=5))
    )
    result = PlaybackResult(
        steps=harness.play(
            [
                PlaybackEvent("render"),
                PlaybackEvent.input("a"),
                PlaybackEvent.input("b"),
            ]
        ),
        port=harness.port,
    )

    with pytest.raises(AssertionError, match="baseline_repaint"):
        result.assert_operation_classes_not_in(
            "baseline_repaint", "recovery_repaint", skip_first=True
        )


def test_playback_result_asserts_max_operations_per_step_after_initial_frame() -> None:
    operation_batches = iter(
        (
            (
                TerminalOperation.write("initial"),
                TerminalOperation.newline(),
                TerminalOperation.write("frame"),
            ),
            (TerminalOperation.write("ok"), TerminalOperation.move_column(column=1)),
            (
                TerminalOperation.write("too"),
                TerminalOperation.newline(),
                TerminalOperation.write("many"),
            ),
        )
    )

    def render(
        _event: PlaybackEvent, _size: TerminalSize, _previous: RenderDiagnostics | None
    ) -> RenderDiagnostics:
        operations = next(operation_batches)
        return RenderDiagnostics(
            current_logical_lines=("hello",), operations=operations
        )

    harness = PlaybackHarness(
        render=render, port=FakeTerminalPort(size=TerminalSize(columns=20, rows=5))
    )
    result = PlaybackResult(
        steps=harness.play(
            [
                PlaybackEvent("render"),
                PlaybackEvent.input("a"),
                PlaybackEvent.input("b"),
            ]
        ),
        port=harness.port,
    )

    with pytest.raises(AssertionError, match="step 2 emitted 3 operations"):
        result.assert_max_operations_per_step(2, skip_first=True)


def test_playback_result_asserts_max_serialized_output_bytes_per_step() -> None:
    frames = iter(
        (
            (TerminalOperation.write("small"),),
            (TerminalOperation.write("x" * 40),),
        )
    )

    def render(
        _event: PlaybackEvent, _size: TerminalSize, _previous: RenderDiagnostics | None
    ) -> RenderDiagnostics:
        return RenderDiagnostics(
            current_logical_lines=("frame",), operations=next(frames)
        )

    harness = PlaybackHarness(
        render=render, port=FakeTerminalPort(size=TerminalSize(columns=80, rows=24))
    )
    result = PlaybackResult(
        steps=harness.play([PlaybackEvent("render"), PlaybackEvent.input("x")]),
        port=harness.port,
    )

    with pytest.raises(AssertionError, match="step 1 emitted 40 serialized bytes"):
        result.assert_max_serialized_output_bytes_per_step(20, skip_first=True)


def test_playback_result_asserts_max_changed_visible_lines_per_step() -> None:
    frames = iter(
        (
            (
                TerminalOperation.clear_screen(),
                TerminalOperation.write("alpha"),
                TerminalOperation.newline(),
                TerminalOperation.write("beta"),
            ),
            (
                TerminalOperation.move_cursor(row=0, column=0),
                TerminalOperation.clear_line(),
                TerminalOperation.write("ALPHA"),
                TerminalOperation.newline(),
                TerminalOperation.clear_line(),
                TerminalOperation.write("BETA"),
            ),
        )
    )

    def render(
        _event: PlaybackEvent, _size: TerminalSize, _previous: RenderDiagnostics | None
    ) -> RenderDiagnostics:
        return RenderDiagnostics(
            current_logical_lines=("frame",), operations=next(frames)
        )

    harness = PlaybackHarness(
        render=render, port=FakeTerminalPort(size=TerminalSize(columns=20, rows=5))
    )
    result = PlaybackResult(
        steps=harness.play([PlaybackEvent("render"), PlaybackEvent.input("x")]),
        port=harness.port,
    )

    with pytest.raises(AssertionError, match="step 1 changed 2 visible lines"):
        result.assert_max_changed_visible_lines_per_step(1, skip_first=True)


def test_playback_result_asserts_screen_anchor_row_stability() -> None:
    frames = iter(
        (
            (
                TerminalOperation.clear_screen(),
                TerminalOperation.write("top"),
                TerminalOperation.newline(),
                TerminalOperation.write("anchor"),
            ),
            (
                TerminalOperation.clear_screen(),
                TerminalOperation.write("anchor"),
                TerminalOperation.newline(),
                TerminalOperation.write("bottom"),
            ),
        )
    )

    def render(
        _event: PlaybackEvent, _size: TerminalSize, _previous: RenderDiagnostics | None
    ) -> RenderDiagnostics:
        return RenderDiagnostics(
            current_logical_lines=("frame",), operations=next(frames)
        )

    harness = PlaybackHarness(
        render=render, port=FakeTerminalPort(size=TerminalSize(columns=20, rows=5))
    )
    result = PlaybackResult(
        steps=harness.play([PlaybackEvent("render"), PlaybackEvent("render")]),
        port=harness.port,
    )

    with pytest.raises(
        AssertionError, match="anchor 'anchor' moved from row 1 to row 0 at step 1"
    ):
        result.assert_screen_anchor_stable("anchor")


def test_playback_result_asserts_synchronized_frames() -> None:
    frames = iter(
        (
            (
                TerminalOperation.begin_synchronized_update(),
                TerminalOperation.write("safe"),
                TerminalOperation.end_synchronized_update(),
            ),
            (TerminalOperation.write("unsafe"),),
        )
    )

    def render(
        _event: PlaybackEvent, _size: TerminalSize, _previous: RenderDiagnostics | None
    ) -> RenderDiagnostics:
        return RenderDiagnostics(
            current_logical_lines=("frame",), operations=next(frames)
        )

    harness = PlaybackHarness(
        render=render, port=FakeTerminalPort(size=TerminalSize(columns=20, rows=5))
    )
    result = PlaybackResult(
        steps=harness.play([PlaybackEvent("render"), PlaybackEvent("render")]),
        port=harness.port,
    )

    with pytest.raises(AssertionError, match="step 1 was not synchronized"):
        result.assert_synchronized_frames()


def test_playback_frame_budget_asserts_incremental_render_contract() -> None:
    frames = iter(
        (
            (
                TerminalOperation.begin_synchronized_update(),
                TerminalOperation.write("hello"),
                TerminalOperation.end_synchronized_update(),
            ),
            (
                TerminalOperation.begin_synchronized_update(),
                TerminalOperation.write("!"),
                TerminalOperation.end_synchronized_update(),
            ),
        )
    )
    operation_classes = iter(("first_render", "changed_range_update"))

    def render(
        _event: PlaybackEvent, _size: TerminalSize, _previous: RenderDiagnostics | None
    ) -> RenderDiagnostics:
        return RenderDiagnostics(
            current_logical_lines=("frame",),
            operation_class=next(operation_classes),
            operations=next(frames),
        )

    harness = PlaybackHarness(
        render=render, port=FakeTerminalPort(size=TerminalSize(columns=20, rows=5))
    )
    result = PlaybackResult(
        steps=harness.play([PlaybackEvent("render"), PlaybackEvent.input("!")]),
        port=harness.port,
    )
    budget = PlaybackFrameBudget(
        disallowed_operation_classes=("baseline_repaint", "recovery_repaint"),
        max_operations=3,
        max_serialized_output_bytes=32,
        max_changed_visible_lines=1,
        require_synchronized=True,
    )

    budget.assert_result(result, skip_first=True)


def test_playback_frame_budget_reports_operation_count_violation() -> None:
    frames = iter(
        (
            (
                TerminalOperation.begin_synchronized_update(),
                TerminalOperation.write("hello"),
                TerminalOperation.end_synchronized_update(),
            ),
            (
                TerminalOperation.begin_synchronized_update(),
                TerminalOperation.write("too"),
                TerminalOperation.write("many"),
                TerminalOperation.end_synchronized_update(),
            ),
        )
    )

    def render(
        _event: PlaybackEvent, _size: TerminalSize, _previous: RenderDiagnostics | None
    ) -> RenderDiagnostics:
        return RenderDiagnostics(
            current_logical_lines=("frame",),
            operation_class="changed_range_update",
            operations=next(frames),
        )

    harness = PlaybackHarness(
        render=render, port=FakeTerminalPort(size=TerminalSize(columns=20, rows=5))
    )
    result = PlaybackResult(
        steps=harness.play([PlaybackEvent("render"), PlaybackEvent.input("!")]),
        port=harness.port,
    )

    with pytest.raises(AssertionError, match="step 1 emitted 4 operations"):
        PlaybackFrameBudget(max_operations=3).assert_result(result, skip_first=True)


def test_playback_frame_budget_allows_noop_frames_when_requiring_synchronization() -> (
    None
):
    frames = iter(
        (
            (
                TerminalOperation.begin_synchronized_update(),
                TerminalOperation.write("hello"),
                TerminalOperation.end_synchronized_update(),
            ),
            (),
        )
    )
    operation_classes = iter(("first_render", "noop"))

    def render(
        _event: PlaybackEvent, _size: TerminalSize, _previous: RenderDiagnostics | None
    ) -> RenderDiagnostics:
        return RenderDiagnostics(
            current_logical_lines=("frame",),
            operation_class=next(operation_classes),
            operations=next(frames),
        )

    harness = PlaybackHarness(
        render=render, port=FakeTerminalPort(size=TerminalSize(columns=20, rows=5))
    )
    result = PlaybackResult(
        steps=harness.play([PlaybackEvent("render"), PlaybackEvent.input("noop")]),
        port=harness.port,
    )

    PlaybackFrameBudget(require_synchronized=True).assert_result(
        result, skip_first=True
    )


def test_playback_harness_failed_flush_does_not_advance_successful_diagnostics() -> (
    None
):
    def render(
        event: PlaybackEvent, size: TerminalSize, previous: RenderDiagnostics | None
    ) -> RenderDiagnostics:
        previous_lines = previous.current_logical_lines if previous is not None else ()
        return RenderDiagnostics(
            current_logical_lines=(str(event.payload),),
            previous_rendered_lines=previous_lines,
            operations=(TerminalOperation.write(str(event.payload)),),
        )

    port = FakeTerminalPort(size=TerminalSize(columns=80, rows=24))
    harness = PlaybackHarness(render=render, port=port)
    first = harness.play([PlaybackEvent("product", "first")])
    port.fail_next_flush(RuntimeError("write failed"))
    second = harness.play([PlaybackEvent("product", "second")])
    third = harness.play([PlaybackEvent("product", "third")])

    assert first[0].flush_error is None
    assert second[0].flush_error == "write failed"
    assert second[0].diagnostics.previous_rendered_lines == ("first",)
    assert third[0].diagnostics.previous_rendered_lines == ("first",)
    assert harness.previous_successful_diagnostics is not None
    assert harness.previous_successful_diagnostics.current_logical_lines == ("third",)


def test_terminal_frame_records_serialized_synchronized_flush_and_screen_snapshots() -> (
    None
):
    port = FakeTerminalPort(size=TerminalSize(columns=8, rows=3))

    frame = port.flush(
        [
            TerminalOperation.begin_synchronized_update(),
            TerminalOperation.write("one"),
            TerminalOperation.newline(),
            TerminalOperation.write("two"),
            TerminalOperation.end_synchronized_update(),
        ]
    )

    assert isinstance(frame, TerminalFrame)
    assert frame.serialized_output == "\x1b[?2026hone\r\ntwo\x1b[?2026l"
    assert frame.synchronized is True
    assert frame.clear_scrollback_emitted is False
    assert frame.screen_before.visible_lines == ("", "", "")
    assert frame.screen_after.visible_lines == ("one", "two", "")
    assert frame.screen_after.cursor_row == 1
    assert frame.screen_after.cursor_column == 3


def test_terminal_frame_treats_pi_style_cursor_after_sync_as_synchronized_render() -> (
    None
):
    port = FakeTerminalPort(size=TerminalSize(columns=8, rows=3))

    frame = port.flush(
        [
            TerminalOperation.hide_cursor(),
            TerminalOperation.begin_synchronized_update(),
            TerminalOperation.write("abc"),
            TerminalOperation.end_synchronized_update(),
            TerminalOperation.move_column(column=1),
            TerminalOperation.show_cursor(),
        ]
    )

    assert frame.synchronized is True
    assert (
        frame.serialized_output == "\x1b[?25l\x1b[?2026habc\x1b[?2026l\x1b[2G\x1b[?25h"
    )
    assert frame.screen_after.visible_lines[0] == "abc"
    assert frame.screen_after.cursor_row == 0
    assert frame.screen_after.cursor_column == 1


def test_fake_screen_models_natural_scroll_and_line_rewrite() -> None:
    port = FakeTerminalPort(size=TerminalSize(columns=4, rows=2))

    port.flush(
        [
            TerminalOperation.write("aa"),
            TerminalOperation.newline(),
            TerminalOperation.write("bb"),
            TerminalOperation.newline(),
            TerminalOperation.write("cc"),
        ]
    )
    assert port.screen.visible_lines == ("bb", "cc")
    assert port.screen.viewport_top == 1

    port.flush(
        [
            TerminalOperation.move_cursor(row=1, column=0),
            TerminalOperation.clear_line(),
            TerminalOperation.write("dd"),
        ]
    )

    assert port.screen.visible_lines == ("bb", "dd")
    assert port.screen.cursor_row == 1
    assert port.screen.cursor_column == 2


def test_fake_screen_clears_autowrap_pending_on_cursor_movement() -> None:
    port = FakeTerminalPort(size=TerminalSize(columns=4, rows=3))

    port.flush(
        [
            TerminalOperation.write("abcd"),
            TerminalOperation.move_relative(lines=1),
            TerminalOperation.write("Z"),
        ]
    )

    assert port.screen.visible_lines == ("abcd", "   Z", "")
    assert port.screen.cursor_row == 1
    assert port.screen.cursor_column == 3


def test_fake_screen_wraps_before_next_printable_after_full_width_write() -> None:
    port = FakeTerminalPort(size=TerminalSize(columns=4, rows=3))

    port.flush([TerminalOperation.write("abcdZ")])

    assert port.screen.visible_lines == ("abcd", "Z", "")
    assert port.screen.cursor_row == 1
    assert port.screen.cursor_column == 1


def test_fake_screen_tracks_sgr_cell_styles_and_resets_them_after_terminal_resets() -> (
    None
):
    port = FakeTerminalPort(size=TerminalSize(columns=20, rows=3))

    port.flush([TerminalOperation.write("\x1b[3;90mthink\x1b[23;39m\ninput")])

    assert port.screen.cell_style(row=0, column=0).italic is True
    assert port.screen.cell_style(row=0, column=0).foreground == "90"
    assert port.screen.cell_style(row=1, column=0).italic is False
    assert port.screen.cell_style(row=1, column=0).foreground is None


def test_fake_screen_proves_markdown_heading_underline_does_not_leak_into_following_cells() -> (
    None
):
    theme = ThemeResolver(defaults={"markdown.heading.level1": {"color": "cyan"}})
    heading = (
        MarkdownRenderer("# Important distinction from `open()`", theme=theme)
        .render(RenderConstraints(width=80, max_height=3))
        .lines[0]
        .text
    )
    port = FakeTerminalPort(size=TerminalSize(columns=80, rows=3))

    port.flush([TerminalOperation.write(heading), TerminalOperation.write(" plain")])

    plain_column = len("Important distinction from open() ")
    assert port.screen.visible_lines[0].startswith(
        "Important distinction from open() plain"
    )
    assert port.screen.cell_style(row=0, column=0).underline is True
    assert port.screen.cell_style(row=0, column=plain_column).underline is False


def test_playback_step_asserts_operation_class_and_scrollback_policy() -> None:
    def render(
        event: PlaybackEvent, size: TerminalSize, previous: RenderDiagnostics | None
    ) -> RenderDiagnostics:
        return RenderDiagnostics(
            current_logical_lines=("resized",),
            previous_rendered_lines=previous.current_logical_lines
            if previous is not None
            else (),
            operation_class="resize_repaint",
            width_changed=True,
            height_changed=True,
            repaint_kind="resize",
            clear_scrollback_policy="disabled",
            operations=(
                TerminalOperation.begin_synchronized_update(),
                TerminalOperation.clear_screen(),
                TerminalOperation.write(f"{size.columns}x{size.rows}"),
                TerminalOperation.end_synchronized_update(),
            ),
        )

    harness = PlaybackHarness(
        render=render, port=FakeTerminalPort(size=TerminalSize(columns=80, rows=24))
    )

    step = harness.play([PlaybackEvent.resize(columns=100, rows=30)])[0]

    step.assert_operation_class("resize_repaint")
    step.assert_no_clear_scrollback()
    assert step.diagnostics.width_changed is True
    assert step.diagnostics.height_changed is True
    assert step.frame is not None
    assert step.frame.clear_scrollback_emitted is False


def test_playback_step_asserts_explicit_clear_scrollback() -> None:
    def render(
        event: PlaybackEvent, size: TerminalSize, previous: RenderDiagnostics | None
    ) -> RenderDiagnostics:
        return RenderDiagnostics(
            current_logical_lines=("panic repaint",),
            operation_class="recovery_repaint",
            repaint_kind="recovery",
            repaint_reason="explicit-panic-recovery",
            clear_scrollback_policy="explicit",
            operations=(
                TerminalOperation.begin_synchronized_update(),
                TerminalOperation.clear_screen(),
                TerminalOperation.clear_scrollback(),
                TerminalOperation.write("panic repaint"),
                TerminalOperation.end_synchronized_update(),
            ),
        )

    harness = PlaybackHarness(render=render)

    step = harness.play([PlaybackEvent("product", "panic")])[0]

    step.assert_operation_class("recovery_repaint")
    step.assert_has_clear_scrollback()
    assert step.diagnostics.clear_scrollback_emitted is True
    assert step.frame is not None
    assert step.frame.clear_scrollback_emitted is True
