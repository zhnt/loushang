from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, replace

import pytest

from loushang.appserver.protocol import (
    MuxAttachV1,
    MuxCreateV1,
    MuxMemberOpenV1,
    MuxSelectorV1,
    SessionOpenSpecV1,
    SessionScopeV1,
    SessionSnapshotRequestV1,
)
from loushang.appservice.execution_contract import ExecutionStatusV1
from loushang.coding.hosted_bootstrap import CodingHostedLaunchV1
from loushang.coding.hosted_goal_application import (
    CodingHostedRepositoryGoalV1,
    create_coding_repository_goal_application,
)
from loushang.harnesswork.goal import GoalError

from .test_hosted_execution import _private_home as _private_home
from .test_repository_goal import digest, implementation_adapter, model, task_package


@pytest.fixture(autouse=True)
def cleanup_adapter():
    from loushang.ai.api_registry import get_default_api_registry

    yield
    get_default_api_registry().unregister_api_adapters("repository-goal-offline")


async def approve(material):
    assert material["initial"]["target.py"] == "VALUE = 0\n"
    assert material["candidate"]["target.py"] == "VALUE = 1\n"
    assert material["verification"]["passed"]
    with pytest.raises(TypeError):
        material["identity"]["inventory"]["target.py"] = "forged"
    return dict(
        decision="approved",
        reason="Reviewed fixed value and unchanged scope",
        coverage=[f"RC-0{i}" for i in range(1, 7)],
        findings=[],
    )


def package(tmp_path, reviewer=approve, **budgets):
    task = task_package(tmp_path, initial="VALUE = 0\n")
    config = task.config
    temporary = tmp_path / "check-tmp"
    temporary.mkdir()
    config.update(
        temporary_root=str(temporary),
        closeout_budget=dict(version=1, work_intents=6, planning_intents=2),
    )
    # Deliberately path-shaped private Method identity must not escape public DTOs.
    method = task.path.parent / "method.json"
    descriptor = json.loads(method.read_text())
    descriptor["id"] = str(tmp_path / "private-method")
    method.write_text(json.dumps(descriptor))
    config["protected"]["method.json"] = digest(method.read_bytes())
    task.path.write_text(json.dumps(config))
    launch = CodingHostedLaunchV1(
        task.root,
        tmp_path / "application",
        "coding.repository-test",
        tmp_path / "cwd-sessions",
        tmp_path / "home-sessions",
    )
    hosted = CodingHostedRepositoryGoalV1(
        task.root,
        tmp_path / "goal-data",
        manifest=task.path,
        expected_sha256=digest(task.path.read_bytes()),
        reviewer_id="trusted-test",
        reviewer=reviewer,
        **budgets,
    )
    return launch, hosted, task


async def application(launch, config, adapter):
    app = await create_coding_repository_goal_application(
        launch, config, model=model(adapter)
    )
    try:
        scope = app.open_client_scope()
        mux = await scope.create_mux(MuxCreateV1("repository"))
        selector = MuxSelectorV1(mux_space_id=mux.mux_space_id)
        await scope.attach_mux(MuxAttachV1(selector))
        mux = await scope.open_member(
            MuxMemberOpenV1(
                selector,
                SessionOpenSpecV1(
                    product_id="coding",
                    continuity_id="repository",
                    scope=SessionScopeV1.CWD,
                    scope_fingerprint=launch.scopes[0].fingerprint,
                    title="Repository Goal",
                ),
            )
        )
        attached = await scope.attach_mux(MuxAttachV1(selector))
        control = SessionSnapshotRequestV1(
            attached.attachment_id,
            attached.controller_generation,
            mux.members[0].member_id,
        )
        return app, scope, control
    except BaseException:
        await app.close()
        raise


@pytest.mark.parametrize("inspect_first", [False, True])
def test_hosted_repository_real_session_tools_verification_review(
    tmp_path, inspect_first
):
    async def scenario():
        launch, config, task = package(tmp_path)
        adapter = implementation_adapter(
            task, "VALUE = 1\n", inspect_first=inspect_first
        )
        app, scope, control = await application(launch, config, adapter)
        try:
            client = scope.goal_client
            _, binding = await client._execution._resolve(
                control, client.service_instance_id
            )
            content = []
            binding.port.subscribe(content.append)
            binding.port.subscribe_execution_content(content.append)
            assert (
                await client.capability(control, client.service_instance_id)
            ).profile == "repository-closeout"
            submitted = await client.start(control, client.service_instance_id, "one")
            assert (
                await client.start(control, client.service_instance_id, "one")
            ).handle == submitted.handle
            result = await client.wait(control, submitted.handle)
            if result.execution.state.status is not ExecutionStatusV1.SUCCEEDED:
                _, binding = await client._execution._resolve(
                    control, client.service_instance_id
                )
                error = binding.port._invocation.task.exception()
                if error:
                    raise error
            assert result.execution.state.status is ExecutionStatusV1.SUCCEEDED, asdict(
                result
            )
            view = result.observation
            assert (view.goal_id, view.status, view.validity) == (
                "repository",
                "completed",
                "current",
            )
            assert len(view.batches) == view.advances == (6 if inspect_first else 4)
            assert view.model_calls == adapter.calls == (4 if inspect_first else 3)
            assert all(
                b.work.method_id is None and b.work.plan_id is None
                for b in view.batches
            )
            assert len({b.work.session_id for b in view.batches}) == 1
            assert all(
                b.work.status == "completed" and b.recording.require_persistence
                for b in view.batches
            )
            assert str(tmp_path) not in json.dumps(asdict(view))
            assert all(
                i["limits"]["work_intents"] == 6
                and i["limits"]["planning_intents"] == 2
                for i in adapter.inputs
            )
            _, binding = await client._execution._resolve(
                control, client.service_instance_id
            )
            owner = binding.port._goal
            assert owner._sdk is None
            assert not content
            assert not (await scope.snapshot_session(control)).records
            execution_snapshot = await binding.port.snapshot_execution()
            assert (
                not execution_snapshot.source.records and not execution_snapshot.draft
            )
            assert (
                owner.planning_trace("repository")["batches"][-1]["phase"] == "review"
            )
        finally:
            await app.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "fault",
    [
        "budget",
        "protected",
        "inspect",
        "initial",
        "symlink",
        "hardlink",
        "roots",
        "interpreter",
        "inspect_groups",
        "selectors",
        "group_shape",
        "ancestor",
    ],
)
def test_reject_task_before_app_resources(tmp_path, fault):
    launch, config, task = package(tmp_path)
    values = json.loads(task.path.read_bytes())
    if fault == "inspect_groups":
        values["inspect_files"] = {}
    elif fault == "selectors":
        values["check_selectors"] = {}
    elif fault == "group_shape":
        values["inspect_files"]["reader"] = "target.py"
    elif fault == "ancestor":
        (task.root / "alias").symlink_to(task.root, target_is_directory=True)
        values["allowed_files"] = ["alias/target.py"]
        values["read_files"] = ["alias/target.py"]
        values["inspect_files"] = {
            k: ["alias/target.py"] for k in values["inspect_files"]
        }
        values["workspace_start"]["alias/target.py"] = values["workspace_start"][
            "target.py"
        ]
    elif fault == "budget":
        values.pop("closeout_budget")
    elif fault == "protected":
        values["protected"].pop("driver.py")
    elif fault == "inspect":
        values["inspect_files"]["reader"] = ["secret.py"]
    elif fault == "initial":
        (task.root / "target.py").write_text("VALUE = 2\n")
    elif fault == "symlink":
        target = task.root / "target.py"
        target.unlink()
        target.symlink_to(task.path)
    elif fault == "hardlink":
        (tmp_path / "alias").hardlink_to(task.root / "target.py")
    elif fault == "roots":
        values["temporary_root"] = str(tmp_path)
    elif fault == "interpreter":
        values["python"] = "/untrusted/python"
    task.path.write_text(json.dumps(values))
    config = replace(config, expected_sha256=digest(task.path.read_bytes()))
    with pytest.raises((ValueError, GoalError)):
        config.prepare(launch)


@pytest.mark.parametrize(
    "decision",
    ["rejected", "exception", "timeout", "identity", "coverage", "changed", "oversize"],
)
def test_review_failure_cannot_approve(tmp_path, decision):
    async def scenario():
        calls = 0

        async def reviewer(material):
            nonlocal calls
            calls += 1
            if decision == "timeout":
                raise TimeoutError("reviewer calculation failed")
            if decision == "exception":
                raise RuntimeError("private reason")
            result = await approve(material)
            if decision == "rejected":
                result.update(
                    decision="rejected",
                    findings=[
                        dict(
                            requirement_id="RC-01",
                            evidence="candidate value",
                            expected="independently required behavior",
                            actual="not accepted by reviewer",
                        )
                    ],
                )
            elif decision == "oversize":
                result["reason"] = "x" * (33 * 1024)
            elif decision == "identity":
                result["reviewer"] = "forged"
            elif decision == "coverage":
                result["coverage"] = ["RC-01"]
            elif decision == "changed":
                (task.root / "target.py").write_text("VALUE = 2\n")
            return result

        launch, config, task = package(tmp_path, reviewer)
        app, scope, control = await application(
            launch, config, implementation_adapter(task, "VALUE = 1\n")
        )
        try:
            client = scope.goal_client
            submitted = await client.start(control, client.service_instance_id, "one")
            result = await client.wait(control, submitted.handle)
            assert result.execution.state.status is ExecutionStatusV1.FAILED
            assert result.observation.status != "completed"
            assert len(result.observation.batches) == (
                4 if decision == "rejected" else 3
            )
            assert result.observation.reason_code == (
                "review_rejected"
                if decision == "rejected"
                else "task_changed"
                if decision == "changed"
                else "review_unavailable"
            )
            assert calls == 1
            assert "private reason" not in json.dumps(asdict(result))
        finally:
            await app.close()

    asyncio.run(scenario())


def test_cancelled_reviewer_late_return_is_discarded(tmp_path):
    async def scenario():
        entered = asyncio.Event()
        calls = 0

        async def reviewer(material):
            nonlocal calls
            calls += 1
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return await approve(material)

        launch, config, task = package(tmp_path, reviewer)
        app, scope, control = await application(
            launch, config, implementation_adapter(task, "VALUE = 1\n")
        )
        try:
            client = scope.goal_client
            submitted = await client.start(control, client.service_instance_id, "one")
            await asyncio.wait_for(entered.wait(), 20)
            await client.interrupt(control, submitted.handle)
            result = await client.wait(control, submitted.handle)
            assert result.execution.state.status is not ExecutionStatusV1.SUCCEEDED
            assert len(result.observation.batches) == 3
            assert calls == 1
        finally:
            await app.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["verification", "review"])
def test_recording_unknown_blocks_success_and_next_command(
    tmp_path, monkeypatch, stage
):
    from loushang.harnesswork.recording import _RecordingObserver

    original = _RecordingObserver.observe
    completed = 0

    def observe(self, entry, **kwargs):
        nonlocal completed
        original(self, entry, **kwargs)
        if entry.payload.get("kind") == "WorkRunCompleted":
            completed += 1
        if completed == (3 if stage == "verification" else 4):
            raise RuntimeError("confirmation failed after persistence")

    monkeypatch.setattr(_RecordingObserver, "observe", observe)

    async def scenario():
        calls = 0

        async def reviewer(material):
            nonlocal calls
            calls += 1
            return await approve(material)

        launch, config, task = package(tmp_path, reviewer)
        adapter = implementation_adapter(task, "VALUE = 1\n")
        app, scope, control = await application(launch, config, adapter)
        try:
            client = scope.goal_client
            submitted = await client.start(
                control, client.service_instance_id, "unknown"
            )
            result = await client.wait(control, submitted.handle)
            assert result.execution.state.status is ExecutionStatusV1.FAILED
            assert result.observation.reason_code == "work_recording_unavailable"
            assert result.observation.validity == "unknown"
            assert len(result.observation.batches) == (
                3 if stage == "verification" else 4
            )
            assert calls == (0 if stage == "verification" else 1)
            count = adapter.calls
            await client.retry_settlement(control, submitted.handle)
            assert adapter.calls == count
        finally:
            await app.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("initialization", [False, True])
def test_repository_cleanup_retry_does_not_restart_business(
    tmp_path, monkeypatch, initialization
):
    from loushang.appserver.protocol import AppServiceError
    from loushang.coding.adapters.goal import CodingGoal

    async def scenario():
        launch, config, task = package(tmp_path, max_advances=1)
        adapter = implementation_adapter(task, "VALUE = 1\n")
        app, scope, control = await application(launch, config, adapter)
        client = scope.goal_client
        _, binding = await client._execution._resolve(
            control, client.service_instance_id
        )
        owner = binding.port._goal
        session = binding.port._product_binding.control
        fail = True
        if initialization:
            original = CodingGoal.close

            def create(self, *args, **kwargs):
                raise RuntimeError("injected after acquisition")

            async def close(self):
                if fail:
                    raise RuntimeError("retained Goal debt")
                await original(self)

            monkeypatch.setattr(CodingGoal, "create", create)
            monkeypatch.setattr(CodingGoal, "close", close)
        else:
            original = session.settle_execution

            async def settle(*, interrupted=False):
                if fail:
                    raise RuntimeError("retained Session debt")
                await original(interrupted=interrupted)

            monkeypatch.setattr(session, "settle_execution", settle)
        try:
            submitted = await client.start(
                control, client.service_instance_id, "cleanup"
            )
            with pytest.raises(AppServiceError):
                await client.wait(control, submitted.handle)
            assert binding.port._goal is owner and owner._sdk is None
            count = adapter.calls
            fail = False
            result = await client.retry_settlement(control, submitted.handle)
            assert result.execution.state.status is ExecutionStatusV1.FAILED
            assert adapter.calls == count
        finally:
            fail = False
            await app.close()

    asyncio.run(scenario())


def test_review_return_after_absolute_deadline_does_not_admit_work(
    tmp_path, monkeypatch
):
    import time
    from types import SimpleNamespace

    from loushang.coding import _hosted_goal_work

    clock = time.monotonic()
    monkeypatch.setattr(
        _hosted_goal_work, "time", SimpleNamespace(monotonic=lambda: clock)
    )

    async def scenario():
        async def reviewer(material):
            nonlocal clock
            result = await approve(material)
            clock += 121
            return result

        launch, config, task = package(tmp_path, reviewer)
        app, scope, control = await application(
            launch, config, implementation_adapter(task, "VALUE = 1\n")
        )
        try:
            client = scope.goal_client
            submitted = await client.start(
                control, client.service_instance_id, "deadline"
            )
            result = await client.wait(control, submitted.handle)
            assert result.execution.state.status is ExecutionStatusV1.FAILED
            assert result.observation.reason_code == "goal_deadline_exceeded"
            assert len(result.observation.batches) == 3
        finally:
            await app.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("budget,expected", [("work", 1), ("model", 2)])
def test_insufficient_budget_stops_without_review(tmp_path, budget, expected):
    async def scenario():
        async def no_review(material):
            raise AssertionError("no review without verification")

        values = {"max_advances": 1} if budget == "work" else {"max_model_calls": 1}
        launch, config, task = package(tmp_path, no_review, **values)
        adapter = implementation_adapter(task, "VALUE = 1\n")
        app, scope, control = await application(launch, config, adapter)
        try:
            client = scope.goal_client
            submitted = await client.start(
                control, client.service_instance_id, "budget"
            )
            result = await client.wait(control, submitted.handle)
            assert result.execution.state.status is ExecutionStatusV1.FAILED
            assert len(result.observation.batches) <= expected
            assert adapter.calls == 1
        finally:
            await app.close()

    asyncio.run(scenario())


def test_frozen_task_config_and_checked_read_boundary(tmp_path):
    launch, config, _ = package(tmp_path)
    task = config.prepare(launch).task
    task.config["read_files"].append("secret")
    task.config["closeout_budget"]["work_intents"] = 20
    assert task.config["read_files"] == ["target.py"]
    assert task.config["closeout_budget"]["work_intents"] == 6
    before = task.snapshot()
    (task.root / "target.py").write_text("VALUE = 2\n")
    with pytest.raises(GoalError, match="material changed"):
        task.read_files(task.allowed, before)
    assert task.material()["files"]["target.py"] == "VALUE = 2\n"
    with pytest.raises(GoalError, match="outside read"):
        task.read_files(["secret"], task.snapshot())
    task.path.write_text("{}")
    with pytest.raises(GoalError, match="manifest changed"):
        task.material()


def test_cancellation_during_original_review_work(tmp_path, monkeypatch):
    from loushang.coding.adapters._goal_repository_review import ReviewWork

    async def scenario():
        entered = asyncio.Event()
        calls = 0

        async def execute(self, operation, context):
            nonlocal calls
            calls += 1
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(ReviewWork, "execute", execute)
        launch, config, task = package(tmp_path)
        app, scope, control = await application(
            launch, config, implementation_adapter(task, "VALUE = 1\n")
        )
        try:
            client = scope.goal_client
            submitted = await client.start(
                control, client.service_instance_id, "cancel-review"
            )
            await asyncio.wait_for(entered.wait(), 20)
            await client.interrupt(control, submitted.handle)
            result = await client.wait(control, submitted.handle)
            assert result.execution.state.status is not ExecutionStatusV1.SUCCEEDED
            assert result.observation.status != "completed"
            assert len(result.observation.batches) == 4
            assert result.observation.batches[-1].work.status == "cancelled"
            await client.retry_settlement(control, submitted.handle)
            assert calls == 1
        finally:
            await app.close()

    asyncio.run(scenario())


def test_task_manifest_digest_before_following_members(tmp_path):
    launch, config, task = package(tmp_path)
    bad = json.loads(task.path.read_bytes())
    bad["protected"] = {"../../must-not-read": "not-a-hash"}
    task.path.write_text(json.dumps(bad))
    with pytest.raises(GoalError, match="manifest changed"):
        config.prepare(launch)


def test_review_request_material_size_bound(tmp_path):
    from types import SimpleNamespace

    from loushang.coding._hosted_repository_work import review_material

    launch, config, _ = package(tmp_path)
    task = config.prepare(launch).task
    # Trusted verified data above the delivery limit must not be truncated and
    # delivered as if it were a complete review request.
    identity = {
        "inventory": task.snapshot(),
        "verification_operation_id": "op",
        "verification_run_id": "run",
    }
    owner = SimpleNamespace(
        _profile=SimpleNamespace(task=task),
        review_basis=lambda goal: (identity, True),
        controller=SimpleNamespace(
            history=SimpleNamespace(batches=[SimpleNamespace(operation_id="op")])
        ),
        _work=SimpleNamespace(
            get_run_for_operation=lambda op: SimpleNamespace(run_id="run")
        ),
        _policy=SimpleNamespace(
            _verification=lambda batch, run: {
                "passed": True,
                "detail": "x" * (4 * 1024 * 1024),
            }
        ),
    )
    with pytest.raises(ValueError, match="exceeds limit"):
        review_material(owner, "repository")


def test_unknown_repository_step_is_not_echoed():
    from loushang.appserver.method_work import (
        MethodWorkObservationV1,
        WorkRunObservationV1,
        WorkStepObservationV1,
    )
    from loushang.coding.hosted_goal import _repository_observation

    work = WorkRunObservationV1(
        "op",
        "run",
        "session",
        "/private/method",
        "/private/plan",
        "running",
        "/private/step",
        (WorkStepObservationV1("/private/step", "running"),),
    )
    original = MethodWorkObservationV1("present", work)
    result = _repository_observation(original)
    assert "/private" not in json.dumps(asdict(result))
    assert result.work.operation_id == "op" and result.work.run_id == "run"
    assert result.errors == ("work_plan_unavailable",)
    assert original.work.current_step_id == "/private/step"


def test_repository_detach_and_cross_await_revocation(tmp_path, monkeypatch):
    from loushang.appserver.protocol import AppServiceError

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def reviewer(material):
            entered.set()
            await release.wait()
            return await approve(material)

        launch, config, task = package(tmp_path, reviewer)
        app, scope, control = await application(
            launch, config, implementation_adapter(task, "VALUE = 1\n")
        )
        try:
            client = scope.goal_client
            submitted = await client.start(
                control, client.service_instance_id, "detach"
            )
            await asyncio.wait_for(entered.wait(), 20)
            _, binding = await client._execution._resolve(
                control, client.service_instance_id
            )
            port = binding.port
            original = port._goal.query
            reading, deliver = asyncio.Event(), asyncio.Event()

            async def query(goal_id):
                reading.set()
                await deliver.wait()
                return await original(goal_id)

            monkeypatch.setattr(port._goal, "query", query)
            pending = asyncio.create_task(client.query(control, submitted.handle))
            await reading.wait()
            await scope.close()
            deliver.set()
            with pytest.raises(AppServiceError):
                await pending
            assert not port._invocation.task.done()
            release.set()
            # The same owner finishes after client detach. No business restart.
            outcome = await port.wait_execution(submitted.handle.execution_id)
            assert outcome.status is ExecutionStatusV1.SUCCEEDED
            assert (
                await port.query_goal(submitted.handle.execution_id)
            ).status == "completed"
            with pytest.raises(AppServiceError):
                await client.query(control, submitted.handle)
        finally:
            release.set()
            await app.close()

    asyncio.run(scenario())
