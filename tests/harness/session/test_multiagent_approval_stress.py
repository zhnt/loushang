from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import Awaitable, Callable
from itertools import product
from random import Random

from loushang.harness.approval import (
    ActorBoundApprovalResolver,
    HeadlessApprovalResolver,
    InteractiveApprovalResolver,
)
from loushang.harness.multiagent import (
    AgentInputMessage,
    AgentPath,
    AgentRef,
    AgentTypeRegistry,
    AgentTypeSpec,
    HostCaller,
    MultiAgentControl,
    SubagentDisposeResult,
    SubagentRoundResult,
)
from loushang.harness.multiagent.run_handle import RoundMode
from loushang.harness.policy import PolicyDecision
from loushang.harness.session.multiagent import (
    SessionMultiAgentRuntime,
    SessionSubagentBinding,
    SessionSubagentRequest,
)
from loushang.harness.tools import (
    FilesystemActionAdapter,
    ToolContext,
    ToolRegistry,
    authorized_tool,
    tool,
)
from loushang.harness.tools.workspace.authorization import (
    create_workspace_tool_execution_host,
)

HOST = HostCaller()


class _AskForStressEffect:
    def evaluate(self, _subject: object) -> PolicyDecision:
        return PolicyDecision.ask(
            "Confirm the protected stress effect",
            code="stress_effect",
        )


class _ApprovalStressDriver:
    def __init__(
        self,
        *,
        ref: AgentRef,
        resolver: InteractiveApprovalResolver,
        effect_calls: dict[AgentRef, int],
        cycle: int,
    ) -> None:
        self.ref = ref
        self._approval = ActorBoundApprovalResolver(
            resolver=resolver,
            actor_id=str(ref),
        )
        self._effect_calls = effect_calls
        self._cycle = cycle
        self.audit_events: list[dict[str, object]] = []
        self.messages: list[AgentInputMessage] = []
        self.dispose_calls = 0

        @tool(name="delete_stress_target")
        async def delete_stress_target(
            path: str,
            context: ToolContext,
        ) -> str:
            del context
            # Leave one scheduling boundary after authorization so lifecycle
            # operations can race the admitted effect.
            await asyncio.sleep(0)
            self._effect_calls[self.ref] += 1
            return path

        definition = authorized_tool(
            delete_stress_target,
            action=FilesystemActionAdapter("delete"),
        )
        registry = ToolRegistry(
            execution_host=create_workspace_tool_execution_host(
                policy_evaluator=_AskForStressEffect(),
                approval_resolver=self._approval,
            )
        )
        registry.register_tool(definition)
        self._tool = registry.materialize_definitions(
            [definition],
            context_provider=lambda *, tool_call_id: ToolContext(
                tool_call_id=tool_call_id,
                event_sink=self.audit_events.append,
            ),
        )[0]

    def deliver(self, message: AgentInputMessage) -> None:
        self.messages.append(message)

    async def run_round(
        self,
        *,
        round_id: int,
        mode: RoundMode,
    ) -> SubagentRoundResult:
        del mode
        self._approval.open_session()
        result = await self._tool.execute(
            f"stress-{self._cycle}-{self.ref}-round-{round_id}",
            {"path": (f"/tmp/stress-target-{self._cycle}-{self.ref.path.name}")},
        )
        return SubagentRoundResult(
            status="completed",
            final_message=str(result.details),
        )

    def abort(self) -> None:
        self._approval.close_session("Child agent interrupted")

    async def dispose(self) -> SubagentDisposeResult:
        self.dispose_calls += 1
        self._approval.end_session("Child agent closed")
        return SubagentDisposeResult()


class _ApprovalStressFactory:
    def __init__(
        self,
        *,
        resolver: InteractiveApprovalResolver,
        effect_calls: dict[AgentRef, int],
        cycle: int,
    ) -> None:
        self._resolver = resolver
        self._effect_calls = effect_calls
        self._cycle = cycle
        self.drivers: dict[AgentRef, _ApprovalStressDriver] = {}

    async def create(
        self,
        request: SessionSubagentRequest,
    ) -> SessionSubagentBinding:
        driver = _ApprovalStressDriver(
            ref=request.record.ref,
            resolver=self._resolver,
            effect_calls=self._effect_calls,
            cycle=self._cycle,
        )
        self.drivers[request.record.ref] = driver
        return SessionSubagentBinding(driver=driver)


async def _wait_until(predicate: Callable[[], bool]) -> None:
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("approval stress condition was not reached")


async def _after_ticks(
    ticks: int,
    operation: Callable[[], Awaitable[object]],
) -> object:
    for _ in range(ticks):
        await asyncio.sleep(0)
    return await operation()


def test_concurrent_child_approval_races_preserve_lifecycle_invariants() -> None:
    async def scenario() -> None:
        cases = list(
            product(
                ("allow_once", "deny", "abort"),
                ("allow_once", "deny", "abort"),
                ("interrupt", "close"),
            )
        )
        cases *= 2
        random = Random(20260729)
        random.shuffle(cases)

        for cycle, (first_outcome, second_outcome, lifecycle) in enumerate(cases):
            payloads: list[dict[str, object]] = []
            resolver = InteractiveApprovalResolver(
                fallback=HeadlessApprovalResolver(mode="deny")
            )
            resolver.set_request_presenter(
                lambda payload, payloads=payloads: payloads.append(dict(payload))
            )
            effect_calls: dict[AgentRef, int] = defaultdict(int)
            spec = AgentTypeSpec(name="worker", maximum_children=2)
            control = MultiAgentControl(agent_types=AgentTypeRegistry((spec,)))
            factory = _ApprovalStressFactory(
                resolver=resolver,
                effect_calls=effect_calls,
                cycle=cycle,
            )
            runtime = SessionMultiAgentRuntime(
                control=control,
                child_factory=factory,
            )

            first, second = await asyncio.gather(
                runtime.spawn_child(
                    caller=HOST,
                    parent_path=AgentPath.root(),
                    name="worker-a",
                    agent_type="worker",
                    initial_prompt="Request the first protected effect.",
                ),
                runtime.spawn_child(
                    caller=HOST,
                    parent_path=AgentPath.root(),
                    name="worker-b",
                    agent_type="worker",
                    initial_prompt="Request the second protected effect.",
                ),
            )
            await _wait_until(lambda payloads=payloads: len(payloads) == 2)
            by_actor = {str(payload["actor_id"]): payload for payload in payloads}
            assert set(by_actor) == {str(first.ref), str(second.ref)}
            first_action = str(by_actor[str(first.ref)]["action_id"])
            second_action = str(by_actor[str(second.ref)]["action_id"])
            assert first_action != second_action

            first_accepted = await resolver.handle_result(
                first_action,
                outcome=first_outcome,  # type: ignore[arg-type]
            )

            async def resolve_second(
                resolver=resolver,
                second_action=second_action,
                second_outcome=second_outcome,
            ) -> object:
                return await resolver.handle_result(
                    second_action,
                    outcome=second_outcome,  # type: ignore[arg-type]
                )

            async def release_second(
                lifecycle=lifecycle,
                runtime=runtime,
                second=second,
            ) -> object:
                if lifecycle == "interrupt":
                    return await runtime.interrupt_agent(
                        caller=HOST,
                        target=second.path,
                    )
                return await runtime.close_agent(
                    caller=HOST,
                    target=second.path,
                )

            second_accepted, _ = await asyncio.gather(
                _after_ticks(random.randrange(3), resolve_second),
                _after_ticks(random.randrange(3), release_second),
            )
            first_terminal = await runtime.await_terminal(
                caller=HOST,
                target=first.path,
                timeout=1,
            )
            assert first_terminal.status != "running"
            if lifecycle == "interrupt":
                second_terminal = control.registry.get(
                    second.ref,
                    include_closed=True,
                )
                assert second_terminal is not None
                # The approval result and interrupt are intentionally raced.
                # Whichever linearizes first owns the terminal state, but the
                # child must never remain running.
                assert second_terminal.status in {
                    "completed",
                    "failed",
                    "interrupted",
                }
            else:
                second_terminal = control.registry.get(
                    second.ref,
                    include_closed=True,
                )
                assert second_terminal is not None
                assert second_terminal.status == "closed"

            assert effect_calls[first.ref] == int(
                first_accepted and first_outcome == "allow_once"
            )
            if not second_accepted or second_outcome != "allow_once":
                assert effect_calls[second.ref] == 0
            assert effect_calls[first.ref] <= 1
            assert effect_calls[second.ref] <= 1
            for ref in (first.ref, second.ref):
                events = factory.drivers[ref].audit_events
                event_types = [str(event["type"]) for event in events]
                assert event_types[:3] == [
                    "tool_action_frozen",
                    "tool_policy_evaluated",
                    "tool_approval_requested",
                ]
                assert event_types.count("tool_execution_started") <= 1
                terminal_audit_count = sum(
                    event_type in {"tool_execution_completed", "tool_execution_failed"}
                    for event_type in event_types
                )
                assert terminal_audit_count == event_types.count(
                    "tool_execution_started"
                )
                assert (
                    len(
                        {
                            event["action_fingerprint"]
                            for event in events
                            if "action_fingerprint" in event
                        }
                    )
                    == 1
                )
                assert "stress-target" not in json.dumps(events)
            assert resolver.permissions_snapshot().pending == ()
            assert not await resolver.handle_result(
                first_action,
                outcome="allow_once",
            )
            assert not await resolver.handle_result(
                second_action,
                outcome="allow_once",
            )

            await runtime.close_agent(caller=HOST, target=first.path)
            if lifecycle == "interrupt":
                await runtime.close_agent(caller=HOST, target=second.path)

            reincarnated = await runtime.spawn_child(
                caller=HOST,
                parent_path=AgentPath.root(),
                name="worker-a",
                agent_type="worker",
                initial_prompt="Request one effect in the new incarnation.",
            )
            assert reincarnated.ref.incarnation == first.ref.incarnation + 1
            await _wait_until(lambda payloads=payloads: len(payloads) == 3)
            reincarnated_payload = payloads[-1]
            assert reincarnated_payload["actor_id"] == str(reincarnated.ref)
            reincarnated_action = str(reincarnated_payload["action_id"])
            assert reincarnated_action not in {first_action, second_action}
            assert not await resolver.handle_result(
                first_action,
                outcome="allow_once",
            )
            assert await resolver.handle_result(
                reincarnated_action,
                outcome="allow_once",
            )
            reincarnated_terminal = await runtime.await_terminal(
                caller=HOST,
                target=reincarnated.path,
                timeout=1,
            )
            assert reincarnated_terminal.status == "completed"
            assert effect_calls[reincarnated.ref] == 1
            reincarnated_events = factory.drivers[reincarnated.ref].audit_events
            assert [event["type"] for event in reincarnated_events][-2:] == [
                "tool_execution_started",
                "tool_execution_completed",
            ]

            await runtime.close_agent(caller=HOST, target=reincarnated.path)
            await runtime.dispose()
            assert resolver.permissions_snapshot().pending == ()
            assert resolver.permissions_snapshot().grants == ()
            assert [record.path for record in runtime.list_agents(caller=HOST)] == [
                AgentPath.root()
            ]
            assert all(driver.dispose_calls == 1 for driver in factory.drivers.values())
            assert not any(
                record.status == "running"
                for record in control.registry.records(include_closed=True)
            )

    asyncio.run(scenario())
