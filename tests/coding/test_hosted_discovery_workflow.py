"""Real Product/semantic workflow; not installed-terminal acceptance evidence."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from loushang.ai.types import UserMessage
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    MuxCreateV1,
    MuxMemberOpenV1,
    MuxSelectorV1,
    SessionListV1,
    SessionOpenSpecV1,
    SessionScopeV1,
)
from loushang.appservice.discovery_ports import HostedSessionDiscoveryScopeV1
from loushang.coding.bootstrap import create_services
from loushang.coding.hosted_bootstrap import create_coding_hosted_attempt
from loushang.coding.hosted_catalog import CodingHostedSessionCatalogV1
from loushang.coding.session_manager import SessionManager
from loushang.harness.config.agent import SettingsManager
from loushang.harnesstui.mux import open_hosted_mux_profile

from .test_hosted_bootstrap import _launch
from .test_hosted_discovery import _create
from .test_hosted_session import _model, _stream


@pytest.mark.parametrize("kind", list(SessionScopeV1))
@pytest.mark.parametrize("scoped", [False, True])
def test_G17_PRODUCT_discover_resume_interact_and_recover_without_replay(
    tmp_path, monkeypatch, kind, scoped,
):
    monkeypatch.setattr("loushang.coding.hosted_bootstrap._services", lambda cwd: create_services(
        settings_manager=SettingsManager(
            global_settings_path=tmp_path / "settings.json",
            project_settings_path=cwd / ".loushang" / "settings.json",
        ),
    ))

    async def scenario():
        launch = _launch(tmp_path)
        scope = next(item for item in launch.scopes if item.scope is kind)
        await _create(CodingHostedSessionCatalogV1((scope,)), scope, 3)
        query = SessionListV1("coding", kind, scope.fingerprint, limit=1)
        old_cursor = None
        selected = None
        for generation in range(2):
            attempt = create_coding_hosted_attempt(
                launch, model=_model(), stream_fn=_stream, tools=[], session_discovery=True,
            )
            app = await attempt.open()
            client_scope = controller = None
            try:
                if scoped:
                    app.enable_client_scopes()
                    client_scope = app.open_client_scope()
                    client, discovery = client_scope, client_scope.discovery_client
                else:
                    client, discovery = app.client, app.discovery_client
                assert discovery is not None
                if generation == 0:
                    page = await discovery.list_sessions(query)
                    assert page.complete and page.continuation
                    old_cursor = page.continuation
                    selected = page.candidates[0].identity
                    # A normal append since listing is not stale identity authority.
                    path = scope.session_dir / f"hosted-{selected.session_id}.jsonl"
                    manager = await SessionManager.open(path)
                    try:
                        await manager.append_message(UserMessage(
                            role="user", content="before resume", timestamp=1.0,
                        ))
                    finally:
                        await manager.dispose_runtime_profile()
                    lines = path.read_text().splitlines()
                    header = json.loads(lines[0])
                    header["metadata"]["padding"] = "x" * 35000
                    lines[0] = json.dumps(header)
                    path.write_text("\n".join(lines) + "\n")
                    # Discovery and strict routing share the actual 64 KiB header
                    # contract, not the old 32 KiB display-summary projection.
                    assert (await discovery.list_sessions(query)).complete
                    await client.create_mux(MuxCreateV1("dev"))
                else:
                    with pytest.raises(AppServiceError) as expired:
                        await discovery.list_sessions(replace(query, continuation=old_cursor))
                    assert expired.value.code is AppErrorCodeV1.SNAPSHOT_REQUIRED
                controller = await open_hosted_mux_profile(client, selector=MuxSelectorV1(name="dev"))
                assert selected is not None
                if generation == 0:
                    spec = SessionOpenSpecV1(
                        product_id=selected.product_id, continuity_id=selected.continuity_id,
                        session_id=selected.session_id, scope=selected.scope,
                        scope_fingerprint=selected.scope_fingerprint, title="Resumed",
                    )
                    state = await controller.open_member(spec)
                    assert state.windows[0].records[0].text == "before resume"
                    await controller.submit("after resume")
                    await controller.poll()
                assert controller.state is not None
                assert [record.text for record in controller.state.windows[0].records] == [
                    "before resume", "after resume", "real Coding response",
                ]
                await controller.close()
                controller = None
                if client_scope is not None:
                    await client_scope.close()
                    assert app.accepting
                    other = app.open_client_scope()
                    try:
                        assert (await other.list_muxes()).mux_spaces[0].members
                    finally:
                        await other.close()
            finally:
                if controller is not None:
                    await controller.close()
                if client_scope is not None:
                    await client_scope.close()
                await app.close()
                await attempt.close()
    asyncio.run(asyncio.wait_for(scenario(), 30))


@pytest.mark.parametrize("enabled", [False, True])
def test_G17_AUTHORITY_direct_resume_rejects_scope_before_catalog_and_maps_missing(
    tmp_path, monkeypatch, enabled,
):
    async def scenario():
        launch = _launch(tmp_path)
        scope = launch.scopes[0]
        attempt = create_coding_hosted_attempt(launch, session_discovery=enabled)
        app = await attempt.open()
        try:
            client = app.client
            assert (app.discovery_client is not None) is enabled
            await client.create_mux(MuxCreateV1("dev"))
            spec = SessionOpenSpecV1(
                product_id="coding", continuity_id="continuity", session_id="missing",
                scope=scope.scope, scope_fingerprint=scope.fingerprint, title="Missing",
            )
            with pytest.raises(AppServiceError) as missing:
                await client.open_member(MuxMemberOpenV1(MuxSelectorV1(name="dev"), spec))
            assert missing.value.code is AppErrorCodeV1.NOT_FOUND

            catalog_calls = []
            async def forbidden(*_args, **_kwargs):
                catalog_calls.append(True)
                raise AssertionError("private catalog sentinel")
            monkeypatch.setattr(CodingHostedSessionCatalogV1, "list_identities", forbidden)
            for request in (
                spec, replace(spec, scope_fingerprint="b" * 64),
                replace(spec, scope=SessionScopeV1.USER_HOME),
            ):
                with pytest.raises(AppServiceError) as unavailable:
                    await client.open_member(MuxMemberOpenV1(MuxSelectorV1(name="dev"), request))
                assert unavailable.value.code is AppErrorCodeV1.SESSION_UNAVAILABLE
                assert "sentinel" not in str(unavailable.value)
                assert catalog_calls == [True]  # Only the admitted request scanned.
        finally:
            await app.close()
            await attempt.close()
    asyncio.run(asyncio.wait_for(scenario(), 10))


@pytest.mark.parametrize("case", ["malformed", "file-root", "unreadable"])
def test_G17_AUTHORITY_unverifiable_real_resume_is_not_missing(tmp_path, monkeypatch, case):
    async def scenario():
        launch = _launch(tmp_path)
        scope = launch.scopes[0]
        catalog = CodingHostedSessionCatalogV1((scope,))
        await _create(catalog, scope)
        snapshot = await catalog.discover_sessions(
            HostedSessionDiscoveryScopeV1("coding", scope.scope, scope.fingerprint),
            stop=lambda: False,
        )
        selected = snapshot.candidates[0].identity
        if case == "file-root":
            scope.session_dir.rename(tmp_path / "old-sessions")
            scope.session_dir.write_text("not a directory")
        elif case == "malformed":
            next(scope.session_dir.glob("*.jsonl")).write_text("{invalid\n")
        else:
            def unreadable(*_args, **_kwargs):
                raise PermissionError("private-read-sentinel")
            monkeypatch.setattr("loushang.coding.hosted_catalog.load_agent_transcript_header", unreadable)
        attempt = create_coding_hosted_attempt(launch, session_discovery=True)
        app = await attempt.open()
        try:
            client = app.client
            await client.create_mux(MuxCreateV1("dev"))
            with pytest.raises(AppServiceError) as unavailable:
                await client.open_member(MuxMemberOpenV1(
                    MuxSelectorV1(name="dev"), SessionOpenSpecV1(
                        product_id="coding", continuity_id=selected.continuity_id,
                        session_id=selected.session_id, scope=scope.scope,
                        scope_fingerprint=scope.fingerprint, title="Unavailable",
                    ),
                ))
            assert unavailable.value.code is AppErrorCodeV1.SESSION_UNAVAILABLE
        finally:
            await app.close()
            await attempt.close()
    asyncio.run(asyncio.wait_for(scenario(), 10))
