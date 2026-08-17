from __future__ import annotations

import asyncio

from loushang.harness.session import SessionOperationRuntime
from loushang.harnesstui.conversation.queue import (
    cleared_queue_messages,
    pending_queue_view,
    restore_queued_messages,
    session_pending_messages,
)


class _Session:
    def __init__(self) -> None:
        self.steering = ["steer"]
        self.follow_up = ["follow"]

    def get_steering_messages(self):
        return list(self.steering)

    def get_follow_up_messages(self):
        return list(self.follow_up)


def test_pending_queue_view_maps_session_queues_to_generic_tui_sections() -> None:
    view = pending_queue_view(SessionOperationRuntime(_Session()))

    assert [
        (section.label, tuple(section.items), section.hint) for section in view.sections
    ] == [
        (
            "Messages to be submitted after next tool call",
            ("steer",),
            "press esc to interrupt and send immediately",
        ),
        ("Messages to be submitted at end of turn", ("follow",), None),
    ]


def test_cleared_queue_messages_supports_aliases_and_stringifies_values() -> None:
    assert cleared_queue_messages({"steering": [1], "follow_up": ["next"]}) == [
        "1",
        "next",
    ]
    assert cleared_queue_messages({"steering": ["steer"], "followUp": [2]}) == [
        "steer",
        "2",
    ]
    assert cleared_queue_messages(None) == []


def test_session_pending_messages_is_defensive() -> None:
    class Broken:
        def get_steering_messages(self):
            raise RuntimeError("boom")

    assert (
        session_pending_messages(
            SessionOperationRuntime(Broken()),
            "steering",
        )
        == []
    )


def test_restore_queued_messages_merges_queue_and_current_text() -> None:
    class Session:
        def clear_queue(self):
            return {"steering": ["steer one"], "follow_up": ["follow one"]}

    restored = asyncio.run(
        restore_queued_messages(SessionOperationRuntime(Session()), "draft")
    )

    assert restored == "steer one\n\nfollow one\n\ndraft"


def test_restore_queued_messages_traces_typed_queue_clear() -> None:
    traces: list[tuple[str, dict[str, object]]] = []

    class Session:
        def clear_queue(self):
            return {"steering": ["steer"]}

    restored = asyncio.run(
        restore_queued_messages(
            SessionOperationRuntime(Session()),
            "   ",
            trace=lambda name, **data: traces.append((name, data)),
        )
    )

    assert restored == "steer"
    assert traces == [("queue.dequeued", {"count": 1, "current_text_len": 3})]


def test_restore_queued_messages_returns_none_when_unavailable_or_empty() -> None:
    traces: list[str] = []

    assert (
        asyncio.run(
            restore_queued_messages(
                SessionOperationRuntime(object()),
                "",
                trace=lambda name, **_data: traces.append(name),
            )
        )
        is None
    )

    class EmptySession:
        def clear_queue(self):
            return {"steering": []}

    assert (
        asyncio.run(
            restore_queued_messages(
                SessionOperationRuntime(EmptySession()),
                "",
                trace=lambda name, **_data: traces.append(name),
            )
        )
        is None
    )
    assert traces == ["queue.dequeue.unavailable", "queue.dequeue.empty"]
