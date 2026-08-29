from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from loushang.ai.types import ImagePart, TextPart, UserMessage
from loushang.harness.runtime.turn import TurnInput, TurnOrchestrator
from loushang.harness.session.request_evidence import RequestEvidenceRuntimePort
from loushang.harness.session.turn_performance import (
    TurnStartPerformanceHandle,
    TurnStartPerformanceRuntime,
)
from loushang.harness.transcript import ApplicationMessage, CompactionResult

CommandExtractor = Callable[[str], tuple[str, str] | None]
CommandExecutor = Callable[[str, str], Awaitable[object | None]]
ExtensionRunnerProvider = Callable[[], Any | None]
CwdProvider = Callable[[], str]
Preflight = Callable[..., Awaitable[Any]]
BeforeAgentStartOptions = Callable[[], dict[str, object]]
ExtensionDiagnosticsSync = Callable[..., None]
PrePromptCompaction = Callable[[], Awaitable[CompactionResult | None]]
RunPrompt = Callable[[list[object]], Awaitable[None]]


class AgentStatePort(Protocol):
    system_prompt: str


class AgentPort(Protocol):
    is_streaming: bool
    state: AgentStatePort

    @property
    def system_prompt(self) -> str: ...

    async def prompt(self, messages: list[object]) -> None: ...


class QueuePort(Protocol):
    def queue_prepared_follow_up(
        self,
        text: str,
        images: list[ImagePart] | None = None,
        *,
        request_evidence: object | None = None,
    ) -> None: ...

    def queue_prepared_steering(
        self,
        text: str,
        images: list[ImagePart] | None = None,
        *,
        request_evidence: object | None = None,
    ) -> None: ...

    def drain_next_turn_messages(self) -> list[object]: ...


@dataclass
class PromptController:
    agent: AgentPort
    queue_controller: QueuePort
    get_extension_runner: ExtensionRunnerProvider
    get_cwd: CwdProvider
    extract_extension_command_invocation: CommandExtractor
    execute_command_async: CommandExecutor
    preflight_user_input_async: Preflight
    before_agent_start_system_prompt_options: BeforeAgentStartOptions
    sync_extension_diagnostics: ExtensionDiagnosticsSync
    compact_before_prompt_async: PrePromptCompaction | None = None
    run_prompt: RunPrompt | None = None
    turn_performance: TurnStartPerformanceRuntime | None = None
    request_evidence: RequestEvidenceRuntimePort | None = None

    async def prompt(
        self,
        user_input: str,
        images: list[ImagePart] | None = None,
        *,
        streaming_behavior: str | None = None,
        source: str | None = None,
        preflight_result: Callable[[bool], None] | None = None,
    ) -> None:
        timing = (
            self.turn_performance.begin(source=source)
            if self.turn_performance is not None
            else None
        )
        evidence_owner = object()
        orchestrator: TurnOrchestrator[list[ImagePart], object] = TurnOrchestrator(
            interceptors=(
                self._intercept_extension_command,
                self._intercept_extension_input,
            ),
            preflight=lambda item: self._timed_preflight(item, timing),
            is_running=lambda: self.agent.is_streaming,
            queue_turn=lambda behavior, item: self._timed_queue_turn(
                behavior,
                item,
                timing,
            ),
            build_message=lambda item: self._build_message(item, evidence_owner),
            drain_pending=self.queue_controller.drain_next_turn_messages,
            before_run=(
                (lambda: self._timed_before_run(timing))
                if self.compact_before_prompt_async is not None
                else None
            ),
            before_start=lambda item: self._timed_before_start(item, timing),
            run_turn=lambda messages: self._timed_run_turn(messages, timing),
            busy_error=(
                "Agent is already processing. Specify streaming_behavior "
                "('steer' or 'followUp') to queue the message."
            ),
        )
        outcome = "completed"
        try:
            await orchestrator.run(
                TurnInput(text=user_input, attachments=images, source=source),
                streaming_behavior=streaming_behavior,
                report_accepted=preflight_result,
            )
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except BaseException:
            outcome = "failed"
            raise
        finally:
            if self.request_evidence is not None:
                self.request_evidence.discard_owner(evidence_owner)
            if timing is not None:
                timing.finish(outcome)

    async def _timed_preflight(
        self,
        turn_input: TurnInput[list[ImagePart]],
        timing: TurnStartPerformanceHandle | None,
    ) -> TurnInput[list[ImagePart]] | None:
        try:
            return await self._preflight(turn_input)
        finally:
            if timing is not None:
                timing.mark("preflight_completed")

    def _timed_queue_turn(
        self,
        behavior: str,
        turn_input: TurnInput[list[ImagePart]],
        timing: TurnStartPerformanceHandle | None,
    ) -> None:
        self._queue_turn(behavior, turn_input)
        if timing is not None:
            timing.mark_queued()

    async def _timed_before_run(
        self,
        timing: TurnStartPerformanceHandle | None,
    ) -> object | None:
        if self.compact_before_prompt_async is None:
            return None
        try:
            return await self.compact_before_prompt_async()
        finally:
            if timing is not None:
                timing.mark("before_run_completed")

    async def _timed_before_start(
        self,
        turn_input: TurnInput[list[ImagePart]],
        timing: TurnStartPerformanceHandle | None,
    ) -> list[object]:
        try:
            return await self._before_start(turn_input)
        finally:
            if timing is not None:
                timing.mark("before_start_completed")

    async def _timed_run_turn(
        self,
        messages: list[object],
        timing: TurnStartPerformanceHandle | None,
    ) -> None:
        if timing is not None:
            timing.activate()
        run_turn = self.run_prompt or self.agent.prompt
        await run_turn(messages)

    async def _intercept_extension_command(
        self,
        turn_input: TurnInput[list[ImagePart]],
    ) -> TurnInput[list[ImagePart]] | None:
        command = self.extract_extension_command_invocation(turn_input.text)
        if command is None:
            return turn_input
        await self.execute_command_async(*command)
        return None

    async def _intercept_extension_input(
        self,
        turn_input: TurnInput[list[ImagePart]],
    ) -> TurnInput[list[ImagePart]] | None:
        extension_runner = self.get_extension_runner()
        if extension_runner is None or not extension_runner.has_handlers("input"):
            return turn_input
        result = await extension_runner.emit_input(
            turn_input.text,
            turn_input.attachments,
            source=turn_input.source or "interactive",
            cwd=self.get_cwd(),
        )
        if result.action == "handled":
            return None
        if result.action != "transform":
            return turn_input
        return TurnInput(
            text=result.text if result.text is not None else turn_input.text,
            attachments=(
                result.images if result.images is not None else turn_input.attachments
            ),
            source=turn_input.source,
        )

    async def _preflight(
        self,
        turn_input: TurnInput[list[ImagePart]],
    ) -> TurnInput[list[ImagePart]] | None:
        result = await self.preflight_user_input_async(
            turn_input.text,
            allow_extension_commands=False,
        )
        if result.consumed:
            return None
        evidence = (
            self.request_evidence.prepare(result)
            if self.request_evidence is not None
            else None
        )
        return _PreparedPromptInput(
            text=result.text,
            attachments=turn_input.attachments,
            source=turn_input.source,
            request_evidence=evidence,
        )

    def _queue_turn(
        self, behavior: str, turn_input: TurnInput[list[ImagePart]]
    ) -> None:
        evidence = _prepared_request_evidence(turn_input)
        if behavior == "steer":
            if evidence is None:
                self.queue_controller.queue_prepared_steering(
                    turn_input.text,
                    images=turn_input.attachments,
                )
            else:
                self.queue_controller.queue_prepared_steering(
                    turn_input.text,
                    images=turn_input.attachments,
                    request_evidence=evidence,
                )
            return
        if evidence is None:
            self.queue_controller.queue_prepared_follow_up(
                turn_input.text,
                images=turn_input.attachments,
            )
        else:
            self.queue_controller.queue_prepared_follow_up(
                turn_input.text,
                images=turn_input.attachments,
                request_evidence=evidence,
            )

    def _build_message(
        self,
        turn_input: TurnInput[list[ImagePart]],
        evidence_owner: object,
    ) -> UserMessage:
        message = _user_message(turn_input.text, images=turn_input.attachments)
        evidence = _prepared_request_evidence(turn_input)
        if evidence is not None:
            if self.request_evidence is None:
                raise RuntimeError("prepared request evidence has no Session runtime")
            self.request_evidence.bind(
                message,
                evidence,
                owner=evidence_owner,
                allow_signature_fallback=True,
            )
        return message

    async def _before_start(
        self, turn_input: TurnInput[list[ImagePart]]
    ) -> list[object]:
        extension_runner = self.get_extension_runner()
        if extension_runner is None:
            return []
        result = await extension_runner.emit_before_agent_start(
            prompt=turn_input.text,
            images=turn_input.attachments,
            system_prompt=self.agent.system_prompt,
            system_prompt_options=self.before_agent_start_system_prompt_options(),
            cwd=self.get_cwd(),
        )
        extra_messages: list[object] = []
        if result is not None:
            if result.system_prompt is not None:
                self.agent.state.system_prompt = result.system_prompt
            if result.extra_messages:
                extra_messages = _custom_messages_from_extension(result.extra_messages)
        self.sync_extension_diagnostics(phase="runtime")
        return extra_messages


def _user_message(text: str, images: list[ImagePart] | None = None) -> UserMessage:
    content: list[TextPart | ImagePart] = [TextPart(type="text", text=text)]
    if images:
        content.extend(images)
    return UserMessage(
        role="user",
        content=content,
        timestamp=0.0,
    )


@dataclass(frozen=True)
class _PreparedPromptInput(TurnInput[list[ImagePart]]):
    request_evidence: object | None = field(default=None, repr=False)


def _prepared_request_evidence(turn_input: TurnInput[list[ImagePart]]) -> object | None:
    if isinstance(turn_input, _PreparedPromptInput):
        return turn_input.request_evidence
    return None


def _custom_messages_from_extension(messages: list[object]) -> list[object]:
    custom_messages: list[object] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        custom_type = message.get("customType", message.get("custom_type"))
        if not isinstance(custom_type, str) or not custom_type:
            continue
        content = message.get("content", "")
        normalized_content = (
            content if isinstance(content, str | list) else str(content)
        )
        custom_messages.append(
            ApplicationMessage(
                application_message_id=str(uuid4()),
                custom_type=custom_type,
                content=normalized_content,
                display=bool(message.get("display", True)),
                details=message.get("details"),
                timestamp=datetime.now(timezone.utc).timestamp(),
                origin="extension.before_agent_start",
                delivery_mode="trigger_turn",
            )
        )
    return custom_messages
