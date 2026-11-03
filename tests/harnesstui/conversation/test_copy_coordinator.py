from __future__ import annotations

import asyncio

from loushang.harnesstui.conversation.copy_coordinator import CopyCoordinator
from loushang.tui.text_clipboard import TextCopyResult


def test_copy_requests_serialize_and_only_latest_result_reports_status() -> None:
    async def scenario() -> None:
        messages: list[str] = []
        started: list[str] = []
        gate = asyncio.Event()

        class Writer:
            destination = "user"

            async def write(self, text: str) -> TextCopyResult:
                started.append(text)
                if text == "first":
                    await gate.wait()
                return TextCopyResult("confirmed", "user")

        coordinator = CopyCoordinator(Writer(), messages.append)
        coordinator.submit("first")
        await asyncio.sleep(0)
        coordinator.submit("second")
        gate.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await coordinator.close()
        assert started == ["first", "second"]
        assert messages == ["Copied to clipboard"]

    asyncio.run(scenario())


def test_unavailable_copy_does_not_claim_success() -> None:
    async def scenario() -> None:
        messages: list[str] = []
        coordinator = CopyCoordinator(None, messages.append)
        coordinator.submit("answer")
        coordinator.submit("")
        await coordinator.close()
        assert messages == [
            "Clipboard is unavailable in this terminal",
            "No completed assistant answer to copy",
        ]

    asyncio.run(scenario())
