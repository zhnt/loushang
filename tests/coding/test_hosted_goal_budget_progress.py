"""Offline budget and progress contracts on the original hosted repository owner."""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from loushang.appserver.goal import GoalServiceError
from loushang.appserver.protocol import AppServiceError
from loushang.appservice.execution_contract import ExecutionOutcomeV1, ExecutionStatusV1
from loushang.coding._hosted_goal_config import CodingHostedGoalV1, HostedGoalSetup
from loushang.coding._hosted_goal_work import GoalInvocation
from loushang.harnesswork.goal import GoalError
from loushang.harnesswork.goal.records import plain

from .test_hosted_execution import _private_home as _private_home
from .test_hosted_repository_goal import application, package
from .test_hosted_repository_goal import cleanup_adapter as cleanup_adapter
from .test_repository_goal import implementation_adapter


@pytest.mark.parametrize("deadline,reserve", [
    (True, 0), (float("inf"), 0), (float("nan"), 0), (0, 0),
    (120, True), (120, -1), (120, 120), (120, float("inf")), (120, float("nan")),
    (10**400, 0), (120, 10**400),
])
def test_invalid_repository_time_configuration(tmp_path, deadline, reserve):
    with pytest.raises(ValueError):
        package(tmp_path, deadline_seconds=deadline, closeout_reserve_seconds=reserve)


def test_repository_explicit_time_and_calculator_compatibility(tmp_path):
    _, config, _ = package(tmp_path, deadline_seconds=240, closeout_reserve_seconds=60)
    assert config.deadline_seconds == 240
    with pytest.raises(ValueError):
        CodingHostedGoalV1(config.workspace, config.data_root, deadline_seconds=240)
    assert CodingHostedGoalV1(config.workspace, config.data_root).deadline_seconds == 120


def test_budget_material_and_cheap_progress_preserve_full_validation(tmp_path, monkeypatch):
    async def scenario():
        launch, config, task = package(tmp_path, deadline_seconds=240,
                                      closeout_reserve_seconds=60, max_model_calls=5, max_advances=4)
        adapter = implementation_adapter(task, "VALUE = 1\n")
        original_invoke = adapter.invoke_prepared_raw
        repairs = []

        async def capture(request, prepared):
            if request.context.tools:
                for message in prepared.payload_for_transport()["messages"]:
                    for part in message.get("content", ()):
                        if isinstance(part, dict) and "Implement the admitted action.\n" in part.get("text", ""):
                            text = part["text"].split("Implement the admitted action.\n", 1)[1]
                            repairs.append(json.JSONDecoder().raw_decode(text)[0])
            async for event in original_invoke(request, prepared):
                yield event

        adapter.invoke_prepared_raw = capture
        app, scope, control = await application(launch, config, adapter)
        try:
            client = scope.goal_client
            submitted = await client.start(control, client.service_instance_id, "budget")
            result = await client.wait(control, submitted.handle)
            assert result.execution.state.status is ExecutionStatusV1.SUCCEEDED
            assert result.observation.validity == "current"
            _, binding = await client._execution._resolve(control, client.service_instance_id)
            port, owner = binding.port, binding.port._goal
            core = owner.controller
            assert not port._invocation.model_stage
            assert port.goal_capability.supports_progress
            material = adapter.inputs[0]
            assert material["limits"]["work_intents"] == 4
            assert material["remaining"]["work_intents_including_this_planning"] == 4
            assert core.query("repository").limit == 6
            assert material["limits"]["repair_calls"] == 5
            assert material["limits"]["provider_attempts"] == 1
            assert material["remaining"]["model_calls_remaining_including_next_call"] == 5
            budget = material["hosted_budget"]
            assert budget["total_calls"] == 0
            assert 0 < budget["model_seconds_remaining"] <= 180
            assert budget["business_seconds_remaining"] > budget["model_seconds_remaining"]
            assert repairs and all(r["hosted_budget"]["total_calls"] == 1 for r in repairs)
            assert all(r["hosted_budget"]["model_calls_remaining_including_next_call"] == 4 for r in repairs)
            limits = plain(core.query("repository").metadata["hosted_execution_limits"])
            assert limits["version"] == 1 and limits["max_model_calls"] == 5
            assert core.query("repository").metadata["planning_limits"]["repair_calls"] == 12

            def forbidden(*args, **kwargs):
                raise AssertionError("progress reached history or business verification")

            # Full history lookup and validation are forbidden even after completion.
            with monkeypatch.context() as patch:
                patch.setattr(owner, "query", forbidden)
                patch.setattr(owner._profile.task, "snapshot", forbidden)
                patch.setattr(owner._work, "query", forbidden)
                patch.setattr(owner._work._event_log, "query", forbidden)
                patch.setattr(owner._work, "get_run_for_operation", forbidden)
                progress = await client.progress(control, submitted.handle)
                assert progress.observation.validity == "not_checked"
                assert progress.observation.status == "completed"
                assert not progress.observation.execution_unresolved
                assert all(b.work and not b.work.steps and not b.errors
                           for b in progress.observation.batches)
                # A loaded record must not trigger get_cancellation's history fallback.
                original_record = owner._work.get_recording
                patch.setattr(owner._work, "get_recording", lambda run_id:
                              replace(original_record(run_id), basis="loaded"))
                patch.setattr(owner._work, "get_cancellation", forbidden)
                uncertain = await client.progress(control, submitted.handle)
                assert uncertain.observation.validity == "unknown"
                assert uncertain.observation.execution_unresolved

            with monkeypatch.context() as patch:
                history = core.history
                patch.setattr(core, "_history", replace(history, batches=(
                    replace(history.batches[0], run_receipt=None), *history.batches[1:])))
                patch.setattr(owner._work, "get_run_for_operation", forbidden)
                pending = await client.progress(control, submitted.handle)
                assert pending.observation.execution_unresolved
                assert pending.observation.batches[0].work is None

            # Budget metadata cannot be silently ignored by business admission.
            with monkeypatch.context() as patch:
                state = core.query("repository")
                metadata = {**state.metadata, "hosted_execution_limits": {**limits, "version": 2}}
                patch.setattr(core, "_history", replace(core.history, goals={
                    "repository": replace(state, metadata=metadata)}))
                with pytest.raises(GoalError, match="hosted execution limits"):
                    owner._policy._current_inputs(core._basis("repository"))

            (task.root / "target.py").write_text("VALUE = 99\n")
            assert (await client.progress(control, submitted.handle)).observation.validity == "not_checked"
            assert (await client.query(control, submitted.handle)).observation.validity != "current"
        finally:
            await app.close()
    asyncio.run(scenario())


def test_model_deadline_cancels_original_work_and_retry_only_settles(tmp_path, monkeypatch):
    from loushang.coding import _hosted_goal_work as module

    async def scenario():
        launch, config, task = package(tmp_path, closeout_reserve_seconds=30)
        adapter = implementation_adapter(task, "VALUE = 1\n")
        invoke = adapter.invoke_prepared_raw
        entered, release = asyncio.Event(), asyncio.Event()

        async def blocked(request, prepared):
            entered.set()
            await release.wait()
            async for event in invoke(request, prepared):
                yield event

        adapter.invoke_prepared_raw = blocked
        app, scope, control = await application(launch, config, adapter)
        try:
            client = scope.goal_client
            submitted = await client.start(control, client.service_instance_id, "stop-model")
            await asyncio.wait_for(entered.wait(), 20)
            _, binding = await client._execution._resolve(control, client.service_instance_id)
            invocation = binding.port._invocation
            clock = invocation.model_deadline
            monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock))
            invocation._timer.reschedule(asyncio.get_running_loop().time())
            result = await client.wait(control, submitted.handle)
            assert result.execution.state.status is ExecutionStatusV1.FAILED
            assert result.observation.reason_code == "goal_model_stage_deadline_exceeded"
            assert result.observation.model_calls == 1
            assert not result.observation.execution_unresolved
            assert len(result.observation.batches) == 1
            assert result.observation.batches[0].work.status in {"cancelled", "failed"}
            before = (invocation.model_deadline, invocation.deadline)
            await client.retry_settlement(control, submitted.handle)
            assert (invocation.model_deadline, invocation.deadline) == before
            assert binding.port._setup.allowance.total_calls == 1
        finally:
            release.set()
            await app.close()
    asyncio.run(scenario())


def test_progress_optional_capability_and_revocation_during_delivery(tmp_path, monkeypatch):
    async def scenario():
        launch, config, task = package(tmp_path)
        adapter = implementation_adapter(task, "VALUE = 1\n")
        app, scope, control = await application(launch, config, adapter)
        try:
            client = scope.goal_client
            submitted = await client.start(control, client.service_instance_id, "progress")
            await client.wait(control, submitted.handle)
            _, binding = await client._execution._resolve(control, client.service_instance_id)
            port = binding.port
            capability = port.goal_capability
            with monkeypatch.context() as patch:
                patch.setattr(type(port), "goal_capability", property(lambda self:
                              replace(capability, supports_progress=False)))
                with pytest.raises(GoalServiceError, match="unsupported"):
                    await client.progress(control, submitted.handle)
            with pytest.raises(GoalServiceError, match="binding_changed"):
                await client.progress(control, replace(submitted.handle, goal_binding="wrong"))
            original = port.progress_goal
            entered, release = asyncio.Event(), asyncio.Event()

            async def delayed(execution_id):
                value = await original(execution_id)
                entered.set()
                await release.wait()
                return value

            monkeypatch.setattr(port, "progress_goal", delayed)
            reading = asyncio.create_task(client.progress(control, submitted.handle))
            await entered.wait()
            await scope.close()
            release.set()
            with pytest.raises(AppServiceError):
                await reading
            assert adapter.calls == 3
        finally:
            await app.close()
    asyncio.run(scenario())


def test_late_completed_repair_does_not_admit_verification(tmp_path, monkeypatch):
    from loushang.coding import _hosted_goal_work as module
    from loushang.harnesswork.runtime import WorkRuntime

    async def scenario():
        launch, config, task = package(tmp_path, closeout_reserve_seconds=30)
        adapter = implementation_adapter(task, "VALUE = 1\n")
        app, scope, control = await application(launch, config, adapter)
        try:
            client = scope.goal_client
            _, binding = await client._execution._resolve(control, client.service_instance_id)
            original_wait = WorkRuntime.wait

            async def late(runtime, run_id):
                result = await original_wait(runtime, run_id)
                invocation = binding.port._invocation
                owner = binding.port._goal
                if runtime is owner._work and owner.controller.history.batches[-1].source.get("phase") == "repair":
                    clock = invocation.model_deadline
                    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock))
                return result

            monkeypatch.setattr(WorkRuntime, "wait", late)
            submitted = await client.start(control, client.service_instance_id, "late-repair")
            result = await client.wait(control, submitted.handle)
            assert result.execution.state.status is ExecutionStatusV1.FAILED
            assert result.observation.reason_code == "goal_model_stage_deadline_exceeded"
            assert result.observation.model_calls == 3
            assert len(result.observation.batches) == 2
            assert result.observation.batches[-1].work.status == "completed"
            assert binding.port._invocation.model_stage
            assert not result.observation.execution_unresolved
        finally:
            await app.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("reserve", [0, 30])
def test_original_invocation_checks_model_and_total_deadlines(tmp_path, monkeypatch, reserve):
    from loushang.coding import _hosted_goal_work as module

    async def scenario():
        _, config, _ = package(tmp_path, closeout_reserve_seconds=reserve)
        setup = HostedGoalSetup(config, repository=SimpleNamespace(tool_policy=lambda root: None))
        invocation = GoalInvocation(None, None, setup, "time", lambda: False)
        clock = [100.0]
        monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))

        async def drive():
            clock[0] = invocation.model_deadline
            setup.allowance.enter("op", "planning")
            # No provider/transport is invoked, and no invocation is charged.
            await setup.allowance.stream(None, None)

        monkeypatch.setattr(invocation, "_drive", drive)
        result = await invocation.run(None)
        assert result.status is ExecutionStatusV1.FAILED
        assert invocation.reason == ("goal_model_stage_deadline_exceeded" if reserve else "goal_deadline_exceeded")
        assert setup.allowance.total_calls == 0
        original_reason = invocation.reason
        clock[0] += 1000
        with pytest.raises(asyncio.CancelledError):
            invocation.checkpoint()
        assert invocation.reason == original_reason
    asyncio.run(scenario())


def test_closeout_changes_original_timer_without_extending_total_deadline(tmp_path, monkeypatch):
    from loushang.coding import _hosted_goal_work as module

    async def scenario():
        _, config, _ = package(tmp_path, closeout_reserve_seconds=30)
        setup = HostedGoalSetup(config, repository=SimpleNamespace(tool_policy=lambda root: None))
        invocation = GoalInvocation(None, None, setup, "closeout", lambda: False)
        clock = [100.0]
        monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))

        async def drive():
            original_timer = invocation._timer
            before = original_timer.when()
            clock[0] = invocation.model_deadline - 1
            invocation.begin_closeout()
            assert invocation._timer is original_timer
            # The same absolute D remains, despite moving from model to closeout.
            assert invocation.deadline == 220
            assert original_timer.when() < before
            clock[0] = invocation.model_deadline + 1
            invocation.checkpoint()
            clock[0] = invocation.deadline
            invocation.checkpoint()
            return ExecutionOutcomeV1(ExecutionStatusV1.SUCCEEDED)

        monkeypatch.setattr(invocation, "_drive", drive)
        result = await invocation.run(None)
        assert result.status is ExecutionStatusV1.FAILED
        assert invocation.reason == "goal_deadline_exceeded"
    asyncio.run(scenario())


@pytest.mark.parametrize("later", ["cancel", "error"])
def test_late_interruption_preserves_locked_deadline_reason(tmp_path, monkeypatch, later):
    from loushang.coding import _hosted_goal_work as module

    async def scenario():
        _, config, _ = package(tmp_path, closeout_reserve_seconds=30)
        setup = HostedGoalSetup(config, repository=SimpleNamespace(tool_policy=lambda root: None))
        invocation = GoalInvocation(None, None, setup, "late-stop", lambda: False)
        clock = [100.0]
        monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        observed = asyncio.Event()

        async def drive():
            clock[0] = invocation.model_deadline
            with pytest.raises(TimeoutError):
                invocation.checkpoint()
            observed.set()
            if later == "error":
                raise RuntimeError("late business exception")
            await asyncio.Event().wait()

        monkeypatch.setattr(invocation, "_drive", drive)
        running = asyncio.create_task(invocation.run(None))
        await observed.wait()
        if later == "cancel":
            running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await running
            with pytest.raises(asyncio.CancelledError):
                await invocation.task
        else:
            result = await running
            assert result.status is ExecutionStatusV1.FAILED
        assert invocation.reason == "goal_model_stage_deadline_exceeded"
        assert setup.allowance.total_calls == 0

    asyncio.run(scenario())
