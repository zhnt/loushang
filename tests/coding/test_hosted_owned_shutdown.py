from __future__ import annotations

import asyncio
import sys

import pytest

from loushang.appserver.protocol import MuxCreateV1, MuxSelectorV1, SessionOpenSpecV1
from loushang.appservice import ApplicationContinuityError
from loushang.coding.hosted_application import CodingForegroundProductFactoryV1
from loushang.coding.hosted_bootstrap import create_coding_hosted_attempt
from loushang.harnesstui.mux import open_hosted_mux_profile

from ._hosted_product_child import scripted_stream
from .test_hosted_bootstrap import _launch
from .test_hosted_local import _model

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux owned hosted transcripts")


def test_real_owned_hosted_shutdown_and_continuity_reopen(tmp_path, monkeypatch):
    async def scenario():
        monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
        monkeypatch.setenv("LOUSHANG_RUNTIME_DIR", str(tmp_path / "runtime"))
        launch = _launch(tmp_path)
        launch.cwd_sessions.mkdir(mode=0o700)
        launch.home_sessions.mkdir(mode=0o700)
        attempt = create_coding_hosted_attempt(
            launch, owned_transcripts=True, model=_model(), stream_fn=scripted_stream, tools=[],
        )
        catalog = attempt._request.foreground.sessions
        assert attempt._request.foreground.session_owner is catalog
        runtime = await attempt.open()
        controller = None
        try:
            await runtime.client.create_mux(MuxCreateV1("dev"))
            controller = await open_hosted_mux_profile(runtime.client, selector=MuxSelectorV1(name="dev"))
            scope = launch.scopes[0]
            state = await controller.open_member(SessionOpenSpecV1(
                "coding", "continuity-owned", scope.scope, scope.fingerprint, title="owned",
            ))
            identity = state.windows[0].session_id
            await controller.submit("hello owned")
            await controller.poll()
            await controller.close()
            controller = None
        finally:
            if controller is not None:
                await controller.close()
            assert (await runtime.shutdown()).completed
            await attempt.close()
        assert catalog._closing and catalog._owned_factory._closing
        assert not catalog.pending_sessions and not catalog._owned_factory.pending_preparations
        fresh = create_coding_hosted_attempt(
            launch, owned_transcripts=True, model=_model(), stream_fn=scripted_stream, tools=[],
        )
        resumed = await fresh.open()
        try:
            view = await open_hosted_mux_profile(resumed.client, selector=MuxSelectorV1(name="dev"))
            assert view.state.windows[0].session_id == identity
            await view.close()
        finally:
            assert (await resumed.shutdown()).completed
            await fresh.close()

    asyncio.run(scenario())


def test_unopened_attempt_does_close_explicit_catalog_without_creating_roots(tmp_path):
    async def scenario():
        attempt = create_coding_hosted_attempt(_launch(tmp_path), owned_transcripts=True)
        owner = attempt._request.foreground.session_owner
        assert not tuple(tmp_path.iterdir())
        await attempt.close()
        assert owner._closing and owner._owned_factory._closing
        assert not attempt.cleanup_pending and not tuple(tmp_path.iterdir())

    asyncio.run(scenario())


def test_catalog_cleanup_failure_prevents_continuity_lease_release_until_retry(tmp_path, monkeypatch):
    async def scenario():
        attempt = create_coding_hosted_attempt(_launch(tmp_path), owned_transcripts=True)
        catalog = attempt._request.foreground.session_owner
        runtime = await attempt.open()
        close = catalog.close
        calls = []

        async def unavailable():
            calls.append(True)
            raise OSError("catalog cleanup unavailable")

        with monkeypatch.context() as patch:
            patch.setattr(catalog, "close", unavailable)
            assert not (await runtime.shutdown()).completed
            assert catalog._closing and calls == [True]
            with pytest.raises(ApplicationContinuityError):
                await attempt._request.store.acquire(application_id="coding.default", owner_epoch="contender")
        assert catalog.close == close
        assert (await runtime.shutdown()).completed
        lease = await attempt._request.store.acquire(application_id="coding.default", owner_epoch="after-cleanup")
        await lease.close()
        await attempt.close()

    asyncio.run(scenario())


def test_product_failure_still_attempts_independent_catalog_cleanup():
    async def scenario():
        calls = []

        class SessionFactory:
            async def create_session(self, **kwargs):
                raise AssertionError("not constructing")

        class CatalogOwner:
            def fence(self):
                calls.append("fence")
                raise ValueError("fence failure")

            async def close(self):
                calls.append("catalog")

        class ProductFactory(CodingForegroundProductFactoryV1):
            async def settle_pending_cleanup(self):
                calls.append("product")
                raise OSError("product cleanup failure")

        product = ProductFactory(SessionFactory(), session_owner=CatalogOwner())
        with pytest.raises(ValueError, match="fence failure"):
            await product.close()
        assert calls == ["fence", "product", "catalog"]

    asyncio.run(scenario())
