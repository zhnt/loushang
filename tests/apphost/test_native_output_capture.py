import os
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256

import pytest

from loushang.apphost.managed._capture_native import NativeOutputCapture
from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.storage_budget import ManagedStorageBudgetV1

from .test_managed_files import directory as directory
from .test_managed_storage_budget import allocation
from .test_managed_storage_budget import namespace as namespace
from .test_managed_storage_budget import pytestmark as pytestmark
from .test_managed_storage_budget import registry as registry


def capture(registry, directory):
    root, owner = directory
    requests = tuple(replace(
        allocation(registry, kind="temporary", slot=slot, size=4096, instance="a" * 32),
        root_key=sha256(os.fsencode(root)).hexdigest(), root_identity=owner._identity,
    ) for slot in (0, 1))
    return NativeOutputCapture(owner, ManagedStorageBudgetV1(registry), requests)


def test_two_stream_capture_reads_sealed_output_then_deletes_and_refunds(registry, directory):
    root, owner = directory
    storage = capture(registry, directory)
    assert not storage.cleanup_pending
    assert storage.prepare()
    storage.append(0, b"hello")
    storage.append(1, b"warning")
    first, second = storage.seal()
    assert (first.size, second.size) == (5, 7)
    assert storage.read(0, max_bytes=5) == b"hello"
    assert storage.read(1, max_bytes=7) == b"warning"
    storage.close()
    storage.close()
    assert not storage.cleanup_pending and not owner.cleanup_pending
    assert all(storage.budget.lookup(request) is None for request in storage.allocations)
    assert list(root.iterdir()) == [root / "capture.lock"]


def test_retention_overflow_is_sticky_for_both_streams_but_cleanup_refunds(registry, directory):
    storage = capture(registry, directory)
    assert storage.prepare()
    storage.append(0, b"x" * 4096)
    storage.append(0, b"overflow")
    storage.append(1, b"must not be retained")
    assert storage.snapshots[1].size == 0
    assert storage.seal() is None
    with pytest.raises(ManagedStorageError, match="closed"):
        storage.read(0, max_bytes=4096)
    storage.close()
    assert not storage.cleanup_pending
    assert all(storage.budget.lookup(request) is None for request in storage.allocations)


def test_bind_failure_keeps_original_create_for_close_retry(registry, directory, monkeypatch):
    storage = capture(registry, directory)
    original = storage.budget.bind_file
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls == 1:
            raise OSError("bind committed but receipt lost")
        return result

    monkeypatch.setattr(storage.budget, "bind_file", fail_once)
    with pytest.raises(ManagedStorageError, match="unavailable"):
        storage.prepare()
    assert storage.cleanup_pending
    storage.close()
    assert not storage.cleanup_pending
    assert all(storage.budget.lookup(request) is None for request in storage.allocations)


def test_registration_validation_and_fence_failure_keep_original_attempt(registry, directory, monkeypatch):
    _, owner = directory
    storage = capture(registry, directory)
    original_fence = owner.fence_data_creation

    def validation_failure(*args, **kwargs):
        raise ManagedStorageError("conflict")

    def fence_failure(*args, **kwargs):
        raise ManagedStorageError("busy")

    with monkeypatch.context() as patch:
        patch.setattr(storage.budget, "_creation_attempt_target", validation_failure)
        patch.setattr(owner, "fence_data_creation", fence_failure)
        with pytest.raises(ManagedStorageError):
            storage.prepare()
        assert storage.attempt is not None and storage.cleanup_pending
        with pytest.raises(ManagedStorageError, match="busy"):
            storage.close()
        assert storage.cleanup_pending and not storage.closed
    original_pair = storage.attempt.creations
    storage.close()
    assert storage.attempt.creations is original_pair and not storage.cleanup_pending
    assert all(original_fence(creation, binding=storage.attempt) for creation in original_pair)


def test_last_refund_receipt_loss_retries_without_native_lock(registry, directory, monkeypatch):
    storage = capture(registry, directory)
    storage.prepare()
    original = storage.budget._database.transaction
    original_release = storage.budget.release_temporary
    calls = 0

    @contextmanager
    def lost_receipt(**kwargs):
        with original(**kwargs) as connection:
            yield connection
        raise OSError("refund committed but receipt lost")

    def lose_second(binding, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            with monkeypatch.context() as patch:
                patch.setattr(storage.budget._database, "transaction", lost_receipt)
                return original_release(binding, **kwargs)
        return original_release(binding, **kwargs)

    monkeypatch.setattr(storage.budget, "release_temporary", lose_second)
    with pytest.raises(OSError):
        storage.close()
    assert storage.deleted == [True, True] and storage.cleanup_pending

    def unexpected(*args, **kwargs):
        raise AssertionError("only original accounting may be retried")

    monkeypatch.setattr(storage.owner, "lock", unexpected)
    storage.close()
    assert not storage.cleanup_pending
