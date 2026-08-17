from __future__ import annotations

import asyncio
import json
from contextlib import redirect_stderr
from datetime import UTC, datetime
from io import StringIO

import pytest

from loushang.harness.conversation import (
    ConversationHeader,
    ConversationJsonlHeaderCodec,
)
from loushang.harness.events import RuntimeEvent
from loushang.harness.tools.execution import direct_execution

_HEADER_CODEC = ConversationJsonlHeaderCodec()


def _runtime_event(payload: dict[str, object], sequence: int) -> RuntimeEvent[object]:
    return RuntimeEvent(
        event_id=f"event-{sequence}",
        kind=f"agent.{payload['type']}",
        stream_id="session:test",
        sequence=sequence,
        occurred_at=datetime(2026, 7, 16, tzinfo=UTC),
        payload=payload,
    )


def _session_header(
    *,
    type: str,
    version: int,
    id: str,
    timestamp: str,
    cwd: str,
    parent_session: str | None,
) -> ConversationHeader:
    del type, version
    metadata = {"cwd": cwd}
    if parent_session is not None:
        metadata["parentSession"] = parent_session
    return ConversationHeader(
        conversation_id=id,
        version=1,
        created_at=timestamp,
        metadata=metadata,
    )


def serialize_session_header(header: ConversationHeader) -> dict[str, object]:
    return dict(_HEADER_CODEC.encode_header(header))


def test_print_mode_run_once_prompts_session_and_waits_for_idle() -> None:
    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )

    class FakeRuntime:
        pass

    class FakeSession:
        def __init__(self) -> None:
            self.prompt_calls: list[tuple[str, object]] = []
            self.wait_calls = 0
            self.listeners = []

        def subscribe(self, listener):
            self.listeners.append(listener)

            def unsubscribe() -> None:
                self.listeners.remove(listener)

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            self.prompt_calls.append((user_input, images))

        async def wait_for_idle(self) -> None:
            self.wait_calls += 1

    async def scenario() -> None:
        stdout = StringIO()
        session = FakeSession()
        mode = PrintMode(runtime=FakeRuntime(), session=session, stdout=stdout)

        exit_code = await mode.run_once("hello")

        assert exit_code == 0
        assert session.prompt_calls == [("hello", None)]
        assert session.wait_calls == 1

    asyncio.run(scenario())


def test_print_mode_json_prefers_common_runtime_event_stream() -> None:
    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )

    class FakeRuntime:
        pass

    class FakeSessionManager:
        def get_header(self) -> ConversationHeader:
            return ConversationHeader(
                conversation_id="session-1",
                version=1,
                created_at="2026-07-19T00:00:00Z",
                metadata={},
            )

    class FakeSession:
        def __init__(self) -> None:
            self.session_manager = FakeSessionManager()
            self.runtime_listeners = []
            self.legacy_subscribe_called = False

        def subscribe(self, listener):
            del listener
            self.legacy_subscribe_called = True
            raise AssertionError("JSON mode must subscribe to runtime events")

        def subscribe_runtime_events(self, listener):
            self.runtime_listeners.append(listener)

            def unsubscribe() -> None:
                self.runtime_listeners.remove(listener)

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            del user_input, images
            for listener in list(self.runtime_listeners):
                listener(_runtime_event({"type": "agent_start"}, 1))

        async def wait_for_idle(self) -> None:
            return None

    async def scenario() -> None:
        stdout = StringIO()
        session = FakeSession()
        mode = PrintMode(
            runtime=FakeRuntime(),
            session=session,
            stdout=stdout,
            output_mode="json",
        )

        assert await mode.run_once("hello", dispose=False) == 0
        assert session.legacy_subscribe_called is False
        assert [
            json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()
        ][1] == {"type": "agent_start"}

    asyncio.run(scenario())


def test_print_mode_work_event_log_records_coding_turn_and_preserves_prompt_behavior() -> (
    None
):
    from loushang.ai.types import AssistantMessage, TextPart, Usage
    from loushang.coding.domain.work import create_coding_work_runtime
    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )
    from loushang.work import InMemoryEventLogBackend
    from loushang.work.session import SessionWorkHostPort

    image = {"type": "image", "mime_type": "image/png", "data": "abc"}
    usage = Usage(
        input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
    )
    assistant = AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text="done")],
        api="anthropic-messages",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=usage,
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )

    class FakeRuntime:
        pass

    class FakeSession:
        session_id = "session-1"

        def __init__(self) -> None:
            self.prompt_calls: list[tuple[str, object]] = []
            self.listeners = []
            self.runtime_listeners = []

        def subscribe(self, listener):
            self.listeners.append(listener)

            def unsubscribe() -> None:
                self.listeners.remove(listener)

            return unsubscribe

        def subscribe_runtime_events(self, listener):
            self.runtime_listeners.append(listener)

            def unsubscribe() -> None:
                self.runtime_listeners.remove(listener)

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            self.prompt_calls.append((user_input, images))
            payloads = [
                {
                    "type": "message_update",
                    "message": {"role": "assistant"},
                    "assistant_message_event": {"type": "text_delta", "text": "done"},
                },
                {"type": "message_end", "message": assistant},
            ]
            for sequence, payload in enumerate(payloads, start=1):
                for listener in list(self.listeners):
                    result = listener(payload)
                    if result is not None:
                        await result
                for listener in list(self.runtime_listeners):
                    result = listener(_runtime_event(payload, sequence))
                    if result is not None:
                        await result

        async def wait_for_idle(self) -> None:
            return None

    async def scenario() -> None:
        stdout = StringIO()
        event_log = InMemoryEventLogBackend()
        session = FakeSession()
        mode = PrintMode(
            runtime=FakeRuntime(),
            session=session,
            stdout=stdout,
            work_event_log=event_log,
            work_port=SessionWorkHostPort(
                create_coding_work_runtime(
                    session=session,
                    event_log=event_log,
                    session_id=lambda: session.session_id,
                )
            ),
            method_id="method:task:review",
        )

        exit_code = await mode.run_once("describe", images=[image])

        assert exit_code == 0
        assert stdout.getvalue() == "done\n"
        assert session.prompt_calls == [("describe", [image])]
        entries = event_log.query(session_id="session-1")
        assert [entry.payload["kind"] for entry in entries] == [
            "SubmitCodingTurn",
            "WorkRunStarted",
            "ContentDelta",
            "ContentDelta",
            "WorkRunCompleted",
        ]
        assert entries[0].payload["payload"] == {
            "text": "describe",
            "image_count": 1,
            "method_id": "method:task:review",
        }
        assert entries[1].payload["payload"]["method_id"] == "method:task:review"
        assert entries[4].payload["payload"]["method_id"] == "method:task:review"

    asyncio.run(scenario())


def test_print_mode_projects_assistant_text_and_tool_events() -> None:
    from loushang.ai.types import AssistantMessage, TextPart, Usage
    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )

    usage = Usage(
        input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
    )

    class FakeRuntime:
        pass

    class FakeSession:
        def __init__(self) -> None:
            self.listeners = []

        def subscribe(self, listener):
            self.listeners.append(listener)

            def unsubscribe() -> None:
                self.listeners.remove(listener)

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            assistant = AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[TextPart(type="text", text="done")],
                api="anthropic-messages",
                provider="faux",
                model="faux-model",
                response_id=None,
                usage=usage,
                stop_reason="stop",
                error_message=None,
                timestamp=0.0,
            )
            for listener in list(self.listeners):
                listener(
                    {
                        "type": "tool_execution_start",
                        "tool_call_id": "t1",
                        "tool_name": "bash",
                        "args": {},
                    }
                )
                listener({"type": "message_end", "message": assistant})
                listener(
                    {
                        "type": "tool_execution_end",
                        "tool_call_id": "t1",
                        "tool_name": "bash",
                        "result": {"content": [], "details": {}},
                        "is_error": False,
                    }
                )

        async def wait_for_idle(self) -> None:
            return None

    async def scenario() -> None:
        stdout = StringIO()
        mode = PrintMode(runtime=FakeRuntime(), session=FakeSession(), stdout=stdout)

        exit_code = await mode.run_once("hello")

        rendered = stdout.getvalue()
        assert exit_code == 0
        assert "[tool:bash t1] start" in rendered
        assert "[tool:bash t1] end" in rendered
        assert "done" in rendered

    asyncio.run(scenario())


def test_print_mode_text_distinguishes_multiple_same_tool_calls() -> None:
    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )

    class FakeRuntime:
        pass

    class FakeSession:
        def __init__(self) -> None:
            self.listeners = []

        def subscribe(self, listener):
            self.listeners.append(listener)

            def unsubscribe() -> None:
                self.listeners.remove(listener)

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            for listener in list(self.listeners):
                listener(
                    {
                        "type": "tool_execution_start",
                        "tool_call_id": "t1",
                        "tool_name": "bash",
                        "args": {"cmd": "pwd"},
                    }
                )
                listener(
                    {
                        "type": "tool_execution_start",
                        "tool_call_id": "t2",
                        "tool_name": "bash",
                        "args": {"cmd": "ls -1"},
                    }
                )

        async def wait_for_idle(self) -> None:
            return None

    async def scenario() -> None:
        stdout = StringIO()
        mode = PrintMode(runtime=FakeRuntime(), session=FakeSession(), stdout=stdout)

        exit_code = await mode.run_once("hello")

        rendered = stdout.getvalue()
        assert exit_code == 0
        assert "t1" in rendered
        assert "pwd" in rendered
        assert "t2" in rendered
        assert "ls -1" in rendered

    asyncio.run(scenario())


def test_print_mode_returns_nonzero_and_prints_error_on_failure() -> None:
    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )

    class FakeRuntime:
        pass

    class FakeSession:
        def subscribe(self, listener):
            def unsubscribe() -> None:
                return None

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            raise RuntimeError("boom")

        async def wait_for_idle(self) -> None:
            raise AssertionError("should not be called")

    async def scenario() -> None:
        stdout = StringIO()
        stderr = StringIO()
        mode = PrintMode(
            runtime=FakeRuntime(), session=FakeSession(), stdout=stdout, stderr=stderr
        )

        exit_code = await mode.run_once("hello")

        assert exit_code == 1
        assert "Error: boom" in stderr.getvalue()

    asyncio.run(scenario())


@pytest.mark.parametrize("output_mode", ["text", "json"])
def test_print_mode_run_once_disposes_runtime_after_exit(output_mode: str) -> None:
    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )

    class FakeRuntime:
        def __init__(self) -> None:
            self.shutdown_events: list[dict[str, str]] = []

        async def dispose(self) -> None:
            self.shutdown_events.append({"type": "session_shutdown", "reason": "quit"})

    class FakeSessionManager:
        def get_header(self) -> ConversationHeader:
            return _session_header(
                type="session",
                version=3,
                id="s1",
                timestamp="2026-05-20T10:00:00.000Z",
                cwd="/tmp/project",
                parent_session=None,
            )

    class FakeSession:
        def __init__(self) -> None:
            self.session_manager = FakeSessionManager()
            self.listeners = []

        def subscribe(self, listener):
            self.listeners.append(listener)

            def unsubscribe() -> None:
                self.listeners.remove(listener)

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            return None

        async def wait_for_idle(self) -> None:
            return None

    async def scenario() -> None:
        runtime = FakeRuntime()
        mode = PrintMode(
            runtime=runtime,
            session=FakeSession(),
            stdout=StringIO(),
            stderr=StringIO(),
            output_mode=output_mode,
        )

        exit_code = await mode.run_once("hello")

        assert exit_code == 0
        assert runtime.shutdown_events == [
            {"type": "session_shutdown", "reason": "quit"}
        ]

    asyncio.run(scenario())


def test_print_mode_run_once_disposes_runtime_after_prompt_error() -> None:
    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )

    class FakeRuntime:
        def __init__(self) -> None:
            self.dispose_calls = 0

        async def dispose(self) -> None:
            self.dispose_calls += 1

    class FakeSession:
        def subscribe(self, listener):
            def unsubscribe() -> None:
                return None

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            raise RuntimeError("boom")

        async def wait_for_idle(self) -> None:
            raise AssertionError("should not be called")

    async def scenario() -> None:
        runtime = FakeRuntime()
        stderr = StringIO()
        mode = PrintMode(
            runtime=runtime, session=FakeSession(), stdout=StringIO(), stderr=stderr
        )

        exit_code = await mode.run_once("hello")

        assert exit_code == 1
        assert runtime.dispose_calls == 1
        assert "Error: boom" in stderr.getvalue()

    asyncio.run(scenario())


def test_print_mode_returns_nonzero_and_disposes_on_assistant_error_message() -> None:
    from types import SimpleNamespace

    from loushang.ai.types import AssistantMessage, Usage
    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )

    assistant = AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[],
        api="anthropic-messages",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=Usage(
            input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
        ),
        stop_reason="error",
        error_message="provider failure",
        timestamp=0.0,
    )

    class FakeRuntime:
        def __init__(self) -> None:
            self.dispose_calls = 0

        async def dispose(self) -> None:
            self.dispose_calls += 1

    class FakeSession:
        def __init__(self) -> None:
            self._messages = [assistant]

        def subscribe(self, listener):
            def unsubscribe() -> None:
                return None

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            return None

        async def wait_for_idle(self) -> None:
            return None

        def get_session_context(self):
            return SimpleNamespace(messages=tuple(self._messages))

    async def scenario() -> None:
        runtime = FakeRuntime()
        stderr = StringIO()
        mode = PrintMode(
            runtime=runtime, session=FakeSession(), stdout=StringIO(), stderr=stderr
        )

        exit_code = await mode.run_once("hello")

        assert exit_code == 1
        assert runtime.dispose_calls == 1
        assert stderr.getvalue() == "provider failure\n"

    asyncio.run(scenario())


def test_print_mode_returns_nonzero_on_aborted_assistant_message() -> None:
    from types import SimpleNamespace

    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )

    assistant = SimpleNamespace(
        role="assistant", stop_reason="aborted", error_message=None
    )

    class FakeRuntime:
        def __init__(self) -> None:
            self.dispose_calls = 0

        async def dispose(self) -> None:
            self.dispose_calls += 1

    class FakeSession:
        def subscribe(self, listener):
            def unsubscribe() -> None:
                return None

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            return None

        async def wait_for_idle(self) -> None:
            return None

        def get_session_context(self):
            return SimpleNamespace(messages=[assistant])

    async def scenario() -> None:
        runtime = FakeRuntime()
        stderr = StringIO()
        mode = PrintMode(
            runtime=runtime, session=FakeSession(), stdout=StringIO(), stderr=stderr
        )

        exit_code = await mode.run_once("hello")

        assert exit_code == 1
        assert runtime.dispose_calls == 1
        assert stderr.getvalue() == "Request aborted\n"

    asyncio.run(scenario())


def test_run_print_mode_wraps_print_mode() -> None:
    from loushang.harnesstui.conversation.agent_binding import (
        run_agent_plain_mode as run_print_mode,
    )

    class FakeRuntime:
        pass

    class FakeSession:
        def subscribe(self, listener):
            def unsubscribe() -> None:
                return None

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            return None

        async def wait_for_idle(self) -> None:
            return None

    async def scenario() -> None:
        exit_code = await run_print_mode(
            runtime=FakeRuntime(),
            session=FakeSession(),
            user_input="hello",
            stdout=StringIO(),
        )

        assert exit_code == 0

    asyncio.run(scenario())


def test_run_print_mode_passes_images_to_session_prompt() -> None:
    from loushang.harnesstui.conversation.agent_binding import (
        run_agent_plain_mode as run_print_mode,
    )

    image = {"type": "image", "mime_type": "image/png", "data": "abc"}

    class FakeRuntime:
        pass

    class FakeSession:
        def __init__(self) -> None:
            self.prompt_calls: list[tuple[str, object]] = []

        def subscribe(self, listener):
            def unsubscribe() -> None:
                return None

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            self.prompt_calls.append((user_input, images))

        async def wait_for_idle(self) -> None:
            return None

    async def scenario() -> None:
        session = FakeSession()

        exit_code = await run_print_mode(
            runtime=FakeRuntime(),
            session=session,
            user_input="describe",
            images=[image],
            stdout=StringIO(),
        )

        assert exit_code == 0
        assert session.prompt_calls == [("describe", [image])]

    asyncio.run(scenario())


def test_run_print_mode_sends_follow_up_messages_after_initial_prompt() -> None:
    from loushang.harnesstui.conversation.agent_binding import (
        run_agent_plain_mode as run_print_mode,
    )

    class FakeRuntime:
        pass

    class FakeSession:
        def __init__(self) -> None:
            self.prompt_calls: list[tuple[str, object]] = []
            self.wait_calls = 0

        def subscribe(self, listener):
            def unsubscribe() -> None:
                return None

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            self.prompt_calls.append((user_input, images))

        async def wait_for_idle(self) -> None:
            self.wait_calls += 1

    async def scenario() -> None:
        session = FakeSession()

        exit_code = await run_print_mode(
            runtime=FakeRuntime(),
            session=session,
            user_input="first",
            follow_up_messages=("second", "third"),
            stdout=StringIO(),
        )

        assert exit_code == 0
        assert session.prompt_calls == [
            ("first", None),
            ("second", None),
            ("third", None),
        ]
        assert session.wait_calls == 3

    asyncio.run(scenario())


def test_shared_agent_hosts_create_print_and_rpc_adapters() -> None:
    from loushang.harness.host.rpc import RpcHost
    from loushang.harnesstui.conversation.agent_binding import AgentPlainHost

    class FakeRuntime:
        def __init__(self, session) -> None:
            self._session = session

        def get_current_session(self):
            return self._session

    class FakeSession:
        session_id = "s1"
        session_name = None
        session_file = None

        def __init__(self) -> None:
            self.listeners = []
            self.agent = object()

        def subscribe(self, listener):
            self.listeners.append(listener)

            def unsubscribe() -> None:
                self.listeners.remove(listener)

            return unsubscribe

        def get_state(self):
            from types import SimpleNamespace

            return SimpleNamespace(
                run=SimpleNamespace(status="idle"),
                steering=[],
                follow_up=[],
                thinking_level="off",
                is_compacting=False,
                model_selection=None,
            )

        def get_session_context(self):
            from types import SimpleNamespace

            return SimpleNamespace(messages=[])

    session = FakeSession()
    runtime = FakeRuntime(session)

    print_mode = AgentPlainHost(
        runtime=runtime,
        session=session,
        stdout=StringIO(),
        output_mode="json",
    )
    rpc_mode = RpcHost(
        runtime=runtime,
        stdin=StringIO(),
        stdout=StringIO(),
    )

    assert isinstance(print_mode, AgentPlainHost)
    assert isinstance(rpc_mode, RpcHost)


def test_run_mode_routes_through_mode_adapter() -> None:
    from loushang.harness.host.mode import ModeConfig
    from loushang.harnesstui.conversation.agent_binding import (
        run_agent_mode as run_mode,
    )

    class FakeRuntime:
        pass

    class FakeSession:
        def __init__(self) -> None:
            self.prompt_calls: list[str] = []

        def subscribe(self, listener):
            def unsubscribe() -> None:
                return None

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            del images
            self.prompt_calls.append(user_input)

        async def wait_for_idle(self) -> None:
            return None

    async def scenario() -> None:
        session = FakeSession()
        exit_code = await run_mode(
            ModeConfig(mode="text"),
            runtime=FakeRuntime(),
            session=session,
            user_input="hello",
            stdin=StringIO(),
            stdout=StringIO(),
        )

        assert exit_code == 0
        assert session.prompt_calls == ["hello"]

    asyncio.run(scenario())


def test_run_mode_passes_work_event_log_to_print_adapter() -> None:
    from loushang.coding.domain.work import create_coding_work_runtime
    from loushang.harness.host.mode import ModeConfig
    from loushang.harnesstui.conversation.agent_binding import (
        run_agent_mode as run_mode,
    )
    from loushang.work import InMemoryEventLogBackend
    from loushang.work.session import SessionWorkHostPort

    class FakeRuntime:
        pass

    class FakeSession:
        session_id = "session-1"

        def __init__(self) -> None:
            self.listeners = []
            self.runtime_listeners = []

        def subscribe(self, listener):
            self.listeners.append(listener)

            def unsubscribe() -> None:
                self.listeners.remove(listener)

            return unsubscribe

        def subscribe_runtime_events(self, listener):
            self.runtime_listeners.append(listener)

            def unsubscribe() -> None:
                self.runtime_listeners.remove(listener)

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            del user_input, images
            payload = {
                "type": "message_update",
                "message": {"role": "assistant"},
                "assistant_message_event": {"type": "text_delta", "text": "done"},
            }
            for listener in list(self.listeners):
                result = listener(payload)
                if result is not None:
                    await result
            for listener in list(self.runtime_listeners):
                result = listener(_runtime_event(payload, 1))
                if result is not None:
                    await result

        async def wait_for_idle(self) -> None:
            return None

    async def scenario() -> None:
        event_log = InMemoryEventLogBackend()
        session = FakeSession()
        exit_code = await run_mode(
            ModeConfig(mode="text"),
            runtime=FakeRuntime(),
            session=session,
            user_input="hello",
            stdin=StringIO(),
            stdout=StringIO(),
            work_event_log=event_log,
            work_port=SessionWorkHostPort(
                create_coding_work_runtime(
                    session=session,
                    event_log=event_log,
                    session_id=lambda: session.session_id,
                )
            ),
        )

        assert exit_code == 0
        assert [
            entry.payload["kind"] for entry in event_log.query(session_id="session-1")
        ] == [
            "SubmitCodingTurn",
            "WorkRunStarted",
            "ContentDelta",
            "WorkRunCompleted",
        ]

    asyncio.run(scenario())


def test_dispatch_mode_action_routes_to_adapter_contract() -> None:
    from loushang.harness.host.mode import ModeAction, dispatch_mode_action

    class FakeAdapter:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        async def start(self, *args: object, **kwargs: object) -> int:
            del kwargs
            self.calls.append(("start", args))
            return 10

        async def stop(self) -> int:
            self.calls.append(("stop", None))
            return 11

        async def submit_input(self, input_payload: object) -> int:
            self.calls.append(("submit_input", input_payload))
            return 12

        async def wait_for_idle(self) -> int:
            self.calls.append(("wait_for_idle", None))
            return 13

        def rebind_session(self, session: object | None = None) -> int:
            self.calls.append(("rebind_session", session))
            return 14

        async def dispose(self) -> int:
            self.calls.append(("dispose", None))
            return 15

        def render_event(self, event: object) -> None:
            self.calls.append(("render_event", event))

        def get_mode_state(self):
            self.calls.append(("get_mode_state", None))
            return {"sessionId": "s1", "messageCount": 0}

    async def scenario() -> None:
        adapter = FakeAdapter()

        assert await dispatch_mode_action(adapter, ModeAction("start", "hello")) == 10
        assert (
            await dispatch_mode_action(adapter, ModeAction("submit_input", "next"))
            == 12
        )
        assert (
            await dispatch_mode_action(
                adapter, ModeAction("render_event", {"type": "noop"})
            )
            == 0
        )
        assert await dispatch_mode_action(adapter, ModeAction("get_state")) == {
            "sessionId": "s1",
            "messageCount": 0,
        }
        assert await dispatch_mode_action(adapter, ModeAction("wait_for_idle")) == 13
        assert (
            await dispatch_mode_action(
                adapter, ModeAction("rebind_session", "next-session")
            )
            == 14
        )
        assert await dispatch_mode_action(adapter, ModeAction("dispose")) == 15
        assert await dispatch_mode_action(adapter, ModeAction("stop")) == 11
        assert adapter.calls == [
            ("start", ("hello",)),
            ("submit_input", "next"),
            ("render_event", {"type": "noop"}),
            ("get_mode_state", None),
            ("wait_for_idle", None),
            ("rebind_session", "next-session"),
            ("dispose", None),
            ("stop", None),
        ]

    asyncio.run(scenario())


def test_mode_action_normalization_accepts_wire_payload_and_rejects_invalid() -> None:
    from loushang.harness.host.mode import ModeAction, normalize_mode_action

    assert normalize_mode_action(ModeAction("stop")) == ModeAction("stop")
    assert normalize_mode_action(
        {"type": "submit_input", "payload": "hello"}
    ) == ModeAction("submit_input", "hello")
    assert normalize_mode_action({"type": "get_state"}) == ModeAction("get_state")

    with pytest.raises(ValueError, match="Mode action requires string type"):
        normalize_mode_action({"payload": "hello"})

    with pytest.raises(ValueError, match="Unsupported mode action"):
        normalize_mode_action({"type": "unknown"})

    with pytest.raises(TypeError, match="Mode action must be"):
        normalize_mode_action("stop")


def test_dispatch_mode_action_accepts_wire_payload() -> None:
    from loushang.harness.host.mode import dispatch_mode_action

    class FakeAdapter:
        def __init__(self) -> None:
            self.inputs: list[object] = []

        async def start(self, *args: object, **kwargs: object) -> int:
            del args, kwargs
            return 0

        async def stop(self) -> int:
            return 0

        async def submit_input(self, input_payload: object) -> int:
            self.inputs.append(input_payload)
            return 7

        async def wait_for_idle(self) -> int:
            return 0

        def rebind_session(self, session: object | None = None) -> int:
            del session
            return 0

        async def dispose(self) -> int:
            return 0

        def render_event(self, event: object) -> None:
            del event

        def get_mode_state(self):
            return {}

    async def scenario() -> None:
        adapter = FakeAdapter()
        assert (
            await dispatch_mode_action(
                adapter, {"type": "submit_input", "payload": "from-wire"}
            )
            == 7
        )
        assert adapter.inputs == ["from-wire"]

    asyncio.run(scenario())


def test_print_mode_lifecycle_actions_delegate_to_runtime_and_session() -> None:
    from loushang.harness.host.mode import ModeAction, dispatch_mode_action
    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )

    class FakeRuntime:
        def __init__(self, session) -> None:
            self.session = session
            self.dispose_calls = 0

        def get_current_session(self):
            return self.session

        async def dispose(self) -> None:
            self.dispose_calls += 1

    class FakeSession:
        def __init__(self) -> None:
            self.wait_calls = 0

        async def wait_for_idle(self) -> None:
            self.wait_calls += 1

    async def scenario() -> None:
        first = FakeSession()
        second = FakeSession()
        runtime = FakeRuntime(second)
        mode = PrintMode(runtime=runtime, session=first, stdout=StringIO())

        assert await dispatch_mode_action(mode, ModeAction("wait_for_idle")) == 0
        assert first.wait_calls == 1
        assert await dispatch_mode_action(mode, ModeAction("rebind_session")) == 0
        assert mode.session is second
        assert await dispatch_mode_action(mode, ModeAction("dispose")) == 0
        assert runtime.dispose_calls == 1

    asyncio.run(scenario())


def test_print_mode_json_output_writes_header_before_event_lines() -> None:
    import asyncio
    import json
    from io import StringIO

    from loushang.ai.types import AssistantMessage, TextPart, Usage
    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )

    usage = Usage(
        input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
    )

    class FakeRuntime:
        pass

    class FakeSessionManager:
        def get_header(self) -> ConversationHeader:
            return _session_header(
                type="session",
                version=3,
                id="s1",
                timestamp="2026-05-20T10:00:00.000Z",
                cwd="/tmp/project",
                parent_session=None,
            )

    class FakeSession:
        def __init__(self) -> None:
            self.listeners = []
            self.session_manager = FakeSessionManager()

        def subscribe(self, listener):
            self.listeners.append(listener)

            def unsubscribe() -> None:
                self.listeners.remove(listener)

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            assistant = AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[TextPart(type="text", text="done")],
                api="anthropic-messages",
                provider="faux",
                model="faux-model",
                response_id=None,
                usage=usage,
                stop_reason="stop",
                error_message=None,
                timestamp=0.0,
            )
            for listener in list(self.listeners):
                listener({"type": "agent_start"})
                listener({"type": "message_end", "message": assistant})

        async def wait_for_idle(self) -> None:
            return None

    async def scenario() -> None:
        stdout = StringIO()
        mode = PrintMode(
            runtime=FakeRuntime(),
            session=FakeSession(),
            stdout=stdout,
            output_mode="json",
        )

        exit_code = await mode.run_once("hello")

        lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
        assert exit_code == 0
        assert lines[0]["type"] == "conversation"
        assert lines[0]["conversationId"] == "s1"
        assert lines[1]["type"] == "agent_start"
        assert lines[2]["type"] == "message_end"
        assert lines[2]["message"]["role"] == "assistant"

    asyncio.run(scenario())


def test_run_print_mode_supports_json_output_mode() -> None:
    import asyncio
    import json
    from io import StringIO

    from loushang.harnesstui.conversation.agent_binding import (
        run_agent_plain_mode as run_print_mode,
    )

    class FakeRuntime:
        pass

    class FakeSessionManager:
        def get_header(self) -> ConversationHeader:
            return _session_header(
                type="session",
                version=3,
                id="s1",
                timestamp="2026-05-20T10:00:00.000Z",
                cwd="/tmp/project",
                parent_session=None,
            )

    class FakeSession:
        def __init__(self) -> None:
            self.session_manager = FakeSessionManager()
            self.listeners = []

        def subscribe(self, listener):
            self.listeners.append(listener)

            def unsubscribe() -> None:
                self.listeners.remove(listener)

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            for listener in list(self.listeners):
                listener({"type": "agent_start"})

        async def wait_for_idle(self) -> None:
            return None

    async def scenario() -> None:
        stdout = StringIO()
        exit_code = await run_print_mode(
            runtime=FakeRuntime(),
            session=FakeSession(),
            user_input="hello",
            stdout=stdout,
            output_mode="json",
        )

        lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
        assert exit_code == 0
        assert lines[0]["type"] == "conversation"
        assert lines[1]["type"] == "agent_start"

    asyncio.run(scenario())


def test_print_mode_rejects_invalid_output_mode() -> None:
    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )

    class FakeRuntime:
        pass

    class FakeSession:
        def subscribe(self, listener):
            def unsubscribe() -> None:
                return None

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            return None

        async def wait_for_idle(self) -> None:
            return None

    with pytest.raises(ValueError, match="unsupported output mode"):
        PrintMode(
            runtime=FakeRuntime(),
            session=FakeSession(),
            stdout=StringIO(),
            output_mode="xml",  # type: ignore[arg-type]
        )


def test_print_mode_rejects_rendered_tool_events_for_text_output() -> None:
    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )

    class FakeRuntime:
        pass

    class FakeSession:
        pass

    with pytest.raises(
        ValueError, match="render_tool_events is only supported for json output mode"
    ):
        PrintMode(
            runtime=FakeRuntime(),
            session=FakeSession(),
            stdout=StringIO(),
            render_tool_events=True,
        )


def test_print_mode_json_compact_view_projects_assistant_stream_and_tool_lifecycle() -> (
    None
):
    import asyncio
    import json
    from io import StringIO

    from loushang.agent import AgentToolResult
    from loushang.ai.types import AssistantMessage, TextPart, Usage
    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )

    usage = Usage(
        input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
    )
    assistant = AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text="hello")],
        api="anthropic-messages",
        provider="anthropic",
        model="claude-sonnet",
        response_id="resp-1",
        usage=usage,
        stop_reason="stop",
        error_message=None,
        timestamp=1.0,
    )

    class FakeRuntime:
        pass

    class FakeSessionManager:
        def get_header(self) -> ConversationHeader:
            return _session_header(
                type="session",
                version=3,
                id="s1",
                timestamp="2026-05-20T10:00:00.000Z",
                cwd="/tmp/project",
                parent_session=None,
            )

    class FakeSession:
        def __init__(self) -> None:
            self.session_manager = FakeSessionManager()
            self.listeners = []

        def subscribe(self, listener):
            self.listeners.append(listener)

            def unsubscribe() -> None:
                self.listeners.remove(listener)

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            for listener in list(self.listeners):
                listener(
                    {
                        "type": "tool_execution_start",
                        "tool_call_id": "t1",
                        "tool_name": "bash",
                        "args": {"cmd": "pwd"},
                    }
                )
                listener(
                    {
                        "type": "message_update",
                        "message": assistant,
                        "assistant_message_event": {
                            "type": "text_delta",
                            "content_index": 0,
                            "delta": "he",
                        },
                    }
                )
                listener({"type": "message_end", "message": assistant})
                listener(
                    {
                        "type": "tool_execution_end",
                        "tool_call_id": "t1",
                        "tool_name": "bash",
                        "result": AgentToolResult(content=[], details={}),
                        "is_error": False,
                    }
                )

        async def wait_for_idle(self) -> None:
            return None

    async def scenario() -> None:
        stdout = StringIO()
        mode = PrintMode(
            runtime=FakeRuntime(),
            session=FakeSession(),
            stdout=stdout,
            output_mode="json",
            event_view="compact",
        )

        exit_code = await mode.run_once("hello")

        lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
        assert exit_code == 0
        assert [line["type"] for line in lines] == [
            "conversation",
            "tool_execution_start",
            "assistant_delta",
            "assistant_final",
            "tool_execution_end",
        ]
        assert lines[2]["delta"] == "he"
        assert lines[3]["message"]["response_id"] == "resp-1"

    asyncio.run(scenario())


def test_print_mode_json_can_include_rendered_tool_event_payloads() -> None:
    import asyncio
    import json
    from io import StringIO

    from loushang.agent.types import AgentToolResult
    from loushang.ai.types import TextPart
    from loushang.harness.tools.workspace import ToolDefinition
    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[TextPart(type="text", text="ok")], details={})

    def render_call(args, theme, context):
        del theme
        context.state["command"] = args["command"]
        return {"text": f"call {args['command']}"}

    def render_result(result, options, theme, context):
        del theme
        return {
            "text": f"{context.state['command']} {result.content[0].text} partial={options.is_partial}"
        }

    definition = ToolDefinition(
        name="bash",
        label="Bash",
        description="Run commands",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        execution=direct_execution(execute),
        render_call=render_call,
        render_result=render_result,
    )

    class FakeRuntime:
        pass

    class FakeSessionManager:
        def get_header(self) -> ConversationHeader:
            return _session_header(
                type="session",
                version=3,
                id="s1",
                timestamp="2026-05-20T10:00:00.000Z",
                cwd="/tmp/project",
                parent_session=None,
            )

        def get_cwd(self) -> str:
            return "/tmp/project"

    class FakeSession:
        def __init__(self) -> None:
            self.session_manager = FakeSessionManager()
            self.listeners = []

        def subscribe(self, listener):
            self.listeners.append(listener)

            def unsubscribe() -> None:
                self.listeners.remove(listener)

            return unsubscribe

        def get_tool_definition(self, name):
            return definition if name == "bash" else None

        async def prompt(self, user_input: str, images=None) -> None:
            for listener in list(self.listeners):
                listener(
                    {
                        "type": "tool_execution_start",
                        "tool_call_id": "tc1",
                        "tool_name": "bash",
                        "args": {"command": "echo hi"},
                    }
                )
                listener(
                    {
                        "type": "tool_execution_update",
                        "tool_call_id": "tc1",
                        "tool_name": "bash",
                        "args": {"command": "echo hi"},
                        "partial_result": AgentToolResult(
                            content=[TextPart(type="text", text="running")], details={}
                        ),
                    }
                )

        async def wait_for_idle(self) -> None:
            return None

    async def scenario() -> None:
        stdout = StringIO()
        mode = PrintMode(
            runtime=FakeRuntime(),
            session=FakeSession(),
            stdout=stdout,
            output_mode="json",
            event_view="tools",
            render_tool_events=True,
        )

        exit_code = await mode.run_once("hello")

        lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
        assert exit_code == 0
        assert "rendered_tool_call" not in lines[0]
        assert lines[1]["rendered_tool_call"] == {
            "type": "text",
            "text": "call echo hi",
            "plain_text": "call echo hi",
            "contract_version": 1,
            "status": "running",
        }
        assert lines[2]["rendered_tool_result"] == {
            "type": "text",
            "text": "echo hi running partial=True",
            "plain_text": "echo hi running partial=True",
            "is_partial": True,
            "expanded": False,
            "contract_version": 1,
            "status": "partial",
            "collapsed_text": "echo hi running partial=True",
            "artifacts": [],
        }

    asyncio.run(scenario())


def test_print_mode_json_event_select_filters_projected_events() -> None:
    import asyncio
    import json
    from io import StringIO

    from loushang.agent import AgentToolResult
    from loushang.ai.types import AssistantMessage, TextPart, Usage
    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )

    usage = Usage(
        input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
    )
    assistant = AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text="hello")],
        api="anthropic-messages",
        provider="anthropic",
        model="claude-sonnet",
        response_id="resp-1",
        usage=usage,
        stop_reason="stop",
        error_message=None,
        timestamp=1.0,
    )

    class FakeRuntime:
        pass

    class FakeSessionManager:
        def get_header(self) -> ConversationHeader:
            return _session_header(
                type="session",
                version=3,
                id="s1",
                timestamp="2026-05-20T10:00:00.000Z",
                cwd="/tmp/project",
                parent_session=None,
            )

    class FakeSession:
        def __init__(self) -> None:
            self.session_manager = FakeSessionManager()
            self.listeners = []

        def subscribe(self, listener):
            self.listeners.append(listener)

            def unsubscribe() -> None:
                self.listeners.remove(listener)

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            for listener in list(self.listeners):
                listener(
                    {
                        "type": "tool_execution_start",
                        "tool_call_id": "t1",
                        "tool_name": "bash",
                        "args": {"cmd": "pwd"},
                    }
                )
                listener(
                    {
                        "type": "message_update",
                        "message": assistant,
                        "assistant_message_event": {
                            "type": "text_delta",
                            "content_index": 0,
                            "delta": "he",
                        },
                    }
                )
                listener({"type": "message_end", "message": assistant})
                listener(
                    {
                        "type": "tool_execution_end",
                        "tool_call_id": "t1",
                        "tool_name": "bash",
                        "result": AgentToolResult(content=[], details={}),
                        "is_error": False,
                    }
                )

        async def wait_for_idle(self) -> None:
            return None

    async def scenario() -> None:
        stdout = StringIO()
        mode = PrintMode(
            runtime=FakeRuntime(),
            session=FakeSession(),
            stdout=stdout,
            output_mode="json",
            event_view="compact",
            event_select=("assistant_delta", "assistant_final"),
        )

        exit_code = await mode.run_once("hello")

        lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
        assert exit_code == 0
        assert [line["type"] for line in lines] == [
            "conversation",
            "assistant_delta",
            "assistant_final",
        ]

    asyncio.run(scenario())


def test_print_mode_json_full_view_event_select_supports_prefix_patterns() -> None:
    import asyncio
    import json
    from io import StringIO

    from loushang.agent import AgentToolResult
    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )

    class FakeRuntime:
        pass

    class FakeSessionManager:
        def get_header(self) -> ConversationHeader:
            return _session_header(
                type="session",
                version=3,
                id="s1",
                timestamp="2026-05-20T10:00:00.000Z",
                cwd="/tmp/project",
                parent_session=None,
            )

    class FakeSession:
        def __init__(self) -> None:
            self.session_manager = FakeSessionManager()
            self.listeners = []

        def subscribe(self, listener):
            self.listeners.append(listener)

            def unsubscribe() -> None:
                self.listeners.remove(listener)

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            for listener in list(self.listeners):
                listener({"type": "agent_start"})
                listener(
                    {
                        "type": "tool_execution_start",
                        "tool_call_id": "t1",
                        "tool_name": "bash",
                        "args": {"cmd": "pwd"},
                    }
                )
                listener(
                    {
                        "type": "tool_execution_end",
                        "tool_call_id": "t1",
                        "tool_name": "bash",
                        "result": AgentToolResult(content=[], details={}),
                        "is_error": False,
                    }
                )

        async def wait_for_idle(self) -> None:
            return None

    async def scenario() -> None:
        stdout = StringIO()
        mode = PrintMode(
            runtime=FakeRuntime(),
            session=FakeSession(),
            stdout=stdout,
            output_mode="json",
            event_view="full",
            event_select=("tool_execution_*",),
        )

        exit_code = await mode.run_once("hello")

        lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
        assert exit_code == 0
        assert [line["type"] for line in lines] == [
            "conversation",
            "tool_execution_start",
            "tool_execution_end",
        ]

    asyncio.run(scenario())


def test_print_mode_json_event_select_accepts_single_string_pattern() -> None:
    import asyncio
    import json
    from io import StringIO

    from loushang.agent import AgentToolResult
    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )

    class FakeRuntime:
        pass

    class FakeSessionManager:
        def get_header(self) -> ConversationHeader:
            return _session_header(
                type="session",
                version=3,
                id="s1",
                timestamp="2026-05-20T10:00:00.000Z",
                cwd="/tmp/project",
                parent_session=None,
            )

    class FakeSession:
        def __init__(self) -> None:
            self.session_manager = FakeSessionManager()
            self.listeners = []

        def subscribe(self, listener):
            self.listeners.append(listener)

            def unsubscribe() -> None:
                self.listeners.remove(listener)

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            for listener in list(self.listeners):
                listener({"type": "agent_start"})
                listener(
                    {
                        "type": "tool_execution_start",
                        "tool_call_id": "t1",
                        "tool_name": "bash",
                        "args": {"cmd": "pwd"},
                    }
                )
                listener(
                    {
                        "type": "tool_execution_end",
                        "tool_call_id": "t1",
                        "tool_name": "bash",
                        "result": AgentToolResult(content=[], details={}),
                        "is_error": False,
                    }
                )

        async def wait_for_idle(self) -> None:
            return None

    async def scenario() -> None:
        stdout = StringIO()
        mode = PrintMode(
            runtime=FakeRuntime(),
            session=FakeSession(),
            stdout=stdout,
            output_mode="json",
            event_view="full",
            event_select="tool_execution_*",
        )

        exit_code = await mode.run_once("hello")

        lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
        assert exit_code == 0
        assert [line["type"] for line in lines] == [
            "conversation",
            "tool_execution_start",
            "tool_execution_end",
        ]

    asyncio.run(scenario())


def test_print_mode_json_default_stderr_routes_errors_off_stdout() -> None:
    import asyncio
    import json
    from io import StringIO

    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )

    class FakeRuntime:
        pass

    class FakeSessionManager:
        def get_header(self) -> ConversationHeader:
            return _session_header(
                type="session",
                version=3,
                id="s1",
                timestamp="2026-05-20T10:00:00.000Z",
                cwd="/tmp/project",
                parent_session=None,
            )

    class FakeSession:
        def __init__(self) -> None:
            self.session_manager = FakeSessionManager()

        def subscribe(self, listener):
            def unsubscribe() -> None:
                return None

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            raise RuntimeError("boom")

        async def wait_for_idle(self) -> None:
            raise AssertionError("should not be called")

    async def scenario() -> None:
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stderr(stderr):
            mode = PrintMode(
                runtime=FakeRuntime(),
                session=FakeSession(),
                stdout=stdout,
                output_mode="json",
            )
            exit_code = await mode.run_once("hello")

        header = serialize_session_header(
            _session_header(
                type="session",
                version=3,
                id="s1",
                timestamp="2026-05-20T10:00:00.000Z",
                cwd="/tmp/project",
                parent_session=None,
            )
        )
        assert exit_code == 1
        assert stdout.getvalue().splitlines() == [json.dumps(header)]
        assert "Error: boom" in stderr.getvalue()

    asyncio.run(scenario())


def test_print_mode_json_failure_keeps_stdout_json_and_writes_error_to_stderr() -> None:
    import asyncio
    import json
    from io import StringIO

    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )

    class FakeRuntime:
        pass

    class FakeSessionManager:
        def get_header(self) -> ConversationHeader:
            return _session_header(
                type="session",
                version=3,
                id="s1",
                timestamp="2026-05-20T10:00:00.000Z",
                cwd="/tmp/project",
                parent_session=None,
            )

    class FakeSession:
        def __init__(self) -> None:
            self.session_manager = FakeSessionManager()

        def subscribe(self, listener):
            def unsubscribe() -> None:
                return None

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            raise RuntimeError("boom")

        async def wait_for_idle(self) -> None:
            raise AssertionError("should not be called")

    async def scenario() -> None:
        stdout = StringIO()
        stderr = StringIO()
        mode = PrintMode(
            runtime=FakeRuntime(),
            session=FakeSession(),
            stdout=stdout,
            stderr=stderr,
            output_mode="json",
        )

        exit_code = await mode.run_once("hello")

        lines = stdout.getvalue().splitlines()
        header = serialize_session_header(
            _session_header(
                type="session",
                version=3,
                id="s1",
                timestamp="2026-05-20T10:00:00.000Z",
                cwd="/tmp/project",
                parent_session=None,
            )
        )
        assert exit_code == 1
        assert lines == [json.dumps(header)]
        assert "Error: boom" in stderr.getvalue()

    asyncio.run(scenario())


def test_print_mode_json_header_failure_returns_error_without_writing_stdout() -> None:
    import asyncio
    from io import StringIO

    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )

    class FakeRuntime:
        pass

    class FakeSessionManager:
        def get_header(self):
            raise RuntimeError("header boom")

    class FakeSession:
        def __init__(self) -> None:
            self.session_manager = FakeSessionManager()
            self.unsubscribe_calls = 0

        def subscribe(self, listener):
            def unsubscribe() -> None:
                self.unsubscribe_calls += 1

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            raise AssertionError("should not be called")

        async def wait_for_idle(self) -> None:
            raise AssertionError("should not be called")

    async def scenario() -> None:
        stdout = StringIO()
        stderr = StringIO()
        mode = PrintMode(
            runtime=FakeRuntime(),
            session=FakeSession(),
            stdout=stdout,
            stderr=stderr,
            output_mode="json",
        )

        exit_code = await mode.run_once("hello")

        assert exit_code == 1
        assert stdout.getvalue() == ""
        assert "Error: header boom" in stderr.getvalue()

    asyncio.run(scenario())


def test_print_mode_json_writes_header_before_subscription() -> None:
    import asyncio
    import json
    from io import StringIO

    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )

    class FakeRuntime:
        pass

    class FakeSessionManager:
        def get_header(self) -> ConversationHeader:
            return _session_header(
                type="session",
                version=3,
                id="s1",
                timestamp="2026-05-20T10:00:00.000Z",
                cwd="/tmp/project",
                parent_session=None,
            )

    async def scenario() -> None:
        stdout = StringIO()

        class FakeSession:
            def __init__(self) -> None:
                self.session_manager = FakeSessionManager()
                self.listeners = []

            def subscribe(self, listener):
                header = json.dumps(
                    serialize_session_header(
                        _session_header(
                            type="session",
                            version=3,
                            id="s1",
                            timestamp="2026-05-20T10:00:00.000Z",
                            cwd="/tmp/project",
                            parent_session=None,
                        )
                    )
                )
                assert stdout.getvalue().splitlines() == [header]
                self.listeners.append(listener)

                def unsubscribe() -> None:
                    self.listeners.remove(listener)

                return unsubscribe

            async def prompt(self, user_input: str, images=None) -> None:
                for listener in list(self.listeners):
                    listener({"type": "agent_start"})

            async def wait_for_idle(self) -> None:
                return None

        mode = PrintMode(
            runtime=FakeRuntime(),
            session=FakeSession(),
            stdout=stdout,
            output_mode="json",
        )

        exit_code = await mode.run_once("hello")

        assert exit_code == 0
        assert stdout.getvalue().splitlines()[0] == json.dumps(
            serialize_session_header(
                _session_header(
                    type="session",
                    version=3,
                    id="s1",
                    timestamp="2026-05-20T10:00:00.000Z",
                    cwd="/tmp/project",
                    parent_session=None,
                )
            )
        )

    asyncio.run(scenario())


def test_print_mode_json_streams_all_supported_session_events() -> None:
    import asyncio
    import json
    from io import StringIO

    from loushang.agent import AgentToolResult
    from loushang.ai.types import AssistantMessage, TextPart, ToolResultMessage, Usage
    from loushang.harness.transcript import ApplicationMessage
    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )

    usage = Usage(
        input=1, output=2, cache_read=3, cache_write=4, total_tokens=5, cost={}
    )
    assistant = AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text="hello")],
        api="anthropic-messages",
        provider="anthropic",
        model="claude-sonnet",
        response_id="resp-1",
        usage=usage,
        stop_reason="stop",
        error_message=None,
        timestamp=1.0,
    )
    tool_result = ToolResultMessage(
        role="toolResult",
        tool_call_id="tool-call-1",
        tool_name="bash",
        content=[TextPart(type="text", text="result")],
        is_error=False,
        timestamp=2.0,
        details={"ok": True},
    )
    application_message = ApplicationMessage(
        application_message_id="application-1",
        custom_type="notice",
        content="done",
        timestamp=4.0,
    )

    def check_agent_start(payload: dict[str, object]) -> None:
        assert payload == {"type": "agent_start"}

    def check_turn_start(payload: dict[str, object]) -> None:
        assert payload == {"type": "turn_start"}

    def check_agent_end(payload: dict[str, object]) -> None:
        assert payload["type"] == "agent_end"
        assert "messages" in payload
        messages = payload["messages"]
        assert isinstance(messages, list)
        assert messages[0]["response_id"] == "resp-1"
        assert messages[1]["role"] == "application"
        assert "responseId" not in messages[0]

    def check_turn_end(payload: dict[str, object]) -> None:
        assert payload["type"] == "turn_end"
        assert "tool_results" in payload
        assert "toolResults" not in payload
        assert payload["message"]["response_id"] == "resp-1"
        assert payload["tool_results"][0]["tool_call_id"] == "tool-call-1"

    def check_message_start(payload: dict[str, object]) -> None:
        assert payload["type"] == "message_start"
        assert payload["message"]["response_id"] == "resp-1"
        assert "responseId" not in payload["message"]

    def check_message_update(payload: dict[str, object]) -> None:
        assert payload["type"] == "message_update"
        assert "assistant_message_event" in payload
        assert "assistantMessageEvent" not in payload
        assert payload["assistant_message_event"]["content_index"] == 0
        assert payload["assistant_message_event"]["delta"] == "he"

    def check_message_end(payload: dict[str, object]) -> None:
        assert payload["type"] == "message_end"
        assert payload["message"]["response_id"] == "resp-1"

    def check_tool_execution_start(payload: dict[str, object]) -> None:
        assert payload["type"] == "tool_execution_start"
        assert payload["tool_call_id"] == "t1"
        assert payload["tool_name"] == "bash"
        assert "toolCallId" not in payload
        assert "toolName" not in payload

    def check_tool_execution_update(payload: dict[str, object]) -> None:
        assert payload["type"] == "tool_execution_update"
        assert payload["partial_result"]["content"][0]["text"] == "progress"
        assert payload["partial_result"]["details"] == {"done": False}
        assert payload["partial_result"]["terminate"] is False
        assert "partialResult" not in payload

    def check_tool_execution_end(payload: dict[str, object]) -> None:
        assert payload["type"] == "tool_execution_end"
        assert payload["tool_call_id"] == "t1"
        assert payload["result"]["content"][0]["text"] == "ok"
        assert payload["result"]["details"] == {"ok": True}
        assert payload["result"]["terminate"] is False
        assert payload["is_error"] is False
        assert "isError" not in payload

    def check_queue_update(payload: dict[str, object]) -> None:
        assert payload["type"] == "queue_update"
        assert payload["follow_up"] == ["b"]
        assert "followUp" not in payload

    def check_compaction_start(payload: dict[str, object]) -> None:
        assert payload == {"type": "compaction_start", "reason": "manual"}

    def check_compaction_end(payload: dict[str, object]) -> None:
        assert payload["type"] == "compaction_end"
        assert payload["will_retry"] is True
        assert payload["error_message"] == "later"
        assert "willRetry" not in payload
        assert "errorMessage" not in payload

    def check_auto_retry_start(payload: dict[str, object]) -> None:
        assert payload["type"] == "auto_retry_start"
        assert payload["max_attempts"] == 3
        assert payload["delay_ms"] == 100
        assert payload["error_message"] == "boom"
        assert "maxAttempts" not in payload

    def check_auto_retry_end(payload: dict[str, object]) -> None:
        assert payload["type"] == "auto_retry_end"
        assert payload["final_error"] == "ignored"
        assert "finalError" not in payload

    session_events = [
        ({"type": "agent_start"}, check_agent_start),
        ({"type": "turn_start"}, check_turn_start),
        (
            {"type": "agent_end", "messages": [assistant, application_message]},
            check_agent_end,
        ),
        (
            {"type": "turn_end", "message": assistant, "tool_results": [tool_result]},
            check_turn_end,
        ),
        ({"type": "message_start", "message": assistant}, check_message_start),
        (
            {
                "type": "message_update",
                "message": assistant,
                "assistant_message_event": {
                    "type": "text_delta",
                    "content_index": 0,
                    "delta": "he",
                },
            },
            check_message_update,
        ),
        ({"type": "message_end", "message": assistant}, check_message_end),
        (
            {
                "type": "tool_execution_start",
                "tool_call_id": "t1",
                "tool_name": "bash",
                "args": {"x": 1},
            },
            check_tool_execution_start,
        ),
        (
            {
                "type": "tool_execution_update",
                "tool_call_id": "t1",
                "tool_name": "bash",
                "args": {"x": 1},
                "partial_result": AgentToolResult(
                    content=[TextPart(type="text", text="progress")],
                    details={"done": False},
                ),
            },
            check_tool_execution_update,
        ),
        (
            {
                "type": "tool_execution_end",
                "tool_call_id": "t1",
                "tool_name": "bash",
                "result": AgentToolResult(
                    content=[TextPart(type="text", text="ok")],
                    details={"ok": True},
                ),
                "is_error": False,
            },
            check_tool_execution_end,
        ),
        (
            {"type": "queue_update", "steering": ["a"], "follow_up": ["b"]},
            check_queue_update,
        ),
        ({"type": "compaction_start", "reason": "manual"}, check_compaction_start),
        (
            {
                "type": "compaction_end",
                "reason": "threshold",
                "result": {"ok": True},
                "aborted": False,
                "will_retry": True,
                "error_message": "later",
            },
            check_compaction_end,
        ),
        (
            {
                "type": "auto_retry_start",
                "attempt": 1,
                "max_attempts": 3,
                "delay_ms": 100,
                "error_message": "boom",
            },
            check_auto_retry_start,
        ),
        (
            {
                "type": "auto_retry_end",
                "success": True,
                "attempt": 2,
                "final_error": "ignored",
            },
            check_auto_retry_end,
        ),
    ]

    class FakeRuntime:
        pass

    class FakeSessionManager:
        def get_header(self) -> ConversationHeader:
            return _session_header(
                type="session",
                version=3,
                id="s1",
                timestamp="2026-05-20T10:00:00.000Z",
                cwd="/tmp/project",
                parent_session=None,
            )

    class FakeSession:
        def __init__(self) -> None:
            self.session_manager = FakeSessionManager()
            self.listeners = []

        def subscribe(self, listener):
            self.listeners.append(listener)

            def unsubscribe() -> None:
                self.listeners.remove(listener)

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            for event, _ in session_events:
                for listener in list(self.listeners):
                    listener(event)

        async def wait_for_idle(self) -> None:
            return None

    async def scenario() -> None:
        stdout = StringIO()
        mode = PrintMode(
            runtime=FakeRuntime(),
            session=FakeSession(),
            stdout=stdout,
            output_mode="json",
        )

        exit_code = await mode.run_once("hello")

        lines = stdout.getvalue().splitlines()
        assert exit_code == 0
        assert len(lines) == 1 + len(session_events)
        assert json.loads(lines[0])["type"] == "conversation"
        for line, (_, checker) in zip(lines[1:], session_events, strict=True):
            payload = json.loads(line)
            checker(payload)

    asyncio.run(scenario())


def test_print_mode_json_serializes_tool_results_and_preserves_utf8() -> None:
    import asyncio
    from io import StringIO
    from pathlib import Path

    from loushang.agent import AgentToolResult, FunctionalToolOutputProjector
    from loushang.ai.types import TextPart
    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )

    class FakeRuntime:
        pass

    class FakeSessionManager:
        def get_header(self) -> ConversationHeader:
            return _session_header(
                type="session",
                version=3,
                id="s1",
                timestamp="2026-05-20T10:00:00.000Z",
                cwd="/tmp/project",
                parent_session=None,
            )

    class FakeSession:
        def __init__(self) -> None:
            self.session_manager = FakeSessionManager()
            self.listeners = []

        def subscribe(self, listener):
            self.listeners.append(listener)

            def unsubscribe() -> None:
                self.listeners.remove(listener)

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            for listener in list(self.listeners):
                listener(
                    {
                        "type": "tool_execution_end",
                        "tool_call_id": "bash_0",
                        "tool_name": "bash",
                        "result": AgentToolResult(
                            content=[TextPart(type="text", text="你好")],
                            details={"cwd": Path("/tmp/project")},
                            projector=FunctionalToolOutputProjector(
                                transcript=lambda details: {"cwd": str(details["cwd"])},
                            ),
                        ),
                        "is_error": False,
                    }
                )

        async def wait_for_idle(self) -> None:
            return None

    async def scenario() -> None:
        stdout = StringIO()
        stderr = StringIO()
        mode = PrintMode(
            runtime=FakeRuntime(),
            session=FakeSession(),
            stdout=stdout,
            stderr=stderr,
            output_mode="json",
        )

        exit_code = await mode.run_once("hello")

        rendered = stdout.getvalue()
        assert exit_code == 0
        assert "你好" in rendered
        assert "\\u4f60\\u597d" not in rendered
        assert '"cwd": "/tmp/project"' in rendered
        assert "Error:" not in stderr.getvalue()

    asyncio.run(scenario())


def test_print_mode_json_event_sink_rejects_non_finite_values_without_output() -> None:
    from io import StringIO

    from loushang.foundation.json import JsonValueError
    from loushang.harnesstui.conversation.agent_binding import (
        AgentPlainHost as PrintMode,
    )

    stdout = StringIO()
    mode = PrintMode(
        runtime=object(), session=object(), stdout=stdout, output_mode="json"
    )

    with pytest.raises(JsonValueError) as exc_info:
        mode.render_event(
            {
                "type": "auto_retry_start",
                "attempt": 1,
                "max_attempts": 3,
                "delay_ms": float("nan"),
                "error_message": "retry",
            }
        )

    assert exc_info.value.path == "print_json_event.delay_ms"
    assert "non-finite float" in str(exc_info.value)
    assert stdout.getvalue() == ""
