from __future__ import annotations

import asyncio
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.agent import Agent, synthetic_model_transport
from loushang.agent.types import AgentToolResult
from loushang.ai.errors import AIProviderError
from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, TextPart, ToolCall, Usage
from loushang.appserver.protocol import (
    AckV1,
    AppErrorCodeV1,
    AppServiceError,
    SessionEventKindV1,
    SessionIdentityV1,
    SessionScopeV1,
)
from loushang.appservice.execution_contract import (
    ExecutionRequestV1,
    ExecutionStatusV1,
    InterruptModeV1,
)
from loushang.coding.appservice_adapter import CodingHostedSessionV1
from loushang.coding.hosted_execution import CodingHostedExecutionSessionV1
from loushang.coding.hosted_session import CodingRealHostedSessionV1
from loushang.coding.session.agent_session import AgentSession
from loushang.coding.session_manager import SessionManager
from loushang.harness.approval import DenyApprovalResolver, InteractiveApprovalResolver
from loushang.harness.events.session import ToolPolicyAuditEvent
from loushang.harness.extensions.agent import (
    ExtensionRunner,
    LoadedExtension,
    RegisteredCommand,
)
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.execution import direct_execution
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry


@pytest.fixture(autouse=True)
def _private_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    for key, path in {
        "HOME": home,
        "USERPROFILE": home,
        "LOUSHANG_HOME": tmp_path / "platform",
        "LOUSHANG_RUNTIME_DIR": tmp_path / "runtime",
        "LOUSHANG_TMPDIR": tmp_path / "scratch",
    }.items():
        monkeypatch.setenv(key, str(path))


def _message(reason="stop"):
    return AssistantMessage(
        role="assistant",
        content=[TextPart(type="text", text="response")],
        api="anthropic-messages",
        endpoint="anthropic-messages",
        provider="faux",
        model="faux",
        response_id=None,
        usage=Usage(
            input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
        ),
        stop_reason=reason,
        error_message="provider failed" if reason == "error" else None,
        timestamp=0,
    )


@synthetic_model_transport
async def _stream(model, context, options=None):
    stream = AssistantMessageEventStream()
    message = _message()
    stream.push({"type": "start", "partial": message})
    stream.push({"type": "done", "reason": "stop", "message": message})
    return stream


async def _binding(
    tmp_path: Path,
    *,
    command=None,
    stream_fn=_stream,
    tools=(),
    persist=False,
    manager=None,
):
    runner = None
    if command is not None:
        runner = ExtensionRunner(
            [
                LoadedExtension(
                    name="execution-test",
                    source_path=tmp_path / "extension.py",
                    commands={"work": RegisteredCommand(name="work", handler=command)},
                )
            ]
        )
    approval = InteractiveApprovalResolver(fallback=DenyApprovalResolver())
    registry = WorkspaceToolRegistry()
    for tool in tools:
        registry.register_tool(tool)
    session = AgentSession(
        agent=Agent(
            initial_state={
                "model": Model(
                    id="faux",
                    name="Faux",
                    provider="faux",
                    endpoint="anthropic-messages",
                    capabilities=Capabilities(
                        input=("text",), context_window=128000, max_tokens=4096
                    ),
                )
            },
            stream_fn=stream_fn,
        ),
        session_manager=manager
        or await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(tmp_path),
            persist=persist,
        ),
        extension_runner=runner,
        approval_resolver=approval,
        tool_registry=registry,
        active_tool_names=[tool.name for tool in tools],
    )
    session.set_auto_retry_enabled(False)
    session.set_auto_compaction_enabled(False)
    identity = SessionIdentityV1(
        product_id="coding",
        continuity_id="continuity",
        session_id=session.session_id,
        scope=SessionScopeV1.CWD,
        scope_fingerprint="c" * 64,
    )
    return CodingRealHostedSessionV1(session, identity, approval), session


def _run(scenario):
    asyncio.run(asyncio.wait_for(scenario, 20))


def test_real_command_is_accepted_before_entry_and_succeeds_without_agent(tmp_path):
    async def scenario():
        calls = []

        async def command(args, context):
            calls.append(args)

        binding, session = await _binding(tmp_path, command=command)
        hosted = CodingHostedExecutionSessionV1(binding)
        try:
            hosted.start_execution(ExecutionRequestV1("A", "/work hello"))
            assert calls == []
            assert hosted.execution_state.status is ExecutionStatusV1.ACCEPTED
            assert (await hosted.snapshot_execution()).observation.execution_id is None
            result = await hosted.wait_execution("A")
            assert calls == ["hello"]
            assert session.messages == []
            assert result.status is ExecutionStatusV1.SUCCEEDED
            snapshot = await hosted.snapshot_execution()
            assert snapshot.observation.execution_id == "A"
            assert snapshot.observation.status is ExecutionStatusV1.SUCCEEDED
            assert not snapshot.source.running
        finally:
            await hosted.close()

    _run(scenario())


def test_real_execution_service_closes_apphost_lease_after_whole_execution_settlement(tmp_path):
    from loushang.apphost import SessionBindingKeyV1
    from loushang.appserver.protocol import (
        MuxAttachV1,
        MuxCreateV1,
        MuxMemberCloseV1,
        MuxMemberOpenV1,
        MuxSelectorV1,
        SessionOpenSpecV1,
        SessionSnapshotRequestV1,
    )
    from loushang.appservice.client_scope import ScopedAppServiceV1
    from loushang.appservice.runtime import AppServiceV1
    from loushang.coding.hosted_application import _LeasedCodingHostedBinding
    from loushang.coding.hosted_execution import create_coding_execution_service_binding

    async def scenario():
        entered, cleanup_entered, cleanup_release = (asyncio.Event() for _ in range(3))
        events = []

        async def command(args, context):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleanup_entered.set()
                await cleanup_release.wait()
                events.append("execution-cleaned")

        binding, session = await _binding(tmp_path, command=command)
        identity = binding.identity

        class Lease:
            binding_key = SessionBindingKeyV1(identity.product_id, identity.continuity_id, identity.session_id)

            async def close(self):
                events.append("lease-closed")

        class Runtime:
            async def close_session(self, key):
                assert key == Lease.binding_key
                events.append("runtime-close")
                await binding.close()

        leased = _LeasedCodingHostedBinding(runtime=Runtime(), lease=Lease(), binding=binding)
        hosted = CodingHostedExecutionSessionV1(binding, owner=leased)

        class Resolver:
            async def open_session(self, request):
                return hosted

        service = AppServiceV1(
            product_id="coding", resolver=Resolver(),
            execution=create_coding_execution_service_binding("application", service_instance_id="instance"),
        )
        owner = ScopedAppServiceV1(service)
        scope = owner.open_client_scope()
        try:
            mux = await scope.create_mux(MuxCreateV1("work"))
            selector = MuxSelectorV1(mux_space_id=mux.mux_space_id)
            await scope.attach_mux(MuxAttachV1(selector))
            mux = await scope.open_member(MuxMemberOpenV1(selector, SessionOpenSpecV1(
                identity.product_id, identity.continuity_id, identity.scope,
                identity.scope_fingerprint, "real", identity.session_id,
            )))
            attachment = await scope.attach_mux(MuxAttachV1(selector))
            control = SessionSnapshotRequestV1(attachment.attachment_id, attachment.controller_generation, mux.members[0].member_id)
            record = await scope.execution_client.submit_execution(control, "instance", "submission", "/work silent")
            await entered.wait()
            running = await scope.execution_client.get_execution(control, "instance", record.state.execution_id)
            assert running.state.status is ExecutionStatusV1.RUNNING
            assert session.messages == []
            closing = asyncio.create_task(scope.close_member(MuxMemberCloseV1(selector, control.member_id)))
            await cleanup_entered.wait()
            assert events == [] and not closing.done()
            assert service._execution_registry.active_count == 1
            cleanup_release.set()
            await closing
            assert events == ["execution-cleaned", "lease-closed", "runtime-close"]
            assert service._execution_registry.get(identity, record.state.execution_id).state.status is ExecutionStatusV1.INTERRUPTED
        finally:
            cleanup_release.set()
            await service.close()

    _run(scenario())


def test_real_command_failure_has_explicit_outcome_and_retains_legacy_ack(tmp_path):
    async def scenario():
        async def command(args, context):
            raise ValueError("private command error")

        binding, _ = await _binding(tmp_path, command=command)
        hosted = CodingHostedExecutionSessionV1(binding)
        try:
            hosted.start_execution(ExecutionRequestV1("A", "/work"))
            result = await hosted.wait_execution("A")
            assert result.status is ExecutionStatusV1.FAILED
            assert result.error_code == "extension_command_failed"
            assert type(result.legacy_result) is AckV1
            assert await hosted.start_turn("/work") is None
        finally:
            await hosted.close()
        binding, _ = await _binding(tmp_path, command=command)
        legacy = CodingHostedSessionV1(binding)
        try:
            assert await legacy.start_turn("/work") is None
        finally:
            await legacy.close()

    _run(scenario())


def test_real_provider_failure_is_not_successful_coroutine_return(tmp_path):
    @synthetic_model_transport
    async def failing_stream(model, context, options=None):
        stream = AssistantMessageEventStream()
        stream.push({"type": "error", "reason": "error", "error": _message("error")})
        return stream

    async def scenario():
        binding, _ = await _binding(tmp_path, stream_fn=failing_stream)
        hosted = CodingHostedExecutionSessionV1(binding)
        try:
            hosted.start_execution(ExecutionRequestV1("A", "hello"))
            result = await hosted.wait_execution("A")
            assert result.status is ExecutionStatusV1.FAILED
            assert result.error_code == "assistant_response_error"
            assert (
                await hosted.snapshot_execution()
            ).observation.status is result.status
        finally:
            await hosted.close()

    _run(scenario())


def test_whole_command_interrupt_waits_for_cleanup_and_fences_stale_ids(tmp_path):
    async def scenario():
        entered, cleanup, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def command(args, context):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleanup.set()
                await release.wait()

        binding, _ = await _binding(tmp_path, command=command)
        hosted = CodingHostedExecutionSessionV1(binding)
        try:
            hosted.start_execution(ExecutionRequestV1("A", "/work"))
            await entered.wait()
            assert not hosted.interrupt_execution("A", InterruptModeV1.LEGACY_TURN_ONLY)
            assert not hosted.interrupt_turn()
            assert hosted.interrupt_execution("A", InterruptModeV1.WHOLE_EXECUTION)
            await cleanup.wait()
            assert hosted.interrupt_execution("A", InterruptModeV1.WHOLE_EXECUTION)
            with pytest.raises(AppServiceError) as busy:
                hosted.start_execution(ExecutionRequestV1("B", "next"))
            assert busy.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
            assert (await hosted.snapshot_execution()).source.running
            release.set()
            assert (
                await hosted.wait_execution("A")
            ).status is ExecutionStatusV1.INTERRUPTED
            hosted.start_execution(ExecutionRequestV1("B", "next"))
            assert not hosted.interrupt_execution("A", InterruptModeV1.WHOLE_EXECUTION)
            assert (
                await hosted.wait_execution("B")
            ).status is ExecutionStatusV1.SUCCEEDED
        finally:
            release.set()
            await hosted.close()

    _run(scenario())


def test_real_settlement_failure_retains_slot_and_retry_does_not_replay(
    tmp_path, monkeypatch
):
    async def scenario():
        calls = []

        async def command(args, context):
            calls.append(args)

        binding, session = await _binding(tmp_path, command=command)
        settle = session.settle_execution
        attempts = 0

        async def fail_once(*, interrupted=False):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("retained cleanup debt")
            await settle(interrupted=interrupted)

        monkeypatch.setattr(session, "settle_execution", fail_once)
        hosted = CodingHostedExecutionSessionV1(binding)
        try:
            hosted.start_execution(ExecutionRequestV1("A", "/work once"))
            with pytest.raises(AppServiceError) as failed:
                await hosted.wait_execution("A")
            assert failed.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
            with pytest.raises(AppServiceError):
                hosted.start_execution(ExecutionRequestV1("B", "/work twice"))
            assert (await hosted.snapshot_execution()).source.running
            await hosted.retry_execution_settlement("A")
            assert (
                await hosted.wait_execution("A")
            ).status is ExecutionStatusV1.SUCCEEDED
            assert calls == ["once"]
            assert attempts == 2
        finally:
            await hosted.close()

    _run(scenario())


def test_preentry_interrupt_keeps_previous_source_and_skips_product(
    tmp_path, monkeypatch
):
    async def scenario():
        binding, session = await _binding(tmp_path)
        hosted = CodingHostedExecutionSessionV1(binding)
        try:
            hosted.start_execution(ExecutionRequestV1("A", "first"))
            await hosted.wait_execution("A")
            before = await hosted.snapshot_execution()

            async def forbidden():
                pytest.fail("pre-entry interrupt must skip Product preparation")

            monkeypatch.setattr(session, "prepare_model_call_runtime", forbidden)
            hosted.start_execution(ExecutionRequestV1("B", "second"))
            assert (await hosted.snapshot_execution()) == before
            assert hosted.interrupt_execution("B", InterruptModeV1.WHOLE_EXECUTION)
            assert (
                await hosted.wait_execution("B")
            ).status is ExecutionStatusV1.INTERRUPTED
            assert (await hosted.snapshot_execution()) == before
        finally:
            await hosted.close()

    _run(scenario())


@pytest.mark.parametrize("mode", list(InterruptModeV1))
def test_real_model_interrupt_and_legacy_scope(tmp_path, mode):
    async def scenario():
        entered, cancelled = asyncio.Event(), asyncio.Event()

        @synthetic_model_transport
        async def blocked_stream(model, context, options=None):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        binding, session = await _binding(tmp_path, stream_fn=blocked_stream)
        hosted = CodingHostedExecutionSessionV1(binding)
        try:
            hosted.start_execution(ExecutionRequestV1("A", "hello"))
            await entered.wait()
            assert hosted.interrupt_execution("A", mode)
            result = await hosted.wait_execution("A")
            assert cancelled.is_set()
            assert result.status is ExecutionStatusV1.INTERRUPTED
            assert not session.is_streaming
            assert hosted.execution_state.interrupt_requested == (
                mode is InterruptModeV1.WHOLE_EXECUTION
            )
        finally:
            await hosted.close()

    _run(scenario())


def test_cancelled_waiter_leaves_real_command_owned(tmp_path):
    async def scenario():
        entered, release, joined = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def command(args, context):
            entered.set()
            await release.wait()

        binding, _ = await _binding(tmp_path, command=command)
        hosted = CodingHostedExecutionSessionV1(binding)

        async def wait():
            joined.set()
            return await hosted.wait_execution("A")

        try:
            hosted.start_execution(ExecutionRequestV1("A", "/work"))
            await entered.wait()
            waiter = asyncio.create_task(wait())
            await joined.wait()
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            assert hosted.execution_state.status is ExecutionStatusV1.RUNNING
            assert not hosted.execution_state.interrupt_requested
            release.set()
            assert (
                await hosted.wait_execution("A")
            ).status is ExecutionStatusV1.SUCCEEDED
        finally:
            release.set()
            await hosted.close()

    _run(scenario())


def test_cancelled_close_keeps_owner_until_command_cleanup_finishes(
    tmp_path, monkeypatch
):
    async def scenario():
        entered, cleanup, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        disposed = False

        async def command(args, context):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleanup.set()
                await release.wait()

        binding, session = await _binding(tmp_path, command=command)
        dispose = session.dispose

        async def observed_dispose(*args, **kwargs):
            nonlocal disposed
            assert release.is_set()
            await dispose(*args, **kwargs)
            disposed = True

        monkeypatch.setattr(session, "dispose", observed_dispose)
        hosted = CodingHostedExecutionSessionV1(binding)
        hosted.start_execution(ExecutionRequestV1("A", "/work"))
        await entered.wait()
        close = asyncio.create_task(hosted.close())
        try:
            await cleanup.wait()
            close.cancel()
            with pytest.raises(asyncio.CancelledError):
                await close
            assert not disposed
            with pytest.raises(RuntimeError, match="closed"):
                hosted.start_execution(ExecutionRequestV1("B", "next"))
            with pytest.raises(RuntimeError, match="closed"):
                hosted.follow_up_turn("next")
        finally:
            release.set()
            await hosted.close()
        assert disposed
        assert (
            await hosted.wait_execution("A")
        ).status is ExecutionStatusV1.INTERRUPTED

    _run(scenario())


def test_success_wins_late_interrupt_during_real_settlement(tmp_path, monkeypatch):
    async def scenario():
        cleanup, release = asyncio.Event(), asyncio.Event()
        binding, session = await _binding(tmp_path)
        settle = session.settle_execution

        async def held_settle(*, interrupted=False):
            cleanup.set()
            await release.wait()
            await settle(interrupted=interrupted)

        monkeypatch.setattr(session, "settle_execution", held_settle)
        hosted = CodingHostedExecutionSessionV1(binding)
        try:
            hosted.start_execution(ExecutionRequestV1("A", "hello"))
            await cleanup.wait()
            assert hosted.interrupt_execution("A", InterruptModeV1.WHOLE_EXECUTION)
            assert (await hosted.snapshot_execution()).source.running
            release.set()
            assert (
                await hosted.wait_execution("A")
            ).status is ExecutionStatusV1.SUCCEEDED
        finally:
            release.set()
            await hosted.close()

    _run(scenario())


def test_real_stream_snapshot_has_execution_and_replaces_bounded_draft(tmp_path):
    async def scenario():
        delivered = asyncio.Event()
        stream = AssistantMessageEventStream()

        @synthetic_model_transport
        async def controlled_stream(model, context, options=None):
            return stream

        binding, _ = await _binding(tmp_path, stream_fn=controlled_stream)
        hosted = CodingHostedExecutionSessionV1(binding)
        events = []

        def observe(event):
            events.append(event)
            if event.source.kind is SessionEventKindV1.ASSISTANT_DELTA:
                delivered.set()

        hosted.subscribe_execution_content(observe)
        try:
            hosted.start_execution(ExecutionRequestV1("A", "hello"))
            message = _message()
            stream.push({"type": "start", "partial": message})
            stream.push(
                {
                    "type": "text_delta",
                    "content_index": 0,
                    "delta": "x" * 20_000,
                    "partial": message,
                }
            )
            await delivered.wait()
            snapshot = await hosted.snapshot_execution()
            assert snapshot.observation.execution_id == "A"
            assert len(snapshot.draft) <= 16_384
            assert snapshot.truncated
            assert snapshot.source.cursor == events[-1].source.cursor
            stream.push({"type": "done", "reason": "stop", "message": message})
            await hosted.wait_execution("A")
            final = await hosted.snapshot_execution()
            assert final.draft == ""
            assert [record.text for record in final.source.records] == [
                "hello",
                "response",
            ]
            assert all(event.execution_id == "A" for event in events)
            assert final.observation.final_cursor == final.source.cursor
        finally:
            await stream.aclose()
            await hosted.close()

    _run(scenario())


def test_full_interrupt_cannot_resume_model_after_preparation_swallows_cancel(
    tmp_path, monkeypatch
):
    async def scenario():
        entered = asyncio.Event()
        binding, session = await _binding(tmp_path)
        prepare = session.prepare_model_call_runtime

        async def held_prepare():
            await prepare()
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                # A preparation owner can finish rollback and consume cancellation.
                return

        monkeypatch.setattr(session, "prepare_model_call_runtime", held_prepare)
        hosted = CodingHostedExecutionSessionV1(binding)
        try:
            hosted.start_execution(ExecutionRequestV1("A", "must not reach model"))
            await entered.wait()
            assert hosted.interrupt_execution("A", InterruptModeV1.WHOLE_EXECUTION)
            assert (
                await hosted.wait_execution("A")
            ).status is ExecutionStatusV1.INTERRUPTED
            assert session.messages == []
        finally:
            await hosted.close()

    _run(scenario())


@pytest.mark.parametrize("interrupt", [False, True])
def test_automatic_retry_stays_in_same_execution_until_second_run_settles(
    tmp_path, monkeypatch, interrupt
):
    async def scenario():
        retried, release = asyncio.Event(), asyncio.Event()
        calls = 0

        async def immediate_retry(delay, signal):
            return None

        monkeypatch.setattr(
            "loushang.coding.session.agent_session.sleep_for_retry", immediate_retry
        )

        @synthetic_model_transport
        async def retrying_stream(model, context, options=None):
            nonlocal calls
            calls += 1
            stream = AssistantMessageEventStream()
            if calls == 1:
                message = replace(_message("error"), error_message="overloaded")
                stream.push(
                    {
                        "type": "error",
                        "reason": "error",
                        "error": message,
                        "error_info": AIProviderError(
                            "overloaded", retryable=True
                        ).info.to_dict(),
                    }
                )
            else:
                retried.set()
                await release.wait()
                stream.push({"type": "done", "reason": "stop", "message": _message()})
            return stream

        binding, session = await _binding(tmp_path, stream_fn=retrying_stream)
        session.set_auto_retry_enabled(True)
        hosted = CodingHostedExecutionSessionV1(binding)
        events = []
        hosted.subscribe_execution_content(events.append)
        try:
            hosted.start_execution(ExecutionRequestV1("A", "hello"))
            await retried.wait()
            assert hosted.execution_state.status is ExecutionStatusV1.RUNNING
            assert (await hosted.snapshot_execution()).observation.execution_id == "A"
            if interrupt:
                assert hosted.interrupt_execution("A", InterruptModeV1.WHOLE_EXECUTION)
            else:
                release.set()
            outcome = await hosted.wait_execution("A")
            assert outcome.status is (
                ExecutionStatusV1.INTERRUPTED
                if interrupt
                else ExecutionStatusV1.SUCCEEDED
            )
            assert calls == 2
            assert not session.is_streaming
            assert not session.is_retrying
            assert all(event.execution_id == "A" for event in events)
        finally:
            release.set()
            await hosted.close()

    _run(scenario())


def test_real_tool_thread_settles_before_slot_release_and_transcript_reopens(tmp_path):
    async def scenario():
        entered, cleanup = asyncio.Event(), asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        artifact = tmp_path / "tool-output.txt"

        def worker():
            loop.call_soon_threadsafe(entered.set)
            release.wait()
            artifact.write_text("completed effect", encoding="utf-8")

        async def tool_call(tool_call_id, params, signal=None, on_update=None):
            task = asyncio.create_task(asyncio.to_thread(worker))
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cleanup.set()
                # Real tool owners must join effects which outlive Task cancellation.
                await asyncio.shield(task)
                raise
            return AgentToolResult(content=[TextPart(type="text", text="written")])

        tool = ToolDefinition(
            name="owned_write",
            description="Write a private test artifact",
            label="Write",
            parameters={"type": "object", "properties": {}},
            execution=direct_execution(tool_call),
            execution_mode="sequential",
        )
        calls = 0

        @synthetic_model_transport
        async def tool_stream(model, context, options=None):
            nonlocal calls
            calls += 1
            message = _message()
            if calls == 1:
                message = replace(
                    message,
                    content=[
                        ToolCall(
                            type="toolCall",
                            id="call-1",
                            name="owned_write",
                            arguments={},
                        )
                    ],
                    stop_reason="toolUse",
                )
            stream = AssistantMessageEventStream()
            stream.push(
                {"type": "done", "reason": message.stop_reason, "message": message}
            )
            return stream

        binding, session = await _binding(
            tmp_path, tools=[tool], stream_fn=tool_stream, persist=True
        )
        hosted = CodingHostedExecutionSessionV1(binding)
        try:
            hosted.start_execution(ExecutionRequestV1("A", "write"))
            await entered.wait()
            assert hosted.interrupt_execution("A", InterruptModeV1.WHOLE_EXECUTION)
            await cleanup.wait()
            assert not artifact.exists()
            assert hosted.execution_state.status is ExecutionStatusV1.RUNNING
            with pytest.raises(AppServiceError):
                hosted.start_execution(ExecutionRequestV1("B", "next"))
            release.set()
            assert (
                await hosted.wait_execution("A")
            ).status is ExecutionStatusV1.INTERRUPTED
            assert artifact.read_text(encoding="utf-8") == "completed effect"
            hosted.start_execution(ExecutionRequestV1("B", "next"))
            assert (
                await hosted.wait_execution("B")
            ).status is ExecutionStatusV1.SUCCEEDED
            saved = await hosted.snapshot_execution()
            path = session.session_manager.session_file
            assert path is not None
        finally:
            release.set()
            await hosted.close()

        manager = await SessionManager.load(path, persist=True)
        reopened, _ = await _binding(tmp_path, manager=manager)
        resumed = CodingHostedExecutionSessionV1(reopened)
        try:
            snapshot = await resumed.snapshot_execution()
            assert snapshot.source.identity == saved.source.identity
            assert snapshot.source.records == saved.source.records
            assert snapshot.source.cursor == 0
            assert snapshot.observation.execution_id is None
            resumed.start_execution(ExecutionRequestV1("C", "after resume"))
            assert (
                await resumed.wait_execution("C")
            ).status is ExecutionStatusV1.SUCCEEDED
        finally:
            await resumed.close()

    _run(scenario())


def test_failed_preparation_retains_real_runtime_cleanup_and_retires_binding(
    tmp_path, monkeypatch
):
    async def scenario():
        binding, session = await _binding(tmp_path)
        dispose_profile = session._dispose_session_runtime_profile
        attempts = 0

        async def fail_prepare():
            raise RuntimeError("preparation failed before publication")

        async def fail_cleanup_once():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("staged owner retirement failed")
            await dispose_profile()

        monkeypatch.setattr(session, "prepare_model_call_runtime", fail_prepare)
        monkeypatch.setattr(
            session, "_dispose_session_runtime_profile", fail_cleanup_once
        )
        hosted = CodingHostedExecutionSessionV1(binding)
        try:
            hosted.start_execution(ExecutionRequestV1("A", "hello"))
            with pytest.raises(AppServiceError) as failure:
                await hosted.wait_execution("A")
            assert failure.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
            assert hosted.execution_state.status is ExecutionStatusV1.RUNNING
            await hosted.retry_execution_settlement("A")
            assert attempts == 2
            assert (await hosted.wait_execution("A")).status is ExecutionStatusV1.FAILED
            with pytest.raises(AppServiceError) as unavailable:
                hosted.start_execution(ExecutionRequestV1("B", "no replay"))
            assert unavailable.value.code is AppErrorCodeV1.SESSION_UNAVAILABLE
            assert session.messages == []
        finally:
            await hosted.close()

    _run(scenario())


def test_swallowed_compaction_cancel_cannot_enter_before_agent_start(
    tmp_path, monkeypatch
):
    async def scenario():
        binding, session = await _binding(tmp_path)
        controller = session.runtime.prompt_controller
        before_start = type(controller)._before_start
        entered = asyncio.Event()
        phases = []

        async def compact():
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return None

        async def observe_before_start(self, turn_input, timing=None):
            phases.append("before_agent_start")
            return await before_start(self, turn_input)

        monkeypatch.setattr(controller, "compact_before_prompt_async", compact)
        monkeypatch.setattr(type(controller), "_before_start", observe_before_start)
        hosted = CodingHostedExecutionSessionV1(binding)
        try:
            hosted.start_execution(ExecutionRequestV1("A", "hello"))
            await entered.wait()
            hosted.interrupt_execution("A", InterruptModeV1.WHOLE_EXECUTION)
            assert (
                await hosted.wait_execution("A")
            ).status is ExecutionStatusV1.INTERRUPTED
            assert phases == []
            assert session.messages == []
        finally:
            await hosted.close()

    _run(scenario())


def test_interrupt_during_legacy_event_delivery_joins_projection_cleanup(tmp_path):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        binding, session = await _binding(tmp_path)
        hosted = CodingHostedExecutionSessionV1(binding)

        async def listener(event):
            if event.kind is SessionEventKindV1.TURN_STARTED:
                entered.set()
                await release.wait()

        hosted.subscribe(listener)
        try:
            hosted.start_execution(ExecutionRequestV1("A", "hello"))
            await entered.wait()
            hosted.interrupt_execution("A", InterruptModeV1.WHOLE_EXECUTION)
            release.set()
            assert (
                await hosted.wait_execution("A")
            ).status is ExecutionStatusV1.INTERRUPTED
            hosted.start_execution(ExecutionRequestV1("B", "next"))
            assert (
                await hosted.wait_execution("B")
            ).status is ExecutionStatusV1.SUCCEEDED
        finally:
            release.set()
            await hosted.close()

    _run(scenario())


def test_prompt_preserves_literal_builtin_text_without_executing_command(tmp_path):
    async def scenario():
        binding, session = await _binding(tmp_path)
        hosted = CodingHostedExecutionSessionV1(binding)
        try:
            hosted.start_execution(ExecutionRequestV1("A", "/import"))
            outcome = await hosted.wait_execution("A")
            assert outcome.status is ExecutionStatusV1.SUCCEEDED
            assert outcome.legacy_result == AckV1()
            await hosted.start_turn("/import")
            assert [message.content[0].text for message in session.messages] == [
                "/import",
                "response",
                "/import",
                "response",
            ]
        finally:
            await hosted.close()

    _run(scenario())


def test_canonical_product_factory_can_supply_optional_execution_port(tmp_path):
    from tests.coding.test_hosted_session import _binding as make_canonical_binding

    async def scenario():
        binding = await make_canonical_binding(tmp_path)
        hosted = CodingHostedExecutionSessionV1(binding)
        try:
            hosted.start_execution(
                ExecutionRequestV1("factory-A", "canonical execution")
            )
            assert (
                await hosted.wait_execution("factory-A")
            ).status is ExecutionStatusV1.SUCCEEDED
            snapshot = await hosted.snapshot_execution()
            assert [record.text for record in snapshot.source.records] == [
                "canonical execution",
                "real Coding response",
            ]
            assert snapshot.observation.execution_id == "factory-A"
        finally:
            await hosted.close()
        assert len(tuple((tmp_path / "sessions").glob("*.jsonl"))) == 1

    _run(scenario())


def test_terminal_waits_for_events_scheduled_by_final_owner_cleanup(
    tmp_path, monkeypatch
):
    async def scenario():
        entered, delivering, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def command(args, context):
            entered.set()
            await asyncio.Event().wait()

        binding, session = await _binding(tmp_path, command=command)

        async def hold_cleanup_event(event):
            if event.kind == "session.tool_approval_resolved":
                delivering.set()
                await release.wait()

        unsubscribe = session.runtime.subscribe(hold_cleanup_event)
        navigation = session._composition.navigation_runtime
        cancel_and_wait = navigation.cancel_and_wait

        async def finish_owner():
            await cancel_and_wait()
            session.runtime.schedule_event_dispatch(
                ToolPolicyAuditEvent(
                    event_type="tool_approval_resolved",
                    details={"hosted_presentation": True, "interaction_id": "cleanup"},
                )
            )

        monkeypatch.setattr(navigation, "cancel_and_wait", finish_owner)
        hosted = CodingHostedExecutionSessionV1(binding)
        events = []
        hosted.subscribe_execution_content(events.append)
        try:
            hosted.start_execution(ExecutionRequestV1("A", "/work"))
            await entered.wait()
            hosted.interrupt_execution("A", InterruptModeV1.WHOLE_EXECUTION)
            await delivering.wait()
            assert hosted.execution_state.status is ExecutionStatusV1.RUNNING
            release.set()
            assert (
                await hosted.wait_execution("A")
            ).status is ExecutionStatusV1.INTERRUPTED
            snapshot = await hosted.snapshot_execution()
            assert events[-1].execution_id == "A"
            assert events[-1].source.kind is SessionEventKindV1.INTERACTION_DISMISSED
            assert snapshot.observation.final_cursor == events[-1].source.cursor
        finally:
            release.set()
            unsubscribe()
            monkeypatch.setattr(navigation, "cancel_and_wait", cancel_and_wait)
            await hosted.close()

    _run(scenario())
