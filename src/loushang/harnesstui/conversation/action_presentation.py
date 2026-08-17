"""Product-neutral action result presentation and screen action sequencing."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, Protocol, TextIO, TypeVar

from loushang.harnesstui.conversation.attachments import PromptImageAttachment
from loushang.harnesstui.conversation.control import ConversationTextAction
from loushang.harnesstui.conversation.intents import (
    AbortIntent,
    ConversationIntent,
    PromptIntent,
    QuitIntent,
    parse_conversation_intent,
)


class ConversationActionResultPort(Protocol):
    """Structural result contract accepted by shared presenters."""

    @property
    def exit_code(self) -> int | None: ...

    @property
    def error_message(self) -> str | None: ...

    @property
    def status_message(self) -> str | None: ...

    @property
    def traceback_text(self) -> str | None: ...


@dataclass(frozen=True, slots=True)
class ConversationTracebackPolicy:
    """Choose whether UI action failures capture and emit tracebacks."""

    enabled: bool

    def write(self, text: str | None, *, sink: TextIO) -> None:
        if not self.enabled or not text:
            return
        sink.write(text)
        sink.flush()


class ConversationActionPresentationPort(Protocol):
    """Immediate screen presentation operations used by the result presenter."""

    def add_error(self, text: str) -> None: ...

    def add_status(self, text: str) -> None: ...

    def set_status(self, message: str | None) -> None: ...


FailureStatus = Callable[[str], str]


@dataclass(frozen=True, slots=True)
class ConversationActionPresentationCopy:
    """Product-owned failure copy for each screen action route."""

    dispatch_failure_status: FailureStatus
    steer_failure_status: FailureStatus
    follow_up_failure_status: FailureStatus


class ConversationActionResultPresenter:
    """Present one neutral result with deterministic screen callback ordering."""

    def __init__(
        self,
        *,
        target: ConversationActionPresentationPort,
        stderr: TextIO,
        traceback_policy: ConversationTracebackPolicy,
    ) -> None:
        self._target = target
        self._stderr = stderr
        self._traceback_policy = traceback_policy

    def present(
        self,
        result: ConversationActionResultPort,
        *,
        failure_status: FailureStatus,
    ) -> int | None:
        if result.error_message:
            self._target.add_error(result.error_message)
            self._target.set_status(failure_status(result.error_message))
        elif result.status_message:
            self._target.add_status(result.status_message)
            self._target.set_status(result.status_message)
        self._traceback_policy.write(result.traceback_text, sink=self._stderr)
        return result.exit_code


IntentT = TypeVar("IntentT")
AttachmentsT = TypeVar("AttachmentsT")
ControllerAttachmentsT = TypeVar("ControllerAttachmentsT", contravariant=True)


@dataclass(frozen=True, slots=True)
class PresentedConversationActionPorts(Generic[IntentT, AttachmentsT]):
    """Product policy and effects used by the immediate-presentation host."""

    parse: Callable[[str], IntentT | None]
    exit_code: Callable[[IntentT], int | None]
    attachments: Callable[[tuple[PromptImageAttachment, ...]], AttachmentsT]
    prepare: Callable[[IntentT, AttachmentsT], IntentT]
    dispatch: Callable[[IntentT], Awaitable[ConversationActionResultPort]]
    steer: Callable[[str, AttachmentsT], Awaitable[ConversationActionResultPort]]
    follow_up: Callable[[str, AttachmentsT], Awaitable[ConversationActionResultPort]]
    abort_intent: Callable[[], IntentT]
    wait_for_idle: Callable[[], Awaitable[object]]


class PresentedConversationActionHost(Generic[IntentT, AttachmentsT]):
    """Sequence screen actions over explicit product ports and neutral results."""

    def __init__(
        self,
        *,
        ports: PresentedConversationActionPorts[IntentT, AttachmentsT],
        presenter: ConversationActionResultPresenter,
        copy: ConversationActionPresentationCopy,
    ) -> None:
        self._ports = ports
        self._presenter = presenter
        self._copy = copy

    async def submit(self, action: ConversationTextAction) -> int | None:
        intent = self._ports.parse(action.text)
        if intent is None:
            return None
        exit_code = self._ports.exit_code(intent)
        if exit_code is not None:
            return exit_code
        attachments = self._ports.attachments(tuple(action.attachments))
        result = await self._ports.dispatch(self._ports.prepare(intent, attachments))
        return self._presenter.present(
            result,
            failure_status=self._copy.dispatch_failure_status,
        )

    async def steer(self, action: ConversationTextAction) -> int | None:
        result = await self._ports.steer(
            action.text,
            self._ports.attachments(tuple(action.attachments)),
        )
        return self._presenter.present(
            result,
            failure_status=self._copy.steer_failure_status,
        )

    async def follow_up(self, action: ConversationTextAction) -> int | None:
        result = await self._ports.follow_up(
            action.text,
            self._ports.attachments(tuple(action.attachments)),
        )
        return self._presenter.present(
            result,
            failure_status=self._copy.follow_up_failure_status,
        )

    async def abort(self) -> None:
        await self._ports.dispatch(self._ports.abort_intent())
        await self._ports.wait_for_idle()


class StandardConversationControllerPort(Protocol[ControllerAttachmentsT]):
    """Controller effects consumed by the standard presented action host."""

    async def dispatch(
        self,
        intent: ConversationIntent,
    ) -> ConversationActionResultPort: ...

    async def steer(
        self,
        text: str,
        images: ControllerAttachmentsT,
    ) -> ConversationActionResultPort: ...

    async def follow_up(
        self,
        text: str,
        images: ControllerAttachmentsT,
    ) -> ConversationActionResultPort: ...

    async def wait_for_idle(self) -> object: ...


STANDARD_CONVERSATION_ACTION_COPY = ConversationActionPresentationCopy(
    dispatch_failure_status=lambda message: f"Request failed: {message}",
    steer_failure_status=lambda message: f"Steering failed: {message}",
    follow_up_failure_status=lambda message: f"Follow-up failed: {message}",
)


def build_standard_presented_conversation_action_host(
    *,
    presenter: ConversationActionPresentationPort,
    controller: StandardConversationControllerPort[AttachmentsT],
    stderr: TextIO,
    verbose: bool,
    attachments: Callable[[tuple[PromptImageAttachment, ...]], AttachmentsT],
    copy: ConversationActionPresentationCopy = STANDARD_CONVERSATION_ACTION_COPY,
) -> PresentedConversationActionHost[ConversationIntent, AttachmentsT]:
    """Bind standard intents to the existing immediate-presentation host."""

    def prepare(
        intent: ConversationIntent,
        values: AttachmentsT,
    ) -> ConversationIntent:
        if isinstance(intent, PromptIntent):
            return PromptIntent(intent.text, images=values)  # type: ignore[arg-type]
        return intent

    return PresentedConversationActionHost(
        ports=PresentedConversationActionPorts(
            parse=parse_conversation_intent,
            exit_code=lambda intent: 0 if isinstance(intent, QuitIntent) else None,
            attachments=attachments,
            prepare=prepare,
            dispatch=controller.dispatch,
            steer=controller.steer,
            follow_up=controller.follow_up,
            abort_intent=AbortIntent,
            wait_for_idle=controller.wait_for_idle,
        ),
        presenter=ConversationActionResultPresenter(
            target=presenter,
            stderr=stderr,
            traceback_policy=ConversationTracebackPolicy(enabled=verbose),
        ),
        copy=copy,
    )


__all__ = [
    "ConversationActionPresentationCopy",
    "ConversationActionPresentationPort",
    "ConversationActionResultPort",
    "ConversationActionResultPresenter",
    "ConversationTracebackPolicy",
    "PresentedConversationActionHost",
    "PresentedConversationActionPorts",
    "STANDARD_CONVERSATION_ACTION_COPY",
    "StandardConversationControllerPort",
    "build_standard_presented_conversation_action_host",
]
