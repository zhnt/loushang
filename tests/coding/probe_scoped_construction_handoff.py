"""Explicit local whole construction suffix evidence, no live/model call."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import loushang.coding.bootstrap as product
import loushang.harness.session.bootstrap_construction as core
from loushang.coding.session.agent_session import AgentSession
from loushang.coding.session_manager import SessionManager
from tests.coding import probe_session_construction_handoff as handoff
from tests.coding.probe_session_construction_handoff import (
    _finish,
    _lease,
    _setup,
)
from tests.coding.test_bootstrap import _model

tmp_path = handoff.tmp_path


def _inject(monkeypatch, failure, phase, sessions):
    construct = core.AgentSessionConstructionRuntime.construct

    def observed(self, *args, **kwargs):
        session = construct(self, *args, **kwargs)
        sessions.append(session)
        return session

    def scoped(*args, **kwargs):
        if phase == "resolution":
            raise failure
        return [object()]

    def setter(self, models):
        if phase == "setter":
            raise failure

    def result(**kwargs):
        raise failure

    monkeypatch.setattr(core.AgentSessionConstructionRuntime, "construct", observed)
    monkeypatch.setattr(core, "scoped_models_from_patterns", scoped)
    monkeypatch.setattr(AgentSession, "set_scoped_models", setter)
    if phase == "result":
        monkeypatch.setattr(core, "AgentProductConstructionResult", result)


@pytest.mark.parametrize("phase", ["resolution", "setter", "result", "cancelled"])
@pytest.mark.parametrize("mode", ["sync", "loop"])
def test_direct_suffix_failure_keeps_native_lease_until_session_close(
    tmp_path,
    monkeypatch,
    phase,
    mode,
):
    cwd, services = _setup(tmp_path, monkeypatch)
    sessions = []
    failure = (
        asyncio.CancelledError("controlled cancellation")
        if phase == "cancelled"
        else ValueError("controlled construction suffix failure")
    )
    _inject(monkeypatch, failure, "setter" if phase == "cancelled" else phase, sessions)

    async def new():
        return await SessionManager.new_with_composition(
            session_dir=tmp_path / "data" / "sessions",
            cwd=str(cwd),
            persist=True,
        )

    def build(manager):
        with pytest.raises(type(failure)) as caught:
            product.create_agent_session(
                session_manager=manager, model=_model(), services=services
            )
        assert caught.value is failure and len(sessions) == 1
        cleanup = product.get_session_construction_cleanup(failure)
        assert cleanup is not None and cleanup.owns_session(sessions[0])
        assert not cleanup.owns_session(None) and not cleanup.owns_session(object())
        assert not _lease(sessions[0])._released
        return cleanup

    async def settle(cleanup):
        await cleanup.retry_cleanup()
        assert _lease(sessions[0])._released
        assert not cleanup.owns_session(sessions[0])
        await cleanup.retry_cleanup()

    async def scenario():
        try:
            await settle(build(await new()))
        finally:
            await _finish(sessions)

    if mode == "loop":
        asyncio.run(scenario())
    else:
        manager = asyncio.run(new())
        try:
            asyncio.run(settle(build(manager)))
        finally:
            asyncio.run(_finish(sessions))


@pytest.mark.parametrize("close_fails", [False, True])
def test_original_root_settles_or_retains_suffix_cleanup(
    tmp_path, monkeypatch, close_fails
):
    cwd, services = _setup(tmp_path, monkeypatch)
    sessions = []
    failure = ValueError("controlled scoped failure")
    _inject(monkeypatch, failure, "setter", sessions)
    original_dispose = AgentSession.dispose
    failing = close_fails

    async def dispose(self, *args, **kwargs):
        if self in sessions and failing:
            raise OSError("controlled cleanup failure")
        return await original_dispose(self, *args, **kwargs)

    monkeypatch.setattr(AgentSession, "dispose", dispose)

    async def scenario():
        nonlocal failing
        runtime = product.create_agent_session_runtime(
            session_dir=tmp_path / "data" / "sessions",
            model=_model(),
            services=services,
            persist=True,
        )
        try:
            with pytest.raises(ValueError) as caught:
                await runtime.create_session(cwd=str(cwd))
            assert caught.value is failure and len(sessions) == 1
            assert _lease(sessions[0])._released is (not close_fails)
            pending = runtime._transcript_construction_store.pending_transcripts
            assert bool(pending) is close_fails
            assert runtime.get_current_session() is None
            failing = False
            await runtime.dispose_session_runtime()
            assert _lease(sessions[0])._released
            assert not runtime._transcript_construction_store.pending_transcripts
        finally:
            failing = False
            await runtime.dispose_session_runtime()
            await _finish(sessions)

    asyncio.run(scenario())


def test_foreign_error_custody_does_not_skip_new_root_cleanup(tmp_path, monkeypatch):
    cwd, services = _setup(tmp_path, monkeypatch)
    sessions, runtimes = [], []
    failure = ValueError("same error reused before second Session")
    _inject(monkeypatch, failure, "setter", sessions)
    activate = core.activate_package_product_runtime

    def captured(*args, **kwargs):
        runtime = activate(*args, **kwargs)
        runtimes.append(runtime)
        return runtime

    monkeypatch.setattr(core, "activate_package_product_runtime", captured)

    async def scenario():
        cleanup = None
        try:
            for index in range(2):
                manager = await SessionManager.new_with_composition(
                    session_dir=tmp_path / "data" / ("sessions" + str(index)),
                    cwd=str(cwd),
                    persist=True,
                )
                if index:

                    def early(*args, **kwargs):
                        raise failure

                    monkeypatch.setattr(core, "resolve_session_model", early)
                with pytest.raises(ValueError) as caught:
                    product.create_agent_session(
                        session_manager=manager, model=_model(), services=services
                    )
                assert caught.value is failure
                current = product.get_session_construction_cleanup(failure)
                if not index:
                    cleanup = current
                    assert cleanup is not None and cleanup.owns_session(sessions[0])
                else:
                    assert current is cleanup and len(sessions) == 1
                    assert len(runtimes) == 2
                    proxy = SimpleNamespace(
                        _package_product_runtime_binding=runtimes[1]
                    )
                    assert _lease(proxy)._released
                    assert not _lease(sessions[0])._released
            await cleanup.retry_cleanup()
        finally:
            await _finish(sessions)

    asyncio.run(scenario())


@pytest.mark.parametrize("cancelled", [False, True, "custom_base"])
def test_generic_session_preserves_original_cleanup_policy(monkeypatch, cancelled):
    calls = []

    class CustomBaseFailure(BaseException):
        @property
        def __class__(self):
            raise AssertionError("BaseException matching must not inspect attributes")

    failure = (
        asyncio.CancelledError("generic cancellation")
        if cancelled
        else ValueError("generic failure")
    )
    if cancelled == "custom_base":
        failure = CustomBaseFailure("generic BaseException")
    settings = SimpleNamespace(
        system_prompt=None,
        default_model=None,
        steering_mode=None,
        follow_up_mode=None,
        thinking_budgets=None,
        retry=SimpleNamespace(provider_max_retry_delay_ms=None),
        enabled_models=(),
    )
    configuration = SimpleNamespace(
        settings=settings,
        session_id="generic",
        resource_loader=None,
        model_registry=SimpleNamespace(
            build_model=None,
            get_model=None,
            ai_registry=SimpleNamespace(get_endpoint=None),
        ),
        diagnostics_service=None,
        package_product_lifecycle=None,
        package_product_inventory=None,
        package_product_lifecycle_mode="legacy",
    )
    ports = SimpleNamespace(
        activate_resources=lambda bundle: None,
        prompt_section_composer=None,
        tool_pack_composer=None,
        list_tool_definitions=None,
        get_tool_source_info=None,
        dispose_capabilities=lambda: calls.append("dispose"),
    )

    class GenericSession:
        @property
        def __class__(self):
            raise AssertionError("generic Session attributes must not be inspected")

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(
        core.StandardAgentSessionConfigurationRuntime,
        "configure",
        lambda *args: SimpleNamespace(resource_bundle=None, extension_runtime=None),
    )
    monkeypatch.setattr(core, "resolve_base_system_prompt", lambda **kwargs: "base")
    monkeypatch.setattr(
        core,
        "assemble_prompt",
        lambda **kwargs: SimpleNamespace(system_prompt="prompt"),
    )
    monkeypatch.setattr(core, "resolve_session_model", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        core.AgentSessionConstructionRuntime,
        "construct",
        lambda *args, **kwargs: GenericSession(),
    )
    monkeypatch.setattr(core, "scoped_models_from_patterns", fail)
    request = SimpleNamespace(
        configuration=configuration,
        ports=ports,
        explicit_system_prompt=None,
        default_system_prompt="default",
        append_system_prompt=(),
        model=None,
        on_default_model_unavailable=None,
        thinking_level=None,
        convert_to_llm=None,
        stream_fn=None,
        tools=None,
        tool_registry=None,
        allowed_tool_names=None,
        active_tool_names=None,
        no_tools=None,
        agent_factory=None,
        session_factory=None,
        product_tool_pack_id="product",
        extension_tool_pack_id="extensions",
    )
    with pytest.raises(type(failure)) as caught:
        core.AgentProductConstructionRuntime().construct(request)
    assert caught.value is failure
    assert calls == ([] if cancelled else ["dispose"])
    assert product.get_session_construction_cleanup(failure) is None


def test_same_error_reused_for_completed_sessions_keeps_independent_custody(
    tmp_path, monkeypatch
):
    from loushang.harness.session._cleanup import (
        SessionConstructionCleanupAttachmentError,
    )

    cwd, services = _setup(tmp_path, monkeypatch)
    sessions, cleanups = [], []
    failure = ValueError("same error from two completed Sessions")
    _inject(monkeypatch, failure, "setter", sessions)

    async def scenario():
        try:
            for index in range(2):
                manager = await SessionManager.new_with_composition(
                    session_dir=tmp_path / "data" / ("sessions" + str(index)),
                    cwd=str(cwd),
                    persist=True,
                )
                with pytest.raises(
                    (ValueError, SessionConstructionCleanupAttachmentError)
                ) as caught:
                    product.create_agent_session(
                        session_manager=manager, model=_model(), services=services
                    )
                if not index:
                    assert caught.value is failure
                else:
                    assert (
                        type(caught.value) is SessionConstructionCleanupAttachmentError
                    )
                    assert caught.value.original_error is failure
                cleanup = product.get_session_construction_cleanup(caught.value)
                assert cleanup is not None and cleanup.owns_session(sessions[index])
                cleanups.append(cleanup)
            assert cleanups[0] is not cleanups[1]
            assert all(not _lease(session)._released for session in sessions)
            await cleanups[1].retry_cleanup()
            assert _lease(sessions[1])._released and not _lease(sessions[0])._released
            assert product.get_session_construction_cleanup(failure) is cleanups[0]
            await cleanups[0].retry_cleanup()
            assert _lease(sessions[0])._released
        finally:
            await _finish(sessions)

    asyncio.run(scenario())
