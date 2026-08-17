from __future__ import annotations

import asyncio

import pytest

from loushang.harness.continuity import (
    ActivationLeaseStateError,
    CallbackPreparedActivationLease,
    ContinuityTarget,
    consume_prepared_activation,
)


def test_same_domain_in_place_lease_is_single_use_and_aborts_once() -> None:
    asyncio.run(_prepared_activation_lease_is_single_use_and_aborts_once())


async def _prepared_activation_lease_is_single_use_and_aborts_once() -> None:
    events: list[str] = []
    target = ContinuityTarget(provider_id="coding.sessions", opaque_id="session-1")
    lease = CallbackPreparedActivationLease(
        target=target,
        disposition="in_place",
        consume=lambda: events.append("consume") or "candidate",
        abort=lambda: events.append("abort"),
    )

    assert await lease.consume() == "candidate"
    assert lease.consumed is True
    await lease.close()
    await lease.abort()
    assert events == ["consume"]
    with pytest.raises(ActivationLeaseStateError):
        await lease.consume()


def test_cross_domain_relaunch_lease_cleanup_is_idempotent() -> None:
    asyncio.run(_unconsumed_activation_lease_cleanup_is_idempotent())


async def _unconsumed_activation_lease_cleanup_is_idempotent() -> None:
    events: list[str] = []
    lease = CallbackPreparedActivationLease(
        target=ContinuityTarget(provider_id="design.canvases", opaque_id="canvas-1"),
        disposition="relaunch",
        consume=lambda: object(),
        abort=lambda: events.append("abort"),
    )

    await lease.abort()
    await lease.close()

    assert events == ["abort"]


def test_prepared_activation_transaction_aborts_a_failed_lease() -> None:
    async def scenario() -> None:
        events: list[str] = []

        class _FailingLease:
            target = ContinuityTarget(
                provider_id="design.canvases",
                opaque_id="canvas-1",
            )
            disposition = "relaunch"
            consumed = False

            async def consume(self) -> object:
                events.append("consume")
                raise RuntimeError("activation failed")

            async def abort(self) -> None:
                events.append("abort")

            async def close(self) -> None:
                events.append("close")

        with pytest.raises(RuntimeError, match="activation failed"):
            await consume_prepared_activation(_FailingLease())

        assert events == ["consume", "abort"]

    asyncio.run(scenario())
