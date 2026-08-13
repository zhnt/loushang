from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.ai.model import ModelSelection
from loushang.ai.model.domain import (
    Capabilities,
    Endpoint,
    Model,
    OpenAICompletionsConfig,
    Pricing,
)
from loushang.ai.types import TextPart
from loushang.harness.events import RuntimeEvent
from loushang.harness.host.rpc import RpcWirePlayback
from loushang.harness.tools.execution import direct_execution
from loushang.harness.transcript import (
    SessionQuery,
)
from tests.coding.rpc_support import (
    FakeModelRegistry,
    FakeRuntime,
    FakeSession,
    _assistant_message,
    _message_record,
    _parse_jsonl,
    _user_message,
)


def test_rpc_mode_runs_prompt_command_and_streams_events() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    session = FakeSession(
        session_id="session-a",
        cwd="/tmp/project",
        event_message=_assistant_message("done"),
    )
    runtime = FakeRuntime(session)
    stdin = StringIO(
        json.dumps({"id": "c1", "type": "prompt", "message": "hello"}) + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()

        assert exit_code == 0
        assert session.prompt_calls == [("hello", None)]
        assert session.wait_calls == 1

    asyncio.run(scenario())

    lines = _parse_jsonl(stdout)
    assert lines[0] == {
        "id": "c1",
        "type": "response",
        "command": "prompt",
        "success": True,
    }
    assert lines[1]["type"] == "message_end"
    assert lines[1]["message"]["role"] == "assistant"
    assert lines[1]["message"]["content"][0]["text"] == "done"


def test_rpc_mode_projects_stream_event_shape_and_tool_correlation() -> None:
    from loushang.agent.types import AgentToolResult
    from loushang.harness.host.rpc import RpcHost as RpcMode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdout = StringIO()

    RpcMode(runtime=runtime, stdin=StringIO(), stdout=stdout, event_view="tools")
    for listener in list(session.listeners):
        listener(
            {
                "type": "tool_execution_update",
                "tool_call_id": "tc1",
                "tool_name": "bash",
                "args": {"cmd": "echo hi"},
                "partial_result": AgentToolResult(
                    content=[TextPart(type="text", text="running")],
                    details={"progress": 0.5},
                ),
            }
        )

    event = _parse_jsonl(stdout)[0]
    assert event["type"] == "tool_execution_update"
    assert event["event_type"] == "tool_execution_update"
    assert event["correlation_id"] == "tc1"
    assert event["stream"] == {
        "kind": "session_event",
        "view": "tools",
        "correlation_id": "tc1",
    }
    assert event["tool_call_id"] == "tc1"
    assert event["tool_name"] == "bash"


def test_rpc_mode_prefers_common_runtime_event_stream() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime_listeners = []

    def subscribe_runtime_events(listener):
        runtime_listeners.append(listener)

        def unsubscribe() -> None:
            runtime_listeners.remove(listener)

        return unsubscribe

    session.subscribe_runtime_events = subscribe_runtime_events
    stdout = StringIO()
    RpcMode(runtime=FakeRuntime(session), stdin=StringIO(), stdout=stdout)

    for listener in list(runtime_listeners):
        listener(
            RuntimeEvent(
                event_id="event-1",
                kind="agent.agent_start",
                stream_id="session:session-a",
                sequence=1,
                occurred_at=datetime(2026, 7, 19, tzinfo=UTC),
                payload={"type": "agent_start"},
            )
        )

    assert session.listeners == []
    assert _parse_jsonl(stdout) == [
        {
            "type": "agent_start",
            "event_type": "agent_start",
            "stream": {"kind": "session_event", "view": "full"},
        }
    ]


def test_rpc_mode_can_include_rendered_tool_event_payloads() -> None:
    from loushang.agent.types import AgentToolResult
    from loushang.harness.host.rpc import RpcHost as RpcMode
    from loushang.harness.tools.workspace import ToolDefinition

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
    session = FakeSession(session_id="session-a", cwd="/tmp/project")

    def get_tool_definition(name):
        return definition if name == "bash" else None

    session.get_tool_definition = get_tool_definition
    runtime = FakeRuntime(session)
    stdout = StringIO()

    RpcMode(
        runtime=runtime,
        stdin=StringIO(),
        stdout=stdout,
        event_view="tools",
        render_tool_events=True,
    )
    for listener in list(session.listeners):
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

    lines = _parse_jsonl(stdout)
    assert lines[0]["rendered_tool_call"] == {
        "type": "text",
        "text": "call echo hi",
        "plain_text": "call echo hi",
        "contract_version": 1,
        "status": "running",
    }
    assert lines[1]["rendered_tool_result"] == {
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


def test_rpc_mode_get_state_and_messages_serialize_current_session() -> None:
    from loushang.harness.host.rpc import run_rpc_host as run_rpc_mode

    assistant = _assistant_message("ready")
    session = FakeSession(
        session_id="session-a",
        session_name="Alpha",
        cwd="/tmp/project",
        messages=[assistant],
    )
    session.model_registry = FakeModelRegistry(
        resolved_models={
            ("faux", "coding", "alpha"): Model(
                id="alpha",
                provider="faux",
                endpoint="coding",
                name="Faux Alpha",
                capabilities=Capabilities(
                    input=("text",),
                    context_window=200_000,
                    max_tokens=8_192,
                    reasoning=True,
                ),
                pricing=Pricing(input=1.5, output=2.5, cache_read=0.1, cache_write=0.2),
                adapter=OpenAICompletionsConfig(reasoning_effort=True),
            )
        },
        endpoints={
            ("faux", "coding"): Endpoint(
                id="coding",
                api="openai-completions",
                provider="faux",
                base_url="https://api.faux.test/v1",
            )
        },
    )
    asyncio.run(
        session.set_model(
            ModelSelection(endpoint_id="coding", provider="faux", model_id="alpha")
        )
    )
    asyncio.run(session.set_active_tools(["bash", "read"]))
    session.steer("first steer")
    runtime = FakeRuntime(session)
    stdin = StringIO(
        "\n".join(
            [
                json.dumps({"id": "state", "type": "get_state"}),
                json.dumps({"id": "messages", "type": "get_messages"}),
            ]
        )
        + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        exit_code = await run_rpc_mode(runtime=runtime, stdin=stdin, stdout=stdout)
        assert exit_code == 0

    asyncio.run(scenario())

    state_response, messages_response = _parse_jsonl(stdout)
    assert state_response["type"] == "response"
    assert state_response["command"] == "get_state"
    assert state_response["data"]["sessionId"] == "session-a"
    assert state_response["data"]["sessionName"] == "Alpha"
    assert state_response["data"]["sessionFile"] == "/tmp/project/session-a.jsonl"
    assert state_response["data"]["isStreaming"] is False
    assert state_response["data"]["model"] == {
        "provider": "faux",
        "endpointId": "coding",
        "id": "alpha",
        "name": "Faux Alpha",
        "api": "openai-completions",
        "baseUrl": "https://api.faux.test/v1",
        "input": ["text"],
        "contextWindow": 200_000,
        "maxTokens": 8_192,
        "reasoning": True,
        "cost": {
            "input": 1.5,
            "output": 2.5,
            "cacheRead": 0.1,
            "cacheWrite": 0.2,
        },
    }
    assert "cwd" not in state_response["data"]
    assert "modelSelection" not in state_response["data"]
    assert "activeToolNames" not in state_response["data"]
    assert "run" not in state_response["data"]
    assert "steering" not in state_response["data"]
    assert "followUp" not in state_response["data"]
    assert "isRetrying" not in state_response["data"]
    assert "autoRetryEnabled" not in state_response["data"]

    assert messages_response["type"] == "response"
    assert messages_response["command"] == "get_messages"
    assert messages_response["data"]["messages"][0]["role"] == "assistant"
    assert messages_response["data"]["messages"][0]["content"][0]["text"] == "ready"


def test_rpc_mode_list_sessions_uses_runtime_summaries() -> None:
    from loushang.harness.host.rpc import run_rpc_host as run_rpc_mode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(
        session,
        session_summaries=[
            SimpleNamespace(
                session_id="session-b",
                cwd="/tmp/project-b",
                session_file=Path("/tmp/session-b.jsonl"),
                parent_session="/tmp/session-a.jsonl",
                leaf_id="leaf-b",
                created_at="2026-05-21T10:00:00Z",
                updated_at="2026-05-22T10:00:00Z",
                name="Beta",
                message_count=4,
                entry_count=6,
                first_message="first beta prompt",
                all_messages_text="first beta prompt latest message",
                last_message_preview="latest message",
                model={"provider": "faux", "model_id": "beta"},
            )
        ],
    )
    stdin = StringIO(json.dumps({"id": "sessions", "type": "list_sessions"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        exit_code = await run_rpc_mode(runtime=runtime, stdin=stdin, stdout=stdout)
        assert exit_code == 0

    asyncio.run(scenario())

    response = _parse_jsonl(stdout)[0]
    assert runtime.find_session_summaries_calls == [SessionQuery()]
    assert runtime.list_session_summaries_calls == 0
    assert response["type"] == "response"
    assert response["command"] == "list_sessions"
    assert response["data"]["sessions"] == [
        {
            "sessionId": "session-b",
            "cwd": "/tmp/project-b",
            "sessionFile": "/tmp/session-b.jsonl",
            "parentSession": "/tmp/session-a.jsonl",
            "leafId": "leaf-b",
            "createdAt": "2026-05-21T10:00:00Z",
            "updatedAt": "2026-05-22T10:00:00Z",
            "name": "Beta",
            "messageCount": 4,
            "entryCount": 6,
            "firstMessage": "first beta prompt",
            "allMessagesText": "first beta prompt latest message",
            "lastMessagePreview": "latest message",
            "model": {"provider": "faux", "modelId": "beta"},
        }
    ]


def test_rpc_mode_list_sessions_supports_query_filters() -> None:
    from loushang.harness.host.rpc import run_rpc_host as run_rpc_mode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(
        session,
        session_summaries=[
            SimpleNamespace(
                session_id="session-alpha",
                cwd="/tmp/project-a",
                session_file=Path("/tmp/session-alpha.jsonl"),
                parent_session=None,
                leaf_id="leaf-alpha",
                created_at="2026-05-21T10:00:00Z",
                updated_at="2026-05-22T10:00:00Z",
                name="Alpha",
                message_count=2,
                entry_count=4,
                last_message_preview="alpha repository task",
                model=None,
            ),
            SimpleNamespace(
                session_id="session-beta",
                cwd="/tmp/project-b",
                session_file=Path("/tmp/session-beta.jsonl"),
                parent_session="/tmp/session-alpha.jsonl",
                leaf_id="leaf-beta",
                created_at="2026-05-22T10:00:00Z",
                updated_at="2026-05-23T10:00:00Z",
                name="Beta",
                message_count=3,
                entry_count=5,
                last_message_preview="beta follow up",
                model=None,
            ),
        ],
    )
    stdin = StringIO(
        json.dumps(
            {
                "id": "sessions",
                "type": "list_sessions",
                "name": "bet",
                "parentSession": "/tmp/session-alpha.jsonl",
                "text": "follow",
                "hasDiagnostics": True,
                "limit": 1,
            }
        )
        + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        exit_code = await run_rpc_mode(runtime=runtime, stdin=stdin, stdout=stdout)
        assert exit_code == 0

    asyncio.run(scenario())

    response = _parse_jsonl(stdout)[0]
    assert runtime.find_session_summaries_calls == [
        SessionQuery(
            name="bet",
            parent_session="/tmp/session-alpha.jsonl",
            text="follow",
            has_diagnostics=True,
            limit=1,
        )
    ]
    assert [item["sessionId"] for item in response["data"]["sessions"]] == [
        "session-beta"
    ]


def test_rpc_mode_list_sessions_supports_all_sessions() -> None:
    from loushang.harness.host.rpc import run_rpc_host as run_rpc_mode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(
        session,
        session_summaries=[
            SimpleNamespace(
                session_id="session-global",
                cwd="/tmp/project-global",
                session_file=Path("/tmp/session-global.jsonl"),
                parent_session=None,
                leaf_id="leaf-global",
                created_at="2026-05-22T10:00:00Z",
                updated_at="2026-05-23T10:00:00Z",
                name="Global",
                message_count=3,
                entry_count=5,
                last_message_preview="global lookup",
                model=None,
            )
        ],
    )
    stdin = StringIO(
        json.dumps(
            {
                "id": "sessions",
                "type": "list_sessions",
                "allSessions": True,
                "text": "lookup",
            }
        )
        + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        exit_code = await run_rpc_mode(runtime=runtime, stdin=stdin, stdout=stdout)
        assert exit_code == 0

    asyncio.run(scenario())

    response = _parse_jsonl(stdout)[0]
    assert runtime.find_all_session_summaries_calls == [SessionQuery(text="lookup")]
    assert runtime.find_session_summaries_calls == []
    assert [item["sessionId"] for item in response["data"]["sessions"]] == [
        "session-global"
    ]


def test_rpc_mode_list_sessions_can_use_indexed_summaries() -> None:
    from loushang.harness.host.rpc import run_rpc_host as run_rpc_mode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(
        session,
        session_summaries=[
            SimpleNamespace(
                session_id="session-indexed",
                cwd="/tmp/project-indexed",
                session_file=Path("/tmp/session-indexed.jsonl"),
                parent_session=None,
                leaf_id=None,
                created_at="2026-05-22T10:00:00Z",
                updated_at="2026-05-23T10:00:00Z",
                name="Indexed",
                message_count=3,
                entry_count=5,
                last_message_preview="indexed lookup",
                model=None,
            )
        ],
    )
    stdin = StringIO(
        json.dumps(
            {
                "id": "sessions",
                "type": "list_sessions",
                "useIndex": True,
                "text": "lookup",
            }
        )
        + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        exit_code = await run_rpc_mode(runtime=runtime, stdin=stdin, stdout=stdout)
        assert exit_code == 0

    asyncio.run(scenario())

    response = _parse_jsonl(stdout)[0]
    assert runtime.find_indexed_session_summaries_calls == [SessionQuery(text="lookup")]
    assert runtime.find_session_summaries_calls == []
    assert [item["sessionId"] for item in response["data"]["sessions"]] == [
        "session-indexed"
    ]


def test_rpc_mode_list_sessions_refresh_index_uses_indexed_all_session_query() -> None:
    from loushang.harness.host.rpc import run_rpc_host as run_rpc_mode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(
        json.dumps(
            {
                "id": "sessions",
                "type": "list_sessions",
                "allSessions": True,
                "refreshIndex": True,
                "text": "global",
            }
        )
        + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        exit_code = await run_rpc_mode(runtime=runtime, stdin=stdin, stdout=stdout)
        assert exit_code == 0

    asyncio.run(scenario())

    assert runtime.refresh_all_session_indexes_calls == 1
    assert runtime.find_all_indexed_session_summaries_calls == [
        SessionQuery(text="global")
    ]
    assert runtime.find_all_session_summaries_calls == []


def test_rpc_mode_list_sessions_rejects_invalid_limit() -> None:
    from loushang.harness.host.rpc import run_rpc_host as run_rpc_mode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(
        json.dumps({"id": "sessions", "type": "list_sessions", "limit": -1}) + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        exit_code = await run_rpc_mode(runtime=runtime, stdin=stdin, stdout=stdout)
        assert exit_code == 0

    asyncio.run(scenario())

    response = _parse_jsonl(stdout)[0]
    assert response == {
        "id": "sessions",
        "type": "response",
        "command": "list_sessions",
        "success": False,
        "error": "Session limit must be non-negative.",
    }


def test_rpc_mode_get_state_omits_optional_fields_when_unset() -> None:
    from loushang.harness.host.rpc import run_rpc_host as run_rpc_mode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    session.session_file = None
    runtime = FakeRuntime(session)
    stdin = StringIO(json.dumps({"id": "state", "type": "get_state"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        exit_code = await run_rpc_mode(runtime=runtime, stdin=stdin, stdout=stdout)
        assert exit_code == 0

    asyncio.run(scenario())

    state_response = _parse_jsonl(stdout)[0]
    assert state_response["command"] == "get_state"
    assert "sessionName" not in state_response["data"]
    assert "sessionFile" not in state_response["data"]
    assert state_response["data"]["isStreaming"] is False


def test_rpc_mode_get_state_fills_stable_defaults_for_partial_state() -> None:
    from loushang.harness.host.rpc import run_rpc_host as run_rpc_mode

    class PartialStateSession(FakeSession):
        def __init__(self) -> None:
            super().__init__(session_id="session-a", cwd="/tmp/project")
            self.agent = object()

        def get_state(self):
            return SimpleNamespace(model_selection=None)

        @property
        def auto_compaction_enabled(self) -> None:
            return None

    session = PartialStateSession()
    runtime = FakeRuntime(session)
    stdin = StringIO(json.dumps({"id": "state", "type": "get_state"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        exit_code = await run_rpc_mode(runtime=runtime, stdin=stdin, stdout=stdout)
        assert exit_code == 0

    asyncio.run(scenario())

    state = _parse_jsonl(stdout)[0]["data"]
    assert state["model"] is None
    assert state["thinkingLevel"] == "off"
    assert state["isStreaming"] is False
    assert state["isCompacting"] is False
    assert state["steeringMode"] == "one-at-a-time"
    assert state["followUpMode"] == "one-at-a-time"
    assert state["autoCompactionEnabled"] is False
    assert state["messageCount"] == 0
    assert state["pendingMessageCount"] == 0


def test_rpc_mode_get_state_tolerates_invalid_state_attributes() -> None:
    from loushang.harness.host.rpc import run_rpc_host as run_rpc_mode

    class _Unprintable:
        def __init__(self, label: str) -> None:
            self.label = label

        def __str__(self) -> str:
            raise RuntimeError(f"cannot stringify {self.label}")

    class BrokenSession:
        def __init__(self) -> None:
            self.session_id = _Unprintable("session-id")
            self.session_name = None
            self.session_file = None
            self.agent = SimpleNamespace(steering_mode="unknown", follow_up_mode=None)

        def get_state(self):
            class BrokenState:
                @property
                def steering(self):
                    raise RuntimeError("broken steering")

                @property
                def follow_up(self):
                    raise RuntimeError("broken follow-up")

                @property
                def run(self):
                    raise RuntimeError("broken run")

                @property
                def thinking_level(self):
                    raise RuntimeError("broken thinking level")

                @property
                def is_compacting(self):
                    raise RuntimeError("broken is_compacting")

            return BrokenState()

        def get_session_context(self) -> object:
            raise RuntimeError("broken session context")

        @property
        def auto_compaction_enabled(self):
            raise RuntimeError("broken auto compaction")

        def subscribe(self, _listener):
            def unsubscribe() -> None:
                return None

            return unsubscribe

    session = BrokenSession()
    runtime = FakeRuntime(session)
    stdin = StringIO(json.dumps({"id": "state", "type": "get_state"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        exit_code = await run_rpc_mode(runtime=runtime, stdin=stdin, stdout=stdout)
        assert exit_code == 0

    asyncio.run(scenario())

    state = _parse_jsonl(stdout)[0]["data"]
    assert isinstance(state["sessionId"], str)
    assert "sessionName" not in state
    assert "sessionFile" not in state
    assert state["model"] is None
    assert state["isStreaming"] is False
    assert state["isCompacting"] is False
    assert state["steeringMode"] == "one-at-a-time"
    assert state["followUpMode"] == "one-at-a-time"
    assert state["autoCompactionEnabled"] is False
    assert state["messageCount"] == 0
    assert state["pendingMessageCount"] == 0


def test_rpc_mode_get_state_tolerates_broken_model_selection() -> None:
    from loushang.harness.host.rpc import run_rpc_host as run_rpc_mode

    class BrokenSelectionSession(FakeSession):
        def get_state(self):
            return SimpleNamespace(
                model_selection=object(), run=SimpleNamespace(status="running")
            )

    session = BrokenSelectionSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(json.dumps({"id": "state", "type": "get_state"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        exit_code = await run_rpc_mode(runtime=runtime, stdin=stdin, stdout=stdout)
        assert exit_code == 0

    asyncio.run(scenario())

    assert _parse_jsonl(stdout)[0]["data"]["model"] is None
    assert _parse_jsonl(stdout)[0]["data"]["isStreaming"] is True


def test_rpc_mode_get_state_tolerates_broken_model_projection() -> None:
    from loushang.harness.host.rpc import run_rpc_host as run_rpc_mode

    class BrokenModel:
        @property
        def provider(self):
            raise RuntimeError("broken provider")

        @property
        def id(self):
            return "alpha"

    class BrokenModelSession:
        def __init__(self) -> None:
            self.session_id = "session-a"
            self.agent = SimpleNamespace(state=SimpleNamespace(model=BrokenModel()))
            self.auto_compaction_enabled = None

        def subscribe(self, _listener):
            def unsubscribe() -> None:
                return None

            return unsubscribe

        def get_session_context(self):
            return SimpleNamespace(messages=[])

        def get_state(self):
            return SimpleNamespace(
                model_selection=None, run=SimpleNamespace(status="idle")
            )

    session = BrokenModelSession()
    runtime = FakeRuntime(session)
    stdin = StringIO(json.dumps({"id": "state", "type": "get_state"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        exit_code = await run_rpc_mode(runtime=runtime, stdin=stdin, stdout=stdout)
        assert exit_code == 0

    asyncio.run(scenario())

    state = _parse_jsonl(stdout)[0]["data"]
    assert state["model"] is None
    assert state["sessionId"] == "session-a"


def test_rpc_mode_get_state_model_uses_id_as_name_and_omits_unknown_cost() -> None:
    from loushang.harness.host.rpc import run_rpc_host as run_rpc_mode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    session.model_registry = FakeModelRegistry(
        resolved_models={
            ("faux", "coding", "alpha"): Model(
                id="alpha",
                provider="faux",
                endpoint="coding",
                capabilities=Capabilities(
                    input=("text",),
                    context_window=100_000,
                    max_tokens=4_096,
                    reasoning=False,
                ),
            )
        },
        endpoints={
            ("faux", "coding"): Endpoint(
                id="coding",
                api="openai-completions",
                provider="faux",
                base_url="https://api.faux.test/v1",
            )
        },
    )
    asyncio.run(
        session.set_model(
            ModelSelection(endpoint_id="coding", provider="faux", model_id="alpha")
        )
    )
    runtime = FakeRuntime(session)
    stdin = StringIO(json.dumps({"id": "state", "type": "get_state"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        exit_code = await run_rpc_mode(runtime=runtime, stdin=stdin, stdout=stdout)
        assert exit_code == 0

    asyncio.run(scenario())

    model = _parse_jsonl(stdout)[0]["data"]["model"]
    assert model == {
        "provider": "faux",
        "endpointId": "coding",
        "id": "alpha",
        "name": "alpha",
        "api": "openai-completions",
        "baseUrl": "https://api.faux.test/v1",
        "input": ["text"],
        "contextWindow": 100_000,
        "maxTokens": 4_096,
        "reasoning": False,
    }


def test_rpc_mode_get_state_model_omits_partial_unknown_cost() -> None:
    from loushang.harness.host.rpc import run_rpc_host as run_rpc_mode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    session.model_registry = FakeModelRegistry(
        resolved_models={
            ("openrouter", "anthropic-messages", "auto"): Model(
                id="auto",
                provider="openrouter",
                endpoint="anthropic-messages",
                capabilities=Capabilities(input=("text",), context_window=100_000),
                pricing=Pricing(input=None, output=None, cache_read=0, cache_write=0),
            )
        },
        endpoints={
            ("openrouter", "anthropic-messages"): Endpoint(
                id="anthropic-messages",
                api="anthropic-messages",
                provider="openrouter",
            )
        },
    )
    asyncio.run(
        session.set_model(
            ModelSelection(
                endpoint_id="anthropic-messages",
                provider="openrouter",
                model_id="auto",
            )
        )
    )
    runtime = FakeRuntime(session)
    stdin = StringIO(json.dumps({"id": "state", "type": "get_state"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        exit_code = await run_rpc_mode(runtime=runtime, stdin=stdin, stdout=stdout)
        assert exit_code == 0

    asyncio.run(scenario())

    model = _parse_jsonl(stdout)[0]["data"]["model"]
    assert "cost" not in model


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf")])
def test_rpc_mode_model_cost_omits_invalid_numeric_values(value: float) -> None:
    from loushang.harness.host.rpc.wire import project_model_cost

    cost = project_model_cost(
        SimpleNamespace(input=1.0, output=value, cache_read=0.0, cache_write=0.0)
    )

    assert cost is None


@pytest.mark.parametrize(
    ("command", "payload", "runtime_attr"),
    [
        (
            "new_session",
            {"cwd": "/tmp/project-b", "parentSession": "parent-1"},
            "new_session_calls",
        ),
        ("switch_session", {"sessionId": "session-b"}, "switch_session_calls"),
        ("fork", {"entryId": "entry-42"}, "fork_session_calls"),
    ],
)
def test_rpc_mode_rebinds_runtime_sessions(
    command: str, payload: dict[str, object], runtime_attr: str
) -> None:
    from loushang.harness.host.rpc import run_rpc_host as run_rpc_mode

    current = FakeSession(session_id="session-a", cwd="/tmp/project-a")
    next_session = FakeSession(
        session_id="session-b",
        cwd="/tmp/project-b",
        event_message=_assistant_message("from-b"),
    )
    runtime = FakeRuntime(current)
    runtime.queue_next_session(next_session)
    stdin = StringIO(
        "\n".join(
            [
                json.dumps({"id": "lifecycle", "type": command, **payload}),
                json.dumps({"id": "prompt", "type": "prompt", "message": "hello"}),
            ]
        )
        + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        exit_code = await run_rpc_mode(runtime=runtime, stdin=stdin, stdout=stdout)
        assert exit_code == 0

    asyncio.run(scenario())

    assert next_session.prompt_calls == [("hello", None)]
    assert getattr(runtime, runtime_attr)

    lines = _parse_jsonl(stdout)
    lifecycle = lines[0]
    assert lifecycle["type"] == "response"
    assert lifecycle["command"] == command
    assert lifecycle["data"]["cancelled"] is False
    if command == "fork":
        assert lifecycle["data"]["text"] is None
    else:
        assert lifecycle["data"] == {"cancelled": False}
    assert lines[1] == {
        "id": "prompt",
        "type": "response",
        "command": "prompt",
        "success": True,
    }
    assert lines[2]["type"] == "message_end"


def test_rpc_mode_switch_session_accepts_session_path_alias() -> None:
    from loushang.harness.host.rpc import run_rpc_host as run_rpc_mode

    current = FakeSession(session_id="session-a", cwd="/tmp/project-a")
    next_session = FakeSession(session_id="session-b", cwd="/tmp/project-b")
    runtime = FakeRuntime(current)
    runtime.queue_next_session(next_session)
    stdin = StringIO(
        json.dumps(
            {"id": "switch", "type": "switch_session", "sessionPath": "/tmp/s-b.jsonl"}
        )
        + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        exit_code = await run_rpc_mode(runtime=runtime, stdin=stdin, stdout=stdout)
        assert exit_code == 0

    asyncio.run(scenario())

    assert runtime.switch_session_calls == ["/tmp/s-b.jsonl"]
    assert _parse_jsonl(stdout)[0]["data"] == {"cancelled": False}


def test_rpc_mode_fork_response_includes_selected_user_text() -> None:
    from loushang.harness.host.rpc import run_rpc_host as run_rpc_mode

    current = FakeSession(session_id="session-a", cwd="/tmp/project-a")
    current.session_manager.set_entry(
        "entry-42",
        _message_record("entry-42", _user_message("selected text")),
    )
    next_session = FakeSession(session_id="session-b", cwd="/tmp/project-b")
    runtime = FakeRuntime(current)
    runtime.queue_next_session(next_session)
    stdin = StringIO(
        json.dumps({"id": "fork", "type": "fork", "entryId": "entry-42"}) + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        exit_code = await run_rpc_mode(runtime=runtime, stdin=stdin, stdout=stdout)
        assert exit_code == 0

    asyncio.run(scenario())

    assert _parse_jsonl(stdout)[0]["data"] == {
        "cancelled": False,
        "text": "selected text",
    }
    assert runtime.fork_session_operation_calls == [("entry-42", "before")]


def test_rpc_mode_fork_accepts_at_position() -> None:
    from loushang.harness.host.rpc import run_rpc_host as run_rpc_mode

    current = FakeSession(session_id="session-a", cwd="/tmp/project-a")
    current.session_manager.set_entry(
        "entry-42",
        _message_record("entry-42", _user_message("selected text")),
    )
    next_session = FakeSession(session_id="session-b", cwd="/tmp/project-b")
    runtime = FakeRuntime(current)
    runtime.queue_next_session(next_session)
    stdin = StringIO(
        json.dumps(
            {"id": "fork", "type": "fork", "entryId": "entry-42", "position": "at"}
        )
        + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        exit_code = await run_rpc_mode(runtime=runtime, stdin=stdin, stdout=stdout)
        assert exit_code == 0

    asyncio.run(scenario())

    assert _parse_jsonl(stdout)[0]["data"] == {"cancelled": False, "text": None}
    assert runtime.fork_session_operation_calls == [("entry-42", "at")]


@pytest.mark.parametrize(
    ("command", "payload", "runtime_attr"),
    [
        (
            "new_session",
            {"cwd": "/tmp/project-b", "parentSession": "parent-1"},
            "new_session_calls",
        ),
        ("switch_session", {"sessionPath": "/tmp/s-b.jsonl"}, "switch_session_calls"),
        ("fork", {"entryId": "leaf-1"}, "fork_session_calls"),
        ("clone", {}, "fork_session_calls"),
    ],
)
def test_rpc_mode_lifecycle_commands_do_not_wait_for_active_prompt(
    command: str,
    payload: dict[str, object],
    runtime_attr: str,
) -> None:
    current = FakeSession(session_id="session-a", cwd="/tmp/project-a")
    current._prompt_started = asyncio.Event()
    current._prompt_release = asyncio.Event()
    next_session = FakeSession(session_id="session-b", cwd="/tmp/project-b")
    runtime = FakeRuntime(current)
    runtime.queue_next_session(next_session)

    async def scenario() -> list[dict[str, object]]:
        playback = RpcWirePlayback(runtime=runtime)
        await playback.dispatch({"id": "p1", "type": "prompt", "message": "start"})
        await current._prompt_started.wait()
        await playback.dispatch({"id": "lifecycle", "type": command, **payload})
        await playback.dispatch(
            {"id": "p2", "type": "prompt", "message": "after switch"}
        )
        current._prompt_release.set()
        return list((await playback.finish()).records)

    lines = asyncio.run(scenario())

    assert getattr(runtime, runtime_attr)
    assert next_session.prompt_calls == [("after switch", None)]
    lifecycle_response = next(line for line in lines if line.get("id") == "lifecycle")
    assert lifecycle_response["type"] == "response"
    assert lifecycle_response["command"] == command
    assert lifecycle_response["success"] is True
    assert lifecycle_response["data"]["cancelled"] is False
    assert not any(
        isinstance(line.get("error"), str) and "active prompt" in line["error"]
        for line in lines
        if line.get("type") == "response"
    )


def test_rpc_mode_compact_command_does_not_wait_for_active_prompt() -> None:
    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    session._prompt_started = asyncio.Event()
    session._prompt_release = asyncio.Event()
    runtime = FakeRuntime(session)

    async def scenario() -> list[dict[str, object]]:
        playback = RpcWirePlayback(runtime=runtime)
        await playback.dispatch({"id": "p1", "type": "prompt", "message": "start"})
        await session._prompt_started.wait()
        await playback.dispatch({"id": "compact", "type": "compact"})
        session._prompt_release.set()
        return list((await playback.finish()).records)

    records = asyncio.run(scenario())

    assert session.compact_calls == [None]
    compact_response = next(line for line in records if line.get("id") == "compact")
    assert compact_response["type"] == "response"
    assert compact_response["command"] == "compact"
    assert compact_response["success"] is True


def test_rpc_mode_prompt_streaming_behavior_uses_prompt_pipeline_while_active() -> None:
    image = {"type": "image", "data": "abc123", "mimeType": "image/png"}
    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    session._prompt_started = asyncio.Event()
    session._prompt_release = asyncio.Event()
    runtime = FakeRuntime(session)

    async def scenario() -> list[dict[str, object]]:
        playback = RpcWirePlayback(runtime=runtime)
        await playback.dispatch({"id": "p1", "type": "prompt", "message": "hello"})
        await session._prompt_started.wait()
        await playback.dispatch(
            {
                "id": "p2",
                "type": "prompt",
                "message": "queued",
                "images": [image],
                "streamingBehavior": "followUp",
            }
        )
        session._prompt_release.set()
        return list((await playback.finish()).records)

    records = asyncio.run(scenario())

    assert session.prompt_calls == [("hello", None), ("queued", [image])]
    assert session.prompt_kwargs[1]["source"] == "rpc"
    assert session.prompt_kwargs[1]["streaming_behavior"] == "followUp"
    assert session.follow_up_calls == [("queued", [image])]
    prompt_responses = [
        line
        for line in records
        if line.get("type") == "response" and line.get("command") == "prompt"
    ]
    assert {line.get("id") for line in prompt_responses} == {"p1", "p2"}
    assert all(line["success"] is True for line in prompt_responses)


def test_rpc_mode_prompt_returns_after_preflight_before_prompt_finishes() -> None:
    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    session._prompt_started = asyncio.Event()
    session._prompt_release = asyncio.Event()
    runtime = FakeRuntime(session)

    async def scenario() -> None:
        playback = RpcWirePlayback(runtime=runtime)
        await playback.dispatch({"id": "p1", "type": "prompt", "message": "hello"})
        await session._prompt_started.wait()
        await asyncio.sleep(0)
        assert list(playback.snapshot().records) == [
            {"id": "p1", "type": "response", "command": "prompt", "success": True}
        ]
        session._prompt_release.set()
        await playback.finish()

    asyncio.run(scenario())

    assert session.prompt_calls == [("hello", None)]
    assert session.wait_calls == 1
