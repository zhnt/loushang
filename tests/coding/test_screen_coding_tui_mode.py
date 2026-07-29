from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.ai import (
    AssistantMessage,
    Model,
    TextPart,
    ToolResultMessage,
    Usage,
    UserMessage,
)
from loushang.ai.model import ModelSelection
from loushang.coding.ui.screen_surfaces import ScreenSurfaceManager
from loushang.harness.conversation import ConversationRecord
from loushang.harness.transcript import (
    AGENT_MESSAGE_KIND,
    CONTEXT_COMPACTION_CHECKPOINT_KIND,
    AgentTranscriptContext,
    AgentTranscriptState,
    ContextCompactionCheckpoint,
)
from loushang.harnesstui.conversation import agent_application as tui_policy
from loushang.harnesstui.conversation.control import ConversationTextAction
from loushang.harnesstui.testing.performance import (
    characterize_long_transcript_rendering,
)
from loushang.observability import configure_debug_logging, reset_observability
from loushang.tui import RenderLoop, TerminalSize
from loushang.tui.transcript import (
    AssistantMessageRecord,
    ContextCompactionRecord,
    ToolExecutionRecord,
    UserPromptRecord,
)


class _TTYStringIO(StringIO):
    def isatty(self) -> bool:
        return True


class _RecordingDebugSink:
    def __init__(self) -> None:
        self.events = []

    def write_log(self, **_kwargs) -> None:
        return None

    def write_problem(self, _record) -> None:
        return None

    def write_debug_event(self, record) -> None:
        self.events.append(record)


class _Session:
    def __init__(self) -> None:
        self.session_id = "254d6156"
        self.session_name = "254d6156"
        self.session_manager = SimpleNamespace(
            get_cwd=lambda: "/repo",
            get_session_file=lambda: Path("/tmp/254d6156.jsonl"),
            get_branch=lambda: list(self.context_messages),
        )
        self.keybindings = {"tui.input.submit": ("enter", "ctrl+j")}
        self.settings_manager = SimpleNamespace(
            get_keybindings=lambda: self.keybindings,
        )
        self.current_model: object = ModelSelection(
            provider="unknown", model_id="unknown"
        )
        self.model_details = [
            Model(
                id="kimi-for-coding",
                provider="moonshot",
                endpoint="kimi-code-anthropic",
            )
        ]
        self.prompts: list[str] = []
        self.listeners: list[Callable[[dict[str, object]], object]] = []
        self.unsubscribed = False
        self.steers: list[str] = []
        self.follow_ups: list[str] = []
        self.visible_steering: list[str] = []
        self.visible_follow_up: list[str] = []
        self.context_messages: list[object] = []

    def get_model_selection(self) -> object:
        return self.current_model

    def get_session_context(self) -> AgentTranscriptContext:
        return AgentTranscriptContext(
            messages=tuple(self.context_messages),
            state=AgentTranscriptState(),
        )

    def get_available_model_details(self) -> list[Model]:
        return self.model_details

    def get_tool_definition(self, _name: str) -> None:
        return None

    async def set_model(self, selection: object) -> None:
        if isinstance(selection, Model):
            self.current_model = ModelSelection(
                provider=selection.provider_id, model_id=selection.id
            )
        else:
            self.current_model = selection

    def subscribe(self, listener: Callable[[dict[str, object]], object]):
        self.listeners.append(listener)

        def unsubscribe() -> None:
            self.unsubscribed = True
            if listener in self.listeners:
                self.listeners.remove(listener)

        return unsubscribe

    async def prompt(self, text: str) -> None:
        self.prompts.append(text)
        await self._emit(
            {
                "type": "message_start",
                "message": UserMessage(
                    role="user",
                    content=[TextPart(type="text", text=text)],
                    timestamp=0.0,
                ),
            }
        )
        await self._emit(
            {
                "type": "message_update",
                "message": SimpleNamespace(role="assistant"),
                "assistant_message_event": {
                    "type": "text_delta",
                    "content_index": 0,
                    "delta": "hello back",
                },
            }
        )
        await self._emit(
            {
                "type": "message_end",
                "message": SimpleNamespace(
                    role="assistant", content=[TextPart(type="text", text="hello back")]
                ),
            }
        )

    async def _emit(self, event: dict[str, object]) -> None:
        for listener in list(self.listeners):
            result = listener(event)
            if inspect.isawaitable(result):
                await result

    async def steer(self, text: str) -> None:
        self.steers.append(text)

    async def follow_up(self, text: str) -> None:
        self.follow_ups.append(text)

    def get_steering_messages(self) -> list[str]:
        return list(self.visible_steering)

    def get_follow_up_messages(self) -> list[str]:
        return list(self.visible_follow_up)

    def abort(self) -> None:
        return None

    def clear_queue(self) -> None:
        return None

    def abort_bash(self) -> None:
        return None


def test_run_coding_tui_interactive_uses_screen_loop(monkeypatch) -> None:
    from loushang.coding.ui import mode

    session = _Session()
    captured: dict[str, object] = {}

    async def fake_screen_loop(**kwargs):
        captured.update(kwargs)
        await kwargs["action_host"].submit(ConversationTextAction("hello"))
        return 0

    monkeypatch.setattr(mode, "run_action_host_conversation_screen", fake_screen_loop)

    exit_code = asyncio.run(
        mode.run_coding_tui(
            runtime=object(),
            session=session,
            stdin=_TTYStringIO(),
            stdout=_TTYStringIO(),
            stderr=StringIO(),
        )
    )

    screen_app = captured["app"]
    records = getattr(screen_app, "state").records
    assistant_records = [
        record for record in records if isinstance(record, AssistantMessageRecord)
    ]
    assert exit_code == 0
    assert session.prompts == ["hello"]
    assert captured["keybindings"] == session.keybindings
    assert assistant_records[-1].text == "hello back"


def test_run_coding_tui_interactive_prints_resume_hint_on_clean_exit(
    monkeypatch,
) -> None:
    from loushang.coding.ui import mode

    session = _Session()
    stdout = _TTYStringIO()

    async def fake_screen_loop(**kwargs):
        return 0

    monkeypatch.setattr(mode, "run_action_host_conversation_screen", fake_screen_loop)

    exit_code = asyncio.run(
        mode.run_coding_tui(
            runtime=object(),
            session=session,
            stdin=_TTYStringIO(),
            stdout=stdout,
            stderr=StringIO(),
        )
    )

    assert exit_code == 0
    assert "Resume this session with:" in stdout.getvalue()
    assert "loushang --resume 254d6156" in stdout.getvalue()
    assert "loushang --tui --resume" not in stdout.getvalue()


def test_run_coding_tui_interactive_replays_resumed_session_history(
    monkeypatch,
) -> None:
    from loushang.coding.ui import mode

    session = _Session()
    usage = Usage(
        input=1, output=2, cache_read=0, cache_write=0, total_tokens=3, cost={}
    )
    session.context_messages = [
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="previous question")],
            timestamp=1.0,
        ),
        AssistantMessage(
            role="assistant",
            content=[TextPart(type="text", text="previous answer")],
            api="openai",
            provider="moonshot",
            model="kimi",
            response_id=None,
            usage=usage,
            stop_reason="stop",
            error_message=None,
            timestamp=2.0,
        ),
        ToolResultMessage(
            role="toolResult",
            tool_call_id="bash-1",
            tool_name="bash",
            content=[TextPart(type="text", text="file contents")],
            is_error=False,
            timestamp=3.0,
        ),
    ]
    session.session_manager.get_branch = lambda: (
        [
            ConversationRecord(
                record_id=f"record-{index}",
                parent_id=f"record-{index - 1}" if index else None,
                kind=AGENT_MESSAGE_KIND,
                payload_version=1,
                created_at=f"2026-07-16T00:00:0{index}Z",
                payload=message,
            )
            for index, message in enumerate(session.context_messages)
        ]
        + [
            ConversationRecord(
                record_id="record-3",
                parent_id="record-2",
                kind=CONTEXT_COMPACTION_CHECKPOINT_KIND,
                payload_version=1,
                created_at="2026-07-16T00:00:03Z",
                payload=ContextCompactionCheckpoint(
                    summary="older context summary",
                    first_kept_record_id="record-0",
                    tokens_before=128,
                ),
            )
        ]
    )
    captured: dict[str, object] = {}

    async def fake_screen_loop(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(mode, "run_action_host_conversation_screen", fake_screen_loop)

    exit_code = asyncio.run(
        mode.run_coding_tui(
            runtime=object(),
            session=session,
            stdin=_TTYStringIO(),
            stdout=_TTYStringIO(),
            stderr=StringIO(),
        )
    )

    app = captured["app"]
    records = getattr(app, "state").records
    reader_source = getattr(app, "transcript_source_factory")()
    reader_snapshot = reader_source.snapshot()
    assert exit_code == 0
    assert reader_snapshot.complete is True
    assert reader_snapshot.source_label == "Full transcript"
    assert reader_snapshot.records == tuple(records)
    assert isinstance(records[0], UserPromptRecord)
    assert records[0].text == "previous question"
    assert isinstance(records[1], AssistantMessageRecord)
    assert records[1].text == "previous answer"
    assert isinstance(records[2], ToolExecutionRecord)
    assert records[2].name.startswith("bash")
    assert records[2].output == "file contents"
    assert isinstance(records[3], ContextCompactionRecord)
    assert records[3].summary == "older context summary"
    assert records[3].tokens_before == 128


def test_run_coding_tui_interactive_bounds_resumed_long_transcript_render_window(
    monkeypatch,
) -> None:
    from loushang.coding.ui import mode

    session = _Session()
    usage = Usage(
        input=1, output=2, cache_read=0, cache_write=0, total_tokens=3, cost={}
    )
    for turn in range(24):
        session.context_messages.append(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text=f"question {turn}")],
                timestamp=float(turn),
            )
        )
        line_count = 900 if turn == 23 else 40
        session.context_messages.append(
            AssistantMessage(
                role="assistant",
                content=[
                    TextPart(
                        type="text",
                        text="\n".join(
                            f"answer {turn} line {line}" for line in range(line_count)
                        ),
                    )
                ],
                api="openai",
                provider="moonshot",
                model="kimi",
                response_id=None,
                usage=usage,
                stop_reason="stop",
                error_message=None,
                timestamp=float(turn) + 0.5,
            )
        )
    captured: dict[str, object] = {}

    async def fake_screen_loop(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(mode, "run_action_host_conversation_screen", fake_screen_loop)

    exit_code = asyncio.run(
        mode.run_coding_tui(
            runtime=object(),
            session=session,
            stdin=_TTYStringIO(),
            stdout=_TTYStringIO(),
            stderr=StringIO(),
        )
    )

    app = captured["app"]
    render_loop = RenderLoop(screen_root=app)
    first_metrics = characterize_long_transcript_rendering(
        app,
        width=100,
        height=30,
        render_loop=render_loop,
        commit_plan=True,
    )
    input_metrics = characterize_long_transcript_rendering(
        app,
        width=100,
        height=30,
        composer_text="x",
        render_loop=render_loop,
        commit_plan=True,
    )

    assert exit_code == 0
    assert getattr(app, "state").evicted_prefix_record_count > 0
    assert first_metrics.render_loop_logical_line_count <= 380
    assert input_metrics.render_loop_logical_line_count <= 380
    assert input_metrics.render_loop_operation_class not in {
        "baseline_repaint",
        "managed_viewport_repaint",
        "recovery_repaint",
        "resize_repaint",
    }


def test_run_coding_tui_interactive_long_transcript_input_frame_does_not_clear_screen(
    monkeypatch,
) -> None:
    from loushang.coding.ui import mode

    session = _Session()
    usage = Usage(
        input=1, output=2, cache_read=0, cache_write=0, total_tokens=3, cost={}
    )
    for turn in range(24):
        session.context_messages.append(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text=f"question {turn}")],
                timestamp=float(turn),
            )
        )
        session.context_messages.append(
            AssistantMessage(
                role="assistant",
                content=[
                    TextPart(
                        type="text",
                        text="\n".join(
                            f"answer {turn} line {line}" for line in range(80)
                        ),
                    )
                ],
                api="openai",
                provider="moonshot",
                model="kimi",
                response_id=None,
                usage=usage,
                stop_reason="stop",
                error_message=None,
                timestamp=float(turn) + 0.5,
            )
        )
    captured: dict[str, object] = {}

    async def fake_screen_loop(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(mode, "run_action_host_conversation_screen", fake_screen_loop)

    exit_code = asyncio.run(
        mode.run_coding_tui(
            runtime=object(),
            session=session,
            stdin=_TTYStringIO(),
            stdout=_TTYStringIO(),
            stderr=StringIO(),
        )
    )

    app = captured["app"]
    render_loop = RenderLoop(screen_root=app)
    size = TerminalSize(columns=100, rows=30)
    first = render_loop.plan(size)
    render_loop.commit(first, size=size)
    app.composer.set_text("x")
    second = render_loop.plan(size)

    assert exit_code == 0
    assert second.operation_class == "changed_range_update"
    assert {operation.kind for operation in second.operations}.isdisjoint(
        {"clear_screen", "clear_scrollback"}
    )


def test_run_coding_tui_interactive_long_transcript_working_timer_frame_stays_bounded(
    monkeypatch,
) -> None:
    from loushang.coding.ui import mode

    session = _Session()
    usage = Usage(
        input=1, output=2, cache_read=0, cache_write=0, total_tokens=3, cost={}
    )
    for turn in range(24):
        session.context_messages.append(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text=f"question {turn}")],
                timestamp=float(turn),
            )
        )
        session.context_messages.append(
            AssistantMessage(
                role="assistant",
                content=[
                    TextPart(
                        type="text",
                        text="\n".join(
                            f"answer {turn} line {line}" for line in range(80)
                        ),
                    )
                ],
                api="openai",
                provider="moonshot",
                model="kimi",
                response_id=None,
                usage=usage,
                stop_reason="stop",
                error_message=None,
                timestamp=float(turn) + 0.5,
            )
        )
    captured: dict[str, object] = {}

    async def fake_screen_loop(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(mode, "run_action_host_conversation_screen", fake_screen_loop)

    exit_code = asyncio.run(
        mode.run_coding_tui(
            runtime=object(),
            session=session,
            stdin=_TTYStringIO(),
            stdout=_TTYStringIO(),
            stderr=StringIO(),
        )
    )

    app = captured["app"]
    app.now = lambda: 10.0
    app.begin_run(started_at=10.0)
    render_loop = RenderLoop(screen_root=app)
    size = TerminalSize(columns=100, rows=30)
    first = render_loop.plan(size)
    render_loop.commit(first, size=size)
    app.now = lambda: 10.2
    second = render_loop.plan(size)

    assert exit_code == 0
    assert len(second.current_logical_lines) <= 380
    assert second.operation_class == "changed_range_update"
    assert second.changed_line_range is not None
    assert second.changed_line_range[0] >= len(second.current_logical_lines) - 8
    assert {operation.kind for operation in second.operations}.isdisjoint(
        {"clear_screen", "clear_scrollback"}
    )


def test_run_coding_tui_interactive_traces_resumed_transcript_window_trim(
    monkeypatch,
) -> None:
    from loushang.coding.ui import mode

    session = _Session()
    usage = Usage(
        input=1, output=2, cache_read=0, cache_write=0, total_tokens=3, cost={}
    )
    for turn in range(24):
        session.context_messages.append(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text=f"question {turn}")],
                timestamp=float(turn),
            )
        )
        session.context_messages.append(
            AssistantMessage(
                role="assistant",
                content=[
                    TextPart(
                        type="text",
                        text="\n".join(
                            f"answer {turn} line {line}" for line in range(80)
                        ),
                    )
                ],
                api="openai",
                provider="moonshot",
                model="kimi",
                response_id=None,
                usage=usage,
                stop_reason="stop",
                error_message=None,
                timestamp=float(turn) + 0.5,
            )
        )
    sink = _RecordingDebugSink()
    captured: dict[str, object] = {}

    async def fake_screen_loop(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(mode, "run_action_host_conversation_screen", fake_screen_loop)
    reset_observability()
    configure_debug_logging(debug_sink=sink, debug_scopes=("tui",))
    try:
        exit_code = asyncio.run(
            mode.run_coding_tui(
                runtime=object(),
                session=session,
                stdin=_TTYStringIO(),
                stdout=_TTYStringIO(),
                stderr=StringIO(),
            )
        )
    finally:
        reset_observability()

    event = next(
        event
        for event in sink.events
        if event.scope == "tui" and event.name == "tui.resume_history"
    )
    app = captured["app"]
    assert exit_code == 0
    assert event.data["record_count"] == 48
    assert event.data["active_record_count"] == len(getattr(app, "state").records)
    assert (
        event.data["evicted_record_count"]
        == getattr(app, "state").evicted_prefix_record_count
    )
    assert event.data["trimmed"] is True


def test_run_coding_tui_interactive_screen_loop_dispatches_steer_and_followup(
    monkeypatch,
) -> None:
    from loushang.coding.ui import mode

    session = _Session()
    captured: dict[str, object] = {}

    async def fake_screen_loop(**kwargs):
        captured.update(kwargs)
        await kwargs["action_host"].steer(ConversationTextAction("steer this"))
        await kwargs["action_host"].follow_up(ConversationTextAction("follow this"))
        return 0

    monkeypatch.setattr(mode, "run_action_host_conversation_screen", fake_screen_loop)

    exit_code = asyncio.run(
        mode.run_coding_tui(
            runtime=object(),
            session=session,
            stdin=_TTYStringIO(),
            stdout=_TTYStringIO(),
            stderr=StringIO(),
        )
    )

    assert exit_code == 0
    assert session.steers == ["steer this"]
    assert session.follow_ups == ["follow this"]


def test_run_coding_tui_injects_on_approval_callback(monkeypatch) -> None:
    from loushang.coding.ui import mode

    session = _Session()
    captured: dict[str, object] = {}

    class RecordingSurfaceManager(ScreenSurfaceManager):
        def __init__(self, *args: object, **kwargs: object) -> None:
            captured["on_approval"] = kwargs.get("on_approval")
            super().__init__(*args, **kwargs)

    async def fake_screen_loop(**kwargs: object) -> int:
        captured["loop_kwargs"] = kwargs
        return 0

    monkeypatch.setattr(mode, "ScreenSurfaceManager", RecordingSurfaceManager)
    monkeypatch.setattr(mode, "run_action_host_conversation_screen", fake_screen_loop)

    exit_code = asyncio.run(
        mode.run_coding_tui(
            runtime=object(),
            session=session,
            stdin=_TTYStringIO(),
            stdout=_TTYStringIO(),
            stderr=StringIO(),
        )
    )

    assert exit_code == 0
    on_approval = captured.get("on_approval")
    assert callable(on_approval)
    assert isinstance(captured.get("loop_kwargs"), dict)


def test_screen_approval_presenter_resolves_ask_tools_and_clears_pending(
    tmp_path,
) -> None:
    from loushang.coding.tool_pack import register_coding_builtin_tools
    from loushang.harness.approval import (
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
    )
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.tools.workspace import ToolContext
    from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry

    resolver = InteractiveApprovalResolver(
        fallback=HeadlessApprovalResolver(mode="deny")
    )
    presented: list[dict[str, object]] = []
    opened = asyncio.Event()

    class ApprovalSession:
        def set_approval_presenter(self, presenter, *, dismisser=None) -> None:
            resolver.set_request_presenter(presenter, dismisser=dismisser)

        async def handle_screen_approval(self, event: dict[str, object]) -> bool:
            action_id = event.get("action_id")
            assert isinstance(action_id, str)
            return await resolver.handle_result(
                action_id,
                approved=bool(event.get("approved")),
            )

    class ApprovalSurfaceManager:
        def open_approval(self, **payload: object) -> None:
            presented.append(dict(payload))
            opened.set()

        def dismiss_approval(self, action_id: str) -> None:
            del action_id

    registry = WorkspaceToolRegistry()
    register_coding_builtin_tools(
        registry,
        policy_engine=PolicyEngine(ask_tools=["write"]),
        approval_resolver=resolver,
    )

    def context_provider(*, tool_call_id: str) -> ToolContext:
        return ToolContext(tool_call_id=tool_call_id, cwd=str(tmp_path))

    write = registry.materialize_tool(
        "write",
        context_provider=context_provider,
    )
    session = ApprovalSession()
    unbind = tui_policy.bind_agent_screen_approval_presenter(
        session,
        ApprovalSurfaceManager(),  # type: ignore[arg-type]
    )

    async def run() -> None:
        allow_task = asyncio.create_task(
            write.execute(
                "write-allow",
                {"path": "approved.txt", "content": "allowed"},
            )
        )
        await opened.wait()
        allow_action_id = presented[-1]["action_id"]
        assert isinstance(allow_action_id, str)
        await session.handle_screen_approval(
            {"action_id": allow_action_id, "approved": True}
        )
        await allow_task

        opened.clear()
        deny_task = asyncio.create_task(
            write.execute(
                "write-deny",
                {"path": "denied.txt", "content": "denied"},
            )
        )
        await opened.wait()
        deny_action_id = presented[-1]["action_id"]
        assert isinstance(deny_action_id, str)
        await session.handle_screen_approval(
            {"action_id": deny_action_id, "approved": False}
        )
        with pytest.raises(PermissionError):
            await deny_task

    try:
        asyncio.run(run())
    finally:
        unbind()

    assert (tmp_path / "approved.txt").read_text(encoding="utf-8") == "allowed"
    assert not (tmp_path / "denied.txt").exists()
    assert resolver._broker.pending_requests() == ()


def test_screen_approval_unbind_targets_runtime_current_session() -> None:
    from loushang.harness.approval import (
        ApprovalRequest,
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
    )

    resolver = InteractiveApprovalResolver(
        fallback=HeadlessApprovalResolver(mode="allow")
    )
    shown = asyncio.Event()

    class ApprovalSession:
        def __init__(self) -> None:
            self.active = True

        def set_approval_presenter(self, presenter, *, dismisser=None) -> None:
            if presenter is None:
                if self.active:
                    resolver.close_session(
                        "Approval presenter closed before approval was resolved"
                    )
                    self.active = False
                resolver.set_request_presenter(None)
                return

            def present(payload: dict[str, object]) -> object:
                shown.set()
                return presenter(payload)

            resolver.set_request_presenter(present, dismisser=dismisser)

    class ApprovalSurfaceManager:
        def open_approval(self, **payload: object) -> None:
            del payload

        def dismiss_approval(self, action_id: str) -> None:
            del action_id

    old_session = ApprovalSession()
    new_session = ApprovalSession()
    current_session = old_session
    unbind = tui_policy.bind_agent_screen_approval_presenter(
        old_session,
        ApprovalSurfaceManager(),  # type: ignore[arg-type]
        session_provider=lambda: current_session,
    )
    old_session.active = False
    new_session.active = True
    current_session = new_session

    async def run() -> object:
        pending = asyncio.create_task(
            resolver.resolve(
                ApprovalRequest(
                    tool_name="write",
                    arguments={},
                    action_id="approval-current-session-unbind",
                )
            )
        )
        await asyncio.wait_for(shown.wait(), timeout=0.5)
        unbind()
        return await asyncio.wait_for(pending, timeout=0.5)

    decision = asyncio.run(run())

    assert getattr(decision, "disposition") == "deny"
    assert resolver._broker.pending_requests() == ()
    assert resolver._request_presenter is None


def test_screen_approval_unbind_clears_host_presenter_without_current_session() -> None:
    from loushang.harness.approval import (
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
    )

    resolver = InteractiveApprovalResolver(
        fallback=HeadlessApprovalResolver(mode="deny")
    )

    class ClosedSession:
        def set_approval_presenter(self, presenter, *, dismisser=None) -> None:
            if presenter is not None:
                resolver.set_request_presenter(presenter, dismisser=dismisser)

        def _unbind_approval_presenter_host(self) -> None:
            resolver.set_request_presenter(None)

    class EmptyRuntime:
        def get_current_session(self) -> None:
            return None

    class ApprovalSurfaceManager:
        def open_approval(self, **payload: object) -> None:
            del payload

        def dismiss_approval(self, action_id: str) -> None:
            del action_id

    session = ClosedSession()
    unbind = tui_policy.bind_agent_screen_approval_presenter(
        session,
        ApprovalSurfaceManager(),  # type: ignore[arg-type]
        session_provider=lambda: tui_policy.current_agent_runtime_session(
            EmptyRuntime(), session
        ),
    )
    assert resolver._request_presenter is not None

    unbind()

    assert resolver._request_presenter is None


def test_screen_approval_unbind_clears_initial_presenter_when_current_has_none() -> (
    None
):
    from loushang.harness.approval import (
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
    )

    resolver = InteractiveApprovalResolver(
        fallback=HeadlessApprovalResolver(mode="deny")
    )

    class InitialSession:
        def set_approval_presenter(self, presenter, *, dismisser=None) -> None:
            resolver.set_request_presenter(presenter, dismisser=dismisser)

        def _unbind_approval_presenter_host(self) -> None:
            resolver.set_request_presenter(None)

    class SessionWithoutApproval:
        def set_approval_presenter(self, presenter, *, dismisser=None) -> None:
            del presenter, dismisser

    class ApprovalSurfaceManager:
        def open_approval(self, **payload: object) -> None:
            del payload

        def dismiss_approval(self, action_id: str) -> None:
            del action_id

    initial_session = InitialSession()
    current_session = SessionWithoutApproval()
    unbind = tui_policy.bind_agent_screen_approval_presenter(
        initial_session,
        ApprovalSurfaceManager(),  # type: ignore[arg-type]
        session_provider=lambda: current_session,
    )
    assert resolver._request_presenter is not None

    unbind()

    assert resolver._request_presenter is None


def test_screen_tui_failure_detaches_presenter_and_denies_pending(
    monkeypatch,
) -> None:
    from loushang.coding.ui import mode
    from loushang.harness.approval import (
        ApprovalRequest,
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
    )

    resolver = InteractiveApprovalResolver(
        fallback=HeadlessApprovalResolver(mode="allow")
    )
    shown = asyncio.Event()

    class ApprovalSession(_Session):
        def set_approval_presenter(self, presenter, *, dismisser=None) -> None:
            if presenter is None:
                resolver.close_session(
                    "Approval presenter closed before approval was resolved"
                )
                resolver.set_request_presenter(None)
                return

            def present(payload: dict[str, object]) -> object:
                shown.set()
                return presenter(payload)

            resolver.set_request_presenter(present, dismisser=dismisser)

    pending: asyncio.Task[object] | None = None

    async def failing_screen_loop(**kwargs: object) -> int:
        nonlocal pending
        del kwargs
        pending = asyncio.create_task(
            resolver.resolve(
                ApprovalRequest(
                    tool_name="write",
                    arguments={},
                    action_id="approval-tui-failure",
                )
            )
        )
        await shown.wait()
        raise RuntimeError("terminal failed")

    monkeypatch.setattr(
        mode, "run_action_host_conversation_screen", failing_screen_loop
    )

    async def run() -> tuple[int, object]:
        exit_code = await mode.run_coding_tui(
            runtime=object(),
            session=ApprovalSession(),
            stdin=_TTYStringIO(),
            stdout=_TTYStringIO(),
            stderr=StringIO(),
        )
        assert pending is not None
        return exit_code, await pending

    exit_code, decision = asyncio.run(run())

    assert exit_code == 1
    assert getattr(decision, "disposition") == "deny"
    assert resolver._broker.pending_requests() == ()
    assert resolver._request_presenter is None


def test_screen_tui_projector_failure_still_unbinds_presenter(
    monkeypatch,
) -> None:
    from loushang.coding.ui import mode
    from loushang.harness.approval import (
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
    )
    from loushang.harnesstui.conversation import agent_application

    resolver = InteractiveApprovalResolver(
        fallback=HeadlessApprovalResolver(mode="deny")
    )

    class ApprovalSession(_Session):
        def set_approval_presenter(self, presenter, *, dismisser=None) -> None:
            resolver.set_request_presenter(presenter, dismisser=dismisser)

    def fail_projector(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("projector failed")

    monkeypatch.setattr(
        agent_application,
        "build_agent_screen_conversation_projection",
        fail_projector,
    )

    exit_code = asyncio.run(
        mode.run_coding_tui(
            runtime=object(),
            session=ApprovalSession(),
            stdin=_TTYStringIO(),
            stdout=_TTYStringIO(),
            stderr=StringIO(),
        )
    )

    assert exit_code == 1
    assert resolver._request_presenter is None
    assert resolver._broker.pending_requests() == ()


def test_screen_session_transition_binding_clears_approval_surfaces_and_rebinds() -> None:

    subscribers: list[Callable[[], None]] = []
    primary_calls = 0
    clears = 0
    rebound: list[object] = []

    class Runtime:
        rebind = None

        def subscribe_before_session_invalidate(self, callback):
            subscribers.append(callback)

            def unsubscribe() -> None:
                subscribers.remove(callback)

            return unsubscribe

        def invalidate(self) -> None:
            nonlocal primary_calls
            primary_calls += 1
            for callback in tuple(subscribers):
                callback()

        def set_rebind_session(self, callback) -> None:
            self.rebind = callback

        def replace(self, next_session: object) -> None:
            self.invalidate()
            if self.rebind is not None:
                self.rebind(next_session)

    class SurfaceManager:
        def clear_approval_surfaces(self) -> None:
            nonlocal clears
            clears += 1

    runtime = Runtime()
    unbind = tui_policy.bind_agent_screen_session_transition(
        runtime,
        SurfaceManager(),  # type: ignore[arg-type]
        on_rebind=rebound.append,
    )
    next_session = object()
    runtime.replace(next_session)
    unbind()
    runtime.invalidate()

    assert clears == 1
    assert primary_calls == 2
    assert rebound == [next_session]
    assert runtime.rebind is None
    assert subscribers == []


def test_run_coding_tui_non_interactive_keeps_plain_prompt_loop(monkeypatch) -> None:
    from loushang.coding.ui import mode

    session = _Session()
    captured: dict[str, object] = {}

    async def fail_screen_loop(**_kwargs):
        raise AssertionError(
            "non-interactive mode should not enter screen terminal loop"
        )

    async def fake_prompt_loop(**kwargs):
        captured.update(kwargs)
        await kwargs["handle_prompt"]("hello")
        return 0

    monkeypatch.setattr(mode, "run_action_host_conversation_screen", fail_screen_loop)
    monkeypatch.setattr(mode, "run_non_interactive_prompt_loop", fake_prompt_loop)

    exit_code = asyncio.run(
        mode.run_coding_tui(
            runtime=object(),
            session=session,
            stdin=StringIO("hello\n"),
            stdout=StringIO(),
            stderr=StringIO(),
        )
    )

    assert exit_code == 0
    assert session.prompts == ["hello"]
    assert set(captured) == {"stdin", "stdout", "handle_prompt"}


def test_screen_event_projection_skips_duplicate_user_messages(monkeypatch) -> None:
    from loushang.coding.ui import mode

    session = _Session()

    async def prompt_with_user_event(text: str) -> None:
        session.prompts.append(text)
        await session._emit(
            {
                "type": "message_start",
                "message": type(
                    "Message",
                    (),
                    {"role": "user", "content": [TextPart(type="text", text=text)]},
                )(),
            }
        )

    session.prompt = prompt_with_user_event  # type: ignore[method-assign]
    captured: dict[str, object] = {}

    async def fake_screen_loop(**kwargs):
        captured.update(kwargs)
        app = kwargs["app"]
        app.start_prompt("hello")
        await kwargs["action_host"].submit(ConversationTextAction("hello"))
        return 0

    monkeypatch.setattr(mode, "run_action_host_conversation_screen", fake_screen_loop)

    exit_code = asyncio.run(
        mode.run_coding_tui(
            runtime=object(),
            session=session,
            stdin=_TTYStringIO(),
            stdout=_TTYStringIO(),
            stderr=StringIO(),
        )
    )

    records = getattr(captured["app"], "state").records
    assert exit_code == 0
    assert [getattr(record, "text", None) for record in records] == ["hello"]
