"""Explicit local real Session handoff observations; no live/model execution."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

import loushang.coding.bootstrap as product
from loushang.coding.control import ControlConfig, SettingsManager
from loushang.coding.session.agent_session import AgentSession
from loushang.coding.session_manager import SessionManager
from tests.coding.test_bootstrap import _model

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux Product lease observation"
)


@pytest.fixture
def tmp_path():
    with TemporaryDirectory(prefix="loushang-construction-handoff-") as raw:
        case = Path(raw) / "case"
        case.mkdir(mode=0o700)
        yield case


def _lease(session):
    owner = session._package_product_runtime_binding.on_dispose.__self__
    if hasattr(owner, "release"):
        owner = owner.release.__self__
    return owner._handle


def _setup(tmp_path, monkeypatch):
    expected = Path(
        os.environ.get(
            "LOUSHANG_CONSTRUCTION_TEST_SOURCE_ROOT",
            str(Path(__file__).resolve().parents[2] / "src"),
        )
    ).resolve()
    assert Path(product.__file__).resolve().is_relative_to(expected)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    (tmp_path / "data").mkdir(mode=0o700)
    cwd = tmp_path / "project"
    cwd.mkdir()
    (cwd / "AGENTS.md").write_text("Local test workspace.\n")
    services = product.create_services(
        settings_manager=SettingsManager(
            ControlConfig(capabilities={"coding.lsp": "disabled"}),
        )
    )
    return cwd, services


async def _finish(sessions):
    for session in sessions:
        runtime = getattr(session, "multiagent_runtime", None)
        if runtime is not None:
            await runtime.dispose()
        await session.dispose()


@pytest.mark.parametrize("mode", ["sync", "running_loop"])
@pytest.mark.parametrize("phase", ["registration", "snapshot"])
def test_direct_failed_handoff_retains_same_actual_owner(
    tmp_path, monkeypatch, mode, phase
):
    cwd, services = _setup(tmp_path, monkeypatch)
    sessions = []
    failure = ValueError("controlled failed Session handoff")
    register = AgentSession.register_runtime_tools

    def injected(self, tools, **kwargs):
        if (
            phase == "registration"
            and (kwargs.get("source_info") or {}).get("pack") == "harness.multiagent"
        ):
            sessions.append(self)
            raise failure
        return register(self, tools, **kwargs)

    def fail_snapshot(session, **kwargs):
        sessions.append(session)
        raise failure

    monkeypatch.setattr(AgentSession, "register_runtime_tools", injected)
    if phase == "snapshot":
        monkeypatch.setattr(
            product, "build_standard_agent_session_result", fail_snapshot
        )

    def build(manager):
        create = (
            product.create_agent_session_result
            if phase == "snapshot"
            else product.create_agent_session
        )
        with pytest.raises(ValueError) as caught:
            create(
                session_manager=manager,
                model=_model(),
                services=services,
                enable_multiagent=True,
            )
        assert caught.value is failure and len(sessions) == 1
        cleanup = product.get_session_construction_cleanup(caught.value)
        assert cleanup is not None and not _lease(sessions[0])._released
        return cleanup

    async def new():
        return await SessionManager.new_with_composition(
            session_dir=tmp_path / "data" / "sessions",
            cwd=str(cwd),
            persist=True,
        )

    async def settle(cleanup):
        await cleanup.retry_cleanup()
        await cleanup.retry_cleanup()
        assert _lease(sessions[0])._released and sessions[0].multiagent_runtime._closed

    async def scenario():
        try:
            await settle(build(await new()))
        finally:
            await _finish(sessions)

    if mode == "running_loop":
        asyncio.run(scenario())
    else:
        manager = asyncio.run(new())
        try:
            cleanup = build(manager)
            asyncio.run(settle(cleanup))
        finally:
            asyncio.run(_finish(sessions))


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_actual_root_settles_or_retains_failed_handoff(
    tmp_path, monkeypatch, cleanup_fails
):
    cwd, services = _setup(tmp_path, monkeypatch)
    sessions, leases = [], []
    broken, failed_close = True, cleanup_fails
    failure = ValueError("controlled postconstruction failure")
    register, dispose = AgentSession.register_runtime_tools, AgentSession.dispose

    def injected(self, tools, **kwargs):
        if (
            broken
            and (kwargs.get("source_info") or {}).get("pack") == "harness.multiagent"
        ):
            sessions.append(self)
            leases.append(_lease(self))
            raise failure
        return register(self, tools, **kwargs)

    async def close(self, *args, **kwargs):
        if self in sessions and failed_close:
            raise OSError("controlled Session close failure")
        return await dispose(self, *args, **kwargs)

    monkeypatch.setattr(AgentSession, "register_runtime_tools", injected)
    monkeypatch.setattr(AgentSession, "dispose", close)

    async def scenario():
        nonlocal failed_close, broken
        runtime = product.create_agent_session_runtime(
            session_dir=tmp_path / "data" / "sessions",
            model=_model(),
            services=services,
            enable_multiagent=True,
            persist=True,
        )
        try:
            with pytest.raises(ValueError) as caught:
                await runtime.create_session(cwd=str(cwd))
            assert caught.value is failure and runtime.get_current_session() is None
            assert len(sessions) == 1
            assert leases[0]._released is (not cleanup_fails)
            assert (
                bool(runtime._transcript_construction_store.pending_transcripts)
                is cleanup_fails
            )
            failed_close = False
            broken = False
            if cleanup_fails:
                await runtime.dispose_session_runtime()
                assert (
                    leases[0]._released
                    and not runtime._transcript_construction_store.pending_transcripts
                )
            else:
                recovered = await runtime.create_session(cwd=str(cwd))
                assert runtime.get_current_session() is recovered
        finally:
            failed_close = False
            broken = False
            await runtime.dispose_session_runtime()
            await _finish(sessions)
        assert all(lease._released for lease in leases)

    asyncio.run(scenario())
