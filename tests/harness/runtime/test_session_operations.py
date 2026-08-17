from __future__ import annotations

import asyncio

import pytest

from loushang.harness.runtime.session_operations import (
    CancelledSessionOperation,
    SessionOperationCandidate,
    SessionOperationCoordinator,
    SessionOperationPhase,
)
from loushang.harness.runtime.transition import SessionTransitionHost


def test_session_operation_orders_prepare_replace_and_commit() -> None:
    events: list[str] = []
    host = SessionTransitionHost(
        "first",
        dispose=lambda session: events.append(f"dispose:{session}"),
    )
    coordinator = SessionOperationCoordinator(host)

    async def scenario() -> object:
        return await coordinator.run(
            lambda current: (
                events.append(f"prepare:{current}"),
                SessionOperationCandidate("second", "payload"),
            )[1],
            prepare_session=lambda candidate, _previous: events.append(
                f"bind:{candidate.session}:{candidate.payload}"
            ),
            before_release=lambda previous, candidate: events.append(
                f"release:{previous}:{candidate.session}"
            ),
            activate=lambda candidate, _previous: events.append(
                f"activate:{candidate.session}"
            ),
            after_commit=lambda result: events.append(
                f"commit:{result.previous}:{result.current}:{result.payload}"
            ),
        )

    result = asyncio.run(scenario())

    assert result.cancelled is False
    assert result.changed is True
    assert events == [
        "prepare:first",
        "bind:second:payload",
        "release:first:second",
        "dispose:first",
        "activate:second",
        "commit:first:second:payload",
    ]


def test_session_operation_cancellation_keeps_current_and_cleans_up() -> None:
    events: list[str] = []
    host = SessionTransitionHost(
        "first", dispose=lambda session: events.append(session)
    )
    coordinator = SessionOperationCoordinator(host)

    result = asyncio.run(
        coordinator.run(
            lambda _current: CancelledSessionOperation(
                "not-selected",
                cleanup=lambda: events.append("cleanup"),
            )
        )
    )

    assert result.cancelled is True
    assert result.changed is False
    assert result.current == "first"
    assert result.payload == "not-selected"
    assert events == ["cleanup"]


def test_session_operation_rolls_back_uncommitted_candidate_and_reports_phase() -> None:
    events: list[str] = []
    host = SessionTransitionHost(
        "first", dispose=lambda session: events.append(f"dispose:{session}")
    )
    coordinator = SessionOperationCoordinator(host)

    def fail_bind(candidate: object, previous: object) -> None:
        del candidate, previous
        raise RuntimeError("bind failed")

    with pytest.raises(RuntimeError, match="bind failed"):
        asyncio.run(
            coordinator.run(
                lambda _current: SessionOperationCandidate(
                    "second",
                    None,
                    rollback=lambda: events.append("rollback"),
                ),
                prepare_session=fail_bind,
                on_failure=lambda failure: events.append(f"failure:{failure.phase}"),
            )
        )

    assert host.current == "first"
    assert events == [
        "rollback",
        f"failure:{SessionOperationPhase.REPLACE}",
    ]


def test_session_operation_reports_after_commit_without_rolling_back() -> None:
    events: list[str] = []
    host = SessionTransitionHost(
        "first", dispose=lambda session: events.append(f"dispose:{session}")
    )
    coordinator = SessionOperationCoordinator(host)

    def fail_callback(_result: object) -> None:
        raise RuntimeError("callback failed")

    with pytest.raises(RuntimeError, match="callback failed"):
        asyncio.run(
            coordinator.run(
                lambda _current: SessionOperationCandidate(
                    "second",
                    None,
                    rollback=lambda: events.append("rollback"),
                ),
                after_commit=fail_callback,
                on_failure=lambda failure: events.append(f"failure:{failure.phase}"),
            )
        )

    assert host.current == "second"
    assert events == [
        "dispose:first",
        f"failure:{SessionOperationPhase.AFTER_COMMIT}",
    ]


def test_session_operation_invalidation_failure_has_no_false_current() -> None:
    events: list[str] = []

    def fail_dispose(session: str) -> None:
        events.append(f"dispose:{session}")
        raise RuntimeError("dispose failed")

    host = SessionTransitionHost("first", dispose=fail_dispose)
    coordinator = SessionOperationCoordinator(host)

    with pytest.raises(RuntimeError, match="dispose failed"):
        asyncio.run(
            coordinator.run(
                lambda _current: SessionOperationCandidate(
                    "second",
                    None,
                    rollback=lambda: events.append("rollback"),
                ),
                on_failure=lambda failure: events.append(
                    f"failure:{failure.phase}:{failure.current}"
                ),
            )
        )

    assert host.current is None
    assert events == [
        "dispose:first",
        "rollback",
        f"failure:{SessionOperationPhase.REPLACE}:None",
    ]


def test_session_operation_rebind_failure_reports_published_candidate() -> None:
    events: list[str] = []

    def fail_rebind(session: str) -> None:
        events.append(f"rebind:{session}")
        raise RuntimeError("rebind failed")

    host = SessionTransitionHost(
        "first",
        dispose=lambda session: events.append(f"dispose:{session}"),
        rebind=fail_rebind,
    )
    coordinator = SessionOperationCoordinator(host)

    with pytest.raises(RuntimeError, match="rebind failed"):
        asyncio.run(
            coordinator.run(
                lambda _current: SessionOperationCandidate(
                    "second",
                    None,
                    rollback=lambda: events.append("rollback"),
                ),
                on_failure=lambda failure: events.append(
                    f"failure:{failure.phase}:{failure.current}"
                ),
            )
        )

    assert host.current == "second"
    assert events == [
        "dispose:first",
        "rebind:second",
        f"failure:{SessionOperationPhase.AFTER_COMMIT}:second",
    ]


def test_session_operation_cancellation_rolls_back_staged_candidate(tmp_path) -> None:
    staged_file = tmp_path / "staged.jsonl"
    staged_file.write_text("candidate", encoding="utf-8")
    prepare_started = asyncio.Event()
    host = SessionTransitionHost("first", dispose=lambda _session: None)
    coordinator = SessionOperationCoordinator(host)

    async def prepare_session(_candidate: object, _previous: object) -> None:
        prepare_started.set()
        await asyncio.Future()

    async def scenario() -> None:
        task = asyncio.create_task(
            coordinator.run(
                lambda _current: SessionOperationCandidate(
                    "second",
                    None,
                    rollback=staged_file.unlink,
                ),
                prepare_session=prepare_session,
            )
        )
        await prepare_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert host.current == "first"
    assert staged_file.exists() is False
