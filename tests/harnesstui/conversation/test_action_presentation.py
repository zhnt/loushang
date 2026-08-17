from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from loushang.harnesstui.conversation.action_presentation import (
    ConversationActionPresentationCopy,
    ConversationActionResultPresenter,
    ConversationTracebackPolicy,
    PresentedConversationActionHost,
    PresentedConversationActionPorts,
)
from loushang.harnesstui.conversation.attachments import PromptImageAttachment
from loushang.harnesstui.conversation.control import ConversationTextAction


@dataclass(frozen=True)
class _Result:
    exit_code: int | None = None
    error_message: str | None = None
    status_message: str | None = None
    traceback_text: str | None = None


class _PresentationTarget:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def add_error(self, text: str) -> None:
        self.calls.append(("add_error", text))

    def add_status(self, text: str) -> None:
        self.calls.append(("add_status", text))

    def set_status(self, message: str | None) -> None:
        self.calls.append(("set_status", message))


def test_action_result_presenter_preserves_callback_and_traceback_order() -> None:
    target = _PresentationTarget()
    stderr = StringIO()
    presenter = ConversationActionResultPresenter(
        target=target,
        stderr=stderr,
        traceback_policy=ConversationTracebackPolicy(enabled=True),
    )

    exit_code = presenter.present(
        _Result(
            exit_code=2,
            error_message="failed",
            traceback_text="traceback\n",
        ),
        failure_status=lambda message: f"caller failure: {message}",
    )
    status_code = presenter.present(
        _Result(exit_code=3, status_message="queued"),
        failure_status=lambda message: message,
    )

    assert exit_code == 2
    assert status_code == 3
    assert target.calls == [
        ("add_error", "failed"),
        ("set_status", "caller failure: failed"),
        ("add_status", "queued"),
        ("set_status", "queued"),
    ]
    assert stderr.getvalue() == "traceback\n"


@dataclass(frozen=True)
class _Intent:
    text: str
    prepared: bool = False


def _attachment() -> PromptImageAttachment:
    return PromptImageAttachment(
        bytes=b"png",
        mime_type="image/png",
        path=Path("/tmp/image.png"),
        display_path="image.png",
        marker="@image.png",
    )


def test_presented_action_host_sequences_routes_over_explicit_ports() -> None:
    calls: list[tuple[str, object]] = []
    target = _PresentationTarget()

    def parse(text: str) -> _Intent | None:
        calls.append(("parse", text))
        return None if not text.strip() else _Intent(text)

    def prepare(
        intent: _Intent,
        attachments: tuple[PromptImageAttachment, ...],
    ) -> _Intent:
        calls.append(("prepare", (intent, attachments)))
        return _Intent(intent.text, prepared=True)

    async def dispatch(intent: _Intent) -> _Result:
        calls.append(("dispatch", intent))
        return _Result(exit_code=4, status_message="done")

    async def steer(
        text: str,
        attachments: tuple[PromptImageAttachment, ...],
    ) -> _Result:
        calls.append(("steer", (text, attachments)))
        return _Result(exit_code=5, error_message="steer error")

    async def follow_up(
        text: str,
        attachments: tuple[PromptImageAttachment, ...],
    ) -> _Result:
        calls.append(("follow_up", (text, attachments)))
        return _Result(exit_code=6)

    async def wait_for_idle() -> object:
        calls.append(("wait_for_idle", None))
        return None

    host = PresentedConversationActionHost(
        ports=PresentedConversationActionPorts(
            parse=parse,
            exit_code=lambda intent: 0 if intent.text == "/quit" else None,
            attachments=lambda values: values,
            prepare=prepare,
            dispatch=dispatch,
            steer=steer,
            follow_up=follow_up,
            abort_intent=lambda: _Intent("abort"),
            wait_for_idle=wait_for_idle,
        ),
        presenter=ConversationActionResultPresenter(
            target=target,
            stderr=StringIO(),
            traceback_policy=ConversationTracebackPolicy(enabled=False),
        ),
        copy=ConversationActionPresentationCopy(
            dispatch_failure_status=lambda message: f"dispatch: {message}",
            steer_failure_status=lambda message: f"steer: {message}",
            follow_up_failure_status=lambda message: f"follow: {message}",
        ),
    )
    attachment = _attachment()

    async def exercise() -> list[int | None]:
        results = [
            await host.submit(ConversationTextAction("   ")),
            await host.submit(ConversationTextAction("/quit")),
            await host.submit(
                ConversationTextAction("prompt", attachments=(attachment,))
            ),
            await host.steer(
                ConversationTextAction("change", attachments=(attachment,))
            ),
            await host.follow_up(ConversationTextAction("later")),
        ]
        await host.abort()
        return results

    assert asyncio.run(exercise()) == [None, 0, 4, 5, 6]
    assert [name for name, _value in calls] == [
        "parse",
        "parse",
        "parse",
        "prepare",
        "dispatch",
        "steer",
        "follow_up",
        "dispatch",
        "wait_for_idle",
    ]
    prepared_attachments = next(value for name, value in calls if name == "prepare")[1]
    assert prepared_attachments == (attachment,)
    assert target.calls == [
        ("add_status", "done"),
        ("set_status", "done"),
        ("add_error", "steer error"),
        ("set_status", "steer: steer error"),
    ]
