from __future__ import annotations

import asyncio
import inspect
import traceback
from dataclasses import dataclass
from typing import Any

from loushang.ai.types import ImagePart
from loushang.coding.commands.catalog import CodingCommandCatalog
from loushang.coding.ui.intent import (
    AbortIntent,
    BashIntent,
    CodingUiIntent,
    FollowUpIntent,
    PromptIntent,
    QuitIntent,
)
from loushang.observability import get_log
from loushang.runtime.commands import CommandEffectKind

log = get_log(__name__).bind(component="CodingUiController")


@dataclass(frozen=True)
class ControllerResult:
    handled: bool = True
    exit_code: int | None = None
    error_message: str | None = None
    status_message: str | None = None
    traceback_text: str | None = None


@dataclass
class CodingUiController:
    session: Any
    runtime: Any | None = None
    verbose: bool = False

    async def dispatch(self, intent: CodingUiIntent | None) -> ControllerResult:
        if intent is None:
            return ControllerResult(handled=False)
        try:
            if isinstance(intent, PromptIntent):
                command_result = await self._dispatch_session_command(intent)
                if command_result is not None:
                    return command_result
                await self._prompt(intent.text, images=intent.images)
                return ControllerResult()
            if isinstance(intent, BashIntent):
                await self._bash(intent.command)
                return ControllerResult()
            if isinstance(intent, FollowUpIntent):
                return await self.follow_up(intent.text)
            if isinstance(intent, AbortIntent):
                await self._abort()
                return ControllerResult()
            if isinstance(intent, QuitIntent):
                return ControllerResult(exit_code=0)
        except asyncio.CancelledError as error:
            log.problem(
                "coding_ui_request_cancelled",
                source="agent",
                message="Request cancelled.",
                recoverable=True,
                exc=error,
                intent=type(intent).__name__,
            )
            return ControllerResult(
                error_message="Request cancelled.",
                traceback_text=traceback.format_exc() if self.verbose else None,
            )
        except Exception as error:  # noqa: BLE001
            log.problem(
                "coding_ui_dispatch_failed",
                source="agent",
                message=str(error) or error.__class__.__name__,
                recoverable=True,
                exc=error,
                intent=type(intent).__name__,
            )
            return ControllerResult(
                error_message=str(error) or error.__class__.__name__,
                traceback_text=traceback.format_exc() if self.verbose else None,
            )
        return ControllerResult(handled=False)

    async def steer(self, text: str, images: tuple[ImagePart, ...] | list[ImagePart] | None = None) -> ControllerResult:
        try:
            method = _streaming_prompt_method(self.session, streaming_behavior="steer")
            if method is None:
                method = getattr(self.session, "steer", None)
            if not callable(method):
                return ControllerResult(error_message="Steering is unavailable for this session.")
            await _call_text_method(method, text, images=images)
            return ControllerResult()
        except Exception as error:  # noqa: BLE001
            log.problem(
                "coding_ui_steer_failed",
                source="agent",
                message=str(error) or error.__class__.__name__,
                recoverable=True,
                exc=error,
            )
            return ControllerResult(
                error_message=str(error) or error.__class__.__name__,
                traceback_text=traceback.format_exc() if self.verbose else None,
            )

    async def follow_up(self, text: str, images: tuple[ImagePart, ...] | list[ImagePart] | None = None) -> ControllerResult:
        try:
            method = _streaming_prompt_method(self.session, streaming_behavior="followUp")
            if method is None:
                method = getattr(self.session, "follow_up", None)
            if not callable(method):
                return ControllerResult(error_message="Follow-up is unavailable for this session.")
            await _call_text_method(method, text, images=images)
            return ControllerResult()
        except Exception as error:  # noqa: BLE001
            log.problem(
                "coding_ui_follow_up_failed",
                source="agent",
                message=str(error) or error.__class__.__name__,
                recoverable=True,
                exc=error,
            )
            return ControllerResult(
                error_message=str(error) or error.__class__.__name__,
                traceback_text=traceback.format_exc() if self.verbose else None,
            )

    async def wait_for_idle(self) -> None:
        await _call_if_available(self.session, "wait_for_idle")

    async def _prompt(self, text: str, images: tuple[ImagePart, ...] | list[ImagePart] | None = None) -> None:
        method = getattr(self.session, "prompt", None)
        if not callable(method):
            raise RuntimeError("Session does not support prompts")
        await _call_text_method(method, text, images=images)

    async def _dispatch_session_command(self, intent: PromptIntent) -> ControllerResult | None:
        if intent.images:
            return None
        executor = getattr(self.session, "execute_command_async", None)
        if not callable(executor):
            return None
        catalog = CodingCommandCatalog(session_commands=_session_commands_provider(self.session))
        effect = catalog.effect_for_route("dispatch", intent)
        if effect is None or effect.kind is not CommandEffectKind.SESSION:
            return None
        if effect.command.source not in {"builtin", "extension"}:
            return None
        invocation_name = effect.payload.get("invocation_name")
        args = effect.payload.get("args", "")
        if not isinstance(invocation_name, str) or not isinstance(args, str):
            return None
        execution = await _maybe_await(executor(invocation_name, args))
        return _controller_result_from_command_execution(execution, invocation_name=invocation_name)

    async def _bash(self, command: str) -> None:
        method = getattr(self.session, "execute_bash", None)
        if not callable(method):
            raise RuntimeError("Session does not support bash execution")
        await _maybe_await(method(command, exclude_from_context=True))

    async def _abort(self) -> None:
        try:
            await _call_if_available(self.session, "abort")
        finally:
            await _call_if_available(self.session, "clear_queue")
            await _call_if_available(self.session, "abort_bash")


async def _call_if_available(target: Any, method_name: str) -> None:
    method = getattr(target, method_name, None)
    if callable(method):
        await _maybe_await(method())


def _streaming_prompt_method(session: Any, *, streaming_behavior: str):
    prompt = getattr(session, "prompt", None)
    if not callable(prompt) or not _supports_keyword(prompt, "streaming_behavior"):
        return None

    async def _call(text: str, images: tuple[ImagePart, ...] | list[ImagePart] | None = None) -> Any:
        kwargs: dict[str, object] = {"streaming_behavior": streaming_behavior}
        if _supports_keyword(prompt, "source"):
            kwargs["source"] = "interactive"
        if images is not None and _supports_keyword(prompt, "images"):
            kwargs["images"] = list(images)
        return await _maybe_await(prompt(text, **kwargs))

    return _call


async def _call_text_method(
    method: Any,
    text: str,
    *,
    images: tuple[ImagePart, ...] | list[ImagePart] | None = None,
) -> Any:
    if images is not None and _supports_keyword(method, "images"):
        return await _maybe_await(method(text, images=list(images)))
    return await _maybe_await(method(text))


def _supports_keyword(method: Any, keyword: str) -> bool:
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return False
    parameters = signature.parameters.values()
    return any(parameter.kind is inspect.Parameter.VAR_KEYWORD or parameter.name == keyword for parameter in parameters)


def _session_commands_provider(session: Any):
    getter = getattr(session, "list_commands", None)
    if not callable(getter):
        return None
    return getter


def _controller_result_from_command_execution(execution: object, *, invocation_name: str) -> ControllerResult:
    result = getattr(execution, "result", None)
    if result is None and not hasattr(execution, "result"):
        result = execution
    if isinstance(result, dict):
        message = result.get("message")
        if isinstance(message, str) and message:
            if result.get("status") == "error":
                return ControllerResult(error_message=message)
            return ControllerResult(status_message=message)
    return ControllerResult(status_message=f"Command /{invocation_name} completed.")


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


__all__ = ["CodingUiController", "ControllerResult"]
