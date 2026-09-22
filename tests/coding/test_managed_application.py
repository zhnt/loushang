from __future__ import annotations

import asyncio
import sys
from dataclasses import replace

import pytest

from loushang.agent import synthetic_model_transport
from loushang.appserver.protocol import (
    AppServiceError,
    MuxCreateV1,
    MuxSelectorV1,
    SessionOpenSpecV1,
)
from loushang.appservice.execution_service import HostedExecutionServiceBindingV1
from loushang.appservice.managed_mux import ManagedMuxServiceBindingV1
from loushang.coding.hosted_application import (
    CODING_HOSTED_APPLICATION_PROFILE_ID,
    CodingAppHostHostedSessionResolverV1,
)
from loushang.coding.hosted_session import CodingRealHostedSessionFactoryV1
from loushang.coding.managed_bootstrap import (
    CodingManagedApplicationLaunchV1,
    create_coding_managed_attempt,
)
from loushang.harness.transcript.writer_lease import TranscriptWriterError
from loushang.harnesstui.mux import open_hosted_mux_profile

from ._hosted_product_child import scripted_stream
from .test_hosted_catalog import _intent
from .test_hosted_local import _model
from .test_managed_catalog import catalog, ordinary, tree

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed application")


def launch(root):
    return CodingManagedApplicationLaunchV1(root, root / "application", "coding.managed", root / "sessions")


def attempt(root):
    return create_coding_managed_attempt(
        launch(root), model=_model(), stream_fn=scripted_stream, tools=[], session_discovery=True,
    )


def test_noncontinuity_managed_request_rejects_before_admission_or_catalog_cleanup(tmp_path, monkeypatch):
    from loushang.coding import hosted_application as module

    async def scenario():
        owner = attempt(tmp_path)
        request = replace(owner._request.foreground, managed_mux=ManagedMuxServiceBindingV1(
            "coding.managed", "a" * 64, "b" * 32, lambda _: pytest.fail("unexpected permission acquisition"),
        ))
        effects = []

        def forbidden(*args, **kwargs):
            effects.append(1)
            raise AssertionError("invalid entry acquired or fenced dependencies")

        with monkeypatch.context() as selected:
            selected.setattr(module, "CodingForegroundProductFactoryV1", forbidden)
            selected.setattr(module.AppHostCatalogV1, "admit", forbidden)
            selected.setattr(type(request.sessions), "fence", forbidden)
            selected.setattr(type(request.sessions), "close", forbidden)
            with pytest.raises(ValueError, match="continuity"):
                await module.create_coding_foreground_hosted_application(request)
            assert not effects
        await owner.close()

    asyncio.run(scenario())


def test_managed_continuity_application_identity_rejects_before_store_acquisition(tmp_path):
    async def scenario():
        owner = attempt(tmp_path)
        try:
            foreground = replace(owner._request.foreground, managed_mux=ManagedMuxServiceBindingV1(
                "coding.other", "a" * 64, "b" * 32, lambda _: pytest.fail("unexpected admission"),
            ))
            before = tree(tmp_path)
            with pytest.raises(ValueError, match="identity mismatch"):
                replace(owner._request, foreground=foreground)
            assert tree(tmp_path) == before
        finally:
            await owner.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("history", ["ordinary", "v1_cwd", "v1_home"])
def test_managed_real_product_scope_projection_reconnect_and_continuity(tmp_path, monkeypatch, history):
    async def scenario():
        monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
        monkeypatch.setenv("LOUSHANG_RUNTIME_DIR", str(tmp_path / "runtime"))
        source = catalog(tmp_path)
        if history == "ordinary":
            path = await ordinary(source, image=True)
            selected = source.scopes[0]
        else:
            original_scope = source.scopes[0 if history == "v1_cwd" else 1]
            created = await source.create_candidate(_intent(original_scope))
            path = created._binding.record.path
            await created.close()
            selected = source.scopes[1 if history == "v1_cwd" else 0]
        rows = await source.list_identities((selected.discovery_scope,), limit=256)
        envelope = rows[0].envelope
        original = path.read_bytes()
        await source.close()
        entered, release = asyncio.Event(), asyncio.Event()

        @synthetic_model_transport
        async def gated_stream(*args, **kwargs):
            entered.set()
            await release.wait()
            return await scripted_stream(*args, **kwargs)

        create = CodingRealHostedSessionFactoryV1.create_session
        products = []

        async def observe(self, **kwargs):
            result = await create(self, **kwargs)
            products.append(result)
            return result

        # Production freezes static native methods during attempt construction.
        monkeypatch.setattr(CodingRealHostedSessionFactoryV1, "create_session", observe)
        owner = create_coding_managed_attempt(
            launch(tmp_path), model=_model(), stream_fn=gated_stream, tools=[], session_discovery=True,
        )
        runtime = await owner.open()
        controller = None
        submitting = None
        spec = SessionOpenSpecV1(
            "coding", envelope.continuity_id, selected.scope, selected.fingerprint,
            session_id=envelope.session_id, title="shared history",
        )
        try:
            await runtime.client.create_mux(MuxCreateV1("dev"))
            controller = await open_hosted_mux_profile(runtime.client, selector=MuxSelectorV1(name="dev"))
            state = await controller.open_member(spec)
            assert len(state.windows) == 1 and state.windows[0].session_id == envelope.session_id
            assert len(products) == 1
            assert products[0].identity.scope is not selected.scope
            assert products[0].identity.continuity_id == envelope.continuity_id
            assert path.read_bytes() == original
            # Reattaching an existing Mux does not invoke a second factory.
            await controller.close()
            controller = await open_hosted_mux_profile(runtime.client, selector=MuxSelectorV1(name="dev"))
            assert len(controller.state.windows) == 1 and len(products) == 1
            submitting = asyncio.create_task(controller.submit("accepted before duplicate"))
            await asyncio.wait_for(entered.wait(), 10)
            other_scope = owner._request.foreground.sessions.scopes[1 if selected.scope.value == "cwd" else 0]
            with pytest.raises(AppServiceError):
                await controller.open_member(replace(spec, scope=other_scope.scope, scope_fingerprint=other_scope.fingerprint))
            assert len(controller.state.windows) == 1 and len(products) == 1
            contender = catalog(tmp_path)
            current = await contender.list_identities((selected.discovery_scope,), limit=256)
            with pytest.raises(TranscriptWriterError, match="busy"):
                await contender.open_candidate(current[0].reference)
            await contender.close()
            release.set()
            await asyncio.wait_for(submitting, 10)
            await asyncio.wait_for(products[0].control.wait_for_idle(), 10)
            assert sum(message.role == "assistant" for message in products[0].control.messages) == 1
            assert products[0].control.messages[-1].content[0].text == "真实跨进程回复\nG14"
            await controller.submit("hello after duplicate rejection")
            await asyncio.wait_for(products[0].control.wait_for_idle(), 10)
            await controller.poll()
            assert sum(message.role == "assistant" for message in products[0].control.messages) == 2
            assert path.read_bytes().startswith(original)
        finally:
            release.set()
            if submitting is not None:
                await asyncio.wait_for(asyncio.gather(submitting, return_exceptions=True), 10)
            if controller is not None:
                await controller.close()
            assert (await runtime.shutdown()).completed
            await owner.close()
        fresh = attempt(tmp_path)
        restored = await fresh.open()
        try:
            view = await open_hosted_mux_profile(restored.client, selector=MuxSelectorV1(name="dev"))
            assert len(view.state.windows) == 1 and view.state.windows[0].session_id == envelope.session_id
            assert len(products) == 2
            await view.submit("continue after application restart")
            await asyncio.wait_for(products[1].control.wait_for_idle(), 10)
            assert sum(message.role == "assistant" for message in products[1].control.messages) == 3
            assert products[1].control.messages[-1].content[0].text == "真实跨进程回复\nG14"
            await view.close()
        finally:
            assert (await restored.shutdown()).completed
            await fresh.close()

    asyncio.run(scenario())


def test_unadmitted_scope_rejected_before_factory_or_session_writes(tmp_path, monkeypatch):
    async def scenario():
        monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
        owner = attempt(tmp_path)
        runtime = await owner.open()
        view = None
        try:
            await runtime.client.create_mux(MuxCreateV1("dev"))
            view = await open_hosted_mux_profile(runtime.client, selector=MuxSelectorV1(name="dev"))
            scope = owner._request.foreground.sessions.scopes[0]
            before = tree(tmp_path)
            foreground = owner._request.foreground
            with pytest.raises(ValueError, match="execution adapter"):
                CodingAppHostHostedSessionResolverV1(
                    runtime=owner._runtime, sessions=foreground.sessions,
                    profile_id=foreground.profile_id, operation_id_factory=lambda: "unused",
                    admitted_scopes=foreground.admitted_scopes, managed_selection=True, execution=True,
                )
            with pytest.raises(AppServiceError):
                await view.open_member(SessionOpenSpecV1(
                    "coding", "rejected", scope.scope, "f" * 64, title="invalid scope",
                ))
            assert not view.state.windows and tree(tmp_path) == before
            assert not owner._request.foreground.sessions.pending_sessions
        finally:
            if view is not None:
                await view.close()
            assert (await runtime.shutdown()).completed
            await owner.close()

    asyncio.run(scenario())


def test_managed_activation_requires_exact_catalog_scope_profile_and_owner(tmp_path):
    async def scenario():
        owner = attempt(tmp_path)
        request = owner._request.foreground
        before = tree(tmp_path)
        for changes in (
            {"managed_selection": False}, {"managed_selection": 1},
            {"profile_id": CODING_HOSTED_APPLICATION_PROFILE_ID},
            {"admitted_scopes": request.admitted_scopes[:1]}, {"session_owner": None},
            {"sessions": object()},
            {"execution": HostedExecutionServiceBindingV1("app", "instance", lambda port: None)},
        ):
            with pytest.raises((TypeError, ValueError)):
                replace(request, **changes)
        await owner.close()
        assert tree(tmp_path) == before and not owner.cleanup_pending

    asyncio.run(scenario())


@pytest.mark.parametrize("target", ["sessions", "session-assets", ".session-blob-writers", ".session-blob-writers/app"])
def test_managed_application_cannot_overlap_session_data(tmp_path, target):
    (tmp_path / target).parent.mkdir(mode=0o700, exist_ok=True)
    with pytest.raises(ValueError, match="separate"):
        CodingManagedApplicationLaunchV1(tmp_path, tmp_path / target, "coding.managed", tmp_path / "sessions")
