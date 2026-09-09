"""Failed debt observations never authorize historical PID or parent killing."""

from __future__ import annotations

import asyncio
import signal
from types import SimpleNamespace

import pytest

from tests.coding import _hosted_debt_cleanup as cleanup


@pytest.mark.parametrize("child_state", ["unpublished", "alive", "already-exited"])
def test_timeout_and_cancellation_retain_same_controller_wait(tmp_path, monkeypatch, child_state):
    if child_state != "unpublished":
        (tmp_path / "child.pid").write_text("123456")
    waits, observations = [], []

    async def scenario():
        ended = asyncio.Event()

        async def wait():
            waits.append("wait")
            await ended.wait()
            return 1

        async def short_wait(waiter):
            observations.append(waiter)
            await asyncio.wait_for(asyncio.shield(waiter), timeout=0.01)

        monkeypatch.setattr(cleanup, "_wait", short_wait)
        process = SimpleNamespace(wait=wait, kill=lambda: pytest.fail("abandoned controller"))
        task = asyncio.create_task(cleanup.release_controller(process, tmp_path / "release"))
        while len(observations) < 2:
            await asyncio.sleep(0.01)
        assert not task.done() and (tmp_path / "release").exists()
        task.cancel()
        await asyncio.sleep(0.02)
        assert not task.done()
        assert len(waits) == 1 and len({id(waiter) for waiter in observations}) == 1
        assert not observations[0].cancelled()
        ended.set()
        await asyncio.wait_for(task, timeout=1)

    previous = signal.getsignal(signal.SIGINT)
    asyncio.run(scenario())
    assert signal.getsignal(signal.SIGINT) == previous


def test_release_publication_failure_retains_controller_and_retries(tmp_path):
    calls = []

    async def scenario():
        ended = asyncio.Event()

        async def wait():
            await ended.wait()

        def touch():
            calls.append("publish")
            if len(calls) == 1:
                raise OSError("release publication unavailable")
            ended.set()

        await cleanup.release_controller(SimpleNamespace(wait=wait), SimpleNamespace(touch=touch))

    asyncio.run(scenario())
    assert calls == ["publish", "publish"]
