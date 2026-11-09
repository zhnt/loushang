"""Internal Coding Product receipt issuance for one selected Worker candidate.

No default Session route constructs this owner. Native preparation, containment,
Capability publication, and public Worker authoring remain separate gates.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
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
from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeActivationError,
    PackageProductRuntimeBindingV1,
)
from loushang.harness.package_product.product_worker_candidate import (
    verify_product_selected_worker_candidate,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.package_product import (
    PackageProductRuntimeReadError,
    PackageProductSelectedRootReader,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.tree_transfer import (
    PackagePhysicalStagingError,
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
from .package_product_worker_opt_in import CodingWorkerOptInJournal
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
class CodingWorkerSelectedPayloadV1:
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


class CodingWorkerProductReceiptOwner(_CodingReceiptHistory):
    """Issue and recheck one Product-owned receipt under the GC/Desired gate."""

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
        self._product = product_owner
        self._runtime = runtime
        self._selected = selected
        self._opt_in = opt_in_journal
        self._native_closure_reader = native_closure_reader
        self._session_discovery_reader = session_discovery_reader
        super().__init__(
            product_owner.state_root / "worker-activation-receipts.jsonl",
            access=_CodingHistoryAccess(product_owner),
        )

    @property
    def path(self) -> Path:
        return self._path

    @property
    def product_owner(self) -> PosixLocalWheelProductSessionOwner:
        return self._product

    @property
    def product_runtime(self) -> PackageProductRuntimeBindingV1:
        """The exact selected Product runtime bound when this receipt was issued."""

        return self._runtime

    def issue(self) -> ProductWorkerActivationReceiptV1 | None:
        """Return Current on absent opt-in; otherwise issue one durable receipt."""

        with self._product.gc_gate.guard(require_write=True):
            self._product.assert_root_gc_authority_current()
            decision = self._opt_in.current(
                self._selected.snapshot.installation_key.plugin_id
            )
            if decision is None or decision.action != "allow":
                return None
            policy = self._derive(decision.opt_in)
            if policy is None:
                return None
            with self._append_position() as position:
                latest = self._latest(position.records, policy)
                if (
                    latest is not None
                    and latest.opt_in_decision_digest == decision.decision_digest
                    and latest.receipt.policy.fingerprint == policy.fingerprint
                ):
                    return latest.receipt
                next_revision = (
                    max(position.last_revision, position.checkpoint_revision) + 1
                )
                receipt = ProductWorkerActivationReceiptV1(
                    policy=policy,
                    issue_sequence=next_revision,
                    issue_nonce=secrets.token_hex(16),
                )
                self._append_record(
                    position,
                    next_revision=next_revision,
                    receipt=receipt,
                    decision=decision,
                )
                return receipt

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

    @contextmanager
    def serialized_admission(self) -> Iterator[None]:
        """Hold the same Product selection gate through Worker first effect."""

        with self._product.gc_gate.guard(require_write=True):
            yield

    def current_witness(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> ActivationWitness:
        """Reject fabricated, replaced, revoked, or stale Product receipts."""

        with self._product.gc_gate.guard():
            if (
                not isinstance(receipt, ProductWorkerActivationReceiptV1)
                or receipt.policy.session_id != self._runtime.session_id
                or receipt.policy.product_runtime_id != self._runtime.product_runtime_id
                or receipt.policy.plugin_id
                != self._selected.snapshot.installation_key.plugin_id
            ):
                return _STALE_WITNESS
            self._product.assert_root_gc_authority_current()
            record = self._latest(
                read_coding_product_worker_receipt_records(
                    self._product, retained_only=True
                ),
                receipt.policy,
            )
            if record is None or record.receipt != receipt:
                return _STALE_WITNESS
            decision = self._opt_in.current(receipt.policy.plugin_id)
            if (
                decision is None
                or decision.action != "allow"
                or decision.decision_digest != record.opt_in_decision_digest
            ):
                return _STALE_WITNESS
            try:
                current_policy = self._derive(decision.opt_in)
            except (
                CodingWorkerPolicySelectionError,
                CodingWorkerNativeClosureReadError,
                PackageProductRuntimeActivationError,
                PackageProductRuntimeReadError,
            ):
                return _STALE_WITNESS
            if (
                current_policy is None
                or current_policy.fingerprint != receipt.policy.fingerprint
            ):
                return _STALE_WITNESS
            return receipt.authority_witness

    def current_native_launch_material(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> CodingWorkerNativeLaunchMaterialV1:
        """Join an issued selected-Worker receipt to Product-owned Linux H6 bytes.

        The result only locates material for Hosting's descriptor capture. The
        activation coordinator must still hold admission through first effect.
        """

        reader = self._native_closure_reader
        if (
            not isinstance(reader, CodingProductInstalledWorkerReleaseReader)
            or reader.product_owner is not self._product
        ):
            raise CodingWorkerReceiptError("coding_worker_native_launch_unbound")
        if (
            not isinstance(receipt, ProductWorkerActivationReceiptV1)
            or receipt.policy.native_profile_id
            != CODING_PRODUCT_WORKER_NATIVE_PROFILE_ID
        ):
            raise CodingWorkerReceiptError("coding_worker_native_launch_unsupported")
        with self._product.gc_gate.guard():
            if self.current_witness(receipt) != receipt.authority_witness:
                raise CodingWorkerReceiptError("coding_worker_receipt_stale")
            try:
                material = reader.current_launch_material()
            except CodingWorkerNativeClosureReadError as exc:
                raise CodingWorkerReceiptError(
                    "coding_worker_native_launch_material_stale"
                ) from exc
            if (
                material.closure.native_profile_catalog_revision
                != receipt.policy.native_profile_catalog_revision
                or self.current_witness(receipt) != receipt.authority_witness
            ):
                raise CodingWorkerReceiptError("coding_worker_receipt_stale")
            return material

    def current_selected_payload(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> CodingWorkerSelectedPayloadV1:
        """Reread the selected Store executable under the receipt/GC gate."""

        with self._product.gc_gate.guard():
            material = self.current_native_launch_material(receipt)
            selected = self.current_selected_manifest(receipt)
            candidate = verify_product_selected_worker_candidate(
                selected,
                contribution_id=receipt.policy.contribution_id,
                native_platform="linux-x86_64",
            )
            manifest = selected.verified_manifest()
            configuration = manifest.contribution_index.items[0].worker_configuration
            assert configuration is not None
            root = manifest.root_relative_path.as_posix()
            prefix = "" if root == "." else f"{root}/"
            body = dict(selected.snapshot.files).get(
                f"{prefix}{configuration.entrypoint}"
            )
            if (
                body is None
                or material.closure.native_platform != "linux-x86_64"
                or candidate.executable_digest != sha256(body).hexdigest()
                or candidate.worker_configuration_fingerprint
                != receipt.policy.worker_configuration_fingerprint
                or selected.snapshot.root_ref.artifact_digest
                != receipt.policy.plugin_revision_digest
                or self.current_witness(receipt) != receipt.authority_witness
            ):
                raise CodingWorkerReceiptError("coding_worker_selected_payload_stale")
            return CodingWorkerSelectedPayloadV1(
                configuration=configuration,
                body=body,
                digest=candidate.executable_digest,
            )

    def current_runtime_binding(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> tuple[CodingWorkerSelectedPayloadV1, CodingWorkerNativeLaunchMaterialV1, str]:
        """Capture one coherent selected payload, native release, and owner."""

        reader = self._native_closure_reader
        if (
            not isinstance(reader, CodingProductInstalledWorkerReleaseReader)
            or reader.product_owner is not self._product
        ):
            raise CodingWorkerReceiptError("coding_worker_native_launch_unbound")
        if (
            not isinstance(receipt, ProductWorkerActivationReceiptV1)
            or receipt.policy.native_profile_id
            != CODING_PRODUCT_WORKER_NATIVE_PROFILE_ID
        ):
            raise CodingWorkerReceiptError("coding_worker_native_launch_unsupported")
        with self._product.gc_gate.guard():
            if self.current_witness(receipt) != receipt.authority_witness:
                raise CodingWorkerReceiptError("coding_worker_receipt_stale")
            try:
                material = reader.current_launch_material()
            except CodingWorkerNativeClosureReadError as exc:
                raise CodingWorkerReceiptError(
                    "coding_worker_native_launch_material_stale"
                ) from exc
            try:
                selected = self._runtime.capture_selected_plugin_manifest_for(
                    receipt.policy.plugin_id,
                    max_files=64,
                    max_total_bytes=16 * 1024 * 1024,
                )
            except (
                PackagePhysicalStagingError,
                PackageProductRuntimeActivationError,
                PackageProductRuntimeReadError,
            ) as exc:
                raise CodingWorkerReceiptError(
                    "coding_worker_selected_payload_stale"
                ) from exc
            if selected != self._selected:
                raise CodingWorkerReceiptError("coding_worker_selected_payload_stale")
            candidate = verify_product_selected_worker_candidate(
                selected,
                contribution_id=receipt.policy.contribution_id,
                native_platform="linux-x86_64",
            )
            manifest = selected.verified_manifest()
            configuration = manifest.contribution_index.items[0].worker_configuration
            assert configuration is not None
            root = manifest.root_relative_path.as_posix()
            prefix = "" if root == "." else f"{root}/"
            body = dict(selected.snapshot.files).get(
                f"{prefix}{configuration.entrypoint}"
            )
            decision = self._opt_in.current(receipt.policy.plugin_id)
            if (
                body is None
                or material.closure.native_platform != "linux-x86_64"
                or material.closure.native_profile_catalog_revision
                != receipt.policy.native_profile_catalog_revision
                or candidate.executable_digest != sha256(body).hexdigest()
                or candidate.worker_configuration_fingerprint
                != receipt.policy.worker_configuration_fingerprint
                or selected.snapshot.root_ref.artifact_digest
                != receipt.policy.plugin_revision_digest
                or decision is None
                or decision.action != "allow"
                or not isinstance(decision.opt_in, CodingWorkerOptInV1)
                or self.current_witness(receipt) != receipt.authority_witness
            ):
                raise CodingWorkerReceiptError("coding_worker_selected_payload_stale")
            return (
                CodingWorkerSelectedPayloadV1(
                    configuration=configuration,
                    body=body,
                    digest=candidate.executable_digest,
                ),
                material,
                decision.opt_in.owner_id,
            )

    def current_selected_manifest(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> PackageProductSelectedPluginManifestV1:
        """Reread the exact selected manifest under the receipt/GC gate."""

        with self._product.gc_gate.guard():
            if self.current_witness(receipt) != receipt.authority_witness:
                raise CodingWorkerReceiptError("coding_worker_receipt_stale")
            try:
                selected = self._runtime.capture_selected_plugin_manifest_for(
                    receipt.policy.plugin_id,
                    max_files=64,
                    max_total_bytes=16 * 1024 * 1024,
                )
            except (
                PackagePhysicalStagingError,
                PackageProductRuntimeActivationError,
                PackageProductRuntimeReadError,
            ) as exc:
                raise CodingWorkerReceiptError(
                    "coding_worker_selected_payload_stale"
                ) from exc
            if selected != self._selected:
                raise CodingWorkerReceiptError("coding_worker_selected_payload_stale")
            return selected

    def current_worker_owner_id(self, receipt: ProductWorkerActivationReceiptV1) -> str:
        """Resolve the accepted domain owner without accepting caller input."""

        with self._product.gc_gate.guard():
            if (
                not isinstance(receipt, ProductWorkerActivationReceiptV1)
                or self.current_witness(receipt) != receipt.authority_witness
            ):
                raise CodingWorkerReceiptError("coding_worker_receipt_stale")
            decision = self._opt_in.current(receipt.policy.plugin_id)
            if (
                decision is None
                or decision.action != "allow"
                or not isinstance(decision.opt_in, CodingWorkerOptInV1)
            ):
                raise CodingWorkerReceiptError("coding_worker_receipt_stale")
            return decision.opt_in.owner_id

    def latch_kill_switch(self, *, expected_generation: int) -> int:
        """Persist revocation before the coordinator retires future requests."""

        if type(expected_generation) is not int or expected_generation < 0:
            raise ValueError("Coding Worker kill-switch generation is invalid")
        with self._product.gc_gate.guard(require_write=True):
            self._product.assert_root_gc_authority_current()
            plugin_id = self._selected.snapshot.installation_key.plugin_id
            decision = self._opt_in.current(plugin_id)
            if decision is None:
                raise CodingWorkerReceiptError("coding_worker_kill_switch_absent")
            if (
                decision.action == "revoke"
                and decision.kill_switch_generation == expected_generation + 1
            ):
                return decision.kill_switch_generation
            if (
                decision.action != "allow"
                or decision.kill_switch_generation != expected_generation
            ):
                raise CodingWorkerReceiptError("coding_worker_kill_switch_stale")
            operation_id = (
                "worker-kill-"
                + sha256(
                    canonical_json_bytes(
                        {
                            "scopeId": self._product.policy.project_scope_id,
                            "pluginId": plugin_id,
                            "expectedGeneration": expected_generation,
                        }
                    )
                ).hexdigest()
            )
            revoked = self._opt_in.change(
                plugin_id=plugin_id,
                operation_id=operation_id,
                expected_generation=decision.generation,
                action="revoke",
                opt_in=None,
            )
            return revoked.kill_switch_generation

    def _derive(self, opt_in: object) -> ProductWorkerActivationPolicyV1 | None:
        if not isinstance(opt_in, CodingWorkerOptInV1):
            return None
        session_id = self._runtime.session_id
        runtime_id = self._runtime.product_runtime_id
        assert session_id is not None and runtime_id is not None
        native_closure = self._native_closure_reader.current_closure()
        if not isinstance(native_closure, CodingWorkerNativeClosureV1):
            raise CodingWorkerReceiptError("coding_worker_native_closure_invalid")
        session_discovery = (
            None
            if self._session_discovery_reader is None
            else self._session_discovery_reader.current_discovery()
        )
        if self._session_discovery_reader is not None and not isinstance(
            session_discovery, SessionDiscoveryMetadata
        ):
            raise CodingWorkerReceiptError("coding_worker_session_discovery_invalid")
        return derive_coding_selected_worker_policy(
            runtime=self._runtime,
            product_policy=self._product.policy,
            selected=self._selected,
            session_id=session_id,
            product_runtime_id=runtime_id,
            opt_in=opt_in,
            native_closure=native_closure,
            session_discovery=session_discovery,
        )

    @staticmethod
    def _latest(
        records: tuple[CodingWorkerReceiptRecordV1, ...],
        policy: ProductWorkerActivationPolicyV1,
    ) -> CodingWorkerReceiptRecordV1 | None:
        return next(
            (
                record
                for record in reversed(records)
                if record.receipt.policy.session_id == policy.session_id
                and record.receipt.policy.plugin_id == policy.plugin_id
            ),
            None,
        )


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
    return next(
        (
            record
            for record in read_coding_product_worker_receipt_records(
                product, retained_only=True
            )
            if record.receipt.fingerprint == receipt_fingerprint
        ),
        None,
    )


def read_coding_product_worker_receipt_records(
    product: PosixLocalWheelProductSessionOwner,
    *,
    retained_only: bool = False,
) -> tuple[CodingWorkerReceiptRecordV1, ...]:
    """Read complete V1 history or explicitly retained V2 receipts."""

    if not isinstance(product, PosixLocalWheelProductSessionOwner):
        raise TypeError("Coding Worker Product owner is required")
    path = product.state_root / "worker-activation-receipts.jsonl"
    return _CodingReceiptHistory(
        path, access=_CodingHistoryAccess(product)
    ).read_records(
        retained_only=retained_only,
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
    selected_session_file = session_manager.get_session_file()
    if (
        not session_manager.is_persisted()
        or selected_session_file is None
        or session_manager.get_header().conversation_id != runtime.session_id
        or Path(session_manager.get_cwd()).resolve(strict=True)
        != product_owner.workspace
        or not (
            transcript_directory.is_authority_session_file(selected_session_file)
            or transcript_directory.is_discovery_session_file(selected_session_file)
        )
    ):
        raise ValueError("Coding Worker selected Session owner changed")
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
