from __future__ import annotations

import asyncio
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread
from time import monotonic

import pytest

from loushang.apphost.managed import event_log as event_module
from loushang.apphost.managed._files import ManagedStorageError, PrivateManagedDirectory
from loushang.apphost.managed.event_log import (
    ManagedLifecycleEventV1,
    ManagedLifecycleLogV1,
)
from loushang.apphost.managed.storage_budget import ManagedStorageBudgetV1

from . import test_managed_registry as fixtures
from . import test_managed_storage_budget as budget_fixtures

registry = fixtures.registry
namespace = fixtures.namespace
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed logs")


@pytest.fixture
def log(registry, tmp_path):
    request = fixtures.intent()
    registry.reserve_mux(request)
    directory = PrivateManagedDirectory(tmp_path / "logs", create=True)
    writer = ManagedLifecycleLogV1(directory, ManagedStorageBudgetV1(registry),
                                   request.service.service_id, segment_bytes=256)
    try:
        yield writer, directory, request.service.service_id
    finally:
        directory.close()


def event(instance="a" * 32):
    return ManagedLifecycleEventV1("ready", instance)


def test_explicit_deadline_reaches_every_registry_admission(log, monkeypatch):
    writer, _, _ = log
    deadline = monotonic() + 5
    calls = []
    for name in ("lookup", "reserve", "bind_file"):
        original = getattr(writer._budget, name)
        def checked(*args, _name=name, _original=original, **kwargs):
            assert kwargs["deadline"] == deadline
            assert kwargs["wait_for_lock"] is True
            calls.append(_name)
            return _original(*args, **kwargs)
        monkeypatch.setattr(writer._budget, name, checked)
    assert writer.write(event(), deadline=deadline) == 1
    assert calls == ["lookup"] * 5 + ["reserve", "bind_file"]


def test_mutex_timeout_has_no_native_effect_and_does_not_seal(log):
    writer, directory, _ = log
    held, release = Event(), Event()
    def hold():
        with directory._mutex:
            held.set()
            release.wait(10)
    holder = Thread(target=hold)
    holder.start()
    try:
        assert held.wait(5)
        with pytest.raises(ManagedStorageError, match="busy"):
            writer.write(event(), deadline=monotonic() + 0.05)
        assert holder.is_alive() and not release.is_set()
        assert not writer._failed
        assert not tuple(directory._root.iterdir())
    finally:
        release.set()
        holder.join(5)
    assert not holder.is_alive()
    assert writer.write(event(), deadline=monotonic() + 5) == 1


def test_events_rotate_reopen_and_remain_charged(log, registry):
    writer, directory, service_id = log
    identities = {}
    for index in range(25):
        assert writer.write(event()) == index + 1
        for path in directory._root.glob("*.jsonl"):
            if path.name in identities:
                assert identities[path.name] == path.stat().st_ino
            identities[path.name] = path.stat().st_ino
            assert path.stat().st_size <= 256
    assert len(identities) == 5
    with registry._database.transaction() as connection:
        assert connection.execute("SELECT count(*),sum(capacity) FROM storage_allocations").fetchone() == (5, 50 * 1024**2)
    for service in (1, 2, 3):
        for slot in range(5):
            writer._budget.reserve(budget_fixtures.allocation(registry, service=service, slot=slot))
    with registry._database.transaction() as connection:
        assert connection.execute("SELECT sum(capacity) FROM storage_allocations").fetchone() == (200 * 1024**2,)
    reopened = ManagedLifecycleLogV1(directory, ManagedStorageBudgetV1(registry), service_id,
                                     segment_bytes=256)
    assert reopened.write(event("b" * 32)) == 26
    values = [json.loads(line) for path in directory._root.glob("*.jsonl")
              for line in path.read_bytes().splitlines()]
    assert max(row["sequence"] for row in values) == 26
    assert {path.name for path in directory._root.iterdir()} == {"lifecycle.lock", *identities}
    for index in range(26, 40):
        assert reopened.write(event()) == index + 1
    assert {path.name: path.stat().st_ino for path in directory._root.glob("*.jsonl")} == identities


@pytest.mark.parametrize("name,instance,code", [("secret text", "a" * 32, None),
    ("ready", "token-value", None), ("ready", "a" * 32, "raw exception"),
    (True, "a" * 32, None)])
def test_invalid_event_has_no_io(log, name, instance, code):
    _, directory, _ = log
    with pytest.raises(ValueError):
        ManagedLifecycleEventV1(name, instance, code)
    assert not tuple(directory._root.iterdir())


@pytest.mark.parametrize("damage", ["unknown", "partial", "missing", "unbound", "extra-field"])
def test_unknown_entries_or_bad_bound_state_never_repaired(log, registry, damage):
    writer, directory, service_id = log
    writer.write(event())
    path = directory._root / "lifecycle-0.jsonl"
    if damage == "unknown":
        (directory._root / "stranger").touch(mode=0o600)
    elif damage == "partial":
        with path.open("ab") as stream:
            stream.write(b"partial")
    elif damage == "missing":
        path.unlink()
    elif damage == "unbound":
        with registry._database.transaction(write=True) as connection:
            connection.execute("UPDATE storage_allocations SET file_device=NULL,file_inode=NULL")
    else:
        row = json.loads(path.read_bytes())
        row["message"] = "private arbitrary text"
        path.write_bytes(json.dumps(row).encode() + b"\n")
    before = {item.name: item.read_bytes() for item in directory._root.iterdir()}
    reopened = ManagedLifecycleLogV1(directory, ManagedStorageBudgetV1(registry), service_id,
                                     segment_bytes=256)
    with pytest.raises(ManagedStorageError):
        reopened.write(event())
    assert {item.name: item.read_bytes() for item in directory._root.iterdir()} == before
    with pytest.raises(ManagedStorageError, match="closed"):
        reopened.write(event())


def test_bind_receipt_loss_does_not_replay_event(log, registry, monkeypatch):
    writer, directory, service_id = log
    original = writer._budget.bind_file

    def lost(*args, **kwargs):
        original(*args, **kwargs)
        raise ManagedStorageError("unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(writer._budget, "bind_file", lost)
        with pytest.raises(ManagedStorageError):
            writer.write(event())
    assert (directory._root / "lifecycle-0.jsonl").read_bytes() == b""
    with pytest.raises(ManagedStorageError, match="closed"):
        writer.write(event())
    # A new admitted writer can use a bound empty file, but this is a new event.
    reopened = ManagedLifecycleLogV1(directory, ManagedStorageBudgetV1(registry), service_id,
                                     segment_bytes=256)
    assert reopened.write(event("b" * 32)) == 1


def test_lifecycle_preserves_fixed_trace_entries_in_shared_directory(log):
    writer, directory, _ = log
    for _ in range(25):
        writer.write(event())
    # Foreign-format contents belong to the trace consumer. Lifecycle must
    # neither parse, modify nor adopt their accounting, even if malformed.
    trace = {name: ("trace-owned:" + name).encode() for name in
             ("trace.lock", "trace-0.jsonl", "trace-1.jsonl")}
    for name, content in trace.items():
        path = directory._root / name
        path.write_bytes(content)
        path.chmod(0o600)
    assert len(tuple(directory._root.iterdir())) == 9
    assert writer.write(event()) == 26
    assert writer.read_tail()[-1].sequence == 26
    assert {name: (directory._root / name).read_bytes() for name in trace} == trace


@pytest.mark.parametrize("name", ["trace-2.jsonl", "trace-secret.jsonl", "trace.lock.backup"])
def test_trace_coexistence_does_not_allow_extra_names(log, name):
    writer, directory, _ = log
    writer.write(event())
    path = directory._root / name
    path.write_bytes(b"foreign")
    path.chmod(0o600)
    before = (directory._root / "lifecycle-0.jsonl").read_bytes()
    with pytest.raises(ManagedStorageError, match="invalid_record"):
        writer.write(event())
    assert (directory._root / "lifecycle-0.jsonl").read_bytes() == before


def test_partial_event_seals_writer_without_retrying(log, monkeypatch):
    writer, directory, _ = log
    writer.write(event())
    native = os.write
    calls = []

    def short(fd, data):
        calls.append(1)
        if len(calls) == 1:
            return native(fd, data[:3])
        raise OSError("private error")

    with monkeypatch.context() as patch:
        patch.setattr(os, "write", short)
        with pytest.raises(ManagedStorageError):
            writer.write(event())
    before = (directory._root / "lifecycle-0.jsonl").read_bytes()
    with pytest.raises(ManagedStorageError, match="closed"):
        writer.write(event())
    directory.close()
    assert (directory._root / "lifecycle-0.jsonl").read_bytes() == before


@pytest.mark.parametrize("stage", ["reserve", "create"])
def test_unbound_reservation_never_authorizes_recreation(log, registry, monkeypatch, stage):
    writer, directory, service_id = log
    target = writer._budget if stage == "reserve" else directory
    name = "reserve" if stage == "reserve" else "append_data"
    original = getattr(target, name)

    def lost(*args, **kwargs):
        original(*args, **kwargs)
        raise ManagedStorageError("unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(target, name, lost)
        with pytest.raises(ManagedStorageError):
            writer.write(event())
    before = {path.name: path.read_bytes() for path in directory._root.iterdir()}
    reopened = ManagedLifecycleLogV1(directory, ManagedStorageBudgetV1(registry), service_id,
                                     segment_bytes=256)
    with pytest.raises(ManagedStorageError, match="conflict"):
        reopened.write(event())
    assert {path.name: path.read_bytes() for path in directory._root.iterdir()} == before
    with registry._database.transaction() as connection:
        assert connection.execute("SELECT count(*),sum(capacity) FROM storage_allocations").fetchone() == (1, 10 * 1024**2)


@pytest.mark.parametrize("value", [True, 0, 2**63 - 1, 2**63])
def test_bad_or_exhausted_tail_sequence_never_writes(log, value):
    writer, directory, _ = log
    writer.write(event())
    path = directory._root / "lifecycle-0.jsonl"
    row = json.loads(path.read_bytes())
    row["sequence"] = value
    path.write_bytes(json.dumps(row, separators=(",", ":")).encode() + b"\n")
    before = path.read_bytes()
    with pytest.raises(ManagedStorageError):
        writer.write(event())
    assert path.read_bytes() == before


def test_duplicate_tail_sequence_never_selects_a_winner(log):
    writer, directory, _ = log
    for _ in range(3):
        writer.write(event())
    first = directory._root / "lifecycle-0.jsonl"
    second = directory._root / "lifecycle-1.jsonl"
    second.write_bytes(first.read_bytes().splitlines(keepends=True)[-1])
    before = {path.name: path.read_bytes() for path in directory._root.iterdir()}
    with pytest.raises(ManagedStorageError, match="invalid_record"):
        writer.write(event())
    assert {path.name: path.read_bytes() for path in directory._root.iterdir()} == before


def test_exclusive_reservation_cannot_claim_existing_unbound_row(log):
    writer, directory, _ = log
    allocation = writer._allocation(0)
    first = writer._budget.reserve(allocation, exclusive=True)
    with pytest.raises(ManagedStorageError, match="conflict"):
        writer._budget.reserve(allocation, exclusive=True)
    assert writer._budget.reserve(allocation) == first
    assert not tuple(directory._root.iterdir())


def test_concurrent_waiter_observes_writer_sealed_by_lost_bind(log, monkeypatch):
    writer, directory, _ = log
    entered, second_validated = Event(), Event()
    original_bind, original_encode = writer._budget.bind_file, event_module._encode

    def encode(value, sequence):
        result = original_encode(value, sequence)
        if value.instance_id == "b" * 32:
            second_validated.set()
        return result

    def bind(*args, **kwargs):
        original_bind(*args, **kwargs)
        entered.set()
        assert second_validated.wait(5)
        raise ManagedStorageError("unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(event_module, "_encode", encode)
        patch.setattr(writer._budget, "bind_file", bind)
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(writer.write, event())
            assert entered.wait(5)
            second = executor.submit(writer.write, event("b" * 32))
            with pytest.raises(ManagedStorageError, match="unavailable"):
                first.result(timeout=5)
            with pytest.raises(ManagedStorageError, match="closed"):
                second.result(timeout=5)
    assert (directory._root / "lifecycle-0.jsonl").read_bytes() == b""


@pytest.mark.parametrize("value", [None, "private text", {"event": "ready"}])
def test_write_invalid_type_has_zero_io(log, value):
    writer, directory, _ = log
    with pytest.raises(ValueError):
        writer.write(value)
    assert not tuple(directory._root.iterdir())


@pytest.mark.parametrize("overfull", [False, True])
def test_scan_close_unknown_stays_with_original_directory(tmp_path, monkeypatch, overfull):
    root = tmp_path / "scan"
    owner = PrivateManagedDirectory(root, create=True)
    if overfull:
        for index in range(2):
            (root / str(index)).touch(mode=0o600)
    original = os.scandir
    closes = []

    class LostClose:
        def __init__(self, fd):
            self.native = original(fd)

        def __iter__(self):
            return iter(self.native)

        def close(self):
            closes.append(1)
            self.native.close()
            raise OSError("private lost close receipt")

    with monkeypatch.context() as patch:
        patch.setattr(os, "scandir", LostClose)
        with pytest.raises(ManagedStorageError, match="capacity" if overfull else "unavailable"):
            owner.names(limit=1)
    assert owner.cleanup_pending
    with pytest.raises(ManagedStorageError, match="busy"):
        owner.names(limit=1)
    for _ in range(2):
        with pytest.raises(ManagedStorageError, match="unavailable"):
            owner.close()
        assert owner.cleanup_pending
    assert closes == [1]


def test_running_loop_is_rejected_before_native_mutex(log):
    writer, directory, _ = log
    entered, release = Event(), Event()

    def holder():
        with directory._mutex:
            entered.set()
            assert release.wait(5)

    async def call():
        try:
            with pytest.raises(ManagedStorageError, match="busy"):
                writer.write(event())
        finally:
            release.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        held = executor.submit(holder)
        assert entered.wait(5)
        asyncio.run(call())
        held.result(timeout=5)
    assert not writer._failed and not tuple(directory._root.iterdir())
