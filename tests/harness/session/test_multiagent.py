from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace

from loushang.ai.types import AssistantMessage, TextPart, ToolCall, Usage, UserMessage
from loushang.harness.multiagent import (
    AgentCaller,
    AgentInputMessage,
    AgentPath,
    AgentTypeRegistry,
    AgentTypeSpec,
    ForkedHistory,
    ForkTier,
    HostCaller,
    MultiAgentControl,
    SubagentContextPlan,
    SubagentDisposeResult,
    SubagentRoundResult,
)
from loushang.harness.multiagent.run_handle import RoundMode
from loushang.harness.runtime import HostInputQueue
from loushang.harness.runtime.execution import HostRuntime
from loushang.harness.session.multiagent import (
    AgentInputFacade,
    AgentInputWaitOutcome,
    SessionMultiAgentRuntime,
    SessionSubagentBinding,
    SessionSubagentDriver,
    SessionSubagentRequest,
    agent_input_application_message,
    bind_agent_session_multiagent,
    compose_multiagent_before_release,
    install_agent_forked_history,
    project_agent_round_result,
)
from loushang.harness.transcript import ApplicationMessage

NOW = datetime(2026, 7, 26, tzinfo=UTC)
HOST = HostCaller()


class _Driver:
    def __init__(self) -> None:
        self.messages: list[AgentInputMessage] = []
        self.calls: list[tuple[int, RoundMode]] = []
        self.pending: list[asyncio.Future[SubagentRoundResult]] = []
        self.abort_calls = 0
        self.dispose_calls = 0

    def deliver(self, message: AgentInputMessage) -> None:
        self.messages.append(message)

    async def run_round(
        self,
        *,
        round_id: int,
        mode: RoundMode,
    ) -> SubagentRoundResult:
        self.calls.append((round_id, mode))
        future = asyncio.get_running_loop().create_future()
        self.pending.append(future)
        return await future

    def abort(self) -> None:
        self.abort_calls += 1
        if self.pending and not self.pending[-1].done():
            self.pending[-1].set_result(
                SubagentRoundResult(
                    status="interrupted",
                    final_message="Interrupted.",
                )
            )

    async def dispose(self) -> SubagentDisposeResult:
        self.dispose_calls += 1
        return SubagentDisposeResult()

    def complete(self, message: str = "Done.", *, summary: str | None = None) -> None:
        self.pending[-1].set_result(
            SubagentRoundResult(
                status="completed",
                final_message=message,
                summary=summary,
            )
        )


class _Factory:
    def __init__(self) -> None:
        self.drivers: dict[AgentPath, _Driver] = {}
        self.requests: list[SessionSubagentRequest] = []

    async def create(self, request: SessionSubagentRequest) -> SessionSubagentBinding:
        self.requests.append(request)
        driver = _Driver()
        self.drivers[request.record.path] = driver
        return SessionSubagentBinding(driver=driver)


class _FailingFactory:
    async def create(
        self,
        _request: SessionSubagentRequest,
    ) -> SessionSubagentBinding:
        raise RuntimeError("child construction failed")


class _WorkspaceFactory:
    def __init__(self) -> None:
        self.driver = _Driver()

    async def create(
        self,
        _request: SessionSubagentRequest,
    ) -> SessionSubagentBinding:
        return SessionSubagentBinding(
            driver=self.driver,
            workspace_ref="coding-worktree:reviewer",
        )


class _InputActivity:
    def __init__(self) -> None:
        self.calls: list[tuple[int | None, float | None]] = []

    async def wait_for_activity(
        self,
        *,
        after_sequence: int | None = None,
        timeout: float | None = None,
    ) -> AgentInputWaitOutcome:
        self.calls.append((after_sequence, timeout))
        return AgentInputWaitOutcome(None, timed_out=True)


class _InputActivityFactory:
    def __init__(self) -> None:
        self.driver = _Driver()
        self.input_activity = _InputActivity()

    async def create(
        self,
        _request: SessionSubagentRequest,
    ) -> SessionSubagentBinding:
        return SessionSubagentBinding(
            driver=self.driver,
            input_activity=self.input_activity,
        )


def _control() -> MultiAgentControl:
    return MultiAgentControl(
        agent_types=AgentTypeRegistry(
            (
                AgentTypeSpec(
                    name="coordinator",
                    can_spawn=True,
                    maximum_children=2,
                ),
                AgentTypeSpec(name="reviewer", maximum_children=3),
            )
        ),
        clock=lambda: NOW,
    )


async def _yield_until(predicate: Callable[[], bool]) -> None:
    for _ in range(30):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition was not reached")


def test_input_facade_reuses_host_queue_and_wakes_activity_waiters() -> None:
    async def scenario() -> None:
        queue: HostInputQueue[AgentInputMessage] = HostInputQueue()
        facade = AgentInputFacade(
            queue=queue,
            build_payload=lambda message: message,
            submit_mailbox=queue.append_next_turn,
        )
        observed = facade.activity_sequence
        waiting = asyncio.create_task(
            facade.wait_for_activity(after_sequence=observed, timeout=1)
        )
        await asyncio.sleep(0)
        message = AgentInputMessage(
            message_id="m1",
            sender=HOST,
            recipient_ref=_control().root_ref,
            kind="follow_up",
            text="Hello.",
        )

        facade.enqueue_message(message)
        outcome = await waiting

        assert queue.texts("follow_up") == ["Hello."]
        assert outcome.timed_out is False
        assert outcome.activity is not None
        assert outcome.activity.kind == "message"

    asyncio.run(scenario())


def test_input_wait_times_out_normally_and_user_steer_wakes_the_next_wait() -> None:
    async def scenario() -> None:
        queue: HostInputQueue[AgentInputMessage] = HostInputQueue()
        facade = AgentInputFacade(
            queue=queue,
            build_payload=lambda message: message,
            submit_mailbox=queue.append_next_turn,
        )

        timed_out = await facade.wait_for_activity(timeout=0)
        observed = facade.activity_sequence
        waiting = asyncio.create_task(
            facade.wait_for_activity(after_sequence=observed, timeout=1)
        )
        await asyncio.sleep(0)
        facade.notify_steered("user-steer-1")
        steered = await waiting

        assert timed_out.timed_out is True
        assert steered.activity is not None
        assert steered.activity.kind == "steered"
        assert steered.activity.message_id == "user-steer-1"

    asyncio.run(scenario())


def test_session_driver_composes_the_existing_queue_and_host_runtime() -> None:
    async def scenario() -> None:
        queue: HostInputQueue[AgentInputMessage] = HostInputQueue()
        facade = AgentInputFacade(
            queue=queue,
            build_payload=lambda message: message,
            submit_mailbox=queue.append_next_turn,
        )
        calls: list[tuple[int, RoundMode]] = []

        async def run_round(
            round_id: int,
            mode: RoundMode,
        ) -> SubagentRoundResult:
            calls.append((round_id, mode))
            return SubagentRoundResult(
                status="completed",
                final_message="Done.",
            )

        driver = SessionSubagentDriver(
            input_facade=facade,
            run_round=run_round,
            host_runtime=HostRuntime(),
        )
        message = AgentInputMessage(
            message_id="m1",
            sender=HOST,
            recipient_ref=_control().root_ref,
            kind="steering",
            text="Inspect this.",
        )

        driver.deliver(message)
        result = await driver.run_round(round_id=1, mode="prompt")
        await driver.dispose()

        assert queue.texts("steering") == ["Inspect this."]
        assert result.status == "completed"
        assert calls == [(1, "prompt")]

    asyncio.run(scenario())


def test_child_completion_uses_root_mailbox_without_starting_a_root_turn() -> None:
    async def scenario() -> None:
        control = _control()
        factory = _Factory()
        root_queue: HostInputQueue[AgentInputMessage] = HostInputQueue()
        root_input = AgentInputFacade(
            queue=root_queue,
            build_payload=lambda message: message,
            submit_mailbox=root_queue.append_next_turn,
        )
        runtime = SessionMultiAgentRuntime(
            control=control,
            child_factory=factory,
            root_input=root_input,
        )

        child = await runtime.spawn_child(
            caller=HOST,
            parent_path=AgentPath.root(),
            name="reviewer",
            agent_type="reviewer",
            initial_prompt="Review this.",
        )
        driver = factory.drivers[child.path]
        await _yield_until(lambda: len(driver.calls) == 1)
        driver.complete("No blockers.", summary="Looks safe")
        terminal = await runtime.await_terminal(
            caller=HOST,
            target=child.path,
        )

        assert terminal.status == "completed"
        assert driver.calls == [(1, "prompt")]
        assert root_queue.pending_count == 0
        assert root_queue.texts("steering") == []
        assert root_queue.texts("follow_up") == []
        mailbox = root_queue.drain_next_turn()
        assert len(mailbox) == 1
        assert mailbox[0].kind == "mailbox"
        assert "Looks safe" in mailbox[0].text
        await runtime.dispose()

    asyncio.run(scenario())


def test_child_completion_uses_mailbox_while_root_is_running() -> None:
    async def scenario() -> None:
        control = _control()
        factory = _Factory()
        root_queue: HostInputQueue[AgentInputMessage] = HostInputQueue()
        root_input = AgentInputFacade(
            queue=root_queue,
            build_payload=lambda message: message,
            submit_mailbox=root_queue.append_next_turn,
        )
        runtime = SessionMultiAgentRuntime(
            control=control,
            child_factory=factory,
            root_input=root_input,
            root_is_active=lambda: True,
        )

        child = await runtime.spawn_child(
            caller=HOST,
            parent_path=AgentPath.root(),
            name="reviewer",
            agent_type="reviewer",
            initial_prompt="Review this.",
        )
        driver = factory.drivers[child.path]
        await _yield_until(lambda: len(driver.calls) == 1)
        driver.complete("No blockers.", summary="Looks safe")
        await runtime.await_terminal(caller=HOST, target=child.path)

        assert root_queue.texts("follow_up") == []
        assert root_queue.texts("steering") == []
        mailbox = root_queue.drain_next_turn()
        assert len(mailbox) == 1
        assert mailbox[0].kind == "mailbox"
        assert "Looks safe" in mailbox[0].text
        await runtime.dispose()

    asyncio.run(scenario())


def test_host_can_await_the_exact_child_completion_payload() -> None:
    async def scenario() -> None:
        control = _control()
        factory = _Factory()
        runtime = SessionMultiAgentRuntime(
            control=control,
            child_factory=factory,
            notice_wake_policy="discard",
        )
        child = await runtime.spawn_child(
            caller=HOST,
            parent_path=AgentPath.root(),
            name="reviewer",
            agent_type="reviewer",
            initial_prompt="Review.",
        )
        await _yield_until(lambda: bool(factory.drivers[child.path].pending))
        factory.drivers[child.path].complete(
            "Full reviewer response.",
            summary="Short summary.",
        )

        notice = await runtime.await_completion(
            caller=HOST,
            target=child.path,
            timeout=1,
        )

        assert notice.terminal.final_message == "Full reviewer response."
        assert notice.summary == "Short summary."
        await runtime.dispose()

    asyncio.run(scenario())


def test_failed_child_construction_closes_the_incarnation_and_releases_capacity() -> (
    None
):
    async def scenario() -> None:
        control = _control()
        runtime = SessionMultiAgentRuntime(
            control=control,
            child_factory=_FailingFactory(),
        )

        try:
            await runtime.spawn_child(
                caller=HOST,
                parent_path=AgentPath.root(),
                name="reviewer",
                agent_type="reviewer",
                initial_prompt="Review.",
            )
        except RuntimeError as error:
            assert str(error) == "child construction failed"
        else:
            raise AssertionError("spawn should fail")

        closed = control.registry.current(
            AgentPath.root().child("reviewer"),
            include_closed=True,
        )
        assert closed is not None
        assert closed.status == "closed"
        assert control.registry.open_count == 1

    asyncio.run(scenario())


def test_spawn_projects_the_product_workspace_before_the_first_round() -> None:
    async def scenario() -> None:
        control = _control()
        factory = _WorkspaceFactory()
        runtime = SessionMultiAgentRuntime(
            control=control,
            child_factory=factory,
            notice_wake_policy="discard",
        )

        child = await runtime.spawn_child(
            caller=HOST,
            parent_path=AgentPath.root(),
            name="reviewer",
            agent_type="reviewer",
            initial_prompt="Review.",
        )

        assert child.workspace_ref == "coding-worktree:reviewer"
        assert [fact.kind for fact in control.facts()][:3] == [
            "spawned",
            "workspace",
            "status_changed",
        ]
        await _yield_until(lambda: bool(factory.driver.pending))
        factory.driver.complete()
        await runtime.dispose()

    asyncio.run(scenario())


def test_spawn_binds_an_input_activity_port_without_concrete_facade_checks() -> None:
    async def scenario() -> None:
        control = _control()
        factory = _InputActivityFactory()
        runtime = SessionMultiAgentRuntime(
            control=control,
            child_factory=factory,
            notice_wake_policy="discard",
        )

        child = await runtime.spawn_child(
            caller=HOST,
            parent_path=AgentPath.root(),
            name="reviewer",
            agent_type="reviewer",
            initial_prompt="Review.",
        )
        outcome = await runtime.wait_for_input(
            caller=AgentCaller(child.ref),
            after_sequence=7,
            timeout=0.5,
        )

        assert outcome.timed_out is True
        assert factory.input_activity.calls == [(7, 0.5)]
        await _yield_until(lambda: bool(factory.driver.pending))
        factory.driver.complete()
        await runtime.dispose()

    asyncio.run(scenario())


def test_root_completion_wake_requires_explicit_policy_and_callback() -> None:
    async def scenario() -> None:
        control = _control()
        factory = _Factory()
        root_queue: HostInputQueue[AgentInputMessage] = HostInputQueue()
        root_input = AgentInputFacade(
            queue=root_queue,
            build_payload=lambda message: message,
            submit_mailbox=root_queue.append_next_turn,
        )
        wakes = 0

        async def wake_root() -> None:
            nonlocal wakes
            wakes += 1

        runtime = SessionMultiAgentRuntime(
            control=control,
            child_factory=factory,
            root_input=root_input,
            root_notice_wake=wake_root,
            notice_wake_policy="wake_if_idle",
        )
        child = await runtime.spawn_child(
            caller=HOST,
            parent_path=AgentPath.root(),
            name="reviewer",
            agent_type="reviewer",
            initial_prompt="Review.",
        )
        driver = factory.drivers[child.path]
        await _yield_until(lambda: bool(driver.pending))
        driver.complete()
        await runtime.await_terminal(caller=HOST, target=child.path)
        await runtime.drain_notice_deliveries()

        assert root_queue.pending_count == 0
        assert len(root_queue.drain_next_turn()) == 1
        assert wakes == 1
        await runtime.dispose()

    asyncio.run(scenario())


def test_completion_notice_to_child_parent_is_queue_only_by_default() -> None:
    async def scenario() -> None:
        control = _control()
        factory = _Factory()
        runtime = SessionMultiAgentRuntime(
            control=control,
            child_factory=factory,
        )
        parent = await runtime.spawn_child(
            caller=HOST,
            parent_path=AgentPath.root(),
            name="coordinator",
            agent_type="coordinator",
            initial_prompt="Coordinate.",
        )
        parent_driver = factory.drivers[parent.path]
        await _yield_until(lambda: len(parent_driver.calls) == 1)
        parent_driver.complete()
        await runtime.await_terminal(caller=HOST, target=parent.path)

        child = await runtime.spawn_child(
            caller=AgentCaller(parent.ref),
            parent_path=parent.path,
            name="reviewer",
            agent_type="reviewer",
            initial_prompt="Review.",
        )
        child_driver = factory.drivers[child.path]
        await _yield_until(lambda: len(child_driver.calls) == 1)
        child_driver.complete("Finding.")
        await runtime.await_terminal(
            caller=AgentCaller(parent.ref),
            target=child.path,
        )
        await runtime.drain_notice_deliveries()

        assert len(parent_driver.calls) == 1
        assert parent_driver.messages[-1].message_id.startswith("completion:")
        assert parent_driver.messages[-1].kind == "mailbox"
        await runtime.dispose()

    asyncio.run(scenario())


def test_notice_drain_removes_an_already_finished_task_without_spinning() -> None:
    async def scenario() -> None:
        runtime = SessionMultiAgentRuntime(
            control=_control(),
            child_factory=_Factory(),
        )
        task = asyncio.create_task(asyncio.sleep(0))
        await task
        runtime._notice_tasks.add(task)

        await asyncio.wait_for(runtime.drain_notice_deliveries(), timeout=0.1)

        assert runtime._notice_tasks == set()

    asyncio.run(scenario())


def test_follow_up_after_terminal_uses_the_same_tracked_handle() -> None:
    async def scenario() -> None:
        control = _control()
        factory = _Factory()
        runtime = SessionMultiAgentRuntime(
            control=control,
            child_factory=factory,
        )
        child = await runtime.spawn_child(
            caller=HOST,
            parent_path=AgentPath.root(),
            name="reviewer",
            agent_type="reviewer",
            initial_prompt="First.",
        )
        driver = factory.drivers[child.path]
        await _yield_until(lambda: len(driver.calls) == 1)
        driver.complete("First done.")
        await runtime.await_terminal(caller=HOST, target=child.path)

        delivery = await runtime.send_message(
            caller=HOST,
            target=child.path,
            text="Second.",
        )
        await _yield_until(lambda: len(driver.calls) == 2)
        driver.complete("Second done.")
        terminal = await runtime.await_terminal(caller=HOST, target=child.path)

        assert delivery.triggered_new_round is True
        assert driver.calls == [(1, "prompt"), (2, "continue")]
        assert terminal.round_id == 2
        await runtime.dispose()

    asyncio.run(scenario())


def test_recursive_close_interrupts_and_disposes_deepest_first() -> None:
    async def scenario() -> None:
        control = _control()
        factory = _Factory()
        runtime = SessionMultiAgentRuntime(
            control=control,
            child_factory=factory,
        )
        parent = await runtime.spawn_child(
            caller=HOST,
            parent_path=AgentPath.root(),
            name="coordinator",
            agent_type="coordinator",
            initial_prompt="Coordinate.",
        )
        child = await runtime.spawn_child(
            caller=AgentCaller(parent.ref),
            parent_path=parent.path,
            name="reviewer",
            agent_type="reviewer",
            initial_prompt="Review.",
        )
        await _yield_until(
            lambda: all(
                factory.drivers[path].pending for path in (parent.path, child.path)
            )
        )

        result = await runtime.close_agent(caller=HOST, target=parent.path)

        assert [record.path for record in result.closed] == [
            child.path,
            parent.path,
        ]
        assert factory.drivers[child.path].dispose_calls == 1
        assert factory.drivers[parent.path].dispose_calls == 1
        assert control.registry.get(control.root_ref).status == "idle"

    asyncio.run(scenario())


def test_before_release_hook_closes_children_then_calls_existing_hook() -> None:
    async def scenario() -> None:
        control = _control()
        factory = _Factory()
        runtime = SessionMultiAgentRuntime(
            control=control,
            child_factory=factory,
        )
        child = await runtime.spawn_child(
            caller=HOST,
            parent_path=AgentPath.root(),
            name="reviewer",
            agent_type="reviewer",
            initial_prompt="Review.",
        )
        await _yield_until(lambda: bool(factory.drivers[child.path].pending))
        order: list[str] = []

        async def existing(
            _session: object,
            _target: object | None,
            _transition: object,
        ) -> None:
            assert (
                control.registry.get(child.ref, include_closed=True).status == "closed"
            )
            order.append("existing")

        hook = compose_multiagent_before_release(
            resolve_runtime=lambda _session: runtime,
            existing=existing,
        )
        await hook(object(), None, object())

        assert order == ["existing"]
        assert factory.drivers[child.path].dispose_calls == 1

    asyncio.run(scenario())


def test_standard_agent_session_binding_reuses_the_root_input_queue() -> None:
    queue: HostInputQueue[ApplicationMessage] = HostInputQueue()
    session = SimpleNamespace(
        runtime=SimpleNamespace(
            queue=SimpleNamespace(input_queue=queue),
            is_active=False,
        )
    )

    runtime = bind_agent_session_multiagent(
        session,
        child_factory=_Factory(),
        agent_types=AgentTypeRegistry((AgentTypeSpec(name="reviewer"),)),
    )
    asyncio.run(
        runtime.send_message(
            caller=HOST,
            target=AgentPath.root(),
            text="Review this.",
        )
    )

    assert queue.texts("follow_up") == ["Review this."]
    assert session.multiagent_runtime is runtime
    assert session.multiagent_input.queue is queue


def test_agent_input_projection_preserves_routing_metadata() -> None:
    control = _control()
    child = control.spawn(
        caller=HOST,
        parent_path=AgentPath.root(),
        name="reviewer",
        agent_type="reviewer",
    )

    payload = agent_input_application_message(
        AgentInputMessage(
            message_id="completion:notice-1",
            sender=AgentCaller(child.ref),
            recipient_ref=control.root_ref,
            kind="mailbox",
            text="Done.",
            references=("artifact:1",),
        )
    )

    assert payload.custom_type == "harness.multiagent.completion_notice"
    assert payload.delivery_mode == "next_turn"
    assert payload.details == {
        "sender": str(child.path),
        "recipient": "/root",
        "references": ["artifact:1"],
    }


def test_standard_agent_history_and_round_projection_are_product_neutral() -> None:
    user = UserMessage(role="user", content="Review.", timestamp=0)
    state = SimpleNamespace(messages=())
    state.set_messages = lambda messages: setattr(state, "messages", tuple(messages))
    session = SimpleNamespace(agent=SimpleNamespace(state=state))
    plan = SubagentContextPlan(
        system_prompt="Review carefully.",
        model=None,
        history=ForkedHistory(
            requested_tier=ForkTier.all(),
            effective_tier=ForkTier.all(),
            watermark=None,
            messages=(user,),
        ),
    )
    install_agent_forked_history(session, plan)

    assistant = AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[
            TextPart(type="text", text="No blockers."),
            ToolCall(type="toolCall", id="tool-1", name="read", arguments={}),
        ],
        api="test",
        provider="test",
        model="test",
        response_id=None,
        usage=Usage(
            input=8,
            output=3,
            cache_read=2,
            cache_write=0,
            total_tokens=13,
            cost=None,
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=0,
    )
    result = project_agent_round_result((user, assistant))

    assert state.messages == (user,)
    assert result.status == "completed"
    assert result.final_message == "No blockers."
    assert result.latest_input_tokens == 10
    assert result.output_tokens == 3
    assert result.tool_uses == 1
