"""One-shot Product custody for an approved Linux H6 native release Wheel.

This is an internal, default-dark installation operation. The caller must
bring a separately approved exact Wheel digest; Plugin bytes cannot approve
their own native runtime. Version replacement remains a separate operation.
"""

from __future__ import annotations

import io
import json
import os
import stat
import zipfile
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
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

from .package_product_worker_installed_native import (
    _PRODUCT_NATIVE_RELEASE_ROOT,
    _RECEIPT_NAME,
    _SOURCE_WHEEL_NAME,
    CodingProductInstalledWorkerReleaseReader,
    open_coding_product_installed_worker_release_reader,
    read_coding_product_native_release_receipt,
    verify_coding_product_native_release_descriptor,
    verify_coding_product_native_release_root,
)
from .package_product_worker_native_approval import (
    CodingWorkerNativeApprovalError,
    CodingWorkerNativeApprovalJournal,
    CodingWorkerNativeReleaseApprovalV1,
    CodingWorkerNativeReleaseReviewV1,
)
from .package_product_worker_native_release import (
    CodingWorkerNativeReleaseError,
    _verify_release_bytes,
)
from .package_product_worker_policy import CodingWorkerNativeClosureV1

_MAX_WHEEL_BYTES = 4 * 1024 * 1024
_MAX_MEMBER_BYTES = 16 * 1024 * 1024
_MAX_TREE_BYTES = 17 * 1024 * 1024
_STAGE_PREFIX = ".worker-native-release-stage-"


def review_coding_product_worker_native_release(
    product_owner: PosixLocalWheelProductSessionOwner,
    *,
    wheel: bytes,
) -> CodingWorkerNativeReleaseReviewV1:
    """Verify one complete native Wheel before showing exact approval facts."""

    CodingWorkerNativeApprovalJournal(product_owner)
    if not isinstance(wheel, bytes) or not 0 < len(wheel) <= _MAX_WHEEL_BYTES:
        raise ValueError("Worker native release Wheel exceeds its bound")
    inspect_package_wheel_bytes(
        wheel,
        wheel_filename=(
            f"loushang_h6_native-{version('loushang')}-py3-none-linux_x86_64.whl"
        ),
        budgets=PackageInspectionBudgetV1(
            max_entries=16,
            max_total_expanded_bytes=_MAX_TREE_BYTES,
            max_entry_expanded_bytes=_MAX_MEMBER_BYTES,
            max_metadata_bytes=64 * 1024,
        ),
        max_artifact_bytes=_MAX_WHEEL_BYTES,
    )
    files = _verified_wheel_members(wheel)
    catalog = files["loushang_h6_native/release/catalog.json"]
    launcher = files["loushang_h6_native/release/containment-launcher"]
    closure = _verify_release_bytes(catalog, launcher)
    approval = CodingWorkerNativeReleaseApprovalV1(
        wheel_sha256=sha256(wheel).hexdigest(),
        catalog_sha256=sha256(catalog).hexdigest(),
        launcher_sha256=closure.containment_launcher_digest,
        profile_sha256=closure.containment_profile_digest,
    )
    with product_owner.gc_gate.guard():
        product_owner.assert_root_gc_authority_current()
        return CodingWorkerNativeReleaseReviewV1.create(
            scope_id=product_owner.policy.project_scope_id,
            product_policy_revision=product_owner.policy.authority_revision,
            approval=approval,
        )


def install_coding_product_worker_native_release(
    product_owner: PosixLocalWheelProductSessionOwner,
    *,
    approval_owner: CodingWorkerNativeApprovalJournal,
    approved: CodingWorkerNativeReleaseApprovalV1,
    wheel: bytes,
) -> CodingProductInstalledWorkerReleaseReader:
    """Publish only an approved exact Wheel into the Product private state."""

    if (
        not isinstance(product_owner, PosixLocalWheelProductSessionOwner)
        or not isinstance(approved, CodingWorkerNativeReleaseApprovalV1)
        or not isinstance(approval_owner, CodingWorkerNativeApprovalJournal)
        or approval_owner.product_owner is not product_owner
        or not isinstance(wheel, bytes)
        or not 0 < len(wheel) <= _MAX_WHEEL_BYTES
        or sha256(wheel).hexdigest() != approved.wheel_sha256
    ):
        raise ValueError("Worker native release approval does not match Wheel")
    files = _verified_wheel_members(wheel)
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
        _require_current_approval(approval_owner, approved)
        if not any(
            binding.source_trust_class == "local-worker-candidate"
            for binding in product_owner.policy.bindings
        ):
            raise ValueError("Coding Product Worker candidate owner is required")
        parent = product_owner.state_root
        parent_fd = os.open(
            parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        try:
            _require_private_root(parent_fd)
            target = parent / _PRODUCT_NATIVE_RELEASE_ROOT
            if any(name.startswith(_STAGE_PREFIX) for name in os.listdir(parent_fd)):
                raise CodingWorkerNativeReleaseError(
                    "Worker native release has unsettled staging debt"
                )
            if target.exists() or target.is_symlink():
                reader = open_coding_product_installed_worker_release_reader(
                    product_owner
                )
                closure = reader.current_closure()
                receipt = read_coding_product_native_release_receipt(
                    target, product_owner
                )
                if (
                    receipt["wheelSha256"] != approved.wheel_sha256
                    or receipt["catalogSha256"] != approved.catalog_sha256
                    or closure.containment_launcher_digest != approved.launcher_sha256
                    or closure.containment_profile_digest != approved.profile_sha256
                ):
                    raise CodingWorkerNativeReleaseError(
                        "Worker native release replacement requires a new operation"
                    )
                return reader
            with TemporaryDirectory(prefix=_STAGE_PREFIX, dir=parent) as raw:
                stage = Path(raw)
                _write_stage(stage, files, wheel, approved, product_owner)
                stage_fd = os.open(
                    stage.name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=parent_fd,
                )
                try:
                    closure, receipt = verify_coding_product_native_release_descriptor(
                        stage_fd, product_owner
                    )
                    _require_approved_native_release(closure, receipt, approved)
                    os.fsync(stage_fd)
                    _require_same_stage(parent_fd, stage.name, stage_fd)
                    _require_current_approval(approval_owner, approved)
                    product_owner.assert_root_gc_authority_current()
                    _require_same_product_root(parent, parent_fd)
                    _rename_directory_noreplace(
                        parent_fd, stage.name, parent_fd, _PRODUCT_NATIVE_RELEASE_ROOT
                    )
                    _require_same_stage(
                        parent_fd, _PRODUCT_NATIVE_RELEASE_ROOT, stage_fd
                    )
                    os.fsync(parent_fd)
                finally:
                    os.close(stage_fd)
            reader = open_coding_product_installed_worker_release_reader(product_owner)
            closure, receipt = verify_coding_product_native_release_root(
                target, product_owner
            )
            _require_approved_native_release(closure, receipt, approved)
            return reader
        finally:
            os.close(parent_fd)


def repair_coding_product_worker_native_release(
    product_owner: PosixLocalWheelProductSessionOwner,
    *,
    approval_owner: CodingWorkerNativeApprovalJournal,
    approved: CodingWorkerNativeReleaseApprovalV1,
) -> CodingProductInstalledWorkerReleaseReader:
    """Finish one complete staged install; preserve partial or ambiguous debt."""

    if (
        not isinstance(product_owner, PosixLocalWheelProductSessionOwner)
        or not isinstance(approved, CodingWorkerNativeReleaseApprovalV1)
        or not isinstance(approval_owner, CodingWorkerNativeApprovalJournal)
        or approval_owner.product_owner is not product_owner
    ):
        raise TypeError("Coding Product native repair owners are required")
    with product_owner.gc_gate.guard(require_write=True):
        product_owner.assert_root_gc_authority_current()
        _require_current_approval(approval_owner, approved)
        if not any(
            binding.source_trust_class == "local-worker-candidate"
            for binding in product_owner.policy.bindings
        ):
            raise ValueError("Coding Product Worker candidate owner is required")
        parent = product_owner.state_root
        parent_fd = os.open(
            parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        try:
            _require_private_root(parent_fd)
            stages = tuple(
                name for name in os.listdir(parent_fd) if name.startswith(_STAGE_PREFIX)
            )
            target = parent / _PRODUCT_NATIVE_RELEASE_ROOT
            if len(stages) != 1 or target.exists() or target.is_symlink():
                raise CodingWorkerNativeReleaseError(
                    "Worker native release repair state is ambiguous"
                )
            stage_name = stages[0]
            stage_fd = os.open(
                stage_name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent_fd,
            )
            try:
                closure, receipt = verify_coding_product_native_release_descriptor(
                    stage_fd, product_owner
                )
                _require_approved_native_release(closure, receipt, approved)
                os.fsync(stage_fd)
                _require_same_stage(parent_fd, stage_name, stage_fd)
                _require_current_approval(approval_owner, approved)
                product_owner.assert_root_gc_authority_current()
                _require_same_product_root(parent, parent_fd)
                _rename_directory_noreplace(
                    parent_fd, stage_name, parent_fd, _PRODUCT_NATIVE_RELEASE_ROOT
                )
                _require_same_stage(parent_fd, _PRODUCT_NATIVE_RELEASE_ROOT, stage_fd)
                os.fsync(parent_fd)
            finally:
                os.close(stage_fd)
            closure, receipt = verify_coding_product_native_release_root(
                target, product_owner
            )
            _require_approved_native_release(closure, receipt, approved)
            return open_coding_product_installed_worker_release_reader(product_owner)
        finally:
            os.close(parent_fd)


def _require_approved_native_release(
    closure: CodingWorkerNativeClosureV1,
    receipt: dict[str, object],
    approved: CodingWorkerNativeReleaseApprovalV1,
) -> None:
    if (
        receipt["wheelSha256"] != approved.wheel_sha256
        or receipt["catalogSha256"] != approved.catalog_sha256
        or receipt["launcherSha256"] != approved.launcher_sha256
        or receipt["profileSha256"] != approved.profile_sha256
        or closure.native_profile_catalog_revision
        != "h6-linux:" + approved.catalog_sha256
        or closure.containment_launcher_digest != approved.launcher_sha256
        or closure.containment_profile_digest != approved.profile_sha256
    ):
        raise CodingWorkerNativeReleaseError("Worker native approved release changed")


def _require_current_approval(
    owner: CodingWorkerNativeApprovalJournal,
    approved: CodingWorkerNativeReleaseApprovalV1,
) -> None:
    try:
        decision = owner.current()
    except CodingWorkerNativeApprovalError as exc:
        raise CodingWorkerNativeReleaseError(
            "Worker native Product approval is unavailable"
        ) from exc
    if (
        decision is None
        or decision.action != "approve"
        or decision.approval != approved
    ):
        raise CodingWorkerNativeReleaseError(
            "Worker native Product approval is not current"
        )


def _require_same_stage(parent_fd: int, name: str, stage_fd: int) -> None:
    opened = os.fstat(stage_fd)
    visible = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if (
        not stat.S_ISDIR(visible.st_mode)
        or opened.st_dev != visible.st_dev
        or opened.st_ino != visible.st_ino
    ):
        raise CodingWorkerNativeReleaseError("Worker native staged root changed")


def _require_same_product_root(parent: Path, parent_fd: int) -> None:
    opened = os.fstat(parent_fd)
    visible = parent.lstat()
    if opened.st_dev != visible.st_dev or opened.st_ino != visible.st_ino:
        raise CodingWorkerNativeReleaseError("Worker Product state root changed")


def _verified_wheel_members(wheel: bytes) -> dict[str, bytes]:
    dist_info = f"loushang_h6_native-{version('loushang')}.dist-info"
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
                or sum(info.file_size for info in infos) > _MAX_TREE_BYTES
            ):
                raise ValueError("Worker native Wheel members are unsupported")
            files = {}
            for info in infos:
                if (
                    info.file_size > _MAX_MEMBER_BYTES
                    or info.compress_type != zipfile.ZIP_DEFLATED
                    or not stat.S_ISREG(info.external_attr >> 16)
                    or stat.S_IMODE(info.external_attr >> 16)
                    != (
                        0o500
                        if info.filename.endswith("/containment-launcher")
                        else 0o644
                    )
                ):
                    raise ValueError("Worker native Wheel member is unsafe")
                files[info.filename] = archive.read(info)
            return files
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ValueError("Worker native Wheel is invalid") from exc


def _require_private_root(descriptor: int) -> None:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise CodingWorkerNativeReleaseError("Worker Product state root is not private")


def _write_stage(
    stage: Path,
    files: dict[str, bytes],
    wheel: bytes,
    approved: CodingWorkerNativeReleaseApprovalV1,
    product_owner: PosixLocalWheelProductSessionOwner,
) -> None:
    for name, body in sorted(files.items()):
        target = stage / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _write_new(
            target,
            body,
            mode=0o500 if name.endswith("/containment-launcher") else 0o600,
        )
    _write_new(stage / _SOURCE_WHEEL_NAME, wheel, mode=0o600)
    receipt = {
        "catalogSha256": approved.catalog_sha256,
        "launcherSha256": approved.launcher_sha256,
        "profileSha256": approved.profile_sha256,
        "scopeId": product_owner.policy.project_scope_id,
        "version": 1,
        "wheelSha256": approved.wheel_sha256,
    }
    receipt["recordDigest"] = sha256(canonical_json_bytes(receipt)).hexdigest()
    _write_new(stage / _RECEIPT_NAME, canonical_json_bytes(receipt) + b"\n", mode=0o600)
    for directory in (
        stage / "loushang_h6_native/release",
        stage / "loushang_h6_native",
        stage / f"loushang_h6_native-{version('loushang')}.dist-info",
    ):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _write_new(path: Path, body: bytes, *, mode: int) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        mode,
    )
    try:
        os.fchmod(descriptor, mode)
        view = memoryview(body)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("Worker native release write made no progress")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
