from __future__ import annotations

import asyncio
import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any

from loushang.agent.types import AgentToolResult
from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage
from loushang.coding.multiagent import (
    CodingSubagentFactory,
    coding_agent_types,
)
from loushang.coding.tool_pack import register_coding_builtin_tools
from loushang.coding.ui.screen_surfaces import ScreenSurfaceManager
from loushang.coding.worktree import CodingGitWorktreeLeasePort
from loushang.harness.approval import (
    HeadlessApprovalResolver,
    InteractiveApprovalResolver,
)
from loushang.harness.multiagent import (
    AgentCaller,
    AgentCompletionNotice,
    AgentFact,
    AgentInputMessage,
    AgentPath,
    AgentTypeRegistry,
    AgentTypeSpec,
    ImmediateRecipeExecutor,
    MultiAgentControl,
    MultiAgentError,
    RecipeRunRequest,
    SubagentRoundResult,
    core_recipe_catalog,
)
from loushang.harness.policy_engine import PolicyEngine
from loushang.harness.runtime import HostInputQueue
from loushang.harness.session.multiagent import (
    AgentInputFacade,
    SessionMultiAgentRuntime,
    SessionSubagentRequest,
)
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.multiagent import MultiAgentToolPack
from loushang.harness.tools.workspace import ToolContext
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
from loushang.harness.workspace.exec import ExecRequest, ExecResult, ExecService
from loushang.harnesstui.multiagent import build_agent_tree_surface_view
from loushang.harnesstui.status.provider import StatusProvider
from loushang.tui import (
    ApprovalChoice,
    PlaybackResult,
    Surface,
    strip_control_sequences,
)
from loushang.tui.playback_suite import PlaybackScenarioSpec
from loushang.tui.transcript import ToolExecutionRecord
from tests.coding.tui_support.playback import (
    ScreenTuiLoopPlayback,
    ScreenTuiScenario,
)

_PROMPT = "派生3个子agent，每个计算1到100之间的随机值，主agent计算平均值"
_PRIOR_PROMPT = "MULTIAGENT_PLAYBACK_PRIOR_PROMPT"
_PRIOR_RESPONSE = "MULTIAGENT_PLAYBACK_PRIOR_RESPONSE"
_RESULTS = {
    "random-1": "95",
    "random-2": "51",
    "random-3": "35",
}
_COMPLETION_ORDER = ("random-1", "random-3", "random-2")
_NOW = datetime(2026, 7, 27, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class MultiAgentPlaybackArtifacts:
    events: Path
    render: Path
    screen: Path
    terminal: Path


@dataclass(frozen=True, slots=True)
class MultiAgentPlaybackResult:
    """Layered evidence from one deterministic collaboration replay."""

    events: tuple[dict[str, object], ...]
    playback: PlaybackResult | None = None

    def write_artifacts(
        self,
        directory: str | Path,
        *,
        basename: str = "multiagent",
        include_frames: bool = False,
    ) -> MultiAgentPlaybackArtifacts:
        output_dir = Path(directory)
        output_dir.mkdir(parents=True, exist_ok=True)
        events_path = output_dir / f"{basename}-events.jsonl"
        render_path = output_dir / f"{basename}-render.jsonl"
        screen_path = output_dir / f"{basename}-screen.txt"
        terminal_path = output_dir / f"{basename}-terminal.txt"
        with events_path.open("w", encoding="utf-8") as stream:
            for event in self.events:
                stream.write(json.dumps(event, ensure_ascii=False))
                stream.write("\n")
        if self.playback is None:
            render_path.write_text("", encoding="utf-8")
            screen_path.write_text(_event_summary(self.events), encoding="utf-8")
            terminal_path.write_text(
                _event_summary(self.events),
                encoding="utf-8",
            )
        else:
            self.playback.write_jsonl(
                render_path,
                include_frames=include_frames,
            )
            screen_path.write_text(self.playback.visible_text, encoding="utf-8")
            terminal_path.write_text(
                self.playback.terminal_text,
                encoding="utf-8",
            )
        return MultiAgentPlaybackArtifacts(
            events=events_path,
            render=render_path,
            screen=screen_path,
            terminal=terminal_path,
        )


class _Recorder:
    def __init__(self) -> None:
        self._events: list[dict[str, object]] = []

    @property
    def events(self) -> tuple[dict[str, object], ...]:
        return tuple(self._events)

    def add(self, layer: str, event: str, **data: object) -> None:
        self._events.append(
            {
                "sequence": len(self._events) + 1,
                "layer": layer,
                "event": event,
                "data": data,
            }
        )


class _Driver:
    def __init__(self) -> None:
        self.messages: list[AgentInputMessage] = []
        self.pending: asyncio.Future[SubagentRoundResult] | None = None
        self.rounds: list[tuple[int, str]] = []
        self.disposed = False

    def deliver(self, message: AgentInputMessage) -> None:
        self.messages.append(message)

    async def run_round(
        self,
        *,
        round_id: int,
        mode: str,
    ) -> SubagentRoundResult:
        self.rounds.append((round_id, mode))
        self.pending = asyncio.get_running_loop().create_future()
        return await self.pending

    def complete(self, result: str) -> None:
        if self.pending is None or self.pending.done():
            raise AssertionError("driver round is not waiting for completion")
        self.pending.set_result(
            SubagentRoundResult(
                status="completed",
                final_message=result,
                summary=result,
                latest_input_tokens=100,
                output_tokens=10,
                tool_uses=1,
                duration_ms=20,
            )
        )

    def fail(self, message: str) -> None:
        if self.pending is None or self.pending.done():
            raise AssertionError("driver round is not waiting for failure")
        self.pending.set_exception(RuntimeError(message))

    def abort(self) -> None:
        if self.pending is not None and not self.pending.done():
            self.pending.set_result(
                SubagentRoundResult(
                    status="interrupted",
                    final_message="Interrupted.",
                )
            )

    async def dispose(self) -> None:
        self.disposed = True


class _Factory:
    def __init__(self) -> None:
        self.drivers: dict[str, _Driver] = {}

    async def create_driver(self, request: SessionSubagentRequest) -> _Driver:
        driver = _Driver()
        self.drivers[request.record.path.name] = driver
        return driver


@dataclass(slots=True)
class _Fixture:
    recorder: _Recorder
    control: MultiAgentControl
    runtime: SessionMultiAgentRuntime
    root_queue: HostInputQueue[AgentInputMessage]
    factory: _Factory
    tools: dict[str, Any]

    async def spawn_three(self) -> tuple[str, ...]:
        paths: list[str] = []
        for name in _RESULTS:
            params = {
                "name": name,
                "agent_type": "explorer",
                "prompt": "Generate one deterministic playback value.",
            }
            self.recorder.add("tool", "spawn.started", call_id=f"spawn:{name}", params=params)
            result = await self.tools["spawn_agent"].execute(
                f"spawn:{name}",
                params,
                None,
                None,
            )
            path = str(result.details["path"])
            paths.append(path)
            self.recorder.add(
                "tool",
                "spawn.completed",
                call_id=f"spawn:{name}",
                result=dict(result.details),
            )
        await _yield_until(
            lambda: all(
                driver.pending is not None for driver in self.factory.drivers.values()
            )
        )
        return tuple(paths)

    async def complete_and_wait(self, name: str) -> dict[str, object]:
        self.factory.drivers[name].complete(_RESULTS[name])
        self.recorder.add(
            "driver",
            "round.completed",
            agent=name,
            result=_RESULTS[name],
        )
        result = await self.tools["wait_agent"].execute(
            f"wait:{name}",
            {"timeout_seconds": 1},
            None,
            None,
        )
        details = dict(result.details)
        self.recorder.add(
            "tool",
            "wait.completed",
            call_id=f"wait:{name}",
            result=details,
        )
        return details

    async def close_all(self) -> None:
        records = {
            record.path: record
            for record in self.control.list_agents(
                caller=AgentCaller(self.control.root_ref)
            )
        }
        for name in _RESULTS:
            record = records.get(AgentPath.root().child(name))
            if record is None or not record.is_open:
                continue
            await self.tools["close_agent"].execute(
                f"close:{name}",
                {"target": str(record.path)},
                None,
                None,
            )
        await self.runtime.dispose()


def _fixture(
    recorder: _Recorder,
    *,
    agent_types: AgentTypeRegistry | None = None,
) -> _Fixture:
    facts: list[AgentFact] = []
    notices: list[AgentCompletionNotice] = []

    def record_fact(fact: AgentFact) -> None:
        facts.append(fact)
        recorder.add("control", "fact", fact=_fact_data(fact))

    def record_notice(notice: AgentCompletionNotice) -> None:
        notices.append(notice)
        recorder.add("mailbox", "completion.notice", notice=_notice_data(notice))

    control = MultiAgentControl(
        agent_types=agent_types
        or AgentTypeRegistry(
            (
                AgentTypeSpec(
                    name="explorer",
                    maximum_children=3,
                ),
            )
        ),
        fact_consumers=(record_fact,),
        notice_consumers=(record_notice,),
        clock=lambda: _NOW,
    )
    root_queue: HostInputQueue[AgentInputMessage] = HostInputQueue()
    root_input = AgentInputFacade(
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
    return _Fixture(
        recorder=recorder,
        control=control,
        runtime=runtime,
        root_queue=root_queue,
        factory=factory,
        tools={definition.name: definition for definition in pack.definitions()},
    )


def _tools_playback() -> MultiAgentPlaybackResult:
    async def scenario() -> MultiAgentPlaybackResult:
        recorder = _Recorder()
        fixture = _fixture(recorder)
        try:
            paths = await fixture.spawn_three()
            listed = await fixture.tools["list_agents"].execute(
                "list:after-spawn",
                {},
                None,
                None,
            )
            agents = list(listed.details["agents"])
            recorder.add("tool", "list.completed", agents=agents)
            assert paths == (
                "/root/random-1",
                "/root/random-2",
                "/root/random-3",
            )
            assert [agent["status"] for agent in agents[1:]] == [
                "running",
                "running",
                "running",
            ]
            assert len(fixture.factory.drivers) == 3
            return MultiAgentPlaybackResult(recorder.events)
        finally:
            await fixture.close_all()

    return asyncio.run(scenario())


def _followup_playback() -> MultiAgentPlaybackResult:
    async def scenario() -> MultiAgentPlaybackResult:
        recorder = _Recorder()
        fixture = _fixture(recorder)
        path = AgentPath.root().child("worker")
        try:
            await fixture.tools["spawn_agent"].execute(
                "spawn:worker",
                {
                    "name": "worker",
                    "agent_type": "explorer",
                    "prompt": "Inspect the first question.",
                },
                None,
                None,
            )
            await _yield_until(
                lambda: fixture.factory.drivers["worker"].pending is not None
            )
            driver = fixture.factory.drivers["worker"]
            driver.complete("Round one result.")
            first = await fixture.runtime.await_completion(
                caller=AgentCaller(fixture.control.root_ref),
                target=path,
                timeout=1,
            )
            recorder.add(
                "topology",
                "followup.round.completed",
                round_id=first.round_id,
                result=first.terminal.final_message,
            )

            sent = await fixture.tools["send_message"].execute(
                "send:worker",
                {
                    "target": str(path),
                    "message": "Check the follow-up.",
                },
                None,
                None,
            )
            recorder.add(
                "tool",
                "followup.sent",
                result=dict(sent.details),
            )
            await _yield_until(lambda: len(driver.rounds) == 2)
            driver.complete("Round two result.")
            second = await fixture.runtime.await_completion(
                caller=AgentCaller(fixture.control.root_ref),
                target=path,
                timeout=1,
            )
            await fixture.runtime.drain_notice_deliveries()
            mailbox = fixture.root_queue.drain_next_turn()
            recorder.add(
                "topology",
                "followup.completed",
                rounds=list(driver.rounds),
                notice_rounds=[notice.round_id for notice in fixture.control.notices()],
                mailbox=[message.text for message in mailbox],
            )

            assert sent.details["triggered_new_round"] is True
            assert driver.rounds == [(1, "prompt"), (2, "continue")]
            assert [first.round_id, second.round_id] == [1, 2]
            assert [notice.round_id for notice in fixture.control.notices()] == [1, 2]
            assert len(mailbox) == 2
            return MultiAgentPlaybackResult(recorder.events)
        finally:
            await fixture.runtime.dispose()

    return asyncio.run(scenario())


def _nested_tree_playback() -> MultiAgentPlaybackResult:
    async def scenario() -> MultiAgentPlaybackResult:
        recorder = _Recorder()
        fixture = _fixture(
            recorder,
            agent_types=AgentTypeRegistry(
                (
                    AgentTypeSpec(
                        name="coordinator",
                        can_spawn=True,
                        maximum_children=1,
                    ),
                    AgentTypeSpec(name="worker"),
                )
            ),
        )
        root_caller = AgentCaller(fixture.control.root_ref)
        try:
            coordinator = await fixture.runtime.spawn_child(
                caller=root_caller,
                parent_path=AgentPath.root(),
                name="coordinator",
                agent_type="coordinator",
                initial_prompt="Coordinate one worker.",
            )
            await _yield_until(
                lambda: fixture.factory.drivers["coordinator"].pending is not None
            )
            worker = await fixture.runtime.spawn_child(
                caller=AgentCaller(coordinator.ref),
                parent_path=coordinator.path,
                name="worker",
                agent_type="worker",
                initial_prompt="Produce one finding.",
            )
            await _yield_until(
                lambda: fixture.factory.drivers["worker"].pending is not None
            )
            fixture.factory.drivers["worker"].complete("Nested worker finding.")
            await fixture.runtime.await_completion(
                caller=AgentCaller(coordinator.ref),
                target=worker.path,
                timeout=1,
            )
            await fixture.runtime.drain_notice_deliveries()
            coordinator_messages = fixture.factory.drivers["coordinator"].messages
            nested_notice = coordinator_messages[-1]
            recorder.add(
                "topology",
                "nested.notice.delivered",
                sender=str(nested_notice.sender.ref.path),
                recipient=str(nested_notice.recipient_ref.path),
                kind=nested_notice.kind,
                text=nested_notice.text,
            )

            assert nested_notice.kind == "mailbox"
            assert nested_notice.recipient_ref == coordinator.ref
            assert "Nested worker finding." in nested_notice.text
            assert fixture.root_queue.drain_next_turn() == []

            fixture.factory.drivers["coordinator"].complete(
                "Coordinator synthesized the nested finding."
            )
            await fixture.runtime.await_completion(
                caller=root_caller,
                target=coordinator.path,
                timeout=1,
            )
            await fixture.runtime.drain_notice_deliveries()
            root_mailbox = fixture.root_queue.drain_next_turn()
            recorder.add(
                "topology",
                "nested.completed",
                paths=[str(coordinator.path), str(worker.path)],
                root_mailbox=[message.text for message in root_mailbox],
            )

            assert len(root_mailbox) == 1
            assert str(coordinator.path) in root_mailbox[0].text
            assert str(worker.path) not in root_mailbox[0].text
            return MultiAgentPlaybackResult(recorder.events)
        finally:
            await fixture.runtime.dispose()

    return asyncio.run(scenario())


def _lifecycle_playback() -> MultiAgentPlaybackResult:
    async def scenario() -> MultiAgentPlaybackResult:
        recorder = _Recorder()
        fixture = _fixture(recorder)
        target = AgentPath.root().child("worker")
        try:
            first = await fixture.tools["spawn_agent"].execute(
                "spawn:worker:first",
                {
                    "name": "worker",
                    "agent_type": "explorer",
                    "prompt": "Start a long task.",
                },
                None,
                None,
            )
            await _yield_until(
                lambda: fixture.factory.drivers["worker"].pending is not None
            )
            interrupted = await fixture.tools["interrupt_agent"].execute(
                "interrupt:worker",
                {"target": str(target)},
                None,
                None,
            )
            closed = await fixture.tools["close_agent"].execute(
                "close:worker:first",
                {"target": str(target)},
                None,
                None,
            )
            second = await fixture.tools["spawn_agent"].execute(
                "spawn:worker:second",
                {
                    "name": "worker",
                    "agent_type": "explorer",
                    "prompt": "Run again after cleanup.",
                },
                None,
                None,
            )
            await _yield_until(
                lambda: fixture.factory.drivers["worker"].pending is not None
            )
            fixture.factory.drivers["worker"].complete("Second incarnation complete.")
            await fixture.runtime.await_completion(
                caller=AgentCaller(fixture.control.root_ref),
                target=target,
                timeout=1,
            )
            recorder.add(
                "topology",
                "lifecycle.completed",
                first_incarnation=first.details["incarnation"],
                second_incarnation=second.details["incarnation"],
                interrupted_status=interrupted.details["status"],
                closed_agents=closed.details["agents"],
            )

            assert interrupted.details["status"] == "interrupted"
            assert first.details["incarnation"] != second.details["incarnation"]
            assert fixture.control.registry.current(target) is not None
            return MultiAgentPlaybackResult(recorder.events)
        finally:
            await fixture.runtime.dispose()

    return asyncio.run(scenario())


def _quota_recovery_playback() -> MultiAgentPlaybackResult:
    async def scenario() -> MultiAgentPlaybackResult:
        recorder = _Recorder()
        fixture = _fixture(recorder)
        root_caller = AgentCaller(fixture.control.root_ref)
        replacement = AgentPath.root().child("random-4")
        try:
            await fixture.spawn_three()
            for name in _COMPLETION_ORDER:
                await fixture.complete_and_wait(name)

            try:
                await fixture.tools["spawn_agent"].execute(
                    "spawn:random-4:blocked",
                    {
                        "name": "random-4",
                        "agent_type": "explorer",
                        "prompt": "Generate one more deterministic value.",
                    },
                    None,
                    None,
                )
            except MultiAgentError as error:
                error_details = dict(error.tool_result_details)
            else:
                raise AssertionError("the fourth open explorer must exceed its quota")

            listed = await fixture.tools["list_agents"].execute(
                "list:quota-blocked",
                {},
                None,
                None,
            )
            open_children = list(error_details["open_children"])
            recorder.add(
                "topology",
                "quota.blocked",
                code=error_details["code"],
                open_children=open_children,
                listed_agents=list(listed.details["agents"]),
                failed_spawn_created_child=(
                    fixture.control.registry.current(replacement) is not None
                ),
                wait_skipped=True,
            )

            assert error_details["code"] == "agent_type_limit_reached"
            assert [item["status"] for item in open_children] == [
                "completed",
                "completed",
                "completed",
            ]
            assert fixture.control.registry.current(replacement) is None

            closed = await fixture.tools["close_agent"].execute(
                "close:random-1:quota-recovery",
                {"target": "/root/random-1"},
                None,
                None,
            )
            spawned = await fixture.tools["spawn_agent"].execute(
                "spawn:random-4:retry",
                {
                    "name": "random-4",
                    "agent_type": "explorer",
                    "prompt": "Generate one more deterministic value.",
                },
                None,
                None,
            )
            await _yield_until(
                lambda: fixture.factory.drivers["random-4"].pending is not None
            )
            fixture.factory.drivers["random-4"].complete("44")
            waited = await fixture.tools["wait_agent"].execute(
                "wait:random-4",
                {"timeout_seconds": 1},
                None,
                None,
            )
            record = fixture.control.registry.current(replacement)
            recorder.add(
                "topology",
                "quota.recovered",
                closed=list(closed.details["agents"]),
                spawned=dict(spawned.details),
                wait=dict(waited.details),
                replacement_status=record.status if record is not None else None,
                open_agents=[
                    str(item.path)
                    for item in fixture.control.list_agents(caller=root_caller)
                ],
            )

            assert spawned.details["path"] == "/root/random-4"
            assert waited.details["wait_expired"] is False
            assert record is not None
            assert record.status == "completed"
            return MultiAgentPlaybackResult(recorder.events)
        finally:
            await fixture.runtime.dispose()

    return asyncio.run(scenario())


class _ImmediateDriver:
    def __init__(self, path: AgentPath) -> None:
        self.path = path
        self.messages: list[AgentInputMessage] = []
        self.disposed = False

    def deliver(self, message: AgentInputMessage) -> None:
        self.messages.append(message)

    async def run_round(
        self,
        *,
        round_id: int,
        mode: str,
    ) -> SubagentRoundResult:
        del round_id, mode
        return SubagentRoundResult(
            status="completed",
            final_message=f"Full result from {self.path}",
            summary=f"Summary from {self.path}",
            latest_input_tokens=120,
            output_tokens=20,
            tool_uses=1,
            duration_ms=25,
        )

    def abort(self) -> None:
        return None

    async def dispose(self) -> None:
        self.disposed = True


class _ImmediateFactory:
    def __init__(self) -> None:
        self.drivers: dict[AgentPath, _ImmediateDriver] = {}

    async def create_driver(
        self,
        request: SessionSubagentRequest,
    ) -> _ImmediateDriver:
        driver = _ImmediateDriver(request.record.path)
        self.drivers[request.record.path] = driver
        return driver


class _SharedState:
    def __init__(self) -> None:
        self.messages: list[object] = []

    def set_messages(self, messages: list[object]) -> None:
        self.messages = list(messages)


class _SharedSession:
    def __init__(self, target: Path) -> None:
        self.target = target
        self.agent = SimpleNamespace(state=_SharedState())
        self.runtime = SimpleNamespace(
            queue=SimpleNamespace(
                input_queue=HostInputQueue(),
            )
        )

    async def prompt(self, text: str, *, source: str | None = None) -> None:
        del source
        self.target.write_text("after\n", encoding="utf-8")
        self.agent.state.messages.extend(
            (
                UserMessage(role="user", content=text, timestamp=0),
                AssistantMessage(
                    role="assistant",
                    content=[
                        TextPart(
                            type="text",
                            text=f"Updated {self.target.name}.",
                        )
                    ],
                    api="playback",
                    provider="scripted",
                    model="shared-worker",
                    response_id=None,
                    usage=Usage(
                        input=20,
                        output=4,
                        cache_read=0,
                        cache_write=0,
                        total_tokens=24,
                        cost=None,
                    ),
                    stop_reason="stop",
                    error_message=None,
                    timestamp=0,
                ),
            )
        )

    async def continue_run(self) -> None:
        raise AssertionError("shared-workspace playback uses one round")

    def abort(self) -> bool:
        return True


class _SharedRuntime:
    def __init__(self, session: _SharedSession) -> None:
        self.session = session
        self.create_cwds: list[str] = []
        self.disposed = False

    async def create_session(self, *, cwd: str) -> _SharedSession:
        self.create_cwds.append(cwd)
        return self.session

    async def dispose_session_runtime(self) -> None:
        self.disposed = True


class _IsolatedRuntime:
    def __init__(self) -> None:
        self.session: _SharedSession | None = None
        self.create_cwds: list[str] = []
        self.disposed = False

    async def create_session(self, *, cwd: str) -> _SharedSession:
        self.create_cwds.append(cwd)
        self.session = _SharedSession(Path(cwd) / "isolated.txt")
        return self.session

    async def dispose_session_runtime(self) -> None:
        self.disposed = True


class _ParallelSharedSession(_SharedSession):
    def __init__(
        self,
        target: Path,
        *,
        started: asyncio.Event,
        release: asyncio.Event,
    ) -> None:
        super().__init__(target)
        self._started = started
        self._release = release

    async def prompt(self, text: str, *, source: str | None = None) -> None:
        self._started.set()
        await self._release.wait()
        await super().prompt(text, source=source)


def _shared_tool_registry(names: tuple[str, ...]) -> WorkspaceToolRegistry:
    async def unused_execute(*_args: object) -> AgentToolResult[None]:
        raise AssertionError("the scripted shared worker does not invoke tools")

    registry = WorkspaceToolRegistry()
    for name in names:
        registry.register_tool(
            ToolDefinition(
                name=name,
                label=name,
                description=f"Playback {name}",
                parameters={"type": "object", "properties": {}},
                execute=unused_execute,
            )
        )
    return registry


def _playback_exec_backend(
    request: ExecRequest,
    **_kwargs: object,
) -> ExecResult:
    environment = dict(request.effective_environment or os.environ.items())
    result = subprocess.run(
        request.command,
        cwd=request.cwd,
        env=environment,
        input=request.stdin,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=request.timeout_seconds,
    )
    return ExecResult(
        exit_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def _shared_workspace_playback() -> MultiAgentPlaybackResult:
    async def scenario() -> MultiAgentPlaybackResult:
        recorder = _Recorder()
        with TemporaryDirectory(
            prefix="loushang-shared-worker-",
            dir="/tmp",
        ) as directory:
            root = Path(directory).resolve()
            target = root / "shared.txt"
            target.write_text("before\n", encoding="utf-8")
            spec = coding_agent_types().resolve("shared_implementation_worker")
            assert spec is not None
            child_session = _SharedSession(target)
            child_runtime = _SharedRuntime(child_session)
            captured: dict[str, object] = {}

            def build_runtime(**kwargs: object) -> _SharedRuntime:
                captured.update(kwargs)
                return child_runtime

            control = MultiAgentControl(
                agent_types=AgentTypeRegistry((spec,)),
                clock=lambda: _NOW,
            )
            root_queue: HostInputQueue[AgentInputMessage] = HostInputQueue()
            runtime = SessionMultiAgentRuntime(
                control=control,
                child_factory=CodingSubagentFactory(
                    session_dir=root / "sessions",
                    cwd=root,
                    tool_registry=_shared_tool_registry(spec.allowed_tools),
                    runtime_builder=build_runtime,
                ),
                root_input=AgentInputFacade(
                    queue=root_queue,
                    build_payload=lambda message: message,
                    submit_mailbox=root_queue.append_next_turn,
                ),
            )
            tools = {
                definition.name: definition
                for definition in MultiAgentToolPack(
                    runtime=runtime,
                    caller=AgentCaller(control.root_ref),
                    default_wait_seconds=1,
                ).definitions()
            }
            try:
                await tools["spawn_agent"].execute(
                    "spawn:shared-writer",
                    {
                        "name": "copy-fix",
                        "agent_type": "shared_implementation_worker",
                        "prompt": "Update only shared.txt.",
                    },
                    None,
                    None,
                )
                notice = await runtime.await_completion(
                    caller=AgentCaller(control.root_ref),
                    target=AgentPath.root().child("copy-fix"),
                    timeout=1,
                )
                await runtime.drain_notice_deliveries()
                mailbox = root_queue.drain_next_turn()
                recorder.add(
                    "topology",
                    "shared_workspace.completed",
                    cwd=child_runtime.create_cwds,
                    before="before\n",
                    after=target.read_text(encoding="utf-8"),
                    workspace_mode=spec.workspace_mode,
                    workspace_ref=notice.workspace_ref,
                    change_set_ref=notice.change_set_ref,
                    mailbox=[message.text for message in mailbox],
                    tools=list(captured["allowed_tool_names"]),
                )

                assert child_runtime.create_cwds == [str(root)]
                assert target.read_text(encoding="utf-8") == "after\n"
                assert notice.workspace_ref is None
                assert notice.change_set_ref is None
                assert len(mailbox) == 1
                return MultiAgentPlaybackResult(recorder.events)
            finally:
                await runtime.dispose()
                assert child_runtime.disposed is True

    return asyncio.run(scenario())


def _isolated_artifact_playback() -> MultiAgentPlaybackResult:
    async def scenario() -> MultiAgentPlaybackResult:
        recorder = _Recorder()
        with TemporaryDirectory(
            prefix="loushang-isolated-artifact-",
            dir="/tmp",
        ) as directory:
            root = Path(directory).resolve()
            repo = root / "repo"
            repo.mkdir()
            service = ExecService(backend=_playback_exec_backend)

            async def git(*args: str) -> None:
                result = await service.execute(
                    ExecRequest(command=("git", *args), cwd=str(repo))
                )
                assert result.exit_code == 0, result.stderr

            await git("init")
            await git("config", "user.email", "playback@example.invalid")
            await git("config", "user.name", "Playback")
            (repo / "README.md").write_text("base\n", encoding="utf-8")
            await git("add", "README.md")
            await git("commit", "-m", "base")

            spec = coding_agent_types().resolve("implementation_worker")
            assert spec is not None
            child_runtime = _IsolatedRuntime()
            leases = CodingGitWorktreeLeasePort(
                cwd=repo,
                exec_service=service,
                state_root=root / "state",
                lease_root=root / "checkouts",
                uuid_factory=lambda: "playback",
            )
            control = MultiAgentControl(
                agent_types=AgentTypeRegistry((spec,)),
                clock=lambda: _NOW,
            )
            caller = AgentCaller(control.root_ref)
            root_queue: HostInputQueue[AgentInputMessage] = HostInputQueue()
            runtime = SessionMultiAgentRuntime(
                control=control,
                child_factory=CodingSubagentFactory(
                    session_dir=root / "sessions",
                    cwd=repo,
                    tool_registry=_shared_tool_registry(spec.allowed_tools),
                    runtime_builder=lambda **_kwargs: child_runtime,
                    workspace_leases=leases,
                ),
                root_input=AgentInputFacade(
                    queue=root_queue,
                    build_payload=lambda message: message,
                    submit_mailbox=root_queue.append_next_turn,
                ),
            )
            tools = {
                definition.name: definition
                for definition in MultiAgentToolPack(
                    runtime=runtime,
                    caller=caller,
                    default_wait_seconds=1,
                ).definitions()
            }
            target = AgentPath.root().child("isolated-writer")
            try:
                await tools["spawn_agent"].execute(
                    "spawn:isolated-writer",
                    {
                        "name": "isolated-writer",
                        "agent_type": "implementation_worker",
                        "prompt": "Create only isolated.txt.",
                    },
                    None,
                    None,
                )
                notice = await runtime.await_completion(
                    caller=caller,
                    target=target,
                    timeout=2,
                )
                assert notice.workspace_ref is not None
                assert len(notice.artifact_refs) == 1
                recorder.add(
                    "topology",
                    "isolated_workspace.completed",
                    workspace_ref=notice.workspace_ref,
                    artifact_refs=list(notice.artifact_refs),
                    child_cwd=child_runtime.create_cwds,
                )

                await runtime.close_agent(caller=caller, target=target)
                patch = leases.manager.artifact_diff(notice.workspace_ref)
                recorder.add(
                    "workspace",
                    "artifact.reviewed",
                    contains_isolated_txt="isolated.txt" in patch,
                )
                plan = await leases.manager.plan_apply_workspace(
                    notice.workspace_ref,
                    target=repo,
                )
                recorder.add(
                    "approval",
                    "apply.approved",
                    touched_paths=list(plan.touched_paths),
                )
                await leases.manager.apply(plan)
                recorder.add(
                    "workspace",
                    "artifact.applied",
                    content=(repo / "isolated.txt").read_text(encoding="utf-8"),
                )
                source = Path(leases.manager.get(notice.workspace_ref).path)
                await leases.manager.discard(notice.workspace_ref)
                recorder.add(
                    "workspace",
                    "workspace.discarded",
                    source_exists=source.exists(),
                    artifact_retained=bool(
                        leases.manager.artifact_diff(notice.workspace_ref)
                    ),
                )

                assert (repo / "isolated.txt").read_text(encoding="utf-8") == "after\n"
                assert source.exists() is False
                return MultiAgentPlaybackResult(recorder.events)
            finally:
                await runtime.dispose()

    return asyncio.run(scenario())


def _shared_parallel_writers_playback() -> MultiAgentPlaybackResult:
    async def scenario() -> MultiAgentPlaybackResult:
        recorder = _Recorder()
        with TemporaryDirectory(
            prefix="loushang-shared-parallel-workers-",
            dir="/tmp",
        ) as directory:
            root = Path(directory).resolve()
            targets = {
                "writer-a": root / "left.txt",
                "writer-b": root / "right.txt",
            }
            for target in targets.values():
                target.write_text("before\n", encoding="utf-8")
            spec = coding_agent_types(
                maximum_children=2
            ).resolve("shared_implementation_worker")
            assert spec is not None
            release = asyncio.Event()
            started = {name: asyncio.Event() for name in targets}
            child_runtimes = [
                _SharedRuntime(
                    _ParallelSharedSession(
                        target,
                        started=started[name],
                        release=release,
                    )
                )
                for name, target in targets.items()
            ]
            captured: list[dict[str, object]] = []

            def build_runtime(**kwargs: object) -> _SharedRuntime:
                runtime = child_runtimes[len(captured)]
                captured.append(dict(kwargs))
                return runtime

            def record_fact(fact: AgentFact) -> None:
                recorder.add("control", "fact", fact=_fact_data(fact))

            def record_notice(notice: AgentCompletionNotice) -> None:
                recorder.add(
                    "mailbox",
                    "completion.notice",
                    notice=_notice_data(notice),
                )

            control = MultiAgentControl(
                agent_types=AgentTypeRegistry((spec,)),
                fact_consumers=(record_fact,),
                notice_consumers=(record_notice,),
                clock=lambda: _NOW,
            )
            caller = AgentCaller(control.root_ref)
            root_queue: HostInputQueue[AgentInputMessage] = HostInputQueue()
            runtime = SessionMultiAgentRuntime(
                control=control,
                child_factory=CodingSubagentFactory(
                    session_dir=root / "sessions",
                    cwd=root,
                    tool_registry=_shared_tool_registry(spec.allowed_tools),
                    runtime_builder=build_runtime,
                ),
                root_input=AgentInputFacade(
                    queue=root_queue,
                    build_payload=lambda message: message,
                    submit_mailbox=root_queue.append_next_turn,
                ),
            )
            tools = {
                definition.name: definition
                for definition in MultiAgentToolPack(
                    runtime=runtime,
                    caller=caller,
                    default_wait_seconds=1,
                ).definitions()
            }
            paths = tuple(
                AgentPath.root().child(name) for name in targets
            )
            try:
                await asyncio.gather(
                    *(
                        tools["spawn_agent"].execute(
                            f"spawn:{name}",
                            {
                                "name": name,
                                "agent_type": "shared_implementation_worker",
                                "prompt": (
                                    f"Own and update only {target.name}. Other "
                                    "workers are active; preserve their edits."
                                ),
                            },
                            None,
                            None,
                        )
                        for name, target in targets.items()
                    )
                )
                await _yield_until(
                    lambda: all(event.is_set() for event in started.values())
                )
                running = {
                    str(record.path): record.status
                    for record in runtime.list_agents(caller=caller)
                    if record.path != AgentPath.root()
                }
                recorder.add(
                    "topology",
                    "shared_parallel.running",
                    agents=running,
                    ownership={
                        name: [target.name] for name, target in targets.items()
                    },
                    maximum_children=spec.maximum_children,
                )
                assert running == {
                    "/root/writer-a": "running",
                    "/root/writer-b": "running",
                }

                release.set()
                notices = await asyncio.gather(
                    *(
                        runtime.await_completion(
                            caller=caller,
                            target=path,
                            timeout=1,
                        )
                        for path in paths
                    )
                )
                await runtime.drain_notice_deliveries()
                mailbox = root_queue.drain_next_turn()
                recorder.add(
                    "topology",
                    "shared_parallel.completed",
                    cwd=[
                        child_runtime.create_cwds
                        for child_runtime in child_runtimes
                    ],
                    files={
                        target.name: target.read_text(encoding="utf-8")
                        for target in targets.values()
                    },
                    notice_paths=[
                        str(notice.sender_ref.path) for notice in notices
                    ],
                    mailbox=[message.text for message in mailbox],
                )

                assert spec.maximum_children == 2
                assert [runtime.create_cwds for runtime in child_runtimes] == [
                    [str(root)],
                    [str(root)],
                ]
                assert {
                    target.name: target.read_text(encoding="utf-8")
                    for target in targets.values()
                } == {
                    "left.txt": "after\n",
                    "right.txt": "after\n",
                }
                assert len(mailbox) == 2
                return MultiAgentPlaybackResult(recorder.events)
            finally:
                release.set()
                await runtime.dispose()
                assert all(
                    child_runtime.disposed for child_runtime in child_runtimes
                )

    return asyncio.run(scenario())


def _recipe_playback(recipe_id: str) -> MultiAgentPlaybackResult:
    async def scenario() -> MultiAgentPlaybackResult:
        recorder = _Recorder()
        recipe = core_recipe_catalog().resolve(recipe_id)
        assert recipe is not None
        factory = _ImmediateFactory()

        def record_fact(fact: AgentFact) -> None:
            recorder.add("control", "fact", fact=_fact_data(fact))

        def record_notice(notice: AgentCompletionNotice) -> None:
            recorder.add(
                "mailbox",
                "completion.notice",
                notice=_notice_data(notice),
            )

        types = AgentTypeRegistry(
            AgentTypeSpec(
                name=role.agent_type,
                maximum_children=role.maximum_replicas,
            )
            for role in recipe.roles
        )
        control = MultiAgentControl(
            agent_types=types,
            fact_consumers=(record_fact,),
            notice_consumers=(record_notice,),
            clock=lambda: _NOW,
        )
        root_queue: HostInputQueue[AgentInputMessage] = HostInputQueue()
        runtime = SessionMultiAgentRuntime(
            control=control,
            child_factory=factory,
            root_input=AgentInputFacade(
                queue=root_queue,
                build_payload=lambda message: message,
                submit_mailbox=root_queue.append_next_turn,
            ),
        )
        try:
            result = await ImmediateRecipeExecutor(runtime).run(
                recipe,
                RecipeRunRequest(
                    prompt=f"Deterministic {recipe_id} playback.",
                    replicas=(
                        {"reviewer": 3}
                        if recipe_id == "parallel-review"
                        else {}
                    ),
                    timeout=1,
                ),
            )
            await runtime.drain_notice_deliveries()
            names = [notice.sender_ref.path.name for notice in result.notices]
            recorder.add(
                "topology",
                "recipe.completed",
                recipe_id=recipe_id,
                agents=names,
                final_message=result.final_message,
                mailbox=[
                    message.text for message in root_queue.drain_next_turn()
                ],
            )
            expected = (
                ["reviewer-1", "reviewer-2", "reviewer-3", "synthesizer"]
                if recipe_id == "parallel-review"
                else ["proposer", "critic", "judge"]
            )
            assert names == expected
            assert result.status == "completed"
            assert all(driver.disposed for driver in factory.drivers.values())
            return MultiAgentPlaybackResult(recorder.events)
        finally:
            await runtime.dispose()

    return asyncio.run(scenario())


def _parallel_review_playback() -> MultiAgentPlaybackResult:
    return _recipe_playback("parallel-review")


def _debate_playback() -> MultiAgentPlaybackResult:
    return _recipe_playback("debate")


def _messaging_playback() -> MultiAgentPlaybackResult:
    async def scenario() -> MultiAgentPlaybackResult:
        recorder = _Recorder()
        fixture = _fixture(recorder)
        try:
            await fixture.spawn_three()
            waits = [
                await fixture.complete_and_wait(name)
                for name in _COMPLETION_ORDER
            ]
            notices = fixture.control.notices()
            followups = fixture.root_queue.texts("follow_up")
            mailbox = fixture.root_queue.drain_next_turn()
            recorder.add(
                "mailbox",
                "root.queue.snapshot",
                steering=fixture.root_queue.texts("steering"),
                follow_up=followups,
                mailbox=[message.text for message in mailbox],
                pending_count=fixture.root_queue.pending_count,
            )
            recorder.add(
                "projection",
                "completion.classified",
                expected_channel="system_mailbox",
                actual_channel="system_mailbox",
                editable=False,
                triggers_queue_preview=False,
                verdict="correct_input_boundary",
            )
            assert all(wait["wait_expired"] is False for wait in waits)
            assert [wait["activity"]["sequence"] for wait in waits] == [1, 2, 3]
            assert len({notice.notice_id for notice in notices}) == 3
            assert [notice.sender_ref.path.name for notice in notices] == list(
                _COMPLETION_ORDER
            )
            assert followups == []
            assert len(mailbox) == 3
            for name, value in _RESULTS.items():
                assert (
                    sum(
                        name in message.text and value in message.text
                        for message in mailbox
                    )
                    == 1
                )
            return MultiAgentPlaybackResult(recorder.events)
        finally:
            await fixture.close_all()

    return asyncio.run(scenario())


def _render_playback() -> MultiAgentPlaybackResult:
    async def scenario() -> MultiAgentPlaybackResult:
        recorder = _Recorder()
        fixture = _fixture(recorder)
        screen = ScreenTuiScenario(
            width=140,
            height=24,
            model_label="deepseek/deepseek-v4-flash",
            cwd="/repo/harness",
            branch="harness/new-command-semantics",
            session_label="ebbd669a",
            now=0.0,
        )
        steps = []

        def render(stage: str) -> None:
            step = screen.render()
            steps.append(step)
            logical = "\n".join(
                strip_control_sequences(line)
                for line in step.diagnostics.current_logical_lines
            )
            visible = screen.visible_text()
            terminal = strip_control_sequences(
                "\n".join(
                    (
                        *screen.port.screen.scrollback_lines,
                        *screen.port.screen.visible_lines,
                    )
                )
            )
            recorder.add(
                "render",
                stage,
                step=step.index,
                operation_class=step.diagnostics.operation_class,
                repaint_kind=step.diagnostics.repaint_kind,
                repaint_reason=step.diagnostics.repaint_reason,
                changed_line_range=step.diagnostics.changed_line_range,
                viewport_top=step.diagnostics.viewport_top,
                prompt_in_logical=logical.count(_PROMPT),
                prompt_in_visible=visible.count(_PROMPT),
                prompt_in_terminal=terminal.count(_PROMPT),
                pending_followups=len(screen.app.state.pending_followups),
                pending_steers=len(screen.app.state.pending_steers),
            )
            assert logical.count(_PROMPT) <= 1
            assert terminal.count(_PROMPT) <= 1
            assert terminal.count(_PRIOR_PROMPT) <= 1
            assert terminal.count(_PRIOR_RESPONSE) <= 1

        def assistant(text: str) -> None:
            screen.app.begin_assistant()
            screen.app.append_assistant_chunk(text)
            screen.app.end_assistant()

        try:
            screen.app.start_prompt(_PRIOR_PROMPT, started_at=0.0)
            assistant(_PRIOR_RESPONSE)
            screen.app.complete_run(elapsed_seconds=0.25)
            render("history.completed")

            screen.app.start_prompt(_PROMPT, started_at=0.0)
            assistant("好的，我先派生 3 个 explorer 子 agent。")
            render("prompt.started")

            for name in _RESULTS:
                screen.app.state.upsert_tool_record(
                    f"spawn:{name}",
                    ToolExecutionRecord(
                        name="spawn_agent",
                        state="running",
                        elapsed_seconds=0.0,
                    ),
                )
                render(f"spawn.{name}.started")
                result = await fixture.tools["spawn_agent"].execute(
                    f"spawn:{name}",
                    {
                        "name": name,
                        "agent_type": "explorer",
                        "prompt": "Generate one deterministic playback value.",
                    },
                    None,
                    None,
                )
                recorder.add(
                    "tool",
                    "spawn.completed",
                    call_id=f"spawn:{name}",
                    result=dict(result.details),
                )
                screen.app.state.upsert_tool_record(
                    f"spawn:{name}",
                    ToolExecutionRecord(
                        name="spawn_agent",
                        state="completed",
                        elapsed_seconds=0.03,
                    ),
                )
                render(f"spawn.{name}.completed")

            await _yield_until(
                lambda: all(
                    driver.pending is not None
                    for driver in fixture.factory.drivers.values()
                )
            )
            assistant("三个子 agent 都已启动，现在等待它们完成。")
            render("spawn.batch.completed")

            for name in _COMPLETION_ORDER:
                screen.app.state.upsert_tool_record(
                    f"wait:{name}",
                    ToolExecutionRecord(
                        name="wait_agent",
                        state="running",
                        elapsed_seconds=0.0,
                    ),
                )
                render(f"wait.{name}.started")
                await fixture.complete_and_wait(name)
                screen.app.state.upsert_tool_record(
                    f"wait:{name}",
                    ToolExecutionRecord(
                        name="wait_agent",
                        state="completed",
                        elapsed_seconds=0.59,
                    ),
                )
                screen.app.sync_queues(
                    steers=fixture.root_queue.texts("steering"),
                    followups=fixture.root_queue.texts("follow_up"),
                )
                recorder.add(
                    "projection",
                    "queue.synced",
                    agent=name,
                    pending_followups=list(screen.app.state.pending_followups),
                    pending_steers=list(screen.app.state.pending_steers),
                    running=screen.app.state.running,
                )
                recorder.add(
                    "projection",
                    "completion.classified",
                    agent=name,
                    expected_channel="system_mailbox",
                    actual_channel="system_mailbox",
                    editable=False,
                    triggers_queue_preview=False,
                    verdict="correct_input_boundary",
                )
                assistant(f"{name} 完成，结果是 {_RESULTS[name]}。")
                render(f"wait.{name}.completed")

            assistant(
                "汇总：95、51、35；平均值为 "
                f"{(95 + 51 + 35) / 3:.2f}。"
            )
            screen.app.complete_run(elapsed_seconds=1.23)
            render("run.completed")

            screen.app.surface_host = screen.runtime.overlay_host()
            agent_tree = build_agent_tree_surface_view(
                records=fixture.runtime.list_agents(
                    caller=AgentCaller(fixture.control.root_ref)
                ),
                subscribe_facts=fixture.control.subscribe_facts,
                request_render=lambda: None,
            )
            agent_tree_handle = screen.app.surface_host.open_surface(
                Surface(
                    renderable=agent_tree,
                    focus_target=agent_tree,
                    presentation="page",
                    width="100%",
                    max_height="100%",
                )
            )
            render("agents.opened")
            agent_tree_handle.close("playback")
            render("agents.closed")

            playback = PlaybackResult(steps=tuple(steps), port=screen.port)
            mailbox = fixture.root_queue.drain_next_turn()
            assert screen.app.state.pending_steers == []
            assert screen.app.state.pending_followups == []
            assert len(mailbox) == 3
            assert "Queued follow-up inputs" not in playback.visible_text
            assert "queued=" not in playback.visible_text
            assert playback.terminal_text.count(_PROMPT) == 1
            assert playback.terminal_text.count(_PRIOR_PROMPT) == 1
            assert playback.terminal_text.count(_PRIOR_RESPONSE) == 1
            return MultiAgentPlaybackResult(
                recorder.events,
                playback=playback,
            )
        finally:
            await fixture.close_all()

    return asyncio.run(scenario())


class _ApprovalPlaybackState:
    def __init__(self) -> None:
        self.messages: list[object] = []

    def set_messages(self, messages: list[object]) -> None:
        self.messages = list(messages)


class _ApprovalPlaybackSession:
    def __init__(
        self,
        *,
        cwd: str,
        commands: tuple[str, ...],
        registry: WorkspaceToolRegistry,
        approval_resolver: object,
        exec_service: ExecService,
        audit_events: list[dict[str, object]],
    ) -> None:
        self._cwd = cwd
        self._commands = list(commands)
        self._registry = registry
        self._approval_resolver = approval_resolver
        self._exec_service = exec_service
        self._audit_events = audit_events
        self.agent = SimpleNamespace(state=_ApprovalPlaybackState())
        self.runtime = SimpleNamespace(
            queue=SimpleNamespace(input_queue=HostInputQueue())
        )

    async def prompt(self, text: str, *, source: str | None = None) -> None:
        del source
        await self._run_command(text)

    async def continue_run(self) -> None:
        await self._run_command("follow-up")

    def abort(self) -> bool:
        return True

    async def _run_command(self, prompt: str) -> None:
        if not self._commands:
            raise AssertionError("approval playback child has no command left")
        command = self._commands.pop(0)

        async def emit_event(event: dict[str, object]) -> None:
            self._audit_events.append(dict(event))

        tool = self._registry.materialize_tool(
            "bash",
            context_provider=lambda *, tool_call_id: ToolContext(
                tool_call_id=tool_call_id,
                cwd=self._cwd,
                exec_service=self._exec_service,
                approval_resolver=self._approval_resolver,
                event_sink=emit_event,
            ),
        )
        result = await tool.execute(
            f"approval-playback:{len(self.agent.state.messages)}",
            {"command": command, "cwd": self._cwd},
        )
        self.agent.state.messages.extend(
            (
                UserMessage(role="user", content=prompt, timestamp=0),
                AssistantMessage(
                    role="assistant",
                    content=[
                        TextPart(
                            type="text",
                            text=f"{command}: {result.content[0].text}",
                        )
                    ],
                    api="playback",
                    provider="scripted",
                    model="approval-child",
                    response_id=None,
                    usage=Usage(
                        input=10,
                        output=3,
                        cache_read=0,
                        cache_write=0,
                        total_tokens=13,
                        cost=None,
                    ),
                    stop_reason="stop",
                    error_message=None,
                    timestamp=0,
                ),
            )
        )


class _ApprovalPlaybackRuntime:
    def __init__(self, session: _ApprovalPlaybackSession) -> None:
        self._session = session
        self.disposed = False

    async def create_session(self, *, cwd: str) -> _ApprovalPlaybackSession:
        assert cwd == self._session._cwd
        return self._session

    async def dispose_session_runtime(self) -> None:
        self.disposed = True


def _child_approval_playback() -> object:
    """Exercise a real Coding child factory through the common approval surface."""

    with TemporaryDirectory(
        prefix="loushang-child-approval-",
        dir="/tmp",
    ) as directory:
        cwd = Path(directory).resolve()
        playback = ScreenTuiLoopPlayback(
            width=112,
            height=22,
            model_label="playback/child-approval",
            cwd=str(cwd),
            branch="lane/harness",
        )
        resolver = InteractiveApprovalResolver(
            fallback=HeadlessApprovalResolver(mode="deny")
        )
        audit_events: list[dict[str, object]] = []
        executed: list[tuple[str, str]] = []
        profiles: dict[str, object] = {}
        child_runtimes: list[_ApprovalPlaybackRuntime] = []

        def exec_backend(
            request: ExecRequest,
            **_kwargs: object,
        ) -> ExecResult:
            command = request.command[-1]
            executed.append((request.cwd or "", command))
            return ExecResult(exit_code=0, stdout="published\n")

        root_registry = WorkspaceToolRegistry()
        register_coding_builtin_tools(
            root_registry,
            policy_engine=PolicyEngine(),
            approval_resolver=resolver,
            exec_service=ExecService(backend=exec_backend),
        )

        def build_runtime(**kwargs: object) -> _ApprovalPlaybackRuntime:
            profile = kwargs["delegated_execution_profile"]
            actor_id = str(getattr(profile, "actor_ref"))
            profiles[actor_id] = profile
            commands = (
                ("git push origin main", "git push origin release")
                if "/reusable@" in actor_id
                else ("git push origin main",)
            )
            exec_service = ExecService(
                backend=exec_backend,
                execution_profile=getattr(profile, "execution_profile_ceiling"),
            )
            session = _ApprovalPlaybackSession(
                cwd=str(cwd),
                commands=commands,
                registry=kwargs["tool_registry"],
                approval_resolver=kwargs["approval_resolver"],
                exec_service=exec_service,
                audit_events=audit_events,
            )
            runtime = _ApprovalPlaybackRuntime(session)
            child_runtimes.append(runtime)
            return runtime

        factory = CodingSubagentFactory(
            session_dir=cwd / ".sessions",
            cwd=cwd,
            tool_registry=root_registry,
            runtime_builder=build_runtime,
            approval_resolver=resolver,
        )
        types = coding_agent_types(maximum_children=3)
        control = MultiAgentControl(agent_types=types)
        runtime = SessionMultiAgentRuntime(
            control=control,
            child_factory=factory,
        )
        caller = AgentCaller(control.root_ref)
        approval_payloads: list[dict[str, object]] = []

        async def on_approval(payload: dict[str, object]) -> bool:
            action_id = payload.get("action_id")
            assert isinstance(action_id, str)
            return await resolver.handle_result(
                action_id,
                outcome=str(payload["outcome"]),
            )

        manager = ScreenSurfaceManager(
            app=playback.app,
            session=object(),
            status_provider=_approval_status_provider(playback.app),
            on_approval=on_approval,
        )

        def present(payload: dict[str, object]) -> None:
            approval_payloads.append(dict(payload))
            options = payload.get("approval_options")
            choices = tuple(
                ApprovalChoice(
                    value=str(option["outcome"]),
                    label=str(option["label"]),
                    shortcut=str(option["shortcut"]),
                    tone=str(option["tone"]),
                )
                for option in options
                if isinstance(option, dict)
            ) if isinstance(options, (tuple, list)) else ()
            manager.open_approval(
                action=str(payload.get("action") or "Approve child tool call"),
                risk=str(payload.get("risk") or ""),
                requester=str(payload.get("actor_id") or "root"),
                cwd=str(payload.get("cwd") or ""),
                environment=str(payload.get("environment") or ""),
                grant_summary=str(payload.get("grant_summary") or ""),
                action_id=str(payload["action_id"]),
                allow_session=any(
                    choice.value == "allow_session" for choice in choices
                ),
                options=choices,
            )

        resolver.set_request_presenter(
            present,
            dismisser=manager.dismiss_approval,
        )

        async def handle_prompt(_text: str) -> None:
            reusable = await runtime.spawn_child(
                caller=caller,
                parent_path=AgentPath.root(),
                name="reusable",
                agent_type="explorer",
                initial_prompt="Publish main.",
            )
            await runtime.await_completion(
                caller=caller,
                target=reusable.path,
                timeout=2,
            )
            await runtime.send_message(
                caller=caller,
                target=reusable.path,
                text="Publish release with the same non-force remote permission.",
            )
            await runtime.await_completion(
                caller=caller,
                target=reusable.path,
                timeout=2,
            )
            sibling = await runtime.spawn_child(
                caller=caller,
                parent_path=AgentPath.root(),
                name="sibling",
                agent_type="explorer",
                initial_prompt="Publish main independently.",
            )
            await runtime.await_terminal(
                caller=caller,
                target=sibling.path,
                timeout=2,
            )

            reusable_actor = str(reusable.ref)
            sibling_actor = str(sibling.ref)
            assert [payload.get("actor_id") for payload in approval_payloads] == [
                reusable_actor,
                sibling_actor,
            ]
            assert len(executed) == 2
            assert [command for _cwd, command in executed] == [
                "git push origin main",
                "git push origin release",
            ]
            assert set(profiles) == {reusable_actor, sibling_actor}
            assert {
                getattr(profile, "approval_actor_id")
                for profile in profiles.values()
            } == {reusable_actor, sibling_actor}
            grants = resolver.permissions_snapshot().grants
            assert [(grant.actor_id, grant.capability) for grant in grants] == [
                (reusable_actor, "git.publish_refs")
            ]

            await runtime.close_agent(caller=caller, target=reusable.path)
            assert resolver.permissions_snapshot().grants == ()
            await runtime.close_agent(caller=caller, target=sibling.path)
            await runtime.dispose()

        result = playback.run(
            (0.00, "run child approval\r"),
            (0.10, "s"),
            (0.25, "\x1b"),
            (0.40, ""),
            handle_prompt=handle_prompt,
            handle_surface_intent=manager.handle_surface_intent,
        )

        result.assert_exit_code(0)
        result.assert_text_contains("Approval")
        result.assert_text_contains("/root/sibling@1")
        result.assert_no_clear_screen()
        assert result.app.active_surface is None
        assert all(child_runtime.disposed for child_runtime in child_runtimes)
        assert {
            event.get("actor_id")
            for event in audit_events
            if event.get("type") == "tool_policy_evaluated"
        } == {"/root/reusable@1", "/root/sibling@1"}
        return result


def _approval_status_provider(app: object) -> StatusProvider:
    state = getattr(app, "state")
    return StatusProvider(
        model_label=state.model_label,
        cwd=state.cwd,
        branch=state.branch,
        session_label=lambda: state.session_label,
        thinking_level=lambda: None,
        running=lambda: state.running,
    )


async def _yield_until(predicate: Callable[[], bool]) -> None:
    for _ in range(50):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition was not reached")


def _fact_data(fact: AgentFact) -> dict[str, object]:
    return {
        "sequence": fact.sequence,
        "kind": fact.kind,
        "path": str(fact.ref.path),
        "incarnation": fact.ref.incarnation,
        "status": fact.status,
        "round_id": fact.round_id,
        "terminal": asdict(fact.terminal) if fact.terminal is not None else None,
    }


def _notice_data(notice: AgentCompletionNotice) -> dict[str, object]:
    return {
        "notice_id": notice.notice_id,
        "sender": str(notice.sender_ref.path),
        "recipient": str(notice.recipient_ref.path),
        "round_id": notice.round_id,
        "terminal": asdict(notice.terminal),
        "summary": notice.summary,
    }


def _event_summary(events: tuple[dict[str, object], ...]) -> str:
    return "\n".join(
        f"{event['sequence']:>3} {event['layer']:<10} {event['event']}"
        for event in events
    )


MULTIAGENT_SCENARIOS = (
    PlaybackScenarioSpec(
        name="multiagent-tools",
        description="Validate three real spawn calls and the authoritative agent registry.",
        run=_tools_playback,
        tags=("multiagent", "tools"),
    ),
    PlaybackScenarioSpec(
        name="multiagent-messaging",
        description="Validate exactly-once completion notices and wait activity ordering.",
        run=_messaging_playback,
        tags=("multiagent", "messaging"),
    ),
    PlaybackScenarioSpec(
        name="multiagent-followup",
        description="Validate two tracked rounds over one persistent child session.",
        run=_followup_playback,
        tags=("multiagent", "topology", "messaging"),
    ),
    PlaybackScenarioSpec(
        name="multiagent-nested-tree",
        description="Validate direct-parent mailbox routing in a nested agent tree.",
        run=_nested_tree_playback,
        tags=("multiagent", "topology", "messaging"),
    ),
    PlaybackScenarioSpec(
        name="multiagent-lifecycle",
        description="Validate interrupt, close, name reuse, and child incarnation changes.",
        run=_lifecycle_playback,
        tags=("multiagent", "topology", "lifecycle"),
    ),
    PlaybackScenarioSpec(
        name="multiagent-quota-recovery",
        description=(
            "Validate completed-open capacity, structured spawn failure, explicit "
            "cleanup, and successful retry without waiting on a nonexistent child."
        ),
        run=_quota_recovery_playback,
        tags=("multiagent", "topology", "lifecycle", "tools"),
    ),
    PlaybackScenarioSpec(
        name="multiagent-parallel-review",
        description="Replay reviewer fan-out, full-result fan-in, and synthesis cleanup.",
        run=_parallel_review_playback,
        tags=("multiagent", "topology", "recipe"),
    ),
    PlaybackScenarioSpec(
        name="multiagent-debate",
        description="Replay proposer, critic, and judge as a serial evidence pipeline.",
        run=_debate_playback,
        tags=("multiagent", "topology", "recipe"),
    ),
    PlaybackScenarioSpec(
        name="multiagent-shared-workspace",
        description="Validate a bounded writer editing the parent's exact cwd directly.",
        run=_shared_workspace_playback,
        tags=("multiagent", "topology", "workspace"),
    ),
    PlaybackScenarioSpec(
        name="multiagent-isolated-artifact",
        description=(
            "Validate detached spawn, immutable artifact review, approved apply, "
            "and explicit discard."
        ),
        run=_isolated_artifact_playback,
        tags=("multiagent", "topology", "workspace", "git"),
    ),
    PlaybackScenarioSpec(
        name="multiagent-shared-parallel-writers",
        description=(
            "Validate two concurrent workers editing disjoint files in the "
            "parent's exact cwd."
        ),
        run=_shared_parallel_writers_playback,
        tags=("multiagent", "topology", "workspace", "concurrency"),
    ),
    PlaybackScenarioSpec(
        name="multiagent-child-approval",
        description=(
            "Replay child-scoped approval presentation, same-child grant reuse, "
            "sibling isolation, and close-time grant cleanup."
        ),
        run=_child_approval_playback,
        tags=("multiagent", "approval", "surface", "gateway"),
    ),
    PlaybackScenarioSpec(
        name="multiagent-render",
        description="Replay tool, mailbox, queue projection, and terminal rendering boundaries.",
        run=_render_playback,
        tags=("multiagent", "render"),
    ),
)


__all__ = [
    "MULTIAGENT_SCENARIOS",
    "MultiAgentPlaybackArtifacts",
    "MultiAgentPlaybackResult",
]
