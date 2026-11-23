"""Internal Coding Product receipt issuance for one selected Worker candidate.

No default Session route constructs this owner. Native preparation, containment,
Capability publication, and public Worker authoring remain separate gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from loushang.coding.hosted._worker_canary import (
    CODING_PRODUCT_WORKER_NATIVE_PROFILE_ID,
)
from loushang.coding.package.worker_history_access import _CodingHistoryAccess
from loushang.coding.session.manager import SessionManager
from loushang.harness.journal import (
    SORTED_UNICODE_JSONL_FORMAT as SORTED_UNICODE_JSONL_FORMAT,
)
from loushang.harness.journal import (
    FunctionalJournalRecordCodec,
    JournalLoadPolicy,
    JournalRecordCodec,
)
from loushang.harness.package_product._worker_product_authority import (
    ProductNativeClosureReadPort,
    ProductSessionDiscoveryReadPort,
    _PosixWorkerProductReceiptAuthority,
    _ProductWorkerReceiptAuthority,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeActivationError,
    PackageProductRuntimeBindingV1,
)
from loushang.harness.package_product.product_worker_candidate import (
    ProductWorkerNativeClosureFacts,
    ProductWorkerOptInFacts,
    ProductWorkerSelectedPayloadFacts,
)
from loushang.harness.plugin_management.package_product import (
    PackageProductRuntimeReadError,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelPolicy,
)
from loushang.harness.resources.plugins.declarations import (
    PluginLocalWorkerConfiguration,
)
from loushang.harness.transcript.directory import AgentTranscriptDirectoryRuntime
from loushang.harness.transcript.discovery import SessionDiscoveryMetadata
from loushang.harness.worker.history._receipt_store import (
    ReceiptHistory,
)
from loushang.harness.worker.history._receipts import (
    _MAX_RECEIPT_SEGMENT_BYTES,
    _MAX_RECEIPTS,
    _ReceiptRecordMethods,
    decode_receipt_history,
    is_receipt_fingerprint,
    parse_receipt_segment,
    receipt_line,
)
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationPolicyV1,
    ProductWorkerActivationReceiptV1,
)

from .product_worker_discovery import CodingWorkerTranscriptDiscoveryReader
from .product_worker_installed_native import (
    CodingProductInstalledWorkerReleaseReader,
    CodingWorkerNativeLaunchMaterialV1,
    open_coding_product_installed_worker_release_reader,
)
from .product_worker_opt_in import CodingWorkerOptInJournal
from .product_worker_policy import (
    CodingWorkerNativeClosureReadError,
    CodingWorkerNativeClosureV1,
    CodingWorkerOptInV1,
    CodingWorkerPolicySelectionError,
    derive_coding_selected_worker_policy,
)


class CodingWorkerNativeClosureReadPort(ProductNativeClosureReadPort, Protocol):
    """Product-bound native facts; changes share the selection/GC gate."""

    def current_closure(self) -> CodingWorkerNativeClosureV1: ...


class CodingWorkerSessionDiscoveryReadPort(ProductSessionDiscoveryReadPort, Protocol):
    """Product-bound resumed Session discovery, rechecked for each witness."""


class CodingWorkerReceiptError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWorkerSelectedPayloadV1(ProductWorkerSelectedPayloadFacts):
    """Fresh Product Store bytes for one receipt; no executable authority."""

    configuration: PluginLocalWorkerConfiguration
    body: bytes
    digest: str


@dataclass(frozen=True, slots=True)
class CodingWorkerReceiptRecordV1(_ReceiptRecordMethods):
    journal_revision: int
    scope_id: str
    opt_in_decision_digest: str
    receipt: ProductWorkerActivationReceiptV1
    record_digest: str
    record_version: int = 1


_CODEC = FunctionalJournalRecordCodec.with_decode_error(
    encoder=CodingWorkerReceiptRecordV1.to_dict,
    decoder=lambda value: CodingWorkerReceiptRecordV1.from_dict(value),
    message="Coding Worker receipt record is invalid",
    code="coding_worker_receipt_record_invalid",
)


class _CodingReceiptHistory(ReceiptHistory[CodingWorkerReceiptRecordV1]):
    def __init__(self, path: Path, *, access: _CodingHistoryAccess) -> None:
        from .product_worker_history_read_v2 import _HISTORY_READER

        super().__init__(
            path,
            access=access,
            history_reader=_HISTORY_READER,
            error_type=CodingWorkerReceiptError,
        )

    @property
    def _record_type(self) -> type[CodingWorkerReceiptRecordV1]:
        return CodingWorkerReceiptRecordV1

    @property
    def _record_codec(self) -> JournalRecordCodec[CodingWorkerReceiptRecordV1]:
        return _CODEC

    def _max_history_records(self) -> int:
        return _MAX_RECEIPTS

    def _max_history_bytes(self) -> int:
        return _MAX_RECEIPT_SEGMENT_BYTES


class _CodingWorkerReceiptAuthority(
    _ProductWorkerReceiptAuthority[CodingWorkerSelectedPayloadV1]
):
    _receipt_error = CodingWorkerReceiptError
    _error_prefix = "coding_worker_"
    _product_id = "coding"
    _receipt_session_label = "Coding Session owner"
    _receipt_session_type = staticmethod(lambda: SessionManager)
    _receipt_discovery_type = staticmethod(lambda: CodingWorkerTranscriptDiscoveryReader)
    _receipt_manifest_max_files = 16
    _receipt_manifest_max_bytes = 16 * 1024 * 1024
    _max_files = 64
    _max_total_bytes = 16 * 1024 * 1024
    _opt_in_type = CodingWorkerOptInV1
    _native_closure_type = CodingWorkerNativeClosureV1
    _native_profile_id = CODING_PRODUCT_WORKER_NATIVE_PROFILE_ID

    def _make_payload(
        self, *, configuration: PluginLocalWorkerConfiguration, body: bytes, digest: str
    ) -> CodingWorkerSelectedPayloadV1:
        return CodingWorkerSelectedPayloadV1(
            configuration=configuration, body=body, digest=digest
        )

    def _derive_domain_policy(
        self,
        *,
        runtime: PackageProductRuntimeBindingV1,
        product_policy: PackageProductLocalWheelPolicy,
        selected: PackageProductSelectedPluginManifestV1,
        session_id: str,
        product_runtime_id: str,
        opt_in: ProductWorkerOptInFacts,
        native_closure: ProductWorkerNativeClosureFacts,
        session_discovery: SessionDiscoveryMetadata | None,
    ) -> ProductWorkerActivationPolicyV1 | None:
        return derive_coding_selected_worker_policy(
            runtime=runtime,
            product_policy=product_policy,
            selected=selected,
            session_id=session_id,
            product_runtime_id=product_runtime_id,
            opt_in=cast(CodingWorkerOptInV1, opt_in),
            native_closure=cast(CodingWorkerNativeClosureV1, native_closure),
            session_discovery=session_discovery,
        )


class CodingWorkerProductReceiptOwner(
    _CodingReceiptHistory,
    _PosixWorkerProductReceiptAuthority[
        CodingWorkerReceiptRecordV1,
        CodingWorkerSelectedPayloadV1,
        CodingWorkerNativeLaunchMaterialV1,
    ],
    _CodingWorkerReceiptAuthority,
):
    """Issue/recheck through the original storage and Core authority."""

    _native_reader_type = CodingProductInstalledWorkerReleaseReader
    _native_error = CodingWorkerNativeClosureReadError

    _receipt_factory_label = "Coding Worker"
    _receipt_opt_in_journal_type = staticmethod(lambda: CodingWorkerOptInJournal)

    _stale_derivation_errors = (
        CodingWorkerPolicySelectionError,
        CodingWorkerNativeClosureReadError,
        PackageProductRuntimeActivationError,
        PackageProductRuntimeReadError,
    )

    _opt_in: CodingWorkerOptInJournal
    _receipt_history_initialize = _CodingReceiptHistory.__init__
    _receipt_history_access = staticmethod(_CodingHistoryAccess)

    __init__ = _PosixWorkerProductReceiptAuthority._initialize_receipt_owner

    def _history_for_product(
        self, product: PosixLocalWheelProductSessionOwner
    ) -> ReceiptHistory[CodingWorkerReceiptRecordV1]:
        return _receipt_history_for_product(product)


def read_coding_product_worker_receipt_record(
    product: PosixLocalWheelProductSessionOwner, *, receipt_fingerprint: str
) -> CodingWorkerReceiptRecordV1 | None:
    """Read one exact historical Product receipt without a Session runtime."""

    if not isinstance(product, PosixLocalWheelProductSessionOwner):
        raise TypeError("Coding Worker Product owner is required")
    if not is_receipt_fingerprint(receipt_fingerprint):
        raise ValueError("Coding Worker receipt fingerprint is invalid")
    return _receipt_history_for_product(product).find_retained_record(
        receipt_fingerprint
    )


def read_coding_product_worker_receipt_records(
    product: PosixLocalWheelProductSessionOwner,
    *,
    retained_only: bool = False,
) -> tuple[CodingWorkerReceiptRecordV1, ...]:
    """Read complete V1 history or explicitly retained V2 receipts."""

    return _receipt_history_for_product(product).read_records(
        retained_only=retained_only
    )


_linux_receipt_line = receipt_line


def _decode_coding_worker_receipt_history(
    raw: bytes,
    *,
    path: Path,
    scope_id: str,
    load_policy: JournalLoadPolicy,
    first_revision: int = 1,
) -> tuple[CodingWorkerReceiptRecordV1, ...]:
    return decode_receipt_history(
        raw,
        path=path,
        scope_id=scope_id,
        load_policy=load_policy,
        first_revision=first_revision,
        record_codec=_CODEC,
        error_type=CodingWorkerReceiptError,
        max_receipts=_MAX_RECEIPTS,
        max_segment_bytes=_MAX_RECEIPT_SEGMENT_BYTES,
    )


def _parse_receipt_segment(
    raw: bytes,
    *,
    scope_id: str,
    first_revision: int,
) -> tuple[CodingWorkerReceiptRecordV1, ...]:
    return parse_receipt_segment(
        raw,
        scope_id=scope_id,
        first_revision=first_revision,
        record_codec=_CODEC,
        error_type=CodingWorkerReceiptError,
        max_receipts=_MAX_RECEIPTS,
        max_segment_bytes=_MAX_RECEIPT_SEGMENT_BYTES,
    )


open_coding_selected_worker_receipt_owner = (
    CodingWorkerProductReceiptOwner._open_selected
)


def open_coding_product_selected_worker_receipt_owner(
    *,
    product_owner: PosixLocalWheelProductSessionOwner,
    runtime: PackageProductRuntimeBindingV1,
    plugin_id: str,
    transcript_directory: AgentTranscriptDirectoryRuntime,
    session_manager: SessionManager,
    active_session: bool = False,
) -> CodingWorkerProductReceiptOwner:
    """Open native closure from Product custody for one selected Session.

    This path accepts no caller-provided launcher digest, profile digest,
    release directory, or native-closure reader.
    """

    native_reader = open_coding_product_installed_worker_release_reader(product_owner)
    return open_coding_selected_worker_receipt_owner(
        product_owner=product_owner,
        runtime=runtime,
        plugin_id=plugin_id,
        native_closure_reader=native_reader,
        transcript_directory=transcript_directory,
        session_manager=session_manager,
        active_session=active_session,
    )


__all__ = [
    "CodingWorkerNativeClosureReadPort",
    "CodingWorkerProductReceiptOwner",
    "CodingWorkerReceiptError",
    "CodingWorkerReceiptRecordV1",
    "CodingWorkerSessionDiscoveryReadPort",
    "open_coding_product_selected_worker_receipt_owner",
    "open_coding_selected_worker_receipt_owner",
    "read_coding_product_worker_receipt_record",
    "read_coding_product_worker_receipt_records",
]


def _receipt_history_for_product(
    product: PosixLocalWheelProductSessionOwner,
) -> _CodingReceiptHistory:
    """Admit the original Product and construct its existing history owner."""
    if not isinstance(product, PosixLocalWheelProductSessionOwner):
        raise TypeError("Coding Worker Product owner is required")
    path = product.state_root / "worker-activation-receipts.jsonl"
    return _CodingReceiptHistory(path, access=_CodingHistoryAccess(product))
