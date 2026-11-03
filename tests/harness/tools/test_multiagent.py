from __future__ import annotations

import asyncio
import json

import pytest

from loushang.harness.multiagent import (
    AgentCaller,
    AgentInputMessage,
    AgentPath,
    AgentTypeRegistry,
    AgentTypeSpec,
    HostCaller,
    MultiAgentControl,
    SubagentDisposeResult,
    SubagentRoundResult,
)
from loushang.harness.runtime import HostInputQueue
from loushang.harness.session.multiagent import (
    AgentInputFacade,
    SessionMultiAgentRuntime,
    SessionSubagentBinding,
    SessionSubagentCreationError,
    SessionSubagentRequest,
)
from loushang.harness.tools.multiagent import (
    MULTIAGENT_TOOL_NAMES,
    MultiAgentToolPack,
)
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry


class _Driver:
    def __init__(self, final_message: str | None = None) -> None:
        self.messages: list[AgentInputMessage] = []
        self.rounds = 0
        self.final_message = final_message

    def deliver(self, message: AgentInputMessage) -> None:
        self.messages.append(message)

    async def run_round(self, *, round_id: int, mode: str) -> SubagentRoundResult:
        del round_id, mode
        self.rounds += 1
        return SubagentRoundResult(
            status="completed",
            final_message=self.final_message or f"result {self.rounds}",
            summary=f"summary {self.rounds}",
        )

    def abort(self) -> None:
        return None

    async def dispose(self) -> SubagentDisposeResult:
        return SubagentDisposeResult()


class _Factory:
    def __init__(self, final_messages: dict[str, str] | None = None) -> None:
        self.drivers: dict[AgentPath, _Driver] = {}
        self.final_messages = final_messages or {}

    async def create(self, request: SessionSubagentRequest) -> SessionSubagentBinding:
        driver = _Driver(self.final_messages.get(request.record.path.parts[-1]))
        self.drivers[request.record.path] = driver
        return SessionSubagentBinding(driver=driver)


def test_spawn_schema_explains_arguments_and_admitted_types() -> None:
    control = MultiAgentControl()
    pack = MultiAgentToolPack(
        runtime=SessionMultiAgentRuntime(control=control, child_factory=_Factory()),
        caller=AgentCaller(control.root_ref),
        agent_type_options={
            "explorer": "read-only investigation",
            "reviewer": "review",
            "implementation_worker": "implementation in an isolated worktree",
        },
    )

    spawn = next(tool for tool in pack.definitions() if tool.name == "spawn_agent")
    properties = spawn.parameters["properties"]

    assert "new child task name" in properties["name"]["description"]
    assert "standalone" in properties["prompt"]["description"]
    assert properties["agent_type"]["enum"] == [
        "explorer",
        "reviewer",
        "implementation_worker",
    ]
    assert (
        "explorer (read-only investigation)" in properties["agent_type"]["description"]
    )
    assert (
        "implementation_worker (implementation in an isolated worktree)"
        in (properties["agent_type"]["description"])
    )


def test_common_tool_pack_registers_and_executes_the_live_session_surface() -> None:
    async def scenario() -> None:
        control = MultiAgentControl(
            agent_types=AgentTypeRegistry(
                (
                    AgentTypeSpec(
                        name="reviewer",
                        maximum_children=2,
                    ),
                )
            )
        )
        root_queue: HostInputQueue[AgentInputMessage] = HostInputQueue()
        root_input: AgentInputFacade[AgentInputMessage] = AgentInputFacade(
            queue=root_queue,
            build_payload=lambda message: message,
            submit_mailbox=root_queue.append_next_turn,
        )
        factory = _Factory()
        runtime = SessionMultiAgentRuntime(
            control=control,
            child_factory=factory,
            root_input=root_input,
        )
        pack = MultiAgentToolPack(
            runtime=runtime,
            caller=AgentCaller(control.root_ref),
            default_wait_seconds=1,
        )
        registry = pack.register(WorkspaceToolRegistry())

        assert (
            tuple(definition.name for definition in registry.list_definitions())
            == MULTIAGENT_TOOL_NAMES
        )

        definitions = {definition.name: definition for definition in pack.definitions()}
        tools = {
            name: registry.materialize_tool(name) for name in MULTIAGENT_TOOL_NAMES
        }
        assert "cleanup-only child" in definitions["spawn_agent"].description
        assert "free open-agent capacity" in definitions["close_agent"].description
        assert "remain open until explicitly closed" in (
            definitions["close_agent"].description
        )
        spawned = await tools["spawn_agent"].execute(
            "spawn-1",
            {
                "name": "reviewer-1",
                "agent_type": "reviewer",
                "prompt": "Review the design.",
            },
            None,
            None,
        )
        assert spawned.details["path"] == "/root/reviewer-1"

        waited = await tools["wait_agent"].execute(
            "wait-1",
            {},
            None,
            None,
        )
        assert waited.details["wait_expired"] is False
        assert waited.details["activity"]["kind"] == "completion_notice"
        assert waited.details["activity"]["sender_path"] == "/root/reviewer-1"
        assert root_input.queue.texts("steering") == []
        assert root_input.queue.texts("follow_up") == []
        first_mailbox = root_input.queue.drain_next_turn()
        assert len(first_mailbox) == 1
        assert first_mailbox[0].kind == "mailbox"

        sent = await tools["send_message"].execute(
            "send-1",
            {
                "target": "/root/reviewer-1",
                "message": "Check the lifecycle too.",
            },
            None,
            None,
        )
        assert sent.details["triggered_new_round"] is True
        assert sent.details["round_id"] == 2

        second_wait = await tools["wait_agent"].execute(
            "wait-2",
            {},
            None,
            None,
        )
        assert second_wait.details["activity"]["kind"] == "completion_notice"
        second_mailbox = root_input.queue.drain_next_turn()
        assert len(second_mailbox) == 1
        assert second_mailbox[0].kind == "mailbox"

        listed = await tools["list_agents"].execute(
            "list-1",
            {},
            None,
            None,
        )
        model_agents = json.loads(listed.content[0].text)["agents"]
        assert model_agents == [
            {
                "path": "/root",
                "incarnation": 1,
                "parent": None,
                "agent_type": "root",
                "status": "idle",
                "round_id": 0,
            },
            {
                "path": "/root/reviewer-1",
                "incarnation": 1,
                "parent": "/root",
                "agent_type": "reviewer",
                "status": "completed",
                "round_id": 2,
            },
        ]
        assert [item["path"] for item in listed.details["agents"]] == [
            "/root",
            "/root/reviewer-1",
        ]
        assert listed.details["agents"][1]["round_id"] == 2
        assert listed.details["agents"][1]["workspace_ref"] is None
        assert listed.details["agents"][1]["artifact_refs"] == []
        assert listed.details["agents"][1]["change_set_ref"] is None

        closed = await tools["close_agent"].execute(
            "close-1",
            {"target": "/root/reviewer-1"},
            None,
            None,
        )
        assert closed.details["agents"][0]["status"] == "closed"

    asyncio.run(scenario())


def test_wait_expiration_is_a_normal_tool_result_not_an_execution_timeout() -> None:
    async def scenario() -> None:
        control = MultiAgentControl()
        root_queue: HostInputQueue[AgentInputMessage] = HostInputQueue()
        root_input: AgentInputFacade[AgentInputMessage] = AgentInputFacade(
            queue=root_queue,
            build_payload=lambda message: message,
            submit_mailbox=root_queue.append_next_turn,
        )
        runtime = SessionMultiAgentRuntime(
            control=control,
            child_factory=_Factory(),
            root_input=root_input,
        )
        pack = MultiAgentToolPack(
            runtime=runtime,
            caller=AgentCaller(control.root_ref),
            default_wait_seconds=0,
        )
        wait_definition = next(
            definition
            for definition in pack.definitions()
            if definition.name == "wait_agent"
        )
        registry = WorkspaceToolRegistry()
        registry.register_tool(wait_definition)
        wait = registry.materialize_tool("wait_agent")

        result = await wait.execute("wait-expired", {}, None, None)

        assert result.details["wait_expired"] is True
        assert "timed_out" not in result.details
        await runtime.dispose()

    asyncio.run(scenario())


def test_parallel_completion_reports_can_be_retrieved_without_loss() -> None:
    async def scenario() -> None:
        reports = {
            "first": "First finding.\nSecond finding.",
            "second": "第二份报告。\n" + "详细证据。" * 250,
            "third": "Third finding.",
        }
        control = MultiAgentControl(
            agent_types=AgentTypeRegistry(
                (AgentTypeSpec(name="reviewer", maximum_children=3),)
            )
        )
        root_queue: HostInputQueue[AgentInputMessage] = HostInputQueue()
        runtime = SessionMultiAgentRuntime(
            control=control,
            child_factory=_Factory(reports),
            root_input=AgentInputFacade(
                queue=root_queue,
                build_payload=lambda message: message,
                submit_mailbox=root_queue.append_next_turn,
            ),
        )
        pack = MultiAgentToolPack(runtime=runtime, caller=AgentCaller(control.root_ref))
        registry = pack.register(WorkspaceToolRegistry())
        tools = {
            name: registry.materialize_tool(name) for name in MULTIAGENT_TOOL_NAMES
        }
        references = {}
        for name in reports:
            spawned = await tools["spawn_agent"].execute(
                f"spawn-{name}",
                {"name": name, "agent_type": "reviewer", "prompt": "Review."},
                None,
                None,
            )
            references[name] = spawned.details
        for name in reports:
            await runtime.await_completion(
                caller=HostCaller(), target=AgentPath.parse(f"/root/{name}")
            )

        notices = root_queue.drain_next_turn()
        assert len(notices) == 3
        by_path = {str(notice.sender.ref.path): notice.text for notice in notices}
        assert reports["first"] in by_path["/root/first"]
        assert "[Report truncated]" in by_path["/root/second"]
        assert (
            f'get_agent_result(path="/root/second", '
            f"incarnation={references['second']['incarnation']}, round_id=1)"
            in by_path["/root/second"]
        )
        assert reports["third"] in by_path["/root/third"]

        second = references["second"]
        await tools["close_agent"].execute(
            "close-second", {"target": second["path"]}, None, None
        )
        chunks = []
        offset = 0
        while True:
            page = await tools["get_agent_result"].execute(
                "read-second",
                {
                    "path": second["path"],
                    "incarnation": second["incarnation"],
                    "round_id": 1,
                    "offset": offset,
                    "limit": 37,
                },
                None,
                None,
            )
            payload = json.loads(page.content[0].text)
            assert payload == page.details
            chunks.append(payload["chunk"])
            if payload["next_offset"] is None:
                break
            offset = payload["next_offset"]
        assert "".join(chunks) == reports["second"]
        await runtime.dispose()

    asyncio.run(scenario())


def test_close_tool_reports_cleanup_failure_and_allows_original_handle_retry():
    async def scenario():
        control = MultiAgentControl(
            agent_types=AgentTypeRegistry((AgentTypeSpec(name="reviewer"),))
        )
        factory = _Factory()
        runtime = SessionMultiAgentRuntime(control=control, child_factory=factory)
        record = await runtime.spawn_child(
            caller=HostCaller(),
            parent_path=AgentPath.root(),
            name="reviewer",
            agent_type="reviewer",
            initial_prompt="Review",
        )
        await runtime.await_terminal(caller=HostCaller(), target=record.path)
        driver = factory.drivers[record.path]
        original_dispose = driver.dispose

        async def fail():
            return SubagentDisposeResult(dispose_error=OSError("cleanup pending"))

        driver.dispose = fail
        pack = MultiAgentToolPack(runtime=runtime, caller=AgentCaller(control.root_ref))
        registry = pack.register(WorkspaceToolRegistry())
        tool = registry.materialize_tool("close_agent")
        result = await tool.execute("close", {"target": str(record.path)}, None, None)
        assert result.details["agents"] == []
        assert result.details["cleanup_errors"] == [
            {"agent_ref": str(record.ref), "error": "cleanup pending"}
        ]
        assert control.registry.open_count == 2
        driver.dispose = original_dispose
        result = await tool.execute("retry", {"target": str(record.path)}, None, None)
        assert result.details["agents"][0]["status"] == "closed"
        assert "cleanup_errors" not in result.details
        await runtime.dispose()

    asyncio.run(scenario())


def test_spawn_cleanup_failure_projects_original_ref_and_errors_to_agent():
    from loushang.agent.agent_loop import _create_error_tool_result

    async def scenario():
        driver = _Driver()
        original_dispose = driver.dispose
        creation_error, cleanup_error = (
            ValueError("cannot create"),
            OSError("still owned"),
        )

        async def fail_close():
            return SubagentDisposeResult(dispose_error=cleanup_error)

        driver.dispose = fail_close

        class Factory:
            async def create(self, request):
                # Also exercise a legacy factory omitting ref: Session owns
                # the canonical incarnation and supplies it to error projection.
                raise SessionSubagentCreationError(
                    driver, creation_error, cleanup_error
                )

        control = MultiAgentControl(
            agent_types=AgentTypeRegistry((AgentTypeSpec(name="reviewer"),))
        )
        runtime = SessionMultiAgentRuntime(control=control, child_factory=Factory())
        registry = MultiAgentToolPack(
            runtime=runtime, caller=AgentCaller(control.root_ref)
        ).register(WorkspaceToolRegistry())
        spawn = registry.materialize_tool("spawn_agent")
        with pytest.raises(SessionSubagentCreationError) as caught:
            await spawn.execute(
                "spawn",
                {"name": "reviewer", "agent_type": "reviewer", "prompt": "Review"},
                None,
                None,
            )
        error = caught.value
        result = _create_error_tool_result(str(error), error)
        record = control.registry.current(AgentPath.root().child("reviewer"))
        assert error.owner is driver and error.error is creation_error
        assert error.cleanup_error is cleanup_error
        assert result.details["agent_ref"] == str(record.ref)
        assert result.details["creation_error"]["message"] == "cannot create"
        assert result.details["cleanup_error"]["message"] == "still owned"
        assert control.registry.open_count == 2
        driver.dispose = original_dispose
        retry = result.details["retry"]
        closed = await registry.materialize_tool(retry["tool"]).execute(
            "retry", retry["arguments"], None, None
        )
        assert closed.details["agents"][0]["status"] == "closed"
        assert control.registry.open_count == 1
        await runtime.dispose()

    asyncio.run(scenario())
