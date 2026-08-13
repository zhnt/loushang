from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.agent.types import AgentToolResult
from loushang.ai.model import ModelSelection
from loushang.ai.types import (
    AssistantMessage,
    TextPart,
    ToolCall,
    Usage,
    UserMessage,
)
from loushang.coding.multiagent import (
    CodingSubagentFactory,
    coding_agent_types,
    coding_multiagent_system_prompt,
    coding_read_only_agent_types,
    coding_recipe_context_plan,
    install_coding_multiagent_session,
)
from loushang.harness.multiagent import (
    AgentInputMessage,
    AgentPath,
    AgentTypeRegistry,
    AgentTypeSpec,
    DelegatedExecutionProfile,
    ForkedHistory,
    ForkTier,
    HostCaller,
    MultiAgentControl,
    SubagentContextPlan,
    WorkspaceLease,
    WorkspaceLeaseRequest,
    WorkspaceLeaseSnapshot,
)
from loushang.harness.runtime import HostInputQueue
from loushang.harness.session.multiagent import SessionSubagentRequest
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.execution import direct_execution
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
from loushang.harness.transcript import ApplicationMessage


class _State:
    def __init__(self) -> None:
        self.messages: list[object] = []

    def set_messages(self, messages: list[object]) -> None:
        self.messages = list(messages)


class _Agent:
    def __init__(self) -> None:
        self.state = _State()


class _SessionInputQueue(HostInputQueue[object]):
    def __init__(self, session: _Session) -> None:
        super().__init__()
        self._session = session

    def enqueue(self, kind, *, text: str, payload: object):
        if kind == "steering":
            self._session.steering.append(text)
        else:
            self._session.follow_ups.append(text)
        return super().enqueue(kind, text=text, payload=payload)


@dataclass
class _Session:
    responses: list[AssistantMessage]
    agent: _Agent = field(default_factory=_Agent)
    prompt_calls: list[tuple[str, str | None]] = field(default_factory=list)
    follow_ups: list[str] = field(default_factory=list)
    steering: list[str] = field(default_factory=list)
    abort_calls: int = 0

    def __post_init__(self) -> None:
        self.runtime = SimpleNamespace(
            queue=SimpleNamespace(input_queue=_SessionInputQueue(self))
        )

    async def prompt(self, text: str, *, source: str | None = None) -> None:
        self.prompt_calls.append((text, source))
        self.agent.state.messages.append(
            UserMessage(role="user", content=text, timestamp=0)
        )
        self.agent.state.messages.append(self.responses.pop(0))

    def follow_up(self, text: str) -> None:
        self.follow_ups.append(text)

    def steer(self, text: str) -> None:
        self.steering.append(text)

    async def continue_run(self) -> None:
        text = self.follow_ups[-1] if self.follow_ups else self.steering[-1]
        self.agent.state.messages.append(
            UserMessage(role="user", content=text, timestamp=0)
        )
        self.agent.state.messages.append(self.responses.pop(0))

    def abort(self) -> bool:
        self.abort_calls += 1
        return True


@dataclass
class _Runtime:
    session: _Session
    create_cwds: list[str] = field(default_factory=list)
    dispose_calls: int = 0

    async def create_session(self, *, cwd: str) -> _Session:
        self.create_cwds.append(cwd)
        return self.session

    async def dispose_session_runtime(self) -> None:
        self.dispose_calls += 1


class _FailingRuntime(_Runtime):
    async def create_session(self, *, cwd: str) -> _Session:
        self.create_cwds.append(cwd)
        raise RuntimeError("child session failed")


class _UnusedFactory:
    async def create(self, request: SessionSubagentRequest):
        raise AssertionError(f"unexpected child construction: {request.record.path}")


class _RootInputQueue(HostInputQueue[object]):
    def __init__(self) -> None:
        super().__init__()
        self.payloads: list[object] = []

    def enqueue(self, kind, *, text: str, payload: object):
        self.payloads.append(payload)
        return super().enqueue(kind, text=text, payload=payload)


class _RootQueue:
    def __init__(self) -> None:
        self.input_queue = _RootInputQueue()
        self.mailbox: list[object] = []

    def queue_mailbox_message(self, message: object) -> None:
        self.mailbox.append(message)


class _RootRuntime:
    def __init__(self) -> None:
        self.queue = _RootQueue()
        self.is_active = False


class _RootSession:
    def __init__(self) -> None:
        self.runtime = _RootRuntime()


class _WorkspaceLeases:
    def __init__(self, root: Path, *, changed: bool = True) -> None:
        self.root = root
        self.changed = changed
        self.acquired: list[WorkspaceLeaseRequest] = []
        self.released = 0

    async def acquire(self, request: WorkspaceLeaseRequest) -> WorkspaceLease:
        self.acquired.append(request)
        return WorkspaceLease(
            workspace_ref="git-workspace:test",
            execution_ref=str(self.root),
        )

    async def snapshot(self, _lease: WorkspaceLease) -> WorkspaceLeaseSnapshot:
        return WorkspaceLeaseSnapshot(
            workspace_ref="git-workspace:test",
            artifact_refs=("git-artifact:test",) if self.changed else (),
            changed=self.changed,
        )

    async def release(self, _lease: WorkspaceLease) -> WorkspaceLeaseSnapshot:
        self.released += 1
        return WorkspaceLeaseSnapshot(
            workspace_ref="git-workspace:test" if self.changed else None,
            artifact_refs=("git-artifact:test",) if self.changed else (),
            changed=self.changed,
            retained=self.changed,
        )


def _assistant(
    text: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read: int = 0,
    tool_call: bool = False,
) -> AssistantMessage:
    content = [TextPart(type="text", text=text)]
    if tool_call:
        content.append(
            ToolCall(
                type="toolCall",
                id="tool-1",
                name="read",
                arguments={"path": "README.md"},
            )
        )
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=content,
        api="test",
        provider="provider",
        model="model",
        response_id=None,
        usage=Usage(
            input=input_tokens,
            output=output_tokens,
            cache_read=cache_read,
            cache_write=0,
            total_tokens=input_tokens + output_tokens + cache_read,
            cost=None,
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=0,
    )


def _tool_registry(*names: str) -> WorkspaceToolRegistry:
    async def unused_execute(*_args: object) -> AgentToolResult[None]:
        raise AssertionError("tool execution is not expected in this test")

    registry = WorkspaceToolRegistry()
    for name in names:
        registry.register_tool(
            ToolDefinition(
                name=name,
                label=name,
                description=f"Test {name}",
                parameters={"type": "object", "properties": {}},
                execution=direct_execution(unused_execute),
            )
        )
    return registry


def _request(
    *,
    spec: AgentTypeSpec,
    context_plan: SubagentContextPlan[object] | None = None,
) -> SessionSubagentRequest:
    control = MultiAgentControl(agent_types=AgentTypeRegistry((spec,)))
    record = control.spawn(
        caller=HostCaller(),
        parent_path=AgentPath.root(),
        name="child",
        agent_type=spec.name,
    )
    parent = control.registry.get(control.root_ref)
    assert parent is not None
    return SessionSubagentRequest(
        record=record,
        parent=parent,
        agent_type=spec,
        context_plan=context_plan,
    )


def test_coding_analysis_agent_types_are_bounded_and_have_no_write_tools() -> None:
    registry = coding_read_only_agent_types(
        default_model="provider:test-endpoint:model",
        maximum_children=2,
    )

    assert [spec.name for spec in registry.values()] == [
        "critic",
        "explorer",
        "judge",
        "proposer",
        "reviewer",
        "synthesizer",
    ]
    for spec in registry.values():
        assert spec.default_model == "provider:test-endpoint:model"
        assert spec.allowed_tools == (
            ("bash", "read", "grep", "find", "ls")
            if spec.name == "explorer"
            else ("read", "grep", "find", "ls")
        )
        assert "write" not in spec.allowed_tools
        assert "edit" not in spec.allowed_tools
        assert spec.maximum_children == (
            2 if spec.name in {"explorer", "reviewer"} else 1
        )
        assert spec.can_spawn is False


def test_coding_phase_two_types_offer_isolated_and_shared_write_workers() -> None:
    registry = coding_agent_types(maximum_children=2)
    worker = registry.resolve("implementation_worker")
    shared_worker = registry.resolve("shared_implementation_worker")
    test_runner = registry.resolve("test_runner")

    assert worker is not None
    assert worker.workspace_mode == "isolated"
    assert worker.allowed_tools == (
        "bash",
        "read",
        "grep",
        "find",
        "ls",
        "write",
        "edit",
    )
    assert worker.maximum_children == 2
    assert shared_worker is not None
    assert shared_worker.workspace_mode == "inherit"
    assert shared_worker.allowed_tools == worker.allowed_tools
    assert shared_worker.maximum_children == 2
    assert test_runner is not None
    assert test_runner.workspace_mode == "isolated"
    assert "bash" in test_runner.allowed_tools
    assert "write" not in test_runner.allowed_tools


def test_coding_multiagent_prompt_names_the_admitted_roles_and_wait_discipline() -> (
    None
):
    prompt = coding_multiagent_system_prompt(coding_agent_types())

    assert "`explorer`" in prompt
    assert "`reviewer`" in prompt
    assert "`spawn_agent`" in prompt
    assert "`wait_agent`" in prompt
    assert "completion notices enter your system mailbox" in prompt
    assert "separate from editable follow-up and steering input queues" in prompt
    assert "whose listed tools cover the delegated task" in prompt
    assert "not proof that the requested task succeeded" in prompt
    assert "Preserve result provenance" in prompt
    assert "tools: bash, read, grep, find, ls" in prompt
    assert "`shared_implementation_worker`" in prompt
    assert "directly in the current worktree and branch" in prompt
    assert "maximum open children" in prompt
    assert "maximum concurrent children" not in prompt
    assert "A failed spawn creates no child" in prompt
    assert "do not wait for it" in prompt
    assert "remain open, addressable, and count against open-child limits" in prompt
    assert "After one-shot fan-out and aggregation, close children" in prompt
    assert "explicit ownership of files or responsibility" in prompt
    assert "write scopes are disjoint" in prompt
    assert "must not revert others' edits" in prompt


def test_coding_explorer_context_allows_investigative_bash_without_write_tools() -> (
    None
):
    registry = coding_read_only_agent_types()

    plan = coding_recipe_context_plan(
        agent_type="explorer",
        model=None,
        agent_types=registry,
    )

    assert plan.allowed_tools == ("bash", "read", "grep", "find", "ls")
    assert "Python analysis" in plan.system_prompt
    assert "curl-based network retrieval" in plan.system_prompt
    assert "Do not modify product files" in plan.system_prompt


def test_factory_projects_explorer_bash_into_the_child_runtime(tmp_path: Path) -> None:
    session = _Session(
        responses=[_assistant("Exploration complete.", input_tokens=1, output_tokens=1)]
    )
    runtime = _Runtime(session)
    captured: dict[str, object] = {}

    def build_runtime(**kwargs: object) -> _Runtime:
        captured.update(kwargs)
        return runtime

    spec = coding_read_only_agent_types().resolve("explorer")
    assert spec is not None
    factory = CodingSubagentFactory(
        session_dir=tmp_path / "sessions",
        cwd=tmp_path,
        tool_registry=_tool_registry("bash", "read", "grep", "find", "ls"),
        runtime_builder=build_runtime,
    )

    async def scenario() -> None:
        binding = await factory.create(_request(spec=spec))
        driver = binding.driver
        await driver.dispose()

    asyncio.run(scenario())

    expected = ["bash", "read", "grep", "find", "ls"]
    assert captured["allowed_tool_names"] == expected
    assert captured["active_tool_names"] == expected
    assert [
        definition.name for definition in captured["tool_registry"].list_definitions()
    ] == expected


def test_factory_binds_shared_approval_resolver_to_child_incarnation(
    tmp_path: Path,
) -> None:
    from loushang.harness.approval import (
        ActorBoundApprovalResolver,
        ApprovalGrantProposal,
        ApprovalRequest,
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
    )

    session = _Session(responses=[_assistant("Done.", input_tokens=1, output_tokens=1)])
    captured: dict[str, object] = {}

    def build_runtime(**kwargs: object) -> _Runtime:
        captured.update(kwargs)
        return _Runtime(session)

    spec = AgentTypeSpec(name="reviewer", allowed_tools=("read",))
    request = _request(spec=spec)
    root_resolver = InteractiveApprovalResolver(
        fallback=HeadlessApprovalResolver(mode="deny")
    )
    factory = CodingSubagentFactory(
        session_dir=tmp_path / "sessions",
        cwd=tmp_path,
        tool_registry=_tool_registry("read"),
        runtime_builder=build_runtime,
        approval_resolver=root_resolver,
    )

    binding = asyncio.run(factory.create(request))
    driver = binding.driver
    bound = captured["approval_resolver"]
    assert isinstance(bound, ActorBoundApprovalResolver)
    assert bound.resolver is root_resolver
    assert bound.actor_id == str(request.record.ref)
    delegated = captured["delegated_execution_profile"]
    assert isinstance(delegated, DelegatedExecutionProfile)
    assert delegated.actor_ref == request.record.ref
    assert delegated.allowed_tools == ("read",)
    assert delegated.approval_actor_id == bound.actor_id
    assert delegated.execution_profile_ceiling.readable_roots == (tmp_path.resolve(),)
    assert delegated.execution_profile_ceiling.writable_roots == ()
    assert driver.delegated_execution_profile is delegated
    grant = root_resolver.grant_store.issue(
        ApprovalRequest(
            tool_name="bash",
            arguments={"command": "git push origin main"},
            action_id="child-push",
            actor_id=bound.actor_id,
            session_grant=ApprovalGrantProposal(
                capability="git.publish_refs",
                constraints=(("remote", "origin"),),
                summary="Publish non-force refs to origin",
            ),
        )
    )

    asyncio.run(driver.dispose())

    assert (
        root_resolver.grant_store.find(
            ApprovalRequest(
                tool_name="bash",
                arguments={"command": "git push origin main"},
                action_id="child-push-after-close",
                actor_id=bound.actor_id,
                session_grant=grant.proposal,
            )
        )
        is None
    )


@pytest.mark.parametrize(
    "release_mode",
    (
        "escape",
        "interrupt_agent",
        "close_agent",
        "new",
        "resume",
        "session_exit",
    ),
)
def test_pending_child_approval_is_cleared_by_every_lifecycle_exit(
    tmp_path: Path,
    release_mode: str,
) -> None:
    from loushang.harness.approval import (
        ApprovalRequest,
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
        resolve_approval,
    )
    from loushang.harness.multiagent import AgentCaller
    from loushang.harness.session.multiagent import (
        SessionMultiAgentRuntime,
        compose_multiagent_before_release,
    )

    class PendingApprovalSession(_Session):
        def __init__(self, approval_resolver: object) -> None:
            super().__init__(responses=[])
            self.approval_resolver = approval_resolver
            self.effect_calls = 0

        async def prompt(self, text: str, *, source: str | None = None) -> None:
            del text, source
            decision = await resolve_approval(
                self.approval_resolver,  # type: ignore[arg-type]
                ApprovalRequest(
                    tool_name="bash",
                    arguments={"command": "rm -r lifecycle-target"},
                    reason="Filesystem content would be deleted",
                ),
            )
            if decision.disposition != "allow":
                raise PermissionError(decision.reason or decision.disposition)
            self.effect_calls += 1

    async def scenario() -> None:
        presented = asyncio.Event()
        payloads: list[dict[str, object]] = []
        root_resolver = InteractiveApprovalResolver(
            fallback=HeadlessApprovalResolver(mode="deny")
        )

        def present(payload: dict[str, object]) -> None:
            payloads.append(dict(payload))
            presented.set()

        root_resolver.set_request_presenter(present)
        sessions: list[PendingApprovalSession] = []
        runtimes: list[_Runtime] = []

        def build_runtime(**kwargs: object) -> _Runtime:
            session = PendingApprovalSession(kwargs["approval_resolver"])
            runtime = _Runtime(session)
            sessions.append(session)
            runtimes.append(runtime)
            return runtime

        spec = coding_read_only_agent_types(maximum_children=1).resolve("explorer")
        assert spec is not None
        control = MultiAgentControl(agent_types=AgentTypeRegistry((spec,)))
        runtime = SessionMultiAgentRuntime(
            control=control,
            child_factory=CodingSubagentFactory(
                session_dir=tmp_path / "sessions",
                cwd=tmp_path,
                tool_registry=_tool_registry(*spec.allowed_tools),
                runtime_builder=build_runtime,
                approval_resolver=root_resolver,
            ),
        )
        caller = AgentCaller(control.root_ref)
        child = await runtime.spawn_child(
            caller=caller,
            parent_path=AgentPath.root(),
            name="pending",
            agent_type="explorer",
            initial_prompt="Request the controlled deletion.",
        )
        await presented.wait()
        assert len(root_resolver.permissions_snapshot().pending) == 1

        if release_mode == "escape":
            action_id = payloads[0]["action_id"]
            assert isinstance(action_id, str)
            assert await root_resolver.handle_result(
                action_id,
                outcome="abort",
            )
            record = await runtime.await_terminal(
                caller=caller,
                target=child.path,
                timeout=1,
            )
            assert record.status == "failed"
        elif release_mode == "interrupt_agent":
            record = await runtime.interrupt_agent(
                caller=caller,
                target=child.path,
            )
            assert record.status == "interrupted"
        elif release_mode == "close_agent":
            result = await runtime.close_agent(caller=caller, target=child.path)
            assert [record.status for record in result.closed] == ["closed"]
        elif release_mode in {"new", "resume"}:
            hook = compose_multiagent_before_release(
                resolve_runtime=lambda _session: runtime,
            )
            await hook(
                object(),
                None,
                SimpleNamespace(reason=release_mode),
            )
        else:
            await runtime.dispose()

        await asyncio.sleep(0)
        assert root_resolver.permissions_snapshot().pending == ()
        assert sessions[0].effect_calls == 0
        current = control.registry.get(child.ref, include_closed=True)
        assert current is not None
        assert current.status != "running"

        await runtime.dispose()
        assert runtimes[0].dispose_calls == 1

    asyncio.run(scenario())


def test_coding_recipe_context_is_fresh_read_only_and_role_specific() -> None:
    registry = coding_read_only_agent_types()

    plan = coding_recipe_context_plan(
        agent_type="critic",
        model="provider/critic-model",
        agent_types=registry,
    )

    assert plan.model == "provider/critic-model"
    assert plan.history.effective_tier == ForkTier.none()
    assert plan.history.messages == ()
    assert plan.allowed_tools == ("read", "grep", "find", "ls")
    assert "critical side" in plan.system_prompt


def test_factory_builds_a_non_persistent_child_and_uses_existing_session_rounds(
    tmp_path: Path,
) -> None:
    session = _Session(
        responses=[
            _assistant(
                "Initial finding.",
                input_tokens=11,
                output_tokens=5,
                cache_read=3,
                tool_call=True,
            ),
            _assistant("Follow-up finding.", input_tokens=19, output_tokens=7),
        ]
    )
    runtime = _Runtime(session)
    captured: dict[str, object] = {}

    def build_runtime(**kwargs: object) -> _Runtime:
        captured.update(kwargs)
        return runtime

    spec = AgentTypeSpec(
        name="reviewer",
        default_model="provider:test-endpoint:model",
        allowed_tools=("read", "grep", "find", "ls"),
    )
    factory = CodingSubagentFactory(
        session_dir=tmp_path / "sessions",
        cwd=tmp_path,
        tool_registry=_tool_registry("read", "grep", "find", "ls"),
        runtime_builder=build_runtime,
    )

    async def scenario() -> None:
        request = _request(spec=spec)
        binding = await factory.create(request)
        driver = binding.driver
        initial = AgentInputMessage(
            message_id="initial",
            sender=HostCaller(),
            recipient_ref=request.record.ref,
            kind="follow_up",
            text="Review this design.",
        )
        driver.deliver(initial)
        first = await driver.run_round(round_id=1, mode="prompt")

        follow_up = AgentInputMessage(
            message_id="follow-up",
            sender=HostCaller(),
            recipient_ref=request.record.ref,
            kind="follow_up",
            text="Check the lifecycle too.",
        )
        driver.deliver(follow_up)
        second = await driver.run_round(round_id=2, mode="continue")
        driver.abort()
        await driver.dispose()

        assert first.status == "completed"
        assert first.final_message == "Initial finding."
        assert first.latest_input_tokens == 14
        assert first.output_tokens == 5
        assert first.tool_uses == 1
        assert second.final_message == "Follow-up finding."

    asyncio.run(scenario())

    assert captured["persist"] is False
    assert captured["sandbox_workspace_writable"] is False
    assert captured["model"] == ModelSelection(
        endpoint_id="test-endpoint", provider="provider", model_id="model"
    )
    assert captured["allowed_tool_names"] == ["read", "grep", "find", "ls"]
    assert captured["active_tool_names"] == ["read", "grep", "find", "ls"]
    assert [
        definition.name for definition in captured["tool_registry"].list_definitions()
    ] == ["read", "grep", "find", "ls"]
    assert "independent read-only code reviewer" in str(captured["system_prompt"])
    assert runtime.create_cwds == [str(tmp_path.resolve())]
    assert session.prompt_calls == [("Review this design.", "multiagent:initial")]
    assert session.follow_ups == ["Check the lifecycle too."]
    assert session.abort_calls == 1
    assert runtime.dispose_calls == 1


def test_factory_installs_forked_history_and_cannot_widen_tools(
    tmp_path: Path,
) -> None:
    history_message = UserMessage(role="user", content="Earlier context", timestamp=0)
    history = ForkedHistory(
        requested_tier=ForkTier.all(),
        effective_tier=ForkTier.all(),
        watermark=None,
        messages=(history_message,),
    )
    plan = SubagentContextPlan(
        system_prompt="Bounded reviewer prompt",
        model="provider:test-endpoint:other",
        history=history,
        allowed_tools=("read",),
    )
    session = _Session(responses=[_assistant("Done.", input_tokens=1, output_tokens=1)])
    runtime = _Runtime(session)
    captured: dict[str, object] = {}

    def build_runtime(**kwargs: object) -> _Runtime:
        captured.update(kwargs)
        return runtime

    spec = AgentTypeSpec(
        name="reviewer",
        allowed_tools=("read", "grep"),
    )
    factory = CodingSubagentFactory(
        session_dir=tmp_path / "sessions",
        cwd=tmp_path,
        tool_registry=_tool_registry("read", "grep"),
        runtime_builder=build_runtime,
    )
    asyncio.run(factory.create(_request(spec=spec, context_plan=plan)))

    assert session.agent.state.messages == [history_message]
    assert captured["system_prompt"] == "Bounded reviewer prompt"
    assert captured["model"] == ModelSelection(
        endpoint_id="test-endpoint", provider="provider", model_id="other"
    )
    assert captured["allowed_tool_names"] == ["read"]

    widened = SubagentContextPlan(
        system_prompt="Bounded reviewer prompt",
        model=None,
        history=history,
        allowed_tools=("write",),
    )
    with pytest.raises(ValueError, match="non-admitted Coding tools: write"):
        asyncio.run(factory.create(_request(spec=spec, context_plan=widened)))


def test_failed_child_creation_disposes_the_non_persistent_runtime(
    tmp_path: Path,
) -> None:
    runtime = _FailingRuntime(
        _Session(responses=[_assistant("Unused.", input_tokens=0, output_tokens=0)])
    )
    factory = CodingSubagentFactory(
        session_dir=tmp_path / "sessions",
        cwd=tmp_path,
        tool_registry=_tool_registry("read"),
        runtime_builder=lambda **_kwargs: runtime,
    )
    spec = AgentTypeSpec(name="reviewer", allowed_tools=("read",))

    with pytest.raises(RuntimeError, match="child session failed"):
        asyncio.run(factory.create(_request(spec=spec)))

    assert runtime.dispose_calls == 1


def test_factory_runs_isolated_types_in_a_lease_and_reports_changes(
    tmp_path: Path,
) -> None:
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    workspace = _WorkspaceLeases(isolated)
    session = _Session(
        responses=[_assistant("Implemented.", input_tokens=3, output_tokens=4)]
    )
    runtime = _Runtime(session)
    captured: dict[str, object] = {}

    def build_runtime(**kwargs: object) -> _Runtime:
        captured.update(kwargs)
        return runtime

    spec = AgentTypeSpec(
        name="implementation_worker",
        allowed_tools=("read", "write"),
        workspace_mode="isolated",
    )
    factory = CodingSubagentFactory(
        session_dir=tmp_path / "sessions",
        cwd=tmp_path,
        tool_registry=_tool_registry("read", "write"),
        runtime_builder=build_runtime,
        workspace_leases=workspace,
    )

    async def scenario() -> None:
        request = _request(spec=spec)
        binding = await factory.create(request)
        driver = binding.driver
        assert binding.workspace_ref == "git-workspace:test"
        driver.deliver(
            AgentInputMessage(
                message_id="initial",
                sender=HostCaller(),
                recipient_ref=request.record.ref,
                kind="follow_up",
                text="Implement it.",
            )
        )
        result = await driver.run_round(round_id=1, mode="prompt")
        dispose_result = await driver.dispose()

        assert result.workspace_ref == "git-workspace:test"
        assert result.artifact_refs == ("git-artifact:test",)
        assert result.change_set_ref is None
        assert dispose_result.released_workspace is not None
        assert dispose_result.released_workspace.retained is True

    asyncio.run(scenario())

    assert runtime.create_cwds == [str(isolated)]
    assert captured["sandbox_workspace_writable"] is True
    delegated = captured["delegated_execution_profile"]
    assert isinstance(delegated, DelegatedExecutionProfile)
    assert delegated.workspace_ref == "git-workspace:test"
    assert delegated.execution_profile_ceiling.writable_roots == (isolated.resolve(),)
    assert workspace.acquired[0].agent_type == "implementation_worker"
    assert workspace.released == 1


def test_factory_runs_shared_write_worker_in_the_exact_parent_worktree(
    tmp_path: Path,
) -> None:
    session = _Session(
        responses=[_assistant("Updated the copy.", input_tokens=3, output_tokens=4)]
    )
    runtime = _Runtime(session)
    captured: dict[str, object] = {}

    def build_runtime(**kwargs: object) -> _Runtime:
        captured.update(kwargs)
        return runtime

    spec = coding_agent_types().resolve("shared_implementation_worker")
    assert spec is not None
    factory = CodingSubagentFactory(
        session_dir=tmp_path / "sessions",
        cwd=tmp_path,
        tool_registry=_tool_registry(*spec.allowed_tools),
        runtime_builder=build_runtime,
        workspace_leases=None,
    )

    async def scenario() -> None:
        request = _request(spec=spec)
        binding = await factory.create(request)
        driver = binding.driver
        assert binding.workspace_ref is None
        driver.deliver(
            AgentInputMessage(
                message_id="initial",
                sender=HostCaller(),
                recipient_ref=request.record.ref,
                kind="follow_up",
                text="Fix one sentence without touching unrelated edits.",
            )
        )
        result = await driver.run_round(round_id=1, mode="prompt")
        await driver.dispose()

        assert result.final_message == "Updated the copy."
        assert result.workspace_ref is None
        assert result.change_set_ref is None

    asyncio.run(scenario())

    assert runtime.create_cwds == [str(tmp_path.resolve())]
    assert captured["allowed_tool_names"] == list(spec.allowed_tools)
    delegated = captured["delegated_execution_profile"]
    assert isinstance(delegated, DelegatedExecutionProfile)
    assert delegated.workspace_ref is None
    assert delegated.execution_profile_ceiling.writable_roots == (tmp_path.resolve(),)
    assert "sharing the parent Coding session's current worktree" in str(
        captured["system_prompt"]
    )


def test_factory_rejects_an_admitted_tool_missing_from_the_product_registry(
    tmp_path: Path,
) -> None:
    factory = CodingSubagentFactory(
        session_dir=tmp_path / "sessions",
        cwd=tmp_path,
        tool_registry=_tool_registry("read"),
        runtime_builder=lambda **_kwargs: _Runtime(
            _Session(responses=[_assistant("Unused.", input_tokens=0, output_tokens=0)])
        ),
    )
    spec = AgentTypeSpec(
        name="reviewer",
        allowed_tools=("read", "grep"),
    )

    with pytest.raises(
        ValueError,
        match="Coding child tools are not registered and enabled: grep",
    ):
        asyncio.run(factory.create(_request(spec=spec)))


def test_factory_releases_isolated_workspace_when_preflight_fails(
    tmp_path: Path,
) -> None:
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    workspace = _WorkspaceLeases(isolated, changed=False)
    runtime_built = False

    def build_runtime(**_kwargs: object) -> _Runtime:
        nonlocal runtime_built
        runtime_built = True
        return _Runtime(
            _Session(responses=[_assistant("Unused.", input_tokens=0, output_tokens=0)])
        )

    factory = CodingSubagentFactory(
        session_dir=tmp_path / "sessions",
        cwd=tmp_path,
        tool_registry=_tool_registry("read"),
        runtime_builder=build_runtime,
        workspace_leases=workspace,
    )
    spec = AgentTypeSpec(
        name="implementation_worker",
        allowed_tools=("read", "write"),
        workspace_mode="isolated",
    )

    with pytest.raises(
        ValueError,
        match="Coding child tools are not registered and enabled: write",
    ):
        asyncio.run(factory.create(_request(spec=spec)))

    assert workspace.released == 1
    assert runtime_built is False


def test_installation_binds_root_input_to_the_existing_queue() -> None:
    session = _RootSession()
    runtime = install_coding_multiagent_session(
        session,  # type: ignore[arg-type]
        child_factory=_UnusedFactory(),
        agent_types=coding_read_only_agent_types(),
    )

    asyncio.run(
        runtime.send_message(
            caller=HostCaller(),
            target=AgentPath.root(),
            text="Child result.",
        )
    )

    assert session.runtime.queue.input_queue.texts("follow_up") == ["Child result."]
    payload = session.runtime.queue.input_queue.payloads[-1]
    assert isinstance(payload, ApplicationMessage)
    assert payload.custom_type == "harness.multiagent.message"
    assert payload.display is False
    assert session.multiagent_runtime is runtime
    assert session.multiagent_input.queue is session.runtime.queue.input_queue


def test_coding_completion_notice_uses_hidden_agent_mailbox() -> None:
    session = _RootSession()
    runtime = install_coding_multiagent_session(
        session,  # type: ignore[arg-type]
        child_factory=_UnusedFactory(),
        agent_types=coding_read_only_agent_types(),
    )
    child = runtime.control.spawn(
        caller=HostCaller(),
        parent_path=AgentPath.root(),
        name="reviewer",
        agent_type="reviewer",
    )
    transition = runtime.control.begin_round(child.ref)
    assert transition.record is not None

    runtime.control.finish_round(
        child.ref,
        round_id=transition.record.round_id,
        status="completed",
        final_message="No blockers.",
        duration_ms=0,
    )

    assert session.runtime.queue.input_queue.texts("steering") == []
    assert session.runtime.queue.input_queue.texts("follow_up") == []
    assert len(session.runtime.queue.mailbox) == 1
    payload = session.runtime.queue.mailbox[0]
    assert isinstance(payload, ApplicationMessage)
    assert payload.custom_type == "harness.multiagent.completion_notice"
    assert payload.delivery_mode == "next_turn"
    assert payload.display is False
