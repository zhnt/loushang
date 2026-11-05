from __future__ import annotations

import asyncio

import pytest

from loushang.harness.runtime import await_owned_task


def test_owned_task_returns_its_result_including_after_settlement() -> None:
    async def scenario() -> None:
        result = object()

        async def operation() -> object:
            return result

        task = asyncio.create_task(operation())
        assert await await_owned_task(task) is result
        assert await await_owned_task(task) is result

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
def test_owned_task_settles_despite_repeated_caller_cancellation(outcome: str) -> None:
    async def scenario() -> None:
        release = asyncio.Event()
        joining = asyncio.Event()
        result = object()
        failure = RuntimeError("owned operation failed")

        async def operation() -> object:
            await release.wait()
            if outcome == "failure":
                raise failure
            if outcome == "cancelled":
                raise asyncio.CancelledError("owned operation cancelled")
            return result

        task = asyncio.create_task(operation())

        async def join() -> object:
            joining.set()
            return await await_owned_task(task)

        async def checkpoint() -> None:
            turn = asyncio.Event()
            asyncio.get_running_loop().call_soon(turn.set)
            await turn.wait()

        caller = asyncio.create_task(join())
        try:
            await joining.wait()
            for reason in ("first cancellation", "second cancellation"):
                caller.cancel(reason)
                await checkpoint()
                assert not caller.done()
                assert not task.done()

            release.set()
            if outcome == "failure":
                with pytest.raises(RuntimeError) as caught:
                    await caller
                assert caught.value is failure
            elif outcome == "cancelled":
                with pytest.raises(asyncio.CancelledError):
                    await caller
                assert task.cancelled()
            else:
                with pytest.raises(asyncio.CancelledError, match="second cancellation"):
                    await caller
                assert task.result() is result
            assert task.done()
        finally:
            release.set()
            await asyncio.gather(task, caller, return_exceptions=True)

    asyncio.run(scenario())
