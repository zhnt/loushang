"""Read a private, offline-installed Linux H6 native Wheel for Product facts.

The Product composition must own the installation root and share its GC gate.
This reader supplies closure facts only; it cannot launch a Worker.
"""

from __future__ import annotations

import csv
import io
import json
import os
import platform
import re
import stat
import sys
from base64 import urlsafe_b64encode
from dataclasses import dataclass, replace
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.worker.native_executable_format import (
    WorkerNativeExecutableFormatError,
)

from .package_product_worker_native_approval import CodingWorkerNativeApprovalJournal
from .package_product_worker_native_release import (
    CodingWorkerNativeReleaseError,
    _read_member,
    _verify_release_bytes,
)
from .package_product_worker_policy import CodingWorkerNativeClosureV1

_PACKAGE = "loushang_h6_native"
_SAFE_MEMBER = re.compile(r"[A-Za-z0-9_.-]{1,80}\Z")
_MAX_RECORD_BYTES = 16 * 1024
_MAX_METADATA_BYTES = 64 * 1024
_MAX_LAUNCHER_BYTES = 16 * 1024 * 1024
_PRODUCT_NATIVE_RELEASE_ROOT = "worker-native-release-v1"
_SOURCE_WHEEL_NAME = "source.whl"
_RECEIPT_NAME = "product-native-release.json"
_MAX_SOURCE_WHEEL_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWorkerNativeLaunchMaterialV1:
    """Verified Product locator for Hosting's descriptor-sealing capture.

    This is not a launch capability. Hosting must capture and verify the
    launcher descriptor, and the Worker receipt must still be current.
    """

    launcher_path: Path
    closure: CodingWorkerNativeClosureV1


def open_coding_product_installed_worker_release_reader(
    product_owner: PosixLocalWheelProductSessionOwner,
) -> CodingProductInstalledWorkerReleaseReader:
    """Bind the installed native catalog to one explicit Coding Product owner."""

    if (
        not isinstance(product_owner, PosixLocalWheelProductSessionOwner)
        or product_owner.policy.product_id != "coding"
        or not any(
            binding.source_trust_class == "local-worker-candidate"
            for binding in product_owner.policy.bindings
        )
    ):
        raise ValueError("Coding Product Worker candidate owner is required")
    with product_owner.gc_gate.guard():
        product_owner.assert_root_gc_authority_current()
        reader = CodingProductInstalledWorkerReleaseReader(product_owner=product_owner)
        reader.current_closure()
        return reader


class CodingProductInstalledWorkerReleaseReader:
    """Recheck Product's retained source Wheel and receipt on each read."""

    def __init__(self, *, product_owner: PosixLocalWheelProductSessionOwner) -> None:
        self._product_owner = product_owner
        self._root = product_owner.state_root / _PRODUCT_NATIVE_RELEASE_ROOT

    @property
    def gc_gate(self) -> PluginPackageGcReservationJournal:
        return self._product_owner.gc_gate

    @property
    def product_owner(self) -> PosixLocalWheelProductSessionOwner:
        return self._product_owner

    def current_closure(self) -> CodingWorkerNativeClosureV1:
        return self.current_launch_material().closure

    def current_launch_material(self) -> CodingWorkerNativeLaunchMaterialV1:
        """Reopen the Product release before giving Hosting its native locator."""

        with self._product_owner.gc_gate.guard():
            closure, receipt = verify_coding_product_native_release_root(
                self._root, self._product_owner
            )
            decision = CodingWorkerNativeApprovalJournal(self._product_owner).current()
            if (
                decision is None
                or decision.action != "approve"
                or decision.approval is None
                or decision.approval.to_dict()
                != {
                    key: receipt[key]
                    for key in (
                        "catalogSha256",
                        "launcherSha256",
                        "profileSha256",
                        "wheelSha256",
                    )
                }
            ):
                raise CodingWorkerNativeReleaseError(
                    "Worker native Product approval is not current"
                )
            return CodingWorkerNativeLaunchMaterialV1(
                launcher_path=(
                    self._root / _PACKAGE / "release" / "containment-launcher"
                ),
                closure=replace(
                    closure,
                    native_profile_catalog_revision=(
                        f"{closure.native_profile_catalog_revision}:g{decision.generation}"
                    ),
                ),
            )


def verify_coding_product_native_release_root(
    root_path: Path, product_owner: PosixLocalWheelProductSessionOwner
) -> tuple[CodingWorkerNativeClosureV1, dict[str, object]]:
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
                return verify_coding_product_native_release_descriptor(
                    root, product_owner
                )
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
        raise CodingWorkerNativeReleaseError(
            "Worker native Product source cannot be verified"
        ) from exc


def verify_coding_product_native_release_descriptor(
    root: int, product_owner: PosixLocalWheelProductSessionOwner
) -> tuple[CodingWorkerNativeClosureV1, dict[str, object]]:
    """Verify all Product facts from the same opened installation directory."""

    try:
        with product_owner.gc_gate.guard():
            product_owner.assert_root_gc_authority_current()
            closure = _verify_installed_root_descriptor(root)
            receipt = _read_product_native_release_receipt(root, product_owner)
            source = _read_member(root, _SOURCE_WHEEL_NAME, _MAX_SOURCE_WHEEL_BYTES)
            if (
                sha256(source).hexdigest() != receipt["wheelSha256"]
                or closure.native_profile_catalog_revision
                != "h6-linux:" + str(receipt["catalogSha256"])
                or closure.containment_launcher_digest != receipt["launcherSha256"]
                or closure.containment_profile_digest != receipt["profileSha256"]
            ):
                raise CodingWorkerNativeReleaseError(
                    "Worker native Product source changed"
                )
            return closure, receipt
    except (
        OSError,
        UnicodeError,
        ValueError,
        TypeError,
        csv.Error,
        PackageNotFoundError,
        WorkerNativeExecutableFormatError,
    ) as exc:
        raise CodingWorkerNativeReleaseError(
            "Worker native Product source cannot be verified"
        ) from exc


def read_coding_product_native_release_receipt(
    target: Path, product_owner: PosixLocalWheelProductSessionOwner
) -> dict[str, object]:
    """Read one exact Product source receipt without following a replaced name."""

    root = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        return _read_product_native_release_receipt(root, product_owner)
    finally:
        os.close(root)


def _read_product_native_release_receipt(
    root: int, product_owner: PosixLocalWheelProductSessionOwner
) -> dict[str, object]:
    body = _read_member(root, _RECEIPT_NAME, 4096)
    try:
        receipt = json.loads(body)
    except (UnicodeError, ValueError) as exc:
        raise CodingWorkerNativeReleaseError(
            "Worker native Product receipt is invalid"
        ) from exc
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
        or type(receipt["version"]) is not int
        or receipt["version"] != 1
        or body != canonical_json_bytes(receipt) + b"\n"
    ):
        raise CodingWorkerNativeReleaseError("Worker native Product receipt changed")
    record_digest = receipt.pop("recordDigest")
    if record_digest != sha256(canonical_json_bytes(receipt)).hexdigest():
        raise CodingWorkerNativeReleaseError("Worker native Product receipt changed")
    for field in (
        "catalogSha256",
        "launcherSha256",
        "profileSha256",
        "wheelSha256",
    ):
        value = receipt[field]
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise CodingWorkerNativeReleaseError(
                "Worker native Product receipt digest is invalid"
            )
    return receipt


class CodingLinuxInstalledWorkerReleaseReader:
    """Reopen exact Wheel RECORD and native bytes under a private Product root."""

    def __init__(
        self,
        *,
        installation_root: Path,
        gc_gate: PluginPackageGcReservationJournal,
    ) -> None:
        if (
            not isinstance(installation_root, Path)
            or not installation_root.is_absolute()
        ):
            raise ValueError("Worker native installation root must be absolute")
        if not isinstance(gc_gate, PluginPackageGcReservationJournal):
            raise TypeError("Worker native installation requires a Product GC gate")
        self._root = installation_root
        self._gc_gate = gc_gate

    @property
    def gc_gate(self) -> PluginPackageGcReservationJournal:
        return self._gc_gate

    def current_closure(self) -> CodingWorkerNativeClosureV1:
        try:
            root = os.open(
                self._root,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            try:
                return _verify_installed_root_descriptor(root)
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
            raise CodingWorkerNativeReleaseError(
                "Installed Worker native release cannot be verified"
            ) from exc


def _verify_installed_root_descriptor(root: int) -> CodingWorkerNativeClosureV1:
    if sys.platform != "linux" or platform.machine().lower() not in {
        "x86_64",
        "amd64",
    }:
        raise CodingWorkerNativeReleaseError("Linux x86-64 release is required")
    installed_version = version("loushang")
    dist_info = f"{_PACKAGE}-{installed_version}.dist-info"
    root_stat = os.fstat(root)
    if (
        not stat.S_ISDIR(root_stat.st_mode)
        or root_stat.st_uid != os.geteuid()
        or stat.S_IMODE(root_stat.st_mode) & 0o077
    ):
        raise CodingWorkerNativeReleaseError(
            "Worker native installation root is not private"
        )
    package = _open_directory(root, _PACKAGE)
    try:
        release = _open_directory(package, "release")
        try:
            metadata = _open_directory(root, dist_info)
            try:
                files = _verify_record(
                    package=package,
                    release=release,
                    metadata=metadata,
                    dist_info=dist_info,
                    installed_version=installed_version,
                )
            finally:
                os.close(metadata)
        finally:
            os.close(release)
    finally:
        os.close(package)
    return _verify_release_bytes(
        files[f"{_PACKAGE}/release/catalog.json"],
        files[f"{_PACKAGE}/release/containment-launcher"],
    )


def _open_directory(parent: int, name: str) -> int:
    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        dir_fd=parent,
    )
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
        os.close(descriptor)
        raise CodingWorkerNativeReleaseError(
            "Installed Worker native directory is unsafe"
        )
    return descriptor


def _verify_record(
    *,
    package: int,
    release: int,
    metadata: int,
    dist_info: str,
    installed_version: str,
) -> dict[str, bytes]:
    record_name = f"{dist_info}/RECORD"
    record = _read_member(metadata, "RECORD", _MAX_RECORD_BYTES, installed=True)
    rows = tuple(csv.reader(io.StringIO(record.decode("utf-8")), strict=True))
    required = {
        f"{_PACKAGE}/__init__.py",
        f"{_PACKAGE}/release/catalog.json",
        f"{_PACKAGE}/release/containment-launcher",
        f"{dist_info}/METADATA",
        f"{dist_info}/WHEEL",
        record_name,
    }
    if not 6 <= len(rows) <= 16 or any(len(row) != 3 for row in rows):
        raise CodingWorkerNativeReleaseError("Installed Worker RECORD is invalid")
    files: dict[str, bytes] = {}
    for name, digest, size in rows:
        if name in files:
            raise CodingWorkerNativeReleaseError(
                "Installed Worker RECORD is duplicated"
            )
        if name == record_name:
            if digest or size:
                raise CodingWorkerNativeReleaseError(
                    "Installed Worker RECORD is invalid"
                )
            files[name] = record
            continue
        parts = name.split("/")
        if len(parts) == 2 and parts[0] == _PACKAGE and parts[1] == "__init__.py":
            body = _read_member(package, parts[1], 4096, installed=True)
        elif (
            len(parts) == 3
            and parts[:2] == [_PACKAGE, "release"]
            and parts[2] in {"catalog.json", "containment-launcher"}
        ):
            body = _read_member(
                release,
                parts[2],
                _MAX_LAUNCHER_BYTES if parts[2] == "containment-launcher" else 4096,
                installed=True,
                executable=parts[2] == "containment-launcher",
            )
        elif (
            len(parts) == 2
            and parts[0] == dist_info
            and _SAFE_MEMBER.fullmatch(parts[1]) is not None
        ):
            body = _read_member(metadata, parts[1], _MAX_METADATA_BYTES, installed=True)
        else:
            raise CodingWorkerNativeReleaseError(
                "Installed Worker RECORD member is unsupported"
            )
        expected = urlsafe_b64encode(sha256(body).digest()).rstrip(b"=").decode()
        if digest != f"sha256={expected}" or size != str(len(body)):
            raise CodingWorkerNativeReleaseError("Installed Worker RECORD changed")
        files[name] = body
    if not required.issubset(files):
        raise CodingWorkerNativeReleaseError("Installed Worker RECORD is incomplete")
    recorded_metadata = {
        name.split("/", 1)[1] for name in files if name.startswith(f"{dist_info}/")
    }
    if (
        set(os.listdir(package)) != {"__init__.py", "release"}
        or set(os.listdir(release)) != {"catalog.json", "containment-launcher"}
        or set(os.listdir(metadata)) != recorded_metadata
    ):
        raise CodingWorkerNativeReleaseError(
            "Installed Worker distribution contains unrecorded members"
        )
    if files[f"{_PACKAGE}/__init__.py"] != b"":
        raise CodingWorkerNativeReleaseError("Installed Worker package changed")
    expected_metadata = (
        "Metadata-Version: 2.1\n"
        "Name: loushang-h6-native\n"
        f"Version: {installed_version}\n\n"
    ).encode("ascii")
    expected_wheel = (
        "Wheel-Version: 1.0\n"
        "Generator: loushang-h6-release\n"
        "Root-Is-Purelib: false\n"
        "Tag: py3-none-linux_x86_64\n\n"
    ).encode("ascii")
    if (
        files[f"{dist_info}/METADATA"] != expected_metadata
        or files[f"{dist_info}/WHEEL"] != expected_wheel
    ):
        raise CodingWorkerNativeReleaseError(
            "Installed Worker distribution identity changed"
        )
    return files
