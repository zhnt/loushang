from __future__ import annotations

import asyncio
from unittest.mock import create_autospec

import pytest

from loushang.appserver.client import AppClientV1
from loushang.appserver.connection import AppServerConnectionV1
from loushang.appserver.execution.client import ExecutionClientV1
from loushang.appserver.execution.codec import (
    decode_response as decode_execution_response,
)
from loushang.appserver.execution.codec import encode_call
from loushang.appserver.execution.model import (
    ExecutionCallV1,
    ExecutionGoalBatchV1,
    ExecutionGoalProgressV1,
    ExecutionOperationV1,
    ExecutionRecordV1,
    ExecutionServiceErrorV1,
    ExecutionStatusV1,
)
from loushang.appserver.framing import AppFramedStreamV1
from loushang.appserver.managed_mux import ManagedMuxCreationClientV1
from loushang.appserver.managed_mux_close import ManagedMuxCloseClientV1
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppFailureV1,
    AppOperationV1,
    AppRequestV1,
    AppServiceError,
    SessionModelChoiceV1,
    SessionModelSelectV1,
    SessionModelsV1,
    SessionSnapshotRequestV1,
    SessionThinkingV1,
    decode_response,
    encode_request,
)
from loushang.appserver.protocol.codec import _dumps, _loads
from loushang.appserver.protocol.connection_profile import (
    AppConnectionProfileV1,
    supports_managed_mux,
    supports_managed_mux_close,
)
from loushang.appserver.remote_client import RemoteAppClientV1
from loushang.appserver.resume_model import (
    ResumeInputLookupQueryV1,
    ResumeInputLookupResultV1,
)
from tests.appservice.test_execution_guard import scenario
from tests.appservice.test_execution_service import fixture

from .test_connection import _pair


@pytest.mark.parametrize("request_thinking", [False, True])
def test_session_thinking_uses_an_opt_in_execution_hello(request_thinking):
    async def run():
        left, right = _pair()
        frames = AppFramedStreamV1(left)
        client = create_autospec(AppClientV1, instance=True)
        execution = create_autospec(ExecutionClientV1, instance=True)
        execution.service_instance_id = "instance"
        choice = SessionModelChoiceV1("model", "provider", "endpoint", "id", "Model", True)
        thinking = SessionThinkingV1("high", ("off", "high"))
        client.list_session_models.return_value = SessionModelsV1("model", (choice,), thinking)
        client.select_session_model.return_value = client.list_session_models.return_value
        server = AppServerConnectionV1(
            client, AppFramedStreamV1(right),
            profile=AppConnectionProfileV1.LOCAL_EXECUTION, execution=execution,
        )
        serving = asyncio.create_task(server.serve())
        try:
            hello = await frames.receive()
            echo = _dumps({**_loads(hello), "sessionThinking": True}) if request_thinking else hello
            await frames.send(echo)
            if request_thinking:
                assert await frames.receive() == echo
            request = AppRequestV1(
                "1", AppOperationV1.SESSION_MODELS, SessionSnapshotRequestV1("a", 1, "m"),
            )
            await frames.send(encode_request(request))
            result = decode_response(await frames.receive()).result
            assert result == SessionModelsV1("model", (choice,), thinking if request_thinking else None)
            selection = SessionModelSelectV1("a", 1, "m", "model", "high")
            await frames.send(encode_request(AppRequestV1(
                "2", AppOperationV1.SESSION_MODEL_SELECT, selection,
            )))
            updated = decode_response(await frames.receive()).result
            if request_thinking:
                assert updated == result
                client.select_session_model.assert_awaited_once_with(selection)
            else:
                assert updated == AppFailureV1(AppErrorCodeV1.OPERATION_UNAVAILABLE)
                client.select_session_model.assert_not_awaited()
        finally:
            await frames.close()
            await serving

    asyncio.run(run())


def test_goal_batch_details_are_opt_in_on_the_existing_progress_operation():
    async def run():
        left, right = _pair()
        frames = AppFramedStreamV1(left)
        app = create_autospec(AppClientV1, instance=True)
        execution = create_autospec(ExecutionClientV1, instance=True)
        execution.service_instance_id = "instance"
        control = SessionSnapshotRequestV1("attachment", 1, "member")
        expected = ExecutionGoalProgressV1(
            "exec", "present", "goal", "paused", "model_budget", "not_checked", False, 1, 2, 1,
            (ExecutionGoalBatchV1("batch-1", None, False, None, True),),
        )

        async def goal_progress(address, instance, execution_id):
            assert (address, instance, execution_id) == (control, "instance", "exec")
            return expected

        execution.goal_progress = goal_progress
        server = AppServerConnectionV1(
            app, AppFramedStreamV1(right),
            profile=AppConnectionProfileV1.LOCAL_EXECUTION, execution=execution,
        )
        serving = asyncio.create_task(server.serve())
        try:
            await frames.send(await frames.receive())
            responses = []
            for number, include in enumerate((False, True), 1):
                await frames.send(encode_call(ExecutionCallV1(
                    str(number), ExecutionOperationV1.GOAL_PROGRESS, control, "instance",
                    execution_id="exec", include_goal_batches=include,
                )))
                responses.append(await frames.receive())
            assert decode_execution_response(responses[1]).result == expected
            legacy, current = (_loads(reply)["result"] for reply in responses)
            assert "batches" not in legacy
            assert legacy == {key: value for key, value in current.items() if key != "batches"}
        finally:
            await frames.close()
            await serving

    asyncio.run(run())


@pytest.mark.parametrize("profile", [
    AppConnectionProfileV1.LOCAL_EXECUTION,
    AppConnectionProfileV1.LOCAL_RESUME_EXECUTION,
    AppConnectionProfileV1.LOCAL_DISCOVERY_RESUME_EXECUTION,
    AppConnectionProfileV1.LOCAL_RESUME_EXECUTION_MANAGED,
    AppConnectionProfileV1.LOCAL_DISCOVERY_RESUME_EXECUTION_MANAGED,
    AppConnectionProfileV1.LOCAL_RESUME_EXECUTION_MANAGED_CLOSE,
    AppConnectionProfileV1.LOCAL_DISCOVERY_RESUME_EXECUTION_MANAGED_CLOSE,
])
def test_resume_lookup_is_negotiated_and_reaches_the_existing_scoped_owner(profile):
    async def run():
        service, owner, first, second, selector, control, product = await fixture()
        calls = []

        async def lookup(query):
            calls.append(query)
            return ResumeInputLookupResultV1(query.input_id, "record-1", "committed")

        product.lookup_resume_input = lookup
        enabled = profile is not AppConnectionProfileV1.LOCAL_EXECUTION
        left, right = _pair()
        server = AppServerConnectionV1(
            first, AppFramedStreamV1(right), profile=profile, execution=first.execution_client,
            managed_mux=(create_autospec(ManagedMuxCreationClientV1, instance=True)
                         if supports_managed_mux(profile) else None),
            managed_mux_close=(create_autospec(ManagedMuxCloseClientV1, instance=True)
                               if supports_managed_mux_close(profile) else None),
        )
        remote = RemoteAppClientV1(AppFramedStreamV1(left), profile=profile)
        serving = asyncio.create_task(server.serve())
        query = ResumeInputLookupQueryV1("input-1", "a" * 64)
        try:
            await remote.start()
            client = remote.execution_client
            assert client.resume_input_lookup_available is enabled
            assert remote.resume_input_lookup_client is (client if enabled else None)
            if enabled:
                assert (await client.lookup_resume_input(control, "instance", query)).status == "committed"
                assert calls == [query]
                with pytest.raises(ExecutionServiceErrorV1):
                    await client.lookup_resume_input(control, "different-instance", query)
            else:
                with pytest.raises(AppServiceError) as unsupported:
                    await client.lookup_resume_input(control, "instance", query)
                assert unsupported.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
                # A peer manually encoding the new operation cannot bypass the
                # negotiated profile or reach the Product on an old profile.
                with pytest.raises(AppServiceError) as unsupported_wire:
                    await remote._send_execution(
                        lambda request_id: ExecutionCallV1(
                            request_id, ExecutionOperationV1.RESUME_INPUT_LOOKUP,
                            control, "instance", resume_query=query,
                        ), ResumeInputLookupResultV1, True, False,
                    )
                assert unsupported_wire.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
                assert calls == []
            assert owner.pending_counts == (0, 0)
            assert product.legacy_calls == []
            assert (await remote.list_muxes()).mux_spaces
        finally:
            await remote.close()
            await serving
            await service.close()

    asyncio.run(run())


@scenario
async def test_optional_execution_connection_submit_snapshot_interrupt_and_old_operations():
    service, owner, first, second, selector, control, product = await fixture()
    left, right = _pair()
    server = AppServerConnectionV1(
        first, AppFramedStreamV1(right), profile=AppConnectionProfileV1.LOCAL_EXECUTION,
        execution=first.execution_client,
    )
    remote = RemoteAppClientV1(AppFramedStreamV1(left), profile=AppConnectionProfileV1.LOCAL_EXECUTION)
    serving = asyncio.create_task(server.serve())
    try:
        assert remote.execution_client is None
        await remote.start()
        client = remote.execution_client
        assert client.service_instance_id == "instance"
        assert (await remote.list_muxes()).mux_spaces
        record = await client.submit_execution(control, "instance", "submission", "silent")
        await product.entered.wait()
        found = await client.find_execution_by_submission(control, "instance", "submission")
        assert found.state.execution_id == record.state.execution_id
        snapshot = await client.snapshot_execution_session(control, "instance")
        assert snapshot.executions.active.status is ExecutionStatusV1.RUNNING
        assert not snapshot.supports_goal_progress
        with pytest.raises(AppServiceError) as unsupported:
            await remote._send_execution(
                lambda request_id: ExecutionCallV1(
                    request_id, ExecutionOperationV1.GOAL_PROGRESS, control, "instance",
                    execution_id=record.state.execution_id,
                ), ExecutionGoalProgressV1, False, False,
            )
        assert unsupported.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
        assert not snapshot.supports_goal_start
        with pytest.raises(AppServiceError) as unsupported:
            await remote._send_execution(
                lambda request_id: ExecutionCallV1(
                    request_id, ExecutionOperationV1.GOAL_START, control, "instance", submission_id="goal",
                ), ExecutionRecordV1, False, False,
            )
        assert unsupported.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
        result = await client.interrupt_execution(control, "instance", record.state.execution_id)
        assert result.record.state.interrupt_requested or result.record.state.status.terminal
        await service._execution_registry.wait(service._sessions[product.identity.session_id]._execution, record)
        finished = await client.get_execution(control, "instance", record.state.execution_id)
        assert finished.state.status is ExecutionStatusV1.INTERRUPTED
        assert await client.read_execution_events(control, "instance")
        with pytest.raises(ExecutionServiceErrorV1) as stale:
            await client.submit_execution(control, "other-instance", "submission", "different")
        assert str(stale.value) == "service_instance_changed"
    finally:
        await remote.close()
        await serving
        await service.close()


@scenario
async def test_execution_requires_explicit_profile_and_injected_capability():
    service, owner, first, second, selector, control, product = await fixture()
    left, right = _pair()
    with pytest.raises(ValueError):
        AppServerConnectionV1(first, AppFramedStreamV1(right), profile=AppConnectionProfileV1.LOCAL_EXECUTION)
    with pytest.raises(ValueError):
        AppServerConnectionV1(first, AppFramedStreamV1(right), execution=first.execution_client)
    await service.close()


@pytest.mark.parametrize("extensions", [None, "thinking", "recovery"])
def test_cold_goal_recovery_capability_is_fenced_by_the_hello_echo(extensions):
    from loushang.appserver.execution.model import InteractiveGoalRecoveryV1

    async def run():
        service, _, first, _, _, control, product = await fixture()
        product.supports_interactive_goal_recovery = True
        expected = InteractiveGoalRecoveryV1("absent", "no_goal")
        calls = []

        async def observe():
            calls.append(control)
            return expected

        product.interactive_goal_recovery = observe
        left, right = _pair()
        frames = AppFramedStreamV1(left)
        server = AppServerConnectionV1(
            first, AppFramedStreamV1(right), profile=AppConnectionProfileV1.LOCAL_EXECUTION,
            execution=first.execution_client,
        )
        serving = asyncio.create_task(server.serve())
        enabled = extensions == "recovery"
        try:
            hello = await frames.receive()
            echo = _loads(hello)
            if extensions:
                echo["sessionThinking"] = True
            if enabled:
                echo["interactiveGoalRecovery"] = True
            await frames.send(_dumps(echo))
            if extensions:
                assert await frames.receive() == _dumps(echo)
            await frames.send(encode_call(ExecutionCallV1(
                "1", ExecutionOperationV1.SNAPSHOT, control, "instance",
            )))
            snapshot = await frames.receive()
            assert ("supportsInteractiveGoalRecovery" in _loads(snapshot)["result"]) == enabled
            await frames.send(encode_call(ExecutionCallV1(
                "2", ExecutionOperationV1.INTERACTIVE_GOAL_RECOVERY, control, "instance",
            )))
            result = decode_execution_response(await frames.receive()).result
            assert result == (expected if enabled else AppFailureV1(AppErrorCodeV1.OPERATION_UNAVAILABLE))
            assert calls == ([control] if enabled else [])
        finally:
            await frames.close()
            await serving
            await service.close()

    asyncio.run(run())
