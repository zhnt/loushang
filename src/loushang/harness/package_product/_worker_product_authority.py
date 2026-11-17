"Complete Product Worker receipt custody using existing history/native owners.\n\nProduct DTOs and selection policy remain caller bindings. These fixed platform\nprograms hold only the original owner's state; no additional runtime is created.\n"

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    ClassVar,
    Generic,
    Literal,
    Protocol,
    Self,
    TypeVar,
    cast,
)

from loushang.harness.capabilities.contracts import CapabilityDefinition
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderCandidateEnvelope,
    CapabilityWorkerProviderBindingSpec,
)
from loushang.harness.capabilities.providers import CapabilityBundleProvider
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
from loushang.harness.plugin_management.current_preview import (
    plugin_package_revision_fingerprint,
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
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelBindingV1,
    PackageProductLocalWheelPolicy,
    PackageProductLocalWorkerAdmissionV1,
)
from loushang.harness.resources.plugins.declarations import (
    PluginLocalWorkerConfiguration,
)
from loushang.harness.transcript.directory import AgentTranscriptDirectoryRuntime
from loushang.harness.transcript.discovery import SessionDiscoveryMetadata
from loushang.harness.worker._native_profile_bridge import (
    _plan_windows_lpac_product_worker_profile,
    _require_exact_binding,
    _WindowsLpacProductWorkerProfilePlan,
)
from loushang.harness.worker.capability_query import (
    CapabilityWorkerAuthorityV1,
    CapabilityWorkerBindingV1,
    CapabilityWorkerFacetGrantV1,
)
from loushang.harness.worker.contracts import ManagedWorkerLaunchRequestV1
from loushang.harness.worker.facet_owner import (
    CapabilityWorkerFacetOwnerError,
    CapabilityWorkerFacetOwnerPolicy,
)
from loushang.harness.worker.gated_start import (
    WorkerGatedStartWitnessV1,
    WorkerNativeProcessIdentityV1,
)
from loushang.harness.worker.history._opt_in import (
    CurrentOptIn,
    _OptInDecisionMethods,
    _OptInValue,
)
from loushang.harness.worker.history._opt_in_store import OptInJournal
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

if TYPE_CHECKING:
    from loushang.harness.transcript._attached_discovery import (
        _AttachedTranscriptReadPort,
    )


_STALE_WITNESS: ActivationWitness = ("0" * 64, "0" * 64, "stale", 0, 0)
R = TypeVar("R", bound=_ReceiptRecordMethods)
D = TypeVar("D", bound=_OptInDecisionMethods)
P = TypeVar("P", bound=_OptInValue)
PayloadT = TypeVar("PayloadT", bound=ProductWorkerSelectedPayloadFacts)
MaterialT = TypeVar("MaterialT", bound=ProductWorkerNativeLaunchMaterialFacts)
MaterialCo = TypeVar(
    "MaterialCo", bound=ProductWorkerNativeLaunchMaterialFacts, covariant=True
)


def _capture_selected_worker_session_file(
    *,
    session_manager: _AttachedTranscriptReadPort,
    transcript_directory: AgentTranscriptDirectoryRuntime,
    runtime: PackageProductRuntimeBindingV1,
    product_owner: PosixLocalWheelProductSessionOwner
    | WindowsLocalWheelProductSessionOwner,
    invalid_owner: str,
) -> Path:
    selected_session_file = session_manager.get_session_file()
    if (
        not session_manager.is_persisted()
        or selected_session_file is None
        or session_manager.get_header().conversation_id != runtime.session_id
        or (
            Path(session_manager.get_cwd()).resolve(strict=True)
            != product_owner.workspace
        )
        or (
            not (
                transcript_directory.is_authority_session_file(selected_session_file)
                or transcript_directory.is_discovery_session_file(selected_session_file)
            )
        )
    ):
        raise ValueError(invalid_owner)
    return selected_session_file


def _derive_product_selected_worker_policy(
    *,
    runtime: PackageProductRuntimeBindingV1,
    product_policy: PackageProductLocalWheelPolicy,
    selected: PackageProductSelectedPluginManifestV1,
    session_id: str,
    product_runtime_id: str,
    opt_in: ProductWorkerOptInFacts | None,
    native_closure: ProductWorkerNativeClosureFacts | None = None,
    session_discovery: SessionDiscoveryMetadata | None = None,
    product_id: str,
    source_trust_class: str,
    opt_in_type: type[ProductWorkerOptInFacts],
    native_closure_type: type[ProductWorkerNativeClosureFacts],
    native_profiles: Mapping[str, str],
    session_scope_id: Callable[[str], str],
    session_fingerprint: Callable[[SessionDiscoveryMetadata], str],
    activation_policy: Callable[..., ProductWorkerActivationPolicyV1],
    error_type: type[RuntimeError],
    error_prefix: str,
) -> ProductWorkerActivationPolicyV1 | None:
    """Recheck Product selection and derive one explicit, authority-free policy."""
    if opt_in is None:
        return None
    if (
        not isinstance(runtime, PackageProductRuntimeBindingV1)
        or not isinstance(product_policy, PackageProductLocalWheelPolicy)
        or (not isinstance(selected, PackageProductSelectedPluginManifestV1))
        or (not isinstance(opt_in, opt_in_type))
        or (not isinstance(native_closure, native_closure_type))
        or (opt_in.native_platform != native_closure.native_platform)
        or (runtime.product_id != product_id)
        or (runtime.session_id != session_id)
        or (runtime.product_runtime_id != product_runtime_id)
        or (product_policy.product_id != product_id)
        or (selected.snapshot.installation_key.product_id != product_id)
        or (
            selected.snapshot.installation_key.scope_id
            != product_policy.project_scope_id
        )
        or (selected.snapshot.installation_key.plugin_id != opt_in.plugin_id)
        or (selected.snapshot.root_ref.artifact_digest != opt_in.artifact_digest)
        or (not isinstance(session_id, str))
        or (not session_id)
        or (not isinstance(product_runtime_id, str))
        or (not product_runtime_id)
    ):
        raise error_type(error_prefix + "product_selection_invalid")
    trust = selected.source_trust_snapshot
    if selected.snapshot.committed_record.closure_lock.node_count != 1:
        raise error_type(error_prefix + "dependency_activation_unsupported")
    if (
        trust is None
        or not trust.trusted
        or trust.source_trust_class != source_trust_class
        or (trust.source_trust_policy_revision != product_policy.authority_revision)
    ):
        raise error_type(error_prefix + "product_trust_changed")
    bindings = tuple(
        (
            binding
            for binding in product_policy.bindings
            if binding.plugin_id == opt_in.plugin_id
            and binding.source_identity
            == selected.snapshot.package_revision.package_source_identity
            and (binding.artifact_digest == opt_in.artifact_digest)
            and (binding.source_trust_class == source_trust_class)
        )
    )
    if len(bindings) != 1:
        raise error_type(error_prefix + "product_binding_changed")
    admitted = bindings[0].worker_admission
    if (
        admitted is None
        or admitted.contribution_id != opt_in.contribution_id
        or admitted.owner_id != opt_in.owner_id
        or (admitted.native_platform != opt_in.native_platform)
    ):
        raise error_type(error_prefix + "product_binding_changed")
    candidate = verify_product_selected_worker_candidate(
        selected,
        contribution_id=opt_in.contribution_id,
        native_platform=admitted.native_platform,
    )
    if candidate.owner_id != opt_in.owner_id:
        raise error_type(error_prefix + "product_binding_changed")
    session_route: Literal["new", "selected"]
    if session_discovery is None:
        session_route = "new"
        locator_fingerprint = None
        locator_revision = "new-session-v1"
    else:
        if (
            not isinstance(session_discovery, SessionDiscoveryMetadata)
            or not session_discovery.resumable
            or session_discovery.conflicts
            or (session_discovery.locator.conversation_id != session_id)
        ):
            raise error_type(error_prefix + "session_invalid")
        session_route = "selected"
        locator_fingerprint = session_fingerprint(session_discovery)
        locator_revision = session_discovery.locator.revision
    runtime.assert_selected_plugin_manifest_current(selected)
    native_profile_id = native_profiles[opt_in.native_platform]
    closure = ProductWorkerActivationPolicyV1.native_policy_closure_fingerprint(
        native_profile_catalog_revision=native_closure.native_profile_catalog_revision,
        native_profile_id=native_profile_id,
        payload_sha256=candidate.executable_digest,
        containment_launcher_sha256=native_closure.containment_launcher_digest,
        containment_profile_sha256=native_closure.containment_profile_digest,
    )
    policy_revision = sha256(
        canonical_json_bytes(
            {
                "packagePolicy": product_policy.authority_revision,
                "optIn": opt_in.to_dict(),
                "nativeClosure": native_closure.to_dict(),
            }
        )
    ).hexdigest()
    return activation_policy(
        product_runtime_id=product_runtime_id,
        product_scope_id=session_scope_id(session_id),
        session_id=session_id,
        session_route=session_route,
        selected_locator_fingerprint=locator_fingerprint,
        selected_locator_revision=locator_revision,
        plugin_id=candidate.plugin_id,
        plugin_revision_digest=selected.snapshot.root_ref.artifact_digest,
        contribution_id=candidate.contribution_id,
        reservation_fingerprint=candidate.reservation_fingerprint,
        declaration_fingerprint=candidate.declaration_fingerprint,
        worker_configuration_fingerprint=candidate.worker_configuration_fingerprint,
        declared_required=candidate.declared_required,
        effective_required=candidate.declared_required or opt_in.require_worker,
        allowed_contribution_ids=(candidate.contribution_id,),
        owner_selection_generation=opt_in.owner_selection_generation,
        native_profile_id=native_profile_id,
        native_profile_catalog_revision=native_closure.native_profile_catalog_revision,
        allowed_native_profile_ids=(native_profile_id,),
        expected_native_policy_closure_fingerprint=closure,
        product_policy_revision=policy_revision,
        kill_switch_generation=opt_in.kill_switch_generation,
    )


def capture_worker_startup_selection(
    *,
    runtime: PackageProductRuntimeBindingV1,
    plugin_id: str,
    receipt: ProductWorkerActivationReceiptV1,
    existing_startup: dict[str, object] | None,
    max_files: int,
    max_total_bytes: int,
    failure: Callable[[str], RuntimeError],
) -> PackageProductSelectedPluginManifestV1:
    selected_worker = runtime.capture_selected_plugin_manifest_for(
        plugin_id, max_files=max_files, max_total_bytes=max_total_bytes
    )

    if (
        selected_worker.snapshot.root_ref.artifact_digest
        != receipt.policy.plugin_revision_digest
    ):
        raise failure("selection_changed")

    if existing_startup is not None:
        worker = existing_startup.get("workerSelection")
        expected_revision = {
            "pluginId": plugin_id,
            "packageRevisionFingerprint": plugin_package_revision_fingerprint(
                selected_worker.snapshot.package_revision
            ),
            "instanceRevisionRef": selected_worker.snapshot.instance_revision_ref.to_dict(),
        }
        revisions = existing_startup.get("selectedRevisions")
        if (
            not isinstance(worker, dict)
            or not isinstance(revisions, list)
            or expected_revision not in revisions
            or (worker.get("pluginId") != receipt.policy.plugin_id)
            or (
                worker.get("productPolicyRevision")
                != receipt.policy.product_policy_revision
            )
            or (worker.get("nativeProfileId") != receipt.policy.native_profile_id)
            or (
                worker.get("selectedLocatorRevision")
                != receipt.policy.selected_locator_revision
            )
            or (
                worker.get("selectedLocatorFingerprint")
                != receipt.policy.selected_locator_fingerprint
            )
            or (
                worker.get("workerConfigurationFingerprint")
                != receipt.policy.worker_configuration_fingerprint
            )
        ):
            raise failure("startup_selection_changed")

    return selected_worker


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


class _ProductWorkerBasePolicyGuard(Protocol):
    @property
    def policy_revision(self) -> str: ...
    def assert_current(self) -> None: ...


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

    _receipt_factory_label: ClassVar[str]
    _receipt_session_label: ClassVar[str]
    _receipt_manifest_max_files: ClassVar[int]
    _receipt_manifest_max_bytes: ClassVar[int]

    @staticmethod
    def _receipt_session_type() -> type[_AttachedTranscriptReadPort]:
        raise NotImplementedError

    @staticmethod
    def _receipt_discovery_type() -> Callable[..., ProductSessionDiscoveryReadPort]:
        raise NotImplementedError

    _provider_native_platform: ClassVar[Literal["linux-x86_64", "windows-amd64"]]

    @contextmanager
    def serialized_admission(self) -> Iterator[None]:
        raise NotImplementedError("the existing platform admission owner is required")
        yield

    @property
    def product_runtime(self) -> PackageProductRuntimeBindingV1:
        raise NotImplementedError("the existing platform runtime owner is required")

    def current_selected_manifest(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> PackageProductSelectedPluginManifestV1:
        raise NotImplementedError("the existing manifest owner is required")

    def current_selected_payload(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> PayloadT:
        raise NotImplementedError("the existing payload owner is required")

    def prepare_provider_candidate(
        self,
        *,
        receipt: ProductWorkerActivationReceiptV1,
        definition: CapabilityDefinition,
        provider: CapabilityBundleProvider,
        base_policy_binding: _ProductWorkerBasePolicyGuard | None = None,
        error_type: type[RuntimeError],
        error_prefix: str,
    ) -> CapabilityProviderCandidateEnvelope:
        with self.serialized_admission():
            if base_policy_binding is not None:
                base_policy_binding.assert_current()
            if self.current_witness(receipt) != receipt.authority_witness:
                raise error_type(error_prefix + "_receipt_stale")
            selected = self.current_selected_manifest(receipt)
            payload = self.current_selected_payload(receipt)
            native_platform = type(self)._provider_native_platform
            candidate = verify_product_selected_worker_candidate(
                selected,
                contribution_id=receipt.policy.contribution_id,
                native_platform=native_platform,
            )
            trust = selected.source_trust_snapshot
            snapshot = selected.snapshot
            policy = receipt.policy
            if (
                trust is None
                or not trust.trusted
                or trust.source_trust_class != "local-worker-candidate"
                or (candidate.plugin_id != policy.plugin_id)
                or (candidate.contribution_id != policy.contribution_id)
                or (candidate.owner_id != self.current_worker_owner_id(receipt))
                or (candidate.owner_id != definition.owner_id)
                or (candidate.reservation_fingerprint != policy.reservation_fingerprint)
                or (candidate.declaration_fingerprint != policy.declaration_fingerprint)
                or (
                    candidate.worker_configuration_fingerprint
                    != policy.worker_configuration_fingerprint
                )
                or (candidate.declared_required != policy.declared_required)
                or (candidate.executable_digest != payload.digest)
                or (candidate.executable_size != len(payload.body))
                or (snapshot.root_ref.artifact_digest != policy.plugin_revision_digest)
                or (snapshot.installation_key.product_id != policy.product_id)
                or (provider.capability_id != definition.capability_id)
                or (provider.source_id != f"plugin:{candidate.plugin_id}")
                or provider.requirements
                or provider.required_authorities
                or (len(selected.declaration_documents) != 1)
            ):
                raise error_type(error_prefix + "_selection_mismatch")
            spec = CapabilityWorkerProviderBindingSpec(
                plugin_id=candidate.plugin_id,
                contribution_id=candidate.contribution_id,
                capability_id=definition.capability_id,
                owner_id=definition.owner_id,
                package_content_digest=snapshot.package_revision.package_content_digest,
                dependency_lock_digest=snapshot.package_revision.dependency_lock_digest,
                manifest_digest=candidate.manifest_digest,
                reservation_fingerprint=candidate.reservation_fingerprint,
                declaration_fingerprint=candidate.declaration_fingerprint,
                worker_configuration_fingerprint=candidate.worker_configuration_fingerprint,
                executable_digest=candidate.executable_digest,
                executable_size=candidate.executable_size,
                declared_required=candidate.declared_required,
                native_platform=native_platform,
            )
            result = CapabilityProviderCandidateEnvelope(
                definition=definition,
                provider=provider,
                binding_spec=spec,
                plugin_candidate_fingerprint=receipt.fingerprint,
                declaration_fingerprint=candidate.declaration_fingerprint,
                declaration_evidence_fingerprint=selected.declaration_documents[0][
                    1
                ].bytes_digest,
                product_id=policy.product_id,
                scope_id=f"session:{policy.session_id}",
                product_policy_revision=base_policy_binding.policy_revision
                if base_policy_binding is not None
                else policy.product_policy_revision,
                instance_revision_ref=snapshot.instance_revision_ref,
                package_source_identity=trust.package_source_identity,
                source_trust_class=trust.source_trust_class,
                source_trust_policy_revision=trust.source_trust_policy_revision,
                source_trusted=trust.trusted,
                allowed_authority_ceiling=(),
            )
            if self.current_witness(receipt) != receipt.authority_witness:
                raise error_type(error_prefix + "_receipt_stale")
            return result

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


class _WorkerBaseCompilationFacts(Protocol):
    @property
    def selected_manifest(self) -> PackageProductSelectedPluginManifestV1: ...
    @property
    def selected_capability_manifests(
        self,
    ) -> tuple[PackageProductSelectedPluginManifestV1, ...]: ...
    @property
    def selected_external_data_manifests(
        self,
    ) -> tuple[PackageProductSelectedPluginManifestV1, ...]: ...


class _ProductWorkerBaseCompositionPolicyMethods(Generic[PayloadT]):
    """Original base selections and Worker receipt rejoined under one gate."""

    __slots__ = ()
    base: _WorkerBaseCompilationFacts
    receipt_owner: _ProductWorkerReceiptAuthority[PayloadT]
    receipt: ProductWorkerActivationReceiptV1

    @staticmethod
    def _base_policy_failure(code: str) -> RuntimeError:
        raise NotImplementedError

    def assert_current(self) -> None:
        """Recheck every base selection and the Worker under one Product gate."""
        with self.receipt_owner.serialized_admission():
            try:
                runtime = self.receipt_owner.product_runtime
                selections = (
                    self.base.selected_manifest,
                    *self.base.selected_capability_manifests,
                    *self.base.selected_external_data_manifests,
                )
                for selected in selections:
                    runtime.assert_selected_plugin_manifest_current(selected)
                    current = runtime.capture_selected_plugin_manifest_for(
                        selected.manifest.name,
                        max_files=64,
                        max_total_bytes=1024 * 1024,
                    )
                    if current != selected:
                        raise self._base_policy_failure("base_selection_stale")
            except (
                PackagePhysicalStagingError,
                PackageProductRuntimeActivationError,
                PackageProductRuntimeReadError,
            ) as exc:
                raise self._base_policy_failure("base_selection_stale") from exc
            if (
                self.receipt_owner.current_witness(self.receipt)
                != self.receipt.authority_witness
            ):
                raise self._base_policy_failure("receipt_stale")


class _ProductWorkerCapabilityAuthority(Generic[PayloadT]):
    """Product freshness and exact facet-owner binding on the original object."""

    @staticmethod
    def _capability_failure(code: str) -> RuntimeError:
        raise NotImplementedError

    def _initialize_capability(
        self,
        *,
        receipt_owner: _ProductWorkerReceiptAuthority[PayloadT],
        receipt: ProductWorkerActivationReceiptV1,
        request: ManagedWorkerLaunchRequestV1,
        binding: CapabilityWorkerBindingV1,
        owner_policy: CapabilityWorkerFacetOwnerPolicy,
    ) -> None:
        identity = request.identity
        authority = binding.authority
        if (
            identity.plugin_id != receipt.policy.plugin_id
            or identity.plugin_revision_digest != receipt.policy.plugin_revision_digest
            or identity.contribution_id != receipt.policy.contribution_id
            or (identity.product_id != receipt.policy.product_id)
            or (identity.scope_id != receipt.policy.product_scope_id)
            or (identity.owner_generation != receipt.policy.owner_selection_generation)
            or (
                identity.declaration_fingerprint
                != receipt.policy.declaration_fingerprint
            )
            or (identity.plugin_id != binding.plugin_id)
            or (identity.contribution_id != binding.contribution_id)
            or (identity.product_id != binding.product_id)
            or (identity.scope_id != binding.scope_id)
            or (identity.owner_id != binding.owner_id)
            or (identity.plugin_revision_digest != authority.plugin_revision_digest)
            or (identity.declaration_fingerprint != authority.declaration_fingerprint)
            or (identity.owner_generation != authority.owner_generation)
            or (
                receipt.policy.product_policy_revision
                != authority.product_policy_revision
            )
            or (owner_policy.binding != binding)
        ):
            raise self._capability_failure("capability_identity_mismatch")
        self._receipt_owner = receipt_owner
        self._receipt = receipt
        self._request = request
        self._binding = binding
        self._owner_policy = owner_policy
        self.current_authority()

    @property
    def binding(self) -> CapabilityWorkerBindingV1:
        return self._binding

    def issue_read_only_facet(
        self, *, capability_id: str, facet_id: str
    ) -> tuple[CapabilityWorkerFacetGrantV1, Callable[[object], object]]:
        """Issue one owner-approved facet grant and its fixed result decoder."""
        current = self.current_authority()
        if current != self._binding.authority:
            raise self._capability_failure("capability_owner_authority_stale")
        try:
            return self._owner_policy.issue_read_only_facet(
                capability_id=capability_id, facet_id=facet_id
            )
        except CapabilityWorkerFacetOwnerError as exc:
            raise self._capability_failure("capability_facet_not_approved") from exc

    def current_authority(self) -> CapabilityWorkerAuthorityV1:
        """Refuse changed Product selection before exposing owner authority."""
        self._request.validate_current()
        if (
            self._receipt_owner.current_witness(self._receipt)
            != self._receipt.authority_witness
        ):
            raise self._capability_failure("receipt_stale")
        if (
            self._receipt_owner.current_worker_owner_id(self._receipt)
            != self._binding.owner_id
        ):
            raise self._capability_failure("capability_owner_changed")
        try:
            authority = self._owner_policy.current_authority()
        except CapabilityWorkerFacetOwnerError as exc:
            raise self._capability_failure(
                "capability_owner_authority_unavailable"
            ) from exc
        if not isinstance(authority, CapabilityWorkerAuthorityV1):
            raise self._capability_failure("capability_owner_authority_invalid")
        return authority


class _PosixWorkerProductReceiptAuthority(
    ReceiptHistory[R],
    _ProductWorkerReceiptAuthority[PayloadT],
    Generic[R, PayloadT, MaterialT],
):
    _provider_native_platform = "linux-x86_64"
    _product: PosixLocalWheelProductSessionOwner
    _native_closure_reader: ProductNativeClosureReadPort
    _session_discovery_reader: ProductSessionDiscoveryReadPort | None
    _native_reader_type: type[ProductNativeLaunchReadPort[MaterialT]]
    _native_error: ClassVar[type[Exception]]
    _native_profile_id: ClassVar[str]

    @staticmethod
    def _receipt_opt_in_journal_type() -> Callable[..., CurrentOptIn]:
        raise NotImplementedError

    @classmethod
    def _open_selected(
        cls,
        *,
        product_owner: PosixLocalWheelProductSessionOwner,
        runtime: PackageProductRuntimeBindingV1,
        plugin_id: str,
        native_closure_reader: ProductNativeClosureReadPort,
        transcript_directory: AgentTranscriptDirectoryRuntime,
        session_manager: _AttachedTranscriptReadPort,
        active_session: bool = False,
    ) -> Self:
        """Bind one Product candidate to its exact attached Session owner.

        An attached active Session owns subsequent transcript appends. Detached
        selection retains the discovery locator revision as an exact snapshot.
        """

        if not isinstance(product_owner, PosixLocalWheelProductSessionOwner):
            raise TypeError(f"{cls._receipt_factory_label} requires a Product owner")
        if not isinstance(runtime, PackageProductRuntimeBindingV1):
            raise TypeError(
                f"{cls._receipt_factory_label} requires an active Product runtime"
            )
        if (
            not isinstance(plugin_id, str)
            or not plugin_id
            or plugin_id != plugin_id.strip()
        ):
            raise ValueError(f"{cls._receipt_factory_label} Plugin identity is invalid")
        if runtime.session_id is None:
            raise ValueError(
                f"{cls._receipt_factory_label} Session identity is unavailable"
            )
        if not isinstance(transcript_directory, AgentTranscriptDirectoryRuntime):
            raise TypeError(
                f"{cls._receipt_factory_label} requires a Transcript directory owner"
            )
        if not isinstance(session_manager, cls._receipt_session_type()):
            raise TypeError(
                f"{cls._receipt_factory_label} requires a {cls._receipt_session_label}"
            )
        selected_session_file = _capture_selected_worker_session_file(
            session_manager=session_manager,
            transcript_directory=transcript_directory,
            runtime=runtime,
            product_owner=product_owner,
            invalid_owner=f"{cls._receipt_factory_label} selected Session owner changed",
        )
        root_reader = runtime._selected_root_reader
        manifest_reader = runtime._selected_manifest_reader
        if not isinstance(root_reader, PackageProductSelectedRootReader):
            raise ValueError(
                f"{cls._receipt_factory_label} Product runtime owners changed"
            )
        bound_root = cast(PackageProductSelectedRootReader, root_reader)
        if (
            getattr(manifest_reader, "root_reader", None) is not bound_root
            or bound_root.desired_state is not product_owner.desired_state
            or bound_root.bindings is not product_owner.gc_bindings
            or bound_root.gc_gate is not product_owner.gc_gate
            or bound_root.product_id != product_owner.policy.product_id
            or bound_root.scope_id != product_owner.policy.project_scope_id
        ):
            raise ValueError(
                f"{cls._receipt_factory_label} Product runtime owners changed"
            )
        selected = runtime.capture_selected_plugin_manifest_for(
            plugin_id,
            max_files=cls._receipt_manifest_max_files,
            max_total_bytes=cls._receipt_manifest_max_bytes,
        )
        opt_in = cls._receipt_opt_in_journal_type()(
            product_owner.state_root / "worker-opt-in.jsonl",
            scope_id=product_owner.policy.project_scope_id,
            gc_gate=product_owner.gc_gate,
            store_id=product_owner.epoch_runtime.registry.store_id,
        )
        discovery = cls._receipt_discovery_type()(
            directory=transcript_directory,
            gc_gate=product_owner.gc_gate,
            session_id=runtime.session_id,
            selected_session_file=selected_session_file,
            attached_session=session_manager if active_session else None,
        )
        return cast(Callable[..., Self], cls)(
            product_owner=product_owner,
            runtime=runtime,
            selected=selected,
            opt_in_journal=opt_in,
            native_closure_reader=native_closure_reader,
            session_discovery_reader=discovery,
        )

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
    _provider_native_platform = "windows-amd64"
    _product: WindowsLocalWheelProductSessionOwner
    _journal: WindowsReceiptRecords[R]
    _native: ProductNativeClosureReadPort
    _session_discovery_reader: ProductSessionDiscoveryReadPort | None

    @classmethod
    def _open_selected(
        cls,
        *,
        product_owner: WindowsLocalWheelProductSessionOwner,
        runtime: PackageProductRuntimeBindingV1,
        plugin_id: str,
        transcript_directory: AgentTranscriptDirectoryRuntime,
        session_manager: _AttachedTranscriptReadPort,
        active_session: bool = False,
    ) -> Self:
        """Bind an exact selected Windows Worker to its persisted attached Session."""

        if type(product_owner) is not WindowsLocalWheelProductSessionOwner:
            raise TypeError(f"{cls._receipt_factory_label} requires a Product owner")
        if type(runtime) is not PackageProductRuntimeBindingV1:
            raise TypeError(
                f"{cls._receipt_factory_label} requires an active Product runtime"
            )
        if (
            not isinstance(plugin_id, str)
            or not plugin_id
            or plugin_id != plugin_id.strip()
        ):
            raise ValueError(f"{cls._receipt_factory_label} Plugin identity is invalid")
        if not isinstance(transcript_directory, AgentTranscriptDirectoryRuntime):
            raise TypeError(
                f"{cls._receipt_factory_label} requires a Transcript directory owner"
            )
        if not isinstance(session_manager, cls._receipt_session_type()):
            raise TypeError(
                f"{cls._receipt_factory_label} requires a {cls._receipt_session_label}"
            )
        selected_session_file = _capture_selected_worker_session_file(
            session_manager=session_manager,
            transcript_directory=transcript_directory,
            runtime=runtime,
            product_owner=product_owner,
            invalid_owner=f"{cls._receipt_factory_label} selected Session owner changed",
        )
        product_owner.assert_session_runtime_current(runtime)
        selected = runtime.capture_selected_plugin_manifest_for(
            plugin_id,
            max_files=cls._receipt_manifest_max_files,
            max_total_bytes=cls._receipt_manifest_max_bytes,
        )
        discovery = cls._receipt_discovery_type()(
            directory=transcript_directory,
            gc_gate=product_owner.gc_gate,
            session_id=cast(str, runtime.session_id),
            selected_session_file=selected_session_file,
            attached_session=session_manager if active_session else None,
        )
        return cast(Callable[..., Self], cls)(
            product=product_owner,
            runtime=runtime,
            selected=selected,
            session_discovery_reader=discovery,
        )

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


OptInProjectionT = TypeVar("OptInProjectionT")


class _ProductWorkerOptInPlanning(Generic[P]):
    _opt_in_error: ClassVar[type[RuntimeError]]
    _error_prefix: ClassVar[str]
    _opt_in_type: ClassVar[type[_OptInValue]]

    def _plan_allow(
        self,
        previous: _OptInDecisionMethods | None,
        *,
        binding: PackageProductLocalWheelBindingV1,
        admission: PackageProductLocalWorkerAdmissionV1,
        plugin_id: str,
        operation_id: str,
        expected_generation: int,
        require_worker: bool,
    ) -> P:
        """Validate a current allow or return the exact prior opt-in for replay."""
        generation = 0 if previous is None else previous.generation
        kill_generation = 0 if previous is None else previous.kill_switch_generation
        if (
            previous is not None
            and previous.operation_id == operation_id
            and (previous.action == "allow")
            and (previous.generation == expected_generation + 1)
        ):
            prior_opt_in = cast("ProductWorkerOptInFacts | None", previous.opt_in)
            if (
                prior_opt_in is None
                or prior_opt_in.plugin_id != plugin_id
                or prior_opt_in.contribution_id != admission.contribution_id
                or (prior_opt_in.owner_id != admission.owner_id)
                or (prior_opt_in.artifact_digest != binding.artifact_digest)
                or (prior_opt_in.native_platform != admission.native_platform)
                or (prior_opt_in.require_worker != require_worker)
            ):
                raise self._opt_in_error(
                    self._error_prefix + "opt_in_operation_conflict"
                )
            return cast(P, prior_opt_in)
        if generation != expected_generation:
            raise self._opt_in_error(self._error_prefix + "opt_in_stale")
        return cast(Callable[..., P], type(self)._opt_in_type)(
            plugin_id=plugin_id,
            contribution_id=admission.contribution_id,
            owner_id=admission.owner_id,
            artifact_digest=binding.artifact_digest,
            native_platform=admission.native_platform,
            owner_selection_generation=generation + 1,
            kill_switch_generation=kill_generation,
            require_worker=require_worker,
        )


class _PosixWorkerProductOptInAuthority(
    _ProductWorkerOptInPlanning[P], Generic[D, OptInProjectionT, P]
):
    _product: PosixLocalWheelProductSessionOwner
    _journal: OptInJournal[D, OptInProjectionT, P]
    _product_id: ClassVar[str]
    _requiredness_error: ClassVar[str]
    _selection_error_prefix: ClassVar[str]

    def _current_native_closure(self) -> ProductWorkerNativeClosureFacts:
        raise NotImplementedError("the installed native owner is required")

    def current(self, plugin_id: str) -> D | None:
        return self._journal.current(plugin_id)

    def allow(
        self,
        *,
        plugin_id: str,
        operation_id: str,
        expected_generation: int,
        require_worker: bool,
    ) -> D:
        """Pin the currently enabled candidate and approved native release."""
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
            closure = self._current_native_closure()
            if closure.native_platform != admission.native_platform:
                raise self._opt_in_error(
                    self._error_prefix + "opt_in_native_platform_changed"
                )
            previous = self._journal.current(plugin_id)
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
                plugin_id=plugin_id,
                operation_id=operation_id,
                expected_generation=expected_generation,
                action="allow",
                opt_in=opt_in,
            )

    def revoke(
        self, *, plugin_id: str, operation_id: str, expected_generation: int
    ) -> D:
        """Revoke even when the selected candidate or native bytes disappeared."""
        with self._product.gc_gate.guard(require_write=True):
            self._product.assert_root_gc_authority_current()
            return self._journal.change(
                plugin_id=plugin_id,
                operation_id=operation_id,
                expected_generation=expected_generation,
                action="revoke",
                opt_in=None,
            )


class _WindowsWorkerProductOptInAuthority(
    _ProductWorkerOptInPlanning[P], Generic[D, P]
):
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


class _GateJournalAppender(Protocol):
    def append(
        self,
        *,
        phase: Literal["intent", "bound"],
        attempt_id: str,
        worker_identity_fingerprint: str,
        receipt_fingerprint: str,
        policy_fingerprint: str,
        scope_id: str,
        native_closure_digest: str,
        identity: WorkerNativeProcessIdentityV1 | None = None,
    ) -> object: ...


class _GateClosureDocument(Protocol):
    def to_dict(self) -> dict[str, object]: ...


class _StartGateReceiptAuthority(Protocol):
    @property
    def product_owner(self) -> PosixLocalWheelProductSessionOwner: ...
    def current_witness(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> ActivationWitness: ...
    def current_native_launch_material(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> ProductWorkerNativeLaunchMaterialFacts: ...


class PosixProductWorkerStartGate:
    """Original pipe/Journal/release transaction; no additional custody state."""

    _error_type: type[RuntimeError]
    _error_prefix: str
    _journal_type: Callable[[PosixLocalWheelProductSessionOwner], _GateJournalAppender]
    _receipt_owner: _StartGateReceiptAuthority

    def _initialize(
        self,
        *,
        receipt_owner: _StartGateReceiptAuthority,
        receipt: ProductWorkerActivationReceiptV1,
        worker_request: ManagedWorkerLaunchRequestV1,
        attempt_id: str,
    ) -> None:
        _require_exact_binding(receipt=receipt, worker_request=worker_request)
        if attempt_id != worker_request.identity.attempt_id:
            raise self._error_type(self._error_prefix + "_attempt_mismatch")
        product = receipt_owner.product_owner
        self._read_fd = -1
        self._write_fd = -1
        self._released = False
        self._receipt_owner = receipt_owner
        self._receipt = receipt
        self._worker_identity_fingerprint = worker_request.identity.fingerprint
        self._attempt_id = attempt_id
        self._journal = self._journal_type(product)
        with product.gc_gate.guard(require_write=True):
            self._recheck()
            self._native_closure_digest = self._current_closure_digest()
            read_fd, write_fd = os.pipe2(os.O_CLOEXEC)
            self._read_fd, self._write_fd = (read_fd, write_fd)
            try:
                os.set_blocking(write_fd, False)
                self._journal.append(
                    phase="intent",
                    attempt_id=attempt_id,
                    worker_identity_fingerprint=self._worker_identity_fingerprint,
                    receipt_fingerprint=receipt.fingerprint,
                    policy_fingerprint=receipt.policy.fingerprint,
                    scope_id=receipt.policy.product_scope_id,
                    native_closure_digest=self._native_closure_digest,
                )
            except BaseException:
                self.close()
                raise

    @property
    def start_gate_read_fd(self) -> int:
        if self._read_fd < 0 or self._write_fd < 0 or self._released:
            raise self._error_type(self._error_prefix + "_closed")
        return self._read_fd

    @property
    def receipt_owner(
        self,
    ) -> _StartGateReceiptAuthority:
        return self._receipt_owner

    @property
    def receipt_fingerprint(self) -> str:
        return self._receipt.fingerprint

    @property
    def worker_identity_fingerprint(self) -> str:
        return self._worker_identity_fingerprint

    @property
    def attempt_id(self) -> str:
        return self._attempt_id

    def release(self, witness: WorkerGatedStartWitnessV1) -> None:
        """Persist exact native identity before allowing the captured child to exec."""
        if self._read_fd < 0 or self._write_fd < 0 or self._released:
            raise self._error_type(self._error_prefix + "_closed")
        try:
            with self._receipt_owner.product_owner.gc_gate.guard(require_write=True):
                self._recheck()
                if self._current_closure_digest() != self._native_closure_digest:
                    raise self._error_type(
                        self._error_prefix + "_native_closure_changed"
                    )
                if type(witness) is not WorkerGatedStartWitnessV1:
                    raise self._error_type(self._error_prefix + "_witness_invalid")
                gate = os.fstat(self._read_fd)
                if (witness.gate_device, witness.gate_inode) != (
                    gate.st_dev,
                    gate.st_ino,
                ):
                    raise self._error_type(self._error_prefix + "_child_mismatch")
                self._journal.append(
                    phase="bound",
                    attempt_id=self._attempt_id,
                    worker_identity_fingerprint=self._worker_identity_fingerprint,
                    receipt_fingerprint=self._receipt.fingerprint,
                    policy_fingerprint=self._receipt.policy.fingerprint,
                    scope_id=self._receipt.policy.product_scope_id,
                    native_closure_digest=self._native_closure_digest,
                    identity=witness.native_identity,
                )
                if os.write(self._write_fd, b"S") != 1:
                    raise self._error_type(self._error_prefix + "_release_failed")
                self._released = True
        finally:
            self.close()

    def close(self) -> None:
        for name in ("_write_fd", "_read_fd"):
            descriptor = getattr(self, name, -1)
            if descriptor >= 0:
                setattr(self, name, -1)
                os.close(descriptor)

    def _recheck(self) -> None:
        if (
            self._receipt_owner.current_witness(self._receipt)
            != self._receipt.authority_witness
        ):
            raise self._error_type(self._error_prefix + "_receipt_stale")

    def _current_closure_digest(self) -> str:
        material = self._receipt_owner.current_native_launch_material(self._receipt)
        return sha256(
            canonical_json_bytes(cast(_GateClosureDocument, material.closure).to_dict())
        ).hexdigest()
