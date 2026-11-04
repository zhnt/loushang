"""One finite profile through embedded Session binding and app-local service."""
from __future__ import annotations

import asyncio

import pytest

from loushang.ai.api_registry import get_default_api_registry
from loushang.ai.model import Auth, Capabilities, Model
from loushang.appservice.execution_contract import ExecutionStatusV1
from loushang.coding import create_agent_session_runtime
from loushang.coding.adapters.goal import CodingGoal
from loushang.harness.session.execution_scope import SessionExecutionScope
from loushang.harnesswork.integrations.session_goal import SessionGoalController
from loushang.harnesswork.plan_projection import project_work_plan_runs

from .test_hosted_execution import _private_home as _private_home
from .test_hosted_goal import CalculatorAdapter, application, task
from .test_work_shell import _goal_project


def _business_snapshot(owner, advances):
    state = owner.controller.query("calculator")
    batches = owner.controller.history.batches
    identities = {batch.operation_id: index for index, batch in enumerate(batches)}
    assert len(identities) == len(batches)
    work = []
    for batch in batches:
        run = owner._work.get_run_for_operation(batch.operation_id)
        assert run is not None and run.operation_id == batch.operation_id
        assert run.session_id == owner.session_id
        recording = owner._work.get_recording(run.run_id)
        assert recording.contract is not None and recording.contract.require_persistence
        plans = project_work_plan_runs(owner._work.query(run_id=run.run_id))
        assert len(plans) == 1
        work.append((batch.source["phase"], run.status, run.method_id,
                     tuple((step.step_id, step.status) for step in plans[0].steps),
                     owner._work.get_cancellation(run.run_id).status))
    acceptance = state.acceptance or {}
    return dict(
        status=state.status, reason=state.reason, revision=state.revision, epoch=state.epoch,
        requirements=tuple(requirement.id for requirement in state.requirements),
        coverage=tuple(acceptance.get("coverage", ())),
        dependencies=tuple(identities[operation] for operation in acceptance.get("operations", ())),
        calls=owner._allowance.total_calls, advances=advances, work=tuple(work),
    )


@pytest.mark.parametrize("invalid", [False, True])
def test_embedded_and_application_local_goal_preserve_same_business_result(tmp_path, invalid):
    async def scenario():
        local_root = tmp_path / "local"
        local_root.mkdir(mode=0o700)
        hosted_root = tmp_path / "hosted"
        hosted_root.mkdir(mode=0o700)
        workspace = _goal_project(local_root)
        launch, config = task(hosted_root)
        adapter = CalculatorAdapter(workspace, invalid=invalid)
        registry = get_default_api_registry()
        registry.register_api_adapter(adapter, source_id=adapter.api)
        model = Model(id="offline-calculator", provider="offline", endpoint="offline", api=adapter.api,
                      base_url="https://unused.invalid", auth=Auth(kind="none"),
                      capabilities=Capabilities(input=("text",), output=("text",), context_window=128000,
                                                max_tokens=4096, stream=True, tool_use=True))
        sdk = create_agent_session_runtime(
            session_dir=local_root / "data/sessions", model=model, enable_multiagent=False,
            active_tool_names=["read", "edit", "write"],
            allowed_tool_names=["read", "edit", "write", "bash"],
            system_prompt="Pursue the finite calculator Goal. Planning turns return only the requested JSON; "
                          "Method steps may use file tools and change only calculator.py. "
                          "Do not change requirements, tests, Method or permissions. "
                          "Only independent verification establishes completion.",
        )
        owner = app = None
        try:
            session = await sdk.create_session(cwd=str(workspace))
            # Match the frozen dedicated hosted profile's initial configuration;
            # attach itself preserves it, as the ordinary-Session tests verify.
            session.set_auto_retry_enabled(False)
            session.set_auto_compaction_enabled(False)
            for invalid_budget in ({"max_model_calls": True}, {"max_output_tokens": 0}):
                with pytest.raises(ValueError, match="positive model allowance"):
                    await CodingGoal.attach(session=session, **invalid_budget)
                assert session.runtime.execution_scope is None
            owner = await CodingGoal.attach(
                session=session, max_model_calls=config.max_model_calls,
                max_output_tokens=config.max_output_tokens,
            )
            owner.create("calculator", command_id="local:create")
            advances = 0
            for index in range(config.max_advances):
                state = owner.controller.query("calculator")
                if state.status != "active":
                    break
                advances += 1
                await owner.advance("calculator", command_id=f"local:{index}",
                                    revision=state.revision, epoch=state.epoch)
                view = await owner.query("calculator")
                if view.goal.status == "completed":
                    break
            local = _business_snapshot(owner, advances)
            local_view = await owner.query("calculator")
            assert adapter.calls == local["calls"] <= config.max_model_calls
            assert type(owner.controller) is SessionGoalController
            assert type(owner._scope) is SessionExecutionScope
            await owner.close()
            await sdk.dispose_session_runtime()
            registry.unregister_api_adapters(adapter.api)

            hosted_adapter = CalculatorAdapter(config.workspace, invalid=invalid)
            app, scope, control, _ = await application(launch, config, hosted_adapter)
            client = scope.goal_client
            submitted = await client.start(control, client.service_instance_id, "equivalence")
            result = await client.wait(control, submitted.handle)
            _, binding = await client._execution._resolve(control, client.service_instance_id)
            hosted = binding.port._goal
            assert type(hosted.controller) is SessionGoalController
            assert type(hosted._scope) is SessionExecutionScope
            assert _business_snapshot(hosted, result.observation.advances) == local
            assert result.observation.model_calls == hosted_adapter.calls == local["calls"]
            assert result.observation.validity == local_view.validity
            assert result.observation.execution_unresolved == local_view.execution_unresolved
            expected = ExecutionStatusV1.FAILED if invalid else ExecutionStatusV1.SUCCEEDED
            assert result.execution.state.status is expected
            assert local["status"] == ("paused" if invalid else "completed")
            assert bool(local["coverage"]) is not invalid
        finally:
            if app is not None:
                await app.close()
            if owner is not None:
                await owner.close()
            await sdk.dispose_session_runtime()
            registry.unregister_api_adapters(adapter.api)

    asyncio.run(scenario())
