from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from loushang.ai.api_registry import get_default_api_registry
from loushang.ai.json_codec import serialize_message
from loushang.ai.model import Auth, Capabilities, Model
from loushang.ai.prepared_request import PreparedModelRequest
from loushang.appserver.goal import GoalServiceError
from loushang.appserver.protocol import (
    AppServiceError,
    MuxAttachV1,
    MuxCreateV1,
    MuxMemberOpenV1,
    MuxSelectorV1,
    SessionOpenSpecV1,
    SessionScopeV1,
    SessionSnapshotRequestV1,
    TurnTextV1,
)
from loushang.appservice.execution_contract import ExecutionStatusV1
from loushang.coding.hosted_bootstrap import CodingHostedLaunchV1
from loushang.coding.hosted_goal_application import (
    CodingHostedGoalV1,
    create_coding_goal_application,
)

from .test_hosted_execution import _private_home as _private_home

FIXED = '''def subtract(a, b):
    return a - b


def clamp(value, lower, upper):
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value
'''


class CalculatorAdapter:
    api = "hosted-goal-offline"

    def __init__(self, workspace, *, block=False, invalid=False):
        self.workspace = workspace
        self.calls = self.plans = 0
        self.wrote = False
        self.block, self.invalid = block, invalid
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    def prepare_request(self, request):
        return PreparedModelRequest.from_provider_request(request, payload={
            "system": request.context.system_prompt,
            "messages": [serialize_message(m) for m in request.context.messages],
            "tools": [t.name for t in request.context.tools or ()], "model": request.model.id,
        })

    async def invoke_raw(self, request):
        async for event in self.invoke_prepared_raw(request, self.prepare_request(request)):
            yield event

    async def invoke_prepared_raw(self, request, prepared):
        self.calls += 1
        assert request.options.max_output_tokens <= 1024
        assert request.options.retry.max_attempts == 1
        prepared.payload_for_transport()
        self.entered.set()
        if self.block:
            await self.release.wait()
        yield {"type": "response_start", "response_id": f"hosted-{self.calls}"}
        names = {t.name for t in request.context.tools or ()}
        if not names:
            action = ("check", "repair", "verify_all")[min(self.plans, 2)]
            self.plans += 1
            targets = ["subtraction", "clamp"] if action == "check" else ["calculator"] if action == "repair" else []
            value = {
                "next_action": action, "targets": targets,
                "requirement_ids": ["R-SUB", "R-CLAMP", "R-FILES"],
                "rationale": "Use the latest execution evidence",
                "expected_evidence": ["method_execution"] if action == "repair" else ["report", "validation"],
                "remaining_route": [{"action": action, "targets": targets}],
                "change_reason": "Follow the completed check or repair", "evidence_refs": [],
            }
            yield {"type": "text_delta", "text": "invalid" if self.invalid else json.dumps(value)}
        elif names == {"read", "edit", "write"} and not self.wrote:
            self.wrote = True
            yield {"type": "tool_call_start", "id": "fix-calculator", "name": "write"}
            yield {"type": "tool_call_args_delta", "delta": json.dumps({"path": str(self.workspace / "calculator.py"), "content": FIXED})}
            yield {"type": "tool_call_done"}
            yield {"type": "stop_reason", "stop_reason": "toolUse"}
            yield {"type": "response_done"}
            return
        else:
            yield {"type": "text_delta", "text": "Inspect or repair step complete; independent verification must decide."}
        yield {"type": "stop_reason", "stop_reason": "stop"}
        yield {"type": "response_done"}


def task(tmp_path):
    workspace = tmp_path / "workspace"
    shutil.copytree(Path("examples/coding/goal_calculator"), workspace)
    launch = CodingHostedLaunchV1(workspace, tmp_path / "application", "coding.goal-test",
                                 tmp_path / "cwd-sessions", tmp_path / "home-sessions")
    return launch, CodingHostedGoalV1(workspace, tmp_path / "goal-data")


async def application(launch, config, adapter):
    get_default_api_registry().register_api_adapter(adapter, source_id=adapter.api)
    model = Model(id="offline-calculator", provider="offline", endpoint="offline", api=adapter.api,
                  base_url="https://unused.invalid", auth=Auth(kind="none"),
                  capabilities=Capabilities(input=("text",), output=("text",), context_window=128000,
                                            max_tokens=4096, stream=True, tool_use=True))
    app = await create_coding_goal_application(launch, config, model=model)
    try:
        scope = app.open_client_scope()
        mux = await scope.create_mux(MuxCreateV1("goal"))
        selector = MuxSelectorV1(mux_space_id=mux.mux_space_id)
        await scope.attach_mux(MuxAttachV1(selector))
        mux = await scope.open_member(MuxMemberOpenV1(selector, SessionOpenSpecV1(
            product_id="coding", continuity_id="goal", scope=SessionScopeV1.CWD,
            scope_fingerprint=launch.scopes[0].fingerprint, title="Hosted Goal",
        )))
        attachment = await scope.attach_mux(MuxAttachV1(selector))
        control = SessionSnapshotRequestV1(attachment.attachment_id, attachment.controller_generation, mux.members[0].member_id)
        return app, scope, control, selector
    except BaseException:
        await app.close()
        raise


def test_hosted_goal_real_planning_method_verification_and_scoped_queries(tmp_path):
    async def scenario():
        launch, config = task(tmp_path)
        protected = {p.relative_to(config.workspace): p.read_bytes() for p in config.workspace.rglob("*") if p.is_file() and p.name != "calculator.py"}
        adapter = CalculatorAdapter(config.workspace)
        app, scope, control, selector = await application(launch, config, adapter)
        try:
            assert scope.execution_client is None and scope.method_work_client is None
            client = scope.goal_client
            submitted = await client.start(control, client.service_instance_id, "goal-1")
            assert (await client.start(control, client.service_instance_id, "goal-1")).handle == submitted.handle
            result = await client.wait(control, submitted.handle)
            if result.execution.state.status is not ExecutionStatusV1.SUCCEEDED:
                _, binding = await client._execution._resolve(control, client.service_instance_id)
                error = binding.port._invocation.task.exception()
                if error is not None:
                    raise error
            assert result.execution.state.status is ExecutionStatusV1.SUCCEEDED, asdict(result)
            view = result.observation
            assert view.status == "completed" and view.validity == "current" and not view.execution_unresolved
            assert 1 < view.advances <= 8 and view.model_calls == adapter.calls <= 8
            runs = [b.work for b in view.batches]
            assert any(r.status == "failed" for r in runs)
            assert any(r.method_id for r in runs)
            assert runs[-1].status == "completed"
            assert len({r.session_id for r in runs}) == 1
            assert len({r.operation_id for r in runs}) == len(runs)
            assert all(r.operation_id != submitted.handle.execution_id for r in runs)
            assert all(b.recording.require_persistence for b in view.batches)
            assert "metadata" not in json.dumps(asdict(view)) and str(tmp_path) not in json.dumps(asdict(view))
            assert all((config.workspace / name).read_bytes() == content for name, content in protected.items())
            with pytest.raises(GoalServiceError):
                await client.start(control, client.service_instance_id, "second")
            with pytest.raises(GoalServiceError, match="binding_changed"):
                await client.query(control, replace(submitted.handle, goal_binding="wrong"))
            with pytest.raises(AppServiceError):
                await scope.start_turn(TurnTextV1(control.attachment_id, control.controller_generation, control.member_id, "bypass"))
            before = adapter.calls
            await scope.close()
            with pytest.raises(AppServiceError):
                await client.query(control, submitted.handle)
            scope2 = app.open_client_scope()
            attached = await scope2.attach_mux(MuxAttachV1(selector))
            control2 = replace(control, attachment_id=attached.attachment_id, controller_generation=attached.controller_generation)
            found = await scope2.goal_client.find(control2, scope2.goal_client.service_instance_id, "goal-1")
            assert found.handle == submitted.handle
            assert (await scope2.goal_client.query(control2, found.handle)).observation.status == "completed"
            assert adapter.calls == before
        finally:
            await app.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["interrupt", "deadline", "calls", "advances", "invalid"])
def test_hosted_goal_bounded_stop_never_claims_completion(tmp_path, mode):
    async def scenario():
        launch, config = task(tmp_path)
        adapter = CalculatorAdapter(config.workspace, block=mode in {"interrupt", "deadline"}, invalid=mode == "invalid")
        config = replace(config, **({"deadline_seconds": 1.0} if mode == "deadline" else
                                    {"max_model_calls": 1} if mode == "calls" else
                                    {"max_advances": 1} if mode == "advances" else {}))
        app, scope, control, _ = await application(launch, config, adapter)
        try:
            client = scope.goal_client
            submitted = await client.start(control, client.service_instance_id, "one")
            if mode == "interrupt":
                await asyncio.wait_for(adapter.entered.wait(), 20)
                await client.interrupt(control, submitted.handle)
            result = await client.wait(control, submitted.handle)
            assert result.execution.state.status in {ExecutionStatusV1.FAILED, ExecutionStatusV1.INTERRUPTED}, asdict(result)
            assert result.observation.status != "completed"
            assert adapter.calls <= config.max_model_calls
            before = adapter.calls
            await client.retry_settlement(control, submitted.handle)
            assert adapter.calls == before
        finally:
            await app.close()
    asyncio.run(scenario())


def test_goal_rejects_overlapping_roots_before_creation(tmp_path):
    launch, config = task(tmp_path)
    for path in (launch.workspace, launch.workspace / "data", tmp_path, launch.cwd_sessions):
        with pytest.raises(ValueError, match="overlap"):
            asyncio.run(create_coding_goal_application(launch, replace(config, data_root=path)))
    assert not launch.cwd_sessions.exists()


@pytest.fixture(autouse=True)
def _offline_registry():
    yield
    get_default_api_registry().unregister_api_adapters(CalculatorAdapter.api)


@pytest.mark.parametrize("initialization", [True, False])
def test_goal_cleanup_failure_retains_owner_and_retry_only_settles(tmp_path, monkeypatch, initialization):
    from loushang.coding.adapters.goal import CodingGoal

    async def scenario():
        launch, config = task(tmp_path)
        adapter = CalculatorAdapter(config.workspace)
        app, scope, control, _ = await application(launch, replace(config, max_advances=1), adapter)
        client = scope.goal_client
        _, binding = await client._execution._resolve(control, client.service_instance_id)
        port = binding.port
        retained = port._goal
        session = port._product_binding.control
        fail = True
        if initialization:
            original = CodingGoal.close

            def bad_create(self, *args, **kwargs):
                raise RuntimeError("injected after journal acquisition")

            async def close(self):
                if fail:
                    raise RuntimeError("injected Goal cleanup debt")
                await original(self)

            monkeypatch.setattr(CodingGoal, "create", bad_create)
            monkeypatch.setattr(CodingGoal, "close", close)
        else:
            original = session.settle_execution

            async def settle(*, interrupted=False):
                if fail:
                    raise RuntimeError("injected Session cleanup debt")
                await original(interrupted=interrupted)

            monkeypatch.setattr(session, "settle_execution", settle)
        try:
            submitted = await client.start(control, client.service_instance_id, "cleanup")
            with pytest.raises(AppServiceError):
                await client.wait(control, submitted.handle)
            snapshot = await client.query(control, submitted.handle)
            assert snapshot.execution.state.status is ExecutionStatusV1.RUNNING
            assert port._goal is retained and retained._sdk is None
            assert port._product_binding._close_task is None
            if initialization:
                assert snapshot.observation.presence == "unavailable" and retained._store is not None
                assert adapter.calls == 0
            count = adapter.calls
            fail = False
            result = await client.retry_settlement(control, submitted.handle)
            assert result.execution.state.status is ExecutionStatusV1.FAILED
            assert adapter.calls == count
            assert port._product_binding._close_task is None
        finally:
            fail = False
            await app.close()
        assert retained._closed and port._goal is None
    asyncio.run(scenario())


def test_detach_during_goal_keeps_execution_and_query_rechecks_authority(tmp_path, monkeypatch):
    async def scenario():
        launch, config = task(tmp_path)
        adapter = CalculatorAdapter(config.workspace, block=True)
        app, scope, control, selector = await application(launch, replace(config, max_advances=1), adapter)
        try:
            client = scope.goal_client
            submitted = await client.start(control, client.service_instance_id, "ongoing")
            await asyncio.wait_for(adapter.entered.wait(), 20)
            _, binding = await client._execution._resolve(control, client.service_instance_id)
            port = binding.port
            original = port._goal.query
            entered, release = asyncio.Event(), asyncio.Event()

            async def query(goal_id):
                entered.set()
                await release.wait()
                return await original(goal_id)

            monkeypatch.setattr(port._goal, "query", query)
            reading = asyncio.create_task(client.query(control, submitted.handle))
            await entered.wait()
            await scope.close()
            release.set()
            with pytest.raises(AppServiceError):
                await reading
            assert not port._invocation.task.done()
            scope2 = app.open_client_scope()
            attached = await scope2.attach_mux(MuxAttachV1(selector))
            control2 = replace(control, attachment_id=attached.attachment_id, controller_generation=attached.controller_generation)
            adapter.release.set()
            result = await scope2.goal_client.wait(control2, submitted.handle)
            assert result.execution.state.status is ExecutionStatusV1.FAILED
            assert adapter.calls == 1
        finally:
            adapter.release.set()
            await app.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("at_completion", [False, True])
def test_recording_observer_failure_stops_next_batch_without_cleanup_debt(tmp_path, monkeypatch, at_completion):
    from loushang.harnesswork.recording import _RecordingObserver

    original = _RecordingObserver.observe
    completed = 0

    def observe(self, entry, **kwargs):
        nonlocal completed
        original(self, entry, **kwargs)
        if entry.payload.get("kind") == "WorkRunCompleted":
            completed += 1
        if completed == (5 if at_completion else 1):
            raise RuntimeError("append succeeded but confirmation observer failed")

    monkeypatch.setattr(_RecordingObserver, "observe", observe)

    async def scenario():
        launch, config = task(tmp_path)
        adapter = CalculatorAdapter(config.workspace)
        app, scope, control, _ = await application(launch, config, adapter)
        try:
            client = scope.goal_client
            submission = await client.start(control, client.service_instance_id, "recording")
            result = await client.wait(control, submission.handle)
            assert result.execution.state.status is ExecutionStatusV1.FAILED
            assert result.observation.reason_code == "work_recording_unavailable"
            assert result.observation.validity == "unknown"
            expected = 6 if at_completion else 1
            assert result.observation.advances == expected and adapter.calls == expected
            assert len(result.observation.batches) == expected
            assert result.observation.batches[-1].work.status == "completed"
            assert "work_recording_unavailable" in result.observation.batches[-1].errors
            if at_completion:
                # Original Goal acceptance is a separate authority; do not rewrite it.
                assert result.observation.status == "completed"
            await client.retry_settlement(control, submission.handle)
            assert adapter.calls == expected
        finally:
            await app.close()
    asyncio.run(scenario())


def test_goal_rejects_second_profile_and_retains_retired_member_until_owner_close(tmp_path):
    import gc
    import weakref

    from loushang.apphost.errors import AppHostError, AppHostFailureCategory
    from loushang.appserver.protocol import MuxMemberCloseV1
    from loushang.coding.hosted_application import CODING_HOSTED_APPLICATION_PROFILE_ID

    async def scenario():
        launch, config = task(tmp_path)
        adapter = CalculatorAdapter(config.workspace)
        app, scope, control, selector = await application(launch, replace(config, max_advances=1), adapter)
        try:
            client = scope.goal_client
            _, binding = await client._execution._resolve(control, client.service_instance_id)
            port = binding.port
            identities = await app._apphost._router.list_identities((launch.scopes[0].discovery_scope,), limit=16)
            assert len(identities) == 1
            with pytest.raises(AppHostError) as error:
                await app._apphost.attach_resume(product_id="coding", reference=identities[0].reference,
                                                profile_id=CODING_HOSTED_APPLICATION_PROFILE_ID)
            assert error.value.category is AppHostFailureCategory.PROFILE_UNAVAILABLE
            submission = await client.start(control, client.service_instance_id, "still-usable")
            result = await client.wait(control, submission.handle)
            assert result.observation.model_calls == 1
            assert result.observation.batches[0].work.session_id == port.identity.session_id
            assert len(list(launch.cwd_sessions.glob("*.jsonl"))) == 1
            goal = weakref.ref(port._goal)
            work = weakref.ref(port._goal._work)
            await scope.close_member(MuxMemberCloseV1(selector, control.member_id, close_session=False))
            with pytest.raises(AppServiceError):
                await client.query(control, submission.handle)
            assert goal() is not None and work() is not None
            assert (await port.query_goal(submission.handle.execution_id)).presence == "present"
        finally:
            await app.close()
        gc.collect()
        assert goal() is None and work() is None
    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["prepare", "startup"])
def test_failed_session_preparation_retries_retirement_without_reinitialization(tmp_path, monkeypatch, stage):
    async def scenario():
        launch, config = task(tmp_path)
        adapter = CalculatorAdapter(config.workspace)
        app, scope, control, _ = await application(launch, config, adapter)
        client = scope.goal_client
        _, binding = await client._execution._resolve(control, client.service_instance_id)
        session = binding.port._product_binding.control
        prepare = session.prepare_model_call_runtime if stage == "prepare" else session.start_extension_runtime
        dispose = session._dispose_session_runtime_profile
        preparations = retirements = 0
        fail = True

        async def preparing(*args, **kwargs):
            nonlocal preparations
            preparations += 1
            await prepare(*args, **kwargs)
            raise RuntimeError("injected prepared owner failure")

        async def retiring():
            nonlocal retirements
            retirements += 1
            if fail:
                raise RuntimeError("injected retained graph retirement debt")
            await dispose()

        monkeypatch.setattr(session, "prepare_model_call_runtime" if stage == "prepare" else "start_extension_runtime", preparing)
        monkeypatch.setattr(session, "_dispose_session_runtime_profile", retiring)
        try:
            submission = await client.start(control, client.service_instance_id, "preparation")
            with pytest.raises(AppServiceError):
                await client.wait(control, submission.handle)
            assert not session.execution_available
            assert preparations == retirements == 1
            snapshot = await client.query(control, submission.handle)
            assert snapshot.execution.state.status is ExecutionStatusV1.RUNNING
            assert snapshot.observation.presence == "unavailable"
            assert binding.port._product_binding._close_task is None
            fail = False
            result = await client.retry_settlement(control, submission.handle)
            assert result.execution.state.status is ExecutionStatusV1.FAILED
            assert preparations == 1 and retirements == 2 and adapter.calls == 0
        finally:
            fail = False
            await app.close()
    asyncio.run(scenario())
