"""Prepare current authority readers for Session registration admission."""

from __future__ import annotations

from collections.abc import Callable

from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionAuthorityContext,
    ProductCompositionCompilation,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAuthority,
    OwnerContributionSnapshot,
)
from loushang.harness.resources.plugins.selection import (
    PluginSelection,
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityOwnerAuthorityGate,
)
from loushang.harness.session.product_composition_assembly import (
    ProductContributionOwnerBinding,
    ProductPluginCompositionAssembly,
)


def bind_compiled_registration_authority(
    compilation: ProductCompositionCompilation,
    owner_bindings: tuple[ProductContributionOwnerBinding, ...],
    *,
    clock: Callable[[], int],
    label: str,
) -> SessionCapabilityOwnerAuthorityGate:
    """Verify the complete owner inventory and read from its compiled context."""
    authorities = {item.owner_key: item.authority for item in owner_bindings}
    context = compilation.authority_context
    if tuple(item.authority.snapshot() for item in owner_bindings) != (
        context.owner_snapshots
    ):
        raise ValueError(f"{label} authority changed Product compilation")

    def read_policy(product_id: str, scope_id: str) -> str:
        if product_id != context.product_id or scope_id != context.scope_id:
            raise ValueError(f"{label} received another Product scope")
        return context.product_policy_revision

    return _bind_authority(
        context,
        context,
        authorities.get,
        read_policy,
        clock=clock,
        label=label,
    )


def bind_selected_registration_authority(
    selection: PluginSelection,
    assembly: ProductPluginCompositionAssembly,
    *,
    authority: OwnerContributionAuthority,
    product_id: str,
    scope_id: str,
    clock: Callable[[], int],
    label: str,
) -> SessionCapabilityOwnerAuthorityGate:
    """Read the selected plan and match the single live contribution owner."""
    trust_snapshots = selection.plan.source_trust_snapshots

    def select_owner(key: tuple[str, str, str]) -> OwnerContributionAuthority | None:
        owner_id, contribution_kind, requested_product_id = key
        policy = authority.policy
        if (
            owner_id != policy.owner_id
            or contribution_kind != policy.contribution_kind
            or requested_product_id != policy.product_id
        ):
            return None
        return authority

    def read_policy(requested_product_id: str, requested_scope_id: str) -> str:
        if requested_product_id != product_id or requested_scope_id != scope_id:
            raise ValueError(f"{label} received another Product scope")
        return selection.plan.context.policy_revision

    return _bind_authority(
        assembly.product_composition.authority_context,
        trust_snapshots,
        select_owner,
        read_policy,
        clock=clock,
        label=label,
    )


def _bind_authority(
    context: ProductCompositionAuthorityContext,
    trust_source: ProductCompositionAuthorityContext
    | tuple[PluginSourceTrustSnapshotV1, ...],
    select_owner: Callable[[tuple[str, str, str]], OwnerContributionAuthority | None],
    read_policy: Callable[[str, str], str],
    *,
    clock: Callable[[], int],
    label: str,
) -> SessionCapabilityOwnerAuthorityGate:
    def read_owner(
        owner_id: str, contribution_kind: str, product_id: str
    ) -> OwnerContributionSnapshot:
        authority = select_owner((owner_id, contribution_kind, product_id))
        if authority is None:
            raise ValueError(f"{label} reader received another owner")
        return authority.snapshot()

    def read_trust(plugin_id: str, source_identity: str) -> PluginSourceTrustSnapshotV1:
        # The compiled route reads its context; the selected route pins its plan snapshots.
        snapshots = (
            trust_source.trust_snapshots
            if isinstance(trust_source, ProductCompositionAuthorityContext)
            else trust_source
        )
        matches = tuple(
            item
            for item in snapshots
            if item.plugin_id == plugin_id
            and item.package_source_identity == source_identity
        )
        if len(matches) != 1:
            raise ValueError(f"{label} requires one trust snapshot")
        return matches[0]

    return SessionCapabilityOwnerAuthorityGate(
        authority_context=context,
        owner_snapshot_reader=read_owner,
        trust_snapshot_reader=read_trust,
        product_policy_revision_reader=read_policy,
        clock=clock,
    )
