from __future__ import annotations

import asyncio
import threading

import pytest

from loushang.coding.bootstrap import create_agent_session, create_services
from loushang.coding.resource_runtime import CodingResourceLoader
from loushang.coding.session_manager import SessionManager
from loushang.harness.resources.loader import ResourceLoader


def test_real_session_disposal_releases_only_its_preview_reference(tmp_path, monkeypatch) -> None:
    loader = CodingResourceLoader(user_resource_roots=())
    services = create_services(resource_loader=loader)
    entered, released = threading.Event(), threading.Event()
    original = ResourceLoader._compute_catalog_input_receipt_from_state
    calls = 0

    def compute(*args, **kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        assert released.wait(5)
        return original(*args, **kwargs)

    async def scenario():
        sessions = []
        waiters = []
        try:
            for _ in range(2):
                manager = await SessionManager.new(
                    session_dir=tmp_path, cwd=str(tmp_path), persist=False,
                )
                sessions.append(create_agent_session(session_manager=manager, services=services))
            monkeypatch.setattr(
                ResourceLoader, "_compute_catalog_input_receipt_from_state", staticmethod(compute),
            )
            for session in sessions:
                waiters.append(asyncio.create_task(
                    session.resource_loader.preview_catalog_input_fingerprint(
                        tmp_path, subject_digest="a" * 64, policy_digest="b" * 64,
                        max_work_units=4096, time_budget_seconds=30,
                    ),
                ))
            async with asyncio.timeout(5):
                while not entered.is_set():
                    await asyncio.sleep(0.001)
            await sessions[0].dispose()
            with pytest.raises(asyncio.CancelledError):
                await waiters[0]
            assert not waiters[1].done()
            assert not released.is_set()
            assert calls == 1
            released.set()
            assert len(await waiters[1]) == 64
        finally:
            released.set()
            for waiter in waiters:
                waiter.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)
            for session in reversed(sessions):
                await session.dispose()
            await loader.aclose()

    asyncio.run(scenario())
