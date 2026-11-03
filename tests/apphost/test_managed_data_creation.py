import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import FrozenInstanceError
from threading import Event
from time import monotonic

import pytest

from loushang.apphost.managed._files import ManagedStorageError, PrivateManagedDirectory

from .test_managed_files import pytestmark as pytestmark


def ids(first):
    return tuple(f"74656d7000000000{value:016x}" for value in (first, first + 1))


def test_fence_prevents_late_create_and_reissuing_same_pair(tmp_path):
    owner = PrivateManagedDirectory(tmp_path / "private", create=True)
    binding = object()
    try:
        first, second = owner.prepare_data_creation_pair(ids(1), capacity=4096, binding=binding)
        assert owner.cleanup_pending
        assert owner.fence_data_creation(first, binding=binding)
        assert owner.cleanup_pending
        with owner.lock("data.lock", create=True):
            with pytest.raises(ManagedStorageError, match="conflict"):
                owner.create_data(first, binding=binding)
            snapshot = owner.create_data(second, binding=binding)
        assert snapshot.size == 0
        assert not owner.cleanup_pending
        assert not owner.fence_data_creation(second, binding=binding)
        assert not (tmp_path / "private" / first.name).exists()
        assert (tmp_path / "private" / second.name).exists()
        with pytest.raises(ManagedStorageError, match="conflict"):
            owner.prepare_data_creation_pair(ids(1), capacity=4096, binding=binding)
    finally:
        owner.close()


def test_pair_capacity_refusal_has_no_partial_registration(tmp_path):
    owner = PrivateManagedDirectory(tmp_path / "private", create=True)
    binding = object()
    creations = []
    try:
        for first in (1, 3, 5, 7):
            creations.extend(owner.prepare_data_creation_pair(ids(first), capacity=4096, binding=binding))
        with pytest.raises(ManagedStorageError, match="capacity"):
            owner.prepare_data_creation_pair(ids(9), capacity=4096, binding=binding)
        assert len(owner._creations) == 8 and owner._creation_high_water == ids(7)[1]
        for creation in creations:
            owner.fence_data_creation(creation, binding=binding)
        assert not owner.cleanup_pending
        pair = owner.prepare_data_creation_pair(ids(9), capacity=4096, binding=binding)
        for creation in pair:
            owner.fence_data_creation(creation, binding=binding)
    finally:
        owner.close()


def test_creation_requires_original_owner_and_binding_before_native_io(tmp_path):
    owner = PrivateManagedDirectory(tmp_path / "private", create=True)
    other = PrivateManagedDirectory(tmp_path / "other", create=True)
    binding = object()
    pair = owner.prepare_data_creation_pair(ids(1), capacity=4096, binding=binding)
    try:
        for destination, credential in ((owner, object()), (other, binding)):
            with pytest.raises(ManagedStorageError, match="conflict"):
                destination.create_data(pair[0], binding=credential)
            with pytest.raises(ManagedStorageError, match="conflict"):
                destination.fence_data_creation(pair[0], binding=credential)
        assert pair[0].phase == "new"
        with pytest.raises(ManagedStorageError, match="busy"):
            owner.close()
        assert not owner._closing
    finally:
        for creation in pair:
            owner.fence_data_creation(creation, binding=binding)
        owner.close()
        other.close()


def test_frozen_native_target_requires_original_fence_completion(tmp_path):
    owner = PrivateManagedDirectory(tmp_path / "private", create=True)
    binding = object()
    first, second = owner.prepare_data_creation_pair(ids(1), capacity=4096, binding=binding)
    try:
        target = owner.creation_target(first, binding=binding)
        assert target.allocation_id == ids(1)[0] and target.name == first.name
        assert target.root_identity == owner._identity and target.capacity == 4096
        with pytest.raises(FrozenInstanceError):
            target.capacity = 8192
        with pytest.raises(ManagedStorageError, match="unavailable"):
            owner.creation_target(first, binding=binding, require_fenced=True)
        owner.fence_data_creation(first, binding=binding)
        assert owner.creation_target(first, binding=binding, require_fenced=True) is target
        with pytest.raises(ManagedStorageError, match="unavailable"):
            owner.creation_target(second, binding=binding, require_fenced=True)
        with pytest.raises(ManagedStorageError, match="conflict"):
            owner.creation_target(first, binding=object(), require_fenced=True)
    finally:
        owner.fence_data_creation(first, binding=binding)
        owner.fence_data_creation(second, binding=binding)
        owner.close()


@pytest.mark.parametrize("expired", [True, False])
def test_creation_registration_deadline_covers_mutex(tmp_path, monkeypatch, expired):
    owner = PrivateManagedDirectory(tmp_path / "private", create=True)
    calls = []

    class HeldMutex:
        def acquire(self, *, timeout):
            calls.append(timeout)
            assert 0 <= timeout <= 1
            return False

    try:
        with monkeypatch.context() as patch:
            patch.setattr(owner, "_mutex", HeldMutex())
            with pytest.raises(ManagedStorageError, match="busy"):
                owner.prepare_data_creation_pair(ids(1), capacity=4096, binding=object(),
                                                 deadline=monotonic() + (-1 if expired else 1))
        assert len(calls) == (0 if expired else 1)
        assert not owner._creations and not owner._creation_high_water
    finally:
        owner.close()


def test_unknown_creation_cannot_be_fenced_or_replayed(tmp_path, monkeypatch):
    owner = PrivateManagedDirectory(tmp_path / "private", create=True)
    binding = object()
    first, second = owner.prepare_data_creation_pair(ids(1), capacity=4096, binding=binding)
    original = owner.append_data

    def lost_receipt(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("lost creation receipt")

    try:
        monkeypatch.setattr(owner, "append_data", lost_receipt)
        with owner.lock("data.lock", create=True):
            with pytest.raises(OSError):
                owner.create_data(first, binding=binding)
            with pytest.raises(ManagedStorageError, match="conflict"):
                owner.create_data(first, binding=binding)
        assert not owner.fence_data_creation(first, binding=binding)
        assert owner.fence_data_creation(second, binding=binding)
        assert owner.cleanup_pending and (tmp_path / "private" / first.name).exists()
        with pytest.raises(ManagedStorageError, match="unavailable"):
            owner.close()
        assert owner._fd is None and owner.cleanup_pending
    finally:
        with suppress(ManagedStorageError):
            owner.close()


def test_fence_wins_against_queued_native_worker(tmp_path, monkeypatch):
    owner = PrivateManagedDirectory(tmp_path / "private", create=True)
    binding = object()
    first, second = owner.prepare_data_creation_pair(ids(1), capacity=4096, binding=binding)
    entered = Event()

    def create():
        entered.set()
        return owner.create_data(first, binding=binding)

    def unexpected(*args, **kwargs):
        raise AssertionError("fenced worker reached native creation")

    try:
        monkeypatch.setattr(owner, "append_data", unexpected)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with owner._mutex:
                future = pool.submit(create)
                assert entered.wait(5)
                assert owner.fence_data_creation(first, binding=binding)
            with pytest.raises(ManagedStorageError, match="conflict"):
                future.result(timeout=5)
        assert not (tmp_path / "private" / first.name).exists()
    finally:
        owner.fence_data_creation(first, binding=binding)
        owner.fence_data_creation(second, binding=binding)
        owner.close()


def test_native_admission_wins_against_concurrent_fence(tmp_path, monkeypatch):
    owner = PrivateManagedDirectory(tmp_path / "private", create=True)
    binding = object()
    first, second = owner.prepare_data_creation_pair(ids(1), capacity=4096, binding=binding)
    admitted, fence_entered, resume = Event(), Event(), Event()
    original = owner.append_data

    def paused_append(*args, **kwargs):
        admitted.set()
        assert resume.wait(5)
        return original(*args, **kwargs)

    def create():
        with owner.lock("data.lock", create=True):
            return owner.create_data(first, binding=binding)

    def fence():
        fence_entered.set()
        return owner.fence_data_creation(first, binding=binding)

    try:
        monkeypatch.setattr(owner, "append_data", paused_append)
        with ThreadPoolExecutor(max_workers=2) as pool:
            creating = pool.submit(create)
            try:
                assert admitted.wait(5)
                fencing = pool.submit(fence)
                assert fence_entered.wait(5)
                assert not fencing.done()
            finally:
                resume.set()
            assert creating.result(timeout=5).size == 0
            assert fencing.result(timeout=5) is False
        assert first._completion is None
        assert owner.cleanup_pending  # The other stream still needs settlement.
    finally:
        resume.set()
        owner.fence_data_creation(second, binding=binding)
        owner.close()


def test_creation_close_receipt_loss_never_closes_reused_descriptor(tmp_path, monkeypatch):
    root = tmp_path / "private"
    owner = PrivateManagedDirectory(root, create=True)
    binding = object()
    first, second = owner.prepare_data_creation_pair(ids(1), capacity=4096, binding=binding)
    original_close = os.close
    reused, attempts = [], []

    def lost_close(fd):
        attempts.append(fd)
        original_close(fd)
        if first.phase == "admitted" and not reused:
            replacement = os.open(root / "unrelated", os.O_CREAT | os.O_RDWR, 0o600)
            if replacement != fd:
                os.dup2(replacement, fd)
                original_close(replacement)
            reused.append(fd)
            raise OSError("close succeeded but receipt was lost")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "close", lost_close)
            with owner.lock("data.lock", create=True):
                with pytest.raises(ManagedStorageError, match="unavailable"):
                    owner.create_data(first, binding=binding)
            assert first.phase == "unknown" and not owner.fence_data_creation(first, binding=binding)
            owner.fence_data_creation(second, binding=binding)
            for _ in range(2):
                with pytest.raises(ManagedStorageError, match="unavailable"):
                    owner.close()
            assert len(reused) == 1 and attempts.count(reused[0]) == 1
            os.write(reused[0], b"still test-owned")
        assert (root / "unrelated").read_bytes() == b"still test-owned"
        assert (root / first.name).exists() and owner.cleanup_pending
    finally:
        for fd in reused:
            original_close(fd)
        owner.fence_data_creation(second, binding=binding)
        with suppress(ManagedStorageError):
            owner.close()
