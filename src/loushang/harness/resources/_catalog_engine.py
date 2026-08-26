"""Pure deterministic Resource Catalog v2 composition for RCP1 shadow use."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from loushang.harness.resources._catalog_records import (
    EmbeddedOemOrigin,
    ExtensionOutputOrigin,
    NativeHostOrigin,
    ResourceActivationPolicySnapshot,
    ResourceCandidateSummary,
    ResourceCatalogDiagnostic,
    ResourceCatalogSnapshot,
    ResourceEffectiveEntry,
    ResourceIdentity,
    ResourceKindMergePolicy,
    ResourceMergeDecision,
    ResourceMergePolicySnapshot,
    ResourceSourceSnapshot,
    VerifiedPluginResourceOrigin,
    build_merge_policy_snapshot,
    catalog_snapshot_fingerprint,
)

_SOURCE_PRIORITY = {
    "temporary": 0,
    "project_local": 1,
    "user_global": 2,
    "external_package": 3,
    "built_in": 4,
}


class CatalogCompositionError(ValueError):
    """The shadow Catalog input cannot form one valid deterministic proposal."""


def default_resource_merge_policy() -> ResourceMergePolicySnapshot:
    """Build the frozen first-party RCP1 kind-policy snapshot."""

    return build_merge_policy_snapshot(
        policy_revision="resource-merge-policy-v2-rcp3",
        kind_policies=(
            ResourceKindMergePolicy("asset", "permissive_exclusive"),
            ResourceKindMergePolicy("context", "ordered_additive"),
            ResourceKindMergePolicy("extension", "ordered_additive"),
            ResourceKindMergePolicy("method", "strict_exclusive"),
            ResourceKindMergePolicy("prompt", "strict_exclusive"),
            ResourceKindMergePolicy("skill", "strict_exclusive"),
            ResourceKindMergePolicy("source", "permissive_exclusive"),
            ResourceKindMergePolicy("theme", "permissive_exclusive"),
        ),
    )


def compose_resource_catalog(
    source_snapshots: Sequence[ResourceSourceSnapshot],
    *,
    catalog_generation: int,
    engine_binding_fingerprint: str,
    merge_policy: ResourceMergePolicySnapshot,
    activation_policy: ResourceActivationPolicySnapshot,
) -> ResourceCatalogSnapshot:
    """Compose source snapshots without discovery, body loading, or publication."""

    canonical_sources = tuple(
        sorted(source_snapshots, key=lambda snapshot: snapshot.snapshot_fingerprint)
    )
    source_fingerprints = tuple(
        snapshot.snapshot_fingerprint for snapshot in canonical_sources
    )
    if len(set(source_fingerprints)) != len(source_fingerprints):
        raise CatalogCompositionError(
            "One source snapshot entered the Catalog more than one source snapshot route."
        )

    candidates = tuple(
        sorted(
            (
                candidate
                for snapshot in canonical_sources
                for candidate in snapshot.candidate_summaries
            ),
            key=lambda candidate: candidate.canonical_sort_key(),
        )
    )
    candidate_fingerprints = [
        candidate.candidate_fingerprint for candidate in candidates
    ]
    if len(set(candidate_fingerprints)) != len(candidate_fingerprints):
        raise CatalogCompositionError(
            "One candidate entered through more than one source snapshot."
        )

    diagnostics = [
        diagnostic
        for snapshot in canonical_sources
        for diagnostic in snapshot.diagnostics
    ]
    diagnostics.extend(
        diagnostic for candidate in candidates for diagnostic in candidate.diagnostics
    )

    grouped: dict[ResourceIdentity, list[ResourceCandidateSummary]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.identity].append(candidate)

    decisions: list[ResourceMergeDecision] = []
    effective_entries: list[ResourceEffectiveEntry] = []
    disabled_identities = frozenset(activation_policy.disabled_identities)
    model_disabled_identities = frozenset(
        activation_policy.model_invocation_disabled_identities
    )

    for identity in sorted(grouped):
        try:
            strategy = merge_policy.strategy_for(identity.resource_kind)
        except KeyError as exc:
            raise CatalogCompositionError(
                f"No merge policy exists for Resource kind '{identity.resource_kind}'."
            ) from exc

        ordered = tuple(sorted(grouped[identity], key=_candidate_precedence_key))
        enabled = tuple(
            candidate
            for candidate in ordered
            if candidate.invocation_policy.enabled
            and candidate.identity not in disabled_identities
        )
        all_fingerprints = tuple(
            candidate.candidate_fingerprint for candidate in ordered
        )

        if not enabled:
            decisions.append(
                ResourceMergeDecision(
                    identity=identity,
                    candidate_fingerprints=all_fingerprints,
                    effective_candidate_fingerprints=(),
                    winner_candidate_fingerprint=None,
                    rejected=False,
                    policy_revision=merge_policy.policy_revision,
                    reason=(
                        "activation_disabled"
                        if identity in disabled_identities
                        else "no_enabled_candidates"
                    ),
                )
            )
            continue

        selected: tuple[ResourceCandidateSummary, ...]
        winner: ResourceCandidateSummary | None
        rejected = False
        if strategy == "strict_exclusive":
            top_rank = _SOURCE_PRIORITY[enabled[0].source_class]
            top_tier = tuple(
                candidate
                for candidate in enabled
                if _SOURCE_PRIORITY[candidate.source_class] == top_rank
            )
            if len(top_tier) > 1:
                selected = ()
                winner = None
                rejected = True
                reason = "same_precedence_conflict"
            else:
                selected = (enabled[0],)
                winner = enabled[0]
                reason = "source_precedence" if len(enabled) > 1 else "single_candidate"
        elif strategy == "permissive_exclusive":
            selected = (enabled[0],)
            winner = enabled[0]
            reason = (
                "precedence_and_tiebreak" if len(enabled) > 1 else "single_candidate"
            )
        elif strategy == "ordered_additive":
            selected = enabled
            winner = enabled[0]
            reason = (
                "all_enabled_candidates_active"
                if len(enabled) > 1
                else "single_candidate"
            )
        else:  # pragma: no cover - validated by ResourceKindMergePolicy
            raise CatalogCompositionError(
                f"Unsupported Resource merge strategy '{strategy}'."
            )

        selected_fingerprints = tuple(
            candidate.candidate_fingerprint for candidate in selected
        )
        decisions.append(
            ResourceMergeDecision(
                identity=identity,
                candidate_fingerprints=all_fingerprints,
                effective_candidate_fingerprints=selected_fingerprints,
                winner_candidate_fingerprint=(
                    winner.candidate_fingerprint if winner is not None else None
                ),
                rejected=rejected,
                policy_revision=merge_policy.policy_revision,
                reason=reason,
            )
        )
        if rejected:
            diagnostics.append(
                ResourceCatalogDiagnostic(
                    code="resource_collision",
                    reason=reason,
                    identity=identity,
                    details=(("candidate_count", str(len(enabled))),),
                )
            )
            continue

        assert winner is not None
        effective_entries.append(
            ResourceEffectiveEntry(
                identity=identity,
                candidate_fingerprints=selected_fingerprints,
                primary_candidate_fingerprint=winner.candidate_fingerprint,
                enabled=True,
                model_invocable=(
                    identity not in model_disabled_identities
                    and all(
                        candidate.invocation_policy.model_invocable
                        for candidate in selected
                    )
                ),
            )
        )
        if len(enabled) > 1 and strategy != "ordered_additive":
            diagnostics.append(
                ResourceCatalogDiagnostic(
                    code="resource_collision",
                    reason=reason,
                    identity=identity,
                    details=(
                        ("candidate_count", str(len(enabled))),
                        ("winner", winner.candidate_fingerprint),
                    ),
                )
            )

    canonical_entries = tuple(
        sorted(effective_entries, key=lambda entry: entry.canonical_sort_key())
    )
    canonical_decisions = tuple(
        sorted(decisions, key=lambda decision: decision.canonical_sort_key())
    )
    canonical_diagnostics = tuple(
        sorted(diagnostics, key=lambda diagnostic: diagnostic.canonical_sort_key())
    )
    complete = all(snapshot.complete for snapshot in canonical_sources)
    snapshot_fingerprint = catalog_snapshot_fingerprint(
        catalog_contract_version=2,
        catalog_generation=catalog_generation,
        engine_binding_fingerprint=engine_binding_fingerprint,
        source_generation_fingerprints=source_fingerprints,
        merge_policy_revision=merge_policy.policy_revision,
        activation_policy_fingerprint=activation_policy.activation_policy_fingerprint,
        candidate_summaries=candidates,
        effective_entries=canonical_entries,
        merge_decisions=canonical_decisions,
        diagnostics=canonical_diagnostics,
        complete=complete,
    )
    return ResourceCatalogSnapshot(
        catalog_contract_version=2,
        catalog_generation=catalog_generation,
        engine_binding_fingerprint=engine_binding_fingerprint,
        source_generation_fingerprints=source_fingerprints,
        merge_policy_revision=merge_policy.policy_revision,
        activation_policy_fingerprint=activation_policy.activation_policy_fingerprint,
        candidate_summaries=candidates,
        effective_entries=canonical_entries,
        merge_decisions=canonical_decisions,
        diagnostics=canonical_diagnostics,
        complete=complete,
        snapshot_fingerprint=snapshot_fingerprint,
    )


def _candidate_precedence_key(
    candidate: ResourceCandidateSummary,
) -> tuple[object, ...]:
    return (
        _SOURCE_PRIORITY[candidate.source_class],
        candidate.source_root_order,
        candidate.source_generation_ref.source_id,
        _content_origin_tiebreak(candidate),
        candidate.identity.resource_kind,
        candidate.identity.schema_id,
        candidate.identity.schema_version,
        candidate.identity.public_id,
        candidate.opaque_locator,
        candidate.candidate_fingerprint,
    )


def _content_origin_tiebreak(candidate: ResourceCandidateSummary) -> tuple[str, ...]:
    origin = candidate.content_origin
    if isinstance(origin, VerifiedPluginResourceOrigin):
        return (
            "verified_plugin_resource",
            origin.resource_contribution_id,
            origin.plugin_instance_revision_ref,
        )
    if isinstance(origin, NativeHostOrigin):
        return ("native_host", origin.host_root_handle_id)
    if isinstance(origin, EmbeddedOemOrigin):
        return (
            "embedded_oem",
            origin.embedded_collection_id,
            origin.embedded_revision,
        )
    if isinstance(origin, ExtensionOutputOrigin):
        return (
            "extension_output",
            origin.extension_id,
            origin.route_id,
        )
    raise CatalogCompositionError("Resource candidate has an unknown content origin.")


def effective_candidate_fingerprints(
    catalog: ResourceCatalogSnapshot,
) -> tuple[str, ...]:
    """Project all effective candidates in canonical entry/policy order."""

    return tuple(
        fingerprint
        for entry in catalog.effective_entries
        for fingerprint in entry.candidate_fingerprints
    )


__all__ = [
    "CatalogCompositionError",
    "compose_resource_catalog",
    "default_resource_merge_policy",
    "effective_candidate_fingerprints",
]
