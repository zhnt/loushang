"""Existing macOS data and launchd cutover checks without a native launchd."""

import asyncio
import sys
from functools import partial
from time import monotonic

import pytest

from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.registry import ManagedMuxReservationV1
from loushang.appservice import (
    AppServiceRecoveryRequestV1,
    create_appservice_recovery_attempt,
)
from loushang.appservice.continuity_file import JsonFileApplicationContinuityStoreV1
from loushang.coding.hosted import macos_service
from loushang.coding.hosted.foreground import NamedMuxProvisioner
from loushang.coding.hosted.managed.service import ServiceControlError
from tests.apphost.test_managed_mux_recovery import owners as _owners
from tests.apphost.test_managed_mux_recovery import recovery, successor
from tests.appservice.test_continuity_runtime import _Resolver

owners = _owners


def test_fresh_home_does_not_query_launchd(tmp_path, monkeypatch):
    def bad_query(*_):
        pytest.fail("fresh home must not query launchd")

    monkeypatch.setattr(macos_service, "LaunchdUserJob", bad_query)
    macos_service.require_legacy_job_stopped(tmp_path)


@pytest.mark.parametrize("registered", [True, False])
def test_migration_requires_the_old_job_to_be_unregistered(tmp_path, monkeypatch, registered):
    state = tmp_path / "state/macos-host"
    state.mkdir(parents=True)
    (state / "host.plist").touch()

    class OldJob:
        def __init__(self, label):
            assert label.startswith("ai.loushang.host.")

        def observe(self):
            return "registered" if registered else "not_running"

    monkeypatch.setattr(macos_service, "LaunchdUserJob", OldJob)
    if registered:
        with pytest.raises(ServiceControlError, match="^legacy_service_active$"):
            macos_service.require_legacy_job_stopped(tmp_path)
    else:
        macos_service.require_legacy_job_stopped(tmp_path)


def test_legacy_workspace_root_is_preserved_and_conflicting_state_is_rejected(tmp_path):
    managed = tmp_path / "hosts/managed/application"
    legacy = tmp_path / "state/macos-host/application"
    managed.mkdir(parents=True)
    assert macos_service.legacy_application_root(tmp_path, managed) is None
    legacy.mkdir(parents=True)
    assert macos_service.legacy_application_root(tmp_path, managed) is None
    (legacy.parent / "host.plist").touch()
    assert macos_service.legacy_application_root(tmp_path, managed) == legacy
    (managed / "coding.default.json").touch()
    with pytest.raises(ManagedStorageError, match="conflict"):
        macos_service.legacy_application_root(tmp_path, managed)


@pytest.mark.skipif(sys.platform != "linux", reason="uses the Linux managed lifecycle fixture")
def test_migrates_real_foreground_mux_receipt_and_restores_it_on_restart(owners, tmp_path):
    root = tmp_path / "state/macos-host/application"
    root.parent.mkdir(parents=True)
    store = JsonFileApplicationContinuityStoreV1(root)
    app_id = "coding.default"

    async def run():
        provisioner = NamedMuxProvisioner(root)
        original = await store.acquire(application_id=app_id, owner_epoch="foreground")
        foreground = await create_appservice_recovery_attempt(AppServiceRecoveryRequestV1(
            "coding", _Resolver([]), original, managed_mux=provisioner.binding,
        )).open()
        await provisioner.ensure_named("old-mux", foreground.create_managed_mux)
        previous = await original.load()
        assert previous is not None
        await foreground.close()
        await original.close()

        first_attempt = "f" * 32
        manager = successor(owners, attempt=first_attempt)
        key = owners[3]
        # The control rows may settle before the legacy record is rewritten.
        await asyncio.to_thread(manager.import_foreground_muxes, previous, deadline=monotonic() + 5)
        await macos_service.import_legacy_continuity(
            root, partial(manager.import_foreground_muxes, deadline=monotonic() + 5),
            application_id=app_id, service_id=key.service_id, attempt_id=first_attempt,
        )
        receipt, = previous.managed_creations
        assert owners[0].resolve("old-mux") == ManagedMuxReservationV1(
            "old-mux", key, receipt.operation_id,
        )

        async def check_restored(current, attempt_id):
            lease = await store.acquire(application_id=app_id, owner_epoch=attempt_id)
            record = await lease.load()
            assert record is not None
            assert record.managed_service_id == key.service_id
            assert record.record_revision == previous.record_revision + 1
            assert record.managed_creations == previous.managed_creations
            restored = await recovery(current, lease).open()
            try:
                mux, = (await restored.list_muxes()).mux_spaces
                assert mux.mux_space_id == receipt.mux_space_id
            finally:
                await restored.close()
                await lease.close()

        await check_restored(manager, first_attempt)
        second_attempt = "e" * 32
        await check_restored(successor(owners, attempt=second_attempt), second_attempt)

    asyncio.run(run())
