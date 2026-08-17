from __future__ import annotations

from dataclasses import dataclass, field

import pytest

import loushang.harnesstui.testing.performance as performance_module
from loushang.harnesstui.testing.performance import (
    build_synthetic_long_transcript_records,
    characterize_long_transcript_rendering,
)
from loushang.tui.core import RenderConstraints, RenderLine, RenderResult
from loushang.tui.render_loop import RenderLoop
from loushang.tui.transcript import (
    AssistantMessageRecord,
    ToolExecutionRecord,
    UserPromptRecord,
    WorkedDividerRecord,
)


@dataclass
class _RecordingComposer:
    text: str = ""
    calls: list[str] = field(default_factory=list)

    def set_text(self, text: str) -> None:
        self.text = text
        self.calls.append(text)


@dataclass
class _ProbeApp:
    _composer: _RecordingComposer = field(default_factory=_RecordingComposer)
    constraints: list[RenderConstraints] = field(default_factory=list)

    @property
    def composer(self) -> _RecordingComposer:
        return self._composer

    def render(self, constraints: RenderConstraints) -> RenderResult:
        self.constraints.append(constraints)
        line_count = min(5, constraints.max_height)
        lines = [RenderLine(f"line {index}") for index in range(line_count)]
        if lines:
            lines[-1] = RenderLine(f"composer: {self.composer.text}")
        return RenderResult(tuple(lines))


def test_synthetic_long_transcript_records_have_stable_neutral_shape() -> None:
    records = build_synthetic_long_transcript_records(
        turns=2,
        tail_tool_output_lines=3,
    )

    assert len(records) == 8
    assert tuple(type(record) for record in records) == (
        UserPromptRecord,
        AssistantMessageRecord,
        ToolExecutionRecord,
        WorkedDividerRecord,
        UserPromptRecord,
        AssistantMessageRecord,
        ToolExecutionRecord,
        WorkedDividerRecord,
    )
    first_tool = records[2]
    tail_tool = records[6]
    assert isinstance(first_tool, ToolExecutionRecord)
    assert isinstance(tail_tool, ToolExecutionRecord)
    assert len(first_tool.output.splitlines()) == 12
    assert len(tail_tool.output.splitlines()) == 3
    assert tail_tool.command == "read /repo/file_2.py"
    assert build_synthetic_long_transcript_records(turns=0) == ()


def test_render_probe_measures_visible_and_logical_plans_and_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = iter((1.0, 1.001, 2.0, 2.003, 3.0, 3.001, 4.0, 4.003))
    monkeypatch.setattr(performance_module, "perf_counter", clock.__next__)
    app = _ProbeApp()
    render_loop = RenderLoop(screen_root=app)

    first = characterize_long_transcript_rendering(
        app,
        width=80,
        height=2,
        composer_text="first",
        render_loop=render_loop,
        commit_plan=True,
    )
    second = characterize_long_transcript_rendering(
        app,
        width=80,
        height=2,
        composer_text="second",
        render_loop=render_loop,
    )

    assert app.composer.calls == ["first", "second"]
    assert app.constraints == [
        RenderConstraints(width=80, max_height=2, visible_height=2),
        RenderConstraints(width=80, max_height=1_000_000, visible_height=2),
        RenderConstraints(width=80, max_height=2, visible_height=2),
        RenderConstraints(width=80, max_height=1_000_000, visible_height=2),
    ]
    assert first.visible_render_ms == pytest.approx(1.0)
    assert first.render_loop_plan_ms == pytest.approx(3.0)
    assert first.visible_render_line_count == 2
    assert first.render_loop_logical_line_count == 5
    assert first.render_loop_operation_class == "first_render"
    assert render_loop.committed_frame_revision == 1
    assert second.visible_render_ms == pytest.approx(1.0)
    assert second.render_loop_plan_ms == pytest.approx(3.0)
    assert second.render_loop_operation_class == "changed_range_update"
    assert second.changed_line_range is not None
