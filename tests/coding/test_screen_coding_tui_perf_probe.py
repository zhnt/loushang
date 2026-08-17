from __future__ import annotations

from pathlib import Path

import pytest

from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.harnesstui.testing.performance import (
    build_synthetic_long_transcript_records,
    characterize_long_transcript_rendering,
)
from loushang.tui import RenderLoop
from loushang.tui.transcript import UserPromptRecord


@pytest.mark.tui_render_contract
def test_long_transcript_probe_shows_render_loop_plans_beyond_visible_height() -> None:
    records = build_synthetic_long_transcript_records(turns=180, tail_tool_output_lines=2400)
    app = ScreenCodingTuiApp(
        model_label="fake-model",
        cwd="/repo",
        branch="main",
        session_label="perf",
    )
    app.replace_transcript_window(records, reason="test")
    render_loop = RenderLoop(screen_root=app)

    first_metrics = characterize_long_transcript_rendering(
        app,
        width=100,
        height=30,
        render_loop=render_loop,
        commit_plan=True,
    )
    second_metrics = characterize_long_transcript_rendering(
        app,
        width=100,
        height=30,
        composer_text="hello",
        render_loop=render_loop,
        commit_plan=True,
    )

    assert first_metrics.visible_render_line_count <= 30
    assert first_metrics.render_loop_logical_line_count > 30
    assert first_metrics.render_loop_logical_line_count > first_metrics.visible_render_line_count
    assert second_metrics.render_loop_logical_line_count == first_metrics.render_loop_logical_line_count
    assert second_metrics.render_loop_operation_class != "first_render"


def test_long_transcript_probe_stays_bounded_after_active_window_trim() -> None:
    records = build_synthetic_long_transcript_records(turns=180, tail_tool_output_lines=2400)
    app = ScreenCodingTuiApp(
        model_label="fake-model",
        cwd="/repo",
        branch="main",
        session_label="perf",
    )
    app.replace_transcript_window(records, reason="test")
    app.trim_active_transcript_window()
    render_loop = RenderLoop(screen_root=app)

    first_metrics = characterize_long_transcript_rendering(
        app,
        width=100,
        height=30,
        render_loop=render_loop,
        commit_plan=True,
    )
    second_metrics = characterize_long_transcript_rendering(
        app,
        width=100,
        height=30,
        composer_text="hello",
        render_loop=render_loop,
        commit_plan=True,
    )

    assert app.state.evicted_prefix_record_count > 0
    assert first_metrics.render_loop_plan_ms < 1_000
    assert first_metrics.visible_render_ms < 1_000
    assert second_metrics.render_loop_plan_ms < 1_000
    assert second_metrics.visible_render_ms < 1_000
    assert first_metrics.render_loop_logical_line_count <= app.active_transcript_line_budget + 60
    assert second_metrics.render_loop_logical_line_count <= app.active_transcript_line_budget + 60
    assert second_metrics.render_loop_logical_line_count == first_metrics.render_loop_logical_line_count
    assert second_metrics.render_loop_operation_class == "changed_range_update"
    assert second_metrics.changed_line_range is not None

@pytest.mark.anyio
async def test_coding_performance_loader_adapts_persisted_session_history(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import loushang.coding.presentation.tui.history as history

    loaded_paths: list[Path] = []
    projected: list[tuple[object, object]] = []
    resolver = object()

    class FakeManager:
        @classmethod
        async def load(cls, path: Path) -> FakeManager:
            loaded_paths.append(path)
            return cls()

        def get_branch(self) -> list[str]:
            return ["branch record"]

    async def fake_load_agent_session_history_records(
        session_file: str | Path,
        *,
        load_session: object,
        tool_definition_resolver: object,
    ) -> tuple[UserPromptRecord, ...]:
        manager = await load_session(Path(session_file).expanduser().resolve())
        projected.append((manager.get_branch(), tool_definition_resolver))
        return (UserPromptRecord("loaded"),)

    monkeypatch.setattr(history, "SessionManager", FakeManager)
    monkeypatch.setattr(
        history,
        "load_agent_session_history_records",
        fake_load_agent_session_history_records,
    )
    session_path = tmp_path / "nested" / "session.jsonl"

    records = await history.load_persisted_session_history_records(
        session_path,
        tool_definition_resolver=resolver,
    )

    assert loaded_paths == [session_path.resolve()]
    assert projected == [(["branch record"], resolver)]
    assert records == (UserPromptRecord("loaded"),)
