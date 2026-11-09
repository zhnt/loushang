"""Product custody for one approved inert Linux H6 runtime release.

Uses the existing Product GC/currentness owner and approval journal. This private
implementation adds no launch authority, replacement operation or recovery policy.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import stat
import zipfile
from collections.abc import Callable
from dataclasses import Field, dataclass, replace
from hashlib import sha256
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, ClassVar, Generic, Protocol, TypeVar, cast

from loushang.harness.journal._io_loops import write_all
from loushang.harness.resources.packages.plugin_lifecycle.posix_materialization import (
    _rename_directory_noreplace,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    PackageInspectionBudgetV1,
    inspect_package_wheel_bytes,
)
from loushang.harness.worker._linux_native_release import (
    _PACKAGE,
    _LinuxNativeReleaseVerifier,
)
from loushang.harness.worker.history._native_approval import (
    _NativeApprovalMethods,
    _NativeDecisionMethods,
)
from loushang.harness.worker.native_executable_format import (
    WorkerNativeExecutableFormatError,
)

from .product_local_wheel_runtime import PosixLocalWheelProductSessionOwner

_PRODUCT_NATIVE_RELEASE_ROOT = "worker-native-release-v1"
_SOURCE_WHEEL_NAME = "source.whl"
_RECEIPT_NAME = "product-native-release.json"
_MAX_SOURCE_WHEEL_BYTES = 4 * 1024 * 1024
_MAX_WHEEL_BYTES = 4 * 1024 * 1024
_MAX_MEMBER_BYTES = 16 * 1024 * 1024
_MAX_TREE_BYTES = 17 * 1024 * 1024
_STAGE_PREFIX = ".worker-native-release-stage-"


class _Closure(Protocol):
    __dataclass_fields__: ClassVar[dict[str, Field[Any]]]

    @property
    def native_profile_catalog_revision(self) -> str: ...
    @property
    def containment_launcher_digest(self) -> str: ...
    @property
    def containment_profile_digest(self) -> str: ...


class _Reader(Protocol):
    def current_closure(self) -> _Closure: ...


A = TypeVar("A", bound=_NativeApprovalMethods)
A_contra = TypeVar("A_contra", bound=_NativeApprovalMethods, contravariant=True)
C = TypeVar("C", bound=_Closure)
C_contra = TypeVar("C_contra", bound=_Closure, contravariant=True)
V = TypeVar("V")
V_co = TypeVar("V_co", covariant=True)
M = TypeVar("M")
M_co = TypeVar("M_co", covariant=True)
R = TypeVar("R", bound=_Reader)
R_co = TypeVar("R_co", bound=_Reader, covariant=True)


class _ApprovalOwner(Protocol[A]):
    def __init__(self, product_owner: PosixLocalWheelProductSessionOwner) -> None: ...
    @property
    def product_owner(self) -> PosixLocalWheelProductSessionOwner: ...
    def current(self) -> _NativeDecisionMethods[A] | None: ...


class _ReviewFactory(Protocol[A_contra, V_co]):
    def __call__(
        self, *, scope_id: str, product_policy_revision: str, approval: A_contra
    ) -> V_co: ...


class _ReaderFactory(Protocol[R_co]):
    def __call__(
        self, *, product_owner: PosixLocalWheelProductSessionOwner
    ) -> R_co: ...


class _MaterialFactory(Protocol[C_contra, M_co]):
    def __call__(self, *, launcher_path: Path, closure: C_contra) -> M_co: ...


@dataclass(frozen=True, slots=True)
class _LinuxWorkerNativeReleaseCustody(Generic[A, V, C, M, R]):
    """Whole original custody program with pure Product value/profile bindings.

    Binding construction performs no admission, IO, version lookup or validation.
    Each entry retains its own original admission, guard and error boundaries.
    """

    product_id: str
    product_label: str
    trust_class: str
    approval_type: Callable[[], type[A]]
    approval_owner_type: Callable[[], type[_ApprovalOwner[A]]]
    review_factory: Callable[[], _ReviewFactory[A, V]]
    reader_factory: Callable[[], _ReaderFactory[R]]
    material_factory: Callable[[], _MaterialFactory[C, M]]
    verifier: Callable[[], _LinuxNativeReleaseVerifier[C]]
    error_type: Callable[[], type[RuntimeError]]
    approval_error_type: Callable[[], type[RuntimeError]]
    wheel_version: Callable[[], str]
    installed_version: Callable[[], str]

    def review(
        self, product_owner: PosixLocalWheelProductSessionOwner, *, wheel: bytes
    ) -> V:
        """Verify one complete native Wheel before showing exact approval facts."""
        self.approval_owner_type()(product_owner)
        if not isinstance(wheel, bytes) or not 0 < len(wheel) <= _MAX_WHEEL_BYTES:
            raise ValueError("Worker native release Wheel exceeds its bound")
        inspect_package_wheel_bytes(
            wheel,
            wheel_filename=f"loushang_h6_native-{self.wheel_version()}-py3-none-linux_x86_64.whl",
            budgets=PackageInspectionBudgetV1(
                max_entries=16,
                max_total_expanded_bytes=_MAX_TREE_BYTES,
                max_entry_expanded_bytes=_MAX_MEMBER_BYTES,
                max_metadata_bytes=64 * 1024,
            ),
            max_artifact_bytes=_MAX_WHEEL_BYTES,
        )
        files = self._verified_wheel_members(wheel)
        catalog = files["loushang_h6_native/release/catalog.json"]
        launcher = files["loushang_h6_native/release/containment-launcher"]
        closure = self.verifier().verify_release_bytes(catalog, launcher)
        approval = cast(Callable[..., A], self.approval_type())(
            wheel_sha256=sha256(wheel).hexdigest(),
            catalog_sha256=sha256(catalog).hexdigest(),
            launcher_sha256=closure.containment_launcher_digest,
            profile_sha256=closure.containment_profile_digest,
        )
        with product_owner.gc_gate.guard():
            product_owner.assert_root_gc_authority_current()
            return self.review_factory()(
                scope_id=product_owner.policy.project_scope_id,
                product_policy_revision=product_owner.policy.authority_revision,
                approval=approval,
            )

    def install(
        self,
        product_owner: PosixLocalWheelProductSessionOwner,
        *,
        approval_owner: _ApprovalOwner[A],
        approved: A,
        wheel: bytes,
    ) -> R:
        """Publish only an approved exact Wheel into the Product private state."""
        if (
            not isinstance(product_owner, PosixLocalWheelProductSessionOwner)
            or not isinstance(approved, self.approval_type())
            or (not isinstance(approval_owner, self.approval_owner_type()))
            or (approval_owner.product_owner is not product_owner)
            or (not isinstance(wheel, bytes))
            or (not 0 < len(wheel) <= _MAX_WHEEL_BYTES)
            or (sha256(wheel).hexdigest() != approved.wheel_sha256)
        ):
            raise ValueError("Worker native release approval does not match Wheel")
        files = self._verified_wheel_members(wheel)
        catalog_name = "loushang_h6_native/release/catalog.json"
        launcher_name = "loushang_h6_native/release/containment-launcher"
        if (
            sha256(files[catalog_name]).hexdigest() != approved.catalog_sha256
            or sha256(files[launcher_name]).hexdigest() != approved.launcher_sha256
        ):
            raise ValueError("Worker native release approval changed")
        catalog = json.loads(files[catalog_name])
        if (
            type(catalog) is not dict
            or catalog.get("profileSourceSha256") != approved.profile_sha256
        ):
            raise ValueError("Worker native profile approval changed")
        with product_owner.gc_gate.guard(require_write=True):
            product_owner.assert_root_gc_authority_current()
            self._require_current_approval(approval_owner, approved)
            if not any(
                (
                    binding.source_trust_class == self.trust_class
                    for binding in product_owner.policy.bindings
                )
            ):
                raise ValueError(
                    f"{self.product_label} Product Worker candidate owner is required"
                )
            parent = product_owner.state_root
            parent_fd = os.open(
                parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            )
            try:
                self._require_private_root(parent_fd)
                target = parent / _PRODUCT_NATIVE_RELEASE_ROOT
                if any(
                    (name.startswith(_STAGE_PREFIX) for name in os.listdir(parent_fd))
                ):
                    raise self.error_type()(
                        "Worker native release has unsettled staging debt"
                    )
                if target.exists() or target.is_symlink():
                    reader = self.open_reader(product_owner)
                    closure = reader.current_closure()
                    receipt = self.read_receipt(target, product_owner)
                    if (
                        receipt["wheelSha256"] != approved.wheel_sha256
                        or receipt["catalogSha256"] != approved.catalog_sha256
                        or closure.containment_launcher_digest
                        != approved.launcher_sha256
                        or (
                            closure.containment_profile_digest
                            != approved.profile_sha256
                        )
                    ):
                        raise self.error_type()(
                            "Worker native release replacement requires a new operation"
                        )
                    return reader
                with TemporaryDirectory(prefix=_STAGE_PREFIX, dir=parent) as raw:
                    stage = Path(raw)
                    self._write_stage(stage, files, wheel, approved, product_owner)
                    stage_fd = os.open(
                        stage.name,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                        dir_fd=parent_fd,
                    )
                    try:
                        closure, receipt = self.verify_descriptor(
                            stage_fd, product_owner
                        )
                        self._require_approved_native_release(
                            closure, receipt, approved
                        )
                        os.fsync(stage_fd)
                        self._require_same_stage(parent_fd, stage.name, stage_fd)
                        self._require_current_approval(approval_owner, approved)
                        product_owner.assert_root_gc_authority_current()
                        self._require_same_product_root(parent, parent_fd)
                        _rename_directory_noreplace(
                            parent_fd,
                            stage.name,
                            parent_fd,
                            _PRODUCT_NATIVE_RELEASE_ROOT,
                        )
                        self._require_same_stage(
                            parent_fd, _PRODUCT_NATIVE_RELEASE_ROOT, stage_fd
                        )
                        os.fsync(parent_fd)
                    finally:
                        os.close(stage_fd)
                reader = self.open_reader(product_owner)
                closure, receipt = self.verify_root(target, product_owner)
                self._require_approved_native_release(closure, receipt, approved)
                return reader
            finally:
                os.close(parent_fd)

    def repair(
        self,
        product_owner: PosixLocalWheelProductSessionOwner,
        *,
        approval_owner: _ApprovalOwner[A],
        approved: A,
    ) -> R:
        """Finish one complete staged install; preserve partial or ambiguous debt."""
        if (
            not isinstance(product_owner, PosixLocalWheelProductSessionOwner)
            or not isinstance(approved, self.approval_type())
            or (not isinstance(approval_owner, self.approval_owner_type()))
            or (approval_owner.product_owner is not product_owner)
        ):
            raise TypeError(
                f"{self.product_label} Product native repair owners are required"
            )
        with product_owner.gc_gate.guard(require_write=True):
            product_owner.assert_root_gc_authority_current()
            self._require_current_approval(approval_owner, approved)
            if not any(
                (
                    binding.source_trust_class == self.trust_class
                    for binding in product_owner.policy.bindings
                )
            ):
                raise ValueError(
                    f"{self.product_label} Product Worker candidate owner is required"
                )
            parent = product_owner.state_root
            parent_fd = os.open(
                parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            )
            try:
                self._require_private_root(parent_fd)
                stages = tuple(
                    (
                        name
                        for name in os.listdir(parent_fd)
                        if name.startswith(_STAGE_PREFIX)
                    )
                )
                target = parent / _PRODUCT_NATIVE_RELEASE_ROOT
                if len(stages) != 1 or target.exists() or target.is_symlink():
                    raise self.error_type()(
                        "Worker native release repair state is ambiguous"
                    )
                stage_name = stages[0]
                stage_fd = os.open(
                    stage_name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=parent_fd,
                )
                try:
                    closure, receipt = self.verify_descriptor(stage_fd, product_owner)
                    self._require_approved_native_release(closure, receipt, approved)
                    os.fsync(stage_fd)
                    self._require_same_stage(parent_fd, stage_name, stage_fd)
                    self._require_current_approval(approval_owner, approved)
                    product_owner.assert_root_gc_authority_current()
                    self._require_same_product_root(parent, parent_fd)
                    _rename_directory_noreplace(
                        parent_fd, stage_name, parent_fd, _PRODUCT_NATIVE_RELEASE_ROOT
                    )
                    self._require_same_stage(
                        parent_fd, _PRODUCT_NATIVE_RELEASE_ROOT, stage_fd
                    )
                    os.fsync(parent_fd)
                finally:
                    os.close(stage_fd)
                closure, receipt = self.verify_root(target, product_owner)
                self._require_approved_native_release(closure, receipt, approved)
                return self.open_reader(product_owner)
            finally:
                os.close(parent_fd)

    def _require_approved_native_release(
        self, closure: C, receipt: dict[str, object], approved: A
    ) -> None:
        if (
            receipt["wheelSha256"] != approved.wheel_sha256
            or receipt["catalogSha256"] != approved.catalog_sha256
            or receipt["launcherSha256"] != approved.launcher_sha256
            or (receipt["profileSha256"] != approved.profile_sha256)
            or (
                closure.native_profile_catalog_revision
                != "h6-linux:" + approved.catalog_sha256
            )
            or (closure.containment_launcher_digest != approved.launcher_sha256)
            or (closure.containment_profile_digest != approved.profile_sha256)
        ):
            raise self.error_type()("Worker native approved release changed")

    def _require_current_approval(self, owner: _ApprovalOwner[A], approved: A) -> None:
        try:
            decision = owner.current()
        except self.approval_error_type() as exc:
            raise self.error_type()(
                "Worker native Product approval is unavailable"
            ) from exc
        if (
            decision is None
            or decision.action != "approve"
            or decision.approval != approved
        ):
            raise self.error_type()("Worker native Product approval is not current")

    def _require_same_stage(self, parent_fd: int, name: str, stage_fd: int) -> None:
        opened = os.fstat(stage_fd)
        visible = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISDIR(visible.st_mode)
            or opened.st_dev != visible.st_dev
            or opened.st_ino != visible.st_ino
        ):
            raise self.error_type()("Worker native staged root changed")

    def _require_same_product_root(self, parent: Path, parent_fd: int) -> None:
        opened = os.fstat(parent_fd)
        visible = parent.lstat()
        if opened.st_dev != visible.st_dev or opened.st_ino != visible.st_ino:
            raise self.error_type()("Worker Product state root changed")

    def _verified_wheel_members(self, wheel: bytes) -> dict[str, bytes]:
        dist_info = f"loushang_h6_native-{self.wheel_version()}.dist-info"
        expected = {
            "loushang_h6_native/__init__.py",
            "loushang_h6_native/release/catalog.json",
            "loushang_h6_native/release/containment-launcher",
            f"{dist_info}/METADATA",
            f"{dist_info}/WHEEL",
            f"{dist_info}/RECORD",
        }
        try:
            with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
                infos = archive.infolist()
                if (
                    len(infos) != len(expected)
                    or {info.filename for info in infos} != expected
                    or sum((info.file_size for info in infos)) > _MAX_TREE_BYTES
                ):
                    raise ValueError("Worker native Wheel members are unsupported")
                files = {}
                for info in infos:
                    if (
                        info.file_size > _MAX_MEMBER_BYTES
                        or info.compress_type != zipfile.ZIP_DEFLATED
                        or (not stat.S_ISREG(info.external_attr >> 16))
                        or (
                            stat.S_IMODE(info.external_attr >> 16)
                            != (
                                0o500
                                if info.filename.endswith("/containment-launcher")
                                else 0o644
                            )
                        )
                    ):
                        raise ValueError("Worker native Wheel member is unsafe")
                    files[info.filename] = archive.read(info)
                return files
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            raise ValueError("Worker native Wheel is invalid") from exc

    def _require_private_root(self, descriptor: int) -> None:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            raise self.error_type()("Worker Product state root is not private")

    def _write_stage(
        self,
        stage: Path,
        files: dict[str, bytes],
        wheel: bytes,
        approved: A,
        product_owner: PosixLocalWheelProductSessionOwner,
    ) -> None:
        for name, body in sorted(files.items()):
            target = stage / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._write_new(
                target,
                body,
                mode=0o500 if name.endswith("/containment-launcher") else 0o600,
            )
        self._write_new(stage / _SOURCE_WHEEL_NAME, wheel, mode=0o600)
        receipt = {
            "catalogSha256": approved.catalog_sha256,
            "launcherSha256": approved.launcher_sha256,
            "profileSha256": approved.profile_sha256,
            "scopeId": product_owner.policy.project_scope_id,
            "version": 1,
            "wheelSha256": approved.wheel_sha256,
        }
        receipt["recordDigest"] = sha256(canonical_json_bytes(receipt)).hexdigest()
        self._write_new(
            stage / _RECEIPT_NAME, canonical_json_bytes(receipt) + b"\n", mode=0o600
        )
        for directory in (
            stage / "loushang_h6_native/release",
            stage / "loushang_h6_native",
            stage / f"loushang_h6_native-{self.wheel_version()}.dist-info",
        ):
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def _write_new(self, path: Path, body: bytes, *, mode: int) -> None:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            mode,
        )
        try:
            os.fchmod(descriptor, mode)
            write_all(
                lambda view: os.write(descriptor, view),
                body,
                message="Worker native release write made no progress",
            )
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def open_reader(self, product_owner: PosixLocalWheelProductSessionOwner) -> R:
        """Bind the installed native catalog to one explicit Coding Product owner."""
        if (
            not isinstance(product_owner, PosixLocalWheelProductSessionOwner)
            or product_owner.policy.product_id != self.product_id
            or (
                not any(
                    (
                        binding.source_trust_class == self.trust_class
                        for binding in product_owner.policy.bindings
                    )
                )
            )
        ):
            raise ValueError(
                f"{self.product_label} Product Worker candidate owner is required"
            )
        with product_owner.gc_gate.guard():
            product_owner.assert_root_gc_authority_current()
            reader = self.reader_factory()(product_owner=product_owner)
            reader.current_closure()
            return reader

    def verify_root(
        self, root_path: Path, product_owner: PosixLocalWheelProductSessionOwner
    ) -> tuple[C, dict[str, object]]:
        """Verify one complete Product-staged or published native installation."""
        if not isinstance(root_path, Path) or not root_path.is_absolute():
            raise ValueError("Worker native Product root is invalid")
        try:
            with product_owner.gc_gate.guard():
                product_owner.assert_root_gc_authority_current()
                root = os.open(
                    root_path,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                )
                try:
                    return self.verify_descriptor(root, product_owner)
                finally:
                    os.close(root)
        except (
            OSError,
            UnicodeError,
            ValueError,
            TypeError,
            csv.Error,
            PackageNotFoundError,
            WorkerNativeExecutableFormatError,
        ) as exc:
            raise self.error_type()(
                "Worker native Product source cannot be verified"
            ) from exc

    def verify_descriptor(
        self, root: int, product_owner: PosixLocalWheelProductSessionOwner
    ) -> tuple[C, dict[str, object]]:
        """Verify all Product facts from the same opened installation directory."""
        try:
            with product_owner.gc_gate.guard():
                product_owner.assert_root_gc_authority_current()
                closure = self.verifier().verify_installed_root_descriptor(
                    root, version_provider=self.installed_version
                )
                receipt = self._read_product_native_release_receipt(root, product_owner)
                source = self.verifier().read_member(
                    root, _SOURCE_WHEEL_NAME, _MAX_SOURCE_WHEEL_BYTES
                )
                if (
                    sha256(source).hexdigest() != receipt["wheelSha256"]
                    or closure.native_profile_catalog_revision
                    != "h6-linux:" + str(receipt["catalogSha256"])
                    or closure.containment_launcher_digest != receipt["launcherSha256"]
                    or (closure.containment_profile_digest != receipt["profileSha256"])
                ):
                    raise self.error_type()("Worker native Product source changed")
                return (closure, receipt)
        except (
            OSError,
            UnicodeError,
            ValueError,
            TypeError,
            csv.Error,
            PackageNotFoundError,
            WorkerNativeExecutableFormatError,
        ) as exc:
            raise self.error_type()(
                "Worker native Product source cannot be verified"
            ) from exc

    def read_receipt(
        self, target: Path, product_owner: PosixLocalWheelProductSessionOwner
    ) -> dict[str, object]:
        """Read one exact Product source receipt without following a replaced name."""
        root = os.open(
            target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        try:
            return self._read_product_native_release_receipt(root, product_owner)
        finally:
            os.close(root)

    def _read_product_native_release_receipt(
        self, root: int, product_owner: PosixLocalWheelProductSessionOwner
    ) -> dict[str, object]:
        body = self.verifier().read_member(root, _RECEIPT_NAME, 4096)
        try:
            receipt = json.loads(body)
        except (UnicodeError, ValueError) as exc:
            raise self.error_type()("Worker native Product receipt is invalid") from exc
        if (
            type(receipt) is not dict
            or set(receipt)
            != {
                "catalogSha256",
                "launcherSha256",
                "profileSha256",
                "scopeId",
                "version",
                "wheelSha256",
                "recordDigest",
            }
            or receipt["scopeId"] != product_owner.policy.project_scope_id
            or (type(receipt["version"]) is not int)
            or (receipt["version"] != 1)
            or (body != canonical_json_bytes(receipt) + b"\n")
        ):
            raise self.error_type()("Worker native Product receipt changed")
        record_digest = receipt.pop("recordDigest")
        if record_digest != sha256(canonical_json_bytes(receipt)).hexdigest():
            raise self.error_type()("Worker native Product receipt changed")
        for field in (
            "catalogSha256",
            "launcherSha256",
            "profileSha256",
            "wheelSha256",
        ):
            value = receipt[field]
            if (
                not isinstance(value, str)
                or re.fullmatch("[0-9a-f]{64}", value) is None
            ):
                raise self.error_type()(
                    "Worker native Product receipt digest is invalid"
                )
        return receipt

    def current_launch_material(
        self, root_path: Path, product_owner: PosixLocalWheelProductSessionOwner
    ) -> M:
        """Reopen the Product release before giving Hosting its native locator."""
        with product_owner.gc_gate.guard():
            closure, receipt = self.verify_root(root_path, product_owner)
            decision = self.approval_owner_type()(product_owner).current()
            if (
                decision is None
                or decision.action != "approve"
                or decision.approval is None
                or (
                    decision.approval.to_dict()
                    != {
                        key: receipt[key]
                        for key in (
                            "catalogSha256",
                            "launcherSha256",
                            "profileSha256",
                            "wheelSha256",
                        )
                    }
                )
            ):
                raise self.error_type()("Worker native Product approval is not current")
            return self.material_factory()(
                launcher_path=root_path / _PACKAGE / "release" / "containment-launcher",
                closure=replace(
                    closure,
                    native_profile_catalog_revision=f"{closure.native_profile_catalog_revision}:g{decision.generation}",
                ),
            )
