"""Coding entry adapters for approved Linux H6 Product release custody."""

from __future__ import annotations

from importlib.metadata import version
from pathlib import Path

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)

from .package_product_worker_installed_native import (
    CodingProductInstalledWorkerReleaseReader,
    _product_native_release_custody,
)
from .package_product_worker_native_approval import (
    CodingWorkerNativeApprovalJournal,
    CodingWorkerNativeReleaseApprovalV1,
    CodingWorkerNativeReleaseReviewV1,
)


def review_coding_product_worker_native_release(
    product_owner: PosixLocalWheelProductSessionOwner, *, wheel: bytes
) -> CodingWorkerNativeReleaseReviewV1:
    """Verify one complete native Wheel before showing exact approval facts."""
    return _product_native_release_custody(
        wheel_version=lambda: version("loushang")
    ).review(product_owner, wheel=wheel)


def install_coding_product_worker_native_release(
    product_owner: PosixLocalWheelProductSessionOwner,
    *,
    approval_owner: CodingWorkerNativeApprovalJournal,
    approved: CodingWorkerNativeReleaseApprovalV1,
    wheel: bytes,
) -> CodingProductInstalledWorkerReleaseReader:
    """Publish only an approved exact Wheel into the Product private state."""
    return _product_native_release_custody(
        wheel_version=lambda: version("loushang")
    ).install(
        product_owner, approval_owner=approval_owner, approved=approved, wheel=wheel
    )


def repair_coding_product_worker_native_release(
    product_owner: PosixLocalWheelProductSessionOwner,
    *,
    approval_owner: CodingWorkerNativeApprovalJournal,
    approved: CodingWorkerNativeReleaseApprovalV1,
) -> CodingProductInstalledWorkerReleaseReader:
    """Finish one complete staged install; preserve partial or ambiguous debt."""
    return _product_native_release_custody(
        wheel_version=lambda: version("loushang")
    ).repair(product_owner, approval_owner=approval_owner, approved=approved)


def _verified_wheel_members(wheel: bytes) -> dict[str, bytes]:
    return _product_native_release_custody(
        wheel_version=lambda: version("loushang")
    )._verified_wheel_members(wheel)


def _write_stage(
    stage: Path,
    files: dict[str, bytes],
    wheel: bytes,
    approved: CodingWorkerNativeReleaseApprovalV1,
    product_owner: PosixLocalWheelProductSessionOwner,
) -> None:
    return _product_native_release_custody(
        wheel_version=lambda: version("loushang")
    )._write_stage(stage, files, wheel, approved, product_owner)
