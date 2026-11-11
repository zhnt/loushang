"""Original legacy Product startup registration and inactivity observation."""

from __future__ import annotations

import os
import stat
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from loushang.harness.journal import JournalLockUnavailable, journal_file_lock
from loushang.harness.resources.packages._private_directory import (
    prepare_private_directory_tree,
)


class _LegacyStateRoots(Protocol):
    @property
    def root(self) -> Path: ...
    @property
    def private_state_base(self) -> Path: ...
    @property
    def package_root(self) -> Path: ...
    @property
    def private_data_base(self) -> Path: ...
    @property
    def coordination_lock(self) -> Path: ...


class _LegacyEpoch(Protocol):
    @property
    def authority_root(self) -> Path: ...
    @property
    def control_root(self) -> Path: ...
    @property
    def store_id(self) -> str: ...


@dataclass(frozen=True, slots=True)
class _LegacyStartupPolicy:
    product_label: str
    error_code_prefix: str
    make_error: Callable[[str, str], RuntimeError]
    registration_identity: Callable[[str], str]


_PROCESS_STARTUP_LEASES_LOCK = threading.Lock()
_PROCESS_STARTUP_LEASES: dict[Path, AbstractContextManager[None]] = {}


def _prepare_tree(
    path: Path, *, private_base: Path, label: str, policy: _LegacyStartupPolicy
) -> None:
    prepare_private_directory_tree(
        path,
        private_base=private_base,
        outside_base_error=lambda: policy.make_error(
            f"{policy.product_label} Plugin {label} root is outside its private base",
            f"{policy.error_code_prefix}_state_permissions_failed",
        ),
        private_error=lambda: policy.make_error(
            f"{policy.product_label} Plugin state root is not private",
            f"{policy.error_code_prefix}_state_permissions_failed",
        ),
    )


def prepare_private_state_layout(
    layout: _LegacyStateRoots, *, policy: _LegacyStartupPolicy
) -> None:
    _prepare_tree(
        layout.root,
        private_base=layout.private_state_base,
        label="state",
        policy=policy,
    )
    _prepare_tree(
        layout.package_root,
        private_base=layout.private_data_base,
        label="data",
        policy=policy,
    )
    with journal_file_lock(layout.coordination_lock, "exclusive"):
        pass


def _hold_process_startup_lease(
    layout: _LegacyStateRoots,
    *,
    startup_id: str,
    lease_path: Path,
    resolve_epoch: Callable[[], _LegacyEpoch],
    policy: _LegacyStartupPolicy,
) -> bool:
    with _PROCESS_STARTUP_LEASES_LOCK:
        if lease_path in _PROCESS_STARTUP_LEASES:
            return False
        lease = _legacy_process_startup_scope(
            layout,
            startup_id=startup_id,
            lease_path=lease_path,
            resolve_epoch=resolve_epoch,
            policy=policy,
        )
        try:
            lease.__enter__()
        except JournalLockUnavailable as exc:
            raise policy.make_error(
                f"{policy.product_label} Plugin startup id is active in another process",
                f"{policy.error_code_prefix}_startup_already_active",
            ) from exc
        _PROCESS_STARTUP_LEASES[lease_path] = lease
        return True


@contextmanager
def _legacy_process_startup_scope(
    layout: _LegacyStateRoots,
    *,
    startup_id: str,
    lease_path: Path,
    resolve_epoch: Callable[[], _LegacyEpoch],
    policy: _LegacyStartupPolicy,
) -> Iterator[None]:
    registration = None
    if sys.platform.startswith("linux"):
        from loushang.harness.resources.packages.product_epoch_guard import (
            PackageProductLegacyPreFenceAdmissionError,
            register_package_product_legacy_runtime,
        )

        epoch = resolve_epoch()
        _prepare_tree(
            epoch.authority_root,
            private_base=layout.private_data_base,
            label="data",
            policy=policy,
        )
        _prepare_tree(
            epoch.control_root,
            private_base=layout.private_state_base,
            label="state",
            policy=policy,
        )
        try:
            registration = register_package_product_legacy_runtime(
                epoch.authority_root,
                control_root=epoch.control_root,
                store_id=epoch.store_id,
                startup_id=policy.registration_identity(startup_id),
            )
        except PackageProductLegacyPreFenceAdmissionError as exc:
            raise policy.make_error(str(exc), exc.code) from exc
    elif os.name == "nt":
        from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
            PackageEpochFenceJournal,
        )
        from loushang.harness.resources.packages.plugin_lifecycle.windows_pre_fence_registration import (
            PackageWindowsPreFenceRegistrationError,
            PackageWindowsPreFenceRegistrationOwner,
        )
        from loushang.harness.resources.packages.product_windows_epoch_guard import (
            prepare_windows_product_control_root,
        )

        epoch = resolve_epoch()
        _prepare_tree(
            epoch.control_root.parent,
            private_base=layout.private_state_base,
            label="state",
            policy=policy,
        )
        try:
            prepare_windows_product_control_root(epoch.control_root)
            registration = PackageWindowsPreFenceRegistrationOwner(
                epoch.control_root,
                store_id=epoch.store_id,
                fences=PackageEpochFenceJournal(epoch.control_root / "epoch.jsonl"),
            ).register(
                startup_id=policy.registration_identity(startup_id),
            )
        except (OSError, ValueError, PackageWindowsPreFenceRegistrationError) as exc:
            raise policy.make_error(
                f"{policy.product_label} Windows legacy Package admission failed",
                getattr(
                    exc, "code", f"{policy.error_code_prefix}_state_permissions_failed"
                ),
            ) from exc
    try:
        prepare_private_state_layout(layout, policy=policy)
        with journal_file_lock(
            lease_path,
            "exclusive",
            lock_suffix="",
            blocking=False,
        ):
            yield
    finally:
        if registration is not None:
            registration.release()


def _release_process_startup_lease(
    lease_path: Path,
) -> None:
    with _PROCESS_STARTUP_LEASES_LOCK:
        lease = _PROCESS_STARTUP_LEASES.pop(lease_path, None)
    if lease is not None:
        lease.__exit__(None, None, None)


def _startup_lease_is_inactive(
    lease_path: Path,
    *,
    policy: _LegacyStartupPolicy,
) -> bool:
    with _PROCESS_STARTUP_LEASES_LOCK:
        if lease_path in _PROCESS_STARTUP_LEASES:
            return False
    try:
        metadata = lease_path.lstat()
        getuid = getattr(os, "getuid", None)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or bool(getattr(metadata, "st_reparse_tag", 0))
            or (os.name == "posix" and callable(getuid) and metadata.st_uid != getuid())
        ):
            raise OSError("startup lease is not a private regular file")
        with journal_file_lock(
            lease_path,
            "exclusive",
            lock_suffix="",
            blocking=False,
        ):
            return True
    except JournalLockUnavailable:
        return False
    except OSError as exc:
        raise policy.make_error(
            f"{policy.product_label} Plugin startup liveness evidence is invalid",
            f"{policy.error_code_prefix}_startup_evidence_invalid",
        ) from exc
