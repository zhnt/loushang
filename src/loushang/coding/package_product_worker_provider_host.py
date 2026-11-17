"""Private Coding Host for one owner-admitted read-only Worker Provider."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial

from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
)
from loushang.harness.session._worker_provider import (
    _PreparedWorkerProviderMethods,
    _read_worker_provider_inputs,
)
from loushang.harness.session._worker_provider import (
    _WorkerAttemptRelease as _SessionWorkerAttemptRelease,
)
from loushang.harness.worker.facet_proxy import CapabilityWorkerReadOnlyFacetProxy

from .package_product_worker_capability import CodingProductWorkerCapabilityAuthority
from .package_product_worker_provider import (
    CodingWorkerBaseCompositionPolicyBinding,
    _native_platform_for_receipt_owner,
    prepare_coding_selected_worker_provider_candidate,
)
from .package_product_worker_receipt import CodingWorkerProductReceiptOwner
from .package_product_worker_windows_receipt import (
    CodingWindowsWorkerProductReceiptOwner,
)


class CodingWorkerProviderHostError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _WorkerAttemptRelease(_SessionWorkerAttemptRelease):
    pass


_read_coding_worker_provider_inputs = partial(
    _read_worker_provider_inputs,
    receipt_owner_types=(
        CodingWorkerProductReceiptOwner,
        CodingWindowsWorkerProductReceiptOwner,
    ),
    capability_authority_type=CodingProductWorkerCapabilityAuthority,
    read_candidate=prepare_coding_selected_worker_provider_candidate,
    native_platform_for_owner=_native_platform_for_receipt_owner,
    error_type=CodingWorkerProviderHostError,
    error_prefix="coding_worker_provider",
    invalid_inputs="Coding Worker Provider Host inputs are invalid",
)


@dataclass(frozen=True, slots=True)
class CodingPreparedWorkerProvider(
    _PreparedWorkerProviderMethods[
        CodingWorkerProductReceiptOwner | CodingWindowsWorkerProductReceiptOwner,
        CodingProductWorkerCapabilityAuthority,
        CodingWorkerBaseCompositionPolicyBinding,
    ]
):
    binding: CapabilityBundleProviderBinding
    facet: CapabilityWorkerReadOnlyFacetProxy
    receipt_fingerprint: str
    worker_admission_fingerprint: str
    _release: _WorkerAttemptRelease = field(repr=False, compare=False)
    _commit: Callable[[], None] | None = field(default=None, repr=False, compare=False)

    _provider_error_type = CodingWorkerProviderHostError
    _provider_error_prefix = "coding_worker_provider"
    _provider_fingerprint_namespace = b"loushang.coding-worker-provider-binding/v1\x00"
    _provider_release_type = _WorkerAttemptRelease
    _provider_read_inputs = staticmethod(_read_coding_worker_provider_inputs)
    _provider_read_candidate = staticmethod(
        prepare_coding_selected_worker_provider_candidate
    )


prepare_coding_worker_provider_binding = CodingPreparedWorkerProvider._prepare


__all__ = [
    "CodingPreparedWorkerProvider",
    "CodingWorkerProviderHostError",
    "prepare_coding_worker_provider_binding",
]
