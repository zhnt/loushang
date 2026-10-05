"""Inert inspection of a Windows LPAC backend release candidate.

The current LPAC backend executes trusted Loushang Python code in the host
process. A release candidate therefore includes that exact Loushang Wheel and
the host Python executable and runtime DLL identities. This inspector checks
candidate bytes only; a Product owner must capture the running images, retain
the Wheel, approve it independently, and recheck both at receipt and launch.
"""

from __future__ import annotations

import io
import os
import re
import zipfile
from dataclasses import dataclass
from hashlib import sha256
from importlib.metadata import version

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    PackageInspectionBudgetV1,
    inspect_package_wheel_bytes,
)
from loushang.hosting.windows_backend_material import (
    WINDOWS_LPAC_BACKEND_CODE_MEMBERS,
    WindowsBackendMaterialExpectationV1,
    capture_windows_python_host_images,
    verify_windows_backend_material_expectation,
)

from .package_product_worker_native_approval import (
    CodingWorkerNativeReleaseApprovalV1,
    CodingWorkerNativeReleaseReviewV1,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_WHEEL_BYTES = 64 * 1024 * 1024
_MAX_MEMBERS = 8192
_MAX_TOTAL_BYTES = 128 * 1024 * 1024
_REQUIRED = frozenset(WINDOWS_LPAC_BACKEND_CODE_MEMBERS)


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerBackendCandidateV1:
    """Exact source and image digests; this grants no launch authority."""

    approval: CodingWorkerNativeReleaseApprovalV1
    package_members: tuple[tuple[str, str], ...]
    python_executable_sha256: str
    python_runtime_dll_sha256: str


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerBackendMaterialReviewV1:
    review: CodingWorkerNativeReleaseReviewV1
    expectation: WindowsBackendMaterialExpectationV1


def inspect_coding_windows_worker_backend_candidate(
    *,
    loushang_wheel: bytes,
    python_executable_sha256: str,
    python_runtime_dll_sha256: str,
) -> CodingWindowsWorkerBackendCandidateV1:
    """Verify a complete Loushang Wheel and bind supplied image identities.

    The image hashes are inert inputs. Product review must derive them from
    pinned running image handles; callers cannot approve their own values.
    """

    for value in (python_executable_sha256, python_runtime_dll_sha256):
        if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
            raise ValueError("Windows Worker Python image digest is invalid")
    if not isinstance(loushang_wheel, bytes):
        raise TypeError("Windows Worker backend Wheel must be bytes")
    wheel_version = version("loushang")
    inspected = inspect_package_wheel_bytes(
        loushang_wheel,
        wheel_filename=f"loushang-{wheel_version}-py3-none-any.whl",
        budgets=PackageInspectionBudgetV1(
            max_entries=_MAX_MEMBERS,
            max_total_expanded_bytes=_MAX_TOTAL_BYTES,
            max_entry_expanded_bytes=8 * 1024 * 1024,
            max_metadata_bytes=2 * 1024 * 1024,
            max_wall_time_ms=60_000,
        ),
        max_artifact_bytes=_MAX_WHEEL_BYTES,
    )
    if inspected.distribution != "loushang" or str(inspected.version) != wheel_version:
        raise ValueError("Windows Worker backend Wheel identity changed")
    with zipfile.ZipFile(io.BytesIO(loushang_wheel)) as archive:
        names = tuple(archive.namelist())
        package_names = sorted(
            name
            for name in names
            if name.startswith("loushang/") and not name.endswith("/")
        )
        if (
            len(names) != len(set(names))
            or not _REQUIRED.issubset(package_names)
            or len(package_names) > _MAX_MEMBERS
        ):
            raise ValueError("Windows Worker backend Wheel members are incomplete")
        package_members = tuple(
            (name, sha256(archive.read(name)).hexdigest()) for name in package_names
        )
    catalog = {
        "backendVersion": 1,
        "members": [[name, digest] for name, digest in package_members],
        "pythonExecutableSha256": python_executable_sha256,
        "pythonRuntimeDllSha256": python_runtime_dll_sha256,
        "wheelSha256": inspected.artifact_digest,
    }
    catalog_sha256 = sha256(canonical_json_bytes(catalog)).hexdigest()
    launcher_sha256 = sha256(
        canonical_json_bytes(
            {
                "pythonExecutableSha256": python_executable_sha256,
                "pythonRuntimeDllSha256": python_runtime_dll_sha256,
            }
        )
    ).hexdigest()
    profile_sha256 = dict(package_members)[
        "loushang/hosting/_windows_launch_preparation.py"
    ]
    return CodingWindowsWorkerBackendCandidateV1(
        approval=CodingWorkerNativeReleaseApprovalV1(
            wheel_sha256=inspected.artifact_digest,
            catalog_sha256=catalog_sha256,
            launcher_sha256=launcher_sha256,
            profile_sha256=profile_sha256,
        ),
        package_members=package_members,
        python_executable_sha256=python_executable_sha256,
        python_runtime_dll_sha256=python_runtime_dll_sha256,
    )


def review_coding_windows_worker_backend_release(
    product: WindowsLocalWheelProductSessionOwner, *, loushang_wheel: bytes
) -> CodingWorkerNativeReleaseReviewV1:
    """Review actual installed backend bytes under the current Product owner.

    This creates no approval or native-release installation. The Product must
    later retain the exact Wheel and compare it again with a durable decision.
    """

    return inspect_coding_windows_worker_backend_material(
        product, loushang_wheel=loushang_wheel
    ).review


def inspect_coding_windows_worker_backend_material(
    product: WindowsLocalWheelProductSessionOwner, *, loushang_wheel: bytes
) -> CodingWindowsWorkerBackendMaterialReviewV1:
    """Recheck Product material and return Hosting's exact capture expectation."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or not any(
            binding.source_trust_class == "local-worker-candidate"
            for binding in product.policy.bindings
        )
    ):
        raise ValueError("Windows Worker candidate Product owner is required")
    with product.gc_gate.guard():
        product.assert_root_gc_authority_current()
        images = capture_windows_python_host_images()
        candidate = inspect_coding_windows_worker_backend_candidate(
            loushang_wheel=loushang_wheel,
            python_executable_sha256=images.python_executable_sha256,
            python_runtime_dll_sha256=images.python_runtime_dll_sha256,
        )
        expectation = WindowsBackendMaterialExpectationV1(
            python_executable_sha256=images.python_executable_sha256,
            python_runtime_dll_sha256=images.python_runtime_dll_sha256,
            package_members=candidate.package_members,
        )
        verify_windows_backend_material_expectation(expectation)
        product.assert_root_gc_authority_current()
        return CodingWindowsWorkerBackendMaterialReviewV1(
            review=CodingWorkerNativeReleaseReviewV1.create(
                scope_id=product.policy.project_scope_id,
                product_policy_revision=product.policy.authority_revision,
                approval=candidate.approval,
            ),
            expectation=expectation,
        )


__all__ = [
    "CodingWindowsWorkerBackendCandidateV1",
    "CodingWindowsWorkerBackendMaterialReviewV1",
    "inspect_coding_windows_worker_backend_candidate",
    "inspect_coding_windows_worker_backend_material",
    "review_coding_windows_worker_backend_release",
]
