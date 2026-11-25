"""The real Managed Coding binding borrows its original Session for Goal Work."""
from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.ai.api_registry import get_default_api_registry
from loushang.apphost.errors import CleanupIncompleteError
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    MuxAttachV1,
    MuxCreateV1,
    MuxMemberOpenV1,
    MuxSelectorV1,
    SessionOpenSpecV1,
    SessionSnapshotRequestV1,
    WorkspaceRequestV1,
)
from loushang.appservice.execution_contract import ExecutionRequestV1, ExecutionStatusV1
from loushang.coding.adapters.goal import GoalConstructionError
from loushang.coding.adapters.interactive_goal import InteractiveGoal
from loushang.coding.hosted.execution import CodingHostedExecutionSessionV1
from loushang.coding.hosted.managed.bootstrap import (
    CodingManagedApplicationLaunchV1,
    create_coding_managed_attempt,
)
from loushang.coding.hosted.resume import CodingDeferredHostedSessionV1
from loushang.coding.hosted.session import CodingHostedHistoryBindingV1
from loushang.harness.events.session import ToolPolicyAuditEvent
from loushang.harnesswork.goal import GoalError
from loushang.harnesswork.integrations.goal_run import run_goal

from .test_current_session_goal import _model
from .test_hosted_execution import _binding
from .test_hosted_execution import _private_home as _private_home
from .test_interactive_goal import TaskAdapter


@pytest.fixture
def tmp_path(standalone_workspace: Path) -> Path:
    return standalone_workspace


class _HostedTaskAdapter(TaskAdapter):
    def __init__(self, workspace):
        super().__init__(workspace, "note.txt")
        self.goal_mode = False
        self.chat_calls = 0

    async def invoke_prepared_raw(self, request, prepared):
        if self.goal_mode:
            async for event in super().invoke_prepared_raw(request, prepared):
                yield event
            return
        prepared.payload_for_transport()
        self.chat_calls += 1
        yield {"type": "response_start", "response_id": f"chat-{self.chat_calls}"}
        yield {"type": "text_delta", "text": "Ordinary hosted reply"}
        yield {"type": "stop_reason", "stop_reason": "stop"}
        yield {"type": "response_done"}


async def _chat(client, address, submission_id):
    execution = client.execution_client
    instance = execution.service_instance_id
    record = await execution.submit_execution(address, instance, submission_id, "Ordinary chat")
    async with asyncio.timeout(10):
        while True:
            observed = await execution.get_execution(address, instance, record.state.execution_id)
            if observed.state.status.terminal:
                assert observed.state.status is ExecutionStatusV1.SUCCEEDED
                return
            await asyncio.sleep(0.01)


@asynccontextmanager
async def _managed(tmp_path, *, blocked=False):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    if blocked:
        settings = workspace / ".loushang/settings.json"
        settings.parent.mkdir()
        settings.write_text(json.dumps({"tools": {"blocked_tools": ["write"]}}))
    adapter = _HostedTaskAdapter(workspace)
    registry = get_default_api_registry()
    registry.register_api_adapter(adapter, source_id=adapter.api)
    launch = CodingManagedApplicationLaunchV1(
        workspace, tmp_path / "app-manifest", "coding.dynamic-goal", tmp_path / "transcripts",
    )
    attempt = create_coding_managed_attempt(launch, model=replace(_model(), api=adapter.api))
    try:
        app = await attempt.open()
        app.enable_client_scopes()
        client = app.open_client_scope()
        registered = await client.workspace(WorkspaceRequestV1("register", str(workspace)))
        selected, = registered.workspaces
        selector = MuxSelectorV1(name="dynamic-goal")
        await client.create_mux(MuxCreateV1("dynamic-goal"))
        await client.attach_mux(MuxAttachV1(selector))
        mux = await client.open_member(MuxMemberOpenV1(
            selector, SessionOpenSpecV1("coding", "target", selected.scope, selected.scope_fingerprint, "Goal test"),
        ))
        member, = mux.members
        attachment = await client.attach_mux(MuxAttachV1(selector))
        address = SessionSnapshotRequestV1(
            attachment.attachment_id, attachment.controller_generation, member.member_id,
        )
        hosted = (await client._session(
            address.attachment_id, address.controller_generation, address.member_id,
        ))._port
        assert type(hosted) is CodingHostedExecutionSessionV1
        approval = hosted._product_binding._approval

        async def approve_attached_directory_action(request):
            action_id = request["action_id"]
            assert isinstance(action_id, str)
            assert await approval.handle_result(action_id, outcome="allow_once")

        approval.set_request_presenter(approve_attached_directory_action)
        yield app, client, selector, address, hosted, adapter, member.session.session_id
    finally:
        try:
            await attempt.close()
        finally:
            registry.unregister_api_adapters(adapter.api)


async def _activate(client, address, hosted, adapter):
    await _chat(client, address, "prepare-chat")
    await hosted._product_binding.wait_for_title()
    assert {"read", "edit", "write"} <= set(hosted._product_binding.control.get_active_tool_names())
    adapter.goal_mode = True


@pytest.mark.skipif(sys.platform != "linux", reason="Managed-owned transcript fixture")
@pytest.mark.parametrize("blocked", [False, True], ids=["write", "policy-denial"])
def test_managed_goal_uses_original_session_and_tool_policy(tmp_path, blocked, monkeypatch):
    async def scenario():
        async with _managed(tmp_path, blocked=blocked) as (app, client, selector, address, hosted, adapter, session_id):
            binding = hosted._product_binding
            session = binding.control
            assert session.session_id == session_id
            file = session.session_manager.get_session_file()
            assert file is not None
            assert session.work_execution_backend is None
            with pytest.raises(GoalError, match="requires original file tools"):
                await binding.create_interactive_goal("Unavailable before original file tools are published")
            assert binding._goal._interactive_goal_owner is None
            if not blocked:
                hosted.start_execution(ExecutionRequestV1("pending-chat", "Prepare original tools"))
                with pytest.raises(GoalError, match="busy"):
                    await binding.create_interactive_goal("Conflicting target")
                assert (await hosted.wait_execution("pending-chat")).status is ExecutionStatusV1.SUCCEEDED
            await _activate(client, address, hosted, adapter)
            initial_calls = adapter.chat_calls
            with monkeypatch.context() as patch:
                patch.setattr(session.session_manager, "get_cwd", lambda: str(tmp_path / "other"))
                with pytest.raises(GoalError, match="Hosted Session and Workspace"):
                    await binding.create_interactive_goal("Wrong workspace")

            created, duplicate = await asyncio.gather(
                binding.create_interactive_goal("Write a greeting in note.txt"),
                binding.create_interactive_goal("Another concurrent target"),
                return_exceptions=True,
            )
            assert isinstance(duplicate, GoalError) and "already" in str(duplicate)
            assert adapter.calls == 0 and adapter.chat_calls == initial_calls
            assert created == binding.interactive_goal_status()
            assert created.status == "active" and created.revision == created.epoch == 1
            assert not created.execution_unresolved
            owner = binding._goal._interactive_goal_owner
            assert owner._session is session and owner._sdk is None
            assert owner.controller.header.session_id == session.session_id
            assert owner.controller.query(created.goal_id).requirements[0].text == "Write a greeting in note.txt"
            contract = owner.controller.query(created.goal_id).metadata["task_contract"]
            assert list(contract["checks"]) == [] and contract["method"] is None and contract["max_model_calls"] == 8
            with pytest.raises(GoalError, match="already"):
                await binding.create_interactive_goal("Another target")
            assert binding._goal._interactive_goal_owner is owner

            await client.close()
            backend = session.work_execution_backend
            events = []
            remove = session.subscribe_runtime_events(events.append)
            try:
                await run_goal(owner, created.goal_id, steps=2)
            finally:
                remove()
            assert backend is session.work_execution_backend
            assert owner._work is backend.work_runtime
            assert session.runtime.execution_scope is owner._scope
            runs = owner.controller.facts().runs
            assert len(runs) == 2 and {run.session_id for run in runs} == {session.session_id}
            assert owner.controller.history.batches[-1].source["phase"] == "repair"
            assert adapter.wrote and adapter.calls >= 2
            note = adapter.workspace / "note.txt"
            if blocked:
                assert not note.exists()
                assert any(
                    isinstance(event.payload, ToolPolicyAuditEvent)
                    and event.payload.details.get("policy_code") == "tool_blocked"
                    for event in events
                )
            else:
                assert note.read_text() == "hello\n"
            await binding.close_interactive_goal()
            assert owner._closed and owner._scope.closed
            assert binding.interactive_goal_status() is None
            assert not session.runtime.execution_admission.closed
            assert session.runtime.execution_scope is None
            assert session.session_manager.get_session_file() == file

            client = app.open_client_scope()
            attached = await client.attach_mux(MuxAttachV1(selector))
            address = replace(address, attachment_id=attached.attachment_id, controller_generation=attached.controller_generation)
            adapter.goal_mode = False
            await _chat(client, address, "after-goal")
            assert session.session_id == session_id
            assert [path for path in file.parent.glob("*.jsonl") if ".goal." not in path.name] == [file]
            with pytest.raises(GoalError, match="already has Goal history"):
                await binding.create_interactive_goal("Recovered goal remains historical")
            assert session.work_execution_backend is backend and session.runtime.execution_scope is None
    asyncio.run(asyncio.wait_for(scenario(), 40))


@pytest.mark.skipif(sys.platform != "linux", reason="Managed-owned transcript fixture")
@pytest.mark.parametrize("failure", ["attach", "create"])
def test_failed_goal_construction_keeps_cleanup_owner(tmp_path, monkeypatch, failure):
    async def scenario():
        async with _managed(tmp_path) as (_, client, _, address, hosted, adapter, _):
            await _activate(client, address, hosted, adapter)
            binding = hosted._product_binding
            session = binding.control
            close = InteractiveGoal.close
            broken = True

            async def fail_construction(*args, **kwargs):
                raise GoalError("construction failed")

            async def close_with_failure(owner):
                if broken:
                    raise OSError("Goal cleanup failed")
                await close(owner)

            monkeypatch.setattr(InteractiveGoal, "close", close_with_failure)
            if failure == "attach":
                monkeypatch.setattr(InteractiveGoal, "_assemble_session", fail_construction)
            else:
                monkeypatch.setattr(InteractiveGoal, "create_task", fail_construction)
            try:
                with pytest.raises(GoalConstructionError) as error:
                    await binding.create_interactive_goal("Target")
                owner = error.value.owner
                assert binding._goal._interactive_goal_owner is owner
                with pytest.raises(GoalError, match="cleanup is pending"):
                    binding.interactive_goal_status()
                execution = client.execution_client
                instance = execution.service_instance_id
                pending = await execution.interactive_goal_status(address, instance)
                assert pending.availability == "cleanup_pending" and pending.goal_id is None
                assert await execution.create_interactive_goal(address, instance, "Retry") == pending
                with pytest.raises(GoalError, match="already"):
                    await binding.create_interactive_goal("Second attempt")
                with pytest.raises(CleanupIncompleteError) as incomplete:
                    await hosted.close()
                assert incomplete.value.cleanup_debt_count >= 1
                assert binding._goal._interactive_goal_owner is owner
                assert not session.runtime.execution_admission.closed
            finally:
                broken = False
            await hosted.close()
            assert binding._goal._interactive_goal_owner is None
            assert owner._closed and owner._scope.closed
            assert session.runtime.execution_admission.closed

    asyncio.run(asyncio.wait_for(scenario(), 40))


@pytest.mark.skipif(sys.platform != "linux", reason="Managed-owned transcript fixture")
def test_closing_parent_fences_goal_creation_before_publication(tmp_path, monkeypatch):
    from loushang.coding.adapters.interactive_goal import _Domain

    async def scenario():
        async with _managed(tmp_path) as (_, client, _, address, hosted, adapter, _):
            await _activate(client, address, hosted, adapter)
            binding = hosted._product_binding
            entered, resume = asyncio.Event(), asyncio.Event()
            refresh = _Domain.refresh

            async def pause_refresh(policy):
                entered.set()
                await resume.wait()
                await refresh(policy)

            monkeypatch.setattr(_Domain, "refresh", pause_refresh)
            creation = asyncio.create_task(binding.create_interactive_goal("Unpublished target"))
            try:
                await asyncio.wait_for(entered.wait(), 10)
                owner = binding._goal._interactive_goal_owner
                closing = asyncio.create_task(hosted.close())
                await asyncio.sleep(0)
                assert not closing.done()
            finally:
                resume.set()
            with pytest.raises(GoalError, match="closing|unavailable"):
                await creation
            await closing
            assert not owner.controller.history.goals
            assert owner._closed and not adapter.calls
            assert binding._goal._interactive_goal_owner is None

    asyncio.run(asyncio.wait_for(scenario(), 40))


@pytest.mark.skipif(sys.platform != "linux", reason="Managed-owned transcript fixture")
def test_parent_close_joins_active_goal_work(tmp_path):
    async def scenario():
        async with _managed(tmp_path) as (_, client, _, address, hosted, adapter, _):
            await _activate(client, address, hosted, adapter)
            binding = hosted._product_binding
            session = binding.control
            created = await binding.create_interactive_goal("Target")
            owner = binding._goal._interactive_goal_owner
            adapter.blocked = True
            running = asyncio.create_task(run_goal(owner, created.goal_id, steps=2))
            try:
                await asyncio.wait_for(adapter.entered.wait(), 10)
                assert session.runtime.execution_admission.execution_reserved
                with pytest.raises(AppServiceError) as busy:
                    hosted.start_execution(ExecutionRequestV1("busy", "Ordinary chat"))
                assert busy.value.code is AppErrorCodeV1.SESSION_UNAVAILABLE
                await hosted.close()
                assert running.done()
                assert binding._goal._interactive_goal_owner is None
                assert owner._closed and owner._scope.closed
                assert session.runtime.execution_admission.closed
                assert session.work_execution_backend is None
                assert not (adapter.workspace / "note.txt").exists()
            finally:
                adapter.release.set()
                await asyncio.gather(running, return_exceptions=True)

    asyncio.run(asyncio.wait_for(scenario(), 40))


def test_interactive_goal_requires_the_real_persistent_binding(tmp_path):
    async def scenario():
        binding, session = await _binding(tmp_path)
        try:
            with pytest.raises(GoalError, match="persistent Transcript"):
                await binding.create_interactive_goal("Transient target")
            assert session.work_execution_backend is None and session.runtime.execution_scope is None
        finally:
            await binding.close()

    asyncio.run(scenario())
    assert not hasattr(CodingDeferredHostedSessionV1, "create_interactive_goal")
    assert not hasattr(CodingHostedHistoryBindingV1, "create_interactive_goal")


@pytest.mark.skipif(sys.platform != "linux", reason="Managed-owned transcript fixture")
def test_scoped_goal_create_rechecks_controller_at_journal_publication(tmp_path, monkeypatch):
    from loushang.appserver.execution.dispatch import dispatch_execution
    from loushang.appserver.execution.model import ExecutionCallV1, ExecutionOperationV1
    from loushang.coding.adapters.interactive_goal import _Domain

    async def scenario():
        async with _managed(tmp_path) as (app, client, selector, address, hosted, adapter, session_id):
            execution = client.execution_client
            instance = execution.service_instance_id

            async def status(port=execution, control=address):
                return await dispatch_execution(port, ExecutionCallV1(
                    "1", ExecutionOperationV1.INTERACTIVE_GOAL_STATUS, control, instance,
                ))

            async def create(port=execution, control=address, target="Write a small greeting"):
                return await dispatch_execution(port, ExecutionCallV1(
                    "2", ExecutionOperationV1.INTERACTIVE_GOAL_CREATE, control, instance, goal_target=target,
                ))

            assert (await execution.snapshot_execution_session(address, instance)).supports_interactive_goal
            assert (await status()).availability == "not_ready"
            await _activate(client, address, hosted, adapter)
            assert (await status()).availability == "ready"
            entered, release = asyncio.Event(), asyncio.Event()
            original = _Domain.refresh

            async def blocked_refresh(policy):
                entered.set()
                await release.wait()
                await original(policy)

            with monkeypatch.context() as patch:
                patch.setattr(_Domain, "refresh", blocked_refresh)
                pending = asyncio.create_task(create())
                try:
                    await asyncio.wait_for(entered.wait(), 10)
                    assert (await status()).availability == "creating"
                    assert (await create()).availability == "creating"
                    old_owner = hosted._product_binding._goal._interactive_goal_owner
                    await client.close()
                    second = app.open_client_scope()
                    attached = await second.attach_mux(MuxAttachV1(selector))
                    address2 = replace(address, attachment_id=attached.attachment_id,
                                       controller_generation=attached.controller_generation)
                finally:
                    release.set()
                with pytest.raises(AppServiceError) as revoked:
                    await pending
                assert revoked.value.code in {AppErrorCodeV1.STALE_ATTACHMENT, AppErrorCodeV1.SERVICE_CLOSED}
                assert not old_owner.controller.history.goals
            assert (await status(second.execution_client, address2)).availability == "ready"
            created = await create(second.execution_client, address2)
            owner = hosted._product_binding._goal._interactive_goal_owner
            assert created.availability == "present"
            assert owner.session_id == session_id
            state = owner.controller.query(created.goal_id)
            assert (created.status, created.revision, created.epoch) == (state.status, state.revision, state.epoch)
            assert (await status(second.execution_client, address2)) == created
            assert not owner.controller.history.batches and adapter.calls == 0
            assert await create(second.execution_client, address2, "Other target") == created
            assert len(owner.controller.history.goals) == 1

            await hosted._product_binding.close_interactive_goal()
            assert (await status(second.execution_client, address2)).availability == "historical"

    asyncio.run(asyncio.wait_for(scenario(), 45))


@pytest.mark.skipif(sys.platform != "linux", reason="Managed-owned transcript fixture")
def test_hosted_goal_commands_keep_the_original_run_after_client_disconnect(tmp_path, monkeypatch):
    from loushang.appserver.execution.dispatch import dispatch_execution
    from loushang.appserver.execution.model import (
        ExecutionCallV1,
        ExecutionOperationV1,
        ExecutionServiceErrorV1,
        InteractiveGoalCommandV1,
    )

    async def scenario():
        async with _managed(tmp_path) as (app, client, selector, address, hosted, adapter, _):
            await _activate(client, address, hosted, adapter)
            port = client.execution_client
            instance = port.service_instance_id
            created = await port.create_interactive_goal(address, instance, "Write a greeting in note.txt")
            goal_id = created.goal_id
            owner = hosted._product_binding._goal._interactive_goal_owner

            async def control(action, command_id=None):
                return await dispatch_execution(port, ExecutionCallV1(
                    "1", ExecutionOperationV1.INTERACTIVE_GOAL_COMMAND, address, instance,
                    goal_command=InteractiveGoalCommandV1(goal_id, command_id or action, action),
                ))

            step = InteractiveGoalCommandV1(goal_id, "step", "step")
            with pytest.raises(AppServiceError):
                await port.control_interactive_goal(address, instance, replace(step, goal_id="other-goal"))
            with pytest.raises(AppServiceError):
                await port.control_interactive_goal(replace(address, member_id="other-session"), instance, step)
            with pytest.raises(ExecutionServiceErrorV1):
                await port.control_interactive_goal(address, "other-host", step)
            assert not owner.controller.history.batches

            async def settled(command_id):
                async with asyncio.timeout(15):
                    while True:
                        view = await port.interactive_goal_status(address, instance)
                        assert view.command.command_id == command_id
                        if view.command.status not in {"running", "settling"}:
                            return view
                        await asyncio.sleep(0.01)

            assert (await port.snapshot_execution_session(address, instance)).supports_interactive_goal_commands
            accepted = await control("step")
            assert accepted.command.status == "running"
            assert (await settled("step")).command.status == "finished"
            assert len(owner.controller.history.batches) == 1
            assert (await control("step")).command.status == "finished"
            assert len(owner.controller.history.batches) == 1

            adapter.entered.clear()
            adapter.blocked = True
            assert (await control("run")).command.status == "running"
            await asyncio.wait_for(adapter.entered.wait(), 10)
            with pytest.raises(AppServiceError):
                await control("step", "while-running")
            with pytest.raises(AppServiceError):
                await control("run", "step")
            with pytest.raises(AppServiceError) as conflict:
                await port.submit_execution(address, instance, "busy-chat", "Keep this input")
            assert conflict.value.code is AppErrorCodeV1.SESSION_UNAVAILABLE

            previous_port, previous_address = port, address
            await client.close()
            second = app.open_client_scope()
            attached = await second.attach_mux(MuxAttachV1(selector))
            with pytest.raises(AppServiceError):
                await previous_port.control_interactive_goal(
                    previous_address, instance, InteractiveGoalCommandV1(goal_id, "stale-pause", "pause"),
                )
            address = replace(address, attachment_id=attached.attachment_id, controller_generation=attached.controller_generation)
            port = second.execution_client
            observed = await port.interactive_goal_status(address, instance)
            assert observed.goal_id == goal_id and observed.command.command_id == "run"
            assert observed.command.status == "running"
            paused = await control("pause")
            assert (paused.status, paused.command.status) == ("paused", "settling")
            assert owner.controller.facts().busy
            with pytest.raises(AppServiceError):
                await control("resume", "early-resume")

            adapter.release.set()
            assert (await settled("pause")).status == "paused"
            assert len(owner.controller.history.batches) == 2
            assert not owner.controller.facts().busy

            adapter.release.clear()
            adapter.entered.clear()
            resumed = await control("resume")
            assert (resumed.goal_id, resumed.status) == (goal_id, "active")
            await asyncio.wait_for(adapter.entered.wait(), 10)
            cancelled = await control("cancel")
            assert cancelled.command.status == "settling"
            final = await settled("cancel")
            assert final.status == "paused" and final.command.status == "finished"
            assert not final.execution_unresolved and not owner.controller.facts().busy
            count = len(owner.controller.history.batches)
            assert count >= 2
            assert (await control("step")).command.status == "finished"
            assert len(owner.controller.history.batches) == count
            assert (await port.interactive_goal_status(address, instance)).command.command_id == "cancel"
            assert await port.find_execution_by_submission(address, instance, "busy-chat") is None
            adapter.goal_mode = False
            await _chat(second, address, "after-controlled-goal")

            # A cancel received on the admission turn can settle without starting Work.
            binding = hosted._product_binding
            accepted = binding.control_interactive_goal(
                InteractiveGoalCommandV1(goal_id, "queued-resume", "resume"), check_current=lambda: None,
            )
            assert accepted.command.status == "running"
            binding.control_interactive_goal(
                InteractiveGoalCommandV1(goal_id, "queued-cancel", "cancel"), check_current=lambda: None,
            )
            assert (await settled("queued-cancel")).status == "paused"
            assert len(owner.controller.history.batches) == count

            schedule = asyncio.create_task

            def fail_publication(coroutine, *, name=None):
                if name == "coding-hosted-goal-command":
                    raise RuntimeError("injected task publication failure")
                return schedule(coroutine, name=name)

            with monkeypatch.context() as patch:
                patch.setattr(asyncio, "create_task", fail_publication)
                failed = await control("resume", "failed-resume")
            assert failed.status == "active" and failed.command.status == "failed"
            assert (await control("resume", "failed-resume")).command == failed.command
            assert len(owner.controller.history.batches) == count
            owner.controller.fence()
            with pytest.raises(AppServiceError):
                await control("step", "fenced-step")

    asyncio.run(asyncio.wait_for(scenario(), 55))


@pytest.mark.skipif(sys.platform != "linux", reason="Managed-owned transcript fixture")
def test_hosted_goal_admission_covers_command_gaps_and_close_retry(tmp_path, monkeypatch):
    from loushang.appserver.execution.model import InteractiveGoalCommandV1

    async def scenario():
        async with _managed(tmp_path) as (_, client, _, address, hosted, adapter, _):
            await _activate(client, address, hosted, adapter)
            port = client.execution_client
            instance = port.service_instance_id
            created = await port.create_interactive_goal(address, instance, "Write a greeting in note.txt")
            binding = hosted._product_binding
            owner = binding._goal._interactive_goal_owner
            start = InteractiveGoalCommandV1(created.goal_id, "run", "run")

            # The registry accepted a chat, but the Product execution has not started.
            adapter.goal_mode = False
            ready, release_chat = asyncio.Event(), asyncio.Event()
            execute = port._registry._drive

            async def delay_chat(*args):
                ready.set()
                await release_chat.wait()
                return await execute(*args)

            with monkeypatch.context() as patch:
                patch.setattr(port._registry, "_drive", delay_chat)
                record = await port.submit_execution(address, instance, "accepted-chat", "Finish old work")
                try:
                    await ready.wait()
                    assert hosted._guard.state.status.terminal
                    with pytest.raises(AppServiceError) as conflict:
                        await port.control_interactive_goal(address, instance, start)
                    assert conflict.value.code is AppErrorCodeV1.SESSION_UNAVAILABLE
                finally:
                    release_chat.set()
                while not (await port.get_execution(address, instance, record.state.execution_id)).state.status.terminal:
                    await asyncio.sleep(.01)

            adapter.goal_mode = True
            between = asyncio.Event()
            advance = owner.advance

            async def wait_between(*args, **kwargs):
                result = await advance(*args, **kwargs)
                between.set()
                await asyncio.Future()
                return result

            monkeypatch.setattr(owner, "advance", wait_between)
            assert (await port.control_interactive_goal(address, instance, start)).command.status == "running"
            await between.wait()
            assert not binding.control.runtime.execution_admission.execution_reserved
            assert not owner.controller.facts().busy and len(owner.controller.history.batches) == 1
            with pytest.raises(AppServiceError):
                await port.control_interactive_goal(address, instance, replace(start, command_id="gap-run"))
            with pytest.raises(AppServiceError) as model_change:
                await hosted.select_model("another-model")
            assert model_change.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
            with pytest.raises(AppServiceError) as busy:
                await port.submit_execution(address, instance, "gap-chat", "Keep this draft")
            assert busy.value.code is AppErrorCodeV1.SESSION_UNAVAILABLE
            assert await port.find_execution_by_submission(address, instance, "gap-chat") is None

            async def fail_close():
                raise OSError("Goal close failed")

            with monkeypatch.context() as patch:
                patch.setattr(owner, "close", fail_close)
                with pytest.raises(CleanupIncompleteError):
                    await hosted.close()
                assert binding._goal._interactive_goal_owner is owner
                assert not binding._goal._goal_commands.running and not owner.controller.facts().busy
            await hosted.close()
            assert owner._closed and binding._goal._interactive_goal_owner is None

    asyncio.run(asyncio.wait_for(scenario(), 40))


@pytest.mark.skipif(sys.platform != "linux", reason="Managed-owned transcript fixture")
def test_hosted_review_rechecks_candidate_and_records_decisions(tmp_path):
    from loushang.appserver.execution.model import (
        InteractiveGoalCommandV1,
        InteractiveGoalReviewSubmissionV1,
    )

    async def scenario():
        async with _managed(tmp_path) as (_, client, _, address, hosted, adapter, _):
            await _activate(client, address, hosted, adapter)
            port = client.execution_client
            instance = port.service_instance_id
            created = await port.create_interactive_goal(address, instance, "Write a greeting in note.txt")
            gid = created.goal_id
            owner = hosted._product_binding._goal._interactive_goal_owner

            async def terminal(command_id):
                async with asyncio.timeout(10):
                    while True:
                        result = await port.interactive_goal_status(address, instance)
                        assert result.command.command_id == command_id
                        if result.command.status not in {"running", "settling"}:
                            return result
                        await asyncio.sleep(.01)

            async def run(command_id):
                await port.control_interactive_goal(
                    address, instance, InteractiveGoalCommandV1(gid, command_id, "run"),
                )
                return await terminal(command_id)

            async def decision(basis, command_id, action, reason=None):
                command = InteractiveGoalReviewSubmissionV1(gid, basis.review_token, command_id, action, reason)
                result = await port.submit_interactive_goal_review(address, instance, command)
                assert result.command.command_id == command_id
                return await terminal(command_id)

            assert (await run("initial-run")).review_available
            original = await port.interactive_goal_review(address, instance, gid)
            assert original.changed_files == ("note.txt",) and original.check_count == 0
            (adapter.workspace / "note.txt").write_text("changed after review\n")
            assert (await decision(original, "stale-accept", "accept")).command.status == "failed"
            def batches():
                return tuple(b for b in owner.controller.history.batches if b.source["phase"] == "review")

            assert not batches()
            basis = await port.interactive_goal_review(address, instance, gid)
            assert basis.review_token != original.review_token
            reason = "Keep the greeting and include a sign-off."
            rejected = await decision(basis, "reject", "reject", reason)
            assert rejected.status == "active" and rejected.command.status == "finished"
            review, = batches()
            run_record = owner._work.get_run_for_operation(review.operation_id)
            report = owner._policy.action_result(review, run_record)
            assert report["approved"] is False and report["reason"] == reason

            assert (await run("after-reject")).review_available
            updated = await port.interactive_goal_review(address, instance, gid)
            completed = await decision(updated, "accept", "accept")
            assert completed.status == "completed" and completed.command.status == "finished"
            assert (await decision(updated, "accept", "accept")).status == "completed"
            assert len(batches()) == 2

    asyncio.run(asyncio.wait_for(scenario(), 45))


@pytest.mark.skipif(sys.platform != "linux", reason="Managed-owned transcript fixture")
def test_hosted_review_checks_authority_and_required_evidence_then_joins_review_close(tmp_path, monkeypatch):
    from loushang.appserver.execution.model import (
        InteractiveGoalCommandV1,
        InteractiveGoalReviewSubmissionV1,
    )
    from loushang.coding.adapters.interactive_goal import _ReportWork

    async def scenario():
        async with _managed(tmp_path) as (app, client, selector, address, hosted, adapter, _):
            await _activate(client, address, hosted, adapter)
            port = client.execution_client
            instance = port.service_instance_id
            create_task = InteractiveGoal.create_task

            async def create_with_check(owner, task, **kwargs):
                return await create_task(owner, replace(task, checks=("required evidence",)), **kwargs)

            with monkeypatch.context() as patch:
                patch.setattr(InteractiveGoal, "create_task", create_with_check)
                created = await port.create_interactive_goal(address, instance, "Write a greeting in note.txt")
            gid = created.goal_id
            binding = hosted._product_binding
            owner = binding._goal._interactive_goal_owner

            async def terminal(command_id):
                async with asyncio.timeout(12):
                    while True:
                        result = await port.interactive_goal_status(address, instance)
                        assert result.command.command_id == command_id
                        if result.command.status not in {"running", "settling"}:
                            return result
                        await asyncio.sleep(.01)

            async def plan(command_id):
                await port.control_interactive_goal(address, instance, InteractiveGoalCommandV1(gid, command_id, "run"))
                return await terminal(command_id)

            assert (await plan("initial-plan")).review_available
            entered, proceed = asyncio.Event(), asyncio.Event()
            original_basis = owner.review_basis

            async def delay_basis(goal_id):
                entered.set()
                await proceed.wait()
                return await original_basis(goal_id)

            with monkeypatch.context() as patch:
                patch.setattr(owner, "review_basis", delay_basis)
                pending = asyncio.create_task(port.interactive_goal_review(address, instance, gid))
                await entered.wait()
                try:
                    await client.close()
                    second = app.open_client_scope()
                    attached = await second.attach_mux(MuxAttachV1(selector))
                finally:
                    proceed.set()
                with pytest.raises(AppServiceError) as revoked:
                    await pending
                assert revoked.value.code in {AppErrorCodeV1.STALE_ATTACHMENT, AppErrorCodeV1.SERVICE_CLOSED}

            address = replace(address, attachment_id=attached.attachment_id, controller_generation=attached.controller_generation)
            port = second.execution_client
            summary = await port.interactive_goal_review(address, instance, gid)
            assert summary.check_count == 1 and not summary.checks_satisfied
            accept = InteractiveGoalReviewSubmissionV1(gid, summary.review_token, "missing-check", "accept")
            await port.submit_interactive_goal_review(address, instance, accept)
            refused = await terminal("missing-check")
            assert refused.command.status == "failed" and refused.status != "completed"
            assert all(batch.source["phase"] != "review" for batch in owner.controller.history.batches)
            assert (await plan("after-missing-evidence")).review_available
            summary = await port.interactive_goal_review(address, instance, gid)
            original_execute = _ReportWork.execute

            async def fail_recording_work(executor, operation, context):
                await original_execute(executor, operation, context)
                if operation.kind == "ReviewGoalTask":
                    raise GoalError("injected Review Work failure after producing its report")

            with monkeypatch.context() as patch:
                patch.setattr(_ReportWork, "execute", fail_recording_work)
                failure = InteractiveGoalReviewSubmissionV1(
                    gid, summary.review_token, "failed-work", "reject", "Fix the greeting",
                )
                await port.submit_interactive_goal_review(address, instance, failure)
                assert (await terminal("failed-work")).command.status == "failed"
            review, = (batch for batch in owner.controller.history.batches if batch.source["phase"] == "review")
            assert owner._work.get_run_for_operation(review.operation_id).status == "failed"

            assert (await plan("after-failed-review")).review_available
            summary = await port.interactive_goal_review(address, instance, gid)
            entered_work = asyncio.Event()

            async def hold_review(executor, operation, context):
                if operation.kind == "ReviewGoalTask":
                    entered_work.set()
                    await asyncio.Future()
                await original_execute(executor, operation, context)

            monkeypatch.setattr(_ReportWork, "execute", hold_review)
            reject = InteractiveGoalReviewSubmissionV1(gid, summary.review_token, "close-review", "reject", "Fix the greeting")
            receipt = await port.submit_interactive_goal_review(address, instance, reject)
            assert receipt.command.status == "running"
            await entered_work.wait()
            assert owner.controller.facts().busy
            with pytest.raises(AppServiceError):
                await port.control_interactive_goal(address, instance, InteractiveGoalCommandV1(gid, "extra", "run"))
            await hosted.close()
            assert not binding._goal._goal_commands.running and owner._closed and owner._scope.closed

    asyncio.run(asyncio.wait_for(scenario(), 45))


@pytest.mark.skipif(sys.platform != "linux", reason="Managed-owned transcript fixture")
@pytest.mark.parametrize("accept", [False, True], ids=["review-required", "completed"])
def test_hosted_goal_cold_projection_preserves_original_journals(tmp_path, monkeypatch, accept):
    from loushang.coding.adapters._goal_store import goal_journal_path
    from loushang.coding.hosted.goal_recovery import read_interactive_goal_recovery
    from loushang.harnesswork.integrations import goal_store

    async def scenario():
        async with _managed(tmp_path) as (_, client, _, address, hosted, adapter, session_id):
            binding = hosted._product_binding
            directory = binding.control.session_manager.get_session_file().parent
            absent = read_interactive_goal_recovery(directory, session_id)
            assert absent.presence == "absent"
            await _activate(client, address, hosted, adapter)
            created = await binding.create_interactive_goal("Write a greeting in note.txt")
            owner = binding._goal._interactive_goal_owner
            await run_goal(owner, created.goal_id)
            if accept:
                await owner.accept(created.goal_id, await owner.review_basis(created.goal_id))
            state = owner.controller.query(created.goal_id)
            assert state.status == ("completed" if accept else "paused")
            if not accept:
                assert state.reason == "review_required"
            count = len(owner.controller.history.batches)
            await binding.close_interactive_goal()
            journal = goal_journal_path(directory, session_id)
            work = journal.with_suffix(".work.jsonl")
            original = (journal.read_bytes(), work.read_bytes(), adapter.calls)
            result = read_interactive_goal_recovery(directory, session_id)
            assert (result.goal_id, result.goal_status, result.revision, result.epoch) == (
                state.id, state.status, state.revision, state.epoch,
            )
            assert result.read_only and result.reason_code == state.reason
            assert result.batch_count == result.completed_count == count
            assert not result.execution_unresolved
            assert original == (journal.read_bytes(), work.read_bytes(), adapter.calls)
            assert binding._goal._interactive_goal_owner is None

            original_read = goal_store._read_recovery_journal

            def change_work_during_read(path, stamp, *, max_bytes):
                data = original_read(path, stamp, max_bytes=max_bytes)
                if path == work:
                    work.write_bytes(original[1] + b"\n")
                return data

            with monkeypatch.context() as patch:
                patch.setattr(goal_store, "_read_recovery_journal", change_work_during_read)
                changed = read_interactive_goal_recovery(directory, session_id)
                assert changed.reason_code == "source_changed" and changed.goal_id is None
            work.write_bytes(original[1])

            # Keep complete committed lines, stopping just before the last Work terminal fact.
            lines = original[1].splitlines(keepends=True)
            assert json.loads(lines[-1])["payload"]["kind"] == "WorkRunCompleted"
            prefix = b"".join(lines[:-1])
            work.write_bytes(prefix)
            orphaned = read_interactive_goal_recovery(directory, session_id)
            assert orphaned.presence == "present" and orphaned.goal_status == state.status
            assert orphaned.orphaned_count == 1 and orphaned.completed_count == count - 1
            assert orphaned.execution_unresolved and work.read_bytes() == prefix

            first = json.loads(lines[0])
            first["session_id"] = "different-session"
            corrupt_log = json.dumps(first).encode() + b"\n" + b"".join(lines[1:])
            work.write_bytes(corrupt_log)
            bad = read_interactive_goal_recovery(directory, session_id)
            assert bad.presence == "unavailable" and bad.reason_code == "work_log_invalid"
            assert work.read_bytes() == corrupt_log

            work.unlink()
            missing = read_interactive_goal_recovery(directory, session_id)
            assert missing.presence == "present" and missing.execution_unresolved
            assert missing.completed_count == missing.orphaned_count == 0
            assert not work.exists()
            work.write_bytes(original[1])

            header, *records = original[0].splitlines(keepends=True)
            wrong_identity = json.loads(header) | {"session_id": "different-session"}
            journal.write_bytes(json.dumps(wrong_identity).encode() + b"\n" + b"".join(records))
            assert read_interactive_goal_recovery(directory, session_id).reason_code == "goal_journal_invalid"

            alias = directory.parent / "unauthorized-alias"
            alias.symlink_to(directory, target_is_directory=True)
            assert read_interactive_goal_recovery(alias, session_id).reason_code == "source_changed"

            truncated = original[0] + b'{"uncommitted":'
            journal.write_bytes(truncated)
            invalid = read_interactive_goal_recovery(directory, session_id)
            assert invalid.presence == "unavailable" and invalid.reason_code == "goal_journal_invalid"
            assert invalid.goal_id is None and invalid.execution_unresolved
            assert journal.read_bytes() == truncated

    asyncio.run(asyncio.wait_for(scenario(), 35))


@pytest.mark.skipif(sys.platform != "linux", reason="Managed-owned transcript fixture")
def test_managed_reopens_original_goal_session_read_only(tmp_path, monkeypatch):
    from loushang.appserver.execution.model import InteractiveGoalCommandV1
    from loushang.harnesswork.integrations.goal_store import _GoalWriter

    async def scenario():
        async with _managed(tmp_path) as (app, client, selector, address, hosted, adapter, session_id):
            await _activate(client, address, hosted, adapter)
            binding = hosted._product_binding
            goal = await binding.create_interactive_goal("Write a greeting in note.txt")
            await run_goal(binding._goal._interactive_goal_owner, goal.goal_id)
            state = binding._goal._interactive_goal_owner.controller.query(goal.goal_id)
            await client.close()
            await app.close()

        workspace = tmp_path / "workspace"
        launch = CodingManagedApplicationLaunchV1(
            workspace, tmp_path / "app-manifest", "coding.dynamic-goal", tmp_path / "transcripts",
        )
        attempt = create_coding_managed_attempt(launch, model=_model())
        try:
            app = await attempt.open()
            app.enable_client_scopes()
            client = app.open_client_scope()
            attachment = await client.attach_mux(MuxAttachV1(selector))
            member, = attachment.mux_space.members
            assert member.session.session_id == session_id
            address = SessionSnapshotRequestV1(
                attachment.attachment_id, attachment.controller_generation, member.member_id,
            )
            hosted = (await client._session(
                address.attachment_id, address.controller_generation, address.member_id,
            ))._port
            binding = hosted._product_binding
            assert type(binding) is CodingDeferredHostedSessionV1 and binding._active is None
            execution = client.execution_client
            instance = execution.service_instance_id
            snapshot = await execution.snapshot_execution_session(address, instance)
            assert snapshot.supports_interactive_goal_recovery and not snapshot.supports_interactive_goal

            def forbidden_lease(*args, **kwargs):
                pytest.fail("history observation acquired a Goal Writer lease")

            monkeypatch.setattr(_GoalWriter, "acquire", forbidden_lease)
            observed = await execution.interactive_goal_recovery(address, instance)
            assert (observed.goal_id, observed.goal_status, observed.revision, observed.epoch) == (
                state.id, "paused", state.revision, state.epoch,
            )
            assert observed.reason_code == "review_required"
            with pytest.raises(AppServiceError) as old_command:
                await execution.control_interactive_goal(address, instance, InteractiveGoalCommandV1(
                    state.id, "old-run", "run",
                ))
            assert old_command.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
            assert binding._active is None and not execution._registry._records
        finally:
            await attempt.close()

    asyncio.run(asyncio.wait_for(scenario(), 35))
