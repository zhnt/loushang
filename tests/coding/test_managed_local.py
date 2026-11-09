from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.apphost.managed.contracts import (
    ManagedContractError,
    ManagedInstanceRefV1,
    ManagedServiceKeyV1,
)
from loushang.apphost.managed.invocation import ManagedChildInvocationV1
from loushang.apphost.managed.paths import resolve_managed_admission_root
from loushang.appservice.managed_mux import ManagedMuxServiceBindingV1
from loushang.coding.hosted_local import CodingLocalCommandV1
from loushang.coding.managed_bootstrap import CodingManagedApplicationLaunchV1
from loushang.coding.managed_local import (
    CodingManagedLocalCommandV1,
    CodingManagedLocalLaunchV1,
    create_coding_managed_local_launch,
)

from ..apphost.test_managed_bootstrap import deployment as deployment
from .test_hosted_local import _local_launch
from .test_managed_catalog import tree
from .test_managed_launch import invocation


def test_invocation_selects_same_canonical_scopes_without_effects(deployment, tmp_path):
    async def scenario():
        value = invocation(deployment, tmp_path)
        before = tree(tmp_path)
        launch = create_coding_managed_local_launch(
            value, session_root=tmp_path / "sessions", application_id="coding.default",
            endpoint="workspace", session_discovery=True,
        )
        owner = CodingManagedLocalCommandV1(launch)
        catalog = owner._attempt._request.foreground.sessions
        assert catalog.scopes == launch.application.scopes
        assert {scope.session_dir for scope in catalog.scopes} == {tmp_path / "sessions"}
        assert launch.connection_root == Path(deployment[4].connection)
        assert launch.application.application_root == Path(deployment[4].application)
        assert owner._attempt._request.foreground.session_owner is catalog
        assert tree(tmp_path) == before
        await owner.close()
        assert not owner.cleanup_pending and tree(tmp_path) == before
        for method in ("prepare", "activate", "start"):
            assert getattr(CodingManagedLocalCommandV1, method) is getattr(CodingLocalCommandV1, method)

    asyncio.run(scenario())


def test_managed_command_keeps_product_runtime_selection_lazy_and_trusted(
    deployment, tmp_path
):
    async def scenario():
        value = invocation(deployment, tmp_path)
        launch = create_coding_managed_local_launch(
            value,
            session_root=tmp_path / "sessions",
            application_id="coding.default",
            endpoint="workspace",
        )
        before = tree(tmp_path)
        called = []

        def select(manager):
            called.append(manager)
            raise AssertionError("construction must not select a Session runtime")

        command = CodingManagedLocalCommandV1(
            launch, package_product_runtime_factory_for_session=select
        )
        factory = command._attempt._request.foreground.session_factory
        assert factory._package_product_runtime_factory_for_session is select
        assert called == []
        await command.close()
        assert tree(tmp_path) == before

    asyncio.run(scenario())


def test_managed_close_keeps_factory_debt_after_application_closes(deployment, tmp_path):
    async def scenario():
        value = invocation(deployment, tmp_path)
        launch = create_coding_managed_local_launch(
            value, session_root=tmp_path / "sessions", application_id="coding.default", endpoint="workspace",
        )
        before = tree(tmp_path)

        class Factory:
            settled = False
            calls = 0

            def new_capture(self):
                raise AssertionError("unstarted application must not allocate a capture")

            async def close(self):
                assert owner._settled  # Original application close must complete first.
                self.calls += 1
                if self.calls == 1:
                    raise OSError("temporary cleanup needs retry")
                self.settled = True

        factory = Factory()
        owner = CodingManagedLocalCommandV1(launch, output_capture_factory=factory)
        with pytest.raises(OSError):
            await owner.close()
        assert owner._settled and owner.cleanup_pending and not factory.settled
        await owner.close()
        assert factory.calls == 2 and not owner.cleanup_pending
        assert tree(tmp_path) == before

    asyncio.run(scenario())


@pytest.mark.parametrize("field", ("application_id", "service_id", "instance_id"))
def test_managed_binding_mismatch_is_rejected_before_path_io(deployment, tmp_path, monkeypatch, field):
    value = invocation(deployment, tmp_path)
    binding = ManagedMuxServiceBindingV1(
        "coding.default", value.service.service_id, value.instance.instance_id,
        lambda _: pytest.fail("launch construction must not acquire authority"),
    )
    replacement = {"application_id": "coding.other", "service_id": "e" * 64, "instance_id": "e" * 32}[field]
    binding = replace(binding, **{field: replacement})
    monkeypatch.setattr(Path, "resolve", lambda *_: pytest.fail("invalid binding performed path IO"))
    with pytest.raises(ManagedContractError):
        create_coding_managed_local_launch(
            value, session_root=tmp_path / "sessions", application_id="coding.default", endpoint="workspace",
            managed_mux=binding,
        )


def test_legacy_and_managed_commands_reject_each_others_launch(deployment, tmp_path, monkeypatch):
    value = invocation(deployment, tmp_path)
    managed = create_coding_managed_local_launch(
        value, session_root=tmp_path / "sessions", application_id="coding.default", endpoint="workspace",
    )
    before = tree(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("wrong launch constructed a directory or attempt")

    from loushang.coding import hosted_local, managed_local

    monkeypatch.setattr(hosted_local, "LocalConnectionDirectoryV1", forbidden)
    monkeypatch.setattr(hosted_local, "create_coding_hosted_attempt", forbidden)
    monkeypatch.setattr(managed_local, "create_coding_managed_attempt", forbidden)
    with pytest.raises(TypeError):
        CodingLocalCommandV1(managed)
    with pytest.raises(TypeError):
        CodingManagedLocalCommandV1(_local_launch(tmp_path))
    assert tree(tmp_path) == before


@pytest.mark.parametrize("enclosed", ["session_storage", "application"])
def test_connection_cannot_enclose_durable_authority(tmp_path, enclosed):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    application = CodingManagedApplicationLaunchV1(
        workspace, data / "application" if enclosed == "application" else tmp_path / "application",
        "coding.default", data / "sessions" if enclosed == "session_storage" else tmp_path / "sessions",
    )
    with pytest.raises(ValueError, match="separate"):
        CodingManagedLocalLaunchV1(application, data, "workspace")


@pytest.mark.parametrize("domain", ["sessions", "session-assets", ".session-blob-writers", "application"])
@pytest.mark.parametrize("nested", [False, True])
def test_connection_cannot_overlap_session_or_application_authority(tmp_path, domain, nested):
    application = CodingManagedApplicationLaunchV1(tmp_path, tmp_path / "application", "coding.default", tmp_path / "sessions")
    target = tmp_path / domain
    if nested:
        target.mkdir(mode=0o700)
        target /= "connection"
    with pytest.raises(ValueError, match="separate"):
        CodingManagedLocalLaunchV1(application, target, "workspace")


@pytest.mark.parametrize("domain", ["registry", "lifecycle", "logs", "temporary", "runtime_control"])
def test_session_root_cannot_be_a_managed_control_directory(deployment, tmp_path, domain):
    with pytest.raises(ValueError):
        create_coding_managed_local_launch(
            invocation(deployment, tmp_path), session_root=Path(getattr(deployment[4], domain)),
            application_id="coding.default", endpoint="workspace",
        )


@pytest.mark.parametrize("relationship", ["equal", "ancestor", "descendant", "sibling_namespace"])
def test_session_authority_cannot_overlap_admission_witness(deployment, tmp_path, relationship):
    value = invocation(deployment, tmp_path)
    root = Path(resolve_managed_admission_root(value.namespace))
    selected = {
        "equal": root, "ancestor": root.parent.parent, "descendant": root / "sessions",
        "sibling_namespace": root.parent / ("f" * 64) / "sessions",
    }[relationship]
    before = tree(tmp_path)
    with pytest.raises(ManagedContractError):
        create_coding_managed_local_launch(
            value, session_root=selected, application_id="coding.default", endpoint="workspace",
        )
    assert tree(tmp_path) == before


def test_wrong_product_is_rejected_before_native_path_checks(deployment, tmp_path, monkeypatch):
    value = invocation(deployment, tmp_path)
    service = ManagedServiceKeyV1("work", value.service.workspace)
    other = ManagedChildInvocationV1(value.namespace, service, ManagedInstanceRefV1(
        value.namespace.namespace_key, service.service_id, value.instance.instance_id,
    ), value.attempt_id, value.runtime_root)

    def forbidden(*args, **kwargs):
        raise AssertionError("wrong Product performed path checks")

    monkeypatch.setattr(Path, "resolve", forbidden)
    with pytest.raises(ManagedContractError):
        create_coding_managed_local_launch(other, session_root=tmp_path / "sessions", application_id="coding.default", endpoint="workspace")


def test_scope_and_endpoint_fields_keep_existing_closed_record_validation(tmp_path):
    launch = CodingManagedLocalLaunchV1(
        CodingManagedApplicationLaunchV1(tmp_path, tmp_path / "application", "coding.default", tmp_path / "sessions"),
        tmp_path / "connection", "workspace",
    )
    for changes in ({"session_discovery": 1}, {"endpoint": "../other"}, {"connection_root": Path("relative")}):
        with pytest.raises((TypeError, ValueError)):
            replace(launch, **changes)


def test_managed_execution_registry_is_shared_and_shutdown_settles_original_owner(tmp_path, monkeypatch):
    from loushang.agent import synthetic_model_transport
    from loushang.apphost import AppHostRuntimeV1
    from loushang.appserver.local import LocalAppClientConnectionV1
    from loushang.appserver.local_record import LocalConnectionDirectoryV1
    from loushang.appserver.protocol import (
        MuxAttachV1,
        MuxCreateV1,
        MuxMemberOpenV1,
        MuxSelectorV1,
        SessionOpenSpecV1,
        SessionSnapshotRequestV1,
    )
    from loushang.appserver.protocol.connection_profile import AppConnectionProfileV1
    from loushang.appservice import runtime as service_module
    from loushang.appservice.execution_contract import ExecutionStatusV1

    from .test_hosted_local import _model

    async def scenario():
        monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
        (tmp_path / "sessions").mkdir(mode=0o700)
        entered, cleaning, release = (asyncio.Event() for _ in range(3))
        registries, events = [], []
        original_registry = service_module.ExecutionRegistryV1

        def registry(**kwargs):
            value = original_registry(**kwargs)
            registries.append(value)
            return value

        monkeypatch.setattr(service_module, "ExecutionRegistryV1", registry)

        @synthetic_model_transport
        async def held_stream(*args, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()
                events.append("execution-cleaned")

        launch = CodingManagedLocalLaunchV1(
            CodingManagedApplicationLaunchV1(tmp_path, tmp_path / "application", "coding.managed", tmp_path / "sessions"),
            tmp_path / "connection", "workspace", session_discovery=True,
        )
        command = CodingManagedLocalCommandV1(launch, model=_model(), stream_fn=held_stream, tools=[])
        directory = LocalConnectionDirectoryV1(launch.connection_root)
        first, second = (LocalAppClientConnectionV1(directory, "workspace") for _ in range(2))
        closing = None
        try:
            config = command._attempt._request.foreground.execution
            assert config is not None and registries == []
            await command.start()
            assert len(registries) == 1
            shared = registries[0]
            assert shared.service_instance_id == config.service_instance_id
            assert directory.read("workspace").semantic_profile is AppConnectionProfileV1.LOCAL_DISCOVERY_EXECUTION
            await first.start()
            await second.start()
            assert len(registries) == 1
            assert first.execution_client.service_instance_id == second.execution_client.service_instance_id == config.service_instance_id
            mux = await first.client.create_mux(MuxCreateV1("dev"))
            selector = MuxSelectorV1(mux_space_id=mux.mux_space_id)
            await first.client.attach_mux(MuxAttachV1(selector))
            scope = launch.application.scopes[0]
            mux = await first.client.open_member(MuxMemberOpenV1(selector, SessionOpenSpecV1(
                "coding", "managed-execution", scope.scope, scope.fingerprint, "managed",
            )))
            attachment = await first.client.attach_mux(MuxAttachV1(selector))
            control = SessionSnapshotRequestV1(attachment.attachment_id, attachment.controller_generation, mux.members[0].member_id)
            accepted = await first.execution_client.submit_execution(control, config.service_instance_id, "submission", "wait")
            await entered.wait()
            service = command._local._application._application._service
            adapter = service._sessions[accepted.identity.session_id]._port
            leased = adapter._binding
            assert adapter._product_binding is leased._lease.profile_binding
            assert shared.active_count == 1
            assert shared.find(accepted.identity, "submission").identity == adapter.identity
            close_session = AppHostRuntimeV1.close_session

            async def observe_close(runtime, key):
                assert leased._lease_closed
                assert shared.active_count == 0
                events.append("runtime-close")
                await close_session(runtime, key)

            monkeypatch.setattr(AppHostRuntimeV1, "close_session", observe_close)
            closing = asyncio.create_task(command.close())
            await cleaning.wait()
            assert not closing.done() and not leased._lease_closed
            assert shared.active_count == 1
            release.set()
            await closing
            assert events == ["execution-cleaned", "runtime-close"]
            assert leased._runtime_closed and not command.cleanup_pending
            assert shared.find(accepted.identity, "submission").state.status is ExecutionStatusV1.INTERRUPTED
            assert len(registries) == 1
        finally:
            release.set()
            if closing is not None:
                await closing
            await first.close()
            await second.close()
            await command.close()
            directory.close()

    asyncio.run(asyncio.wait_for(scenario(), 30))
