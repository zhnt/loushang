"""The real Managed Coding binding borrows its original Session for Goal Work."""
from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from dataclasses import replace

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
from loushang.coding.hosted_execution import CodingHostedExecutionSessionV1
from loushang.coding.hosted_resume import CodingDeferredHostedSessionV1
from loushang.coding.hosted_session import CodingHostedHistoryBindingV1
from loushang.coding.managed_bootstrap import (
    CodingManagedApplicationLaunchV1,
    create_coding_managed_attempt,
)
from loushang.harness.events.session import ToolPolicyAuditEvent
from loushang.harnesswork.goal import GoalError
from loushang.harnesswork.integrations.goal_run import run_goal

from .test_current_session_goal import _model
from .test_hosted_execution import _binding
from .test_hosted_execution import _private_home as _private_home
from .test_interactive_goal import TaskAdapter


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
            assert binding._interactive_goal_owner is None
            if not blocked:
                hosted.start_execution(ExecutionRequestV1("pending-chat", "Prepare original tools"))
                with pytest.raises(GoalError, match="busy"):
                    await binding.create_interactive_goal("Conflicting target")
                assert (await hosted.wait_execution("pending-chat")).status is ExecutionStatusV1.SUCCEEDED
            await _activate(client, address, hosted, adapter)
            initial_calls = adapter.chat_calls
            with monkeypatch.context() as patch:
                patch.setattr(session.session_manager, "cwd", str(tmp_path / "other"))
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
            owner = binding._interactive_goal_owner
            assert owner._session is session and owner._sdk is None
            assert owner.controller.header.session_id == session.session_id
            assert owner.controller.query(created.goal_id).requirements[0].text == "Write a greeting in note.txt"
            contract = owner.controller.query(created.goal_id).metadata["task_contract"]
            assert list(contract["checks"]) == [] and contract["method"] is None and contract["max_model_calls"] == 8
            with pytest.raises(GoalError, match="already"):
                await binding.create_interactive_goal("Another target")
            assert binding._interactive_goal_owner is owner

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
                assert binding._interactive_goal_owner is owner
                with pytest.raises(GoalError, match="cleanup is pending"):
                    binding.interactive_goal_status()
                with pytest.raises(GoalError, match="already"):
                    await binding.create_interactive_goal("Second attempt")
                with pytest.raises(CleanupIncompleteError) as incomplete:
                    await hosted.close()
                assert incomplete.value.cleanup_debt_count >= 1
                assert binding._interactive_goal_owner is owner
                assert not session.runtime.execution_admission.closed
            finally:
                broken = False
            await hosted.close()
            assert binding._interactive_goal_owner is None
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
                owner = binding._interactive_goal_owner
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
            assert binding._interactive_goal_owner is None

    asyncio.run(asyncio.wait_for(scenario(), 40))


@pytest.mark.skipif(sys.platform != "linux", reason="Managed-owned transcript fixture")
def test_parent_close_joins_active_goal_work(tmp_path):
    async def scenario():
        async with _managed(tmp_path) as (_, client, _, address, hosted, adapter, _):
            await _activate(client, address, hosted, adapter)
            binding = hosted._product_binding
            session = binding.control
            created = await binding.create_interactive_goal("Target")
            owner = binding._interactive_goal_owner
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
                assert binding._interactive_goal_owner is None
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
