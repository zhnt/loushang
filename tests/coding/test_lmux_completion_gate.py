import asyncio
import os

import pytest

from ._lmux_completion_gate import CompletionGate, release

INSTANCE = "a" * 32
NONCE = "b" * 32


def test_gate_releases_only_exact_instance_nonce_and_only_once(tmp_path):
    tmp_path.chmod(0o700)
    async def check():
        gate = CompletionGate(tmp_path, INSTANCE)
        waiter = asyncio.create_task(gate(NONCE))
        await asyncio.sleep(0)
        release(tmp_path, "c" * 32, NONCE)
        release(tmp_path, INSTANCE, "d" * 32)
        await asyncio.sleep(0.03)
        assert not waiter.done()
        release(tmp_path, INSTANCE, NONCE)
        await asyncio.wait_for(waiter, 1)
        with pytest.raises(ValueError, match="already consumed"):
            await gate(NONCE)
        with pytest.raises(FileExistsError):
            release(tmp_path, INSTANCE, NONCE)
    asyncio.run(check())


@pytest.mark.parametrize("cancel", [False, True])
def test_unreleased_gate_never_finishes_successfully(tmp_path, cancel):
    tmp_path.chmod(0o700)
    async def check():
        gate = CompletionGate(tmp_path, INSTANCE, timeout=0.03)
        task = asyncio.create_task(gate(NONCE))
        await asyncio.sleep(0)
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
            await task
        assert not list(tmp_path.iterdir())
    asyncio.run(check())


def test_partial_release_does_not_complete_gate(tmp_path):
    tmp_path.chmod(0o700)
    async def check():
        gate = CompletionGate(tmp_path, INSTANCE, timeout=1)
        task = asyncio.create_task(gate(NONCE))
        path = tmp_path / f"release-{INSTANCE}-{NONCE}"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, INSTANCE.encode())
            await asyncio.sleep(0.03)
            assert not task.done()
            os.write(fd, (":" + NONCE).encode())
            await asyncio.wait_for(task, 1)
        finally:
            os.close(fd)
            if not task.done():
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
    asyncio.run(check())
