from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from loushang.harness.session import PromptController


@dataclass(frozen=True)
class _PreflightResult:
    text: str
    consumed: bool = False


@dataclass(frozen=True)
class _BeforeAgentStartResult:
    system_prompt: str | None = None
    extra_messages: list[object] | None = None


@dataclass(frozen=True)
class _InputEventResult:
    action: str
    text: str | None = None
    images: object | None = None


class State:
    def __init__(self) -> None:
        self.system_prompt = "base system"


class Agent:
    def __init__(self, *, streaming: bool = False) -> None:
        self.is_streaming = streaming
        self.state = State()
        self.prompted_messages: list[list[object]] = []

    @property
    def system_prompt(self) -> str:
        return self.state.system_prompt

    async def prompt(self, messages: list[object]) -> None:
        self.prompted_messages.append(list(messages))


class Queue:
    def __init__(self) -> None:
        self.next_turn_messages: list[object] = []
        self.steering: list[tuple[str, object]] = []
        self.follow_up: list[tuple[str, object]] = []

    def queue_prepared_steering(self, text: str, images: object | None = None) -> None:
        self.steering.append((text, images))

    def queue_prepared_follow_up(self, text: str, images: object | None = None) -> None:
        self.follow_up.append((text, images))

    def drain_next_turn_messages(self) -> list[object]:
        messages = list(self.next_turn_messages)
        self.next_turn_messages.clear()
        return messages


def test_prompt_controller_extension_command_short_circuits_agent_prompt() -> None:
    agent = Agent()
    queue = Queue()
    calls: list[tuple[str, object]] = []
    preflight_results: list[bool] = []
    compact_calls = 0

    async def _compact_before_prompt() -> None:
        nonlocal compact_calls
        compact_calls += 1

    async def scenario() -> None:
        controller = PromptController(
            agent=agent,
            queue_controller=queue,
            get_extension_runner=lambda: None,
            get_cwd=lambda: "/tmp/project",
            extract_extension_command_invocation=lambda text: (
                ("demo", "args") if text == "/demo args" else None
            ),
            execute_command_async=lambda name, args: _record_async(
                calls, ("command", (name, args))
            ),
            preflight_user_input_async=lambda text, **kwargs: _preflight(
                text, **kwargs
            ),
            before_agent_start_system_prompt_options=lambda: {},
            sync_extension_diagnostics=lambda **kwargs: calls.append(("sync", kwargs)),
            compact_before_prompt_async=_compact_before_prompt,
        )

        await controller.prompt("/demo args", preflight_result=preflight_results.append)

    asyncio.run(scenario())

    assert calls == [("command", ("demo", "args"))]
    assert preflight_results == [True]
    assert agent.prompted_messages == []
    assert compact_calls == 0


def test_prompt_controller_streaming_follow_up_queues_prepared_input() -> None:
    agent = Agent(streaming=True)
    queue = Queue()
    preflight_results: list[bool] = []
    compact_calls = 0

    async def _compact_before_prompt() -> None:
        nonlocal compact_calls
        compact_calls += 1

    async def scenario() -> None:
        controller = PromptController(
            agent=agent,
            queue_controller=queue,
            get_extension_runner=lambda: None,
            get_cwd=lambda: "/tmp/project",
            extract_extension_command_invocation=lambda text: None,
            execute_command_async=lambda name, args: _record_async(
                [], ("command", (name, args))
            ),
            preflight_user_input_async=lambda text, **kwargs: _preflight(
                f"prepared:{text}", **kwargs
            ),
            before_agent_start_system_prompt_options=lambda: {},
            sync_extension_diagnostics=lambda **kwargs: None,
            compact_before_prompt_async=_compact_before_prompt,
        )

        await controller.prompt(
            "hello",
            streaming_behavior="followUp",
            preflight_result=preflight_results.append,
        )

    asyncio.run(scenario())

    assert queue.follow_up == [("prepared:hello", None)]
    assert queue.steering == []
    assert preflight_results == [True]
    assert agent.prompted_messages == []
    assert compact_calls == 0


def test_prompt_controller_streaming_steer_queues_prepared_input_without_compaction() -> (
    None
):
    agent = Agent(streaming=True)
    queue = Queue()
    preflight_results: list[bool] = []
    compact_calls = 0

    async def _compact_before_prompt() -> None:
        nonlocal compact_calls
        compact_calls += 1

    async def scenario() -> None:
        controller = PromptController(
            agent=agent,
            queue_controller=queue,
            get_extension_runner=lambda: None,
            get_cwd=lambda: "/tmp/project",
            extract_extension_command_invocation=lambda text: None,
            execute_command_async=lambda name, args: _record_async(
                [], ("command", (name, args))
            ),
            preflight_user_input_async=lambda text, **kwargs: _preflight(
                f"prepared:{text}", **kwargs
            ),
            before_agent_start_system_prompt_options=lambda: {},
            sync_extension_diagnostics=lambda **kwargs: None,
            compact_before_prompt_async=_compact_before_prompt,
        )

        await controller.prompt(
            "adjust direction",
            streaming_behavior="steer",
            preflight_result=preflight_results.append,
        )

    asyncio.run(scenario())

    assert queue.steering == [("prepared:adjust direction", None)]
    assert queue.follow_up == []
    assert preflight_results == [True]
    assert agent.prompted_messages == []
    assert compact_calls == 0


def test_prompt_controller_input_handler_consumes_prompt_without_compaction() -> None:
    agent = Agent()
    queue = Queue()
    runner = InputHandledRunner()
    preflight_results: list[bool] = []
    compact_calls = 0

    async def _compact_before_prompt() -> None:
        nonlocal compact_calls
        compact_calls += 1

    async def scenario() -> None:
        controller = PromptController(
            agent=agent,
            queue_controller=queue,
            get_extension_runner=lambda: runner,
            get_cwd=lambda: "/tmp/project",
            extract_extension_command_invocation=lambda text: None,
            execute_command_async=lambda name, args: _record_async(
                [], ("command", (name, args))
            ),
            preflight_user_input_async=lambda text, **kwargs: _preflight(
                text, **kwargs
            ),
            before_agent_start_system_prompt_options=lambda: {},
            sync_extension_diagnostics=lambda **kwargs: None,
            compact_before_prompt_async=_compact_before_prompt,
        )

        await controller.prompt(
            "handled locally", source="rpc", preflight_result=preflight_results.append
        )

    asyncio.run(scenario())

    assert runner.seen == [("handled locally", "rpc", "/tmp/project")]
    assert preflight_results == [True]
    assert agent.prompted_messages == []
    assert queue.steering == []
    assert queue.follow_up == []
    assert compact_calls == 0


def test_prompt_controller_preflight_consumed_prompt_does_not_compact() -> None:
    agent = Agent()
    queue = Queue()
    preflight_results: list[bool] = []
    compact_calls = 0

    async def _compact_before_prompt() -> None:
        nonlocal compact_calls
        compact_calls += 1

    async def _consumed_preflight(
        text: str, *, allow_extension_commands: bool = True
    ) -> _PreflightResult:
        del text, allow_extension_commands
        return _PreflightResult(text="", consumed=True)

    async def scenario() -> None:
        controller = PromptController(
            agent=agent,
            queue_controller=queue,
            get_extension_runner=lambda: None,
            get_cwd=lambda: "/tmp/project",
            extract_extension_command_invocation=lambda text: None,
            execute_command_async=lambda name, args: _record_async(
                [], ("command", (name, args))
            ),
            preflight_user_input_async=_consumed_preflight,
            before_agent_start_system_prompt_options=lambda: {},
            sync_extension_diagnostics=lambda **kwargs: None,
            compact_before_prompt_async=_compact_before_prompt,
        )

        await controller.prompt(
            "/local-command", preflight_result=preflight_results.append
        )

    asyncio.run(scenario())

    assert preflight_results == [True]
    assert agent.prompted_messages == []
    assert queue.steering == []
    assert queue.follow_up == []
    assert compact_calls == 0


def test_prompt_controller_input_transform_still_compacts_before_prompt() -> None:
    agent = Agent()
    queue = Queue()
    runner = InputTransformRunner()
    calls: list[str] = []

    async def _compact_before_prompt() -> None:
        calls.append("compact")

    async def _agent_prompt(messages: list[object]) -> None:
        calls.append("prompt")
        agent.prompted_messages.append(list(messages))

    async def scenario() -> None:
        setattr(agent, "prompt", _agent_prompt)
        controller = PromptController(
            agent=agent,
            queue_controller=queue,
            get_extension_runner=lambda: runner,
            get_cwd=lambda: "/tmp/project",
            extract_extension_command_invocation=lambda text: None,
            execute_command_async=lambda name, args: _record_async(
                [], ("command", (name, args))
            ),
            preflight_user_input_async=lambda text, **kwargs: _preflight(
                f"prepared:{text}", **kwargs
            ),
            before_agent_start_system_prompt_options=lambda: {},
            sync_extension_diagnostics=lambda **kwargs: None,
            compact_before_prompt_async=_compact_before_prompt,
        )

        await controller.prompt("original", source="interactive")

    asyncio.run(scenario())

    assert runner.seen == [("original", "interactive", "/tmp/project")]
    assert calls == ["compact", "prompt"]
    assert len(agent.prompted_messages) == 1
    assert (
        agent.prompted_messages[0][0].content[0].text == "prepared:transformed:original"
    )


def test_prompt_controller_compacts_before_new_agent_prompt() -> None:
    agent = Agent()
    queue = Queue()
    calls: list[str] = []

    async def _compact_before_prompt() -> None:
        calls.append("compact")

    async def _agent_prompt(messages: list[object]) -> None:
        calls.append("prompt")
        agent.prompted_messages.append(list(messages))

    async def scenario() -> None:
        setattr(agent, "prompt", _agent_prompt)
        controller = PromptController(
            agent=agent,
            queue_controller=queue,
            get_extension_runner=lambda: None,
            get_cwd=lambda: "/tmp/project",
            extract_extension_command_invocation=lambda text: None,
            execute_command_async=lambda name, args: _record_async(
                [], ("command", (name, args))
            ),
            preflight_user_input_async=lambda text, **kwargs: _preflight(
                text, **kwargs
            ),
            before_agent_start_system_prompt_options=lambda: {},
            sync_extension_diagnostics=lambda **kwargs: None,
            compact_before_prompt_async=_compact_before_prompt,
        )

        await controller.prompt("hello")

    asyncio.run(scenario())

    assert calls == ["compact", "prompt"]
    assert len(agent.prompted_messages) == 1


def test_prompt_controller_rejects_streaming_prompt_without_queue_mode() -> None:
    agent = Agent(streaming=True)
    queue = Queue()
    preflight_results: list[bool] = []

    async def scenario() -> None:
        controller = PromptController(
            agent=agent,
            queue_controller=queue,
            get_extension_runner=lambda: None,
            get_cwd=lambda: "/tmp/project",
            extract_extension_command_invocation=lambda text: None,
            execute_command_async=lambda name, args: _record_async(
                [], ("command", (name, args))
            ),
            preflight_user_input_async=lambda text, **kwargs: _preflight(
                text, **kwargs
            ),
            before_agent_start_system_prompt_options=lambda: {},
            sync_extension_diagnostics=lambda **kwargs: None,
        )

        with pytest.raises(RuntimeError, match="Agent is already processing"):
            await controller.prompt("hello", preflight_result=preflight_results.append)

    asyncio.run(scenario())

    assert preflight_results == [False]


def test_prompt_controller_applies_before_agent_start_result_after_next_turn_messages() -> (
    None
):
    agent = Agent()
    queue = Queue()
    queue.next_turn_messages.append("next-turn")
    runner = BeforeStartRunner()
    calls: list[tuple[str, object]] = []
    preflight_results: list[bool] = []

    async def scenario() -> None:
        controller = PromptController(
            agent=agent,
            queue_controller=queue,
            get_extension_runner=lambda: runner,
            get_cwd=lambda: "/tmp/project",
            extract_extension_command_invocation=lambda text: None,
            execute_command_async=lambda name, args: _record_async(
                calls, ("command", (name, args))
            ),
            preflight_user_input_async=lambda text, **kwargs: _preflight(
                f"prepared:{text}", **kwargs
            ),
            before_agent_start_system_prompt_options=lambda: {"cwd": "/tmp/project"},
            sync_extension_diagnostics=lambda **kwargs: calls.append(("sync", kwargs)),
        )

        await controller.prompt("hello", preflight_result=preflight_results.append)

    asyncio.run(scenario())

    assert agent.state.system_prompt == "extension system"
    assert preflight_results == [True]
    assert calls == [("sync", {"phase": "runtime"})]
    assert len(agent.prompted_messages) == 1
    prompted = agent.prompted_messages[0]
    assert prompted[0].content[0].text == "prepared:hello"
    assert prompted[1] == "next-turn"
    assert getattr(prompted[2], "custom_type") == "demo_notice"
    assert getattr(prompted[2], "content") == "visible note"
    assert runner.seen == [
        (
            "prepared:hello",
            "base system",
            {"cwd": "/tmp/project"},
            "/tmp/project",
        )
    ]


class BeforeStartRunner:
    def __init__(self) -> None:
        self.seen: list[tuple[object, ...]] = []

    def has_handlers(self, name: str) -> bool:
        return name == "before_agent_start"

    async def emit_before_agent_start(
        self,
        *,
        prompt: str,
        images: object | None,
        system_prompt: str,
        system_prompt_options: dict[str, object],
        cwd: str,
    ) -> _BeforeAgentStartResult:
        del images
        self.seen.append((prompt, system_prompt, system_prompt_options, cwd))
        return _BeforeAgentStartResult(
            system_prompt="extension system",
            extra_messages=[{"customType": "demo_notice", "content": "visible note"}],
        )


class InputHandledRunner:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str, str]] = []

    def has_handlers(self, name: str) -> bool:
        return name == "input"

    async def emit_input(
        self, text: str, images: object | None, *, source: str, cwd: str
    ) -> _InputEventResult:
        del images
        self.seen.append((text, source, cwd))
        return _InputEventResult(action="handled")


class InputTransformRunner:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str, str]] = []

    def has_handlers(self, name: str) -> bool:
        return name == "input"

    async def emit_input(
        self, text: str, images: object | None, *, source: str, cwd: str
    ) -> _InputEventResult:
        del images
        self.seen.append((text, source, cwd))
        return _InputEventResult(action="transform", text=f"transformed:{text}")

    async def emit_before_agent_start(
        self,
        *,
        prompt: str,
        images: object | None,
        system_prompt: str,
        system_prompt_options: dict[str, object],
        cwd: str,
    ) -> None:
        del prompt, images, system_prompt, system_prompt_options, cwd
        return None


async def _record_async(
    calls: list[tuple[str, object]], value: tuple[str, object]
) -> None:
    calls.append(value)


async def _preflight(
    text: str, *, allow_extension_commands: bool = True
) -> _PreflightResult:
    del allow_extension_commands
    return _PreflightResult(text=text)
