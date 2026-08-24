from __future__ import annotations

import asyncio

import pytest

from loushang.harness.runtime import SessionTransitionHost


def test_transition_host_orders_release_activation_and_rebind() -> None:
    events: list[tuple[str, str | None]] = []

    async def dispose(session: str) -> None:
        events.append(("dispose", session))

    async def rebind(session: str) -> None:
        events.append(("rebind", session))

    host = SessionTransitionHost(
        "first",
        dispose=dispose,
        rebind=rebind,
        before_invalidate=lambda: events.append(("invalidate", None)),
    )

    async def scenario() -> None:
        await host.replace(
            "second",
            prepare=lambda session: events.append(("prepare", session)),
            before_release=lambda session: events.append(("release", session)),
            activate=lambda session: events.append(("activate", session)),
        )

    asyncio.run(scenario())

    assert events == [
        ("prepare", "second"),
        ("release", "first"),
        ("invalidate", None),
        ("dispose", "first"),
        ("activate", "second"),
        ("rebind", "second"),
    ]
    assert host.current == "second"


def test_transition_host_before_invalidate_subscription_preserves_primary_callback() -> (
    None
):
    events: list[str] = []
    host = SessionTransitionHost(
        "first",
        dispose=lambda session: events.append(f"dispose:{session}"),
        before_invalidate=lambda: events.append("primary"),
    )
    unsubscribe = host.subscribe_before_invalidate(lambda: events.append("observer"))

    asyncio.run(host.replace("second"))
    unsubscribe()
    asyncio.run(host.replace("third"))

    assert events == [
        "primary",
        "observer",
        "dispose:first",
        "primary",
        "dispose:second",
    ]


def test_transition_host_subscription_unsubscribe_has_token_identity() -> None:
    events: list[str] = []
    host = SessionTransitionHost(
        "first",
        dispose=lambda session: events.append(f"dispose:{session}"),
    )

    def observer() -> None:
        events.append("observer")

    unsubscribe_first = host.subscribe_before_invalidate(observer)
    host.subscribe_before_invalidate(observer)
    unsubscribe_first()
    unsubscribe_first()

    asyncio.run(host.replace("second"))

    assert events == ["observer", "dispose:first"]


def test_transition_host_after_invalidate_observers_are_post_release_and_isolated() -> (
    None
):
    events: list[str] = []
    host = SessionTransitionHost(
        "first", dispose=lambda session: events.append(f"dispose:{session}")
    )
    host.subscribe_after_invalidate(lambda: events.append("after:first"))

    def fail_observer() -> None:
        events.append("after:failed")
        raise RuntimeError("observer failed")

    host.subscribe_after_invalidate(fail_observer)
    host.subscribe_after_invalidate(lambda: events.append("after:last"))

    asyncio.run(
        host.replace(
            "second",
            activate=lambda session: events.append(f"activate:{session}"),
        )
    )

    assert events == [
        "dispose:first",
        "after:first",
        "after:failed",
        "after:last",
        "activate:second",
    ]
    assert host.current == "second"


def test_transition_host_rejects_replacement_reentry_from_after_observer() -> None:
    errors: list[str] = []
    host = SessionTransitionHost("first", dispose=lambda session: None)

    async def reenter() -> None:
        try:
            await host.replace("nested")
        except RuntimeError as error:
            errors.append(str(error))

    host.subscribe_after_invalidate(reenter)

    asyncio.run(host.replace("second"))

    assert host.current == "second"
    assert errors == [
        "Session transition cannot be re-entered from an after-invalidate observer"
    ]


def test_transition_host_preserves_current_when_prepare_fails() -> None:
    async def dispose(session: str) -> None:
        del session

    host = SessionTransitionHost("first", dispose=dispose)

    async def fail_prepare(session: str) -> None:
        del session
        raise RuntimeError("prepare failed")

    with pytest.raises(RuntimeError, match="prepare failed"):
        asyncio.run(host.replace("second", prepare=fail_prepare))

    assert host.current == "first"


def test_transition_host_does_not_publish_session_after_dispose_failure() -> None:
    disposed: list[str] = []

    async def fail_dispose(session: str) -> None:
        disposed.append(session)
        raise RuntimeError("dispose failed")

    host = SessionTransitionHost("first", dispose=fail_dispose)

    with pytest.raises(RuntimeError, match="dispose failed"):
        asyncio.run(host.replace("second"))

    assert disposed == ["first"]
    assert host.current is None


def test_transition_host_retries_retained_disposal_after_failure() -> None:
    attempts = 0

    async def dispose(session: str) -> None:
        nonlocal attempts
        assert session == "first"
        attempts += 1
        if attempts == 1:
            raise RuntimeError("dispose failed transiently")

    host = SessionTransitionHost("first", dispose=dispose)

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="transiently"):
            await host.dispose_current()
        assert host.current is None
        await host.dispose_current()

    asyncio.run(scenario())

    assert attempts == 2
    assert host.current is None


def test_transition_host_serializes_concurrent_replacements() -> None:
    dispose_started = asyncio.Event()
    dispose_release = asyncio.Event()
    disposed: list[str] = []

    async def dispose(session: str) -> None:
        disposed.append(session)
        if session == "first":
            dispose_started.set()
            await dispose_release.wait()

    host = SessionTransitionHost("first", dispose=dispose)

    async def scenario() -> list[str]:
        second_task = asyncio.create_task(host.replace("second"))
        await dispose_started.wait()
        third_task = asyncio.create_task(host.replace("third"))
        await asyncio.sleep(0)
        assert host.current is None
        dispose_release.set()
        return await asyncio.gather(second_task, third_task)

    assert asyncio.run(scenario()) == ["second", "third"]
    assert disposed == ["first", "second"]
    assert host.current == "third"


def test_transition_host_allows_reentrant_transition_callbacks() -> None:
    rebound: list[str] = []

    async def dispose(session: str) -> None:
        del session

    host = SessionTransitionHost("first", dispose=dispose)

    async def rebind(session: str) -> None:
        rebound.append(session)
        async with host.transition():
            assert host.current == session

    host.set_rebind(rebind)

    asyncio.run(host.replace("second"))

    assert rebound == ["second"]


def test_transition_host_disposes_current_idempotently() -> None:
    disposed: list[str] = []
    host = SessionTransitionHost(
        "first", dispose=lambda session: disposed.append(session)
    )

    async def scenario() -> None:
        await host.dispose_current()
        await host.dispose_current()

    asyncio.run(scenario())

    assert disposed == ["first"]
    assert host.current is None
