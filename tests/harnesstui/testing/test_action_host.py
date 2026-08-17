from __future__ import annotations

import asyncio
from pathlib import Path

from loushang.harnesstui.conversation.attachments import PromptImageAttachment
from loushang.harnesstui.conversation.control import ConversationTextAction
from loushang.harnesstui.testing.action_host import CallbackConversationActionHost


def _attachment() -> PromptImageAttachment:
    return PromptImageAttachment(
        bytes=b"png bytes",
        mime_type="image/png",
        path=Path("/tmp/clipboard.png"),
        display_path=".loushang/clipboard/clipboard.png",
        marker="@.loushang/clipboard/clipboard.png",
    )


def test_callback_action_host_passes_attachments_to_aware_callback() -> None:
    calls: list[tuple[str, tuple[PromptImageAttachment, ...]]] = []

    async def submit(
        text: str,
        *,
        attachments: tuple[PromptImageAttachment, ...],
    ) -> int:
        calls.append((text, attachments))
        return 4

    attachment = _attachment()
    host = CallbackConversationActionHost(submit=submit)

    result = asyncio.run(
        host.submit(ConversationTextAction("describe", attachments=(attachment,)))
    )

    assert result == 4
    assert calls == [("describe", (attachment,))]


def test_callback_action_host_keeps_text_only_callbacks_compatible() -> None:
    calls: list[str] = []

    def steer(text: str) -> int:
        calls.append(text)
        return 5

    host = CallbackConversationActionHost(steer=steer)

    result = asyncio.run(
        host.steer(ConversationTextAction("change", attachments=(_attachment(),)))
    )

    assert result == 5
    assert calls == ["change"]
