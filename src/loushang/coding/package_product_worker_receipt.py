"""Internal Coding Product receipt issuance for one selected Worker candidate.

No default Session route constructs this owner. Native preparation, containment,
Capability publication, and public Worker authoring remain separate gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from loushang.harness.journal import (
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalFormatProfile,
    JournalLoadPolicy,
    JournalRecordCodec,
)
from loushang.harness.journal._rooted_io import (
    RootedFile,
)
from loushang.harness.package_product._worker_product_authority import (
    _capture_selected_worker_session_file,
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
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.package_product import (
    PackageProductRuntimeReadError,
    PackageProductSelectedRootReader,
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
    assert_checkpoint_fingerprint_fresh,
)
from loushang.harness.worker.history._receipts import (
    _MAX_RECEIPT_SEGMENT_BYTES,
    _MAX_RECEIPTS,
    _ReceiptRecordMethods,
    decode_receipt_history,
    parse_receipt_segment,
    receipt_line,
)
from loushang.harness.worker.product_activation import (
    ActivationWitness,
    ProductWorkerActivationPolicyV1,
    ProductWorkerActivationReceiptV1,
)

from ._product_worker_canary import CODING_PRODUCT_WORKER_NATIVE_PROFILE_ID
from ._worker_history_access import _CodingHistoryAccess
from .package_product_worker_discovery import CodingWorkerTranscriptDiscoveryReader
from .package_product_worker_history_segments import (
    CodingWorkerSegmentedHistoryV1,
)
from .package_product_worker_installed_native import (
    CodingProductInstalledWorkerReleaseReader,
    CodingWorkerNativeLaunchMaterialV1,
    open_coding_product_installed_worker_release_reader,
)
from .package_product_worker_opt_in import (
    CodingWorkerOptInJournal,
)
from .package_product_worker_policy import (
    CodingWorkerNativeClosureReadError,
    CodingWorkerNativeClosureV1,
    CodingWorkerOptInV1,
    CodingWorkerPolicySelectionError,
    derive_coding_selected_worker_policy,
)
from .session_manager import SessionManager

if TYPE_CHECKING:
    from .package_product_worker_history_checkpoint import (
        CodingWorkerHistoryCheckpointV1,
    )

_STALE_WITNESS: ActivationWitness = ("0" * 64, "0" * 64, "stale", 0, 0)


class CodingWorkerNativeClosureReadPort(Protocol):
    """Product-bound native facts; changes share the selection/GC gate."""

    @property
    def gc_gate(self) -> PluginPackageGcReservationJournal: ...

    def current_closure(self) -> CodingWorkerNativeClosureV1: ...


class CodingWorkerSessionDiscoveryReadPort(Protocol):
    """Product-bound resumed Session discovery, rechecked for each witness."""

    @property
    def gc_gate(self) -> PluginPackageGcReservationJournal: ...

    @property
    def session_id(self) -> str: ...

    def current_discovery(self) -> SessionDiscoveryMetadata: ...


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


def _decode(value: object) -> CodingWorkerReceiptRecordV1:
    try:
        return CodingWorkerReceiptRecordV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Coding Worker receipt record is invalid",
            code="coding_worker_receipt_record_invalid",
        ) from exc


_CODEC: FunctionalJournalRecordCodec[CodingWorkerReceiptRecordV1] = (
    FunctionalJournalRecordCodec(
        encoder=CodingWorkerReceiptRecordV1.to_dict,
        decoder=_decode,
    )
)


class _CodingReceiptHistory(ReceiptHistory[CodingWorkerReceiptRecordV1]):
    def __init__(self, path: Path, *, access: _CodingHistoryAccess) -> None:
        from .package_product_worker_history_read_v2 import _HISTORY_READER

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

    @property
    def _record_format(self) -> JournalFormatProfile:
        return SORTED_UNICODE_JSONL_FORMAT

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

    _stale_derivation_errors = (
        CodingWorkerPolicySelectionError,
        CodingWorkerNativeClosureReadError,
        PackageProductRuntimeActivationError,
        PackageProductRuntimeReadError,
    )

    def __init__(
        self,
        *,
        product_owner: PosixLocalWheelProductSessionOwner,
        runtime: PackageProductRuntimeBindingV1,
        selected: PackageProductSelectedPluginManifestV1,
        opt_in_journal: CodingWorkerOptInJournal,
        native_closure_reader: CodingWorkerNativeClosureReadPort,
        session_discovery_reader: CodingWorkerSessionDiscoveryReadPort | None = None,
    ) -> None:
        if (
            not isinstance(product_owner, PosixLocalWheelProductSessionOwner)
            or not isinstance(runtime, PackageProductRuntimeBindingV1)
            or not isinstance(selected, PackageProductSelectedPluginManifestV1)
            or not isinstance(opt_in_journal, CodingWorkerOptInJournal)
            or not callable(getattr(native_closure_reader, "current_closure", None))
            or getattr(native_closure_reader, "gc_gate", None)
            is not product_owner.gc_gate
            or (
                session_discovery_reader is not None
                and (
                    getattr(session_discovery_reader, "gc_gate", None)
                    is not product_owner.gc_gate
                    or getattr(session_discovery_reader, "session_id", None)
                    != runtime.session_id
                    or not callable(
                        getattr(session_discovery_reader, "current_discovery", None)
                    )
                )
            )
            or product_owner.policy.product_id != "coding"
            or runtime.product_id != "coding"
            or runtime.session_id is None
            or runtime.product_runtime_id is None
            or selected.snapshot.installation_key.scope_id
            != product_owner.policy.project_scope_id
            or opt_in_journal.path != product_owner.state_root / "worker-opt-in.jsonl"
            or opt_in_journal.gc_gate is not product_owner.gc_gate
            or opt_in_journal.scope_id != product_owner.policy.project_scope_id
        ):
            raise ValueError("Coding Worker Product receipt owners changed")
        self._product: PosixLocalWheelProductSessionOwner = product_owner
        self._runtime = runtime
        self._selected = selected
        self._opt_in: CodingWorkerOptInJournal = opt_in_journal
        self._native_closure_reader = native_closure_reader
        self._session_discovery_reader = session_discovery_reader
        super().__init__(
            product_owner.state_root / "worker-activation-receipts.jsonl",
            access=_CodingHistoryAccess(product_owner),
        )

    def _checkpoint_writer_fence(
        self, rooted: RootedFile
    ) -> tuple[CodingWorkerHistoryCheckpointV1, ...]:
        return cast(
            "tuple[CodingWorkerHistoryCheckpointV1, ...]",
            super()._checkpoint_writer_fence(rooted),
        )

    @staticmethod
    def _assert_checkpoint_source(
        checkpoints: tuple[CodingWorkerHistoryCheckpointV1, ...],
        history: CodingWorkerSegmentedHistoryV1,
    ) -> int:
        from .package_product_worker_history_checkpoint import _CHECKPOINT_HISTORY

        return _CHECKPOINT_HISTORY.verify_source_revision(
            checkpoints,
            history,
            stream_index=1,
            error_type=CodingWorkerReceiptError,
            code="coding_worker_receipt_checkpoint_source_changed",
        )

    @staticmethod
    def _assert_checkpoint_fingerprint_fresh(
        checkpoints: tuple[CodingWorkerHistoryCheckpointV1, ...],
        fingerprint: str,
    ) -> None:
        assert_checkpoint_fingerprint_fresh(
            checkpoints,
            fingerprint,
            error_type=CodingWorkerReceiptError,
        )

    def latch_kill_switch(self, *, expected_generation: int) -> int:
        """Persist revocation before the coordinator retires future requests."""
        return self._latch_kill_switch(
            expected_generation=expected_generation,
            invalid_generation_message="Coding Worker kill-switch generation is invalid",
            revoke=lambda plugin_id, operation_id, decision: self._opt_in.change(
                plugin_id=plugin_id,
                operation_id=operation_id,
                expected_generation=decision.generation,
                action="revoke",
                opt_in=None,
            ),
        )

    def _history_for_product(
        self, product: PosixLocalWheelProductSessionOwner
    ) -> ReceiptHistory[CodingWorkerReceiptRecordV1]:
        return _receipt_history_for_product(product)

    def current_native_launch_material(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> CodingWorkerNativeLaunchMaterialV1:
        """Join an issued selected-Worker receipt to Product-owned Linux H6 bytes.

        The result only locates material for Hosting's descriptor capture. The
        activation coordinator must still hold admission through first effect.
        """

        return super().current_native_launch_material(receipt)

    def current_selected_payload(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> CodingWorkerSelectedPayloadV1:
        """Reread the selected Store executable under the receipt/GC gate."""

        return super().current_selected_payload(receipt)

    def current_runtime_binding(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> tuple[CodingWorkerSelectedPayloadV1, CodingWorkerNativeLaunchMaterialV1, str]:
        """Capture one coherent selected payload, native release, and owner."""

        return super().current_runtime_binding(receipt)


def read_coding_product_worker_receipt_record(
    product: PosixLocalWheelProductSessionOwner, *, receipt_fingerprint: str
) -> CodingWorkerReceiptRecordV1 | None:
    """Read one exact historical Product receipt without a Session runtime."""

    if not isinstance(product, PosixLocalWheelProductSessionOwner):
        raise TypeError("Coding Worker Product owner is required")
    if (
        type(receipt_fingerprint) is not str
        or len(receipt_fingerprint) != 64
        or any(char not in "0123456789abcdef" for char in receipt_fingerprint)
    ):
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


def open_coding_selected_worker_receipt_owner(
    *,
    product_owner: PosixLocalWheelProductSessionOwner,
    runtime: PackageProductRuntimeBindingV1,
    plugin_id: str,
    native_closure_reader: CodingWorkerNativeClosureReadPort,
    transcript_directory: AgentTranscriptDirectoryRuntime,
    session_manager: SessionManager,
    active_session: bool = False,
) -> CodingWorkerProductReceiptOwner:
    """Bind one Product candidate to its exact Coding Session owner.

    An attached active Session owns subsequent transcript appends. Detached
    selection retains the discovery locator revision as an exact snapshot.
    """

    if not isinstance(product_owner, PosixLocalWheelProductSessionOwner):
        raise TypeError("Coding Worker requires a Product owner")
    if not isinstance(runtime, PackageProductRuntimeBindingV1):
        raise TypeError("Coding Worker requires an active Product runtime")
    if (
        not isinstance(plugin_id, str)
        or not plugin_id
        or plugin_id != plugin_id.strip()
    ):
        raise ValueError("Coding Worker Plugin identity is invalid")
    if runtime.session_id is None:
        raise ValueError("Coding Worker Session identity is unavailable")
    if not isinstance(transcript_directory, AgentTranscriptDirectoryRuntime):
        raise TypeError("Coding Worker requires a Transcript directory owner")
    if not isinstance(session_manager, SessionManager):
        raise TypeError("Coding Worker requires a Coding Session owner")
    selected_session_file = _capture_selected_worker_session_file(
        session_manager=session_manager,
        transcript_directory=transcript_directory,
        runtime=runtime,
        product_owner=product_owner,
        invalid_owner="Coding Worker selected Session owner changed",
    )
    root_reader = runtime._selected_root_reader
    manifest_reader = runtime._selected_manifest_reader
    if not isinstance(root_reader, PackageProductSelectedRootReader):
        raise ValueError("Coding Worker Product runtime owners changed")
    bound_root = cast(PackageProductSelectedRootReader, root_reader)
    if (
        getattr(manifest_reader, "root_reader", None) is not bound_root
        or bound_root.desired_state is not product_owner.desired_state
        or bound_root.bindings is not product_owner.gc_bindings
        or bound_root.gc_gate is not product_owner.gc_gate
        or bound_root.product_id != product_owner.policy.product_id
        or bound_root.scope_id != product_owner.policy.project_scope_id
    ):
        raise ValueError("Coding Worker Product runtime owners changed")
    selected = runtime.capture_selected_plugin_manifest_for(
        plugin_id, max_files=16, max_total_bytes=16 * 1024 * 1024
    )
    opt_in = CodingWorkerOptInJournal(
        product_owner.state_root / "worker-opt-in.jsonl",
        scope_id=product_owner.policy.project_scope_id,
        gc_gate=product_owner.gc_gate,
        store_id=product_owner.epoch_runtime.registry.store_id,
    )
    discovery = CodingWorkerTranscriptDiscoveryReader(
        directory=transcript_directory,
        gc_gate=product_owner.gc_gate,
        session_id=runtime.session_id,
        selected_session_file=selected_session_file,
        attached_session=session_manager if active_session else None,
    )
    return CodingWorkerProductReceiptOwner(
        product_owner=product_owner,
        runtime=runtime,
        selected=selected,
        opt_in_journal=opt_in,
        native_closure_reader=native_closure_reader,
        session_discovery_reader=discovery,
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
