"""Windows backend release custody in the existing PackageProduct component.

Uses existing Wheel, Windows receipt, approval and Hosting material authorities.
The private slotted method providers hold no descriptors, state or launch rights.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable
from hashlib import sha256
from importlib.metadata import version
from typing import Any, ClassVar, Protocol, Self, TypeVar, cast

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages._private_receipts_windows import (
    WindowsPrivateReceiptIO,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    PackageInspectionBudgetV1,
    inspect_package_wheel_bytes,
)
from loushang.harness.worker.history._native_approval import (
    _DIGEST,
    _NativeApprovalMethods,
    _NativeDecision,
    _NativeReviewMethods,
)
from loushang.hosting.windows_backend_material import (
    WINDOWS_LPAC_BACKEND_CODE_MEMBERS,
    WindowsBackendMaterialExpectationV1,
    capture_windows_python_host_images,
    verify_windows_backend_material_expectation,
)


class _ApprovalOwner(Protocol):
    def __init__(self, product: WindowsLocalWheelProductSessionOwner) -> None: ...
    def current(self) -> _NativeDecision | None: ...


_N = TypeVar("_N", bound=_NativeDecision)
_N_co = TypeVar("_N_co", bound=_NativeDecision, covariant=True)


class _CurrentJournal(Protocol[_N_co]):
    def current(self, *, directory_fd: int) -> _N_co | None: ...


class _BackendReview(Protocol):
    @property
    def approval(self) -> _NativeApprovalMethods: ...
    @property
    def review_id(self) -> str: ...


_REQUIRED = frozenset(WINDOWS_LPAC_BACKEND_CODE_MEMBERS)


def current_windows_backend_approval(
    product: WindowsLocalWheelProductSessionOwner,
    journal: _CurrentJournal[_N],
) -> _N | None:
    with product.gc_gate.guard():
        product.assert_root_gc_authority_current()
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            decision = journal.current(directory_fd=root)
        product.assert_root_gc_authority_current()
        return decision


class _WindowsBackendCandidateMethods:
    __slots__ = ()
    approval: _NativeApprovalMethods
    package_members: tuple[tuple[str, str], ...]
    _wheel_limit: ClassVar[int]
    _member_limit: ClassVar[int]
    _total_limit: ClassVar[int]
    _approval_type: ClassVar[type[_NativeApprovalMethods]]

    @classmethod
    def _inspect(
        cls,
        *,
        loushang_wheel: bytes,
        python_executable_sha256: str,
        python_runtime_dll_sha256: str,
    ) -> Self:
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
                max_entries=cls._member_limit,
                max_total_expanded_bytes=cls._total_limit,
                max_entry_expanded_bytes=8 * 1024 * 1024,
                max_metadata_bytes=2 * 1024 * 1024,
                max_wall_time_ms=60_000,
            ),
            max_artifact_bytes=cls._wheel_limit,
        )
        if (
            inspected.distribution != "loushang"
            or str(inspected.version) != wheel_version
        ):
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
                or len(package_names) > cls._member_limit
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
        return cast(Callable[..., Self], cls)(
            approval=cast(Callable[..., _NativeApprovalMethods], cls._approval_type)(
                wheel_sha256=inspected.artifact_digest,
                catalog_sha256=catalog_sha256,
                launcher_sha256=launcher_sha256,
                profile_sha256=profile_sha256,
            ),
            package_members=package_members,
            python_executable_sha256=python_executable_sha256,
            python_runtime_dll_sha256=python_runtime_dll_sha256,
        )


class _WindowsBackendMaterialMethods:
    __slots__ = ()
    review: _BackendReview
    expectation: WindowsBackendMaterialExpectationV1
    _candidate_type: ClassVar[type[_WindowsBackendCandidateMethods]]
    _review_type: ClassVar[type[_NativeReviewMethods[Any]]]
    _admit_product: ClassVar[Callable[[WindowsLocalWheelProductSessionOwner], None]]

    @classmethod
    def _inspect_material(
        cls, product: WindowsLocalWheelProductSessionOwner, *, loushang_wheel: bytes
    ) -> Self:
        cls._admit_product(product)
        with product.gc_gate.guard():
            product.assert_root_gc_authority_current()
            images = capture_windows_python_host_images()
            candidate = cls._candidate_type._inspect(
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
            return cast(Callable[..., Self], cls)(
                review=cls._review_type.create(
                    scope_id=product.policy.project_scope_id,
                    product_policy_revision=product.policy.authority_revision,
                    approval=candidate.approval,
                ),
                expectation=expectation,
            )


class _WindowsBackendInstalledMethods:
    __slots__ = ()
    review: _BackendReview
    approval_generation: int
    expectation: WindowsBackendMaterialExpectationV1
    _material_type: ClassVar[type[_WindowsBackendMaterialMethods]]
    _approval_owner_type: ClassVar[type[_ApprovalOwner]]
    _receipt_io: ClassVar[WindowsPrivateReceiptIO]
    _release_name: ClassVar[str]
    _wheel_limit: ClassVar[int]
    _failure: ClassVar[type[RuntimeError]]
    _read_errors: ClassVar[tuple[type[BaseException], ...]]

    @classmethod
    def _install(
        cls,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        loushang_wheel: bytes,
        review_id: str,
    ) -> Self:
        if (
            type(loushang_wheel) is not bytes
            or not 0 < len(loushang_wheel) <= cls._wheel_limit
            or type(review_id) is not str
        ):
            raise ValueError("Windows Worker backend installation input is invalid")
        with product.gc_gate.guard(require_write=True):
            product.assert_root_gc_authority_current()
            material = cls._material_type._inspect_material(
                product, loushang_wheel=loushang_wheel
            )
            review = material.review
            if review.review_id != review_id:
                raise cls._failure("Windows Worker backend review changed")
            generation = cls._current_approval_generation(product, review)
            with product.epoch_runtime.borrow_product_state_root_descriptor():
                path = product.state_root / cls._release_name
                existing = cls._receipt_io.read_private_receipt(
                    path,
                    maximum_bytes=cls._wheel_limit,
                    allow_unpublished_stage=True,
                )
                if existing is None:
                    cls._receipt_io.write_private_receipt(
                        path, loushang_wheel, maximum_bytes=cls._wheel_limit
                    )
                elif existing != loushang_wheel:
                    raise cls._failure(
                        "Windows Worker backend replacement requires a new operation"
                    )
                retained = cls._receipt_io.read_private_receipt(
                    path, maximum_bytes=cls._wheel_limit
                )
                if retained != loushang_wheel:
                    raise cls._failure("Windows Worker backend Product source changed")
            product.assert_root_gc_authority_current()
            if cls._current_approval_generation(product, review) != generation:
                raise cls._failure("Windows Worker backend approval changed")
            return cast(Callable[..., Self], cls)(
                review=review,
                approval_generation=generation,
                expectation=material.expectation,
            )

    @classmethod
    def _read(cls, product: WindowsLocalWheelProductSessionOwner) -> Self:
        try:
            with product.gc_gate.guard():
                product.assert_root_gc_authority_current()
                with product.epoch_runtime.borrow_product_state_root_descriptor():
                    wheel = cls._receipt_io.read_private_receipt(
                        (product.state_root / cls._release_name),
                        maximum_bytes=cls._wheel_limit,
                    )
                if wheel is None:
                    raise cls._failure(
                        "Windows Worker backend Product source is absent"
                    )
                material = cls._material_type._inspect_material(
                    product, loushang_wheel=wheel
                )
                review = material.review
                generation = cls._current_approval_generation(product, review)
                product.assert_root_gc_authority_current()
                return cast(Callable[..., Self], cls)(
                    review=review,
                    approval_generation=generation,
                    expectation=material.expectation,
                )
        except cls._read_errors as exc:
            raise cls._failure(
                "Windows Worker backend Product source cannot be verified"
            ) from exc

    @classmethod
    def _current_approval_generation(
        cls,
        product: WindowsLocalWheelProductSessionOwner,
        review: _BackendReview,
    ) -> int:
        decision = cls._approval_owner_type(product).current()
        if (
            decision is None
            or decision.action != "approve"
            or decision.approval != review.approval
        ):
            raise cls._failure("Windows Worker backend Product approval is not current")
        return decision.generation
