from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from loushang.appserver.managed_mux import ManagedMuxCreatedV1
from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError
from loushang.appservice import (
    AppServiceRecoveryRequestV1,
    create_appservice_recovery_attempt,
)
from loushang.appservice.continuity import (
    APPLICATION_CONTINUITY_VERSION,
    MANAGED_CONTINUITY_VERSION,
    ApplicationContinuityError,
    ApplicationContinuityRecordV1,
    decode_application_continuity_record,
    encode_application_continuity_record,
)
from tests.appservice.test_continuity import _record
from tests.appservice.test_continuity_runtime import _MemoryLease, _Resolver
from tests.appservice.test_managed_mux import _binding

SERVICE = "a" * 64


def record(*, closed=False):
    from loushang.appserver.managed_mux_close import (
        ManagedMuxClosePhaseV1,
        ManagedMuxCloseStateV1,
    )
    from loushang.appservice.continuity import MANAGED_CLOSE_CONTINUITY_VERSION

    original = _record()
    creation = ManagedMuxCreatedV1("a" * 32, "b" * 32, "dev", "mux-1")
    close = ManagedMuxCloseStateV1(
        "c" * 32, "d" * 32, creation.operation_id, creation.name, creation.mux_space_id,
        ManagedMuxClosePhaseV1.CLOSED if closed else ManagedMuxClosePhaseV1.CLEANUP_PENDING,
    )
    return replace(original, contract_version=MANAGED_CLOSE_CONTINUITY_VERSION,
                   managed_service_id=SERVICE, managed_creations=(creation,),
                   managed_closures=(close,), mux_spaces=() if closed else original.mux_spaces)


@pytest.mark.parametrize("closed", [False, True])
def test_close_record_roundtrips_exact_phase_and_retained_members(closed):
    value = record(closed=closed)
    encoded = encode_application_continuity_record(value)
    assert decode_application_continuity_record(encoded) == value
    assert (not value.mux_spaces) is closed
    assert "authority" not in encoded.decode()
    assert "managedClosures" in encoded.decode()
    # Creation may precede the closing instance, including after a clean restart.
    assert value.managed_creations[0].instance_id != value.managed_closures[0].instance_id


def test_previous_versions_keep_exact_bytes_and_reject_close_fields():
    legacy = ApplicationContinuityRecordV1("coding.default", "coding", 1)
    assert encode_application_continuity_record(legacy) == (
        b'{"applicationId":"coding.default","contractVersion":'
        b'"loushang.appservice.continuity/v1","muxSpaces":[],"productId":"coding",'
        b'"recordRevision":1}'
    )
    previous = replace(legacy, contract_version=MANAGED_CONTINUITY_VERSION,
                       managed_service_id=SERVICE)
    assert encode_application_continuity_record(previous) == (
        b'{"applicationId":"coding.default","contractVersion":'
        b'"loushang.appservice.continuity/v2","managedCreations":[],"managedServiceId":"'
        + SERVICE.encode() + b'","muxSpaces":[],"productId":"coding","recordRevision":1}'
    )
    for value in (legacy, previous):
        raw = json.loads(encode_application_continuity_record(value))
        with pytest.raises(ApplicationContinuityError):
            decode_application_continuity_record(json.dumps(raw | {"managedClosures": []}).encode())
        with pytest.raises(ValueError):
            replace(value, managed_closures=record().managed_closures)


@pytest.mark.parametrize("mutation", [
    "missing_field", "unknown_field", "duplicate_key", "duplicate_record",
    "duplicate_target", "unknown_creation", "name_mismatch",
    "mux_mismatch", "invalid_phase", "authority", "missing_pending_mux",
    "retained_closed_mux", "aliased_operation", "list_not_tuple",
])
def test_close_record_rejects_inconsistent_or_ambiguous_state(mutation):
    value = record()
    raw = json.loads(encode_application_continuity_record(value))
    closure = raw["managedClosures"][0]
    if mutation == "list_not_tuple":
        with pytest.raises(ValueError):
            replace(value, managed_closures=list(value.managed_closures))
        return
    if mutation == "missing_field":
        del raw["managedClosures"]
    elif mutation == "unknown_field":
        raw["unknown"] = True
    elif mutation == "duplicate_key":
        payload = encode_application_continuity_record(value)
        payload = payload.replace(b'"phase":', b'"phase":"closed","phase":')
        with pytest.raises(ApplicationContinuityError):
            decode_application_continuity_record(payload)
        return
    elif mutation == "duplicate_record":
        raw["managedClosures"].append(dict(closure))
    elif mutation == "duplicate_target":
        raw["managedClosures"].append(dict(closure, operationId="e" * 32))
    elif mutation == "unknown_creation":
        closure["creationOperationId"] = "f" * 32
    elif mutation == "name_mismatch":
        closure["name"] = "other"
    elif mutation == "mux_mismatch":
        closure["muxSpaceId"] = "other"
    elif mutation == "invalid_phase":
        closure["phase"] = "stop_requested"
    elif mutation == "authority":
        closure["authority"] = "secret"
    elif mutation == "missing_pending_mux":
        raw["muxSpaces"] = []
    elif mutation == "retained_closed_mux":
        closure["phase"] = "closed"
    elif mutation == "aliased_operation":
        closure["operationId"] = raw["managedCreations"][0]["operationId"]
    with pytest.raises(ApplicationContinuityError):
        decode_application_continuity_record(json.dumps(raw).encode())


def test_old_closed_mux_does_not_forbid_different_mux_reusing_name():
    value = record(closed=True)
    creation = ManagedMuxCreatedV1("e" * 32, "f" * 32, "dev", "mux-new")
    new_mux = replace(_record().mux_spaces[0], mux_space_id=creation.mux_space_id)
    value = replace(value, managed_creations=(*value.managed_creations, creation), mux_spaces=(new_mux,))
    assert decode_application_continuity_record(encode_application_continuity_record(value)) == value


@pytest.mark.parametrize("alias", ["other_close", "other_creation"])
def test_close_operation_is_unique_across_independently_valid_targets(alias):
    value = record(closed=True)
    creation = ManagedMuxCreatedV1("e" * 32, "b" * 32, "other", "mux-other")
    closure = replace(value.managed_closures[0], operation_id="f" * 32,
                      creation_operation_id=creation.operation_id,
                      name=creation.name, mux_space_id=creation.mux_space_id)
    value = replace(value, managed_creations=(*value.managed_creations, creation),
                    managed_closures=(*value.managed_closures, closure))
    encoded = encode_application_continuity_record(value)
    assert decode_application_continuity_record(encoded) == value
    raw = json.loads(encoded)
    raw["managedClosures"][1]["operationId"] = (
        value.managed_closures[0].operation_id if alias == "other_close"
        else value.managed_creations[0].operation_id
    )
    with pytest.raises(ApplicationContinuityError):
        decode_application_continuity_record(json.dumps(raw).encode())


def test_close_history_is_bounded_before_encoding_and_still_obeys_byte_limit(monkeypatch):
    from loushang.appservice import continuity

    original = record(closed=True)
    creations = tuple(
        ManagedMuxCreatedV1(f"{index:032x}", "b" * 32, "dev", f"mux-{index}")
        for index in range(continuity.MAX_MANAGED_CLOSURES)
    )
    closures = tuple(
        replace(original.managed_closures[0], operation_id=f"{index + 65536:032x}",
                creation_operation_id=creation.operation_id, mux_space_id=creation.mux_space_id)
        for index, creation in enumerate(creations)
    )
    maximum = replace(original, managed_creations=creations, managed_closures=closures)
    assert len(maximum.managed_closures) == continuity.MAX_MANAGED_CLOSURES
    with pytest.raises(ApplicationContinuityError):
        encode_application_continuity_record(maximum)
    # Independently exercise the closure-count limit with otherwise valid history.
    monkeypatch.setattr(continuity, "MAX_MANAGED_CLOSURES", 2)
    with pytest.raises(ValueError, match="closure history"):
        replace(original, managed_creations=creations[:3], managed_closures=closures[:3])


def test_absent_mux_without_close_fact_does_not_invent_settlement():
    value = replace(record(closed=True), managed_closures=())
    restored = decode_application_continuity_record(encode_application_continuity_record(value))
    assert restored.managed_creations and not restored.mux_spaces and not restored.managed_closures


def test_real_store_reopens_pending_and_closed_without_losing_identity(tmp_path):
    from loushang.appservice import JsonFileApplicationContinuityStoreV1

    async def scenario():
        store = JsonFileApplicationContinuityStoreV1(tmp_path / "continuity")
        pending = record()
        closed = replace(record(closed=True), record_revision=2)
        first = await store.acquire(application_id=pending.application_id, owner_epoch="first")
        try:
            await first.commit(expected_revision=None, record=pending)
        finally:
            await first.close()
        second = await store.acquire(application_id=pending.application_id, owner_epoch="second")
        try:
            assert await second.load() == pending
            await second.commit(expected_revision=1, record=closed)
        finally:
            await second.close()
        third = await store.acquire(application_id=pending.application_id, owner_epoch="third")
        try:
            assert await third.load() == closed
        finally:
            await third.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("version", [APPLICATION_CONTINUITY_VERSION, MANAGED_CONTINUITY_VERSION])
def test_close_record_cannot_be_downgraded_by_version_tag(version):
    raw = json.loads(encode_application_continuity_record(record()))
    raw["contractVersion"] = version
    with pytest.raises(ApplicationContinuityError):
        decode_application_continuity_record(json.dumps(raw).encode())


@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("closed", [False, True])
def test_unactivated_close_recovery_rejects_before_any_session_open(managed, closed):
    async def scenario():
        events = []
        admissions = []
        value = record(closed=closed)
        if closed:
            # Retain an unrelated active Mux so accidental recovery calls the resolver.
            creation = ManagedMuxCreatedV1("e" * 32, "f" * 32, "other", "mux-other")
            mux = replace(_record().mux_spaces[0], mux_space_id="mux-other", name="other")
            value = replace(value, managed_creations=(*value.managed_creations, creation), mux_spaces=(mux,))
        lease = _MemoryLease(decode_application_continuity_record(encode_application_continuity_record(value)))
        attempt = create_appservice_recovery_attempt(AppServiceRecoveryRequestV1(
            "coding", _Resolver(events), lease, managed_mux=_binding(admissions) if managed else None,
        ))
        try:
            with pytest.raises(AppServiceError) as error:
                await attempt.open()
            assert error.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
            assert not events and not admissions and not lease.commits
        finally:
            await attempt.close()

    asyncio.run(scenario())
