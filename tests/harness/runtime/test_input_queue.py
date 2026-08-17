from __future__ import annotations

from dataclasses import dataclass

import pytest

from loushang.harness.runtime.input_queue import HostInputQueue


@dataclass(frozen=True)
class ReferenceInput:
    value: str


def test_host_input_queue_tracks_neutral_payloads_and_snapshots() -> None:
    queue: HostInputQueue[ReferenceInput] = HostInputQueue()
    steering = ReferenceInput("inspect sources")
    follow_up = ReferenceInput("write report")

    first = queue.enqueue("steering", text="inspect", payload=steering)
    second = queue.enqueue("follow_up", text="report", payload=follow_up)

    assert (first.id, second.id) == ("q1", "q2")
    assert queue.pending_count == 2
    assert queue.has_pending() is True
    assert queue.texts("steering") == ["inspect"]
    assert queue.snapshot().follow_up == (second,)


def test_host_input_queue_consumes_identity_before_duplicate_text() -> None:
    queue: HostInputQueue[ReferenceInput] = HostInputQueue()
    first_payload = ReferenceInput("same")
    second_payload = ReferenceInput("same")
    first = queue.enqueue("steering", text="same", payload=first_payload)
    second = queue.enqueue("steering", text="same", payload=second_payload)

    consumed = queue.consume(second_payload, fallback_text="same")

    assert consumed == second
    assert queue.snapshot().steering == (first,)


def test_host_input_queue_falls_back_to_one_visible_text_match() -> None:
    queue: HostInputQueue[ReferenceInput] = HostInputQueue()
    first = queue.enqueue(
        "steering",
        text="same",
        payload=ReferenceInput("first"),
    )
    queue.enqueue(
        "steering",
        text="same",
        payload=ReferenceInput("second"),
    )

    consumed = queue.consume(object(), fallback_text="same")

    assert consumed == first
    assert len(queue.snapshot().steering) == 1


def test_host_input_queue_drains_by_mode_and_keeps_queue_ids_monotonic() -> None:
    queue: HostInputQueue[ReferenceInput] = HostInputQueue()
    first = queue.enqueue("steering", text="one", payload=ReferenceInput("one"))
    second = queue.enqueue("steering", text="two", payload=ReferenceInput("two"))

    assert queue.drain("steering", "one-at-a-time") == (first,)
    assert queue.drain("steering", "all") == (second,)
    third = queue.enqueue("follow_up", text="three", payload=ReferenceInput("three"))
    assert third.id == "q3"


def test_host_input_queue_clear_preserves_next_turn_buffer() -> None:
    queue: HostInputQueue[ReferenceInput] = HostInputQueue()
    payload = ReferenceInput("next")
    queued = queue.enqueue("follow_up", text="later", payload=ReferenceInput("later"))
    queue.append_next_turn(payload)

    previous = queue.clear()

    assert previous.follow_up == (queued,)
    assert queue.has_pending() is False
    assert queue.drain_next_turn() == [payload]
    assert queue.drain_next_turn() == []


def test_host_input_queue_rejects_unknown_kind_and_mode() -> None:
    queue: HostInputQueue[ReferenceInput] = HostInputQueue()
    with pytest.raises(ValueError, match="queue kind"):
        queue.texts("priority")  # type: ignore[arg-type]
    queue.enqueue("steering", text="one", payload=ReferenceInput("one"))
    with pytest.raises(ValueError, match="queue mode"):
        queue.drain("steering", "sometimes")  # type: ignore[arg-type]
