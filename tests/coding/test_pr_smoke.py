"""Two offline smoke flows using real sessions, storage, tools and screen IO."""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from io import StringIO

import pytest

from loushang.agent import Agent, synthetic_model_transport
from loushang.agent.types import AgentToolResult
from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import (
    AssistantMessage,
    TextPart,
    ToolCall,
    ToolResultMessage,
    Usage,
)
from loushang.apphost import (
    SessionBindingKeyV1,
    SessionCreateIntentV1,
    SessionCreateRequestV1,
)
from loushang.appserver.protocol import SessionScopeV1
from loushang.coding.appservice_adapter import CodingHostedSessionV1
from loushang.coding.bootstrap import create_services
from loushang.coding.hosted_catalog import (
    CODING_HOSTED_COMPATIBILITY_ID,
    CodingHostedScopeV1,
    CodingHostedSessionCatalogV1,
)
from loushang.coding.hosted_session import CodingRealHostedSessionFactoryV1
from loushang.coding.session import AgentSession
from loushang.coding.session_manager import SessionManager
from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.harness.config.agent import SettingsManager
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.execution import direct_execution
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
from loushang.harnesstui.testing.action_host import CallbackConversationActionHost
from loushang.tui import strip_control_sequences
from tests.coding.tui_support.scenario_binding import run_coding_test_screen

pytestmark = pytest.mark.e2e_smoke


@pytest.fixture(autouse=True)
def _private_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    for name, path in {
        "HOME": home,
        "USERPROFILE": home,
        "LOUSHANG_HOME": tmp_path / "platform",
        "LOUSHANG_RUNTIME_DIR": tmp_path / "runtime",
        "LOUSHANG_TMPDIR": tmp_path / "scratch",
    }.items():
        monkeypatch.setenv(name, str(path))


def _message(content, reason="stop"):
    return AssistantMessage(
        endpoint="anthropic-messages",
        role="assistant",
        content=content,
        api="anthropic-messages",
        provider="faux",
        model="smoke",
        response_id=None,
        usage=Usage(
            input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
        ),
        stop_reason=reason,
        error_message=None,
        timestamp=0.0,
    )


def _model_stream(tool_name, *, expected_tool_text=None):
    @synthetic_model_transport
    async def stream_fn(model, context, options=None):
        last = context.messages[-1]
        if isinstance(last, ToolResultMessage):
            assert not last.is_error
            if expected_tool_text is not None:
                assert expected_tool_text in "".join(part.text for part in last.content)
            message = _message([TextPart(type="text", text="tool result received")])
        elif last.content[0].text == "use tool":
            arguments = {"path": "smoke.txt"} if tool_name == "read" else {}
            message = _message(
                [
                    ToolCall(
                        type="toolCall",
                        id="smoke-tool",
                        name=tool_name,
                        arguments=arguments,
                    )
                ],
                "toolUse",
            )
        else:
            message = _message([TextPart(type="text", text="smoke-reply")])
        stream = AssistantMessageEventStream()
        stream.push({"type": "start", "partial": message})
        stream.push({"type": "done", "reason": message.stop_reason, "message": message})
        return stream

    return stream_fn


async def _open(tmp_path, stream_fn, tools, *, resume=False):
    # Reconstruct both catalog and factory on every open: no in-memory history
    # can make the restore assertion pass without reading the saved transcript.
    scope = CodingHostedScopeV1(SessionScopeV1.CWD, tmp_path / "sessions", tmp_path)
    catalog = CodingHostedSessionCatalogV1((scope,))
    request = SessionCreateRequestV1(
        "coding",
        scope.fingerprint,
        "b" * 32,
        requested_continuity_id="smoke-continuity",
        requested_scope=scope.discovery_scope,
    )
    candidate = (
        await catalog.find_created_candidate(request)
        if resume
        else await catalog.create_candidate(
            SessionCreateIntentV1(
                request,
                CODING_HOSTED_COMPATIBILITY_ID,
            )
        )
    )
    assert candidate is not None
    claimed = await candidate.claim()
    identity = claimed.opaque_binding.record.identity
    factory = CodingRealHostedSessionFactoryV1(
        services_factory=lambda cwd: create_services(
            settings_manager=SettingsManager(
                global_settings_path=tmp_path / "settings.json",
                project_settings_path=cwd / ".loushang" / "settings.json",
            )
        ),
        model=Model(
            id="smoke",
            name="Smoke",
            provider="faux",
            endpoint="anthropic-messages",
            capabilities=Capabilities(
                input=("text",), context_window=128000, max_tokens=4096
            ),
        ),
        stream_fn=stream_fn,
        tools=tools,
    )
    try:
        binding = await factory.create_session(
            binding_key=SessionBindingKeyV1(
                identity.product_id,
                identity.continuity_id,
                identity.session_id,
            ),
            opaque_session_binding=claimed.opaque_binding,
        )
    finally:
        await claimed.close()
        await candidate.close()
    return CodingHostedSessionV1(binding), factory, catalog, binding


def test_real_session_tool_persistence_resume_and_close(tmp_path, record_property):
    async def scenario():
        payload = "真实工具 smoke payload"
        (tmp_path / "smoke.txt").write_text(payload, encoding="utf-8")
        stream_fn = _model_stream("read", expected_tool_text=payload)
        tools = None  # The real product publishes its reserved read tool.
        first, factory, catalog, binding = await _open(tmp_path, stream_fn, tools)
        try:
            await first.start_turn("use tool")
            messages = binding.control.get_session_context().messages
            (result,) = [
                item for item in messages if isinstance(item, ToolResultMessage)
            ]
            assert result.tool_call_id == "smoke-tool" and not result.is_error
            assert payload in "".join(part.text for part in result.content)
            before = await first.snapshot()
            assert before.records[-1].text == "tool result received"
            assert not before.running
        finally:
            await first.close()
            await factory.close()
            await catalog.close()
        assert first.closed
        (transcript,) = (tmp_path / "sessions").glob("*.jsonl")
        assert payload in json.dumps(
            [
                json.loads(line)
                for line in transcript.read_text(encoding="utf-8").splitlines()
            ],
            ensure_ascii=False,
        )
        resumed, factory, catalog, binding = await _open(
            tmp_path,
            stream_fn,
            tools,
            resume=True,
        )
        try:
            restored = await resumed.snapshot()
            assert resumed.identity.session_id == first.identity.session_id
            assert restored.records == before.records
            restored_messages = binding.control.get_session_context().messages
            assert len(restored_messages) == len(messages)
            for restored_message, original in zip(
                restored_messages, messages, strict=True
            ):
                assert restored_message.role == original.role
                assert restored_message.content == original.content
            (restored_result,) = [
                item
                for item in restored_messages
                if isinstance(item, ToolResultMessage)
            ]
            assert restored_result.tool_call_id == result.tool_call_id
            assert restored_result.is_error == result.is_error
            assert restored_result.details == result.details
            await resumed.start_turn("after resume")
            after = await resumed.snapshot()
            assert after.records[: len(before.records)] == before.records
            assert after.records[-2].text == "after resume"
            assert after.records[-1].text == "smoke-reply"
            assert not after.running
        finally:
            await resumed.close()
            await factory.close()
            await catalog.close()
        assert resumed.closed
        record_property(
            "smoke_stages", "create,tool-result,persist,close,reload,resume-turn,close"
        )

    async def bounded():
        async with asyncio.timeout(60) as deadline:
            await scenario()
        assert not deadline.expired(), "smoke swallowed its deadline cancellation"

    asyncio.run(bounded())


def test_terminal_cancel_tool_then_message_and_exit(tmp_path, record_property):
    async def scenario():
        started, settled, next_rendered = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )

        async def blocking(tool_call_id, params, signal=None, on_update=None):
            started.set()
            try:
                await asyncio.Event().wait()
                return AgentToolResult(content=[])
            finally:
                settled.set()

        tools = [
            ToolDefinition(
                name="blocking",
                description="Controlled cancellation probe",
                parameters={"type": "object", "properties": {}},
                label="Blocking",
                execution=direct_execution(blocking),
                execution_mode="sequential",
            )
        ]
        registry = WorkspaceToolRegistry()
        registry.register_tool(tools[0])
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(tmp_path), persist=True
        )
        session = AgentSession(
            agent=Agent(
                stream_fn=_model_stream("blocking"),
                initial_state={
                    "model": Model(
                        id="smoke",
                        name="Smoke",
                        provider="faux",
                        endpoint="anthropic-messages",
                        capabilities=Capabilities(
                            input=("text",), context_window=128000, max_tokens=4096
                        ),
                    )
                },
                tool_execution="sequential",
            ),
            session_manager=manager,
            tool_registry=registry,
            active_tool_names=["blocking"],
        )
        screen_idle = asyncio.Event()

        class SmokeScreen(ScreenCodingTuiApp):
            def complete_run(self, *, elapsed_seconds=None):
                super().complete_run(elapsed_seconds=elapsed_seconds)
                print("smoke screen run completed", flush=True)
                if next_rendered.is_set():
                    screen_idle.set()

        app = SmokeScreen(
            model_label="offline smoke",
            cwd=str(tmp_path),
            branch="smoke",
            session_label="smoke-cancel",
        )
        stdout = StringIO()
        terminal_events = []

        @contextmanager
        def terminal_mode(_stdin, _stdout):
            terminal_events.append("enter")
            try:
                yield
            finally:
                terminal_events.append("exit")

        async def submit(text):
            print(f"smoke submit: {text}", flush=True)
            await session.prompt(text)
            print(f"smoke prompt settled: {text}", flush=True)
            if text != "use tool":
                messages = session.get_session_context().messages
                app.begin_assistant()
                app.append_assistant_chunk(messages[-1].content[0].text)
                app.end_assistant(messages[-1].content[0].text)
                next_rendered.set()

        def abort():
            session.abort()

        step = 0

        async def read_input(_stdin):
            nonlocal step
            # Render ticks cancel pending reads. Advance only after a chunk
            # has been produced, so cancellation cannot consume Escape/Enter.
            if step == 0:
                chunk = "use tool\r"
            elif step == 1:
                await started.wait()
                chunk = "\x1b"
            elif step == 2:
                await settled.wait()
                chunk = "after cancel\r"
            elif step == 3:
                await next_rendered.wait()
                await screen_idle.wait()
                chunk = "/quit\r"
            else:
                chunk = ""
            step += 1
            print(f"smoke input stage: {step}", flush=True)
            return chunk

        exits = []

        def should_exit(text):
            print(f"smoke routed input: {text!r}", flush=True)
            if text == "/quit":
                exits.append(text)
                return True
            return False

        try:
            result = await run_coding_test_screen(
                app=app,
                stdin=StringIO(),
                stdout=stdout,
                action_host=CallbackConversationActionHost(submit=submit, abort=abort),
                should_exit=should_exit,
                terminal_mode_factory=terminal_mode,
                input_chunk_reader=read_input,
            )
            assert result == 0
            assert exits == ["/quit"], repr(
                strip_control_sequences(stdout.getvalue())[-1500:]
            )
            assert started.is_set() and settled.is_set() and next_rendered.is_set()
            messages = session.get_session_context().messages
            (tool_result,) = [
                item for item in messages if isinstance(item, ToolResultMessage)
            ]
            assert tool_result.details == {"code": "tool_call_aborted"}
            assert "smoke-reply" in strip_control_sequences(stdout.getvalue())
            assert terminal_events == ["enter", "exit"]
        finally:
            await session.dispose()
        assert not session.agent.is_streaming
        record_property(
            "smoke_stages",
            "terminal-enter,tool-start,cancel,tool-settle,next-reply,terminal-exit,close",
        )

    async def bounded():
        async with asyncio.timeout(60) as deadline:
            await scenario()
        assert not deadline.expired(), "smoke swallowed its deadline cancellation"

    asyncio.run(bounded())
