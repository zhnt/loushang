from __future__ import annotations

import asyncio

import pytest

from loushang.harness.session import ApplicationInputRuntime
from loushang.harness.transcript import (
    ApplicationMessage,
    CommitResult,
)


class _Committer:
    def __init__(self) -> None:
        self.persisted: dict[str, ApplicationMessage] = {}

    async def commit(self, message: ApplicationMessage) -> CommitResult:
        existing = self.persisted.get(message.application_message_id)
        if existing is None:
            self.persisted[message.application_message_id] = message
            return CommitResult(
                record_id=f"record-{message.application_message_id}",
                disposition="committed",
                receipt=None,
            )
        if existing != message:
            raise ValueError("application message id was reused with another payload")
        return CommitResult(
            record_id=f"record-{message.application_message_id}",
            disposition="already_committed",
            receipt=None,
        )


class _Queue:
    def __init__(self) -> None:
        self.next_turn: list[ApplicationMessage] = []
        self.steering: list[tuple[str, ApplicationMessage]] = []
        self.follow_up: list[tuple[str, ApplicationMessage]] = []

    def append_next_turn_message(self, message: object) -> None:
        assert isinstance(message, ApplicationMessage)
        self.next_turn.append(message)

    def queue_steering_message(self, visible_text: str, message: object) -> None:
        assert isinstance(message, ApplicationMessage)
        self.steering.append((visible_text, message))

    def queue_follow_up_message(self, visible_text: str, message: object) -> None:
        assert isinstance(message, ApplicationMessage)
        self.follow_up.append((visible_text, message))

    def has_pending_messages(self) -> bool:
        return bool(self.next_turn or self.steering or self.follow_up)


def _message(
    message_id: str,
    *,
    delivery_mode: str = "direct",
    content: str = "notice",
) -> ApplicationMessage:
    return ApplicationMessage(
        application_message_id=message_id,
        custom_type="notice",
        content=content,
        timestamp=0.0,
        delivery_mode=delivery_mode,  # type: ignore[arg-type]
    )


def test_direct_application_input_commits_once_and_projects_once() -> None:
    committer = _Committer()
    queue = _Queue()
    projected: list[tuple[str, str]] = []

    async def project(message: ApplicationMessage, record_id: str) -> None:
        projected.append((message.application_message_id, record_id))

    runtime = ApplicationInputRuntime(
        commit_application_message=committer.commit,
        queue=queue,
        project_direct=project,
        run_trigger_turn=lambda message: _record_trigger([], message),
    )
    message = _message("direct-1")

    first = asyncio.run(runtime.deliver(message))
    second = asyncio.run(runtime.deliver(message))

    assert first.disposition == "committed"
    assert second.disposition == "already_committed"
    assert first.record_id == second.record_id == "record-direct-1"
    assert list(committer.persisted) == ["direct-1"]
    assert projected == [("direct-1", "record-direct-1")]


def test_direct_projection_retry_reuses_the_committed_application_message() -> None:
    committer = _Committer()
    attempts = 0

    async def project(_message: ApplicationMessage, _record_id: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("projection unavailable")

    runtime = ApplicationInputRuntime(
        commit_application_message=committer.commit,
        queue=_Queue(),
        project_direct=project,
        run_trigger_turn=lambda message: _record_trigger([], message),
    )
    message = _message("direct-retry")

    with pytest.raises(RuntimeError, match="projection unavailable"):
        asyncio.run(runtime.deliver(message))
    retry = asyncio.run(runtime.deliver(message))

    assert retry.disposition == "already_committed"
    assert list(committer.persisted) == ["direct-retry"]
    assert attempts == 2


def test_delayed_application_inputs_route_without_direct_commit() -> None:
    committer = _Committer()
    queue = _Queue()
    triggered: list[str] = []
    runtime = ApplicationInputRuntime(
        commit_application_message=committer.commit,
        queue=queue,
        project_direct=lambda message, record_id: _record_projection(
            [], message, record_id
        ),
        run_trigger_turn=lambda message: _record_trigger(triggered, message),
    )

    next_turn = asyncio.run(
        runtime.deliver(_message("next", delivery_mode="next_turn"))
    )
    steering = asyncio.run(runtime.deliver(_message("steer", delivery_mode="steering")))
    follow_up = asyncio.run(
        runtime.deliver(_message("follow", delivery_mode="follow_up"))
    )
    trigger = asyncio.run(
        runtime.deliver(_message("trigger", delivery_mode="trigger_turn"))
    )

    assert [delivery.disposition for delivery in (next_turn, steering, follow_up)] == [
        "queued",
        "queued",
        "queued",
    ]
    assert trigger.disposition == "triggered"
    assert [message.application_message_id for message in queue.next_turn] == ["next"]
    assert [
        (text, message.application_message_id) for text, message in queue.steering
    ] == [("notice", "steer")]
    assert [
        (text, message.application_message_id) for text, message in queue.follow_up
    ] == [("notice", "follow")]
    assert triggered == ["trigger"]
    assert committer.persisted == {}
    assert runtime.has_pending_messages() is True


async def _record_trigger(target: list[str], message: ApplicationMessage) -> None:
    target.append(message.application_message_id)


async def _record_projection(
    target: list[tuple[str, str]],
    message: ApplicationMessage,
    record_id: str,
) -> None:
    target.append((message.application_message_id, record_id))
