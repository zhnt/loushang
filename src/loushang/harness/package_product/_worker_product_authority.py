"Complete Product Worker receipt custody using existing history/native owners.\n\nProduct DTOs and selection policy remain caller bindings. These fixed platform\nprograms hold only the original owner's state; no additional runtime is created.\n"

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import ClassVar, Generic, Protocol, TypeVar

from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
    PosixLocalWheelProductSessionOwner,
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeActivationError,
    PackageProductRuntimeBindingV1,
)
from loushang.harness.package_product.product_worker_candidate import (
    ProductWorkerNativeClosureFacts,
    ProductWorkerNativeLaunchMaterialFacts,
    ProductWorkerOptInFacts,
    ProductWorkerSelectedPayloadFacts,
    WorkerPackageCandidateV1,
    _capture_worker_opt_in_selection,
    _read_product_selected_worker_payload_facts,
    verify_product_selected_worker_candidate,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.package_product import (
    PackageProductRuntimeReadError,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.tree_transfer import (
    PackagePhysicalStagingError,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelBindingV1,
    PackageProductLocalWheelPolicy,
    PackageProductLocalWorkerAdmissionV1,
)
from loushang.harness.resources.plugins.declarations import (
    PluginLocalWorkerConfiguration,
)
from loushang.harness.transcript.discovery import SessionDiscoveryMetadata
from loushang.harness.worker._native_profile_bridge import (
    _plan_windows_lpac_product_worker_profile,
    _WindowsLpacProductWorkerProfilePlan,
)
from loushang.harness.worker.contracts import ManagedWorkerLaunchRequestV1
from loushang.harness.worker.history._opt_in import (
    CurrentOptIn,
    _OptInDecisionMethods,
    _OptInValue,
)
from loushang.harness.worker.history._receipt_store import ReceiptHistory
from loushang.harness.worker.history._receipts import (
    _ReceiptRecordMethods,
    latest_receipt_record,
)
from loushang.harness.worker.history._windows_record_journals import (
    WindowsOptInRecords,
    WindowsReceiptRecords,
)
from loushang.harness.worker.product_activation import (
    ActivationWitness,
    ProductWorkerActivationPolicyV1,
    ProductWorkerActivationReceiptV1,
)
from loushang.hosting.windows_backend_material import (
    WINDOWS_LPAC_PLATFORM_IMPORTS,
    WindowsBackendMaterialExpectationV1,
)

from ._windows_worker_backend_release import _WindowsBackendInstalledMethods

_STALE_WITNESS: ActivationWitness = ("0" * 64, "0" * 64, "stale", 0, 0)
R = TypeVar("R", bound=_ReceiptRecordMethods)
D = TypeVar("D", bound=_OptInDecisionMethods)
P = TypeVar("P", bound=_OptInValue)
PayloadT = TypeVar("PayloadT", bound=ProductWorkerSelectedPayloadFacts)
MaterialT = TypeVar("MaterialT", bound=ProductWorkerNativeLaunchMaterialFacts)
MaterialCo = TypeVar(
    "MaterialCo", bound=ProductWorkerNativeLaunchMaterialFacts, covariant=True
)


class ProductNativeClosureReadPort(Protocol):
    @property
    def gc_gate(self) -> PluginPackageGcReservationJournal: ...
    def current_closure(self) -> ProductWorkerNativeClosureFacts: ...


class ProductNativeLaunchReadPort(ProductNativeClosureReadPort, Protocol[MaterialCo]):
    @property
    def product_owner(self) -> PosixLocalWheelProductSessionOwner: ...
    def current_launch_material(self) -> MaterialCo: ...


class ProductSessionDiscoveryReadPort(Protocol):
    @property
    def gc_gate(self) -> PluginPackageGcReservationJournal: ...
    @property
    def session_id(self) -> str: ...
    def current_discovery(self) -> SessionDiscoveryMetadata: ...


class _ProductWorkerReceiptAuthority(Generic[PayloadT]):
    _product: PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner
    _runtime: PackageProductRuntimeBindingV1
    _selected: PackageProductSelectedPluginManifestV1
    _opt_in: CurrentOptIn
    _stale_derivation_errors: ClassVar[tuple[type[Exception], ...]]
    _receipt_error: ClassVar[type[RuntimeError]]
    _error_prefix: ClassVar[str]
    _product_id: ClassVar[str]
    _max_files: ClassVar[int]
    _max_total_bytes: ClassVar[int]
    _opt_in_type: ClassVar[type[ProductWorkerOptInFacts]]
    _native_closure_type: ClassVar[type[ProductWorkerNativeClosureFacts]]

    def _make_payload(
        self, *, configuration: PluginLocalWorkerConfiguration, body: bytes, digest: str
    ) -> PayloadT:
        raise NotImplementedError

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
        raise NotImplementedError

    def _read_current_receipt_record(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> _ReceiptRecordMethods | None:
        raise NotImplementedError

    def _derive(self, opt_in: object) -> ProductWorkerActivationPolicyV1 | None:
        raise NotImplementedError

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
            record = self._read_current_receipt_record(receipt)
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
            except self._stale_derivation_errors:
                return _STALE_WITNESS
            if (
                current_policy is None
                or current_policy.fingerprint != receipt.policy.fingerprint
            ):
                return _STALE_WITNESS
            return receipt.authority_witness

    def current_worker_owner_id(self, receipt: ProductWorkerActivationReceiptV1) -> str:
        """Resolve the accepted domain owner without accepting caller input."""

        with self._product.gc_gate.guard():
            if (
                not isinstance(receipt, ProductWorkerActivationReceiptV1)
                or self.current_witness(receipt) != receipt.authority_witness
            ):
                raise self._receipt_error(self._error_prefix + "receipt_stale")
            decision = self._opt_in.current(receipt.policy.plugin_id)
            if (
                decision is None
                or decision.action != "allow"
                or not isinstance(decision.opt_in, self._opt_in_type)
            ):
                raise self._receipt_error(self._error_prefix + "receipt_stale")
            return decision.opt_in.owner_id

    def _latch_kill_switch(
        self,
        *,
        expected_generation: int,
        invalid_generation_message: str,
        revoke: Callable[[str, str, _OptInDecisionMethods], _OptInDecisionMethods],
    ) -> int:
        """Persist revocation before the coordinator retires future requests."""

        if type(expected_generation) is not int or expected_generation < 0:
            raise ValueError(invalid_generation_message)
        with self._product.gc_gate.guard(require_write=True):
            self._product.assert_root_gc_authority_current()
            plugin_id = self._selected.snapshot.installation_key.plugin_id
            decision = self._opt_in.current(plugin_id)
            if decision is None:
                raise self._receipt_error(self._error_prefix + "kill_switch_absent")
            if (
                decision.action == "revoke"
                and decision.kill_switch_generation == expected_generation + 1
            ):
                return decision.kill_switch_generation
            if (
                decision.action != "allow"
                or decision.kill_switch_generation != expected_generation
            ):
                raise self._receipt_error(self._error_prefix + "kill_switch_stale")
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
            revoked = revoke(plugin_id, operation_id, decision)
            return revoked.kill_switch_generation

    def _capture_selected_manifest_under_gc_guard(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> PackageProductSelectedPluginManifestV1:
        """Capture the selected root after the caller has checked the receipt."""

        try:
            selected = self._runtime.capture_selected_plugin_manifest_for(
                receipt.policy.plugin_id,
                max_files=self._max_files,
                max_total_bytes=self._max_total_bytes,
            )
        except (
            PackagePhysicalStagingError,
            PackageProductRuntimeActivationError,
            PackageProductRuntimeReadError,
        ) as exc:
            raise self._receipt_error(
                self._error_prefix + "selected_payload_stale"
            ) from exc
        if selected != self._selected:
            raise self._receipt_error(self._error_prefix + "selected_payload_stale")
        return selected

    @staticmethod
    def _selected_worker_payload_is_stale(
        receipt: ProductWorkerActivationReceiptV1,
        selected: PackageProductSelectedPluginManifestV1,
        candidate: WorkerPackageCandidateV1,
        body: bytes,
    ) -> bool:
        if candidate.executable_digest != sha256(body).hexdigest():
            return True
        if (
            candidate.worker_configuration_fingerprint
            != receipt.policy.worker_configuration_fingerprint
        ):
            return True
        return bool(
            selected.snapshot.root_ref.artifact_digest
            != receipt.policy.plugin_revision_digest
        )


class _PosixWorkerProductReceiptAuthority(
    ReceiptHistory[R],
    _ProductWorkerReceiptAuthority[PayloadT],
    Generic[R, PayloadT, MaterialT],
):
    _product: PosixLocalWheelProductSessionOwner
    _native_closure_reader: ProductNativeClosureReadPort
    _session_discovery_reader: ProductSessionDiscoveryReadPort | None
    _native_reader_type: type[ProductNativeLaunchReadPort[MaterialT]]
    _native_error: ClassVar[type[Exception]]
    _native_profile_id: ClassVar[str]

    def _history_for_product(
        self, product: PosixLocalWheelProductSessionOwner
    ) -> ReceiptHistory[R]:
        raise NotImplementedError

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
            return self._issue_recorded_receipt(policy, decision)

    @contextmanager
    def serialized_admission(self) -> Iterator[None]:
        """Hold the same Product selection gate through Worker first effect."""

        with self._product.gc_gate.guard(require_write=True):
            yield

    def _read_current_receipt_record(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> R | None:
        self._product.assert_root_gc_authority_current()
        return self._latest(
            self._history_for_product(self._product).read_records(retained_only=True),
            receipt.policy,
        )

    def _require_native_receipt_reader(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> ProductNativeLaunchReadPort[MaterialT]:
        reader = self._native_closure_reader
        if (
            not isinstance(reader, self._native_reader_type)
            or reader.product_owner is not self._product
        ):
            raise self._receipt_error(self._error_prefix + "native_launch_unbound")
        if (
            not isinstance(receipt, ProductWorkerActivationReceiptV1)
            or receipt.policy.native_profile_id != self._native_profile_id
        ):
            raise self._receipt_error(self._error_prefix + "native_launch_unsupported")
        return reader

    def _read_native_receipt_material_under_gc_guard(
        self,
        reader: ProductNativeLaunchReadPort[MaterialT],
        receipt: ProductWorkerActivationReceiptV1,
    ) -> MaterialT:
        if self.current_witness(receipt) != receipt.authority_witness:
            raise self._receipt_error(self._error_prefix + "receipt_stale")
        try:
            material = reader.current_launch_material()
        except self._native_error as exc:
            raise self._receipt_error(
                self._error_prefix + "native_launch_material_stale"
            ) from exc
        return material

    def current_native_launch_material(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> MaterialT:
        """Join an issued selected-Worker receipt to Product-owned Linux H6 bytes.

        The result only locates material for Hosting's descriptor capture. The
        activation coordinator must still hold admission through first effect.
        """
        reader = self._require_native_receipt_reader(receipt)
        with self._product.gc_gate.guard():
            material = self._read_native_receipt_material_under_gc_guard(
                reader, receipt
            )
            if (
                material.closure.native_profile_catalog_revision
                != receipt.policy.native_profile_catalog_revision
                or self.current_witness(receipt) != receipt.authority_witness
            ):
                raise self._receipt_error(self._error_prefix + "receipt_stale")
            return material

    def current_selected_payload(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> PayloadT:
        """Reread the selected Store executable under the receipt/GC gate."""
        with self._product.gc_gate.guard():
            material = self.current_native_launch_material(receipt)
            selected = self.current_selected_manifest(receipt)
            candidate, configuration, body = (
                _read_product_selected_worker_payload_facts(
                    selected,
                    contribution_id=receipt.policy.contribution_id,
                    native_platform="linux-x86_64",
                )
            )
            if (
                body is None
                or material.closure.native_platform != "linux-x86_64"
                or self._selected_worker_payload_is_stale(
                    receipt, selected, candidate, body
                )
                or (self.current_witness(receipt) != receipt.authority_witness)
            ):
                raise self._receipt_error(self._error_prefix + "selected_payload_stale")
            return self._make_payload(
                configuration=configuration,
                body=body,
                digest=candidate.executable_digest,
            )

    def current_runtime_binding(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> tuple[PayloadT, MaterialT, str]:
        """Capture one coherent selected payload, native release, and owner."""
        reader = self._require_native_receipt_reader(receipt)
        with self._product.gc_gate.guard():
            material = self._read_native_receipt_material_under_gc_guard(
                reader, receipt
            )
            selected = self._capture_selected_manifest_under_gc_guard(receipt)
            candidate, configuration, body = (
                _read_product_selected_worker_payload_facts(
                    selected,
                    contribution_id=receipt.policy.contribution_id,
                    native_platform="linux-x86_64",
                )
            )
            decision = self._opt_in.current(receipt.policy.plugin_id)
            if (
                body is None
                or material.closure.native_platform != "linux-x86_64"
                or material.closure.native_profile_catalog_revision
                != receipt.policy.native_profile_catalog_revision
                or self._selected_worker_payload_is_stale(
                    receipt, selected, candidate, body
                )
                or (decision is None)
                or (decision.action != "allow")
                or (not isinstance(decision.opt_in, self._opt_in_type))
                or (self.current_witness(receipt) != receipt.authority_witness)
            ):
                raise self._receipt_error(self._error_prefix + "selected_payload_stale")
            return (
                self._make_payload(
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
                raise self._receipt_error(self._error_prefix + "receipt_stale")
            selected = self._capture_selected_manifest_under_gc_guard(receipt)
            return selected

    def _derive(self, opt_in: object) -> ProductWorkerActivationPolicyV1 | None:
        if not isinstance(opt_in, self._opt_in_type):
            return None
        session_id = self._runtime.session_id
        runtime_id = self._runtime.product_runtime_id
        assert session_id is not None and runtime_id is not None
        native_closure = self._native_closure_reader.current_closure()
        if not isinstance(native_closure, self._native_closure_type):
            raise self._receipt_error(self._error_prefix + "native_closure_invalid")
        session_discovery = (
            None
            if self._session_discovery_reader is None
            else self._session_discovery_reader.current_discovery()
        )
        if self._session_discovery_reader is not None and not isinstance(
            session_discovery, SessionDiscoveryMetadata
        ):
            raise self._receipt_error(self._error_prefix + "session_discovery_invalid")
        return self._derive_domain_policy(
            runtime=self._runtime,
            product_policy=self._product.policy,
            selected=self._selected,
            session_id=session_id,
            product_runtime_id=runtime_id,
            opt_in=opt_in,
            native_closure=native_closure,
            session_discovery=session_discovery,
        )


class _WindowsWorkerProductReceiptAuthority(
    _ProductWorkerReceiptAuthority[PayloadT], Generic[R, PayloadT]
):
    _product: WindowsLocalWheelProductSessionOwner
    _journal: WindowsReceiptRecords[R]
    _native: ProductNativeClosureReadPort
    _session_discovery_reader: ProductSessionDiscoveryReadPort | None

    def _read_backend(
        self, product: WindowsLocalWheelProductSessionOwner
    ) -> _WindowsBackendInstalledMethods:
        raise NotImplementedError

    @property
    def product_owner(self) -> WindowsLocalWheelProductSessionOwner:
        return self._product

    @property
    def product_runtime(self) -> PackageProductRuntimeBindingV1:
        return self._runtime

    def issue(self) -> ProductWorkerActivationReceiptV1 | None:
        """Return Current on absent opt-in, otherwise persist exact authority."""

        with self._product.gc_gate.guard(require_write=True):
            self._product.assert_session_runtime_current(self._runtime)
            self._runtime.assert_selected_plugin_manifest_current(self._selected)
            decision = self._opt_in.current(
                self._selected.snapshot.installation_key.plugin_id
            )
            if decision is None or decision.action != "allow":
                return None
            policy = self._derive(decision.opt_in)
            if policy is None:
                return None
            with (
                self._product.epoch_runtime.borrow_product_state_root_descriptor() as root
            ):
                receipt = self._journal.issue(
                    directory_fd=root,
                    policy=policy,
                    opt_in_decision_digest=decision.decision_digest,
                )
            self._product.assert_session_runtime_current(self._runtime)
            return receipt

    @contextmanager
    def serialized_admission(self) -> Iterator[None]:
        """Hold Product selection and GC through the first Worker effect."""

        with self._product.gc_gate.guard(require_write=True):
            self._product.assert_session_runtime_current(self._runtime)
            yield

    def _read_current_receipt_record(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> R | None:
        self._product.assert_session_runtime_current(self._runtime)
        with self._product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            records = self._journal.records(directory_fd=root)
        return self._latest(records, receipt.policy)

    def current_backend_capture_expectation(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> WindowsBackendMaterialExpectationV1:
        """Derive Hosting's expectation only from a current Product receipt."""

        with self._product.gc_gate.guard():
            if (
                not isinstance(receipt, ProductWorkerActivationReceiptV1)
                or self.current_witness(receipt) != receipt.authority_witness
            ):
                raise self._receipt_error(self._error_prefix + "receipt_stale")
            material = self._read_backend(self._product)
            closure = material.native_closure()
            if (
                closure.native_profile_catalog_revision
                != receipt.policy.native_profile_catalog_revision
                or self.current_witness(receipt) != receipt.authority_witness
            ):
                raise self._receipt_error(self._error_prefix + "receipt_stale")
            return material.expectation

    def current_selected_manifest(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> PackageProductSelectedPluginManifestV1:
        """Reread exactly the selected Store revision under Product custody."""

        with self._product.gc_gate.guard():
            if (
                not isinstance(receipt, ProductWorkerActivationReceiptV1)
                or self.current_witness(receipt) != receipt.authority_witness
            ):
                raise self._receipt_error(self._error_prefix + "receipt_stale")
            return self._capture_selected_manifest_under_gc_guard(receipt)

    def _payload_from_selected(
        self,
        receipt: ProductWorkerActivationReceiptV1,
        selected: PackageProductSelectedPluginManifestV1,
    ) -> PayloadT:
        candidate, configuration, body = _read_product_selected_worker_payload_facts(
            selected,
            contribution_id=receipt.policy.contribution_id,
            native_platform="windows-amd64",
        )
        if (
            body is None
            or _ProductWorkerReceiptAuthority._selected_worker_payload_is_stale(
                receipt, selected, candidate, body
            )
        ):
            raise self._receipt_error(self._error_prefix + "selected_payload_stale")
        return self._make_payload(
            configuration=configuration, body=body, digest=candidate.executable_digest
        )

    def current_selected_payload(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> PayloadT:
        """Read verified Windows PE bytes from the current Product selection."""

        with self._product.gc_gate.guard():
            self.current_backend_capture_expectation(receipt)
            selected = self.current_selected_manifest(receipt)
            payload = self._payload_from_selected(receipt, selected)
            if self.current_witness(receipt) != receipt.authority_witness:
                raise self._receipt_error(self._error_prefix + "selected_payload_stale")
            return payload

    def current_payload_and_worker_owner_id(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> tuple[PayloadT, str]:
        """Capture payload and owner in one Product read with two full rechecks.

        Each witness verifies the complete installed backend. The selected
        root is captured between them; the final witness rechecks receipt and
        opt-in authority before either value is returned.
        """

        with self._product.gc_gate.guard():
            if (
                not isinstance(receipt, ProductWorkerActivationReceiptV1)
                or self.current_witness(receipt) != receipt.authority_witness
            ):
                raise self._receipt_error(self._error_prefix + "receipt_stale")
            selected = self._capture_selected_manifest_under_gc_guard(receipt)
            payload = self._payload_from_selected(receipt, selected)
            decision = self._opt_in.current(receipt.policy.plugin_id)
            if (
                decision is None
                or decision.action != "allow"
                or not isinstance(decision.opt_in, self._opt_in_type)
                or self.current_witness(receipt) != receipt.authority_witness
            ):
                raise self._receipt_error(self._error_prefix + "receipt_stale")
            return payload, decision.opt_in.owner_id

    def plan_current_native_attempt(
        self,
        receipt: ProductWorkerActivationReceiptV1,
        worker_request: ManagedWorkerLaunchRequestV1,
    ) -> _WindowsLpacProductWorkerProfilePlan:
        """Build one LPAC plan from Product facts, including Hosting recheck."""

        if not isinstance(worker_request, ManagedWorkerLaunchRequestV1):
            raise TypeError("Windows Worker native request is invalid")
        with self._product.gc_gate.guard():
            expectation = self.current_backend_capture_expectation(receipt)
            candidate = verify_product_selected_worker_candidate(
                self._selected,
                contribution_id=receipt.policy.contribution_id,
                native_platform="windows-amd64",
            )
            identity = worker_request.identity
            if (
                identity.product_id != self._product_id
                or identity.scope_id != receipt.policy.product_scope_id
                or identity.plugin_id != receipt.policy.plugin_id
                or identity.plugin_revision_digest
                != receipt.policy.plugin_revision_digest
                or identity.contribution_id != receipt.policy.contribution_id
                or identity.owner_generation
                != receipt.policy.owner_selection_generation
                or worker_request.runtime.executable_digest
                != candidate.executable_digest
            ):
                raise self._receipt_error(self._error_prefix + "native_request_stale")
            material = self._read_backend(self._product)
            if worker_request.runtime.package_root.parent != self._product.state_root:
                raise self._receipt_error(
                    self._error_prefix + "native_payload_root_changed"
                )
            plan = _plan_windows_lpac_product_worker_profile(
                worker_request=worker_request,
                native_profile_catalog_revision=(
                    receipt.policy.native_profile_catalog_revision
                ),
                containment_launcher_sha256=(material.review.approval.launcher_sha256),
                platform_imports=WINDOWS_LPAC_PLATFORM_IMPORTS,
                backend_material_expectation=expectation,
                release_profile_sha256=material.review.approval.profile_sha256,
                owner_private_ancestors=True,
            )
            if (
                plan.expected_native_policy_closure_fingerprint
                != receipt.policy.expected_native_policy_closure_fingerprint
                or self.current_witness(receipt) != receipt.authority_witness
            ):
                raise self._receipt_error(self._error_prefix + "native_plan_stale")
            return plan

    def _derive(self, opt_in: object) -> ProductWorkerActivationPolicyV1 | None:
        if not isinstance(opt_in, self._opt_in_type):
            return None
        session_id = self._runtime.session_id
        runtime_id = self._runtime.product_runtime_id
        assert session_id is not None and runtime_id is not None
        session_discovery = (
            None
            if self._session_discovery_reader is None
            else self._session_discovery_reader.current_discovery()
        )
        if self._session_discovery_reader is not None and not isinstance(
            session_discovery, SessionDiscoveryMetadata
        ):
            raise self._receipt_error(self._error_prefix + "session_discovery_invalid")
        return self._derive_domain_policy(
            runtime=self._runtime,
            product_policy=self._product.policy,
            selected=self._selected,
            session_id=session_id,
            product_runtime_id=runtime_id,
            opt_in=opt_in,
            native_closure=self._native.current_closure(),
            session_discovery=session_discovery,
        )

    @staticmethod
    def _latest(
        records: tuple[R, ...],
        policy: ProductWorkerActivationPolicyV1,
    ) -> R | None:
        return latest_receipt_record(records, policy)


class _WindowsWorkerProductOptInAuthority(Generic[D, P]):
    _product: WindowsLocalWheelProductSessionOwner
    _journal: WindowsOptInRecords[D, P]
    _opt_in_error: ClassVar[type[RuntimeError]]
    _error_prefix: ClassVar[str]
    _product_id: ClassVar[str]
    _requiredness_error: ClassVar[str]
    _selection_error_prefix: ClassVar[str]

    def _read_backend(
        self, product: WindowsLocalWheelProductSessionOwner
    ) -> _WindowsBackendInstalledMethods:
        raise NotImplementedError

    def _plan_allow(
        self,
        previous: D | None,
        *,
        binding: PackageProductLocalWheelBindingV1,
        admission: PackageProductLocalWorkerAdmissionV1,
        plugin_id: str,
        operation_id: str,
        expected_generation: int,
        require_worker: bool,
    ) -> P:
        raise NotImplementedError

    def current(self, plugin_id: str) -> D | None:
        with self._product.gc_gate.guard():
            self._product.assert_root_gc_authority_current()
            with (
                self._product.epoch_runtime.borrow_product_state_root_descriptor() as root
            ):
                decision = self._journal.current(plugin_id, directory_fd=root)
            self._product.assert_root_gc_authority_current()
            return decision

    def allow(
        self,
        *,
        plugin_id: str,
        operation_id: str,
        expected_generation: int,
        require_worker: bool,
    ) -> D:
        """Record only the selected candidate with an approved installed backend."""

        if type(require_worker) is not bool:
            raise TypeError(self._requiredness_error)
        with self._product.gc_gate.guard(require_write=True):
            binding, admission = _capture_worker_opt_in_selection(
                self._product,
                plugin_id,
                product_id=self._product_id,
                error_type=self._opt_in_error,
                error_prefix=self._selection_error_prefix,
            )
            closure = self._read_backend(self._product).native_closure()
            if closure.native_platform != admission.native_platform:
                raise self._opt_in_error(
                    self._error_prefix + "opt_in_native_platform_changed"
                )
            with (
                self._product.epoch_runtime.borrow_product_state_root_descriptor() as root
            ):
                previous = self._journal.current(plugin_id, directory_fd=root)
                opt_in = self._plan_allow(
                    previous,
                    binding=binding,
                    admission=admission,
                    plugin_id=plugin_id,
                    operation_id=operation_id,
                    expected_generation=expected_generation,
                    require_worker=require_worker,
                )
                return self._journal.change(
                    directory_fd=root,
                    plugin_id=plugin_id,
                    operation_id=operation_id,
                    expected_generation=expected_generation,
                    action="allow",
                    opt_in=opt_in,
                )

    def revoke(
        self,
        *,
        plugin_id: str,
        operation_id: str,
        expected_generation: int,
    ) -> D:
        """Persist a kill generation even if the release has disappeared."""

        with self._product.gc_gate.guard(require_write=True):
            self._product.assert_root_gc_authority_current()
            with (
                self._product.epoch_runtime.borrow_product_state_root_descriptor() as root
            ):
                decision = self._journal.change(
                    directory_fd=root,
                    plugin_id=plugin_id,
                    operation_id=operation_id,
                    expected_generation=expected_generation,
                    action="revoke",
                    opt_in=None,
                )
            self._product.assert_root_gc_authority_current()
            return decision


_CrashProductT = TypeVar(
    "_CrashProductT",
    PosixLocalWheelProductSessionOwner,
    WindowsLocalWheelProductSessionOwner,
)


class ClosedProductWorkerCrashRecoveryAuthority(Generic[_CrashProductT]):
    """Provide Product serialization while refusing fresh activation authority."""

    _admission_error: str

    def __init__(self, product: _CrashProductT) -> None:
        self._product: _CrashProductT = product

    @contextmanager
    def serialized_admission(self) -> Iterator[None]:
        with self._product.gc_gate.guard(require_write=True):
            self._product.assert_root_gc_authority_current()
            yield
            self._product.assert_root_gc_authority_current()

    def current_witness(
        self, _receipt: ProductWorkerActivationReceiptV1
    ) -> ActivationWitness:
        return _STALE_WITNESS

    def latch_kill_switch(self, *, expected_generation: int) -> int:
        raise ValueError(self._admission_error)
