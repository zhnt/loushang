"""Rejoin a live Coding Product Worker receipt to inert Provider admission facts.

The Capability owner still decides eligibility. This bridge does not grant a
facet, start a Worker, construct a graph binding, or change Session routing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from loushang.coding._base_product_composition import CodingBaseProductCompilation
from loushang.harness.capabilities.contracts import (
    CapabilityContractRange,
    CapabilityDefinition,
)
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderCandidateEnvelope,
    CapabilityWorkerProviderBindingSpec,
)
from loushang.harness.capabilities.providers import CapabilityBundleProvider
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeActivationError,
)
from loushang.harness.package_product.product_worker_candidate import (
    verify_product_selected_worker_candidate,
)
from loushang.harness.plugin_management.package_product import (
    PackageProductRuntimeReadError,
)
from loushang.harness.resources.packages.plugin_lifecycle.tree_transfer import (
    PackagePhysicalStagingError,
)
from loushang.harness.worker.product_activation import ProductWorkerActivationReceiptV1

from .package_product_worker_query_consumer import (
    CODING_WORKER_QUERY_DEFINITION,
    CODING_WORKER_QUERY_PROVIDER_ID,
)
from .package_product_worker_receipt import CodingWorkerProductReceiptOwner


class CodingWorkerProviderCandidateError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWorkerBaseCompositionPolicyBinding:
    """Product-owned bridge from a current base policy to one Worker receipt.

    The Worker activation policy remains distinct. Its receipt fingerprint is
    part of the Provider candidate, so changes to that policy stale admission.
    """

    base: CodingBaseProductCompilation = field(repr=False)
    receipt_owner: CodingWorkerProductReceiptOwner = field(repr=False)
    receipt: ProductWorkerActivationReceiptV1 = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.base, CodingBaseProductCompilation)
            or not isinstance(self.receipt_owner, CodingWorkerProductReceiptOwner)
            or not isinstance(self.receipt, ProductWorkerActivationReceiptV1)
            or self.base.plan.context.product_id != "coding"
            or self.base.plan.context.scope_id
            != f"session:{self.receipt.policy.session_id}"
            or self.base.selected_manifest.manifest.name != "coding.base"
            or self.receipt.policy.session_id
            != self.receipt_owner.product_runtime.session_id
            or self.receipt.policy.product_runtime_id
            != self.receipt_owner.product_runtime.product_runtime_id
        ):
            raise ValueError("Coding Worker base Product policy owners changed")
        self.assert_current()

    @property
    def policy_revision(self) -> str:
        return self.base.plan.context.policy_revision

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
                        raise CodingWorkerProviderCandidateError(
                            "coding_worker_provider_base_selection_stale"
                        )
            except (
                PackagePhysicalStagingError,
                PackageProductRuntimeActivationError,
                PackageProductRuntimeReadError,
            ) as exc:
                raise CodingWorkerProviderCandidateError(
                    "coding_worker_provider_base_selection_stale"
                ) from exc
            if (
                self.receipt_owner.current_witness(self.receipt)
                != self.receipt.authority_witness
            ):
                raise CodingWorkerProviderCandidateError(
                    "coding_worker_provider_receipt_stale"
                )


def coding_worker_query_capability_provider(plugin_id: str) -> CapabilityBundleProvider:
    """Describe the one Coding-owned query Provider selected by a Product receipt."""

    if not isinstance(plugin_id, str) or not plugin_id:
        raise ValueError("Coding Worker query Provider Plugin ID is invalid")
    return CapabilityBundleProvider(
        capability_id=CODING_WORKER_QUERY_DEFINITION.capability_id,
        provider_id=CODING_WORKER_QUERY_PROVIDER_ID,
        implementation_version=1,
        compatible_contract=CapabilityContractRange.exact(
            CODING_WORKER_QUERY_DEFINITION.contract_version
        ),
        facets=CODING_WORKER_QUERY_DEFINITION.facets,
        source_id=f"plugin:{plugin_id}",
        selection_rule="product-selected-canary",
    )


def prepare_coding_selected_worker_provider_candidate(
    *,
    receipt_owner: CodingWorkerProductReceiptOwner,
    receipt: ProductWorkerActivationReceiptV1,
    definition: CapabilityDefinition,
    provider: CapabilityBundleProvider,
    base_policy_binding: CodingWorkerBaseCompositionPolicyBinding | None = None,
) -> CapabilityProviderCandidateEnvelope:
    """Capture exact Product-selected bytes and form an owner-reviewable record."""

    if (
        not isinstance(receipt_owner, CodingWorkerProductReceiptOwner)
        or not isinstance(receipt, ProductWorkerActivationReceiptV1)
        or not isinstance(definition, CapabilityDefinition)
        or not isinstance(provider, CapabilityBundleProvider)
        or (
            base_policy_binding is not None
            and (
                not isinstance(
                    base_policy_binding, CodingWorkerBaseCompositionPolicyBinding
                )
                or base_policy_binding.receipt_owner is not receipt_owner
                or base_policy_binding.receipt != receipt
            )
        )
    ):
        raise TypeError("Coding Worker Provider candidate inputs are invalid")
    with receipt_owner.serialized_admission():
        if base_policy_binding is not None:
            base_policy_binding.assert_current()
        if receipt_owner.current_witness(receipt) != receipt.authority_witness:
            raise CodingWorkerProviderCandidateError(
                "coding_worker_provider_receipt_stale"
            )
        selected = receipt_owner.current_selected_manifest(receipt)
        payload = receipt_owner.current_selected_payload(receipt)
        candidate = verify_product_selected_worker_candidate(
            selected,
            contribution_id=receipt.policy.contribution_id,
            native_platform="linux-x86_64",
        )
        trust = selected.source_trust_snapshot
        snapshot = selected.snapshot
        policy = receipt.policy
        if (
            trust is None
            or not trust.trusted
            or trust.source_trust_class != "local-worker-candidate"
            or candidate.plugin_id != policy.plugin_id
            or candidate.contribution_id != policy.contribution_id
            or candidate.owner_id != receipt_owner.current_worker_owner_id(receipt)
            or candidate.owner_id != definition.owner_id
            or candidate.reservation_fingerprint != policy.reservation_fingerprint
            or candidate.declaration_fingerprint != policy.declaration_fingerprint
            or candidate.worker_configuration_fingerprint
            != policy.worker_configuration_fingerprint
            or candidate.declared_required != policy.declared_required
            or candidate.executable_digest != payload.digest
            or candidate.executable_size != len(payload.body)
            or snapshot.root_ref.artifact_digest != policy.plugin_revision_digest
            or snapshot.installation_key.product_id != policy.product_id
            or provider.capability_id != definition.capability_id
            or provider.source_id != f"plugin:{candidate.plugin_id}"
            or provider.requirements
            or provider.required_authorities
            or len(selected.declaration_documents) != 1
        ):
            raise CodingWorkerProviderCandidateError(
                "coding_worker_provider_selection_mismatch"
            )
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
            worker_configuration_fingerprint=(
                candidate.worker_configuration_fingerprint
            ),
            executable_digest=candidate.executable_digest,
            executable_size=candidate.executable_size,
            declared_required=candidate.declared_required,
            native_platform="linux-x86_64",
        )
        result = CapabilityProviderCandidateEnvelope(
            definition=definition,
            provider=provider,
            binding_spec=spec,
            plugin_candidate_fingerprint=receipt.fingerprint,
            declaration_fingerprint=candidate.declaration_fingerprint,
            declaration_evidence_fingerprint=(
                selected.declaration_documents[0][1].bytes_digest
            ),
            product_id=policy.product_id,
            scope_id=f"session:{policy.session_id}",
            product_policy_revision=(
                base_policy_binding.policy_revision
                if base_policy_binding is not None
                else policy.product_policy_revision
            ),
            instance_revision_ref=snapshot.instance_revision_ref,
            package_source_identity=trust.package_source_identity,
            source_trust_class=trust.source_trust_class,
            source_trust_policy_revision=trust.source_trust_policy_revision,
            source_trusted=trust.trusted,
            allowed_authority_ceiling=(),
        )
        if receipt_owner.current_witness(receipt) != receipt.authority_witness:
            raise CodingWorkerProviderCandidateError(
                "coding_worker_provider_receipt_stale"
            )
        return result


__all__ = [
    "CodingWorkerBaseCompositionPolicyBinding",
    "CodingWorkerProviderCandidateError",
    "coding_worker_query_capability_provider",
    "prepare_coding_selected_worker_provider_candidate",
]
