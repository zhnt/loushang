from __future__ import annotations

import asyncio
import base64
from io import StringIO
from pathlib import Path

from loushang.ai.types import ImagePart
from loushang.coding.ui.product_binding import (
    build_screen_coding_action_host,
)
from loushang.harness.host.types import HostActionResult
from loushang.harnesstui.conversation.attachments import PromptImageAttachment
from loushang.harnesstui.conversation.control import ConversationTextAction
from loushang.harnesstui.conversation.intents import (
    AbortIntent,
    ConversationIntent,
    PromptIntent,
)


class _Presenter:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.statuses: list[str] = []
        self.current_statuses: list[str | None] = []

    def add_error(self, text: str) -> None:
        self.errors.append(text)

    def add_status(self, text: str) -> None:
        self.statuses.append(text)

    def set_status(self, message: str | None) -> None:
        self.current_statuses.append(message)


class _Controller:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.dispatch_result = HostActionResult(exit_code=7)
        self.steer_result = HostActionResult()
        self.follow_up_result = HostActionResult()

    async def dispatch(self, intent: ConversationIntent) -> HostActionResult:
        self.calls.append(("dispatch", intent))
        return self.dispatch_result

    async def steer(
        self,
        text: str,
        images: tuple[ImagePart, ...] | None = None,
    ) -> HostActionResult:
        self.calls.append(("steer", (text, images)))
        return self.steer_result

    async def follow_up(
        self,
        text: str,
        images: tuple[ImagePart, ...] | None = None,
    ) -> HostActionResult:
        self.calls.append(("follow_up", (text, images)))
        return self.follow_up_result

    async def wait_for_idle(self) -> None:
        self.calls.append(("wait_for_idle", None))


def _attachment() -> PromptImageAttachment:
    return PromptImageAttachment(
        bytes=b"png bytes",
        mime_type="image/png",
        path=Path("/tmp/clipboard.png"),
        display_path=".loushang/clipboard/clipboard.png",
        marker="@.loushang/clipboard/clipboard.png",
    )


def _host(
    controller: _Controller,
    presenter: _Presenter,
    *,
    stderr: StringIO | None = None,
    verbose: bool = False,
):
    return build_screen_coding_action_host(
        presenter=presenter,
        controller=controller,
        stderr=stderr or StringIO(),
        verbose=verbose,
    )


def test_screen_action_host_submits_prompt_intent_with_coding_image_parts() -> None:
    controller = _Controller()
    presenter = _Presenter()
    attachment = _attachment()

    result = asyncio.run(
        _host(controller, presenter).submit(
            ConversationTextAction("  describe this  ", attachments=(attachment,))
        )
    )

    expected_image = ImagePart(
        type="image",
        data=base64.b64encode(attachment.bytes).decode("ascii"),
        mime_type="image/png",
    )
    assert result == 7
    assert controller.calls == [
        ("dispatch", PromptIntent("describe this", images=(expected_image,)))
    ]


def test_screen_action_host_routes_steer_and_follow_up_with_attachments() -> None:
    controller = _Controller()
    controller.steer_result = HostActionResult(
        exit_code=2,
        error_message="steer failed",
        traceback_text="steer traceback\n",
    )
    controller.follow_up_result = HostActionResult(
        exit_code=3,
        status_message="follow-up queued",
    )
    presenter = _Presenter()
    stderr = StringIO()
    host = _host(controller, presenter, stderr=stderr, verbose=True)
    attachment = _attachment()

    steer_result = asyncio.run(
        host.steer(ConversationTextAction("change", attachments=(attachment,)))
    )
    follow_up_result = asyncio.run(
        host.follow_up(ConversationTextAction("later", attachments=(attachment,)))
    )

    expected_images = (
        ImagePart(
            type="image",
            data=base64.b64encode(attachment.bytes).decode("ascii"),
            mime_type="image/png",
        ),
    )
    assert steer_result == 2
    assert follow_up_result == 3
    assert controller.calls == [
        ("steer", ("change", expected_images)),
        ("follow_up", ("later", expected_images)),
    ]
    assert presenter.errors == ["steer failed"]
    assert presenter.statuses == ["follow-up queued"]
    assert presenter.current_statuses == [
        "Steering failed: steer failed",
        "follow-up queued",
    ]
    assert stderr.getvalue() == "steer traceback\n"


def test_screen_action_host_aborts_then_waits_for_session_to_settle() -> None:
    controller = _Controller()
    host = _host(controller, _Presenter())

    asyncio.run(host.abort())

    assert controller.calls == [
        ("dispatch", AbortIntent()),
        ("wait_for_idle", None),
    ]
