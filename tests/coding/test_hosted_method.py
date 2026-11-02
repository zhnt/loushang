from __future__ import annotations

import asyncio
import gc
import weakref
from dataclasses import asdict, dataclass, fields, replace

import pytest

from loushang.agent import synthetic_model_transport
from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import Capabilities, Model
from loushang.apphost.errors import AppHostError, AppHostFailureCategory
from loushang.appserver.method_work import MethodWorkError
from loushang.appserver.protocol import (
    AppServiceError,
    MuxAttachV1,
    MuxCreateV1,
    MuxMemberCloseV1,
    MuxMemberOpenV1,
    MuxSelectorV1,
    SessionOpenSpecV1,
    SessionScopeV1,
    SessionSnapshotRequestV1,
    TurnInterruptV1,
    TurnTextV1,
)
from loushang.appservice.client_scope import ScopedAppServiceV1
from loushang.appservice.execution_contract import (
    ExecutionRequestV1,
    ExecutionStatusV1,
    InterruptModeV1,
)
from loushang.appservice.execution_registry import ExecutionServiceErrorV1
from loushang.appservice.runtime import AppServiceV1
from loushang.coding.hosted_application import (
    CODING_HOSTED_APPLICATION_PROFILE_ID,
    CodingForegroundHostedApplicationRequestV1,
)
from loushang.coding.hosted_bootstrap import CodingHostedLaunchV1
from loushang.coding.hosted_execution import CodingHostedExecutionSessionV1
from loushang.coding.hosted_method import (
    CodingHostedMethodSessionV1,
    CodingHostedMethodV1,
    create_coding_method_service_binding,
)
from loushang.coding.hosted_method_application import create_coding_method_application
from loushang.method.types import MethodDescriptor

from .test_hosted_execution import _binding, _message, _run, _stream
from .test_hosted_execution import _private_home as _private_home


def _method(metadata=None):
    return CodingHostedMethodV1(MethodDescriptor(
        id="method:hosted-check", name="Hosted check", description="Two steps", kind="test",
        content="Perform the assigned step.",
        metadata=metadata or {"frontmatter": {"plan_mode": "fixed", "steps": ["inspect", "verify"]}},
    ))


async def _hosted(tmp_path, stream_fn=_stream):
    binding, session = await _binding(tmp_path, stream_fn=stream_fn)
    return CodingHostedMethodSessionV1(binding, _method()), session, binding


async def _service(tmp_path, stream_fn=_stream):
    hosted, session, binding = await _hosted(tmp_path, stream_fn)

    class Resolver:
        async def open_session(self, request):
            return hosted

    service = AppServiceV1(product_id="coding", resolver=Resolver(), execution=create_coding_method_service_binding("test"))
    owner = ScopedAppServiceV1(service)
    scope = owner.open_client_scope()
    mux = await scope.create_mux(MuxCreateV1("method"))
    selector = MuxSelectorV1(mux_space_id=mux.mux_space_id)
    await scope.attach_mux(MuxAttachV1(selector))
    mux = await scope.open_member(MuxMemberOpenV1(selector, SessionOpenSpecV1(
        product_id="coding", continuity_id="continuity", scope=SessionScopeV1.CWD,
        scope_fingerprint="c" * 64, title="Method check",
        session_id=session.session_id,
    )))
    attach = await scope.attach_mux(MuxAttachV1(selector))
    control = SessionSnapshotRequestV1(attach.attachment_id, attach.controller_generation, mux.members[0].member_id)
    return service, owner, scope, control, hosted, session, selector


def test_two_steps_reuse_original_session_and_project_confirmed_work(tmp_path):
    async def scenario():
        hosted, session, _ = await _hosted(tmp_path)
        try:
            hosted.start_execution(ExecutionRequestV1("E1", "inspect and verify"))
            outcome = await hosted.wait_execution("E1")
            assert outcome.status is ExecutionStatusV1.SUCCEEDED
            observation = hosted.query_method_work("E1")
            assert observation.presence == "present"
            assert observation.work.session_id == session.session_id
            assert observation.work.operation_id == "E1"
            assert [(s.step_id, s.status) for s in observation.work.steps] == [("inspect", "completed"), ("verify", "completed")]
            assert observation.recording.run_status == "completed"
            assert observation.recording.retention == "memory"
            assert observation.cancellation.status == "not_requested"
            assert len(session.messages) == 4
            assert "Perform the assigned" not in str(asdict(observation))
        finally:
            await hosted.close()
    _run(scenario())


def test_method_is_deeply_frozen_and_unsupported_contract_rejected():
    metadata = {"frontmatter": {"plan_mode": "fixed", "steps": ["inspect", "verify"]}}
    method = _method(metadata)
    digest = method.digest
    metadata["frontmatter"]["steps"].append("injected")
    assert method.digest == digest
    with pytest.raises(ValueError):
        _method({"frontmatter": {"plan_mode": "fixed", "steps": ["x"], "step_constraints": {"x": {"permission": "unknown"}}}})
    @dataclass
    class MutableMetadata:
        value: str = "mutable"

    with pytest.raises(ValueError, match="data class"):
        _method({"custom": MutableMetadata()})
    with pytest.raises(ValueError, match="approval gates"):
        _method({"approval_gates": ["unimplemented"]})


def test_scoped_submit_dedup_query_and_legacy_fences(tmp_path):
    async def scenario():
        service, owner, scope, control, hosted, session, _ = await _service(tmp_path)
        try:
            assert scope.execution_client is None
            client = scope.method_work_client
            assert client is not None
            instance = client.service_instance_id
            capability = await client.capability(control, instance)
            submitted = await client.submit(control, instance, "S1", "run both")
            duplicate = await client.submit(control, instance, "S1", "run both")
            assert duplicate.handle == submitted.handle
            with pytest.raises(ExecutionServiceErrorV1):
                await client.submit(control, instance, "S1", "different")
            result = await client.wait(control, submitted.handle)
            assert result.execution.state.status is ExecutionStatusV1.SUCCEEDED
            assert result.observation.work.method_id == capability.method_id
            assert (await client.find(control, instance, "S1")).handle == submitted.handle
            for target in (scope, service):
                for name in ("start_turn", "steer_turn", "follow_up_turn"):
                    with pytest.raises(AppServiceError):
                        await getattr(target, name)(TurnTextV1(control.attachment_id, control.controller_generation, control.member_id, "bypass"))
                with pytest.raises(AppServiceError):
                    await target.interrupt_turn(TurnInterruptV1(control.attachment_id, control.controller_generation, control.member_id))
            with pytest.raises(MethodWorkError, match="binding_changed"):
                await client.query(control, replace(submitted.handle, work_binding="other"))
            assert len(session.messages) == 4
        finally:
            await owner.close()
            await service.close()
    _run(scenario())


def test_model_failure_stops_method_even_when_prompt_returns(tmp_path):
    calls = []

    @synthetic_model_transport
    async def failing(model, context, options=None):
        calls.append(1)
        stream = AssistantMessageEventStream()
        message = _message("error")
        stream.push({"type": "error", "reason": "error", "error": message})
        return stream

    async def scenario():
        hosted, _, _ = await _hosted(tmp_path, failing)
        try:
            hosted.start_execution(ExecutionRequestV1("failure", "run"))
            result = await hosted.wait_execution("failure")
            assert result.status is ExecutionStatusV1.FAILED
            assert calls == [1]
            observation = hosted.query_method_work("failure")
            assert observation.work.status == "failed"
            assert observation.work.current_step_id == "inspect"
        finally:
            await hosted.close()
    _run(scenario())


def test_cancel_during_step_does_not_start_next_step(tmp_path):
    async def scenario():
        entered = asyncio.Event()
        calls = []

        @synthetic_model_transport
        async def blocked(model, context, options=None):
            calls.append(1)
            entered.set()
            await asyncio.Event().wait()

        hosted, _, _ = await _hosted(tmp_path, blocked)
        try:
            hosted.start_execution(ExecutionRequestV1("cancel", "run"))
            await entered.wait()
            hosted.interrupt_execution("cancel", InterruptModeV1.WHOLE_EXECUTION)
            result = await hosted.wait_execution("cancel")
            assert result.status is ExecutionStatusV1.INTERRUPTED
            assert calls == [1]
            assert hosted.query_method_work("cancel").work.status == "cancelled"
        finally:
            await hosted.close()
    _run(scenario())


def test_second_execution_wrapper_is_rejected_without_closing_first(tmp_path):
    async def scenario():
        hosted, _, binding = await _hosted(tmp_path)
        try:
            with pytest.raises(ValueError, match="execution owner"):
                CodingHostedExecutionSessionV1(binding)
            hosted.start_execution(ExecutionRequestV1("still-alive", "run"))
            assert (await hosted.wait_execution("still-alive")).status is ExecutionStatusV1.SUCCEEDED
        finally:
            await hosted.close()
    _run(scenario())


def test_real_apphost_application_executes_and_queries_fixed_method(tmp_path):
    async def scenario():
        launch = CodingHostedLaunchV1(
            tmp_path, tmp_path / "application", "coding.method-test",
            tmp_path / "cwd-sessions", tmp_path / "home-sessions",
        )
        model = Model(
            id="faux", name="Faux", provider="faux", endpoint="anthropic-messages",
            capabilities=Capabilities(input=("text",), context_window=128000, max_tokens=4096),
        )
        app = await create_coding_method_application(launch, _method(), model=model, stream_fn=_stream, tools=[])
        try:
            scope = app.open_client_scope()
            mux = await scope.create_mux(MuxCreateV1("method"))
            selector = MuxSelectorV1(mux_space_id=mux.mux_space_id)
            await scope.attach_mux(MuxAttachV1(selector))
            spec = SessionOpenSpecV1(
                product_id="coding", continuity_id="method-test", scope=SessionScopeV1.CWD,
                scope_fingerprint=launch.scopes[0].fingerprint, title="Method check",
            )
            mux = await scope.open_member(MuxMemberOpenV1(selector, spec))
            attachment = await scope.attach_mux(MuxAttachV1(selector))
            control = SessionSnapshotRequestV1(
                attachment.attachment_id, attachment.controller_generation, mux.members[0].member_id,
            )
            client = scope.method_work_client
            submitted = await client.submit(control, client.service_instance_id, "S1", "inspect then verify")
            result = await client.wait(control, submitted.handle)
            assert result.execution.state.status is ExecutionStatusV1.SUCCEEDED
            assert result.observation.work.session_id == mux.members[0].session.session_id
            assert [s.status for s in result.observation.work.steps] == ["completed", "completed"]
            assert len(list(launch.cwd_sessions.glob("*.jsonl"))) == 1
            identities = await app._apphost._router.list_identities((launch.scopes[0].discovery_scope,), limit=16)
            assert len(identities) == 1
            with pytest.raises(AppHostError) as error:
                await app._apphost.attach_resume(
                    product_id="coding", reference=identities[0].reference,
                    profile_id=CODING_HOSTED_APPLICATION_PROFILE_ID,
                )
            assert error.value.category is AppHostFailureCategory.PROFILE_UNAVAILABLE
            # Rejecting the second AppHost profile must not close the first.
            next_work = await client.submit(control, client.service_instance_id, "S2", "still usable")
            assert (await client.wait(control, next_work.handle)).execution.state.status is ExecutionStatusV1.SUCCEEDED
        finally:
            await app.close()
    _run(scenario(), timeout=30)


def test_pre_product_interrupt_reports_unknown_not_invented_non_submission(tmp_path):
    async def scenario():
        service, owner, scope, control, _, session, _ = await _service(tmp_path)
        try:
            client = scope.method_work_client
            submitted = await client.submit(control, client.service_instance_id, "early", "run")
            await client.interrupt(control, submitted.handle)
            result = await client.wait(control, submitted.handle)
            assert result.execution.state.status is ExecutionStatusV1.INTERRUPTED
            assert result.observation.presence == "unknown"
            assert session.messages == []
            following = await client.submit(control, client.service_instance_id, "next", "run")
            await client.wait(control, following.handle)
            assert (await client.query(control, submitted.handle)).observation.presence == "unknown"
        finally:
            await owner.close()
            await service.close()
    _run(scenario())


def test_cleanup_failure_retains_work_and_retry_does_not_execute_again(tmp_path, monkeypatch):
    async def scenario():
        service, owner, scope, control, hosted, session, _ = await _service(tmp_path)
        fail = True
        original = session.settle_execution

        async def settlement(*, interrupted=False):
            if fail and hosted._work.work_runtime.query_runs()[-1].status == "completed":
                raise RuntimeError("injected cleanup failure")
            await original(interrupted=interrupted)

        monkeypatch.setattr(session, "settle_execution", settlement)
        try:
            client = scope.method_work_client
            submitted = await client.submit(control, client.service_instance_id, "cleanup", "run")
            with pytest.raises(AppServiceError):
                await client.wait(control, submitted.handle)
            observed = await client.query(control, submitted.handle)
            assert observed.observation.work.status == "completed"
            assert observed.execution.state.status is ExecutionStatusV1.RUNNING
            with pytest.raises(ExecutionServiceErrorV1):
                await client.submit(control, client.service_instance_id, "blocked", "run")
            assert hosted._work is not None
            fail = False
            result = await client.retry_settlement(control, submitted.handle)
            assert result.execution.state.status is ExecutionStatusV1.SUCCEEDED
            assert len(session.messages) == 4
            assert len(hosted._work.work_runtime.query_runs()) == 1
        finally:
            fail = False
            await owner.close()
            await service.close()
    _run(scenario())


def test_late_interrupt_preserves_candidate_outcome(tmp_path, monkeypatch):
    async def scenario():
        hosted, session, _ = await _hosted(tmp_path)
        entered, release = asyncio.Event(), asyncio.Event()
        original = session.settle_execution

        async def settlement(*, interrupted=False):
            run = hosted._work.work_runtime.get_run_for_operation("late")
            if run is not None and run.status == "completed":
                entered.set()
                await release.wait()
            await original(interrupted=interrupted)

        monkeypatch.setattr(session, "settle_execution", settlement)
        try:
            hosted.start_execution(ExecutionRequestV1("late", "run"))
            await entered.wait()
            hosted.interrupt_execution("late", InterruptModeV1.WHOLE_EXECUTION)
            assert hosted.execution_state.interrupt_requested
            release.set()
            assert (await hosted.wait_execution("late")).status is ExecutionStatusV1.SUCCEEDED
            assert len(session.messages) == 4
        finally:
            release.set()
            await hosted.close()
    _run(scenario())


def test_scope_detach_keeps_owner_and_old_authority_cannot_read(tmp_path):
    async def scenario():
        service, owner, scope, control, hosted, session, selector = await _service(tmp_path)
        try:
            client = scope.method_work_client
            submitted = await client.submit(control, client.service_instance_id, "retained", "run")
            await client.wait(control, submitted.handle)
            work_owner = hosted._work
            await scope.close()
            with pytest.raises(AppServiceError):
                await client.query(control, submitted.handle)
            second = owner.open_client_scope()
            attach = await second.attach_mux(MuxAttachV1(selector))
            new_control = SessionSnapshotRequestV1(attach.attachment_id, attach.controller_generation, control.member_id)
            result = await second.method_work_client.query(new_control, submitted.handle)
            assert result.observation.work.status == "completed"
            assert hosted._work is work_owner
            assert len(session.messages) == 4
            with pytest.raises(ExecutionServiceErrorV1):
                await second.method_work_client.query(new_control, replace(submitted.handle, service_instance_id="wrong-instance"))
            with pytest.raises(ExecutionServiceErrorV1):
                await second.method_work_client.query(new_control, replace(submitted.handle, execution_id="unknown-execution"))
        finally:
            await owner.close()
            await service.close()
    _run(scenario())


def test_close_releases_work_graph_while_facade_remains_referenced(tmp_path):
    async def scenario():
        hosted, _, _ = await _hosted(tmp_path)
        hosted.start_execution(ExecutionRequestV1("release", "run"))
        await hosted.wait_execution("release")
        runtime = weakref.ref(hosted._work.work_runtime)
        backend = weakref.ref(hosted._work.event_log)
        await hosted.close()
        gc.collect()
        assert runtime() is None and backend() is None
        with pytest.raises(RuntimeError, match="closed"):
            hosted.query_method_work("release")
    _run(scenario())


def test_append_failure_cannot_become_completed_or_leak_error_text(tmp_path, monkeypatch):
    async def scenario():
        service, owner, scope, control, hosted, session, _ = await _service(tmp_path)
        backend = hosted._work.event_log
        append = backend.append

        def failing(entry):
            if entry.payload.get("kind") == "WorkRunCompleted":
                raise OSError("secret /server/private/path")
            return append(entry)

        monkeypatch.setattr(backend, "append", failing)
        try:
            client = scope.method_work_client
            submitted = await client.submit(control, client.service_instance_id, "append-fault", "run")
            result = await client.wait(control, submitted.handle)
            assert result.execution.state.status is ExecutionStatusV1.FAILED
            observation = result.observation
            assert observation.recording is None
            assert "work_recording_unavailable" in observation.errors
            assert "/server/private/path" not in str(asdict(observation))
            assert not (await client.capability(control, client.service_instance_id)).accepting
            assert (await client.submit(control, client.service_instance_id, "append-fault", "run")).handle == submitted.handle
            with pytest.raises(MethodWorkError, match="unavailable"):
                await client.submit(control, client.service_instance_id, "second", "must not execute")
            assert await client.find(control, client.service_instance_id, "second") is None
            assert len(session.messages) == 4
        finally:
            await owner.close()
            await service.close()
    _run(scenario())


def test_finished_admission_with_unknown_write_is_not_still_admitting(tmp_path, monkeypatch):
    async def scenario():
        hosted, session, _ = await _hosted(tmp_path)
        entered, release = asyncio.Event(), asyncio.Event()
        original = session.settle_execution

        def append_failure(entry):
            raise OSError("injected admission write failure")

        async def settlement(*, interrupted=False):
            entered.set()
            await release.wait()
            await original(interrupted=interrupted)

        monkeypatch.setattr(hosted._work.event_log, "append", append_failure)
        monkeypatch.setattr(session, "settle_execution", settlement)
        try:
            hosted.start_execution(ExecutionRequestV1("unknown", "run"))
            await entered.wait()
            assert hosted.execution_state.status is ExecutionStatusV1.RUNNING
            assert hosted.query_method_work("unknown").presence == "unknown"
            assert session.messages == []
            release.set()
            assert (await hosted.wait_execution("unknown")).status is ExecutionStatusV1.FAILED
        finally:
            release.set()
            await hosted.close()
    _run(scenario())


def test_retired_member_keeps_work_until_actual_owner_close(tmp_path):
    async def scenario():
        service, owner, scope, control, hosted, _, selector = await _service(tmp_path)
        client = scope.method_work_client
        try:
            submitted = await client.submit(control, client.service_instance_id, "retire", "run")
            await client.wait(control, submitted.handle)
            work = weakref.ref(hosted._work.work_runtime)
            await scope.close_member(MuxMemberCloseV1(selector, control.member_id, close_session=False))
            with pytest.raises(AppServiceError):
                await client.query(control, submitted.handle)
            assert work() is not None
            assert hosted.query_method_work(submitted.handle.execution_id).work.status == "completed"
        finally:
            await owner.close()
            await service.close()
        gc.collect()
        assert work() is None
    _run(scenario())


def test_new_method_option_preserves_original_positional_constructor():
    from .test_hosted_application import (
        _CanonicalSessions,
        _foreground_request,
        _Ids,
        _SessionFactory,
    )

    class Owner:
        def fence(self):
            pass

        async def close(self):
            pass

    events = []
    owner = Owner()
    request = replace(_foreground_request(
        generation_id="compatibility", sessions=_CanonicalSessions(),
        session_factory=_SessionFactory(events), events=events, ids=_Ids(),
    ), session_owner=owner)
    original_values = [getattr(request, f.name) for f in fields(request) if f.name != "method"]
    copied = CodingForegroundHostedApplicationRequestV1(*original_values)
    assert copied.session_owner is owner and copied.method is None
    assert copied.managed_selection is request.managed_selection
