"""Original observer invocation boundaries retain cleanup ownership."""
import asyncio

import pytest

from loushang.harness.session.execution_admission import SessionExecutionUnavailable
from loushang.harness.session.execution_scope import ExecutionObservations


def test_observers_join_invocation_finally_and_retain_cleanup_failure():
    async def scenario():
        observations = ExecutionObservations()
        entered, cleanup, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()
        error = OSError("reader cleanup unresolved")

        async def read():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleanup.set()
                await finish.wait()
                raise error

        read_task = asyncio.create_task(observations.invoke(read))
        await entered.wait()
        close_task = asyncio.create_task(observations.quiesce())
        await cleanup.wait()
        assert not close_task.done()
        with pytest.raises(SessionExecutionUnavailable):
            await observations.invoke(read)
        finish.set()
        with pytest.raises(OSError) as raised:
            await close_task
        assert raised.value is error
        await asyncio.gather(read_task, return_exceptions=True)
        with pytest.raises(OSError) as repeated:
            await observations.quiesce()
        assert repeated.value is error

    asyncio.run(scenario())


def test_cancelled_quiesce_waiter_does_not_lose_observer_cleanup_failure():
    async def scenario():
        observations = ExecutionObservations()
        entered, cleanup, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def read():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleanup.set()
                await finish.wait()
                raise OSError("still unresolved")

        read_task = asyncio.create_task(observations.invoke(read))
        await entered.wait()
        close_task = asyncio.create_task(observations.quiesce())
        await cleanup.wait()
        close_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await close_task
        finish.set()
        await asyncio.gather(read_task, return_exceptions=True)
        with pytest.raises(OSError, match="still unresolved"):
            await observations.quiesce()

    asyncio.run(scenario())
