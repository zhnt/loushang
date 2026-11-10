"""Inert inspection of a Windows LPAC backend release candidate.

The current LPAC backend executes trusted Loushang Python code in the host
process. A release candidate therefore includes that exact Loushang Wheel and
the host Python executable and runtime DLL identities. This inspector checks
candidate bytes only; a Product owner must capture the running images, retain
the Wheel, approve it independently, and recheck both at receipt and launch.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from loushang.harness.package_product._windows_worker_backend_release import (
    _WindowsBackendCandidateMethods,
    _WindowsBackendMaterialMethods,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.hosting.windows_backend_material import (
    WindowsBackendMaterialExpectationV1,
)

from .package_product_worker_native_approval import (
    CodingWorkerNativeReleaseApprovalV1,
    CodingWorkerNativeReleaseReviewV1,
)

_MAX_WHEEL_BYTES = 64 * 1024 * 1024
_MAX_MEMBERS = 8192
_MAX_TOTAL_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerBackendCandidateV1(_WindowsBackendCandidateMethods):
    """Exact source and image digests; this grants no launch authority."""

    approval: CodingWorkerNativeReleaseApprovalV1
    package_members: tuple[tuple[str, str], ...]
    python_executable_sha256: str
    python_runtime_dll_sha256: str


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerBackendMaterialReviewV1(_WindowsBackendMaterialMethods):
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
    return CodingWindowsWorkerBackendCandidateV1._inspect(
        loushang_wheel=loushang_wheel,
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
    return CodingWindowsWorkerBackendMaterialReviewV1._inspect_material(
        product, loushang_wheel=loushang_wheel
    )


__all__ = [
    "CodingWindowsWorkerBackendCandidateV1",
    "CodingWindowsWorkerBackendMaterialReviewV1",
    "inspect_coding_windows_worker_backend_candidate",
    "inspect_coding_windows_worker_backend_material",
    "review_coding_windows_worker_backend_release",
]


def _require_candidate_product(product: WindowsLocalWheelProductSessionOwner) -> None:
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


CodingWindowsWorkerBackendCandidateV1._wheel_limit = _MAX_WHEEL_BYTES
CodingWindowsWorkerBackendCandidateV1._member_limit = _MAX_MEMBERS
CodingWindowsWorkerBackendCandidateV1._total_limit = _MAX_TOTAL_BYTES
CodingWindowsWorkerBackendCandidateV1._approval_type = (
    CodingWorkerNativeReleaseApprovalV1
)
CodingWindowsWorkerBackendMaterialReviewV1._candidate_type = (
    CodingWindowsWorkerBackendCandidateV1
)
CodingWindowsWorkerBackendMaterialReviewV1._review_type = (
    CodingWorkerNativeReleaseReviewV1
)
CodingWindowsWorkerBackendMaterialReviewV1._admit_product = staticmethod(
    _require_candidate_product
)
