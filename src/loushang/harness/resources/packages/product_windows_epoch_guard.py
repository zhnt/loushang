"""Windows Product fence owner over one pinned control root and lease registry.

This owner retains epoch and runtime-quiescence authority. Session admission,
Product state preparation, and Package Store composition remain separate ports.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
    PackageEpochRuntimeAdmissionOwner,
    PackageEpochRuntimeAdmissionRequestV1,
    PackageEpochRuntimeAdmissionResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
    PackageEpochRuntimeQuiescenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverQuiescenceReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_cutover import (
    PackageWindowsEpochCutoverError,
    PackageWindowsEpochCutoverOwner,
    PackageWindowsEpochCutoverResultV1,
    _directory_native_identity,
    _PinnedWindowsAuthority,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry import (
    PackageWindowsEpochRuntimeLeaseRegistry,
    PackageWindowsRuntimeLeaseHandle,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_pre_fence_registration import (
    PackageWindowsPreFenceRegistrationOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    supports_windows_rooted_io,
    windows_flush_directory,
)


def prepare_windows_product_control_root(control_root: Path) -> Path:
    """Create a private control root or admit an exact existing one.

    An existing directory is never repaired in place. Callers must prepare
    its parent before first cutover; the Product owner revalidates it on open.
    """

    if (
        os.name != "nt"
        or not supports_windows_rooted_io()
        or not isinstance(control_root, Path)
        or not control_root.is_absolute()
        or ".." in control_root.parts
        or control_root.parent == Path(control_root.anchor)
    ):
        raise ValueError("Windows Package Product control root is invalid")
    with WindowsPrivateDirectoryAcl() as acl:
        parent = _PinnedWindowsAuthority.open(control_root.parent)
        try:
            created = False
            try:
                descriptor = open_windows_directory(
                    control_root.name,
                    dir_fd=parent.descriptor,
                    create_new=True,
                    share_delete=False,
                    security_descriptor=acl.security_descriptor,
                    read_control=True,
                )
                created = True
            except FileExistsError:
                descriptor = open_windows_directory(
                    control_root.name,
                    dir_fd=parent.descriptor,
                    share_delete=False,
                    read_control=True,
                )
            try:
                acl.validate(descriptor)
                identity = _directory_native_identity(descriptor)
                if created:
                    windows_flush_directory(parent.descriptor)
                parent.assert_visible()
                visible = open_windows_directory(
                    control_root.name,
                    dir_fd=parent.descriptor,
                    share_delete=False,
                    read_control=True,
                )
                try:
                    acl.validate(visible)
                    if _directory_native_identity(visible) != identity:
                        raise OSError("Windows Package Product control root changed")
                finally:
                    os.close(visible)
            finally:
                os.close(descriptor)
        finally:
            parent.close()
    return control_root


def prepare_windows_product_private_directory_chain(
    root: Path, *child_names: str, inherit_leaf: bool = False
) -> Path:
    """Create private children; optionally inherit the final ACL to files."""

    if (
        os.name != "nt"
        or not supports_windows_rooted_io()
        or not isinstance(root, Path)
        or not root.is_absolute()
        or ".." in root.parts
        or not child_names
        or type(inherit_leaf) is not bool
        or any(
            not isinstance(name, str)
            or not name
            or name in {".", ".."}
            or any(separator in name for separator in ("/", "\\", ":"))
            for name in child_names
        )
    ):
        raise ValueError("Windows Product private directory chain is invalid")
    with ExitStack() as stack:
        acl = stack.enter_context(WindowsPrivateDirectoryAcl())
        inheritable_acl = (
            stack.enter_context(WindowsPrivateDirectoryAcl(inherit_children=True))
            if inherit_leaf
            else acl
        )
        pinned = _PinnedWindowsAuthority.open(root, read_control=True)
        descriptors: list[tuple[int, bool]] = []
        try:
            acl.validate(pinned.descriptor)
            parent_descriptor = pinned.descriptor
            for index, name in enumerate(child_names):
                leaf = inherit_leaf and index == len(child_names) - 1
                child_acl = inheritable_acl if leaf else acl
                created = False
                try:
                    descriptor = open_windows_directory(
                        name,
                        dir_fd=parent_descriptor,
                        create_new=True,
                        share_delete=False,
                        security_descriptor=child_acl.security_descriptor,
                        read_control=True,
                    )
                    created = True
                except FileExistsError:
                    descriptor = open_windows_directory(
                        name,
                        dir_fd=parent_descriptor,
                        share_delete=False,
                        read_control=True,
                    )
                descriptors.append((descriptor, leaf))
                child_acl.validate(descriptor)
                if created:
                    windows_flush_directory(parent_descriptor)
                parent_descriptor = descriptor
            pinned.assert_visible()
            for descriptor, leaf in descriptors:
                (inheritable_acl if leaf else acl).validate(descriptor)
            return root.joinpath(*child_names)
        finally:
            for descriptor, _leaf in reversed(descriptors):
                os.close(descriptor)
            pinned.close()


def inspect_windows_product_private_directory_identity(
    root: Path,
) -> tuple[int, int]:
    """Read the exact native identity of an existing private directory."""

    if (
        os.name != "nt"
        or not supports_windows_rooted_io()
        or not isinstance(root, Path)
        or not root.is_absolute()
        or ".." in root.parts
    ):
        raise ValueError("Windows Product private directory is invalid")
    with WindowsPrivateDirectoryAcl() as acl:
        pinned = _PinnedWindowsAuthority.open(root, read_control=True)
        try:
            acl.validate(pinned.descriptor)
            pinned.assert_visible()
            return pinned.identities[-1]
        finally:
            pinned.close()


@dataclass(frozen=True, slots=True)
class PackageWindowsProductRuntimeLease:
    """Retain one admitted native Session lease until Product disposal."""

    registry: PackageWindowsEpochRuntimeLeaseRegistry
    admission_request: PackageEpochRuntimeAdmissionRequestV1
    _handle: PackageWindowsRuntimeLeaseHandle = field(repr=False, compare=False)

    def release(self) -> None:
        self._handle.release()

    def __enter__(self) -> PackageWindowsProductRuntimeLease:
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


class PackageProductWindowsFencedRuntimeOwner:
    """Retain one current Windows Product fence and its offline lease gate."""

    def __init__(
        self,
        *,
        authority_root: Path,
        control_root: Path,
        epochs_root_name: str,
        cutover_result: PackageWindowsEpochCutoverResultV1,
        fences: PackageEpochFenceJournal,
        registry: PackageWindowsEpochRuntimeLeaseRegistry,
        pinned_control: _PinnedWindowsAuthority,
        acl: WindowsPrivateDirectoryAcl,
    ) -> None:
        if (
            not isinstance(registry, PackageWindowsEpochRuntimeLeaseRegistry)
            or not isinstance(pinned_control, _PinnedWindowsAuthority)
            or not isinstance(acl, WindowsPrivateDirectoryAcl)
            or registry.control_root != control_root
            or registry.fences is not fences
            or fences.path != control_root / "epoch.jsonl"
            or not isinstance(cutover_result, PackageWindowsEpochCutoverResultV1)
            or cutover_result.disposition != "fenced"
            or cutover_result.fence is None
            or cutover_result.fence.store_id != registry.store_id
        ):
            raise ValueError("Windows Package Product epoch owners are not bound")
        self._authority_root = authority_root
        self.control_root = control_root
        self._epochs_root_name = epochs_root_name
        self.cutover_result = cutover_result
        self.fences = fences
        self.registry = registry
        self._pinned_control = pinned_control
        self._acl = acl
        self._close_lock = RLock()
        self._closed = False
        self._children: dict[str, tuple[int, tuple[int, int]]] = {}

    @classmethod
    def open(
        cls,
        *,
        authority_root: Path,
        control_root: Path,
        store_id: str,
        epochs_root_name: str,
    ) -> PackageProductWindowsFencedRuntimeOwner:
        """Open only the current durable fence through native pinned roots."""

        if os.name != "nt" or not supports_windows_rooted_io():
            raise ValueError("Windows Package Product epoch owner is unavailable")
        if any(
            not isinstance(path, Path)
            or not path.is_absolute()
            or ".." in path.parts
            or path == Path(path.anchor)
            for path in (authority_root, control_root)
        ):
            raise ValueError("Windows Package Product epoch roots are invalid")
        acl = WindowsPrivateDirectoryAcl()
        try:
            pinned = _PinnedWindowsAuthority.open(control_root, read_control=True)
        except BaseException:
            acl.close()
            raise
        registry: PackageWindowsEpochRuntimeLeaseRegistry | None = None
        try:
            acl.validate(pinned.descriptor)
            journal_path = control_root / "epoch.jsonl"
            fences = PackageEpochFenceJournal(journal_path)
            if fences.path != journal_path:
                raise ValueError("Windows Package Product fence path changed")
            cutover = PackageWindowsEpochCutoverOwner.reopen_fenced(
                authority_root,
                store_id=store_id,
                epoch_journal=fences,
                epochs_root_name=epochs_root_name,
            )
            registry = PackageWindowsEpochRuntimeLeaseRegistry(
                control_root=control_root,
                fences=fences,
                store_id=store_id,
            )
            if fences.current(store_id) != cutover.fence:
                raise ValueError("Windows Package Product fence changed during open")
            pinned.assert_visible()
            return cls(
                authority_root=authority_root,
                control_root=control_root,
                epochs_root_name=epochs_root_name,
                cutover_result=cutover,
                fences=fences,
                registry=registry,
                pinned_control=pinned,
                acl=acl,
            )
        except BaseException:
            if registry is not None:
                registry.close()
            pinned.close()
            acl.close()
            raise

    def assert_current(self) -> None:
        with self._close_lock:
            self._assert_current_unlocked()

    def issue_runtime_lease(
        self,
        *,
        runtime_id: str,
        runtime_version: str,
        runtime_protocol_epoch: int,
    ) -> PackageWindowsProductRuntimeLease:
        """Admit a live Session against the current native fence and lease set."""

        with self._close_lock:
            self._assert_current_unlocked()
            fence = self.cutover_result.fence
            if fence is None:
                raise ValueError("Windows Package Product fence is unavailable")
            handle = self.registry.register(
                runtime_id=runtime_id,
                runtime_protocol_epoch=runtime_protocol_epoch,
            )
            try:
                self._assert_current_unlocked()
                admission = PackageEpochRuntimeAdmissionRequestV1.create(
                    fence=fence,
                    runtime_id=handle.lease.runtime_id,
                    runtime_version=runtime_version,
                    runtime_protocol_epoch=runtime_protocol_epoch,
                    runtime_epoch=handle.lease.runtime_epoch,
                    store_root_identity=handle.lease.store_root_identity,
                    lease_id=handle.lease.lease_id,
                )
                result = PackageEpochRuntimeAdmissionOwner(
                    fences=self.fences,
                    leases=self.registry,
                ).admit(admission)
                if result.disposition != "admitted":
                    raise ValueError("Windows Package Product runtime was not admitted")
                self._assert_current_unlocked()
                return PackageWindowsProductRuntimeLease(
                    registry=self.registry,
                    admission_request=admission,
                    _handle=handle,
                )
            except BaseException:
                handle.release()
                raise

    def prepare_product_state_root(self) -> Path:
        """Create or reopen one pinned Product journal directory."""

        return self._prepare_private_child("product-state")

    @contextmanager
    def borrow_product_state_root_descriptor(self) -> Iterator[int]:
        """Hold the current epoch and pinned Product state root for child I/O.

        The descriptor is borrowed for this scope only and must not be closed
        by the Product caller. The owner rechecks the durable epoch on exit.
        """

        self.prepare_product_state_root()
        with self._close_lock:
            self._assert_current_unlocked()
            descriptor, _identity = self._children["product-state"]
            try:
                yield descriptor
            finally:
                self._assert_current_unlocked()

    def prepare_product_source_root(self) -> Path:
        """Create or reopen one pinned Product Source directory."""

        return self._prepare_private_child("product-sources")

    def prepare_product_dependency_root(self) -> Path:
        """Create or reopen the private shared-dependency Store root."""

        return self._prepare_private_child("dependency-store")

    def selected_store_root(self) -> Path:
        """Return the only Store namespace admitted by this Product fence."""

        with self._close_lock:
            self._assert_current_unlocked()
            switch = self.cutover_result.switch_receipt
            if switch is None:
                raise ValueError("Windows Package Product switch receipt is missing")
            return self._authority_root / self._epochs_root_name / switch.namespace_id

    def _prepare_private_child(self, name: str) -> Path:
        with self._close_lock:
            self._assert_current_unlocked()
            if name not in self._children:
                created = False
                try:
                    descriptor = open_windows_directory(
                        name,
                        dir_fd=self._pinned_control.descriptor,
                        create_new=True,
                        share_delete=False,
                        security_descriptor=self._acl.security_descriptor,
                        read_control=True,
                    )
                    created = True
                except FileExistsError:
                    descriptor = open_windows_directory(
                        name,
                        dir_fd=self._pinned_control.descriptor,
                        share_delete=False,
                        read_control=True,
                    )
                try:
                    self._acl.validate(descriptor)
                    identity = _directory_native_identity(descriptor)
                    if created:
                        windows_flush_directory(self._pinned_control.descriptor)
                    self._pinned_control.assert_visible()
                    self._children[name] = (descriptor, identity)
                except BaseException:
                    os.close(descriptor)
                    raise
            self._assert_current_unlocked()
            return self.control_root / name

    @contextmanager
    def exclusive_runtime_quiescence(
        self,
    ) -> Iterator[PackageEpochRuntimeQuiescenceV1]:
        """Keep this Product owner and native lease gate through one operation."""

        with self._close_lock:
            self._assert_current_unlocked()
            with self.registry.exclusive_runtime_quiescence(
                store_id=self.registry.store_id
            ) as quiescence:
                self._assert_current_unlocked()
                try:
                    yield quiescence
                finally:
                    self._assert_current_unlocked()

    def _assert_current_unlocked(self) -> None:
        if self._closed:
            raise ValueError("Windows Package Product epoch owner is closed")
        self._pinned_control.assert_visible()
        self._acl.validate(self._pinned_control.descriptor)
        observed = PackageWindowsEpochCutoverOwner.reopen_fenced(
            self._authority_root,
            store_id=self.registry.store_id,
            epoch_journal=self.fences,
            epochs_root_name=self._epochs_root_name,
        )
        if observed != self.cutover_result:
            raise ValueError("Windows Package Product epoch changed")
        for name, (descriptor, expected) in self._children.items():
            self._acl.validate(descriptor)
            if _directory_native_identity(descriptor) != expected:
                raise ValueError("Windows Package Product child root changed")
            visible = open_windows_directory(
                name,
                dir_fd=self._pinned_control.descriptor,
                share_delete=False,
                read_control=True,
            )
            try:
                self._acl.validate(visible)
                if _directory_native_identity(visible) != expected:
                    raise ValueError("Windows Package Product child root changed")
            finally:
                os.close(visible)
        self._pinned_control.assert_visible()

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self.registry.close()
            for descriptor, _identity in reversed(tuple(self._children.values())):
                os.close(descriptor)
            self._children.clear()
            self._pinned_control.close()
            self._closed = True
            self._acl.close()


@dataclass(frozen=True, slots=True)
class PackageProductWindowsEpochTransactionGuard:
    """Keep one Windows Product fence and lease gate through a transaction."""

    epoch_runtime: PackageProductWindowsFencedRuntimeOwner

    def __post_init__(self) -> None:
        if not isinstance(self.epoch_runtime, PackageProductWindowsFencedRuntimeOwner):
            raise TypeError("Windows Package Product epoch owner is required")

    @contextmanager
    def shared_runtime(self, *, store_id: str) -> Iterator[None]:
        owner = self.epoch_runtime
        with owner._close_lock:
            owner._assert_current_unlocked()
            if store_id != owner.registry.store_id:
                raise ValueError("Windows Package Product store identity changed")
            with owner.registry.shared_runtime(store_id=store_id):
                owner._assert_current_unlocked()
                try:
                    yield
                finally:
                    owner._assert_current_unlocked()


class PackageProductWindowsStoreRootAdmission(PackageEpochRuntimeAdmissionOwner):
    """Admit a Session only while its Product Store root remains current."""

    def __init__(
        self, *, epoch_runtime: PackageProductWindowsFencedRuntimeOwner
    ) -> None:
        if not isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner):
            raise TypeError("Windows Package Product epoch owner is required")
        super().__init__(fences=epoch_runtime.fences, leases=epoch_runtime.registry)
        self._epoch_runtime = epoch_runtime

    def admit(
        self, request: PackageEpochRuntimeAdmissionRequestV1
    ) -> PackageEpochRuntimeAdmissionResultV1:
        owner = self._epoch_runtime
        try:
            owner.assert_current()
        except (OSError, ValueError, PackageWindowsEpochCutoverError):
            return self._reject_root(request)
        result = super().admit(request)
        if result.disposition == "admitted":
            try:
                owner.assert_current()
            except (OSError, ValueError, PackageWindowsEpochCutoverError):
                return self._reject_root(request)
        return result

    @staticmethod
    def _reject_root(
        request: PackageEpochRuntimeAdmissionRequestV1,
    ) -> PackageEpochRuntimeAdmissionResultV1:
        return PackageEpochRuntimeAdmissionResultV1.rejected(
            request,
            evidence_ref=request.fence_id,
            operator_action="offline_restore",
        )


@dataclass(frozen=True, slots=True)
class PackageWindowsCurrentEpochCutoverCoordinationOwner:
    """Bind a B-to-B Windows cutover to the Product's native lease lock."""

    registry: PackageWindowsEpochRuntimeLeaseRegistry

    def __post_init__(self) -> None:
        if not isinstance(self.registry, PackageWindowsEpochRuntimeLeaseRegistry):
            raise TypeError("Windows Package runtime lease registry is required")

    @contextmanager
    def exclusive_quiescence(
        self, *, store_id: str
    ) -> Iterator[PackageEpochCutoverQuiescenceReceiptV1]:
        if store_id != self.registry.store_id:
            raise ValueError("Windows Package cutover store identity changed")
        if self.registry.fences.current(store_id) is None:
            raise ValueError("Windows Package current B fence is required")
        with self.registry.exclusive_runtime_quiescence(store_id=store_id) as held:
            if self.registry.fences.current(store_id) is None:
                raise ValueError("Windows Package current B fence changed")
            yield PackageEpochCutoverQuiescenceReceiptV1.create(
                store_id=store_id,
                owner_revision=held.owner_revision,
                active_runtime_lease_ids=held.active_runtime_lease_ids,
                active_pre_fence_registration_ids=(),
            )


@dataclass(frozen=True, slots=True)
class PackageWindowsFirstEpochCutoverCoordinationOwner:
    """Bind first-B cutover to the pre-fence launch barrier and live set."""

    pre_fence: PackageWindowsPreFenceRegistrationOwner

    def __post_init__(self) -> None:
        if not isinstance(self.pre_fence, PackageWindowsPreFenceRegistrationOwner):
            raise TypeError("Windows pre-fence registration owner is required")

    @contextmanager
    def exclusive_quiescence(
        self, *, store_id: str
    ) -> Iterator[PackageEpochCutoverQuiescenceReceiptV1]:
        with self.pre_fence.exclusive_quiescence(store_id=store_id) as held:
            yield PackageEpochCutoverQuiescenceReceiptV1.create(
                store_id=store_id,
                owner_revision=held.owner_revision,
                active_runtime_lease_ids=(),
                active_pre_fence_registration_ids=held.active_registration_ids,
            )


__all__ = [
    "PackageProductWindowsEpochTransactionGuard",
    "PackageProductWindowsStoreRootAdmission",
    "PackageProductWindowsFencedRuntimeOwner",
    "PackageWindowsProductRuntimeLease",
    "PackageWindowsCurrentEpochCutoverCoordinationOwner",
    "PackageWindowsFirstEpochCutoverCoordinationOwner",
    "prepare_windows_product_control_root",
    "prepare_windows_product_private_directory_chain",
    "inspect_windows_product_private_directory_identity",
]
