from __future__ import annotations

import asyncio
import inspect
import threading
from types import SimpleNamespace
from typing import Any

import pytest

import loushang.harnesstui.conversation.agent_binding as agent_binding
from loushang.ai import TextPart
from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.harness.events import OrderedEventBus
from loushang.harnesstui.conversation.agent_binding import (
    build_agent_screen_conversation_projection,
    cooperative_agent_screen_event_listener,
)
from loushang.tui.core import RenderConstraints
from loushang.tui.markdown.renderer import LargeMarkdownDeltaAnalysis
from loushang.tui.transcript import AssistantMessageRecord, WorkedDividerRecord


def _assistant(text: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        role="assistant",
        content=[TextPart(type="text", text=text)] if text else [],
        stop_reason="stop",
        error_message=None,
    )


def _large_list() -> str:
    return "".join(
        f"- **Line {index}**: [link](https://example.com/{index})\n"
        for index in range(2000)
    )


def _large_mixed_markdown() -> str:
    return "".join(
        f"## Section {index}\n\nParagraph {index} with **bold** and [link](https://example.com/{index}).\n\n"
        for index in range(500)
    )


def test_large_screen_delta_yields_between_safe_batches_and_preserves_final_text() -> None:
    async def scenario() -> None:
        app = ScreenCodingTuiApp(
            model_label="test", cwd="/repo", branch="main", session_label="paced"
        )
        app.begin_run(started_at=0.0)
        projection = build_agent_screen_conversation_projection(app)
        observed_lengths: list[int] = []

        async def pause() -> None:
            draft = app.state.assistant_draft
            observed_lengths.append(len(draft.text) if draft is not None else 0)
            await asyncio.sleep(0)

        listener = cooperative_agent_screen_event_listener(projection, pause=pause)
        listener({"type": "message_start", "message": _assistant()})
        answer = _large_list()
        update = {
            "type": "message_update",
            "message": _assistant(answer),
            "assistant_message_event": {"type": "text_delta", "delta": answer},
        }
        pending = listener(update)
        assert inspect.isawaitable(pending)
        await pending
        assert observed_lengths
        assert observed_lengths == sorted(observed_lengths)
        assert observed_lengths[-1] < len(answer)
        assert app.state.assistant_draft is not None
        assert app.state.assistant_draft.text == answer
        assert update["assistant_message_event"]["delta"] == answer

        completion = listener({"type": "message_end", "message": _assistant(answer)})
        if inspect.isawaitable(completion):
            await completion
        app.complete_run(elapsed_seconds=1.0)
        assert [record.text for record in app.state.records if isinstance(record, AssistantMessageRecord)] == [answer]
        assert sum(isinstance(record, WorkedDividerRecord) for record in app.state.records) == 1

    asyncio.run(scenario())


def test_large_mixed_markdown_delta_yields_without_changing_final_text() -> None:
    async def scenario() -> None:
        app = ScreenCodingTuiApp(
            model_label="test", cwd="/repo", branch="main", session_label="paced"
        )
        app.begin_run(started_at=0.0)
        projection = build_agent_screen_conversation_projection(app)
        pauses: list[int] = []

        async def pause() -> None:
            draft = app.state.assistant_draft
            pauses.append(len(draft.text) if draft is not None else 0)
            await asyncio.sleep(0)

        listener = cooperative_agent_screen_event_listener(projection, pause=pause)
        answer = _large_mixed_markdown()
        listener({"type": "message_start", "message": _assistant()})
        pending = listener(
            {
                "type": "message_update",
                "message": _assistant(answer),
                "assistant_message_event": {"type": "text_delta", "delta": answer},
            }
        )
        assert inspect.isawaitable(pending)
        await pending
        assert pauses and pauses == sorted(pauses)
        assert pauses[-1] < len(answer)
        assert app.state.assistant_draft is not None
        assert app.state.assistant_draft.text == answer

        listener({"type": "message_end", "message": _assistant(answer)})
        app.complete_run(elapsed_seconds=1.0)
        assert [record.text for record in app.state.records if isinstance(record, AssistantMessageRecord)] == [answer]
        assert sum(isinstance(record, WorkedDividerRecord) for record in app.state.records) == 1

    asyncio.run(scenario())


def test_cancelling_large_markdown_parse_does_not_project_the_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()

    def blocked_parse(_delta: str) -> LargeMarkdownDeltaAnalysis:
        started.set()
        assert release.wait(5)
        return LargeMarkdownDeltaAnalysis()

    monkeypatch.setattr(
        agent_binding, "analyze_large_markdown_delta", blocked_parse
    )

    async def scenario() -> None:
        app = ScreenCodingTuiApp(
            model_label="test", cwd="/repo", branch="main", session_label="paced"
        )
        app.begin_run(started_at=0.0)
        listener = cooperative_agent_screen_event_listener(
            build_agent_screen_conversation_projection(app)
        )
        answer = _large_mixed_markdown()
        listener({"type": "message_start", "message": _assistant()})
        pending = listener(
            {
                "type": "message_update",
                "message": _assistant(answer),
                "assistant_message_event": {"type": "text_delta", "delta": answer},
            }
        )
        assert inspect.isawaitable(pending)
        task = asyncio.create_task(pending)
        try:
            assert await asyncio.to_thread(started.wait, 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()
        assert app.state.assistant_draft is None

    asyncio.run(scenario())


def test_atomic_table_worker_render_keeps_input_loop_live_and_cancels_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()
    original = agent_binding.render_prepared_atomic_markdown

    def blocked_render(*args: Any) -> Any:
        started.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(agent_binding, "render_prepared_atomic_markdown", blocked_render)

    async def scenario() -> None:
        app = ScreenCodingTuiApp(
            model_label="test", cwd="/repo", branch="main", session_label="paced"
        )
        app.begin_run(started_at=0.0)
        app.render(RenderConstraints(width=80, max_height=18, visible_height=18))
        listener = cooperative_agent_screen_event_listener(
            build_agent_screen_conversation_projection(app)
        )
        answer = "| Name | Value |\n| --- | --- |\n" + "".join(
            f"| row {index} | [link](https://example.com/{index}) |\n"
            for index in range(600)
        )
        listener({"type": "message_start", "message": _assistant()})
        pending = listener(
            {
                "type": "message_update",
                "message": _assistant(answer),
                "assistant_message_event": {"type": "text_delta", "delta": answer},
            }
        )
        assert inspect.isawaitable(pending)
        task = asyncio.create_task(pending)
        try:
            assert await asyncio.to_thread(started.wait, 5)
            assert app.state.running
            assert app.state.assistant_draft is None
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()
        assert app.state.assistant_draft is None

    asyncio.run(scenario())


def test_atomic_table_worker_render_failure_keeps_normal_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_render(*_args: Any) -> Any:
        raise ValueError("worker render unavailable")

    monkeypatch.setattr(agent_binding, "render_prepared_atomic_markdown", fail_render)

    async def scenario() -> None:
        app = ScreenCodingTuiApp(
            model_label="test", cwd="/repo", branch="main", session_label="paced"
        )
        app.begin_run(started_at=0.0)
        app.render(RenderConstraints(width=80, max_height=18, visible_height=18))
        listener = cooperative_agent_screen_event_listener(
            build_agent_screen_conversation_projection(app)
        )
        answer = "| Name | Value |\n| --- | --- |\n" + "".join(
            f"| row {index} | value {index} |\n" for index in range(700)
        )
        listener({"type": "message_start", "message": _assistant()})
        pending = listener(
            {
                "type": "message_update",
                "message": _assistant(answer),
                "assistant_message_event": {"type": "text_delta", "delta": answer},
            }
        )
        assert inspect.isawaitable(pending)
        await pending
        assert app.state.assistant_draft is not None
        assert app.state.assistant_draft.text == answer
        completion = listener({"type": "message_end", "message": _assistant(answer)})
        if inspect.isawaitable(completion):
            await completion
        app.complete_run(elapsed_seconds=1.0)
        rendered = app.render(
            RenderConstraints(width=80, max_height=18, visible_height=18)
        )
        assert sum("Worked for" in line.text for line in rendered.lines) == 1

    asyncio.run(scenario())


def test_small_deltas_wait_for_worker_without_blocking_working_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()
    original = agent_binding.render_prepared_atomic_markdown

    def blocked_render(*args: Any) -> Any:
        started.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(agent_binding, "render_prepared_atomic_markdown", blocked_render)

    async def scenario() -> None:
        app = ScreenCodingTuiApp(
            model_label="test", cwd="/repo", branch="main", session_label="paced"
        )
        app.begin_run(started_at=0.0)
        app.render(RenderConstraints(width=80, max_height=18, visible_height=18))
        listener = cooperative_agent_screen_event_listener(
            build_agent_screen_conversation_projection(app)
        )
        listener({"type": "message_start", "message": _assistant()})
        chunks = [
            f"- **Line {index}**: [link](https://example.com/{index})\n"
            for index in range(512)
        ]
        for chunk in chunks:
            listener(
                {
                    "type": "message_update",
                    "message": _assistant(chunk),
                    "assistant_message_event": {"type": "text_delta", "delta": chunk},
                }
            )
        answer = "".join(chunks)
        pending = listener({"type": "message_end", "message": _assistant(answer)})
        assert inspect.isawaitable(pending)
        task = asyncio.create_task(pending)
        try:
            assert await asyncio.to_thread(started.wait, 5)
            ticked = asyncio.Event()
            asyncio.get_running_loop().call_soon(ticked.set)
            await asyncio.wait_for(ticked.wait(), 1)
            assert app.state.running
            assert app.state.assistant_draft is not None
            assert not any(
                isinstance(record, WorkedDividerRecord) for record in app.state.records
            )
        finally:
            release.set()
        await task
        app.complete_run(elapsed_seconds=1.0)
        assert sum(
            isinstance(record, WorkedDividerRecord) for record in app.state.records
        ) == 1

    asyncio.run(scenario())


def test_cancelled_small_delta_completion_does_not_commit_late_worked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    original = agent_binding.render_prepared_atomic_markdown

    def blocked_render(*args: Any) -> Any:
        started.set()
        assert release.wait(5)
        try:
            return original(*args)
        finally:
            finished.set()

    monkeypatch.setattr(agent_binding, "render_prepared_atomic_markdown", blocked_render)

    async def scenario() -> None:
        app = ScreenCodingTuiApp(
            model_label="test", cwd="/repo", branch="main", session_label="paced"
        )
        app.begin_run(started_at=0.0)
        app.render(RenderConstraints(width=80, max_height=18, visible_height=18))
        listener = cooperative_agent_screen_event_listener(
            build_agent_screen_conversation_projection(app)
        )
        listener({"type": "message_start", "message": _assistant()})
        chunks = [
            f"- **Line {index}**: [link](https://example.com/{index})\n"
            for index in range(512)
        ]
        for chunk in chunks:
            listener(
                {
                    "type": "message_update",
                    "message": _assistant(chunk),
                    "assistant_message_event": {"type": "text_delta", "delta": chunk},
                }
            )
        pending = listener(
            {"type": "message_end", "message": _assistant("".join(chunks))}
        )
        assert inspect.isawaitable(pending)
        task = asyncio.create_task(pending)
        try:
            assert await asyncio.to_thread(started.wait, 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 1)
        finally:
            release.set()
        assert await asyncio.to_thread(finished.wait, 5)
        await asyncio.sleep(0)
        assert app.state.assistant_draft is not None
        assert not app._transcript_region.has_prepared_assistant_markdown_render
        assert not any(
            isinstance(record, WorkedDividerRecord) for record in app.state.records
        )

    asyncio.run(scenario())


def test_cancelled_large_screen_delta_does_not_project_remaining_batches() -> None:
    async def scenario() -> None:
        app = ScreenCodingTuiApp(
            model_label="test", cwd="/repo", branch="main", session_label="paced"
        )
        app.begin_run(started_at=0.0)
        projection = build_agent_screen_conversation_projection(app)
        paused = asyncio.Event()
        release = asyncio.Event()

        async def pause() -> None:
            paused.set()
            await release.wait()

        listener = cooperative_agent_screen_event_listener(projection, pause=pause)
        listener({"type": "message_start", "message": _assistant()})
        answer = _large_list()
        pending = listener(
            {
                "type": "message_update",
                "message": _assistant(answer),
                "assistant_message_event": {"type": "text_delta", "delta": answer},
            }
        )
        assert inspect.isawaitable(pending)
        task = asyncio.create_task(pending)
        await paused.wait()
        draft = app.state.assistant_draft
        prefix = draft.text if draft is not None else ""
        assert 0 < len(prefix) < len(answer)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        await asyncio.sleep(0)
        assert app.state.assistant_draft is not None
        assert app.state.assistant_draft.text == prefix

    asyncio.run(scenario())


def test_ordered_session_events_wait_for_all_paced_delta_batches() -> None:
    async def scenario() -> None:
        app = ScreenCodingTuiApp(
            model_label="test", cwd="/repo", branch="main", session_label="paced"
        )
        app.begin_run(started_at=0.0)
        answer = _large_list()
        listener = cooperative_agent_screen_event_listener(
            build_agent_screen_conversation_projection(app),
            pause=lambda: asyncio.sleep(0),
        )
        bus: OrderedEventBus[dict[str, object]] = OrderedEventBus()
        bus.subscribe(listener)
        bus.schedule({"type": "message_start", "message": _assistant()})
        bus.schedule(
            {
                "type": "message_update",
                "message": _assistant(answer),
                "assistant_message_event": {"type": "text_delta", "delta": answer},
            }
        )
        bus.schedule({"type": "message_end", "message": _assistant(answer)})
        await bus.drain()
        records = [
            record for record in app.state.records
            if isinstance(record, AssistantMessageRecord)
        ]
        assert len(records) == 1
        assert records[0].text == answer
        assert app.state.assistant_draft is None

    asyncio.run(scenario())
