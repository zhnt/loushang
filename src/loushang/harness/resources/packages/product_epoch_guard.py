"""Product transaction guard paired with the Package cutover coordination lock."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
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
    "PackageProductRuntimeLease",
    "register_package_product_runtime_lease",
    "register_package_product_legacy_runtime",
]
