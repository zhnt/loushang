"""Managed creation is an authorized durable operation, not create-by-name."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.appserver.managed_mux import ManagedMuxCreateV1
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    MuxCloseV1,
    MuxCreateV1,
    MuxSelectorV1,
)
from loushang.appservice import (
    AppServiceRecoveryRequestV1,
    JsonFileApplicationContinuityStoreV1,
    create_appservice_recovery_attempt,
)
from loushang.appservice.continuity import (
    APPLICATION_CONTINUITY_VERSION,
    MANAGED_CONTINUITY_VERSION,
    ApplicationContinuityRecordV1,
    decode_application_continuity_record,
    encode_application_continuity_record,
)
from loushang.appservice.managed_mux import ManagedMuxServiceBindingV1
from tests.appservice.test_continuity_runtime import _MemoryLease as _Lease
from tests.appservice.test_continuity_runtime import _Resolver

SERVICE = "a" * 64
INSTANCE = "b" * 32
OPERATION = "c" * 32


class _Admission:
    def __init__(self, *, allowed: bool = True) -> None:
        self.allowed = allowed
        self.acquired = False
        self.closed = 0
        self.fail_close = False
        self.entered = asyncio.Event()
        self.release: asyncio.Event | None = None

    async def acquire(self) -> None:
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if not self.allowed:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        self.acquired = True

    async def close(self) -> None:
        self.closed += 1
        if self.fail_close:
            raise RuntimeError("private authority failure")
        self.acquired = False

    def check_creation(self, previous) -> None:
        assert self.acquired


def _request(**changes: object) -> ManagedMuxCreateV1:
    return replace(
        ManagedMuxCreateV1(SERVICE, INSTANCE, OPERATION, "dev", "secret"),
        **changes,
    )


def _binding(admissions: list[_Admission], *, instance: str = INSTANCE):
    def prepare(request: ManagedMuxCreateV1) -> _Admission:
        owner = _Admission(allowed=request.authority == "secret")
        admissions.append(owner)
        return owner

    return ManagedMuxServiceBindingV1("coding.default", SERVICE, instance, prepare)


async def _open(lease, binding):
    attempt = create_appservice_recovery_attempt(AppServiceRecoveryRequestV1(
        "coding", _Resolver([]), lease, managed_mux=binding,
    ))
    return await attempt.open()


def test_managed_create_concurrent_replay_is_one_durable_result() -> None:
    async def scenario():
        admissions: list[_Admission] = []
        lease = _Lease()
        service = await _open(lease, _binding(admissions))
        try:
            first, second = await asyncio.gather(
                service.create_managed_mux(_request()),
                service.create_managed_mux(_request()),
            )
            assert first == second
            assert first.operation_id == OPERATION
            assert first.instance_id == INSTANCE
            assert len(lease.commits) == 1
            assert lease.record.managed_creations == (first,)
            assert lease.record.mux_spaces[0].mux_space_id == first.mux_space_id
            assert len((await service.list_muxes()).mux_spaces) == 1
            assert len(admissions) == 2
            assert all(owner.closed == 1 and not owner.acquired for owner in admissions)
            for request in (
                _request(name="other"),
                _request(operation_id="d" * 32),
            ):
                with pytest.raises(AppServiceError):
                    await service.create_managed_mux(request)
            assert len(lease.commits) == 1
        finally:
            await service.close()

    asyncio.run(scenario())


def test_managed_create_real_store_recovery_requires_fresh_instance_authority(
    tmp_path: Path,
) -> None:
    async def scenario():
        admissions: list[_Admission] = []
        store = JsonFileApplicationContinuityStoreV1(tmp_path / "continuity")
        lease = await store.acquire(application_id="coding.default", owner_epoch="one")
        service = await _open(lease, _binding(admissions))
        result = await service.create_managed_mux(_request())
        await service.close()
        await lease.close()
        lease = await store.acquire(application_id="coding.default", owner_epoch="two")
        second = await _open(lease, _binding(admissions, instance="e" * 32))
        try:
            with pytest.raises(AppServiceError):
                await second.create_managed_mux(_request())
            assert await second.create_managed_mux(
                _request(instance_id="e" * 32)
            ) == result
            assert second.continuity_revision == 1
        finally:
            await second.close()
            await lease.close()

    asyncio.run(scenario())


def test_managed_legacy_mutations_and_bad_authority_have_no_effect() -> None:
    async def scenario():
        admissions: list[_Admission] = []
        lease = _Lease()
        service = await _open(lease, _binding(admissions))
        try:
            for call in (
                lambda: service.create_mux(MuxCreateV1("dev")),
                lambda: service.close_mux(MuxCloseV1(MuxSelectorV1(name="dev"))),
                lambda: service.create_managed_mux(_request(authority="wrong")),
                lambda: service.create_managed_mux(_request(service_id="f" * 64)),
            ):
                with pytest.raises(AppServiceError):
                    await call()
            assert not lease.commits
            assert len(admissions) == 1
            assert admissions[0].closed == 1
            await service.create_managed_mux(_request())
            with pytest.raises(AppServiceError):
                await service.create_managed_mux(_request(authority="wrong"))
            assert len(lease.commits) == 1
        finally:
            await service.close()

    asyncio.run(scenario())


def test_managed_create_cancelled_commit_still_publishes_original_receipt() -> None:
    async def scenario():
        gate = asyncio.Event()
        entered = asyncio.Event()

        class PausedLease(_Lease):
            async def commit(self, *, expected_revision, record):
                entered.set()
                await super().commit(expected_revision=expected_revision, record=record)

        lease = PausedLease(commit_gate=gate)
        admissions: list[_Admission] = []
        service = await _open(lease, _binding(admissions))
        task = asyncio.create_task(service.create_managed_mux(_request()))
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert admissions[0].acquired
        assert admissions[0].closed == 0
        gate.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        result = await service.create_managed_mux(_request())
        assert lease.record.managed_creations == (result,)
        assert len(lease.commits) == 1
        assert admissions[0].closed == 1
        await service.close()

    asyncio.run(scenario())


def test_managed_cleanup_debt_retains_original_and_blocks_new_admission() -> None:
    async def scenario():
        admission = _Admission()
        admission.fail_close = True
        binding = ManagedMuxServiceBindingV1(
            "coding.default", SERVICE, INSTANCE, lambda _request: admission,
        )
        lease = _Lease()
        service = await _open(lease, binding)
        with pytest.raises(AppServiceError) as error:
            await service.create_managed_mux(_request())
        assert error.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
        assert len(lease.commits) == 1
        with pytest.raises(AppServiceError):
            await service.create_managed_mux(_request(operation_id="d" * 32))
        assert admission.closed == 1
        admission.fail_close = False
        await service.close()
        assert admission.closed == 2
        assert not admission.acquired

    asyncio.run(scenario())


def test_managed_unknown_commit_fences_runtime_and_recovery_finds_receipt() -> None:
    class LostReplyLease(_Lease):
        async def commit(self, *, expected_revision, record):
            await super().commit(expected_revision=expected_revision, record=record)
            raise RuntimeError("commit reply lost after write")

    async def scenario():
        admissions: list[_Admission] = []
        lease = LostReplyLease()
        service = await _open(lease, _binding(admissions))
        with pytest.raises(AppServiceError):
            await service.create_managed_mux(_request())
        assert len(lease.commits) == 1
        for request in (_request(), _request(operation_id="d" * 32, name="other")):
            with pytest.raises(AppServiceError):
                await service.create_managed_mux(request)
        assert len(admissions) == 1
        await service.close()
        recovered_lease = _Lease(lease.record)
        recovered = await _open(recovered_lease, _binding(admissions))
        assert await recovered.create_managed_mux(_request()) == lease.record.managed_creations[0]
        assert not recovered_lease.commits
        await recovered.close()

    asyncio.run(scenario())


def test_managed_recovery_cannot_silently_switch_owner_or_legacy_profile() -> None:
    async def scenario():
        admissions: list[_Admission] = []
        original = ApplicationContinuityRecordV1("coding.default", "coding", 1)
        with pytest.raises(AppServiceError):
            await _open(_Lease(original), _binding(admissions))
        managed = replace(original, contract_version=MANAGED_CONTINUITY_VERSION,
                          managed_service_id=SERVICE)
        for binding in (None, replace(_binding(admissions), service_id="f" * 64)):
            with pytest.raises(AppServiceError):
                await _open(_Lease(managed), binding)
        assert not admissions

    asyncio.run(scenario())


def test_managed_receipts_are_bounded_strict_and_do_not_change_legacy_bytes() -> None:
    import json

    from loushang.appserver.managed_mux import ManagedMuxCreatedV1
    from loushang.appservice.continuity import ApplicationContinuityError

    legacy = ApplicationContinuityRecordV1("coding.default", "coding", 1)
    assert encode_application_continuity_record(legacy) == (
        b'{"applicationId":"coding.default","contractVersion":'
        b'"loushang.appservice.continuity/v1","muxSpaces":[],"productId":"coding",'
        b'"recordRevision":1}'
    )
    receipt = ManagedMuxCreatedV1(OPERATION, INSTANCE, "dev", "mux-old")
    managed = replace(legacy, contract_version=MANAGED_CONTINUITY_VERSION,
                      managed_service_id=SERVICE, managed_creations=(receipt,))
    assert decode_application_continuity_record(encode_application_continuity_record(managed)) == managed
    raw = json.loads(encode_application_continuity_record(managed))
    for mutation in (
        {"contractVersion": APPLICATION_CONTINUITY_VERSION},
        {"managedServiceId": True},
        {"managedCreations": raw["managedCreations"] * 2},
        {"managedCreations": raw["managedCreations"] * 4097},
        {"extra": "ignored?"},
        {"managedCreations": [dict(raw["managedCreations"][0], authority="secret")]},
    ):
        with pytest.raises(ApplicationContinuityError):
            decode_application_continuity_record(json.dumps(raw | mutation).encode())
    assert "secret" not in repr(_request())


def test_managed_retired_creation_replay_never_resurrects_mux() -> None:
    from loushang.appserver.managed_mux import ManagedMuxCreatedV1

    async def scenario():
        # Simulate a future logical close: the historical creation stays, the
        # live Mux does not. A delayed create RPC must not recreate that Mux.
        receipt = ManagedMuxCreatedV1(OPERATION, INSTANCE, "dev", "mux-retired")
        record = ApplicationContinuityRecordV1(
            "coding.default", "coding", 2, contract_version=MANAGED_CONTINUITY_VERSION,
            managed_service_id=SERVICE, managed_creations=(receipt,),
        )
        lease = _Lease(record)
        service = await _open(lease, _binding([]))
        assert await service.create_managed_mux(_request()) == receipt
        assert not (await service.list_muxes()).mux_spaces
        assert not lease.commits
        await service.close()

    asyncio.run(scenario())


def test_managed_byte_capacity_rejection_does_not_fence_existing_runtime(monkeypatch) -> None:
    async def scenario():
        lease = _Lease()
        service = await _open(lease, _binding([]))
        first = await service.create_managed_mux(_request())
        size = len(encode_application_continuity_record(lease.record))
        monkeypatch.setattr("loushang.appservice.continuity.MAX_CONTINUITY_RECORD_BYTES", size + 1)
        with pytest.raises(AppServiceError):
            await service.create_managed_mux(_request(operation_id="d" * 32, name="other"))
        assert await service.create_managed_mux(_request()) == first
        assert len((await service.list_muxes()).mux_spaces) == 1
        assert len(lease.commits) == 1
        await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ("acquire", "commit", "close"))
@pytest.mark.parametrize("spawned", (False, True))
def test_managed_task_publication_failure_cannot_start_late_effect(phase, spawned) -> None:
    async def scenario():
        lease = _Lease()
        admissions: list[_Admission] = []
        service = await _open(lease, _binding(admissions))
        loop = asyncio.get_running_loop()
        original = loop.get_task_factory()
        tasks: list[asyncio.Task] = []
        calls = 0
        failed_at = {"acquire": 1, "commit": 2, "close": 3}[phase]

        def factory(loop, coroutine, **kwargs):
            nonlocal calls
            calls += 1
            if calls == failed_at:
                if spawned:
                    tasks.append(asyncio.Task(coroutine, loop=loop, **kwargs))
                raise RuntimeError("lost original task receipt")
            return asyncio.Task(coroutine, loop=loop, **kwargs)

        loop.set_task_factory(factory)
        try:
            with pytest.raises(AppServiceError):
                await service.create_managed_mux(_request())
        finally:
            loop.set_task_factory(original)
        await asyncio.gather(*tasks, return_exceptions=True)
        assert len(lease.commits) == (1 if phase == "close" else 0)
        assert len(admissions) == 1
        admission = admissions[0]
        if phase == "close":
            assert admission.acquired and admission.closed == 0
        else:
            assert not admission.acquired and admission.closed == 1
        await service.close()
        assert admission.closed == 1
        assert not admission.acquired

    asyncio.run(scenario())


def test_managed_cancelled_acquisition_closes_only_after_original_settles() -> None:
    async def scenario():
        admission = _Admission()
        admission.release = asyncio.Event()
        binding = ManagedMuxServiceBindingV1(
            "coding.default", SERVICE, INSTANCE, lambda _request: admission,
        )
        lease = _Lease()
        service = await _open(lease, binding)
        task = asyncio.create_task(service.create_managed_mux(_request()))
        await admission.entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and admission.closed == 0
        closing = asyncio.create_task(service.close())
        await asyncio.sleep(0)
        assert not closing.done()
        admission.release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await closing
        assert admission.closed == 1
        assert not lease.commits

    asyncio.run(scenario())


def test_managed_scoped_create_survives_delivery_eof_and_blocks_legacy_before_tasks() -> None:
    from loushang.appserver.protocol import MuxAttachV1
    from loushang.appservice.client_scope import ScopedAppServiceV1

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        class PausedLease(_Lease):
            async def commit(self, *, expected_revision, record):
                entered.set()
                await release.wait()
                await super().commit(expected_revision=expected_revision, record=record)

        lease = PausedLease()
        admissions: list[_Admission] = []
        service = await _open(lease, _binding(admissions))
        owner = ScopedAppServiceV1(service)
        first = owner.open_client_scope()
        assert first.managed_mux_client is first
        waiter = asyncio.create_task(first.create_managed_mux(_request()))
        await entered.wait()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        await first.close()
        assert owner.pending_counts == (1, 0)
        assert admissions[0].acquired and admissions[0].closed == 0
        release.set()
        second = owner.open_client_scope()
        receipt = await second.create_managed_mux(_request())
        assert len(lease.commits) == 1
        selector = MuxSelectorV1(mux_space_id=receipt.mux_space_id)
        attached = await second.attach_mux(MuxAttachV1(selector))
        for call in (
            lambda: second.create_mux(MuxCreateV1("other")),
            lambda: second.close_mux(MuxCloseV1(selector)),
        ):
            with pytest.raises(AppServiceError):
                await call()
        assert owner.pending_counts == (0, 0)
        control = second._controllers[receipt.mux_space_id]
        assert not control.fenced and control.attachment == attached
        assert len(lease.commits) == 1
        await second.close()
        await service.close()

    asyncio.run(scenario())


def test_managed_full_receipt_history_allows_replay_but_no_new_commit() -> None:
    from loushang.appserver.managed_mux import ManagedMuxCreatedV1
    from loushang.appservice.continuity import MAX_MANAGED_CREATIONS

    async def scenario():
        receipts = tuple(
            ManagedMuxCreatedV1(f"{index:032x}", INSTANCE, f"mux-{index}", f"id-{index}")
            for index in range(MAX_MANAGED_CREATIONS)
        )
        record = ApplicationContinuityRecordV1(
            "coding.default", "coding", 1, contract_version=MANAGED_CONTINUITY_VERSION,
            managed_service_id=SERVICE, managed_creations=receipts,
        )
        assert decode_application_continuity_record(encode_application_continuity_record(record)) == record
        lease = _Lease(record)
        service = await _open(lease, _binding([]))
        assert await service.create_managed_mux(
            _request(operation_id=receipts[0].operation_id, name=receipts[0].name)
        ) == receipts[0]
        with pytest.raises(AppServiceError):
            await service.create_managed_mux(_request())
        assert not lease.commits
        assert not (await service.list_muxes()).mux_spaces
        await service.close()

    asyncio.run(scenario())


def test_managed_continuity_requires_unique_operations_and_exact_live_mux_receipts() -> None:
    from loushang.appserver.managed_mux import ManagedMuxCreatedV1
    from loushang.appservice.continuity import MuxSpaceContinuityV1

    receipt = ManagedMuxCreatedV1(OPERATION, INSTANCE, "dev", "mux-1")
    record = ApplicationContinuityRecordV1(
        "coding.default", "coding", 1, contract_version=MANAGED_CONTINUITY_VERSION,
        managed_service_id=SERVICE, managed_creations=(receipt,),
    )
    for receipts in (
        (receipt, replace(receipt, mux_space_id="mux-2")),
        (receipt, replace(receipt, operation_id="d" * 32)),
    ):
        with pytest.raises(ValueError):
            replace(record, managed_creations=receipts)
    for live in (MuxSpaceContinuityV1("missing", "dev", 1),
                 MuxSpaceContinuityV1("mux-1", "other", 1)):
        with pytest.raises(ValueError):
            replace(record, mux_spaces=(live,))


def test_managed_tab_mutations_preserve_original_creation_through_recovery() -> None:
    from loushang.appserver.protocol import (
        MuxMemberCloseV1,
        MuxMemberOpenV1,
        SessionOpenSpecV1,
        SessionScopeV1,
    )

    async def scenario():
        lease = _Lease()
        service = await _open(lease, _binding([]))
        receipt = await service.create_managed_mux(_request())
        selector = MuxSelectorV1(mux_space_id=receipt.mux_space_id)
        for index in range(2):
            mux = await service.open_member(MuxMemberOpenV1(selector, SessionOpenSpecV1(
                "coding", f"continuity-{index}", SessionScopeV1.CWD, "a" * 64, f"Tab {index}",
            )))
            assert lease.record.managed_creations == (receipt,)
        assert len(mux.members) == 2
        await service.close_member(MuxMemberCloseV1(selector, mux.members[0].member_id))
        assert lease.record.managed_creations == (receipt,)
        assert len(lease.record.mux_spaces[0].members) == 1
        await service.close()
        recovered = await _open(_Lease(lease.record), _binding([], instance="e" * 32))
        assert await recovered.create_managed_mux(_request(instance_id="e" * 32)) == receipt
        assert len((await recovered.list_muxes()).mux_spaces[0].members) == 1
        await recovered.close()

    asyncio.run(scenario())


def test_managed_scoped_live_capacity_still_allows_historical_replay() -> None:
    from loushang.appservice.client_scope import ScopedAppServiceV1

    async def scenario():
        lease = _Lease()
        service = await _open(lease, _binding([]))
        owner = ScopedAppServiceV1(service)
        client = owner.open_client_scope()
        first_request = _request(operation_id="0" * 32, name="mux-0")
        first = await client.create_managed_mux(first_request)
        for index in range(1, 32):
            await client.create_managed_mux(_request(
                operation_id=f"{index:032x}", name=f"mux-{index}",
            ))
        assert await client.create_managed_mux(first_request) == first
        with pytest.raises(AppServiceError):
            await client.create_managed_mux(_request())
        assert len(lease.commits) == 32
        assert len((await client.list_muxes()).mux_spaces) == 32
        await client.close()
        await service.close()

    asyncio.run(scenario())
