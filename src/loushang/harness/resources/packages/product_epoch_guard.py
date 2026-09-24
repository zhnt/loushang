"""Product transaction guard paired with the Package cutover coordination lock."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Protocol

from loushang.harness.journal import journal_file_lock
from loushang.harness.journal._rooted_io import RootedFileIO
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
    PackageEpochFenceReceiptV1,
    PackageEpochRuntimeAdmissionRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
    PackageEpochRuntimeLeaseHandle,
    PackageEpochRuntimeLeaseRegistry,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_pre_fence_registration import (
    PackagePosixPreFenceRegistrationError,
    PackagePosixPreFenceRegistrationOwner,
)
from loushang.harness.resources.packages.product_pre_b_snapshot import (
    PackagePosixEpochCutoverResultV1,
    reopen_posix_product_cutover,
)

_SAFE_STORE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")


class PackageProductLegacyPreFenceAdmissionError(RuntimeError):
    """Product-facing refusal for a fenced or concurrent old runtime launch."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class PackageProductLegacyRuntimeRegistration(Protocol):
    def release(self) -> None: ...


@dataclass(frozen=True, slots=True)
class PackageProductRuntimeLease:
    """Keep one exact Product runtime admission live until Session disposal."""

    registry: PackageEpochRuntimeLeaseRegistry
    admission_request: PackageEpochRuntimeAdmissionRequestV1
    _handle: PackageEpochRuntimeLeaseHandle = field(repr=False, compare=False)

    def release(self) -> None:
        self._handle.release()

    def __enter__(self) -> PackageProductRuntimeLease:
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


class PackageProductPosixFencedRuntimeOwner:
    """Retain the rooted control authority and lease registry after B cutover.

    The application must stop creating Sessions and release their leases before
    closing this owner. An active lease refuses close so the root fd stays live.
    """

    def __init__(
        self,
        *,
        cutover_result: PackagePosixEpochCutoverResultV1,
        registry: PackageEpochRuntimeLeaseRegistry,
        file_io: RootedFileIO,
        root_fd: int,
        authority_root: Path,
        epochs_root_name: str,
    ) -> None:
        self.cutover_result = cutover_result
        self.registry = registry
        self._file_io = file_io
        self._root_fd = root_fd
        self._authority_root = authority_root
        self._epochs_root_name = epochs_root_name
        self._closed = False
        self._close_lock = Lock()

    @classmethod
    def open(
        cls,
        *,
        authority_root: Path,
        control_root: Path,
        store_id: str,
        epochs_root_name: str,
    ) -> PackageProductPosixFencedRuntimeOwner:
        """Reopen only the current durable fence and its private control root."""

        if (
            not isinstance(control_root, Path)
            or not control_root.is_absolute()
            or ".." in control_root.parts
        ):
            raise ValueError("Package Product control root is invalid")
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        descriptor = os.open(control_root, flags)
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) & 0o077
                or metadata.st_uid != os.geteuid()
            ):
                raise ValueError("Package Product control root is not private")
            cutover = reopen_posix_product_cutover(
                authority_root=authority_root,
                control_root=control_root,
                store_id=store_id,
                epochs_root_name=epochs_root_name,
            )
            visible = control_root.lstat()
            if (visible.st_dev, visible.st_ino) != (
                metadata.st_dev,
                metadata.st_ino,
            ):
                raise ValueError("Package Product control root changed")
            file_io = RootedFileIO(control_root, descriptor)
            fences = PackageEpochFenceJournal(control_root / "epoch.jsonl")
            registry = PackageEpochRuntimeLeaseRegistry(
                path=control_root / "runtime-leases.jsonl",
                coordination_lock=control_root / "coordination",
                file_io=file_io,
                fences=fences,
                store_id=store_id,
            )
            if fences.current(store_id) != cutover.fence:
                raise ValueError("Package Product epoch changed during open")
            return cls(
                cutover_result=cutover,
                registry=registry,
                file_io=file_io,
                root_fd=descriptor,
                authority_root=authority_root,
                epochs_root_name=epochs_root_name,
            )
        except BaseException:
            os.close(descriptor)
            raise

    def assert_current(self) -> None:
        with self._close_lock:
            self._assert_current_unlocked()

    @property
    def control_root(self) -> Path:
        return self._file_io.root

    def prepare_product_state_root(self) -> Path:
        """Create the B Product journal root only after the fence is selected."""

        with self._close_lock:
            self._assert_current_unlocked()
            name = "product-state"
            try:
                os.mkdir(name, mode=0o700, dir_fd=self._root_fd)
            except FileExistsError:
                pass
            else:
                os.chmod(
                    name, 0o700, dir_fd=self._root_fd, follow_symlinks=False
                )
                os.fsync(self._root_fd)
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            descriptor = os.open(name, flags, dir_fd=self._root_fd)
            try:
                metadata = os.fstat(descriptor)
                visible = (self.control_root / name).lstat()
                if (
                    not stat.S_ISDIR(metadata.st_mode)
                    or stat.S_IMODE(metadata.st_mode) & 0o077
                    or metadata.st_uid != os.geteuid()
                    or (metadata.st_dev, metadata.st_ino)
                    != (visible.st_dev, visible.st_ino)
                ):
                    raise ValueError("Package Product state root is unsafe")
            finally:
                os.close(descriptor)
            self._assert_current_unlocked()
            return self.control_root / name

    def issue_runtime_lease(
        self,
        *,
        runtime_id: str,
        runtime_version: str,
        runtime_protocol_epoch: int,
    ) -> PackageProductRuntimeLease:
        """Admit a Session only while this exact control root remains visible."""

        with self._close_lock:
            self._assert_current_unlocked()
            fence = self.cutover_result.fence
            if fence is None:
                raise ValueError("Package Product fence is unavailable")
            lease = register_package_product_runtime_lease(
                self.registry,
                fence=fence,
                runtime_id=runtime_id,
                runtime_version=runtime_version,
                runtime_protocol_epoch=runtime_protocol_epoch,
            )
            try:
                self._assert_current_unlocked()
                return lease
            except BaseException:
                lease.release()
                raise

    def _assert_current_unlocked(self) -> None:
        if self._closed:
            raise ValueError("Package Product epoch owner is closed")
        metadata = os.fstat(self._root_fd)
        visible = self._file_io.root.lstat()
        if (metadata.st_dev, metadata.st_ino) != (visible.st_dev, visible.st_ino):
            raise ValueError("Package Product control root changed")
        observed = reopen_posix_product_cutover(
            authority_root=self._authority_root,
            control_root=self._file_io.root,
            store_id=self.registry.store_id,
            epochs_root_name=self._epochs_root_name,
        )
        if observed != self.cutover_result:
            raise ValueError("Package Product epoch changed")
        visible = self._file_io.root.lstat()
        if (metadata.st_dev, metadata.st_ino) != (visible.st_dev, visible.st_ino):
            raise ValueError("Package Product control root changed")

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            with self.registry.exclusive_runtime_quiescence(
                store_id=self.registry.store_id
            ) as quiescence:
                if quiescence.active_runtime_lease_ids:
                    raise RuntimeError("Package Product runtime leases remain active")
            self._file_io.cleanup()
            os.close(self._root_fd)
            self._closed = True

    def __enter__(self) -> PackageProductPosixFencedRuntimeOwner:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def register_package_product_runtime_lease(
    registry: PackageEpochRuntimeLeaseRegistry,
    *,
    fence: PackageEpochFenceReceiptV1,
    runtime_id: str,
    runtime_version: str,
    runtime_protocol_epoch: int,
) -> PackageProductRuntimeLease:
    """Register one B runtime and bind its admission to the selected fence."""

    if not isinstance(registry, PackageEpochRuntimeLeaseRegistry):
        raise TypeError("Package Product runtime lease registry is required")
    if not isinstance(fence, PackageEpochFenceReceiptV1):
        raise TypeError("Package Product current fence is required")
    if registry.store_id != fence.store_id or registry.fences.current(registry.store_id) != fence:
        raise ValueError("Package Product runtime fence changed")
    handle = registry.register(
        runtime_id=runtime_id,
        runtime_protocol_epoch=runtime_protocol_epoch,
    )
    try:
        if (
            registry.fences.current(registry.store_id) != fence
            or handle.lease.runtime_epoch != fence.epoch
            or handle.lease.store_root_identity != fence.fenced_root_identity
        ):
            raise ValueError("Package Product runtime fence changed")
        admission = PackageEpochRuntimeAdmissionRequestV1.create(
            fence=fence,
            runtime_id=handle.lease.runtime_id,
            runtime_version=runtime_version,
            runtime_protocol_epoch=runtime_protocol_epoch,
            runtime_epoch=handle.lease.runtime_epoch,
            store_root_identity=handle.lease.store_root_identity,
            lease_id=handle.lease.lease_id,
        )
        return PackageProductRuntimeLease(
            registry=registry,
            admission_request=admission,
            _handle=handle,
        )
    except BaseException:
        handle.release()
        raise


def register_package_product_legacy_runtime(
    authority_root: Path,
    *,
    control_root: Path,
    store_id: str,
    startup_id: str,
) -> PackageProductLegacyRuntimeRegistration:
    """Admit one legacy process through the internal Linux pre-fence owner."""

    if (
        not isinstance(control_root, Path)
        or not control_root.is_absolute()
        or ".." in control_root.parts
    ):
        raise ValueError("Package Product epoch control root is invalid")
    try:
        return PackagePosixPreFenceRegistrationOwner(
            authority_root,
            store_id=store_id,
            fences=PackageEpochFenceJournal(control_root / "epoch.jsonl"),
        ).register(startup_id=startup_id)
    except PackagePosixPreFenceRegistrationError as exc:
        raise PackageProductLegacyPreFenceAdmissionError(
            str(exc), code=exc.code
        ) from exc


@dataclass(frozen=True, slots=True)
class PackageProductFileEpochTransactionGuard:
    """Hold the Product's shared coordination lock across admission and effects.

    Offline cutover must acquire the same lock path exclusively before its
    quiescence and root-switch proof. This guard does not issue a runtime lease
    or turn an uncut legacy root into a B-epoch Store.
    """

    store_id: str
    coordination_lock: Path
    file_io: RootedFileIO | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.store_id, str)
            or _SAFE_STORE_ID.fullmatch(self.store_id) is None
        ):
            raise ValueError("Package Product store identity is invalid")
        path = self.coordination_lock
        if (
            not isinstance(path, Path)
            or not path.is_absolute()
            or ".." in path.parts
            or path == Path(path.anchor)
        ):
            raise ValueError("Package Product coordination lock must be absolute")
        if self.file_io is not None and (
            not isinstance(self.file_io, RootedFileIO)
            or self.file_io.root != path.parent
        ):
            raise TypeError("Package Product epoch guard requires the same rooted IO")

    @contextmanager
    def shared_runtime(self, *, store_id: str) -> Iterator[None]:
        if store_id != self.store_id:
            raise ValueError("Package Product store identity changed")
        if self.file_io is None:
            with journal_file_lock(self.coordination_lock, "shared"):
                yield
        else:
            with self.file_io.bind(self.coordination_lock) as rooted:
                rooted.acquire_lock(exclusive=False, suffix=".lock")
                yield


__all__ = [
    "PackageProductFileEpochTransactionGuard",
    "PackageProductLegacyPreFenceAdmissionError",
    "PackageProductLegacyRuntimeRegistration",
    "PackageProductPosixFencedRuntimeOwner",
    "PackageProductRuntimeLease",
    "register_package_product_runtime_lease",
    "register_package_product_legacy_runtime",
]
