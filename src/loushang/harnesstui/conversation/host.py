"""Product-neutral routing for conversation actions."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from enum import Enum
from typing import Generic, TextIO, TypeVar

from loushang.harness.commands import CommandEffect
from loushang.harnesstui.conversation.attachments import PromptImageAttachment
from loushang.harnesstui.conversation.control import (
    ConversationActionHost,
    ConversationRunControl,
    ConversationTextAction,
)
from loushang.harnesstui.conversation.info import ConversationLocalActionRegistry
from loushang.harnesstui.conversation.intents import (
    ConversationIntent,
    FollowUpIntent,
    QuitIntent,
    parse_conversation_intent,
)
from loushang.harnesstui.conversation.run_context import TraceFn
from loushang.harnesstui.conversation.screen_runner import (
    AbortHandler,
    ConversationInputRouterFactoryPort,
    ConversationScreenPort,
    LocalCommandPredicate,
    ShouldExit,
    SurfaceIntentHandler,
    TerminalModeFactory,
    TerminalSizeProvider,
    TextHandler,
    run_conversation_screen,
)
from loushang.tui.keybindings import KeybindingConfig, KeybindingManager
from loushang.tui.terminal_input import InputChunkReader

IntentT = TypeVar("IntentT")
OutcomeT = TypeVar("OutcomeT")
LocalT = TypeVar("LocalT")
PendingT = TypeVar("PendingT")


class ConversationHostRoute(Enum):
    """Mechanism-level routes understood by a conversation action host."""

    ABORT_SETTLING = "abort_settling"
    FOLLOW_UP = "follow_up"
    STEER = "steer"
    LOCAL = "local"
    DISPATCH = "dispatch"


@dataclass(frozen=True, slots=True)
class ConversationHostDecision(Generic[LocalT]):
    """One product decision projected onto a neutral host route.

    ``text`` and ``source`` selectively replace the corresponding action
    fields. Attachments always come from the submitted action, so routing a
    prompt to follow-up or steer cannot accidentally discard them.
    """

    route: ConversationHostRoute
    local: LocalT | None = None
    text: str | None = None
    source: str | None = None

    def apply(self, action: ConversationTextAction) -> ConversationTextAction:
        return replace(
            action,
            text=action.text if self.text is None else self.text,
            source=action.source if self.source is None else self.source,
        )


@dataclass(frozen=True, slots=True)
class ConversationHostProfile(Generic[IntentT, LocalT]):
    """Product policy used by :class:`RoutedConversationActionHost`."""

    parse: Callable[[ConversationTextAction], IntentT | None]
    decide: Callable[
        [IntentT, ConversationTextAction],
        ConversationHostDecision[LocalT],
    ]
    is_exit: Callable[[IntentT], bool]
    now: Callable[[], float] = time.monotonic
    follow_up_source: str = "keybinding"


@dataclass(frozen=True, slots=True)
class ConversationRoutingProfile(Generic[IntentT, LocalT]):
    """Compose standard conversation routing from Product intent callbacks."""

    lifecycle: ConversationRunControl
    parse_intent: Callable[[str], IntentT | None]
    is_exit: Callable[[IntentT], bool]
    local_action: Callable[[IntentT], LocalT | None]
    deferred_local_action: Callable[[IntentT], LocalT | None]
    follow_up_text: Callable[[IntentT], str | None]
    command_effect: Callable[[LocalT, IntentT], CommandEffect | None]
    session_running: Callable[[], bool]
    trace: TraceFn

    def host_profile(
        self,
        *,
        now: Callable[[], float],
    ) -> ConversationHostProfile[IntentT, LocalT]:
        return ConversationHostProfile(
            parse=self.parse,
            decide=self.decide,
            is_exit=self.is_exit,
            now=now,
        )

    def parse(self, action: ConversationTextAction) -> IntentT | None:
        self.trace(
            "prompt.start",
            active_run=self.lifecycle.active,
            active_run_id=self.lifecycle.active_id,
            aborted_run_id=self.lifecycle.aborted_id,
            session_running=self.session_running(),
            text_len=len(action.text),
        )
        intent = self.parse_intent(action.text)
        if intent is None:
            self.trace("prompt.ignored", reason="empty")
        return intent

    def decide(
        self,
        intent: IntentT,
        _action: ConversationTextAction,
    ) -> ConversationHostDecision[LocalT]:
        if self.lifecycle.abort_is_settling() and not self.is_exit(intent):
            self.trace(
                "prompt.ignored",
                reason="abort_in_progress",
                active_run_id=self.lifecycle.active_id,
            )
            return ConversationHostDecision(ConversationHostRoute.ABORT_SETTLING)
        local_action = self.local_action(intent)
        if local_action is not None:
            return self._local_decision(local_action, intent)
        follow_up_text = self.follow_up_text(intent)
        if follow_up_text is not None:
            return ConversationHostDecision(
                ConversationHostRoute.FOLLOW_UP,
                text=follow_up_text,
                source="command",
            )
        if self.lifecycle.active and not self.is_exit(intent):
            return ConversationHostDecision(ConversationHostRoute.STEER)
        local_action = self.deferred_local_action(intent)
        if local_action is not None:
            return self._local_decision(local_action, intent)
        return ConversationHostDecision(ConversationHostRoute.DISPATCH)

    def _local_decision(
        self,
        action: LocalT,
        intent: IntentT,
    ) -> ConversationHostDecision[LocalT]:
        effect = self.command_effect(action, intent)
        if effect is not None:
            self.trace(
                "prompt.command",
                route=str(action.value if isinstance(action, Enum) else action),
                command_id=effect.command.id,
                command_name=effect.command.name,
                effect=effect.kind.value,
            )
        return ConversationHostDecision(ConversationHostRoute.LOCAL, local=action)


def build_standard_conversation_host_profile(
    *,
    lifecycle: ConversationRunControl,
    local_actions: ConversationLocalActionRegistry[ConversationIntent],
    command_effect: Callable[[str, ConversationIntent], CommandEffect | None],
    session_running: Callable[[], bool],
    trace: TraceFn,
    now: Callable[[], float],
) -> ConversationHostProfile[ConversationIntent, str]:
    """Bind standard Agent Product intents to the existing routed host."""

    routing: ConversationRoutingProfile[ConversationIntent, str] = (
        ConversationRoutingProfile(
            lifecycle=lifecycle,
            parse_intent=parse_conversation_intent,
            is_exit=lambda intent: isinstance(intent, QuitIntent),
            local_action=local_actions.immediate_action,
            deferred_local_action=local_actions.deferred_action,
            follow_up_text=lambda intent: (
                intent.text if isinstance(intent, FollowUpIntent) else None
            ),
            command_effect=command_effect,
            session_running=session_running,
            trace=trace,
        )
    )
    return routing.host_profile(now=now)


@dataclass(frozen=True, slots=True)
class ConversationHostPorts(Generic[IntentT, OutcomeT, LocalT, PendingT]):
    """Effects supplied by a product around the neutral routing mechanism."""

    abort_settling: Callable[
        [ConversationTextAction, IntentT],
        Awaitable[None],
    ]
    follow_up: Callable[[ConversationTextAction], Awaitable[int | None]]
    steer: Callable[[ConversationTextAction], Awaitable[int | None]]
    local: Callable[
        [ConversationTextAction, IntentT, LocalT | None],
        Awaitable[int | None],
    ]
    dispatch: Callable[
        [ConversationTextAction, IntentT],
        Awaitable[OutcomeT],
    ]
    result: Callable[
        [OutcomeT, ConversationTextAction, IntentT, float],
        Awaitable[int | None],
    ]
    abort: Callable[[], Awaitable[None]]
    restore_queue: Callable[[str], Awaitable[str | None]]
    pending_messages: Callable[[], PendingT]


class RoutedConversationActionHost(Generic[IntentT, OutcomeT, LocalT, PendingT]):
    """Route neutral UI actions through injected product policy and effects.

    This class coordinates ordering only. It owns no Session, product intent,
    command catalog, renderer, queue, or model-facing attachment conversion.
    """

    def __init__(
        self,
        *,
        profile: ConversationHostProfile[IntentT, LocalT],
        ports: ConversationHostPorts[IntentT, OutcomeT, LocalT, PendingT],
    ) -> None:
        self._profile = profile
        self._ports = ports

    async def submit(self, action: ConversationTextAction) -> int | None:
        prompt_started = self._profile.now()
        intent = self._profile.parse(action)
        if intent is None:
            return None

        decision = self._profile.decide(intent, action)
        routed_action = decision.apply(action)
        if decision.route is ConversationHostRoute.ABORT_SETTLING:
            await self._ports.abort_settling(routed_action, intent)
            return None
        if decision.route is ConversationHostRoute.FOLLOW_UP:
            return await self._ports.follow_up(routed_action)
        if decision.route is ConversationHostRoute.STEER:
            return await self._ports.steer(routed_action)
        if decision.route is ConversationHostRoute.LOCAL:
            return await self._ports.local(
                routed_action,
                intent,
                decision.local,
            )

        outcome = await self._ports.dispatch(routed_action, intent)
        return await self._ports.result(
            outcome,
            routed_action,
            intent,
            prompt_started,
        )

    async def steer(self, action: ConversationTextAction) -> int | None:
        return await self._ports.steer(action)

    async def follow_up(self, action: ConversationTextAction) -> int | None:
        if action.source:
            routed_action = action
        else:
            routed_action = replace(
                action,
                source=self._profile.follow_up_source,
            )
        return await self._ports.follow_up(routed_action)

    async def abort(self) -> None:
        await self._ports.abort()

    async def restore_queue_to_composer(self, current_text: str) -> str | None:
        return await self._ports.restore_queue(current_text)

    def pending_messages(self) -> PendingT:
        return self._ports.pending_messages()

    def should_exit(self, text: str) -> bool:
        intent = self._profile.parse(ConversationTextAction(text=text))
        return intent is not None and self._profile.is_exit(intent)


@dataclass(frozen=True, slots=True)
class ConversationScreenCallbacks:
    """Action callbacks accepted by ``run_conversation_screen``."""

    handle_prompt: TextHandler
    handle_local: TextHandler
    handle_steer: TextHandler
    handle_followup: TextHandler
    on_abort: AbortHandler


@dataclass(frozen=True, slots=True)
class ConversationScreenRunProfile:
    """Product policy needed by the shared action-host screen binding."""

    input_router_factory: ConversationInputRouterFactoryPort | None
    interruption_message: str
    cancellation_message: str


def bind_action_host_to_screen_runner(
    host: ConversationActionHost,
) -> ConversationScreenCallbacks:
    """Adapt a neutral action host to the shared screen runner callbacks."""

    return ConversationScreenCallbacks(
        handle_prompt=_bind_text_action(host.submit, source="prompt"),
        handle_local=_bind_text_action(host.submit, source="local"),
        handle_steer=_bind_text_action(host.steer, source="steer"),
        handle_followup=_bind_text_action(host.follow_up, source="follow_up"),
        on_abort=host.abort,
    )


async def run_action_host_conversation_screen(
    *,
    app: ConversationScreenPort,
    stdin: TextIO,
    stdout: TextIO,
    action_host: ConversationActionHost,
    profile: ConversationScreenRunProfile,
    handle_local: TextHandler | None = None,
    handle_surface_intent: SurfaceIntentHandler | None = None,
    should_exit: ShouldExit,
    is_local_command: LocalCommandPredicate | None = None,
    keybindings: KeybindingManager | KeybindingConfig | None = None,
    terminal_mode_factory: TerminalModeFactory | None = None,
    terminal_size_provider: TerminalSizeProvider | None = None,
    input_chunk_reader: InputChunkReader | None = None,
) -> int:
    """Run a screen by binding one neutral action host exactly once."""

    callbacks = bind_action_host_to_screen_runner(action_host)
    return await run_conversation_screen(
        app=app,
        stdin=stdin,
        stdout=stdout,
        handle_prompt=callbacks.handle_prompt,
        handle_local=handle_local,
        handle_steer=callbacks.handle_steer,
        handle_followup=callbacks.handle_followup,
        handle_surface_intent=handle_surface_intent,
        on_abort=callbacks.on_abort,
        should_exit=should_exit,
        is_local_command=is_local_command,
        keybindings=keybindings,
        terminal_mode_factory=terminal_mode_factory,
        terminal_size_provider=terminal_size_provider,
        input_chunk_reader=input_chunk_reader,
        input_router_factory=profile.input_router_factory,
        interruption_message=profile.interruption_message,
        cancellation_message=profile.cancellation_message,
    )


TextActionHandler = Callable[
    [ConversationTextAction],
    Awaitable[int | None],
]


def _bind_text_action(
    handler: TextActionHandler,
    *,
    source: str,
) -> TextHandler:
    async def adapted(
        text: str,
        *,
        attachments: tuple[object, ...] | None = None,
    ) -> int | None:
        return await handler(
            ConversationTextAction(
                text=text,
                attachments=tuple(
                    _require_prompt_image_attachment(attachment)
                    for attachment in attachments or ()
                ),
                source=source,
            )
        )

    return adapted


def _require_prompt_image_attachment(value: object) -> PromptImageAttachment:
    if not isinstance(value, PromptImageAttachment):
        raise TypeError("conversation attachments must be prompt images")
    return value


__all__ = [
    "ConversationHostDecision",
    "ConversationHostPorts",
    "ConversationHostProfile",
    "ConversationHostRoute",
    "ConversationRoutingProfile",
    "ConversationScreenCallbacks",
    "ConversationScreenRunProfile",
    "RoutedConversationActionHost",
    "bind_action_host_to_screen_runner",
    "build_standard_conversation_host_profile",
    "run_action_host_conversation_screen",
]
