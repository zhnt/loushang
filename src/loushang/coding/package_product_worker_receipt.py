"""Internal Coding Product receipt issuance for one selected Worker candidate.

No default Session route constructs this owner. Native preparation, containment,
Capability publication, and public Worker authoring remain separate gates.
"""

from __future__ import annotations

import json
import os
import secrets
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Protocol, cast

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalLoadPolicy,
    append_jsonl_record,
    decode_jsonl,
)
from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO
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
from loushang.harness.worker.product_activation import (
    ActivationWitness,
    ProductWorkerActivationPolicyV1,
    ProductWorkerActivationReceiptV1,
)

from ._product_worker_canary import CODING_PRODUCT_WORKER_NATIVE_PROFILE_ID
from .package_product_worker_discovery import CodingWorkerTranscriptDiscoveryReader
from .package_product_worker_history_segments import (
    CodingWorkerHistorySegmentError,
    CodingWorkerSegmentedHistoryV1,
    read_coding_worker_segmented_history,
    seal_coding_worker_active_segment,
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

_STALE_WITNESS: ActivationWitness = ("0" * 64, "0" * 64, "stale", 0, 0)
_MAX_RECEIPTS = 4096
_MAX_RECEIPT_SEGMENT_BYTES = 32 * 1024 * 1024


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
class CodingWorkerReceiptRecordV1:
    journal_revision: int
    scope_id: str
    opt_in_decision_digest: str
    receipt: ProductWorkerActivationReceiptV1
    record_digest: str
    record_version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.journal_revision) is not int
            or self.journal_revision < 1
            or not isinstance(self.scope_id, str)
            or not self.scope_id
            or not isinstance(self.opt_in_decision_digest, str)
            or len(self.opt_in_decision_digest) != 64
            or not isinstance(self.receipt, ProductWorkerActivationReceiptV1)
            or self.receipt.issue_sequence != self.journal_revision
            or self.record_version != 1
            or self.record_digest != self._fingerprint()
        ):
            raise ValueError("Coding Worker receipt record is invalid")

    @classmethod
    def create(
        cls,
        *,
        journal_revision: int,
        scope_id: str,
        opt_in_decision_digest: str,
        receipt: ProductWorkerActivationReceiptV1,
    ) -> CodingWorkerReceiptRecordV1:
        values = {
            "journalRevision": journal_revision,
            "optInDecisionDigest": opt_in_decision_digest,
            "receipt": receipt.to_dict(),
            "recordVersion": 1,
            "scopeId": scope_id,
        }
        return cls(
            journal_revision=journal_revision,
            scope_id=scope_id,
            opt_in_decision_digest=opt_in_decision_digest,
            receipt=receipt,
            record_digest=sha256(canonical_json_bytes(values)).hexdigest(),
        )

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "journalRevision": self.journal_revision,
            "optInDecisionDigest": self.opt_in_decision_digest,
            "receipt": self.receipt.to_dict(),
            "recordVersion": self.record_version,
            "scopeId": self.scope_id,
        }

    def _fingerprint(self) -> str:
        return sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned_dict(), "recordDigest": self.record_digest}

    @classmethod
    def from_dict(cls, value: object) -> CodingWorkerReceiptRecordV1:
        fields = {
            "journalRevision",
            "optInDecisionDigest",
            "receipt",
            "recordDigest",
            "recordVersion",
            "scopeId",
        }
        if type(value) is not dict or set(value) != fields:
            raise ValueError("Coding Worker receipt record shape is invalid")
        return cls(
            journal_revision=value["journalRevision"],
            scope_id=value["scopeId"],
            opt_in_decision_digest=value["optInDecisionDigest"],
            receipt=ProductWorkerActivationReceiptV1.from_dict(value["receipt"]),
            record_digest=value["recordDigest"],
            record_version=value["recordVersion"],
        )


def _decode(value: object) -> CodingWorkerReceiptRecordV1:
    try:
        return CodingWorkerReceiptRecordV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Coding Worker receipt record is invalid",
            code="coding_worker_receipt_record_invalid",
        ) from exc


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingWorkerReceiptRecordV1.to_dict,
    decoder=_decode,
)


class CodingWorkerProductReceiptOwner:
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
        self._path = product_owner.state_root / "worker-activation-receipts.jsonl"
        self._durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="raise", create_lock=False)

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

        with self._product.gc_gate.guard():
            self._product.assert_root_gc_authority_current()
            decision = self._opt_in.current(
                self._selected.snapshot.installation_key.plugin_id
            )
            if decision is None or decision.action != "allow":
                return None
            policy = self._derive(decision.opt_in)
            if policy is None:
                return None
            with self._bound_journal() as rooted:
                records, history = _read_receipt_history(
                    rooted,
                    path=self._path,
                    scope_id=self._product.policy.project_scope_id,
                    load_policy=self._load_policy,
                )
                latest = self._latest(records, policy)
                if (
                    latest is not None
                    and latest.opt_in_decision_digest == decision.decision_digest
                    and latest.receipt.policy.fingerprint == policy.fingerprint
                ):
                    return latest.receipt
                receipt = ProductWorkerActivationReceiptV1(
                    policy=policy,
                    issue_sequence=len(records) + 1,
                    issue_nonce=secrets.token_hex(16),
                )
                record = CodingWorkerReceiptRecordV1.create(
                    journal_revision=len(records) + 1,
                    scope_id=self._product.policy.project_scope_id,
                    opt_in_decision_digest=decision.decision_digest,
                    receipt=receipt,
                )
                record_bytes = _linux_receipt_line(record)
                if len(record_bytes) > _MAX_RECEIPT_SEGMENT_BYTES:
                    raise CodingWorkerReceiptError("coding_worker_receipt_capacity")
                if (
                    len(records) - history.last_sealed_revision >= _MAX_RECEIPTS
                    or len(history.active_raw) + len(record_bytes)
                    > _MAX_RECEIPT_SEGMENT_BYTES
                ):
                    try:
                        seal_coding_worker_active_segment(
                            rooted,
                            stem="worker-activation-receipts",
                            stream_id="worker-activation-receipts",
                            history=history,
                            last_revision=len(records),
                        )
                    except CodingWorkerHistorySegmentError as exc:
                        raise CodingWorkerReceiptError(exc.code) from exc
                    target = rooted.sibling(
                        "worker-activation-receipts"
                        f".g{history.active_generation + 1:08d}.jsonl"
                    )
                else:
                    target = rooted.sibling(
                        self._path.name
                        if history.active_generation == 0
                        else "worker-activation-receipts"
                        f".g{history.active_generation:08d}.jsonl"
                    )
                append_jsonl_record(
                    self._path,
                    record,
                    record_codec=_CODEC,
                    format_profile=SORTED_UNICODE_JSONL_FORMAT,
                    durability=self._durability,
                    bound_file=target,
                )
                return receipt

    @contextmanager
    def serialized_admission(self) -> Iterator[None]:
        """Hold the same Product selection gate through Worker first effect."""

        with self._product.gc_gate.guard():
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
            with self._bound_journal() as rooted:
                record = self._latest(self._load(rooted), receipt.policy)
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
    ) -> tuple[
        CodingWorkerSelectedPayloadV1, CodingWorkerNativeLaunchMaterialV1, str
    ]:
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
        with self._product.gc_gate.guard():
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

    @contextmanager
    def _bound_journal(self) -> Iterator[RootedFile]:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        parent_fd = os.open(self._path.parent, flags)
        try:
            opened = os.fstat(parent_fd)
            visible = self._path.parent.lstat()
            if (
                not stat.S_ISDIR(opened.st_mode)
                or opened.st_uid != os.geteuid()
                or stat.S_IMODE(opened.st_mode) & 0o077
                or (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino)
            ):
                raise CodingWorkerReceiptError(
                    "coding_worker_receipt_state_root_unsafe"
                )
            file_io = RootedFileIO(self._path.parent, parent_fd)
            try:
                with file_io.bind(self._path, durable=True) as rooted:
                    rooted.acquire_lock(exclusive=True, suffix=".lock")
                    yield rooted
            finally:
                file_io.cleanup()
            visible_after = self._path.parent.lstat()
            if (opened.st_dev, opened.st_ino) != (
                visible_after.st_dev,
                visible_after.st_ino,
            ):
                raise CodingWorkerReceiptError(
                    "coding_worker_receipt_state_root_changed"
                )
        finally:
            os.close(parent_fd)

    def _load(self, rooted: RootedFile) -> tuple[CodingWorkerReceiptRecordV1, ...]:
        return _read_receipt_records(
            rooted,
            path=self._path,
            scope_id=self._product.policy.project_scope_id,
            load_policy=self._load_policy,
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
    path = product.state_root / "worker-activation-receipts.jsonl"
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    with product.gc_gate.guard():
        product.assert_root_gc_authority_current()
        root_fd = os.open(product.state_root, flags)
        try:
            opened = os.fstat(root_fd)
            visible = product.state_root.lstat()
            if (
                not stat.S_ISDIR(opened.st_mode)
                or opened.st_uid != os.geteuid()
                or stat.S_IMODE(opened.st_mode) & 0o077
                or (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino)
            ):
                raise CodingWorkerReceiptError(
                    "coding_worker_receipt_state_root_unsafe"
                )
            file_io = RootedFileIO(product.state_root, root_fd)
            try:
                with file_io.bind(path, durable=False) as rooted:
                    records = _read_receipt_records(
                        rooted,
                        path=path,
                        scope_id=product.policy.project_scope_id,
                        load_policy=JournalLoadPolicy(
                            partial_tail="raise", create_lock=False
                        ),
                    )
            finally:
                file_io.cleanup()
            visible_after = product.state_root.lstat()
            if (opened.st_dev, opened.st_ino) != (
                visible_after.st_dev,
                visible_after.st_ino,
            ):
                raise CodingWorkerReceiptError(
                    "coding_worker_receipt_state_root_changed"
                )
            return next(
                (
                    record
                    for record in records
                    if record.receipt.fingerprint == receipt_fingerprint
                ),
                None,
            )
        finally:
            os.close(root_fd)


def _read_receipt_records(
    rooted: RootedFile,
    *,
    path: Path,
    scope_id: str,
    load_policy: JournalLoadPolicy,
) -> tuple[CodingWorkerReceiptRecordV1, ...]:
    records, _history = _read_receipt_history(
        rooted,
        path=path,
        scope_id=scope_id,
        load_policy=load_policy,
    )
    return records


def _read_receipt_history(
    rooted: RootedFile,
    *,
    path: Path,
    scope_id: str,
    load_policy: JournalLoadPolicy,
) -> tuple[tuple[CodingWorkerReceiptRecordV1, ...], CodingWorkerSegmentedHistoryV1]:
    try:
        history = read_coding_worker_segmented_history(
            rooted,
            stem="worker-activation-receipts",
            stream_id="worker-activation-receipts",
            max_segment_bytes=_MAX_RECEIPT_SEGMENT_BYTES,
        )
    except CodingWorkerHistorySegmentError as exc:
        raise CodingWorkerReceiptError(exc.code) from exc
    records: list[CodingWorkerReceiptRecordV1] = []
    seen_receipts: set[str] = set()
    for generation, raw in enumerate(history.segments):
        segment_records = _decode_coding_worker_receipt_history(
            raw,
            path=path,
            scope_id=scope_id,
            load_policy=load_policy,
            first_revision=len(records) + 1,
        )
        lines = raw.splitlines(keepends=True)
        if len(lines) != len(segment_records) or any(
            line != _linux_receipt_line(record)
            for record, line in zip(segment_records, lines, strict=True)
        ):
            raise CodingWorkerReceiptError("coding_worker_receipt_corrupt")
        for record in segment_records:
            if record.receipt.fingerprint in seen_receipts:
                raise CodingWorkerReceiptError("coding_worker_receipt_corrupt")
            seen_receipts.add(record.receipt.fingerprint)
        records.extend(segment_records)
        if (
            history.manifest is not None
            and generation < history.active_generation
            and len(records) != history.manifest.sealed[generation].last_revision
        ):
            raise CodingWorkerReceiptError("coding_worker_receipt_corrupt")
    return tuple(records), history


def _linux_receipt_line(record: CodingWorkerReceiptRecordV1) -> bytes:
    return (
        json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")
        + b"\n"
    )


def _decode_coding_worker_receipt_history(
    raw: bytes,
    *,
    path: Path,
    scope_id: str,
    load_policy: JournalLoadPolicy,
    first_revision: int = 1,
) -> tuple[CodingWorkerReceiptRecordV1, ...]:
    """Replay one Product scope's receipt history across platform journals."""

    if len(raw) > _MAX_RECEIPT_SEGMENT_BYTES:
        raise CodingWorkerReceiptError("coding_worker_receipt_capacity")
    records: tuple[CodingWorkerReceiptRecordV1, ...] = decode_jsonl(
        raw.decode("utf-8"),
        target=path,
        record_codec=_CODEC,
        load_policy=load_policy,
    ).records
    if len(records) > _MAX_RECEIPTS:
        raise CodingWorkerReceiptError("coding_worker_receipt_capacity")
    seen_receipts: set[str] = set()
    for revision, record in enumerate(records, first_revision):
        if (
            record.journal_revision != revision
            or record.scope_id != scope_id
            or record.receipt.fingerprint in seen_receipts
        ):
            raise CodingWorkerReceiptError("coding_worker_receipt_corrupt")
        seen_receipts.add(record.receipt.fingerprint)
    return records


def open_coding_selected_worker_receipt_owner(
    *,
    product_owner: PosixLocalWheelProductSessionOwner,
    runtime: PackageProductRuntimeBindingV1,
    plugin_id: str,
    native_closure_reader: CodingWorkerNativeClosureReadPort,
    transcript_directory: AgentTranscriptDirectoryRuntime,
    session_manager: SessionManager,
) -> CodingWorkerProductReceiptOwner:
    """Bind one resumed candidate to Product selection and its Coding Session."""

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
    )
    discovery = CodingWorkerTranscriptDiscoveryReader(
        directory=transcript_directory,
        gc_gate=product_owner.gc_gate,
        session_id=runtime.session_id,
        selected_session_file=selected_session_file,
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
]
